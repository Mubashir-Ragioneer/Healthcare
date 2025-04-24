from fastapi import APIRouter
from pydantic import BaseModel, Field
from datetime import datetime
from app.db.mongo import reception_requests_collection
from typing import List

router = APIRouter(tags=["receptionist"])

class ReceptionRequest(BaseModel):
    name: str = Field(..., description="Patient’s name")
    phone: str = Field(..., description="Contact phone number")
    reason: str = Field(..., description="Reason for contacting reception")

@router.post("/request", summary="Connect to a human receptionist")
async def connect_receptionist(req: ReceptionRequest):
    doc = req.dict()
    doc["created_at"] = datetime.utcnow()
    await reception_requests_collection.insert_one(doc)
    return {"message": "✅ Request received. Our agent will call you shortly."}

@router.get("/request", response_model=List[ReceptionRequest], summary="List all receptionist requests")
async def list_receptionist_requests():
    docs = await reception_requests_collection.find().to_list(100)
    return docs
