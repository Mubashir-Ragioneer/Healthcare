# app/models/appointment.py

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class AppointmentBase(BaseModel):
    # v2 replacement for allow_population_by_field_name
    model_config = ConfigDict(validate_by_name=True)

    user_id: str
    doctor_id: str
    scheduled_time: datetime = Field(..., alias="datetime")
    purpose: str

class AppointmentCreate(AppointmentBase):
    pass

class AppointmentInDB(AppointmentBase):
    # also enable from_attributes (formerly orm_mode)
    model_config = ConfigDict(
        validate_by_name=True,
        from_attributes=True,
    )

    id: str               = Field(..., alias="_id")
    created_at: datetime
