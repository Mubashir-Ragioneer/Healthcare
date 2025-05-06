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

    patient_name: str
    email: EmailStr
    phone: str
    gender: Optional[str] = None
    birthdate: Optional[datetime] = None
    appointment_type: Optional[str] = None
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

    def to_kommo_dict(self) -> dict:
        """Return a dict formatted for Kommo lead sync."""
        return {
            "patient_name": self.patient_name,
            "email": self.email,
            "phone": self.phone,
            "birthdate": self.birthdate.isoformat() if self.birthdate else None,
            "datetime": self.scheduled_time.isoformat(),
            "appointment_type": self.appointment_type or "Virtual",  # fallback default
            "notes": self.notes or "",
        }
