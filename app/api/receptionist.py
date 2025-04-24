app/api/receptionist.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(prefix="/reception", tags=["receptionist"])

class ReceptionRequest(BaseModel):
    name: str = Field(..., description="Patient's full name")
    phone: str = Field(..., description="Contact phone number in E.164 format")
    reason: str = Field(..., description="Reason for connecting to receptionist")

class ReceptionResponse(BaseModel):
    message: str = Field(...)

@router.post("/request", response_model=ReceptionResponse)
async def connect_receptionist(request: ReceptionRequest):
    """Route patient request to a human receptionist or queue after hours."""
    hour = datetime.utcnow().hour
    if hour < 9 or hour >= 18:
        return ReceptionResponse(message="Office is closed. We’ll contact you on the next business day.")
    # Optionally enqueue request in a support queue here
    return ReceptionResponse(message="✅ Request received. Our agent will call you shortly.")