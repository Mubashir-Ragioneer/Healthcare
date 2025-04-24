app/api/doctor.py
from fastapi import APIRouter, HTTPException, status
from typing import List
from datetime import datetime
from app.models.appointment import Appointment, AppointmentCreate, AppointmentInDB
from app.db.mongo import appointments_collection

router = APIRouter(prefix="/doctors", tags=["doctors"])

# Dummy in-memory doctor directory (replace with DB lookup as needed)
DOCTORS = [
    {"id": "doc-1", "name": "Dr. Sarah Malik", "specialization": "Cardiologist"},
    {"id": "doc-2", "name": "Dr. Ahmed Raza", "specialization": "Dermatologist"},
]

@router.get("/", response_model=List[dict])
async def list_doctors():
    """Return list of available doctors."""
    return DOCTORS

@router.post("/book", response_model=AppointmentInDB, status_code=status.HTTP_201_CREATED)
async def book_appointment(appointment: AppointmentCreate):
    """Book an appointment with a doctor."""
    # Validate doctor ID
    if not any(d["id"] == appointment.doctor_id for d in DOCTORS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor with id '{appointment.doctor_id}' not found"
        )

    # Prepare record for DB
    record = AppointmentInDB(
        **appointment.dict(),
        id=f"appt-{int(datetime.utcnow().timestamp())}",
        created_at=datetime.utcnow()
    )
    # Insert into MongoDB
    await appointments_collection.insert_one(record.dict(by_alias=True))
    return record