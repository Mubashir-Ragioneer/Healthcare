# app/routers/chat.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from fastapi.responses import JSONResponse
from uuid import uuid4
from datetime import datetime
from app.services.chat_engine import chat_with_assistant, conversations

router = APIRouter(tags=["chat"])

# ---------------------
# Request / Response Models
# ---------------------

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    user_id: str
    conversation_id: str

class ChatResponse(BaseModel):
    reply: str
    chat_title: str

class NewChatRequest(BaseModel):
    user_id: str

class NewChatResponse(BaseModel):
    conversation_id: str
    chat_title: str

# ---------------------
# Chat Routes
# ---------------------

@router.post("/", response_model=ChatResponse, summary="Send a message and receive a reply")
async def chat_endpoint(request: ChatRequest):
    try:
        msgs = [msg.dict() for msg in request.messages]
        result = await chat_with_assistant(msgs, request.user_id, request.conversation_id)

        return ChatResponse(reply=result["reply"], chat_title=result["chat_title"])

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/new", response_model=NewChatResponse, summary="Start a new chat thread")
async def start_new_chat(req: NewChatRequest):
    new_id = str(uuid4())
    convo = {
        "user_id": req.user_id,
        "conversation_id": new_id,
        "chat_title": "New Conversation",
        "created_at": datetime.utcnow(),
        "last_updated": datetime.utcnow(),
        "messages": []
    }
    await conversations.insert_one(convo)
    return {"conversation_id": new_id, "chat_title": "New Conversation"}

@router.get("/history/{conversation_id}", summary="Get full conversation by ID")
async def get_chat_history(conversation_id: str):
    try:
        convo = await conversations.find_one({"conversation_id": conversation_id})
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")

        convo["_id"] = str(convo.get("_id", ""))
        for field in ["created_at", "last_updated"]:
            if convo.get(field):
                convo[field] = convo[field].isoformat()

        for msg in convo.get("messages", []):
            if "timestamp" in msg and hasattr(msg["timestamp"], "isoformat"):
                msg["timestamp"] = msg["timestamp"].isoformat()

        return JSONResponse(content=convo)

    except Exception as e:
        print("❌ Error in get_chat_history():", str(e))
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Server error while retrieving chat history")
