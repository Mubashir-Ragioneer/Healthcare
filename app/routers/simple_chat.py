# app/routers/simple_chat.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi import Depends
from app.routers.deps import require_admin, get_current_user
from typing import List, Dict, Optional
from app.services.simple_chat_engine import simple_chat_with_assistant

router = APIRouter(tags=["simple_chat"])

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str
    conversation_id: Optional[str] = None

@router.post("/chat/simple", summary="Simple chat without RAG")
async def simple_chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        # Convert ChatMessage objects to dictionaries
        messages = [msg.model_dump() for msg in req.messages]
        result = await simple_chat_with_assistant(messages, req.user_id, req.conversation_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
