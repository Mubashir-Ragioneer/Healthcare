# app/routers/chat.py

import os
import json
import asyncio
import tempfile
from pinecone import Pinecone
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
    chat_with_image_assistant,
    process_and_log_image_chat_message
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
from app.services.vector_store import embed_text
from app.services.prompt_templates import FIND_SPECIALIST_PROMPT
from fastapi import BackgroundTasks

ASSEMBLYAI_API_KEY = "0dd308f8c94e4ec9840bbb0348adaad8"  # You should use an environment variable for security!

# OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)

PINECONE_API_KEY = settings.PINECONE_API_KEY  # Store in env
INDEX_HOST = "https://nudii-experts-description-7iqky9x.svc.aped-4627-b74a.pinecone.io"
NAMESPACE = "specialist"

pc = Pinecone(api_key=PINECONE_API_KEY)
pinecone_index = pc.Index(host=INDEX_HOST)

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
    # 1️ Validate input
    if not request.messages:
        raise HTTPException(status_code=400, detail="At least one message must be provided.")

    # 2️ Ensure we have a conversation_id (new or existing)
    conv_id = request.conversation_id or str(uuid4())

    # 3️ Prepare the payload
    msgs = [msg.dict() for msg in request.messages]

    try:
        # 4️ Call the service
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

    # 5️ Return the reply, title—and the conversation_id so the frontend can thread future requests.
    return ChatResponse(
        reply=result["reply"],
        chat_title=result["chat_title"],
        conversation_id=conv_id
    )

@router.post("/chat/with-image")
async def chat_with_image(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    user_id: str = Form(...),
    conversation_id: str = Form(None),
    prompt: str = Form("What's in this image?"),
    current_user: dict = Depends(get_current_user)
):
    # 1. Read image to memory (don't save to disk yet!)
    image_bytes = await image.read()

    # 2. Base64 encode for LLM
    import base64, os
    ext = image.filename.split('.')[-1]
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    # 3. Compose OpenAI message
    llm_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{ext};base64,{base64_image}"
                }
            }
        ]
    }]

    # 4. Get LLM reply
    from app.core.config import settings
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    completion = client.chat.completions.create(
        model="gpt-4.1",  # Or gpt-4o
        messages=llm_messages,
        max_tokens=400
    )
    reply = completion.choices[0].message.content
    conv_id = conversation_id or str(uuid4())

    # 5. Return the response immediately!
    response_obj = {
        "reply": reply,
        "chat_title": "Image Analysis",
        "conversation_id": conv_id
    }

    # 6. Start background upload + DB logging
    background_tasks.add_task(
        process_and_log_image_chat_message,
        image_bytes, ext, image.filename, prompt, user_id, conv_id, reply
    )

    return response_obj



