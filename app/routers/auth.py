# app/routers/auth.py

from fastapi import APIRouter, HTTPException, Depends, Body, Request
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings, FRONTEND_URLS
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
from app.utils.email import send_verification_email, send_password_reset_email
from app.services.google import post_to_google_sheets_signup
import os
import logging

FRONTEND_URL = os.getenv("FRONTEND_URL")

router = APIRouter(tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
users_collection = db["users"]
logger = logging.getLogger("auth")


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
    lead_source: str = Field("website", description="Where the user came from (e.g., 'website', 'nudii.com.br', etc.)")


class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ResetPasswordRequest(BaseModel):
    token: str
    email: EmailStr
    new_password: str

class ResendVerificationRequest(BaseModel):
    email: EmailStr

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# app/routers/auth.py

from fastapi import APIRouter, HTTPException, Depends, Body, Request
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings, FRONTEND_URLS
from app.db.mongo import users_collection
from app.utils.email import send_verification_email
from app.services.google import post_to_google_sheets_signup
from app.utils.errors import ConflictError
import jwt
from datetime import datetime, timedelta
import secrets
import logging

router = APIRouter(tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger("auth")

class UserSignup(BaseModel):
    full_name: str
    email: EmailStr
    phone_number: str
    password: str
    diagnosis: str  # "crohns", "colitis", "undiagnosed"
    lead_source: str = Field("website", description="Autodetected or provided (e.g., 'nudii.com.br')")

@router.post("/signup", summary="Create a new user")
async def signup(user: UserSignup, request: Request):
    # --- Lead Source Detection Logic ---
    lead_source = user.lead_source  # Default
    origin = request.query_params.get("origin")
    referer = request.headers.get("referer")

    if origin and origin.startswith("http"):
        lead_source = origin.split("//")[-1].split("/")[0]
    elif referer and referer.startswith("http"):
        lead_source = referer.split("//")[-1].split("/")[0]
    # else: keep default from user.lead_source

    # --- Duplicate Email Check ---
    existing = await users_collection.find_one({"email": user.email})
    if existing:
        raise ConflictError("Email already registered")

    # --- User Creation ---
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
        "role": "user",
        "verified": False,
        "verification_token": verification_token,
        "verification_token_expiry": verification_token_expiry,
        "lead_source": lead_source,
    }

    result = await users_collection.insert_one(user_doc)
    verification_link = f"{FRONTEND_URLS[0]}/verify-email?token={verification_token}&email={user.email}"

    # --- Push to Google Sheets (non-blocking failure) ---
    try:
        post_to_google_sheets_signup(user_doc)
    except Exception as e:
        logger.error(f"Google Sheets signup push failed: {e}", exc_info=True)

    # --- Send Verification Email ---
    try:
        await send_verification_email(user.email, verification_link)
    except Exception as e:
        await users_collection.delete_one({"_id": result.inserted_id})
        raise HTTPException(status_code=500, detail=f"Failed to send verification email: {e}")

    return {
        "message": "User registered successfully. Please check your email to verify your account.",
        "user": {
            "email": user.email,
            "verified": False,
            "lead_source": lead_source,
        }
    }

    
@router.post("/login", response_model=Token)
async def login(user: UserLogin, db: AsyncIOMotorDatabase = Depends(get_db)):
    logger.info(f"Attempting login for: {user.email}")

    existing_user = await db["users"].find_one({"email": user.email})
    logger.debug(f"Found user: {existing_user}")

    if not existing_user:
        logger.warning(f"User not found: {user.email}")
        raise UnauthorizedRequestError("Invalid credentials: User not found")

    # Google-only account: no password available for normal login
    if existing_user.get("provider") == "google" and "password" not in existing_user:
        logger.warning(f"Account registered via Google; password login not available for {user.email}")
        raise UnauthorizedRequestError("This account was registered via Google. Please use Google login.")

    # Block unverified users
    if not existing_user.get("verified", False):
        logger.warning(f"User not verified: {user.email}")
        raise UnauthorizedRequestError("Email not verified. Please check your inbox for a verification email.")

    logger.info("Verifying password...")
    if not verify_password(user.password, existing_user.get("password", "")):
        logger.warning(f"Password verification failed for: {user.email}")
        raise UnauthorizedRequestError("Invalid credentials: Password verification failed")

    try:
        logger.info(f"Creating access token for {user.email}")
        access_token = create_access_token(data={
            "sub": str(existing_user["_id"]),
            "email": existing_user["email"],
            "role": existing_user.get("role", "user")
        })
        logger.info(f"Login successful for: {user.email}")
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"Login error for {user.email}: {e}", exc_info=True)
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
    """
    Verify user email using the one-time token.
    On success, mark the user as verified and issue an access token.
    """
    user = await users_collection.find_one({"verification_token": token})
    if not user or user.get("verified", False):
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired verification link."})

    expiry = user.get("verification_token_expiry")
    if expiry and datetime.utcnow() > expiry:
        return JSONResponse(status_code=401, content={"detail": "Verification link expired."})

    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"verified": True},
            "$unset": {"verification_token": "", "verification_token_expiry": ""}
        }
    )

    access_token = create_access_token(data={
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user.get("role", "user")
    })
    return {
        "message": "Email verified successfully.",
        "access_token": access_token
    }

