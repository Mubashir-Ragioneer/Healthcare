# app/services/chat_engine.py

from openai import OpenAI
from app.core.config import settings
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from uuid import uuid4
import asyncio

# MongoDB connection
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)

def chat_with_assistant(messages: List[Dict[str, Any]], user_id: str) -> str:
    # Add timestamp to each message
    timestamped_msgs = [
        {**msg, "timestamp": datetime.utcnow().isoformat()} for msg in messages
    ]

    # Query model
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )

    reply = response.choices[0].message.content
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    # Async logging to MongoDB
    async def log_to_db():
        await conversations.update_one(
            {"user_id": user_id},
            {
                "$set": {"last_updated": datetime.utcnow()},
                "$setOnInsert": {
                    "created_at": datetime.utcnow(),
                    "conversation_id": str(uuid4()),
                    "user_id": user_id
                },
                "$push": {"messages": {"$each": timestamped_msgs + [reply_msg]}}
            },
            upsert=True
        )

    asyncio.create_task(log_to_db())
    return reply
