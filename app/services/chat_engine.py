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
import re
import tempfile
import os
import base64
import tiktoken
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

def extract_text_from_content(content):
    """Extracts all text from an OpenAI message content (supports string or list for multimodal)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Join all 'text' fields together for retrieval
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


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
def count_tokens_openai(messages, model="gpt-4o"):
    """
    Counts the number of tokens for OpenAI chat API messages using tiktoken.
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    tokens_per_message = 3  # According to OpenAI docs for chat API
    tokens_per_name = 1
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if key == "content":
                if isinstance(value, str):
                    num_tokens += len(enc.encode(value))
                elif isinstance(value, list):
                    for part in value:
                        if isinstance(part, dict):
                            for v in part.values():
                                if isinstance(v, str):
                                    num_tokens += len(enc.encode(v))
            elif key == "name":
                num_tokens += tokens_per_name
            elif isinstance(value, str):
                num_tokens += len(enc.encode(value))
    num_tokens += 3  # Every reply is primed with <im_start>assistant
    return num_tokens

async def chat_with_assistant(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None
) -> Dict[str, str]:
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
    final_messages = [system_prompt] + messages

    model = cfg.get("model", "gpt-4o")
    # These limits are up to date for gpt-4o/gpt-4
    max_model_tokens = 128000 if "gpt-4o" in model else 8192
    n_tokens = count_tokens_openai(final_messages, model=model)
    logging.info(f"Token count for chat_with_assistant (model={model}): {n_tokens}")

    if n_tokens > max_model_tokens:
        logging.error(
            f"Token count {n_tokens} exceeds max for model {model} ({max_model_tokens})."
        )
        return {
            "reply": "Sorry, your message or file/image is too large for the AI model. Please try a smaller file or shorter message.",
            "chat_title": "New Conversation",
            "conversation_id": conv_id,
        }

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

def get_direct_drive_image_url(share_link):
    # Extract file ID from Google Drive share link
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", share_link)
    if not match:
        return share_link  # fallback
    file_id = match.group(1)
    return f"https://drive.google.com/uc?export=view&id={file_id}"

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
    direct_image_url = get_direct_drive_image_url(public_url)

    # 3. Prepare chat message for MongoDB (no base64, only Drive URL)
    mongo_user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "url": direct_image_url}
        ],
        "image_url": direct_image_url,
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


async def process_and_log_file_chat_message(
    file_bytes, ext, orig_filename, mime_type, prompt, user_id, conv_id, reply
):
    # 1. Save to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    local_filename = f"{uuid4()}.{ext}"
    local_path = os.path.join(UPLOAD_DIR, local_filename)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    # 2. Upload to Google Drive
    public_url = upload_file_to_drive(local_path, orig_filename)

    # 3. Prepare chat message for MongoDB (no base64, only Drive URL)
    mongo_user_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "file", "url": public_url, "filename": orig_filename, "mime_type": mime_type}
        ],
        "file_url": public_url,
        "timestamp": datetime.utcnow().isoformat(),
    }
    reply_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # 4. Logging: Save to MongoDB (thread-safe)
    convo = await conversations.find_one({"conversation_id": conv_id})
    if convo:
        await conversations.update_one(
            {"conversation_id": conv_id},
            {
                "$set": {
                    "last_updated": datetime.utcnow(),
                    "chat_title": "File Analysis"
                },
                "$push": {"messages": {"$each": [mongo_user_msg, reply_msg]}}
            }
        )
    else:
        new_convo = {
            "conversation_id": conv_id,
            "user_id": user_id,
            "chat_title": "File Analysis",
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
