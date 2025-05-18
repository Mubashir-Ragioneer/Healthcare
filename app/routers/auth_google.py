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
        # Verify OAuth flow and retrieve user info
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve user info")

        email = user_info["email"]
        name = user_info.get("name")
        picture = user_info.get("picture")

        # Store or update user in MongoDB
        user_collection = db["users"]
        existing_user = await user_collection.find_one({"email": email})
        if not existing_user:
            await user_collection.insert_one({
                "email": email,
                "name": name,
                "picture": picture,
                "provider": "google"
            })

        # Issue JWT token for the user
        jwt_token = create_jwt_token({"sub": email})
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "user": {
                "email": email,
                "name": name,
                "picture": picture
            }
        }

    except OAuthError as e:
        logging.error(f"OAuth error: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth Error: {e}")

    except Exception as e:
        logging.error(f"Unexpected error during callback: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
