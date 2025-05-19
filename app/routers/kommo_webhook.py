# app/routers/kommo_webhook.py
from fastapi import APIRouter, Request

router = APIRouter(prefix="/kommo", tags=["kommo"])

@router.post("/webhook")
async def kommo_webhook(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    message_text = payload.get("message", {}).get("text")
    lead_id = payload.get("lead", {}).get("id")

    if message_text:
        # Lookup user_id via your DB → match lead_id
        # Send this back to the frontend (e.g. via WebSocket or DB insert for polling)
        await insert_message_to_user_thread(user_id, message_text, sender="kommo")
    return {"status": "received"}
