# app/routers/ingest.py

from fastapi import APIRouter, UploadFile, File, Form
from typing import List
from app.services.file_ingestor import process_file, process_url

router = APIRouter(tags=["ingestion"])

@router.post(
    "/upload/", 
    summary="Upload files for ingestion",
)
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Accepts one or more files (PDF/Word/TXT) and processes them asynchronously.
    """
    results = []
    for file in files:
        result = await process_file(file)
        results.append(result)
    return {"status": "success", "results": results}

@router.post(
    "/url/", 
    summary="Ingest content from a URL",
)
async def ingest_url(url: str = Form(...)):
    """
    Fetches and processes the content at the given URL.
    """
    result = await process_url(url)
    return {"status": "success", "result": result}
