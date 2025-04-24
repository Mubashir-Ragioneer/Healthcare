# app/services/exam_service.py

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class ExamScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    confirmation_id: str
    scheduled_time: datetime
    status: str

async def schedule_exam(
    specialization: str,
    exam_type: str,
    scheduled_time: datetime,
    user_id: str,
    purpose: str | None = None,
) -> ExamScheduleResponse:
    """
    In a real app, validate inputs, persist to DB, etc.
    Here we just simulate a successful scheduling.
    """
    return ExamScheduleResponse(
        confirmation_id=str(uuid.uuid4()),
        scheduled_time=scheduled_time,
        status="scheduled",
    )
