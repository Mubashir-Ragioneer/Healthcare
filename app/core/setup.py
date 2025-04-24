app/core/setup.py
from fastapi import FastAPI
from app.api import chat, ingest, admin, doctor, receptionist

def setup_routers(app: FastAPI):
    app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingest"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    app.include_router(doctor.router, prefix="/api/doctor", tags=["Doctor"])
    app.include_router(receptionist.router, prefix="/api/receptionist", tags=["Receptionist"])

def startup_events(app: FastAPI):
    @app.on_event("startup")
    async def startup_hook():
        print("🚀 AI Medical Assistant is live.")
