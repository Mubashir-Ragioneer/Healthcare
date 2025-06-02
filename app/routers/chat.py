# app/routers/chat.py

import os
import json
import asyncio
import tempfile
import logging
import time
from uuid import uuid4
from datetime import datetime
from typing import Literal, List, Optional, Dict, Any
from fastapi import (
    APIRouter,
    Form,
    File,
    UploadFile,
    HTTPException,
    Body,
    Depends,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from bson import ObjectId
from openai import OpenAI
import requests
from app.core.config import settings
from app.core.logger import logger
from app.db.mongo import (
    db,
    conversation_collection,
    specialist_history_collection,
)
from app.routers.deps import get_current_user
from app.schemas.chat import (
    ChatModelOutput,
    Message,
    ChatRequest,
    NewChatResponse,
    NewChatRequest,
    ChatResponse,
)
from app.schemas.specialist import (
    FindSpecialistRequest,
    SpecialistSuggestion,
)
from app.services.chat_engine import (
    chat_with_assistant,
    conversations,
    chat_with_assistant_file,
)
from app.services.find_specialist_engine import (
    find_specialist_response,
    get_recent_specialist_suggestions,
    save_specialist_history,
    is_similar_query,
    get_full_specialist_session_history
)
from app.services.kommo import (
    push_lead_to_kommo,
    push_clinical_trial_lead,
)
from app.services.google import (
    upload_file_to_drive,
    post_to_google_sheets,
    post_to_google_sheets_clinical_trial,
)
from app.services.prompt_templates import FIND_SPECIALIST_PROMPT

ASSEMBLYAI_API_KEY = "0dd308f8c94e4ec9840bbb0348adaad8"  # You should use an environment variable for security!

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)
UPLOAD_DIR = os.path.abspath("app/uploads")

router = APIRouter(tags=["chat"])

