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

async def get_llm_settings() -> dict:
    return await db["llm_settings"].find_one({"_id": "config"}) or {}

async def chat_with_assistant(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None
) -> Dict[str, str]:
    query = messages[-1]["content"]

    # 🔍 Retrieve semantic context
    matches = await search_similar_chunks(query, user_id=user_id)
    context_chunks = [match["metadata"]["chunk_text"] for match in matches]

    # ⚙️ Model settings
    llm_config = await get_llm_settings()
    model = llm_config.get("model", "gpt-4o")
    temperature = llm_config.get("temperature", 0.3)
    max_tokens = llm_config.get("max_tokens", 400)

    # 🧠 System prompt
    system_prompt = {
        "role": "system",
        "content": """You are a helpful healthcare assistant.

        Always respond in **this exact JSON format**:

        {
            "reply": "your helpful reply",
            "chat_title": "brief title like 'Fever Symptoms' or 'New Conversation'"
        }
        Do not include anything else except this JSON response.

        Relevant context:\n""" + "\n--\n".join(context_chunks[:3]
        )
    }

    # 👇 Optionally fetch previous conversation
    prior_messages = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conversation_id})
        if convo and "messages" in convo:
            prior_messages = convo["messages"]

    final_messages = [system_prompt] + prior_messages + messages

    try:
        response = client.chat.completions.create(
            model=model,
            messages=final_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        print("❌ OpenAI API error:", str(e))
        raise RuntimeError("LLM call failed")

    reply_raw = response.choices[0].message.content
    print("🪵 Raw LLM response:", repr(reply_raw))

    try:
        parsed = json.loads(reply_raw)
        if not isinstance(parsed, dict):
            raise TypeError("Expected a JSON object")
        reply = parsed["reply"]
        chat_title = parsed.get("chat_title", "New Conversation")
    except Exception as e:
        print("❌ Failed to parse JSON:", str(e))
        raise RuntimeError("Invalid JSON from LLM")

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
                    "$set": {"last_updated": datetime.utcnow()},
                    "$push": {"messages": {"$each": timestamped_msgs + [reply_msg]}}
                }
            )
        else:
            new_conversation_id = str(uuid4())
            await conversations.insert_one({
                "conversation_id": new_conversation_id,
                "user_id": user_id,
                "chat_title": chat_title,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": timestamped_msgs + [reply_msg]
            })

    asyncio.create_task(log_to_db())

    return {
        "reply": reply,
        "chat_title": chat_title,
        "conversation_id": conversation_id or "new"
    }