@router.post("/resend-verification")
async def resend_verification(
    req: ResendVerificationRequest,
    request: Request
):
    """
    Resend the email verification link to the user if not yet verified.
    The verification link respects ?origin param or Referer header if present.
    """
    email = req.email.strip().lower()
    logger.info(f"Resend verification requested for: {email}")

    user = await users_collection.find_one({"email": email})
    if not user:
        logger.warning(f"User not found for resend verification: {email}")
        return {
            "success": False,
            "message": "User not found."
        }

    if user.get("verified", False):
        logger.info(f"User already verified: {email}")
        return {
            "success": False,
            "message": "Your email is already verified. Please log in."
        }

    # --- Detect correct frontend for the link
    frontend_url = FRONTEND_URLS[0]  # Default
    origin = request.query_params.get("origin")
    referer = request.headers.get("referer")
    if origin and origin.startswith("http"):
        frontend_url = origin.rstrip("/")
    elif referer and referer.startswith("http"):
        frontend_url = referer.rstrip("/").split("?")[0]  # strip any query params

    # --- Generate new token and expiry
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

    verification_link = f"{frontend_url}/verify-email?token={verification_token}&email={user['email']}"

    try:
        await send_verification_email(email, verification_link)
        logger.info(f"Verification email sent to: {email} with link: {verification_link}")
        return {
            "success": True,
            "message": "Verification email sent successfully! Please check your inbox."
        }
    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to send verification email: {str(e)}"
        }

@router.post("/request-password-reset")
async def request_password_reset(
    req: ForgotPasswordRequest,
    request: Request
):
    """
    Sends a password reset link to the user's verified email.
    The link respects ?origin or Referer header for correct frontend domain.
    """
    email = req.email.strip().lower()
    logger.info(f"Password reset requested for: {email}")

    user = await users_collection.find_one({"email": email})

    # Strict validation
    if not user:
        logger.warning(f"Password reset failed - user not found: {email}")
        raise NotFoundError("No user found with this email.")

    if not user.get("verified", False):
        logger.warning(f"Password reset failed - user not verified: {email}")
        raise UnauthorizedRequestError("Email is not verified.")

    # --- Detect correct frontend for the link
    frontend_url = FRONTEND_URLS[0]
    origin = request.query_params.get("origin")
    referer = request.headers.get("referer")
    if origin and origin.startswith("http"):
        frontend_url = origin.rstrip("/")
    elif referer and referer.startswith("http"):
        frontend_url = referer.rstrip("/").split("?")[0]

    # --- Generate reset token
    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(hours=1)
    await users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "reset_token": token,
            "reset_token_expiry": expiry
        }}
    )

    reset_link = f"{frontend_url}/reset-password?token={token}&email={email}"

    try:
        from app.utils.email import send_password_reset_email
        await send_password_reset_email(email, reset_link)
        logger.info(f"Password reset email sent to {email} with link: {reset_link}")
        return {
            "success": True,
            "message": "Reset link sent. Please check your inbox."
        }
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send reset email: {e}")

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    user = await users_collection.find_one({"email": req.email})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid token or email.")

    if user.get("reset_token") != req.token:
        raise HTTPException(status_code=400, detail="Invalid reset token.")

    if datetime.utcnow() > user.get("reset_token_expiry", datetime.utcnow()):
        raise HTTPException(status_code=400, detail="Reset token has expired.")

    hashed = pwd_context.hash(req.new_password)

    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"password": hashed},
            "$unset": {"reset_token": "", "reset_token_expiry": ""}
        }
    )

    return {"success": True, "message": "Password reset successful. Please log in with your new password."}


@router.patch("/me/diagnosis", summary="Set diagnosis for logged-in user")
async def set_diagnosis(
    diagnosis: Literal["crohns", "colitis", "undiagnosed"] = Body(...),
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("user_id") or current_user.get("email")
    query = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"email": user_id}
    result = await users_collection.update_one(
        query,
        {"$set": {"diagnosis": diagnosis}}
    )
    if result.modified_count == 1:
        return format_response(success=True, message="Diagnosis updated")
    raise HTTPException(status_code=400, detail="Failed to update diagnosis")

@router.patch("/complete-profile", summary="Complete profile after Google login")
async def complete_profile(
    diagnosis: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    email = current_user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="User email missing from token.")
    await users_collection.update_one(
        {"email": email},
        {"$set": {"diagnosis": diagnosis}}
    )
    return {"success": True, "message": "Profile updated."}
