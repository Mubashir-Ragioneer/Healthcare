# app/services/file_ingestor.py

import os
import uuid
import tempfile
from datetime import datetime
from fastapi import UploadFile, HTTPException
from pdf2image import convert_from_bytes
import pytesseract
import docx
from firecrawl import FirecrawlApp
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.services.vector_store import upsert_to_pinecone
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor
import asyncio
from app.core.logger import logger
from PIL import Image
import json
import pandas as pd
import io

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".jpeg", ".jpg", ".png", ".csv", ".xlsx", ".json"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]
urls = db["urls"]

# Firecrawl setup
firecrawl = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

# OpenAI embedding client
client = OpenAI(api_key=settings.OPENAI_API_KEY)
executor = ThreadPoolExecutor()

MAX_OCR_IMAGE_DIM = 3000  # px; you can adjust as needed

def downscale_if_needed(img):
    width, height = img.size
    if max(width, height) > MAX_OCR_IMAGE_DIM:
        scale = MAX_OCR_IMAGE_DIM / float(max(width, height))
        new_size = (int(width * scale), int(height * scale))
        logger.warning(f"Downscaled image from {img.size} to {new_size} for OCR.")
        return img.resize(new_size, Image.LANCZOS)
    return img

def chunk_text(text: str, chunk_size=400, overlap=50):
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


async def embed_text(text: str) -> list[float]:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(executor, lambda: client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ))
    return res.data[0].embedding


async def process_file(file: UploadFile, user_id: str) -> dict:
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit.")

        file_id = str(uuid.uuid4())
        text = ""

        # PDF
        if ext == ".pdf":
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(content)
                texts = []
                for img in images:
                    img = downscale_if_needed(img)
                    texts.append(pytesseract.image_to_string(img))
                text = "\n".join(texts)
                if len(text.strip()) < 100:
                    raise HTTPException(status_code=400, detail="PDF appears to contain no readable text.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"PDF OCR failed: {str(e)}")

        # DOCX
        elif ext == ".docx":
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                    tmp.write(content)
                    tmp.flush()
                    doc = docx.Document(tmp.name)
                text = "\n".join(para.text for para in doc.paragraphs)
                os.remove(tmp.name)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"DOCX parsing failed: {str(e)}")

        # TXT
        elif ext == ".txt":
            try:
                text = content.decode("utf-8")
            except Exception as e:
                raise HTTPException(status_code=400, detail="Unable to decode text file.")

        # IMAGE FILES (JPEG/JPG/PNG)
        elif ext in [".jpeg", ".jpg", ".png"]:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(content)
                    tmp.flush()
                    img = Image.open(tmp.name)
                    img = downscale_if_needed(img)
                    text = pytesseract.image_to_string(img)
                    os.remove(tmp.name)
                if not text.strip():
                    raise HTTPException(status_code=400, detail="Image contains no readable text.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Image OCR failed: {str(e)}")

        elif ext == ".csv":
            try:
                # Try reading as UTF-8; fallback to latin1 for legacy files
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(io.BytesIO(content), encoding="latin1")
                # Convert DataFrame to a readable text (limit rows/cols if needed)
                text = df.to_csv(index=False)
                if df.empty:
                    raise HTTPException(status_code=400, detail="CSV contains no data.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"CSV parsing failed: {str(e)}")

        # XLSX
        elif ext == ".xlsx":
            try:
                df = pd.read_excel(io.BytesIO(content))
                text = df.to_csv(index=False)
                if df.empty:
                    raise HTTPException(status_code=400, detail="XLSX contains no data.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"XLSX parsing failed: {str(e)}")

        
        elif ext == ".json":
            try:
                # Try decoding as UTF-8, fallback to latin1 for weird files
                try:
                    data = json.loads(content.decode("utf-8"))
                except UnicodeDecodeError:
                    data = json.loads(content.decode("latin1"))
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"JSON decoding failed: {str(e)}")

                # Convert the loaded JSON to a pretty string for text search/embedding
                text = json.dumps(data, ensure_ascii=False, indent=2)
                if not text.strip():
                    raise HTTPException(status_code=400, detail="JSON appears to be empty or invalid.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"JSON parsing failed: {str(e)}")
        # Add more types as elif branches here if you wish

        doc_record = {
            "file_id": file_id,
            "filename": file.filename,
            "user_id": user_id,
            "extension": ext,
            "file_data": content,
            "text": text,
            "source_type": "file",
            "created_at": datetime.utcnow()
        }

        result = await documents.insert_one(doc_record)
        logger.info(f"✅ Inserted document {result.inserted_id} into MongoDB (documents)")

        asyncio.create_task(upsert_to_pinecone(str(result.inserted_id), text))

        return {
            "document_id": str(result.inserted_id),
            "filename": file.filename,
            "text_snippet": text[:200],
            "chunk_count": None,
            "source_type": "file"
        }

    except Exception as e:
        logger.error(f"🔥 process_file failed: {e}")
        raise HTTPException(status_code=500, detail=f"File ingestion failed: {str(e)}")

async def process_url(url: str, user_id: str) -> dict:
    try:
        logger.info(f"🔍 Scraping URL: {url}")
        response = firecrawl.scrape_url(url=url, formats=["markdown"])
        content = response.markdown
        logger.info(f"✅ Scraped content ({len(content)} chars) from URL")

        doc_record = {
            "source": url,
            "user_id": user_id,
            "type": "url",
            "text": content,
            "source_type": "url",
            "created_at": datetime.utcnow()
        }

        result = await urls.insert_one(doc_record)
        logger.info(f"✅ Inserted URL {result.inserted_id} into MongoDB (urls)")

        # asyncio.create_task(upsert_to_pinecone(str(result.inserted_id), content))

        chunk_count = await upsert_to_pinecone(str(result.inserted_id), content)

        return {
            "document_id": str(result.inserted_id),
            "source": url,
            "text_snippet": content[:200],
            "chunk_count": chunk_count,
            "source_type": "url"
        }

    except Exception as e:
        logger.error(f"🔥 process_url failed: {e}")
        raise HTTPException(status_code=500, detail=f"URL ingestion failed: {str(e)}")
