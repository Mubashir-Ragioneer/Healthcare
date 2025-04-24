# app/routers/exam.py

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from app.services.exam_service import schedule_exam, ExamScheduleResponse

router = APIRouter(tags=["exam"])

class ExamScheduleRequest(BaseModel):
    specialization: str = Field(..., description="Medical specialty")
    exam_type: str       = Field(..., description="Specific exam type")
    scheduled_time: datetime = Field(
        ..., 
        description="Desired date/time in ISO format"
    )
    user_id: str         = Field(..., description="Patient identifier")
    purpose: Optional[str] = Field(None, description="Reason for the exam")

@router.post(
    "/schedule",
    response_model=ExamScheduleResponse,
    summary="Schedule a medical exam",
    status_code=status.HTTP_201_CREATED,
)
async def schedule_exam_endpoint(req: ExamScheduleRequest):
    """
    Schedule an exam and return a confirmation.
    """
    try:
        return await schedule_exam(
            req.specialization,
            req.exam_type,
            req.scheduled_time,
            req.user_id,
            req.purpose,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
