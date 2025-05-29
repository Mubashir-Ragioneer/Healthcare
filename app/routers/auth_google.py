# app/routers/auth_google.py

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import RedirectResponse
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth
from app.db.mongo import db
from app.core.jwt import create_jwt_token
from app.core.config import settings, FRONTEND_URLS
import logging
from urllib.parse import urlparse, urlencode, unquote

router = APIRouter(tags=["auth"])

config = Config(".env")

oauth = OAuth(config)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    client_kwargs={"scope": "openid email profile"},
)

def get_frontend_url(request: Request) -> str:
    """
    Detects the frontend URL from query param (?origin=) or Referer header.
    Falls back to settings.FRONTEND_URL.
    """
    origin = request.query_params.get("origin")
    if origin and origin.startswith("http"):
        return origin.rstrip("/")

    referer = request.headers.get("referer")
    if referer and referer.startswith("http"):
        parsed = urlparse(referer)
        return f"{parsed.scheme}://{parsed.netloc}"

    # Fallback to first allowed frontend
    return FRONTEND_URLS[0]

@router.get("/login/google")
async def login_with_google(request: Request):
    frontend_url = get_frontend_url(request)
    logging.info(f"Detected frontend_url: {frontend_url}")

    redirect_uri = settings.GOOGLE_REDIRECT_URI
    state = urlencode({"origin": frontend_url})
    logging.info(f"Redirecting to Google OAuth with redirect_uri={redirect_uri} and state={state}")

    return await oauth.google.authorize_redirect(request, redirect_uri, state=state)

@router.get("/callback/auth", name="auth_callback")
async def auth_callback(request: Request):
    """
    Handles the OAuth2 callback from Google. Reads the original frontend URL from state param.
    """
    try:
        # 1. OAuth flow
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve user info")

        email = user_info["email"]
        name = user_info.get("name")
        picture = user_info.get("picture")

        user_collection = db["users"]

        # 2. Upsert user document
        await user_collection.update_one(
            {"email": email},
            {
                "$setOnInsert": {
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "provider": "google",
                    "role": "user",
                }
            },
            upsert=True
        )

        # 3. Get user, check for diagnosis
        user = await user_collection.find_one({"email": email})
        needs_profile_completion = not bool(user.get("diagnosis"))

        jwt_payload = {
            "sub": user["email"],
            "email": user["email"],
            "name": user.get("name", ""),
            "role": user.get("role", "user"),
            "needs_profile_completion": needs_profile_completion
        }
        jwt_token = create_jwt_token(jwt_payload)

        # 4. Parse frontend_url from state param
        state = request.query_params.get("state", "")
        frontend_url = FRONTEND_URLS[0]  # default
        try:
            state_params = dict(pair.split('=') for pair in state.split('&') if '=' in pair)
            if "origin" in state_params and state_params["origin"].startswith("http"):
                candidate_url = unquote(state_params["origin"])
                if candidate_url in FRONTEND_URLS:
                    frontend_url = candidate_url
                else:
                    logging.warning(f"Candidate frontend_url '{candidate_url}' not in allowed list, using default.")
        except Exception as e:
            logging.warning(f"Failed to parse state param for frontend_url: {e}")

        # 5. Redirect to frontend with token
        return RedirectResponse(
            url=f"{frontend_url}/login?token={jwt_token}",
            status_code=302
        )

    except Exception as e:
        logging.exception("Google OAuth callback failed")
        raise HTTPException(status_code=500, detail=str(e))
