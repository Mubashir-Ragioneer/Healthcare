# app/utils/email.py

import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from fastapi.concurrency import run_in_threadpool

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

async def send_verification_email(to_email: str, verification_url: str):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")
    message = Mail(
        from_email=("info@healthcare.ragioneer.com", "Healthcare AI"),
        to_emails=to_email,
        subject="Verify your email address",
        html_content=(
            f"Please verify your email by clicking this link: "
            f"<a href='{verification_url}'>{verification_url}</a>"
        ),
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = await run_in_threadpool(sg.send, message)
        print(f"[SENDGRID] Status: {response.status_code}")
    except Exception as e:
        import traceback
        print("SendGrid email error:", e)
        print(traceback.format_exc())
        raise
