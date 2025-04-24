import os
import uuid
import pytesseract
from datetime import datetime
from fastapi import UploadFile, HTTPException
from pdf2image import convert_from_bytes
import aiofiles
import docx
from firecrawl import FirecrawlApp, ScrapeOptions
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]

# Firecrawl setup
firecrawl = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)

# Storage config
STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

async def process_file(file: UploadFile) -> dict:
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit.")

    file_id = str(uuid.uuid4())
    save_path = os.path.join(STORAGE_DIR, f"{file_id}{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # Extract text based on file type
    text = ""
    if ext == ".pdf":
        try:
            images = convert_from_bytes(content)
            text = "\n".join(pytesseract.image_to_string(img) for img in images)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF OCR failed: {str(e)}")
    elif ext == ".docx":
        doc = docx.Document(save_path)
        text = "\n".join(para.text for para in doc.paragraphs)
    elif ext == ".txt":
        text = content.decode("utf-8")

    doc_record = {
        "file_id": file_id,
        "filename": file.filename,
        "extension": ext,
        "path": save_path,
        "text": text,
        "created_at": datetime.utcnow()
    }

    result = await documents.insert_one(doc_record)
    print("✅ Inserted into MongoDB:", result.inserted_id)
    return {
        "document_id": str(result.inserted_id),
        "filename": file.filename,
        "text_snippet": text[:200]
    }
async def process_url(url: str) -> dict:
    try:
        response = firecrawl.scrape_url(
            url=url,
            formats=["markdown"]
        )
        content = response.markdown  # ✅ Use attribute, not dictionary
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"URL scrape failed: {str(e)}"
        )

    doc_record = {
        "source": url,
        "type": "url",
        "text": content,
        "created_at": datetime.utcnow()
    }

    result = await documents.insert_one(doc_record)
    print("✅ Inserted Firecrawl content into MongoDB:", result.inserted_id)  # ← Add here too
    return {
        "document_id": str(result.inserted_id),
        "source": url,
        "text_snippet": content[:200]
    }
