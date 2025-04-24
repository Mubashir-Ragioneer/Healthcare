# app/routers/chat.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, List
from app.services.chat_engine import chat_with_assistant
from bson import ObjectId
from fastapi.responses import JSONResponse
from app.services.chat_engine import conversations  # ensure this is imported
import traceback


router = APIRouter(tags=["chat"])

class Message(BaseModel):
    role: Literal["user", "assistant"] = Field(
        ..., description="Role of the message sender"
    )
    content: str = Field(..., description="Message content")

class ChatRequest(BaseModel):
    messages: List[Message] = Field(
        ..., description="List of messages in the conversation so far"
    )
    user_id: str = Field(..., description="Identifier for the user session")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="The assistant’s reply")


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Send a chat message and receive a reply",
)
async def chat_endpoint(request: ChatRequest):
    """
    Forward the conversation to the LLM and return its reply.
    """
    try:
        msgs = [msg.dict() for msg in request.messages]
        # ❗ No await here anymore
        reply_text = await chat_with_assistant(msgs, request.user_id)

        return ChatResponse(reply=reply_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/history/{user_id}",
    summary="Get full chat history for a user",
)
async def get_chat_history(user_id: str):
    try:
        convo = await conversations.find_one({"user_id": user_id})
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Optional safety fallback
        convo["_id"] = str(convo.get("_id", ""))
        convo["created_at"] = convo.get("created_at", "").isoformat() if convo.get("created_at") else None
        convo["last_updated"] = convo.get("last_updated", "").isoformat() if convo.get("last_updated") else None

        for msg in convo.get("messages", []):
            if "timestamp" in msg and hasattr(msg["timestamp"], "isoformat"):
                msg["timestamp"] = msg["timestamp"].isoformat()

        return JSONResponse(content=convo)

    except Exception as e:
        print("❌ Error in get_chat_history():", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Server error while retrieving chat history")
