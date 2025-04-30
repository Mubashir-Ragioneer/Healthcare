# app/routers/ingest.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List
from fastapi.encoders import jsonable_encoder
from datetime import datetime
import io

from app.services.file_ingestor import process_file, process_url
from app.db.mongo import documents_collection
from bson import ObjectId

router = APIRouter(tags=["ingest"])  # Removed prefix="/ingest"

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
# Helper function
# -----------------------------

def clean_mongo_document(doc):
    doc["_id"] = str(doc["_id"])
    if "created_at" in doc and isinstance(doc["created_at"], datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc

# -----------------------------
# Upload Files
# -----------------------------

@router.post("/upload", summary="Upload one or more files")
async def upload_files(
    files: List[UploadFile] = File(...),
    user_id: str = Form(...)
):
    results = []
    for file in files:
        result = await process_file(file, user_id=user_id)
        results.append(result)
    return {"status": "success", "results": results}

# -----------------------------
# Download File by ID
# -----------------------------

@router.get("/file/{document_id}", summary="Download a previously uploaded file")
async def download_file(document_id: str):
    doc = await documents_collection.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    file_data = doc.get("file_data")
    if not file_data:
        raise HTTPException(status_code=404, detail="No file data stored in database")

    return StreamingResponse(io.BytesIO(file_data), media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename={doc['filename']}"
    })

# -----------------------------
# Ingest URL
# -----------------------------

@router.post("/url", response_model=URLIngestionResponse, summary="Ingest a public URL")
async def ingest_url(
    url: str = Form(...),
    user_id: str = Form(...)
):
    result = await process_url(url, user_id=user_id)

    return URLIngestionResponse(
        document_id=result["document_id"],
        url=result["source"],
        content=result["text_snippet"],
        timestamp=datetime.utcnow()
    )

# -----------------------------
# List All Ingested URLs
# -----------------------------

@router.get("/url", response_model=List[URLIngestionEntry], summary="List all URL ingestions")
async def list_url_ingestions(user_id: str):
    docs = await documents_collection.find({
        "url": {"$exists": True},
        "user_id": user_id
    }).to_list(100)

    return [URLIngestionEntry(**doc) for doc in docs]

# -----------------------------
# List All Ingested Files (file-logs)
# -----------------------------

@router.get("/file-logs", summary="List all uploaded file ingestions")
async def list_uploaded_files(user_id: str):
    docs = await documents_collection.find({
        "filename": {"$exists": True},
        "user_id": user_id
    }).to_list(100)

    for doc in docs:
        doc["_id"] = str(doc["_id"])       # Convert ObjectId
        doc.pop("file_data", None)         # Remove raw binary field if exists

    return JSONResponse(content=jsonable_encoder(docs))

# -----------------------------
# List All Ingested URLs (url-logs)
# -----------------------------

@router.get("/url-logs", summary="List all URL ingestions")
async def list_ingested_urls(user_id: str):
    docs = await documents_collection.find({
        "source": {"$exists": True},
        "user_id": user_id
    }).to_list(100)

    cleaned_docs = [clean_mongo_document(doc) for doc in docs]
    return JSONResponse(content=cleaned_docs)
