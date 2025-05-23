# app/utils/email.py

import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

async def send_verification_email(to_email: str, verification_url: str):
    message = Mail(
        from_email="info@healthcare.ragioneer.com",
        to_emails=to_email,
        subject="Verify your email address",
        html_content=f"Please verify your email by clicking this link: <a href='{verification_url}'>{verification_url}</a>",
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(response.status_code)
    except Exception as e:
        print(e)
        raise
