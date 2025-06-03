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


async def chat_with_assistant_file(
    messages: List[Dict[str, Any]],
    user_id: str,
    conversation_id: Optional[str] = None,
    file: UploadFile = None
) -> Dict[str, str]:
    
    # 1. Retrieve semantic context
    query = ""
    for block in messages[-1]["content"]:
        if isinstance(block, dict) and block.get("type") == "text":
            query = block.get("text")
            break

    if not query:
        raise RuntimeError("No user text found for semantic search.")

    matches = await search_similar_chunks(query)

    context_chunks = [match["metadata"]["chunk_text"] for match in matches]
    cfg = await get_llm_config()

    # 2. Build system prompt with context
    context_block = "\n--\n".join(context_chunks[:3])
    system_prompt = {
        "role": "system",
        "content": f"{cfg['prompt']}\n\nRelevant context:\n{context_block}"
    }

    # 3. Get prior conversation messages if needed
    prior_messages = []
    if conversation_id:
        convo = await conversations.find_one({"conversation_id": conversation_id})
        if convo and "messages" in convo:
            prior_messages = convo["messages"]

    # 4. Prepare the user content block (file + text)
    content_block = []
    if file:
        try:
            suffix = "." + file.filename.split(".")[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await file.read())
                tmp.flush()
                tmp.seek(0)
                tmp_name = tmp.name

            with open(tmp_name, "rb") as f:
                uploaded = client.files.create(
                    file=f,
                    purpose="assistants",  # Must be 'assistants'
                )
                file_id = uploaded.id
                print("File uploaded to OpenAI:", file.filename, "ID:", file_id, "MIME type:", file.content_type)

            time.sleep(2)  # (rare, but can help w/ OpenAI file indexing lag)

            content_block.append({
                "type": "file",
                "file": {"file_id": file_id}
            })

        except Exception as e:
            logging.error("File upload to OpenAI failed: %s", str(e))
            raise RuntimeError(f"File upload to OpenAI failed: {e}")

    # 5. Add user text messages
    for msg in messages:
        if msg["role"] == "user":
            if isinstance(msg["content"], dict) and "type" in msg["content"]:
                content_block.append(msg["content"])
            else:
                content_block.append({"type": "text", "text": msg["content"]})

    # 6. Compose message sequence for OpenAI
    final_messages = [system_prompt] + prior_messages + [
        {"role": "user", "content": content_block}
    ]

    # 7. OpenAI chat call
    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=final_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"]
        )
    except Exception as e:
        print("OpenAI API error:", str(e))
        raise RuntimeError("LLM call failed")

    reply_raw = response.choices[0].message.content
    print("Raw LLM response:", repr(reply_raw))
    logging.info("Raw LLM response: %s", repr(reply_raw))

    try:
        parsed = json.loads(reply_raw)
        if not isinstance(parsed, dict):
            raise TypeError("Expected a JSON object")
        reply = parsed["reply"]
        chat_title = parsed.get("chat_title", "New Conversation")
    except Exception as e:
        print("Failed to parse JSON:", str(e))
        raise RuntimeError("Invalid JSON from LLM")

    # 8. Log to DB
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
                        "chat_title": chat_title
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
