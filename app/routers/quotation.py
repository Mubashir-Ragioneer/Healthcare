from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List
from app.db.mongo import quote_requests_collection

router = APIRouter(tags=["quotation"])

class QuoteRequest(BaseModel):
    category: str
    subcategory: str
    details: str
    user_id: str

@router.post("/request", status_code=201, summary="Request a quotation")
async def request_quote(req: QuoteRequest):
    doc = req.dict()
    doc["created_at"] = datetime.utcnow()
    await quote_requests_collection.insert_one(doc)
    return {"message": "✅ Quotation request submitted."}

@router.get("/request", response_model=List[QuoteRequest], summary="List all quote requests")
async def list_quote_requests():
    docs = await quote_requests_collection.find().to_list(100)
    return docs
