# app/service/chat_engine.py


from openai import OpenAI
from app.core.config import settings
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from uuid import uuid4
import asyncio
from app.db.pinecone import index
from app.db.mongo import get_db  # assuming you have a db helper

async def get_llm_settings():
    doc = await db["llm_settings"].find_one({"_id": "config"})  # <- required to match admin.py
    return doc or {}


# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)

# Get OpenAI embedding
async def get_openai_embedding(text: str) -> list[float]:
    res = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return res.data[0].embedding

# Retrieve top-k similar chunks from Pinecone
async def retrieve_similar_chunks(user_query: str, user_id: str, top_k: int = 5):
    embedding = await get_openai_embedding(user_query)
    result = index.query(
        vector=embedding,
        top_k=top_k,
        include_metadata=True,
        filter={"user_id": user_id}   # ✅ filter for just this user's documents
    )
    return [match["metadata"]["chunk_text"] for match in result["matches"]]

# Core chat function
async def chat_with_assistant(messages: List[Dict[str, Any]], user_id: str) -> str:
    query = messages[-1]["content"]

    # ✅ Await the async function directly
    context_chunks = await retrieve_similar_chunks(query, user_id)

    llm_settings = await get_llm_settings()

    system_prompt_text = llm_settings.get("system_prompt", "You are a helpful healthcare assistant. Respond clearly and briefly.")
    model = llm_settings.get("model", "gpt-4")
    temperature = llm_settings.get("temperature", 0.7)
    max_tokens = llm_settings.get("max_tokens", 400)

    system_prompt = {
        "role": "system",
        "content": system_prompt_text + "\n\nRelevant context:\n" + "\n---\n".join(context_chunks[:3])
    }
    final_messages = [system_prompt] + messages

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

    # ✅ Async DB logging
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
