from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from typing import List
from app.services.file_ingestor import process_file
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
import os
from app.services.file_ingestor import process_url  # already in use


router = APIRouter(prefix="/ingest", tags=["ingest"])

mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]


@router.post("/upload/")
async def upload_files(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        result = await process_file(file)
        results.append(result)
    return {"status": "success", "results": results}


@router.get("/file/{document_id}")
async def download_file(document_id: str):
    doc = await documents.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    path = doc.get("path")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Stored file missing")

    return FileResponse(path, filename=doc["filename"])


@router.post("/url/")
async def ingest_url(url: str = Form(...)):
    """
    Scrape and ingest content from a public URL using Firecrawl.
    """
    result = await process_url(url)
    return {"status": "success", "result": result}