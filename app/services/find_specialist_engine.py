# app/services/find_specialist_engine.py
import re
import json

def clean_and_parse(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"`", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception as e:
        print("❌ JSON parsing failed in find_specialist_response:", e)
        print("Raw model output was:", raw)
        # Raise or return a fallback
        raise

from openai import OpenAI
from app.core.config import settings
from app.services.prompt_templates import FIND_SPECIALIST_PROMPT

client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

def find_specialist_response(user_query: str) -> dict:
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": FIND_SPECIALIST_PROMPT},
                {"role": "user",   "content": user_query},
            ],
            temperature=0,
            max_tokens=512
        )
        raw = resp.choices[0].message.content
        try:
            return clean_and_parse(raw)
        except Exception as e:
            # JSON parse failed—fallback to safe empty doctor
            print("❌ Returning fallback due to JSON parse failure.")
            return {
                "response_message": "Sorry, there was an issue processing your request.",
                "Name": "",
                "Specialization": "",
                "Registration": "",
                "Image": "",
                "doctor_description": ""
            }
    except Exception as e:
        print("❌ GPT call failed:", e)
        # fallback JSON structure
        return {
            "response_message": "Sorry, there was an issue processing your request.",
            "Name": "",
            "Specialization": "",
            "Registration": "",
            "Image": "",
            "doctor_description": ""
        }
