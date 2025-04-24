# app/routers/admin.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from app.core.config import settings

router = APIRouter(
    prefix="/llm",               # now relative to the mount point
    tags=["admin", "llm"],
)

class LLMSettings(BaseModel):
    prompt: str = Field(..., description="System prompt for the LLM")
    temperature: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Sampling temperature (0.0–1.0)",
    )
    max_tokens: int = Field(
        ...,
        gt=0,
        description="Maximum tokens for each response",
    )
    model: str = Field(..., description="Model identifier")

    @validator("model")
    def validate_model(cls, v):
        allowed = {settings.LLM_MODEL, "gpt-3.5-turbo", "gpt-4"}
        if v not in allowed:
            raise ValueError(f"Unsupported model: {v}")
        return v

# In-memory store of current settings
_current_settings = LLMSettings(
    prompt=settings.SYSTEM_PROMPT,
    temperature=settings.LLM_TEMPERATURE,
    max_tokens=settings.LLM_MAX_TOKENS,
    model=settings.LLM_MODEL,
)

@router.get(
    "/",
    response_model=LLMSettings,
    summary="Get current LLM settings",
)
async def get_llm_settings():
    """
    Retrieve the current LLM configuration.
    """
    return _current_settings

@router.put(
    "/",
    response_model=LLMSettings,
    summary="Update LLM settings",
)
async def update_llm_settings(cfg: LLMSettings):
    """
    Update in-memory LLM configuration. (Not persisted permanently.)
    """
    global _current_settings
    _current_settings = cfg
    return _current_settings
