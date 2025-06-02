# app/services/find_specialist_engine.py

from datetime import datetime
from app.db.mongo import specialist_history_collection
import re
import json
from openai import OpenAI
from app.core.config import settings
from app.services.prompt_templates import FIND_SPECIALIST_PROMPT

def clean_and_parse(raw: str) -> dict:
    # Try to extract JSON first
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except Exception as e:
            print("❌ JSON in markdown but failed to parse:", e)
    # If not JSON, treat as text advice and wrap in expected JSON schema
    print("ℹ️ Received non-JSON, wrapping as fallback JSON.")
    return {
        "response_message": raw.strip(),
        "Name": "",
        "Specialization": "",
        "Registration": "",
        "Image": "https://nudii.com.br/wp-content/uploads/2025/05/placeholder.png",
        "doctor_description": ""
    }

async def save_specialist_history(
    user_email: str,
    query: str,
    doctor_name: str,
    session_id: str,
    response: dict
):
    entry = {
        "query": query,
        "doctor_name": doctor_name,
        "response": response,
        "timestamp": datetime.utcnow()
    }
    await specialist_history_collection.update_one(
        {"user_email": user_email, "session_id": session_id},
        {"$push": {"queries": entry}, "$set": {"last_updated": datetime.utcnow()}},
        upsert=True
    )

async def get_recent_specialist_suggestions(user_email: str, max_records=5, session_id: str = None):
    """
    Get the last N specialist suggestions for a user and session, sorted by time descending.
    """
    session_doc = await specialist_history_collection.find_one(
        {"user_email": user_email, "session_id": session_id}
    )
    if session_doc and "queries" in session_doc:
        # Return last N turns (most recent last)
        return session_doc["queries"][-max_records:]
    return []

async def get_full_specialist_session_history(user_email: str, session_id: str):
    session_doc = await specialist_history_collection.find_one(
        {"user_email": user_email, "session_id": session_id}
    )
    return session_doc["queries"] if session_doc and "queries" in session_doc else []


def is_similar_query(new_query: str, old_query: str) -> bool:
    """Very basic similarity check; can be replaced with NLP."""
    # Lowercase and check for simple substring/keyword overlap
    n = new_query.lower()
    o = old_query.lower()
    # You can use fuzzywuzzy or rapidfuzz for more advanced similarity
    return n == o or (len(n) > 10 and n in o) or (len(o) > 10 and o in n)

client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
def find_specialist_response(messages: list) -> dict:
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            temperature=0,
            max_tokens=1024
        )
        raw = resp.choices[0].message.content
        try:
            return clean_and_parse(raw)
        except Exception as e:
            print("❌ Returning fallback due to JSON parse failure.")
            return {
            "response_message": "Sorry, there was an issue processing your request.",
            "Name": "",
            "Specialization": "",
            "Registration": "",
            "Image": "https://nudii.com.br/wp-content/uploads/2025/05/placeholder.png",
            "doctor_description": ""
        }

    except Exception as e:
        print("❌ GPT call failed:", e)
        return {
            "response_message": "Sorry, there was an issue processing your request.",
            "Name": "",
            "Specialization": "",
            "Registration": "",
            # FIX THIS LINE
            "Image": "https://nudii.com.br/wp-content/uploads/2025/05/placeholder.png",
            "doctor_description": ""
        }
