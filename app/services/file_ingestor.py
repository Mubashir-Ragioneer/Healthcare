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

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


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

        if ext == ".pdf":
            try:
                images = convert_from_bytes(content)
                text = "\n".join(pytesseract.image_to_string(img) for img in images)
                if len(text.strip()) < 100:
                    raise HTTPException(status_code=400, detail="PDF appears to contain no readable text.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"PDF OCR failed: {str(e)}")

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

        elif ext == ".txt":
            text = content.decode("utf-8")

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
