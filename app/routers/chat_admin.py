# app/routers/chat_admin.py

from fastapi import APIRouter, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from typing import List, Optional
from datetime import datetime

router = APIRouter(
    prefix="/chat",
    tags=["admin", "chat-history"],
)

# MongoDB connection
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

@router.get("/history/{user_id}", summary="Get full chat history for a user")
async def get_chat_history(user_id: str):
    convo = await conversations.find_one({"user_id": user_id}, {"_id": 0})
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo

@router.get("/history", summary="List all chat conversations (admin view)")
async def list_all_conversations(limit: int = 50):
    cursor = conversations.find({}, {"_id": 0, "user_id": 1, "last_updated": 1}).sort("last_updated", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    return {
        "count": len(results),
        "conversations": results
    }
