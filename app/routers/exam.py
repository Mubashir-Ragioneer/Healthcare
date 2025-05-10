# app/routers/exam.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.db.mongo import exam_requests_collection
from app.services.kommo import push_exam_lead_to_kommo  

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

    try:
        push_exam_lead_to_kommo(doc)  # ⬅️ Push to Kommo
    except Exception as e:
        print("❌ Kommo sync failed:", str(e))

    return {"message": "✅ Exam scheduled successfully."}

@router.get("/schedule", response_model=List[ExamScheduleRequest])
async def list_exam_requests(user_id: str):
    docs = await exam_requests_collection.find({"user_id": user_id}).to_list(100)
    return docs
