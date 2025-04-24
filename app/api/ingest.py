app/api/ingest.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from typing import List, Dict, Any
from app.services.file_ingestor import process_file, process_url
from pydantic import BaseModel, Field, HttpUrl

router = APIRouter(prefix="/ingest", tags=["ingestion"])

class FileResult(BaseModel):
    filename: str = Field(..., description="Name of the uploaded file")
    success: bool = Field(..., description="Whether the ingestion succeeded")
    detail: Any = Field(None, description="Additional info or error message")

class URLRequest(BaseModel):
    url: HttpUrl = Field(..., description="URL to ingest content from")

class URLResult(BaseModel):
    url: HttpUrl = Field(..., description="The ingested URL")
    success: bool = Field(..., description="Whether the ingestion succeeded")
    detail: Any = Field(None, description="Additional info or error message")

@router.post("/files", response_model=List[FileResult], status_code=status.HTTP_200_OK)
async def upload_files(files: List[UploadFile] = File(...)) -> List[FileResult]:
    """
    Ingest one or more uploaded files (PDF, Word, TXT).
    Returns a list of results per file.
    """
    results: List[FileResult] = []
    for file in files:
        try:
            detail = await process_file(file)
            results.append(FileResult(filename=file.filename, success=True, detail=detail))
        except Exception as e:
            results.append(FileResult(filename=file.filename, success=False, detail=str(e)))
    return results

@router.post("/url", response_model=URLResult, status_code=status.HTTP_200_OK)
async def ingest_url(request: URLRequest) -> URLResult:
    """
    Ingest content from a URL.
    """
    try:
        detail = await process_url(request.url)
        return URLResult(url=request.url, success=True, detail=detail)
    except Exception as e:
        # Could log exception here
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to ingest URL: {e}"
        )