# app/models/user.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class User(BaseModel):
    id: Optional[str]
    name: str
    email: EmailStr
    phone: Optional[str] = None
    created_at: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    email: EmailStr
    password: str
