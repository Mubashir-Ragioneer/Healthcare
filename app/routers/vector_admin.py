# app/routers/vector_admin.py

from fastapi import APIRouter, Depends, HTTPException
from app.db.pinecone import index
from app.routers.deps import get_current_user
from app.utils.responses import format_response

router = APIRouter(prefix="/vector", tags=["vector-admin"])

@router.delete("/{doc_id}", summary="Delete a document's embeddings from Pinecone")
async def delete_document_vectors(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    # Optional: Only allow admin
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete vectors.")

    # Delete chunks by predictable ID pattern
    chunk_ids = [f"{doc_id}-{i}" for i in range(1000)]  # Assumes max 1000 chunks per doc
    index.delete(ids=chunk_ids)

    return format_response(success=True, message=f"Embeddings for doc_id {doc_id} deleted from Pinecone.")
