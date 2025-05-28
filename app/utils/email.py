# app/utils/email.py
# app/utils/email.py

import os
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from fastapi.concurrency import run_in_threadpool

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

async def send_verification_email(to_email: str, verification_url: str):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f7; padding: 20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden;">
          <tr>
            <td style="background-color: #4F46E5; padding: 20px; color: white; text-align: center;">
              <h2 style="margin: 0;">Healthcare AI</h2>
            </td>
          </tr>
          <tr>
            <td style="padding: 30px;">
              <h3 style="color: #333;">Verify Your Email Address</h3>
              <p style="color: #555;">
                Thank you for registering with Healthcare AI. Please click the button below to verify your email address and activate your account.
              </p>
              <div style="text-align: center; margin: 30px 0;">
                <a href="{verification_url}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                  Verify Email
                </a>
              </div>
              <p style="color: #555;">
                If you didn’t create an account, you can safely ignore this email.
              </p>
              <p style="color: #aaa; font-size: 12px; margin-top: 30px;">
                This link will expire in 1 hour for security reasons.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color: #f4f4f7; text-align: center; padding: 20px; font-size: 12px; color: #888;">
              © {datetime.utcnow().year} Healthcare AI. All rights reserved.
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    message = Mail(
        from_email=("info@healthcare.ragioneer.com", "Healthcare AI"),
        to_emails=to_email,
        subject="Verify your email address",
        html_content=html_content,
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

async def send_password_reset_email(to_email: str, reset_url: str):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not set")

    message = Mail(
        from_email=("info@healthcare.ragioneer.com", "Healthcare AI"),
        to_emails=to_email,
        subject="Reset Your Password",
        html_content=(f"""
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f4f4f7; padding: 20px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden;">
      <tr>
        <td style="background-color: #4F46E5; padding: 20px; color: white; text-align: center;">
          <h2 style="margin: 0;">Healthcare AI</h2>
        </td>
      </tr>
      <tr>
        <td style="padding: 30px;">
          <h3 style="color: #333;">Reset Your Password</h3>
          <p style="color: #555;">
            We received a request to reset the password for your account.
            If this was you, please click the button below to set a new password.
          </p>
          <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">
              Reset Password
            </a>
          </div>
          <p style="color: #555;">
            If you didn't request a password reset, you can safely ignore this email.
            Your current password will remain unchanged.
          </p>
          <p style="color: #aaa; font-size: 12px; margin-top: 30px;">
            This link will expire in 1 hour for security reasons.
          </p>
        </td>
      </tr>
      <tr>
        <td style="background-color: #f4f4f7; text-align: center; padding: 20px; font-size: 12px; color: #888;">
          © {datetime.utcnow().year} Healthcare AI. All rights reserved.
        </td>
      </tr>
    </table>
  </body>
</html>
"""),
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = await run_in_threadpool(sg.send, message)
        print(f"[SENDGRID] Reset Email Status: {response.status_code}")
    except Exception as e:
        import traceback
        print("SendGrid reset email error:", e)
        print(traceback.format_exc())
        raise
