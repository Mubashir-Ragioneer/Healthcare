# app/routers/deps.py

from fastapi import Depends, HTTPException, status
from jose import jwt, JWTError
from app.core.config import settings
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Security

bearer_scheme = HTTPBearer()

def get_current_user(token: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> dict:
    try:
        payload = jwt.decode(token.credentials, settings.SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": user_id, "role": role}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )


def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
