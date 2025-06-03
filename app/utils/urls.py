# app/utils/url.py

from typing import Optional
from fastapi import Request
from app.core.config import FRONTEND_URLS

def detect_frontend_url(request):
    origin = request.query_params.get("origin")
    if origin and origin.startswith("http") and origin.rstrip("/") in FRONTEND_URLS:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer and referer.startswith("http"):
        base = referer.split("?")[0].rstrip("/")
        if base in FRONTEND_URLS:
            return base
    return FRONTEND_URLS[0]  # fallback default