# ---------------------
# Chat Routes
# ---------------------
@router.post(
    "",
    response_model=ChatResponse,
    summary="Send a message and receive a reply"
)
async def chat_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):
    # 1️⃣ Validate input
    if not request.messages:
        raise HTTPException(status_code=400, detail="At least one message must be provided.")

    # 2️⃣ Ensure we have a conversation_id (new or existing)
    conv_id = request.conversation_id or str(uuid4())

    # 3️⃣ Prepare the payload
    msgs = [msg.dict() for msg in request.messages]

    try:
        # 4️⃣ Call the service
        result = await chat_with_assistant(
            messages=msgs,
            user_id=request.user_id,
            conversation_id=conv_id
        )

    except RuntimeError as e:
        logging.error("LLM service error: %s", e, exc_info=True)
        # 502 for upstream model failures
        raise HTTPException(
            status_code=502,
            detail="Language model service unavailable. Please try again later."
        )

    except Exception as e:
        logging.exception("Unexpected error in chat_endpoint")
        # 500 for anything else
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

    # 5️⃣ Return the reply, title—and the conversation_id so the frontend can thread future requests.
    return ChatResponse(
        reply=result["reply"],
        chat_title=result["chat_title"],
        conversation_id=conv_id
    )
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
    user_id: str = Form(...),
    message: str = Form(...),             # Simple string, not JSON!
    conversation_id: str = Form(None),
    file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    # Step 1: Build the message content (OpenAI expects a list)
    content_blocks = []

    # Step 2: Upload file to OpenAI if present
    if file:
        import os
        from app.services.chat_engine import client  # or however your OpenAI client is imported

        suffix = "." + file.filename.split(".")[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp.flush()
            tmp.seek(0)
            tmp_name = tmp.name

        try:
            with open(tmp_name, "rb") as f:
                uploaded = client.files.create(
                    file=f,
                    purpose="assistants",  # For OpenAI Assistant API
                )
                file_id = uploaded.id
                logging.info(f"Uploaded file to OpenAI: {file.filename} -> file_id={file_id}")
            # Required sleep to avoid race condition (sometimes)
            time.sleep(2)
            content_blocks.append({"type": "file", "file": {"file_id": file_id}})
        except Exception as e:
            logging.error(f"File upload to OpenAI failed: {str(e)}")
            raise HTTPException(status_code=500, detail="File upload to OpenAI failed.")
        finally:
            os.remove(tmp_name)
    
    # Step 3: Add the text as the user’s message (always required)
    content_blocks.append({"type": "text", "text": message})  # message is a string


    # Step 4: Build OpenAI chat message
    openai_messages = [{
        "role": "user",
        "content": content_blocks
    }]
    print("Final openai_messages", openai_messages)

    # Step 5: Call your assistant (pass the built message)
    from app.services.chat_engine import chat_with_assistant_file
    try:
        result = await chat_with_assistant_file(
            messages=openai_messages,     # <--- Correct format!
            user_id=user_id,
            conversation_id=conversation_id,
            file=None  # Already handled!
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
    email: Optional[str] = Form(""),
    diagnosis: Optional[str] = Form(""),
    medications: Optional[str] = Form(""),
    test_results_description: Optional[str] = Form(""),
    test_results_file: Optional[UploadFile] = File(
        default=None,
        description="Optional: upload test result file (PDF, image, etc.)"
    ),
    current_user: dict = Depends(get_current_user)
):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        file_path = None
        google_drive_link = None

        # ✅ Save locally and upload to Drive
        if test_results_file:
            ext = test_results_file.filename.split(".")[-1]
            local_filename = f"{uuid4()}.{ext}"
            file_path = os.path.join(UPLOAD_DIR, local_filename)

            with open(file_path, "wb") as f:
                f.write(await test_results_file.read())

            google_drive_link = upload_file_to_drive(file_path, test_results_file.filename)
            logger.info("✅ File uploaded to Google Drive: %s", google_drive_link)

        # 📦 Prepare form data
        # Get lead_source from current user (or fetch from DB)
        lead_source = current_user.get("lead_source")
        if not lead_source:
            user_doc = await db["users"].find_one({"email": email})
            lead_source = user_doc.get("lead_source") if user_doc else None

        form_data = {
            "email": email,
            "diagnosis": diagnosis,
            "medications": medications,
            "test_results_description": test_results_description,
            "lead_source": lead_source,
            "google_drive_link": google_drive_link
        }

        # 💾 Store in MongoDB
        await db["clinical_trial_uploads"].insert_one({
            **form_data,
            "submitted_at": datetime.utcnow()
        })
        logger.info("💾 Data saved to MongoDB for %s", email)

        # # 🔁 External integrations
        # await push_clinical_trial_lead({**form_data, "uploaded_file_path": file_path})
        logger.info("📤 Pushed to Kommo")

        post_to_google_sheets_clinical_trial(form_data)
        logger.info("✅ Posted to Google Sheets")

        # 🧹 Clean up temp file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info("🧹 Temp file deleted: %s", file_path)

        return {
            "success": True,
            "message": "Clinical trial form submitted successfully"
        }

    except Exception as e:
        logger.exception("❌ Error in /clinical-trial")
        raise HTTPException(status_code=500, detail=f"Submission failed: {str(e)}")

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
    session_id: Optional[str] = Body(None, embed=True),
):
    """
    Handles a specialist suggestion chat flow in a threaded session:
    - Loads the session by session_id.
    - Replays last N prior queries/responses to give the LLM limited context.
    - Passes custom prompt with doctor exclusions if needed.
    - Saves the new turn as an additional message in the session's array.
    """
    MAX_CONTEXT_TURNS = 5  # Only last 5 turns (user+assistant)

    try:
        user_email = current_user.get("email")
        if not user_email:
            raise HTTPException(status_code=400, detail="User email not found in current_user")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required for session-based specialist chat.")

        # 1️⃣ Get full conversation history for this session
        history = await get_full_specialist_session_history(user_email, session_id)
        # Limit to last N turns
        if len(history) > MAX_CONTEXT_TURNS:
            history = history[-MAX_CONTEXT_TURNS:]

        already_recommended = set()
        # 2️⃣ Determine doctors to exclude based on similar queries in the (limited) history
        for entry in history:
            if "query" in entry and is_similar_query(payload.query, entry["query"]):
                already_recommended.add(entry.get("doctor_name", ""))

        # 3️⃣ Build the system prompt
        if already_recommended:
            doctors_list = ", ".join([d for d in already_recommended if d])
            custom_prompt = (
                FIND_SPECIALIST_PROMPT +
                f"\n\nNOTE: For this session ({session_id}), the user has previously been recommended the following specialist(s) for similar symptoms: {doctors_list}. If possible, suggest a different specialist from the available list."
            )
        else:
            custom_prompt = FIND_SPECIALIST_PROMPT

        # 4️⃣ Construct message list for OpenAI (system, prior pairs, current user)
        messages = [{"role": "system", "content": custom_prompt}]
        for entry in history:
            if "query" in entry:
                messages.append({"role": "user", "content": entry["query"]})
            if "response" in entry and entry["response"]:
                resp_msg = entry["response"].get("response_message", "")
                if resp_msg:
                    messages.append({"role": "assistant", "content": resp_msg})
        messages.append({"role": "user", "content": payload.query})

        # 5️⃣ Call the LLM (thread-safe)
        raw = await asyncio.to_thread(find_specialist_response, messages)

        # 6️⃣ Always save the turn
        await save_specialist_history(
            user_email,
            payload.query,
            raw.get("Name", ""),
            session_id=session_id,
            response=raw
        )

        # 7️⃣ Return model-validated result
        return SpecialistSuggestion(**raw)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/new-specialist-session-by-email", summary="Create a new specialist session using email")
async def start_new_specialist_session_by_email(
    email: str = Body(..., embed=True)
):
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    session_id = str(uuid4())
    session_title = "New Specialist Session"

    session_doc = {
        "user_email": email,
        "session_id": session_id,
        "session_title": session_title,
        "created_at": datetime.utcnow(),
        "last_updated": datetime.utcnow(),
        "queries": [],
    }
    await specialist_history_collection.insert_one(session_doc)

    return {"session_id": session_id, "session_title": session_title}

# app/routers/chat.py (your GET endpoint)

@router.get("/specialist-history/{session_id}", summary="Get full specialist chat history by session")
async def get_specialist_session_history(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_email = current_user.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found")
    session_doc = await specialist_history_collection.find_one(
        {"user_email": user_email, "session_id": session_id}
    )
    if not session_doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": session_doc.get("queries", [])}

@router.get("/all-specialist-sessions", summary="List all specialist chat sessions")
async def list_all_specialist_sessions():
    """
    Returns ALL specialist chat sessions from the DB, across all users.
    """
    cursor = specialist_history_collection.find(
        {},
        {"_id": 1, "user_email": 1, "session_id": 1, "session_title": 1, "created_at": 1, "last_updated": 1}
    ).sort("last_updated", -1)
    sessions = await cursor.to_list(length=200)  # Adjust limit as needed

    # Convert ObjectId to string and format dates
    for session in sessions:
        session["_id"] = str(session["_id"])
        for field in ["created_at", "last_updated"]:
            if session.get(field):
                session[field] = session[field].isoformat()

    return {"sessions": sessions}


@router.delete("/delete/{conversation_id}", summary="Delete a conversation by ID")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    result = await conversations.delete_one({"conversation_id": conversation_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True, "message": "🗑️ Conversation deleted successfully"}
