# app/routers/auth.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
import jwt
from datetime import datetime, timedelta
from bson import ObjectId
from bson.errors import InvalidId
from app.db.mongo import users_collection
from fastapi.responses import JSONResponse, RedirectResponse
from app.utils.responses import format_response
from app.db.mongo import get_db
from typing import Literal
from app.routers.deps import get_current_user
from app.utils.errors import UnauthorizedRequestError, BadRequestError, NotFoundError, ConflictError, InternalServerError
import secrets
from datetime import timedelta
from app.utils.email import send_verification_email
import os

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://healthcare.ragioneer.com")

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
        raise ConflictError("Email already registered")

    hashed_password = pwd_context.hash(user.password)
    verification_token = secrets.token_urlsafe(32)
    verification_token_expiry = datetime.utcnow() + timedelta(hours=1)

    user_doc = {
        "full_name": user.full_name,
        "email": user.email,
        "phone_number": user.phone_number,
        "diagnosis": user.diagnosis,
        "password": hashed_password,
        "created_at": datetime.utcnow(),
        "verified": False,
        "verification_token": verification_token,
        "verification_token_expiry": verification_token_expiry,
    }

    result = await users_collection.insert_one(user_doc)
    verification_link = f"{FRONTEND_URL}/verify-email?token={verification_token}"

    # SEND EMAIL!
    try:
        await send_verification_email(user.email, verification_link)
    except Exception as e:
        # Cleanup if email sending fails
        await users_collection.delete_one({"_id": result.inserted_id})
        raise HTTPException(status_code=500, detail=f"Failed to send verification email: {e}")

    return {
        "message": "User registered successfully. Please check your email to verify your account.",
        "user": {
            "email": user.email,
            "verified": False
        }
    }
    
@router.post("/login", response_model=Token)
async def login(user: UserLogin, db: AsyncIOMotorDatabase = Depends(get_db)):
    print("🔍 Attempting login for:", user.email)
    existing_user = await db["users"].find_one({"email": user.email})
    print("📝 Found user:", existing_user)

    if not existing_user:
        print("❌ User not found")
        raise UnauthorizedRequestError("Invalid credentials: User not found")

    # Google-only account: no password available for normal login
    if existing_user.get("provider") == "google" and "password" not in existing_user:
        print("❌ Account registered via Google; password login not available.")
        raise UnauthorizedRequestError("This account was registered via Google. Please use Google login.")

    # Block unverified users
    if not existing_user.get("verified", False):
        raise UnauthorizedRequestError(
            "Email not verified. Please check your inbox for a verification email."
        )

    print("🔑 Verifying password...")
    if not verify_password(user.password, existing_user.get("password", "")):
        print("❌ Password verification failed")
        raise UnauthorizedRequestError("Invalid credentials: Password verification failed")

    try:
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
        raise HTTPException(status_code=500, detail="Internal Server Error: Login failed")
        
@router.get("/me", summary="Get current user info")
async def whoami(current_user: dict = Depends(get_current_user)):
    sub = current_user.get("user_id")

    try:
        # Case 1: sub is a valid ObjectId (email/password login)
        user = await users_collection.find_one({"_id": ObjectId(sub)})
    except (InvalidId, TypeError):
        # Case 2: sub is likely an email (Google OAuth login)
        user = await users_collection.find_one({"email": sub})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user["_id"] = str(user["_id"])
    return format_response(success=True, data={"user": user})


@router.post("/logout", summary="Logout and clear auth cookie")
async def logout():
    response = JSONResponse(content={"message": "Successfully logged out"})
    response.delete_cookie(
        key="access_token",
        path="/",  # match how it was set
        domain=None,  # set if you used a specific domain
        httponly=True,  # important if your token is httpOnly
    )
    return response

@router.get("/verify-email")
async def verify_email(token: str):
    user = await users_collection.find_one({"verification_token": token})
    if not user or user.get("verified"):
        return JSONResponse(status_code=400, content={"detail": "Invalid or expired verification link."})

    expiry = user.get("verification_token_expiry")
    if expiry and datetime.utcnow() > expiry:
        return JSONResponse(status_code=400, content={"detail": "Verification link expired."})

    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"verified": True},
            "$unset": {"verification_token": "", "verification_token_expiry": ""}
        }
    )

    return JSONResponse({"message": "Email verified successfully."})

@router.post("/resend-verification")
async def resend_verification(data: dict):
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    user = await users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.get("verified"):
        raise HTTPException(status_code=400, detail="Email already verified.")

    # Generate new token and expiry
    verification_token = secrets.token_urlsafe(32)
    verification_token_expiry = datetime.utcnow() + timedelta(hours=1)
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "verification_token": verification_token,
                "verification_token_expiry": verification_token_expiry
            }
        }
    )
    verification_link = f"{FRONTEND_URL}/verify-email?token={verification_token}"
    await send_verification_email(email, verification_link)
    return {"message": "Verification email resent. Please check your inbox."}
