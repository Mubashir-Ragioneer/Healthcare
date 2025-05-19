# app/routers/ingest.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from bson import ObjectId
import io
from app.routers.deps import require_admin
from app.services.file_ingestor import process_file
from app.db.mongo import documents_collection
from app.routers.deps import get_current_user
from app.utils.responses import format_response  # ✅ standardized responses

router = APIRouter(tags=["ingest"])

# -----------------------------
# Upload Files
# -----------------------------

@router.post("/upload", summary="Upload one or more files (admin only)")
async def upload_files(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(require_admin)
):
    """
    Admin uploads files to be ingested and stored.
    """
    user_id = current_user["user_id"]
    results = []
    for file in files:
        result = await process_file(file, user_id=user_id)
        results.append(result)

    return format_response(success=True, data={"results": results})


# -----------------------------
# Download File by ID
# -----------------------------

@router.get("/file/{document_id}", summary="Download a previously uploaded file")
async def download_file(
    document_id: str,
    current_user: dict = Depends(require_admin)
):
    """
    Admin can download a specific uploaded file by document ID.
    """
    doc = await documents_collection.find_one({"_id": ObjectId(document_id)})
    if not doc or doc.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="File not found or access denied")

    file_data = doc.get("file_data")
    if not file_data:
        raise HTTPException(status_code=404, detail="No file data stored in database")

    return StreamingResponse(io.BytesIO(file_data), media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename={doc['filename']}"
    })
