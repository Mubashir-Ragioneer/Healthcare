# app/models/message.py
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

class Message(BaseModel):
    id: Optional[str]
    user_id: Optional[str]
    sender: Literal["user", "assistant"]
    content: str
    timestamp: Optional[datetime] = None
