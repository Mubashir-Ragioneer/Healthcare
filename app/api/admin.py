# app/api/admin.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from app.core.config import settings

router = APIRouter(prefix="/admin/llm", tags=["admin", "llm"])

class LLMSettings(BaseModel):
    prompt: str = Field(..., description="System prompt for the LLM")
    temperature: float = Field(..., ge=0.0, le=1.0, description="Sampling temperature (0.0-1.0)")
    max_tokens: int = Field(..., gt=0, description="Maximum number of tokens in the response")
    model: str = Field(..., description="LLM model identifier")

    @validator("model")
    def validate_model(cls, v):
        # you could check against a whitelist of supported models
        supported = {"gpt-4o", "gpt-3.5-turbo", "gpt-4"}
        if v not in supported:
            raise ValueError(f"Unsupported model '{v}'. Supported models: {supported}")
        return v

# In-memory store for demo purposes
_current_llm_settings = LLMSettings(
    prompt=settings.SYSTEM_PROMPT,
    temperature=settings.LLM_TEMPERATURE,
    max_tokens=settings.LLM_MAX_TOKENS,
    model=settings.LLM_MODEL,
)

@router.get("/", response_model=LLMSettings)
async def get_settings():
    """Retrieve the current LLM configuration."""
    return _current_llm_settings

@router.put("/", response_model=LLMSettings)
async def update_settings(cfg: LLMSettings):
    """Update the LLM configuration (in-memory demo)."""
    global _current_llm_settings
    _current_llm_settings = cfg
    return _current_llm_settings


