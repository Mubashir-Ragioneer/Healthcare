# app/services/find_specialist_engine.py

from openai import OpenAI
from app.core.config import settings
from app.services.prompt_templates import FIND_SPECIALIST_PROMPT

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)

def find_specialist_response(user_query: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": FIND_SPECIALIST_PROMPT},
                {"role": "user", "content": user_query},
            ],
            temperature=0.3,
            max_tokens=512
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ GPT call failed:", e)
        return "Sorry, there was an issue processing your request."
