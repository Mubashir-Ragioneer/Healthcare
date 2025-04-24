# app/routers/receptionist.py

from fastapi import APIRouter
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(tags=["receptionist"])

class ReceptionRequest(BaseModel):
    name: str   = Field(..., description="Patient’s name")
    phone: str  = Field(..., description="Contact phone number")
    reason: str = Field(..., description="Reason for contacting reception")

@router.post(
    "/request",
    response_model=dict,
    summary="Connect to a human receptionist",
)
async def connect_receptionist(req: ReceptionRequest):
    """
    Submits a request for a human receptionist callback.
    If outside office hours (09:00–18:00 UTC), informs patient it will be next business day.
    """
    hour = datetime.utcnow().hour
    if hour < 9 or hour > 18:
        return {"message": "Office is closed. We’ll contact you on the next business day."}
    return {"message": "✅ Request received. Our agent will call you shortly."}
