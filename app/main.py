# app/main.pt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth  
from app.core.config import settings
from app.db.mongo import client, verify_mongodb_connection
from app.routers import (
    admin,
    chat,
    doctor,
    ingest,
    receptionist,
    exam,
    quotation,
    chat_admin,
)

# ✅ 1. Create app instance first
app = FastAPI(
    title="Healthcare AI Assistant",
    version="0.1.0",
    description="Backend for the Healthcare AI chatbot platform",
)

# ✅ 2. Add CORS middleware after app instantiation
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 3. Startup & shutdown hooks
@app.on_event("startup")
async def startup():
    await verify_mongodb_connection()

@app.on_event("shutdown")
async def shutdown_db():
    client.close()

# ✅ 4. Health check
@app.get("/", tags=["root"], summary="Health check")
async def root():
    return {"status": "ok", "service": "Healthcare AI Assistant"}

# ✅ 5. Register routes
app.include_router(auth.router,         prefix="/auth")  
app.include_router(admin.router,        prefix="/admin")
app.include_router(chat.router,         prefix="/chat")
app.include_router(doctor.router,       prefix="/doctors")
app.include_router(ingest.router,       prefix="/ingest")
app.include_router(receptionist.router, prefix="/reception")
app.include_router(exam.router,         prefix="/exam")
app.include_router(quotation.router,    prefix="/quote")
app.include_router(chat_admin.router)
