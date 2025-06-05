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
import time
import tempfile
import os
import base64
import logging
from fastapi import UploadFile
from app.schemas.chat import ChatModelOutput, Message, ChatRequest, NewChatResponse, NewChatRequest, ChatResponse
from pydantic import ValidationError          

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)

# Immutable system prompt segments
SYSTEM_PROMPT_HEAD = "You are a professional medical assistant."
SYSTEM_PROMPT_TAIL = (
    "Always reply in JSON matching exactly this schema: {\"reply\": <string>, \"chat_title\": <string>}"
    " If the user asks anything outside of medical assistance, return: {\"reply\": \"Sorry, I can only answer medical-assistance questions.\", \"chat_title\": \"New Conversation\"}"
)


def generate_timestamped_msgs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {**msg, "timestamp": datetime.utcnow().isoformat()}
        for msg in messages
    ]


async def get_llm_config() -> dict:
    # fetch admin's free-form prompt text from DB
    cfg = await db["llm_settings"].find_one({"_id": "config"}) or {}
    admin_text = cfg.get("prompt", "").strip()

    # splice head, admin instructions, and tail
    full_instruction = "\n".join([
        SYSTEM_PROMPT_HEAD,
        f"# Admin custom instructions:\n{admin_text}",
        SYSTEM_PROMPT_TAIL
    ])

    return {
        "model":       cfg.get("model", "gpt-4.1"),
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens":  cfg.get("max_tokens", 400),
        "prompt":      full_instruction,
    }

async def chat_with_assistant(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None
) -> Dict[str, str]:
    # assign or generate conversation_id
    conv_id = conversation_id or str(uuid4())

    # retrieve semantic context for the last user message
    recent_history = [msg["content"] for msg in messages[-5:] if msg["role"] == "user"]
    query = "\n".join(recent_history)
    matches = await search_similar_chunks(query)
    context_chunks = [m["metadata"]["chunk_text"] for m in matches]
    context_block = "\n--\n".join(context_chunks[:3])
    logging.info("Context retrieved: %s", context_block)

    # assemble the fixed + admin prompt
    cfg = await get_llm_config()

    # build labeled sections in system prompt
    sections = [
        f"### Retrieval Content:\n{context_block}",
        "### Previous Messages:",
    ]
    # flatten prior messages as simple text
    prior = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conv_id})
        if convo and "messages" in convo:
            prior = convo["messages"]
    for msg in prior:
        sections.append(f"- {msg['role']}: {msg['content']}")
    sections.append(f"### User Query:\n{query}")

    system_content = "\n\n".join([
        cfg['prompt'],
        "\n".join(sections)
    ])
    system_prompt = {"role": "system", "content": system_content}

    # compose conversation history and user input
    final_messages = [system_prompt] + messages

    # call OpenAI
    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=final_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"]
        )
    except Exception as e:
        logging.error("OpenAI API error: %s", e, exc_info=True)
        raise RuntimeError("LLM call failed")

    raw = response.choices[0].message.content
    logging.debug("LLM raw response: %s", raw)

    # enforce JSON schema via Pydantic
    try:
        out = ChatModelOutput.parse_raw(raw)
    except ValidationError:
        logging.error("Schema validation failed for LLM output: %s", raw)
        out = ChatModelOutput(
            reply="Sorry, I can only answer medical-assistance questions.",
            chat_title="New Conversation"
        )

    # prepare timestamped logging
    timestamped = generate_timestamped_msgs(messages)
    reply_msg = {"role": "assistant", "content": out.reply, "timestamp": datetime.utcnow().isoformat()}

    async def _log():
        if conversation_id:
            await conversations.update_one(
                {"conversation_id": conv_id},
                {"$set": {"last_updated": datetime.utcnow(), "chat_title": out.chat_title},
                 "$push": {"messages": {"$each": timestamped + [reply_msg]}}}
            )
        else:
            new_convo = {
                "conversation_id": conv_id,
                "user_id": user_id,
                "chat_title": out.chat_title,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": timestamped + [reply_msg]
            }
            await conversations.insert_one(new_convo)

    asyncio.create_task(_log())

    return {"reply": out.reply, "chat_title": out.chat_title, "conversation_id": conv_id}

async def chat_with_image_assistant(
    image_file,
    user_id: str,
    conversation_id: str = None,
    text_prompt: str = "What’s in this image?"
):
    conv_id = conversation_id or str(uuid4())

    # --- Prepare user message with image ---
    image_bytes = await image_file.read()
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}",
                },
            },
        ],
        "timestamp": datetime.utcnow().isoformat()
    }

    # --- Gather previous messages for context ---
    prior = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conv_id})
        if convo and "messages" in convo:
            prior = convo["messages"]

    # --- Compose OpenAI message list ---
    # Prior messages must be flattened as OpenAI expects (text only or text+image for user)
    messages = []
    for msg in prior:
        if msg["role"] == "user":
            # Just include prior text user messages, skip images for context
            if isinstance(msg["content"], str):
                messages.append({"role": "user", "content": msg["content"]})
            elif isinstance(msg["content"], list):
                # Assume any prior multimodal msg
                messages.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            messages.append({"role": "assistant", "content": msg["content"]})
    # Add the new user message (with image)
    messages.append(user_msg)

    # --- OpenAI API call ---
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1",  # or "gpt-4o" if vision enabled, adjust as needed
            messages=messages,
            max_tokens=400
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI Vision API call failed: {str(e)}")

    # --- Get reply ---
    reply = completion.choices[0].message.content
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    # --- Logging: Save to MongoDB ---
    async def _log():
        if conversation_id and convo:
            await conversations.update_one(
                {"conversation_id": conv_id},
                {"$set": {"last_updated": datetime.utcnow(), "chat_title": "Image Analysis"},
                 "$push": {"messages": {"$each": [user_msg, reply_msg]}}}
            )
        else:
            new_convo = {
                "conversation_id": conv_id,
                "user_id": user_id,
                "chat_title": "Image Analysis",
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": [user_msg, reply_msg]
            }
            await conversations.insert_one(new_convo)

    import asyncio
    asyncio.create_task(_log())

    return {
        "reply": reply,
        "chat_title": "Image Analysis",
        "conversation_id": conv_id,
    }