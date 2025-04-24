# app/main.py

from fastapi import FastAPI
from app.core.config import settings
from app.db.mongo import client
from app.routers import chat_admin
from app.routers import (
    admin,
    chat,
    doctor,
    ingest,
    receptionist,
    exam,
    quotation,
)
# from fastapi.middleware.cors import CORSMiddleware

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[settings.FRONTEND_URL],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


app = FastAPI(
    title="Healthcare AI Assistant",
    version="0.1.0",
    description="Backend for the Healthcare AI chatbot platform",
)

@app.get(
    "/",
    tags=["root"],
    summary="Health check",
)
async def root():
    """
    Simple health-check endpoint.
    """
    return {"status": "ok", "service": "Healthcare AI Assistant"}

# Mount routers under their top-level prefixes:
app.include_router(admin.router,        prefix="/admin")       # → /admin/llm
app.include_router(chat.router,         prefix="/chat")
app.include_router(doctor.router,       prefix="/doctors")
app.include_router(ingest.router,       prefix="/ingest")
app.include_router(receptionist.router, prefix="/reception")
app.include_router(exam.router,         prefix="/exam")
app.include_router(quotation.router,    prefix="/quote")
app.include_router(chat_admin.router)

@app.on_event("shutdown")
async def shutdown_db():
    """
    Close MongoDB client on shutdown.
    """
    client.close()
