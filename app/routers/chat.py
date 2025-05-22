# app/routers/chat.py
import os, json
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Body, Depends
from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Dict, Any
from fastapi.responses import JSONResponse
from uuid import uuid4
from datetime import datetime
from app.services.kommo import push_lead_to_kommo
from app.routers.deps import get_current_user
from app.services.chat_engine import chat_with_assistant, conversations
from app.db.mongo import db
from bson import ObjectId
from app.db.mongo import conversation_collection
from app.utils.responses import format_response
from app.services.kommo import push_clinical_trial_lead, post_to_google_sheets
from app.services.find_specialist_engine import find_specialist_response
import logging
from app.schemas.specialist import FindSpecialistRequest, SpecialistSuggestion
import asyncio  # for async to_thread
from openai import OpenAI
from app.core.config import settings
from app.services.chat_engine import chat_with_assistant_file
import requests
import time
import tempfile


ASSEMBLYAI_API_KEY = "0dd308f8c94e4ec9840bbb0348adaad8"  # You should use an environment variable for security!


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

@router.post("/chat/audio", summary="Send audio and receive a reply")
async def chat_with_audio(
    audio: UploadFile = File(...),
    user_id: str = Form(...),
    conversation_id: str = Form(None),
    current_user: dict = Depends(get_current_user)
):
    # 1. Save audio to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        audio_bytes = await audio.read()
        tmp.write(audio_bytes)
        filename = tmp.name

    try:
        # 2. Upload audio to AssemblyAI
        base_url = "https://api.assemblyai.com"
        headers = {"authorization": ASSEMBLYAI_API_KEY}

        with open(filename, "rb") as f:
            upload_res = requests.post(f"{base_url}/v2/upload", headers=headers, data=f)
        if upload_res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Upload failed: {upload_res.text}")

        try:
            audio_url = upload_res.json().get("upload_url")
        except Exception:
            raise HTTPException(status_code=500, detail=f"Upload API did not return JSON: {upload_res.text}")

        # 3. Start transcription
        data = {"audio_url": audio_url, "speech_model": "universal"}
        transcript_res = requests.post(f"{base_url}/v2/transcript", json=data, headers=headers)
        if transcript_res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Transcription start failed: {transcript_res.text}")

        try:
            transcript_id = transcript_res.json()["id"]
        except Exception:
            raise HTTPException(status_code=500, detail=f"Transcription start did not return JSON: {transcript_res.text}")

        polling_endpoint = f"{base_url}/v2/transcript/{transcript_id}"

        # 4. Poll for transcription result
        transcribed_text = None
        for _ in range(60):  # max 2 minutes
            poll_res = requests.get(polling_endpoint, headers=headers)
            if poll_res.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Polling failed: {poll_res.text}")

            try:
                result = poll_res.json()
            except Exception:
                raise HTTPException(status_code=500, detail=f"Polling did not return JSON: {poll_res.text}")

            status = result.get('status')
            if status == 'completed':
                transcribed_text = result['text']
                break
            elif status == 'error':
                raise HTTPException(status_code=400, detail=f"Transcription failed: {result.get('error', 'unknown error')}")
            time.sleep(2)
        else:
            raise HTTPException(status_code=504, detail="Transcription timed out after 2 minutes.")

        # 5. Use transcribed text as the chat message!
        msgs = [{"role": "user", "content": transcribed_text}]

        # 6. Call your chat_with_assistant
        result = await chat_with_assistant(
            messages=msgs,
            user_id=user_id,
            conversation_id=conversation_id
        )

        return {
            "reply": result["reply"],
            "chat_title": result["chat_title"],
            "transcribed_text": transcribed_text
        }

    finally:
        # Clean up temp file
        os.remove(filename)

@router.post("/chat-with-file", summary="Chat with optional file input (OpenAI file_id method)")
async def chat_with_file(
    messages: str = Form(...),  # JSON stringified list of messages
    user_id: str = Form(...),
    conversation_id: str = Form(None),
    file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    # Parse JSON string of messages
    try:
        msgs = json.loads(messages)
        if not isinstance(msgs, list):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON for messages.")

    try:
        result = await chat_with_assistant_file(
            messages=msgs,
            user_id=user_id,
            conversation_id=conversation_id,
            file=file
        )
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-with-upload", summary="Send a message with file upload (OpenAI file_id method)")
async def chat_with_upload(
    user_id: str = Form(...),
    conversation_id: str = Form(...),
    messages: str = Form(...),  # JSON string of message dicts (text parts)
    file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    # Step 1: Parse messages
    try:
        msgs = json.loads(messages)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON for messages.")

    # Step 2: If file, upload to OpenAI and get file_id
    file_id = None
    if file:
        try:
            uploaded = client.files.create(
                file=file.file,  # FastAPI's UploadFile.file is a file-like object
                purpose="user_data"
            )
            file_id = uploaded.id
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"File upload to OpenAI failed: {e}")

    # Step 3: Build chat messages for OpenAI
    content_block = []
    if file_id:
        content_block.append({
            "type": "file",
            "file": {"file_id": file_id}
        })
    # Append all text and/or other messages provided
    for part in msgs:
        content_block.append(part)

    # Step 4: Send chat completion to OpenAI
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": content_block}
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI chat completion failed: {e}")

    reply = completion.choices[0].message.content
    return {"reply": reply, "file_id": file_id}


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


@router.post(
    "/find-specialist",
    response_model=SpecialistSuggestion,
    summary="Suggest a specialist based on user query"
)
async def suggest_specialist(
    payload: FindSpecialistRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        # Use to_thread to call your sync function in async route
        raw = await asyncio.to_thread(find_specialist_response, payload.query)
        return SpecialistSuggestion(**raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/delete/{conversation_id}", summary="Delete a conversation by ID")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    result = await conversations.delete_one({"conversation_id": conversation_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True, "message": "🗑️ Conversation deleted successfully"}
