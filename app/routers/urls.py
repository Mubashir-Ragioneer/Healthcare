# app/routers/documents.py

from fastapi import APIRouter, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.core.config import settings
from app.db.pinecone import index
from app.routers.deps import get_current_user
from fastapi import Depends


router = APIRouter(prefix="/documents", tags=["documents"])

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]

# Helper to convert Mongo document
def doc_to_dict(doc):
    doc["document_id"] = str(doc["_id"])
    doc.pop("_id", None)
    doc.pop("file_data", None)  # avoid binary overload
    return doc


@router.get("/", summary="List all documents for a user")
async def list_documents(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    docs = await documents.find({"user_id": user_id}).to_list(length=100)
    return [doc_to_dict(doc) for doc in docs]
@router.get("/{document_id}", summary="Get document metadata by ID")
async def get_document(document_id: str):
    doc = await documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc_to_dict(doc)

@router.delete("/{document_id}", summary="Delete a document and its Pinecone chunks")
async def delete_document(document_id: str):
    doc = await documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from Mongo
    await documents.delete_one({"_id": ObjectId(document_id)})

    # Attempt to delete up to 1000 possible chunk IDs
    pinecone_ids = [f"{document_id}-{i}" for i in range(1000)]
    index.delete(ids=pinecone_ids)

    return {"message": "Document and chunks deleted successfully"}
