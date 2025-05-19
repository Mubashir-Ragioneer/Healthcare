# app/routers/auth_google.py

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import RedirectResponse
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth, OAuthError
from app.db.mongo import db
from app.core.jwt import create_jwt_token
from app.core.config import settings
import logging

router = APIRouter(tags=["auth"])

# Load secrets from .env
config = Config(".env")

# OAuth config for Google
oauth = OAuth(config)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    client_kwargs={"scope": "openid email profile"},
)

@router.get("/login/google")
async def login_with_google(request: Request):
    # directly use the exact HTTPS URI you registered in Google
    redirect_uri = settings.GOOGLE_REDIRECT_URI  
    logging.info(f"Redirecting to Google OAuth with redirect_uri: {redirect_uri}")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback/auth", name="auth_callback")
async def auth_callback(request: Request):
    try:
        # 1) Complete the OAuth flow
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve user info")

        email   = user_info["email"]
        name    = user_info.get("name")
        picture = user_info.get("picture")

        # 2) Upsert your user
        user_collection = db["users"]
        await user_collection.update_one(
            {"email": email},
            {"$setOnInsert": {
                "email":   email,
                "name":    name,
                "picture": picture,
                "provider":"google"
            }},
            upsert=True
        )

        # 3) Issue your JWT
        jwt_token = create_jwt_token({"sub": email})

        # # ─── OPTION A: Set as HttpOnly cookie ────────────────────────
        # response = RedirectResponse(url=f"{settings.FRONTEND_URL}/ask-me-anything")
        # response.set_cookie(
        #     key="access_token",
        #     value=jwt_token,
        #     httponly=True,
        #     secure=True,
        #     samesite="lax",
        #     max_age=60 * 60 * 24 * 7,  # 1 week
        # )
        # return response

        # ─── OPTION B: Pass in query string ─────────────────────────
        redirect_url = f"{settings.FRONTEND_URL}/ask?token={jwt_token}"
        return RedirectResponse(url=redirect_url)

    except OAuthError as e:
        logging.error(f"OAuth error: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth Error: {e}")

    except Exception as e:
        logging.error(f"Unexpected error during callback: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")