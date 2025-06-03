# app/routers/doctor.py

from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from datetime import datetime
from app.models.appointment import AppointmentCreate, AppointmentInDB
from app.db.mongo import appointments_collection
from app.routers.deps import get_current_user
from app.services.feegow import forward_to_feegow
from app.services.kommo import push_appointment_to_kommo
from app.db.mongo import db
from fastapi.responses import JSONResponse

router = APIRouter(tags=["doctors"])
doctors_collection = db["doctors"]


@router.post(
    "/book",
    response_model=AppointmentInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment with a doctor",
)
async def book_appointment(a: AppointmentCreate):
    doctor = await doctors_collection.find_one({"id": a.doctor_id})
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

    # 👇 Set _id explicitly for future updates
    doc = rec.dict(by_alias=True)
    doc["_id"] = rec.id
    await appointments_collection.insert_one(doc)

    feegow_synced = False
    try:
        print("Sending appointment to Feegow...")
        await forward_to_feegow(rec.dict())
        feegow_synced = True
        print("Feegow sync successful.")
    except Exception as e:
        print(f"Feegow sync failed: {e}")

    kommo_synced = False
    try:
        print("Sending appointment to Kommo...")
        push_appointment_to_kommo(rec.to_kommo_dict())
        kommo_synced = True
        print("Kommo sync successful.")
    except Exception as e:
        print(f" Kommo sync failed: {e}")

    update_result = await appointments_collection.update_one(
        {"_id": rec.id},
        {"$set": {
            "feegow_synced": feegow_synced,
            "kommo_synced": kommo_synced
        }}
    )
    print(f" Updated sync flags in DB: {update_result.modified_count} modified")

    return rec

@router.get(
    "/",
    summary="List all available doctors from MongoDB (safe)",
)
async def list_doctors(current_user: dict = Depends(get_current_user)):
    docs = await doctors_collection.find().to_list(length=100)

    for doc in docs:
        doc["_id"] = str(doc["_id"])  # or doc.pop("_id")

    return JSONResponse(content=docs)


@router.get(
    "/appointments/{user_id}",
    summary="List all booked appointments for a specific user",
    response_model=List[AppointmentInDB],
)
async def get_appointments_for_user(user_id: str, current_user: dict = Depends(get_current_user)):
    docs = await appointments_collection.find({"user_id": user_id}).to_list(length=100)
    return docs
