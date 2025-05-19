# app/routers/chat.py
import os
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from fastapi.responses import JSONResponse
from uuid import uuid4
from datetime import datetime
from app.services.kommo import push_lead_to_kommo
from fastapi import Depends
from app.routers.deps import get_current_user
from app.services.chat_engine import chat_with_assistant, conversations
from fastapi import Form, UploadFile, File
from app.db.mongo import db
from bson import ObjectId
from app.db.mongo import conversation_collection
from app.utils.responses import format_response
from app.services.kommo import push_clinical_trial_lead, post_to_google_sheets
from app.services.find_specialist_engine import find_specialist_response
import logging

UPLOAD_DIR = os.path.abspath("app/uploads")

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
    #mode: Optional[str] = "ask_anything"  # ask_anything, find_specialist, find_test, have_ibd


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
@router.post("", response_model=ChatResponse, summary="Send a message and receive a reply")
async def chat_endpoint(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        msgs = [msg.dict() for msg in request.messages]

        result = await chat_with_assistant(
            messages=msgs,
            user_id=request.user_id,
            conversation_id=request.conversation_id
        )

        return ChatResponse(
            reply=result["reply"],
            chat_title=result["chat_title"]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/new", response_model=NewChatResponse, summary="Start a new chat thread")
async def start_new_chat(req: NewChatRequest, current_user: dict = Depends(get_current_user)):
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
async def get_chat_history(conversation_id: str, current_user: dict = Depends(get_current_user)):
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

@router.post("/clinical-trial", summary="Submit clinical trial intake form")
async def submit_clinical_trial(
    full_name: str = Form(...),
    diagnosis: str = Form(...),
    medications: Optional[str] = Form(""),
    test_results_description: Optional[str] = Form(""),
    lead_source: Optional[str] = Form("nudii.com.br"),
    test_results_file: Optional[UploadFile] = File(
        default=None,
        description="Optional: upload test result file (PDF, image, etc.)"
    ),
    current_user: dict = Depends(get_current_user)
):
    try:
        # Ensure upload directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # Handle file upload
        file_path = None
        if test_results_file:
            ext = test_results_file.filename.split(".")[-1]
            filename = f"{uuid4()}.{ext}"
            file_path = os.path.join(UPLOAD_DIR, filename)
            with open(file_path, "wb") as f:
                f.write(await test_results_file.read())

        # Prepare data
        form_data = {
            "full_name": full_name,
            "diagnosis": diagnosis,
            "medications": medications,
            "test_results_description": test_results_description,
            "lead_source": lead_source,
            "uploaded_file_path": file_path,
        }

        # Save in MongoDB
        await db["clinical_trial_uploads"].insert_one({
            **form_data,
            "submitted_at": datetime.utcnow()
        })

        # Send to integrations
        await push_clinical_trial_lead(form_data)
        post_to_google_sheets(form_data)

        return {
            "success": True,
            "message": "Clinical trial form submitted successfully"
        }

    except Exception as e:
        print("❌ Error in /clinical-trial:", str(e))
        raise HTTPException(status_code=500, detail="Submission failed")


@router.get("/conversations/{user_id}", summary="Get all conversations by user_id (email)")
async def get_user_conversations_by_id(user_id: str, current_user: dict = Depends(get_current_user)):
    try:
        convos = await conversations.find(
            {"user_id": user_id},
            {"_id": 1, "conversation_id": 1, "chat_title": 1, "created_at": 1}
        ).sort("created_at", -1).to_list(length=50)

        results = []
        for conv in convos:
            results.append({
                "conversation_id": conv.get("conversation_id"),
                "chat_title": conv.get("chat_title", "New Conversation"),
                "created_at": conv.get("created_at").isoformat() if conv.get("created_at") else None
            })

        return {
            "success": True,
            "data": {"conversations": results},
            "message": ""
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error fetching conversations")


@router.post("/find-specialist", summary="Suggest a specialist based on user query")
async def suggest_specialist(query: str = Body(...), current_user: dict = Depends(get_current_user)):
    answer = find_specialist_response(query)
    return {"reply": answer}

@router.delete("/delete/{conversation_id}", summary="Delete a conversation by ID")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    result = await conversations.delete_one({"conversation_id": conversation_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True, "message": "🗑️ Conversation deleted successfully"}
