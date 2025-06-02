# app/models/specialist_history.py

from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class SpecialistHistory(BaseModel):
    user_email: str
    query: str
    doctor_name: str
    timestamp: datetime
    session_id: Optional[str] = None
    response: Optional[dict] = None  # <- Add this
