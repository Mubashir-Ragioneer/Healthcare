from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
from app.services.chat_engine import chat_with_assistant

router = APIRouter(prefix="/chat", tags=["chat"])

class Message(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Message content text")

class ChatRequest(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user session")
    messages: List[Message] = Field(..., description="List of chat messages in order")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="Assistant's reply to the chat request")

@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a list of messages to the assistant and get a reply."""
    try:
        # Convert Pydantic Message models to dicts for the engine
        message_dicts = [msg.dict() for msg in request.messages]
        reply_text = await chat_with_assistant(message_dicts, request.user_id)
        return ChatResponse(reply=reply_text)
    except Exception as e:
        # Log exception details in real implementation
        raise HTTPException(status_code=500, detail=f"Chat engine error: {e}")