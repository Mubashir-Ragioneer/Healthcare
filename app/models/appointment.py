# app/models/appointment.py

from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional

class AppointmentBase(BaseModel):
    model_config = ConfigDict(validate_by_name=True)

    user_id: str
    doctor_id: str
    scheduled_time: datetime = Field(..., alias="datetime")
    purpose: str

    # ✅ New fields
    patient_name: str
    email: EmailStr
    phone: str
    gender: Optional[str] = None  # e.g., "male", "female", "other"
    birthdate: Optional[datetime] = None
    appointment_type: Optional[str] = None  # e.g., "consultation", "follow-up"
    notes: Optional[str] = None

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentInDB(AppointmentBase):
    model_config = ConfigDict(
        validate_by_name=True,
        from_attributes=True,
    )

    id: str = Field(..., alias="_id")
    created_at: datetime
