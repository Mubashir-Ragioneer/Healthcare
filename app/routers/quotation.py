# app/routers/quotation.py

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime
from app.services.quotation_service import request_quote, QuoteResponse

router = APIRouter(tags=["quotation"])

class QuoteRequest(BaseModel):
    category: str = Field(..., description="Quotation category (diagnosis, exam, etc.)")
    subcategory: str = Field(..., description="Specific sub-category")
    details: str = Field(..., description="Additional details describing the request")
    user_id: str = Field(..., description="Patient identifier")

@router.post(
    "/request",
    response_model=QuoteResponse,
    summary="Request a quotation",
    status_code=status.HTTP_201_CREATED,
)
async def request_quote_endpoint(req: QuoteRequest):
    """
    Handle quotation requests and return a quote ID, ETA, and status.
    """
    try:
        return await request_quote(
            req.category,
            req.subcategory,
            req.details,
            req.user_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
