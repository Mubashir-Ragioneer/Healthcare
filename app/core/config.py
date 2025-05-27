# app/core/config.py

from typing import Optional
from pydantic import Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # MongoDB settings
    MONGODB_URI: str = Field(default="mongodb://localhost:27017", env="MONGODB_URI")
    MONGODB_DB: str = Field(default="healthcare", env="MONGODB_DB")

    # OpenAI settings
    OPENAI_API_KEY: str = Field(..., env="OPENAI_API_KEY")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")

    # Pinecone settings
    PINECONE_API_KEY: str = Field(..., env="PINECONE_API_KEY")
    PINECONE_ENV: str = Field(..., env="PINECONE_ENV")
    PINECONE_INDEX: str = Field(..., env="PINECONE_INDEX")

    # Firecrawl settings
    FIRECRAWL_API_KEY: str = Field(..., env="FIRECRAWL_API_KEY")

    # LLM settings
    SYSTEM_PROMPT: str = Field(
        default="You are a highly knowledgeable and empathetic AI healthcare assistant designed to support users with general medical inquiries...",
        env="SYSTEM_PROMPT"
    )
    LLM_TEMPERATURE: float = Field(default=0.6, env="LLM_TEMPERATURE")
    LLM_MAX_TOKENS: int = Field(default=1024, env="LLM_MAX_TOKENS")
    LLM_MODEL: str = Field(default="gpt-4.1", env="LLM_MODEL")

    # Auth/JWT settings
    SECRET_KEY: str = Field(..., env="SECRET_KEY")  # ✅ Added for auth
    JWT_ALGORITHM: str = Field(default="HS256", env="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Kommo settings
    KOMMO_CLIENT_ID: str = Field(..., env="KOMMO_CLIENT_ID")
    KOMMO_CLIENT_SECRET: str = Field(..., env="KOMMO_CLIENT_SECRET")
    KOMMO_SUBDOMAIN: str = Field(..., env="KOMMO_SUBDOMAIN")  # e.g. yourteam
    KOMMO_REDIRECT_URI: str = Field(default="http://localhost:8000/kommo/auth/callback", env="KOMMO_REDIRECT_URI")
    
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    FRONTEND_URL: str

settings = Settings()
