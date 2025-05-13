# app/routers/auth.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
import jwt
from datetime import datetime, timedelta
from app.db.mongo import get_db
from typing import Literal


router = APIRouter(tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
users_collection = db["users"]

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

class Token(BaseModel):
    access_token: str
    token_type: str

class UserSignup(BaseModel):
    full_name: str
    email: EmailStr
    phone_number: str
    password: str
    diagnosis: Literal["crohns", "colitis", "undiagnosed"]

class UserLogin(BaseModel):
    email: EmailStr
    password: str

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/signup", summary="Create a new user")
async def signup(user: UserSignup):
    existing = await users_collection.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = pwd_context.hash(user.password)
    await users_collection.insert_one({
        "full_name": user.full_name,
        "email": user.email,
        "phone_number": user.phone_number,
        "diagnosis": user.diagnosis,
        "password": hashed_password,
        "created_at": datetime.utcnow()
    })
    return {"message": "User registered successfully"}

@router.post("/login", response_model=Token)
async def login(user: UserLogin, db: AsyncIOMotorDatabase = Depends(get_db)):
    print("🔍 Attempting login for:", user.email)
    existing_user = await db["users"].find_one({"email": user.email})
    print("📝 Found user:", existing_user)

    if not existing_user:
        print("❌ User not found")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        print("🔑 Verifying password...")
        if not verify_password(user.password, existing_user["password"]):
            print("❌ Password verification failed")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        print("✅ Creating access token...")
        access_token = create_access_token(data={
            "sub": str(existing_user["_id"]),
            "email": existing_user["email"],
            "role": existing_user.get("role", "user")
        })

        return {"access_token": access_token, "token_type": "bearer"}

    except Exception as e:
        print("🔥 Login error:", str(e))
        import traceback
        print("🔥 Stack trace:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
