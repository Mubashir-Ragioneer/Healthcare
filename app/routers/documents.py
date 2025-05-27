# app/routers/documents.py

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from app.core.config import settings
from app.db.pinecone import index
from app.routers.deps import get_current_user
from app.utils.responses import format_response  # ✅ standardized response
from app.utils.pagination import build_pagination, build_sort

router = APIRouter(prefix="/documents", tags=["documents"])

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
documents = db["documents"]

# -----------------------------
# Helpers
# -----------------------------

def doc_to_dict(doc):
    doc["document_id"] = str(doc["_id"])
    doc.pop("_id", None)
    doc.pop("file_data", None)  # avoid binary overload
    return doc

# -----------------------------
# Routes
# -----------------------------
@router.get("", summary="List all documents")
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    search: str = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_user: dict = Depends(get_current_user),
):
    skip, limit = build_pagination(page, page_size)
    sort = build_sort(sort_by, sort_order)

    query = {}
    if search:
        query["$or"] = [
            {"filename": {"$regex": search, "$options": "i"}},
            {"user_id": {"$regex": search, "$options": "i"}},
        ]
    total = await documents.count_documents(query)
    docs = await documents.find(query).sort(sort).skip(skip).limit(limit).to_list(length=page_size)

    return format_response(
        success=True,
        data={
            "documents": [doc_to_dict(doc) for doc in docs],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    )

@router.get("/{document_id}", summary="Get document metadata by ID")
async def get_document(document_id: str, current_user: dict = Depends(get_current_user)):
    doc = await documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return format_response(success=True, data={"document": doc_to_dict(doc)})


@router.delete("/{document_id}", summary="Delete a document and its Pinecone chunks")
async def delete_document(document_id: str, current_user: dict = Depends(get_current_user)):
    doc = await documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await documents.delete_one({"_id": ObjectId(document_id)})

    pinecone_ids = [f"{document_id}-{i}" for i in range(1000)]
    index.delete(ids=pinecone_ids)

    return format_response(success=True, message="Document and chunks deleted successfully")

