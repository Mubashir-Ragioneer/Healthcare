import os
import uuid
import pytesseract
from datetime import datetime
from fastapi import UploadFile, HTTPException
from pdf2image import convert_from_bytes
import docx
from firecrawl import FirecrawlApp
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.db.pinecone import index
from openai import OpenAI

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]

# Firecrawl setup
firecrawl = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

# OpenAI client for embedding
client = OpenAI(api_key=settings.OPENAI_API_KEY)

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
    res = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return res.data[0].embedding

async def upsert_to_pinecone(doc_id: str, text: str, user_id: str):
    chunks = chunk_text(text)
    embeddings = [await embed_text(chunk) for chunk in chunks]

    vectors = [
        {
            "id": f"{doc_id}-{i}",
            "values": embedding,
            "metadata": {
                "chunk_text": chunk,
                "doc_id": doc_id,
                "user_id": user_id
            }
        }
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    index.upsert(vectors)
    print(f"📌 Upserted {len(vectors)} chunks to Pinecone for doc_id: {doc_id}")

async def process_file(file: UploadFile, user_id: str) -> dict:
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit.")

        file_id = str(uuid.uuid4())

        # Extract text
        text = ""
        if ext == ".pdf":
            try:
                images = convert_from_bytes(content)
                text = "\n".join(pytesseract.image_to_string(img) for img in images)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"PDF OCR failed: {str(e)}")
        elif ext == ".docx":
            try:
                with open("temp.docx", "wb") as temp_doc:
                    temp_doc.write(content)
                doc = docx.Document("temp.docx")
                text = "\n".join(para.text for para in doc.paragraphs)
                os.remove("temp.docx")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"DOCX parsing failed: {str(e)}")
        elif ext == ".txt":
            text = content.decode("utf-8")

        # Store in Mongo (no local storage)
        doc_record = {
            "file_id": file_id,
            "filename": file.filename,
            "user_id": user_id,
            "extension": ext,
            "file_data": content,
            "text": text,
            "created_at": datetime.utcnow()
        }

        result = await documents.insert_one(doc_record)
        print("✅ Inserted into MongoDB:", result.inserted_id)

        # Pinecone
        await upsert_to_pinecone(str(result.inserted_id), text, user_id)

        return {
            "document_id": str(result.inserted_id),
            "filename": file.filename,
            "text_snippet": text[:200]
        }

    except Exception as e:
        print("🔥 process_file failed:", str(e))
        raise HTTPException(status_code=500, detail=f"File ingestion failed: {str(e)}")


async def process_url(url: str, user_id: str) -> dict:
    try:
        print(f"🔍 Scraping URL: {url}")
        response = firecrawl.scrape_url(url=url, formats=["markdown"])
        content = response.markdown
        print(f"✅ Scraped content: {len(content)} characters")
    except Exception as e:
        print(f"❌ Firecrawl scrape failed: {e}")
        raise HTTPException(status_code=500, detail=f"URL scrape failed: {str(e)}")

    doc_record = {
        "source": url,
        "user_id": user_id,
        "type": "url",
        "text": content,
        "created_at": datetime.utcnow()
    }

    result = await documents.insert_one(doc_record)
    print("✅ Inserted Firecrawl content into MongoDB:", result.inserted_id)

    # Pinecone upsert
    await upsert_to_pinecone(str(result.inserted_id), content, user_id)

    return {
        "document_id": str(result.inserted_id),
        "source": url,
        "text_snippet": content[:200]
    }
