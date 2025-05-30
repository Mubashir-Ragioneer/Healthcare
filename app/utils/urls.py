# app/utils/url.py
from typing import Optional
from fastapi import Request
from app.core.config import FRONTEND_URLS

def detect_frontend_url(request: Request) -> str:
    origin = request.query_params.get("origin")
    referer = request.headers.get("referer")
    if origin and origin.startswith("http"):
        return origin.rstrip("/")
    if referer and referer.startswith("http"):
        return referer.rstrip("/").split("?")[0]
    return FRONTEND_URLS[0]
