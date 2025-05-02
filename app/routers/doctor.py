# app/routers/doctor.py

from fastapi import APIRouter, HTTPException, status
from typing import List
from datetime import datetime
from app.models.appointment import AppointmentCreate, AppointmentInDB
from app.db.mongo import appointments_collection
from app.services.feegow import forward_to_feegow
from app.services.kommo import push_appointment_to_kommo

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
    return DOCTORS

@router.post(
    "/book",
    response_model=AppointmentInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment with a doctor",
)
async def book_appointment(a: AppointmentCreate):
    doctor = next((d for d in DOCTORS if d["id"] == a.doctor_id), None)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor with id '{a.doctor_id}' not found."
        )

    rec = AppointmentInDB(
        **a.dict(by_alias=True),
        doctor_name=doctor["name"],
        specialization=doctor["specialization"],
        id=f"appt-{int(datetime.utcnow().timestamp())}",
        created_at=datetime.utcnow(),
    )

    await appointments_collection.insert_one(rec.dict(by_alias=True))

    feegow_synced = False
    try:
        print("📤 Sending appointment to Feegow...")
        await forward_to_feegow(rec.dict())
        feegow_synced = True
        print("✅ Feegow sync successful.")
    except Exception as e:
        print(f"❌ Feegow sync failed: {e}")

    kommo_synced = False
    try:
        print("📤 Sending appointment to Kommo...")
        push_appointment_to_kommo(rec.dict())
        kommo_synced = True
        print("✅ Kommo sync successful.")
    except Exception as e:
        print(f"❌ Kommo sync failed: {e}")

    await appointments_collection.update_one(
        {"id": rec.id},
        {"$set": {
            "feegow_synced": feegow_synced,
            "kommo_synced": kommo_synced
        }}
    )

    return rec

@router.get(
    "/appointments",
    summary="List all booked appointments",
    response_model=List[AppointmentInDB],
)
async def get_appointments():
    docs = await appointments_collection.find().to_list(length=100)
    return docs

@router.get(
    "/appointments/{user_id}",
    summary="List all booked appointments for a specific user",
    response_model=List[AppointmentInDB],
)
async def get_appointments_for_user(user_id: str):
    docs = await appointments_collection.find({"user_id": user_id}).to_list(length=100)
    return docs
