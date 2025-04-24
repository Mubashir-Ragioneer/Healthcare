from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.db.mongo import exam_requests_collection

router = APIRouter(tags=["exam"])

class ExamScheduleRequest(BaseModel):
    specialization: str
    exam_type: str
    scheduled_time: datetime
    user_id: str
    purpose: Optional[str] = None

@router.post("/schedule", status_code=201, summary="Schedule a medical exam")
async def schedule_exam(req: ExamScheduleRequest):
    doc = req.dict()
    doc["created_at"] = datetime.utcnow()
    await exam_requests_collection.insert_one(doc)
    return {"message": "✅ Exam scheduled successfully."}

@router.get("/schedule", response_model=List[ExamScheduleRequest], summary="List all exam requests")
async def list_exam_requests():
    docs = await exam_requests_collection.find().to_list(100)
    return docs
