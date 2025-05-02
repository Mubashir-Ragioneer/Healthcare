# app/routers/admin.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from typing import List, Dict
from app.models.appointment import AppointmentInDB
from app.db.mongo import appointments_collection
from app.services.kommo import push_appointment_to_kommo
from app.services.feegow import forward_to_feegow

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
llm_settings_collection = db["llm_settings"]

class LLMSettings(BaseModel):
    prompt: str = Field(..., description="System prompt for the LLM")
    temperature: float = Field(..., ge=0.0, le=1.0)
    max_tokens: int = Field(..., gt=0)
    model: str = Field(...)

    @validator("model")
    def validate_model(cls, v):
        allowed = {"gpt-4", "gpt-3.5-turbo", settings.LLM_MODEL}
        if v not in allowed:
            raise ValueError(f"Unsupported model: {v}")
        return v

@router.get("/llm", response_model=LLMSettings, summary="Get current LLM settings")
async def get_llm_settings():
    cfg = await llm_settings_collection.find_one({"_id": "config"})
    if not cfg:
        raise HTTPException(status_code=404, detail="LLM config not set")
    cfg.pop("_id", None)
    return cfg

@router.put("/llm", response_model=LLMSettings, summary="Update LLM settings")
async def update_llm_settings(cfg: LLMSettings):
    await llm_settings_collection.update_one(
        {"_id": "config"},
        {"$set": cfg.dict()},
        upsert=True
    )
    return cfg

@router.get("/unsynced", response_model=List[AppointmentInDB], summary="View unsynced appointments")
async def get_unsynced_appointments():
    query = {
        "$or": [
            {"kommo_synced": {"$ne": True}},
            {"feegow_synced": {"$ne": True}}
        ]
    }
    docs = await appointments_collection.find(query).to_list(length=100)
    return docs

@router.post("/resync/{appointment_id}", response_model=AppointmentInDB, summary="Resync a failed appointment")
async def resync_appointment(appointment_id: str):
    rec = await appointments_collection.find_one({"id": appointment_id})
    if not rec:
        raise HTTPException(status_code=404, detail="Appointment not found")

    feegow_synced = False
    kommo_synced = False

    try:
        print("📤 Resyncing to Feegow...")
        await forward_to_feegow(rec)
        feegow_synced = True
        print("✅ Feegow resync successful.")
    except Exception as e:
        print(f"❌ Feegow resync failed: {e}")

    try:
        print("📤 Resyncing to Kommo...")
        await push_appointment_to_kommo(rec)
        kommo_synced = True
        print("✅ Kommo resync successful.")
    except Exception as e:
        print(f"❌ Kommo resync failed: {e}")

    await appointments_collection.update_one(
        {"id": appointment_id},
        {"$set": {
            "feegow_synced": feegow_synced,
            "kommo_synced": kommo_synced
        }}
    )

    updated = await appointments_collection.find_one({"id": appointment_id})
    return updated

@router.get("/sync-report", summary="Get sync summary report")
async def sync_report() -> Dict[str, int]:
    total = await appointments_collection.count_documents({})
    kommo_ok = await appointments_collection.count_documents({"kommo_synced": True})
    feegow_ok = await appointments_collection.count_documents({"feegow_synced": True})
    return {
        "total_appointments": total,
        "kommo_synced": kommo_ok,
        "feegow_synced": feegow_ok,
        "kommo_unsynced": total - kommo_ok,
        "feegow_unsynced": total - feegow_ok
    }
