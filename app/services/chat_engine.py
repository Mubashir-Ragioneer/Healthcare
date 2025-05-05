# app/services/chat_engine.py

from openai import OpenAI
from app.core.config import settings
from app.services.vector_search import search_similar_chunks
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from uuid import uuid4
from typing import List, Dict, Any
import asyncio

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)

async def get_llm_settings():
    doc = await db["llm_settings"].find_one({"_id": "config"})
    return doc or {}

async def chat_with_assistant(messages: List[Dict[str, Any]], user_id: str) -> str:
    query = messages[-1]["content"]

    # 🔁 Reuse Pinecone context retrieval from vector_search
    matches = await search_similar_chunks(query, user_id=user_id)
    context_chunks = [match["metadata"]["chunk_text"] for match in matches]

    # ⚙️ Load dynamic model settings
    llm_settings = await get_llm_settings()
    system_prompt_text = llm_settings.get("system_prompt", "You are a helpful healthcare assistant. Respond clearly and briefly.")
    model = llm_settings.get("model", "gpt-4o")
    temperature = llm_settings.get("temperature", 0.3)
    max_tokens = llm_settings.get("max_tokens", 400)

    # 🧠 Construct final prompt with system + context
    system_prompt = {
        "role": "system",
        "content": system_prompt_text + "\n\nRelevant context:\n" + "\n---\n".join(context_chunks[:3])
    }
    final_messages = [system_prompt] + messages

    # 🔮 Get response from LLM
    response = client.chat.completions.create(
        model=model,
        messages=final_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    reply = response.choices[0].message.content
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    timestamped_msgs = [
        {**msg, "timestamp": datetime.utcnow().isoformat()} for msg in messages
    ]

    async def log_to_db():
        await conversations.update_one(
            {"user_id": user_id},
            {
                "$set": {"last_updated": datetime.utcnow()},
                "$setOnInsert": {
                    "conversation_id": str(uuid4()),
                    "created_at": datetime.utcnow(),
                    "user_id": user_id,
                },
                "$push": {"messages": {"$each": timestamped_msgs + [reply_msg]}}
            },
            upsert=True
        )

    asyncio.create_task(log_to_db())

    return reply
