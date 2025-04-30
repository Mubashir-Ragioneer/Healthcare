#  app/routers/admin.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

router = APIRouter(
    prefix="/llm",
    tags=["llm"],  # ❌ Removed "admin"
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

# GET route
@router.get("/", response_model=LLMSettings, summary="Get current LLM settings")
async def get_llm_settings():
    cfg = await llm_settings_collection.find_one({"_id": "config"})
    if not cfg:
        raise HTTPException(status_code=404, detail="LLM config not set")
    cfg.pop("_id", None)
    return cfg

# PUT route
@router.put("/", response_model=LLMSettings, summary="Update LLM settings")
async def update_llm_settings(cfg: LLMSettings):
    await llm_settings_collection.update_one(
        {"_id": "config"},
        {"$set": cfg.dict()},
        upsert=True
    )
    return cfg
