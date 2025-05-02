# app/models/kommo.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class KommoToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    expires_at: Optional[datetime] = None
