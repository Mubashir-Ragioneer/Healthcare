# app/services/chat_engine.py

from openai import OpenAI
from app.core.config import settings
from app.services.vector_search import search_similar_chunks
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from uuid import uuid4
from typing import List, Dict, Any, Optional
import asyncio
import json
import os
import logging
# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
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
        "prompt": cfg.get("prompt", "You are a helpful healthcare assistant. Always reply in JSON format: {\"reply\": ..., \"chat_title\": ...}")
    }

async def chat_with_assistant(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None
) -> Dict[str, str]:
    query = messages[-1]["content"]

    # 🔍 Retrieve semantic context
    matches = await search_similar_chunks(query)
    context_chunks = [match["metadata"]["chunk_text"] for match in matches]
    
    # ⚙️ Model settings
    cfg = await get_llm_config()

    # 🧠 System prompt with context
    context_block = "\n--\n".join(context_chunks[:3])
    #print("retrieval:", context_block)
    logging.info("retrieval:", context_block)
    system_prompt = {
        "role": "system",
        "content": f"{cfg['prompt']}\n\nRelevant context:\n{context_block}"
    }

    # ⏪ Optional: include prior conversation
    prior_messages = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conversation_id})
        if convo and "messages" in convo:
            prior_messages = convo["messages"]

    # 📨 Compose final message sequence
    final_messages = [system_prompt] + prior_messages + messages

    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=final_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"]
        )
    except Exception as e:
        print("❌ OpenAI API error:", str(e))
        raise RuntimeError("LLM call failed")

    # 📦 Parse structured JSON reply
    reply_raw = response.choices[0].message.content
    print("🪵 Raw LLM response:", repr(reply_raw))
    logging.info("🪵 Raw LLM response:", repr(reply_raw))

    try:
        parsed = json.loads(reply_raw)
        if not isinstance(parsed, dict):
            raise TypeError("Expected a JSON object")
        reply = parsed["reply"]
        chat_title = parsed.get("chat_title", "New Conversation")
    except Exception as e:
        print("❌ Failed to parse JSON:", str(e))
        raise RuntimeError("Invalid JSON from LLM")

    # 🧾 Save messages with timestamps
    timestamped_msgs = generate_timestamped_msgs(messages)
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    async def log_to_db():
        if conversation_id:
            await conversations.update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {
                        "last_updated": datetime.utcnow(),
                        "chat_title": chat_title  # ✅ Fix: persist the updated chat_title
                    },
                    "$push": {
                        "messages": {"$each": timestamped_msgs + [reply_msg]}
                    }
                }
            )
        else:
            new_convo = {
                "conversation_id": str(uuid4()),
                "user_id": user_id,
                "chat_title": chat_title,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": timestamped_msgs + [reply_msg]
            }
            await conversations.insert_one(new_convo)
            
    asyncio.create_task(log_to_db())

    return {
        "reply": reply,
        "chat_title": chat_title,
        "conversation_id": conversation_id or "new"
    }
