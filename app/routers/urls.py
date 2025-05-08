# app/routers/urls.py

from fastapi import APIRouter, Form, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import List
from bson import ObjectId

from app.db.mongo import db
from app.db.pinecone import index
from app.services.file_ingestor import process_url
from app.routers.deps import get_current_user
from app.utils.responses import format_response

router = APIRouter(prefix="/url", tags=["urls"])
urls_collection = db["urls"]

# --------------------
# Schemas
# --------------------

class URLIngestionResponse(BaseModel):
    document_id: str
    url: str
    content: str
    timestamp: datetime

class URLIngestionEntry(BaseModel):
    url: str
    content: str
    timestamp: datetime

# --------------------
# Helpers
# --------------------

def clean_doc(doc):
    doc["_id"] = str(doc["_id"])
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc

# --------------------
# Routes
# --------------------

@router.post("/", summary="Ingest a public URL")
async def ingest_url(
    url: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    result = await process_url(url, user_id=user_id)

    return format_response(
        success=True,
        data={
            "document_id": result["document_id"],
            "url": result["source"],
            "content": result["text_snippet"],
            "timestamp": datetime.utcnow()
        },
        message="URL ingested successfully"
    )
    
@router.get("/logs", summary="List all ingested URL documents")
async def list_full_url_docs(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    docs = await urls_collection.find({"user_id": user_id}).to_list(100)

    return format_response(
        success=True,
        data={"documents": [clean_doc(doc) for doc in docs]},
        message="Fetched full URL logs"
    )

@router.delete("/{document_id}", summary="Delete a URL and its Pinecone chunks")
async def delete_url(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    doc = await urls_collection.find_one({"_id": ObjectId(document_id)})
    if not doc or doc.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="URL document not found or access denied")

    await urls_collection.delete_one({"_id": ObjectId(document_id)})

    # Optional: delete up to 1000 chunked vectors
    pinecone_ids = [f"{document_id}-{i}" for i in range(1000)]
    index.delete(ids=pinecone_ids)

    return format_response(success=True, message="URL document and vectors deleted successfully")
