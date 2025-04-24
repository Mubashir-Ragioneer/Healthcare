# app/routers/ingest.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
import os

from app.services.file_ingestor import process_file, process_url
from app.db.mongo import documents_collection
from bson import ObjectId

router = APIRouter(prefix="/ingest", tags=["ingest"])

# -----------------------------
# Pydantic Schemas
# -----------------------------

class URLIngestionResponse(BaseModel):
    document_id: str = Field(..., description="MongoDB document ID")
    url: str = Field(..., description="Original ingested URL")
    content: str = Field(..., description="Extracted content")
    timestamp: datetime = Field(..., description="Ingestion timestamp")


class URLIngestionEntry(BaseModel):
    url: str
    content: str
    timestamp: datetime


# -----------------------------
# Upload Files
# -----------------------------

@router.post("/upload/", summary="Upload one or more files")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload files and store them locally & in MongoDB.
    """
    results = []
    for file in files:
        result = await process_file(file)
        results.append(result)
    return {"status": "success", "results": results}


# -----------------------------
# Download File by ID
# -----------------------------

@router.get("/file/{document_id}", summary="Download a previously uploaded file")
async def download_file(document_id: str):
    """
    Download a previously uploaded file using its document ID.
    """
    doc = await documents_collection.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    path = doc.get("path")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Stored file is missing")

    return FileResponse(path, filename=doc["filename"])


# -----------------------------
# Ingest URL
# -----------------------------

@router.post("/url/", response_model=URLIngestionResponse, summary="Ingest a public URL")
async def ingest_url(url: str = Form(...)):
    """
    Scrape and ingest content from a public URL using Firecrawl.
    """
    result = await process_url(url)

    doc = {
        "url": url,
        "content": result["content"],
        "timestamp": datetime.utcnow(),
    }

    inserted = await documents_collection.insert_one(doc)
    return URLIngestionResponse(
        document_id=str(inserted.inserted_id),
        url=url,
        content=result["content"],
        timestamp=doc["timestamp"]
    )


# -----------------------------
# List All Ingested URLs
# -----------------------------

@router.get("/url/", response_model=List[URLIngestionEntry], summary="List all URL ingestions")
async def list_url_ingestions():
    """
    List all ingested URLs and their content.
    """
    docs = await documents_collection.find({"url": {"$exists": True}}).to_list(100)
    return [URLIngestionEntry(**doc) for doc in docs]