@router.post("/with-audio", summary="Send audio and receive a reply")
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
        print(" Error in get_chat_history():", str(e))
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

        # Save locally and upload to Drive
        if test_results_file:
            ext = test_results_file.filename.split(".")[-1]
            local_filename = f"{uuid4()}.{ext}"
            file_path = os.path.join(UPLOAD_DIR, local_filename)

            with open(file_path, "wb") as f:
                f.write(await test_results_file.read())

            google_drive_link = upload_file_to_drive(file_path, test_results_file.filename)
            logger.info("File uploaded to Google Drive: %s", google_drive_link)

        # Prepare form data
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

        # Store in MongoDB
        await db["clinical_trial_uploads"].insert_one({
            **form_data,
            "submitted_at": datetime.utcnow()
        })
        logger.info("💾 Data saved to MongoDB for %s", email)

        #  External integrations
        # await push_clinical_trial_lead({**form_data, "uploaded_file_path": file_path})
        logger.info(" Pushed to Kommo")

        post_to_google_sheets_clinical_trial(form_data)
        logger.info(" Posted to Google Sheets")

        # 🧹 Clean up temp file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info("🧹 Temp file deleted: %s", file_path)

        return {
            "success": True,
            "message": "Clinical trial form submitted successfully"
        }

    except Exception as e:
        logger.exception(" Error in /clinical-trial")
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
    response_model=Dict[str, Any],  # Accepts both single/multi structures
    summary="Suggest a specialist based on user query"
)
async def suggest_specialist(
    payload: FindSpecialistRequest,
    current_user: dict = Depends(get_current_user),
    session_id: Optional[str] = Body(None, embed=True),
):
    MAX_CONTEXT_TURNS = 1
    TOP_K_RAG = 8

    try:
        user_email = current_user.get("email")
        if not user_email:
            raise HTTPException(status_code=400, detail="User email not found in current_user")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required for session-based specialist chat.")

        # 1️ Get last N turns of chat for this session
        history = await get_full_specialist_session_history(user_email, session_id)
        if len(history) > MAX_CONTEXT_TURNS:
            history = history[-MAX_CONTEXT_TURNS:]

        # 2️ Collect last N user queries for RAG
        user_queries = [entry["query"] for entry in history if "query" in entry]
        combined_query = "\n".join(user_queries[-MAX_CONTEXT_TURNS:]) if user_queries else payload.query
        #logger.info("Combined query: %s", combined_query)
        # 3️ Pinecone RAG retrieval
        doctors = []
        try:
            query_embedding = await embed_text(combined_query)
            pinecone_results = pinecone_index.query(
                vector=query_embedding,
                top_k=TOP_K_RAG,
                namespace=NAMESPACE,
                include_metadata=True
            )
            for m in pinecone_results.get("matches", []):
                doc_json = m['metadata'].get('doc', '{}')
                try:
                    doc = json.loads(doc_json)
                    doctors.append(doc)
                except Exception as e:
                    print(f"Error loading doc JSON: {e}")
        except Exception as pinecone_err:
            print("Pinecone retrieval failed:", pinecone_err)

        # 4️ Format the RAG block as strict JSON per profile
        rag_context_str = ""
        if doctors:
            rag_context_str = "\n".join([
                f"""{{
    "Name": "{doc.get('name', '')}",
    "Specialization": "{(
        ', '.join(doc.get('medical_specialty', [])) or
        ', '.join(doc.get('specialty', [])) or
        doc.get('specialization', '') or
        ''
    )}",
    "Registration": "{doc.get('crm', '')}",
    "Image": "{doc.get('Image in Google Drive', 'https://nudii.com.br/wp-content/uploads/2025/05/placeholder.png')}",
    "doctor_description": "{doc.get('my_story', '')[:1000]}"
    }}"""
                for doc in doctors
            ])
            #logger.info("RAG context: %s", rag_context_str)

        # 5️ Compose the system prompt: RAG context FIRST, then instructions
        if rag_context_str:
            system_prompt = (
                "Here are the relevant specialist profiles (choose only from these):\n"
                f"{rag_context_str}\n\n"
                f"{FIND_SPECIALIST_PROMPT.strip()}"
            )
        else:
            system_prompt = FIND_SPECIALIST_PROMPT.strip()

        # 6️ Build OpenAI message array
        messages = [{"role": "system", "content": system_prompt}]
        for entry in history:
            if "query" in entry:
                messages.append({"role": "user", "content": entry["query"]})
            if "response" in entry and entry["response"]:
                resp_msg = entry["response"].get("response_message", "")
                if resp_msg:
                    messages.append({"role": "assistant", "content": resp_msg})
        messages.append({"role": "user", "content": payload.query})

        # 7️ LLM call (thread-safe)
        raw = await asyncio.to_thread(
            find_specialist_response,
            payload.query,
            system_prompt,
            rag_context_str,
            history
        )

        # 8️ Save all recommended doctor names for history
        doctor_names = []
        if isinstance(raw, dict):
            if "specialists" in raw and isinstance(raw["specialists"], list):
                doctor_names = [d.get("Name", "") for d in raw["specialists"]]
            elif "Name" in raw:
                doctor_names = [raw.get("Name", "")]
        await save_specialist_history(
            user_email,
            payload.query,
            ", ".join([name for name in doctor_names if name]),
            session_id=session_id,
            response=raw
        )

        # 9️ Return result directly
        return raw

    except Exception as e:
        import traceback; traceback.print_exc()
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
    return {"success": True, "message": " Conversation deleted successfully"}
