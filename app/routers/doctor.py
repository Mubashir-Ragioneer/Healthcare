# app/routers/doctor.py

from fastapi import APIRouter, HTTPException, status
from typing import List
from datetime import datetime
from app.models.appointment import AppointmentCreate, AppointmentInDB
from app.db.mongo import appointments_collection

# No prefix here—will be mounted under "/doctors" in main.py
router = APIRouter(tags=["doctors"])

# In-memory doctor directory
DOCTORS = [
    {"id": "doc-1", "name": "Dr. Sarah Malik", "specialization": "Cardiology"},
    {"id": "doc-2", "name": "Dr. Ahmed Raza", "specialization": "Dermatology"},
]

@router.get(
    "/",
    response_model=List[dict],
    summary="List all available doctors",
)
async def list_doctors():
    """
    Return a list of all doctors with their ID, name, and specialization.
    """
    return DOCTORS

@router.post(
    "/book",
    response_model=AppointmentInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment with a doctor",
)
async def book_appointment(a: AppointmentCreate):
    """
    Create a new appointment for the given doctor.
    - Validates that the doctor exists.
    - Generates a simple appointment ID and timestamp.
    - Persists the record to MongoDB.
    """
    # Check doctor exists
    if not any(d["id"] == a.doctor_id for d in DOCTORS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor with id '{a.doctor_id}' not found."
        )

    # Build the AppointmentInDB record
    rec = AppointmentInDB(
        **a.dict(by_alias=True),
        id=f"appt-{int(datetime.utcnow().timestamp())}",
        created_at=datetime.utcnow(),
    )

    # Persist to MongoDB
    await appointments_collection.insert_one(rec.dict(by_alias=True))

    return rec

@router.get(
    "/appointments",
    summary="List all booked appointments",
    response_model=List[AppointmentInDB],
)
async def get_appointments():
    """
    Retrieve all booked doctor appointments from MongoDB.
    """
    docs = await appointments_collection.find().to_list(length=100)
    return docs

@router.get(
    "/appointments/{user_id}",
    summary="List all booked appointments for a specific user",
    response_model=List[AppointmentInDB],
)
async def get_appointments_for_user(user_id: str):
    """
    Retrieve all booked doctor appointments for a specific user from MongoDB.
    """
    docs = await appointments_collection.find({"user_id": user_id}).to_list(length=100)
    return docs
