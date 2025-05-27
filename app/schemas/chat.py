# app/schemas/chat.py
from pydantic import BaseModel
from typing import Literal, List, Optional, Dict, Any

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
    conversation_id: str

class NewChatRequest(BaseModel):
    user_id: str

class NewChatResponse(BaseModel):
    conversation_id: str
    chat_title: str

class ChatModelOutput(BaseModel):
    reply: str
    chat_title: str
