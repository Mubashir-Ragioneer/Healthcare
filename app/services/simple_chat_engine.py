# app/services/simple_chat_engine.py

from openai import OpenAI
from app.core.config import settings
from motor.motor_asyncio import AsyncIOMotorClient
from uuid import uuid4
from datetime import datetime
import asyncio
import json
from typing import List, Dict, Optional, Any

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)

def generate_timestamped_msgs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {**msg, "timestamp": datetime.utcnow().isoformat()}
        for msg in messages
    ]

async def get_llm_config() -> dict:
    cfg = await db["llm_settings"].find_one({"_id": "config"}) or {}
    return {
        "model": cfg.get("model", "gpt-4o"),
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 400),
        "prompt": cfg.get("prompt", "You are a helpful assistant. Reply in JSON: {\"reply\": ..., \"chat_title\": ...}")
    }

async def simple_chat_with_assistant(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None
) -> Dict[str, str]:

    cfg = await get_llm_config()
    system_prompt = {"role": "system", "content": cfg["prompt"]}

    prior_messages = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conversation_id})
        if convo and "messages" in convo:
            prior_messages = convo["messages"]

    # Convert messages to dictionaries if they are Pydantic models
    message_dicts = []
    for msg in messages:
        if hasattr(msg, 'model_dump'):
            message_dicts.append(msg.model_dump())
        else:
            message_dicts.append(msg)

    final_messages = [system_prompt] + prior_messages + message_dicts

    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=final_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"]
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI error: {str(e)}")

    reply_raw = response.choices[0].message.content

    try:
        parsed = json.loads(reply_raw)
        reply = parsed["reply"]
        chat_title = parsed.get("chat_title", "New Conversation")
    except Exception as e:
        raise RuntimeError(f"Failed to parse JSON from LLM: {str(e)}")

    timestamped_msgs = generate_timestamped_msgs(messages)
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    async def save():
        if conversation_id:
            await conversations.update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {"last_updated": datetime.utcnow()},
                    "$push": {"messages": {"$each": timestamped_msgs + [reply_msg]}}
                }
            )
        else:
            await conversations.insert_one({
                "conversation_id": str(uuid4()),
                "user_id": user_id,
                "chat_title": chat_title,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": timestamped_msgs + [reply_msg]
            })

    asyncio.create_task(save())

    return {
        "reply": reply,
        "chat_title": chat_title,
        "conversation_id": conversation_id or "new"
    }
