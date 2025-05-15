# app/routers/auth_google.py

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth, OAuthError
from app.db.mongo import db
from app.core.jwt import create_jwt_token  # Update path based on your app

router = APIRouter(tags=["auth"])

config = Config(".env")

oauth = OAuth(config)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=config("GOOGLE_CLIENT_ID"),
    client_secret=config("GOOGLE_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)

@router.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback/auth", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        email = user_info["email"]

        # Optional: Store or update user in MongoDB
        user_collection = db["users"]
        existing_user = await user_collection.find_one({"email": email})
        if not existing_user:
            await user_collection.insert_one({
                "email": email,
                "name": user_info.get("name"),
                "picture": user_info.get("picture"),
                "provider": "google"
            })

        jwt_token = create_jwt_token({"sub": email})
        return {"access_token": jwt_token, "token_type": "bearer"}

    except OAuthError as e:
        return {"error": str(e)}
