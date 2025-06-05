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
from fastapi import UploadFile, File, Form, Depends, BackgroundTasks
from app.schemas.chat import ChatModelOutput, Message, ChatRequest, NewChatResponse, NewChatRequest, ChatResponse
from pydantic import ValidationError      
from app.services.google import upload_file_to_drive


# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
conversations = db["conversations"]

UPLOAD_DIR = os.path.abspath("app/uploads")

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
    text_prompt: str = "What's in this image?"
):
    conv_id = conversation_id or str(uuid4())

    # 1. Save the image locally (for upload and for base64 conversion)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = image_file.filename.split('.')[-1]
    local_filename = f"{uuid4()}.{ext}"
    local_path = os.path.join(UPLOAD_DIR, local_filename)
    with open(local_path, "wb") as f:
        image_bytes = await image_file.read()
        f.write(image_bytes)

    # 2. Upload to Google Drive and get public URL
    public_url = upload_file_to_drive(local_path, image_file.filename)

    # 3. Prepare message for OpenAI (use base64 inline, but not for DB)
    with open(local_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")

    user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{ext};base64,{base64_image}",
                },
            },
        ],
        "image_url": public_url,  # This goes in Mongo for the frontend
        "timestamp": datetime.utcnow().isoformat(),
    }

    # 4. Gather previous messages for context, use only text or image links for context
    prior = []
    convo = None
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conv_id})
        if convo and "messages" in convo:
            prior = convo["messages"]

    # Build context for OpenAI (strip any prior base64 from history)
    messages = []
    for msg in prior:
        safe_content = []
        if isinstance(msg.get("content"), str):
            safe_content = msg["content"]
        elif isinstance(msg.get("content"), list):
            # Only keep text and URLs, never old base64
            for item in msg["content"]:
                if item.get("type") == "text":
                    safe_content.append(item)
                elif item.get("type") == "image_url":
                    # Use only if it's a public URL (not base64)
                    img_url = item.get("image_url", {}).get("url", "")
                    if img_url and img_url.startswith("http"):
                        safe_content.append(item)
        else:
            continue

        messages.append({"role": msg["role"], "content": safe_content})

    # Add this message (with base64 for LLM call)
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{ext};base64,{base64_image}",
                },
            },
        ],
    })

    # 5. Call OpenAI Vision API
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1",  # or gpt-4o if your org is enabled
            messages=messages,
            max_tokens=400
        )
    except Exception as e:
        # Clean up file before raising
        try:
            os.remove(local_path)
        except Exception:
            pass
        raise RuntimeError(f"OpenAI Vision API call failed: {str(e)}")

    reply = completion.choices[0].message.content
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # 6. Store only Google Drive link (never base64) in MongoDB
    mongo_user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "url": public_url}
        ],
        "image_url": public_url,
        "timestamp": user_msg["timestamp"],
    }

    async def _log():
        if conversation_id and convo:
            await conversations.update_one(
                {"conversation_id": conv_id},
                {
                    "$set": {
                        "last_updated": datetime.utcnow(),
                        "chat_title": "Image Analysis"
                    },
                    "$push": {"messages": {"$each": [mongo_user_msg, reply_msg]}}
                }
            )
        else:
            new_convo = {
                "conversation_id": conv_id,
                "user_id": user_id,
                "chat_title": "Image Analysis",
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "messages": [mongo_user_msg, reply_msg]
            }
            await conversations.insert_one(new_convo)

    import asyncio
    asyncio.create_task(_log())

    # 7. Clean up temp file
    try:
        os.remove(local_path)
    except Exception:
        pass

    return {
        "reply": reply,
        "chat_title": "Image Analysis",
        "conversation_id": conv_id,
        "image_url": public_url,  # Frontend can use this to display/download the image
    }


async def process_and_log_image_chat_message(
    image_bytes, ext, orig_filename, prompt, user_id, conv_id, reply
):
    # 1. Save to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    local_filename = f"{uuid4()}.{ext}"
    local_path = os.path.join(UPLOAD_DIR, local_filename)
    with open(local_path, "wb") as f:
        f.write(image_bytes)

    # 2. Upload to Google Drive
    public_url = upload_file_to_drive(local_path, orig_filename)

    # 3. Prepare chat message for MongoDB (no base64, only Drive URL)
    mongo_user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "url": public_url}
        ],
        "image_url": public_url,
        "timestamp": datetime.utcnow().isoformat(),
    }
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # 4. Logging: Save to MongoDB (thread-safe)
    from app.services.chat_engine import conversations  # Ensure this import works as expected
    convo = await conversations.find_one({"conversation_id": conv_id})
    if convo:
        await conversations.update_one(
            {"conversation_id": conv_id},
            {
                "$set": {
                    "last_updated": datetime.utcnow(),
                    "chat_title": "Image Analysis"
                },
                "$push": {"messages": {"$each": [mongo_user_msg, reply_msg]}}
            }
        )
    else:
        new_convo = {
            "conversation_id": conv_id,
            "user_id": user_id,
            "chat_title": "Image Analysis",
            "created_at": datetime.utcnow(),
            "last_updated": datetime.utcnow(),
            "messages": [mongo_user_msg, reply_msg]
        }
        await conversations.insert_one(new_convo)

    # 5. Cleanup local file
    try:
        os.remove(local_path)
    except Exception:
        pass