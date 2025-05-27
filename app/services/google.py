# app/services/google.py

import os
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.core.credentials import get_gcp_credentials
from app.core.logger import logger

# Load configs from environment
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def upload_file_to_drive(local_path: str, filename: str) -> str:
    """
    Uploads a file to Google Drive and returns a public shareable link.
    """
    if not GOOGLE_DRIVE_FOLDER_ID:
        raise ValueError("Missing GOOGLE_DRIVE_FOLDER_ID")

    # ✅ Load credentials using shared helper
    creds = get_gcp_credentials(GOOGLE_DRIVE_SCOPES)
    drive_service = build("drive", "v3", credentials=creds)

    file_metadata = {
        "name": filename,
        "parents": [GOOGLE_DRIVE_FOLDER_ID]
    }

    media = MediaFileUpload(local_path, resumable=True)

    uploaded = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    file_id = uploaded.get("id")

    # Make file public
    drive_service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
    ).execute()

    public_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    logger.info(f"✅ Uploaded to Google Drive: {public_url}")
    return public_url


def post_to_google_sheets(form_data: dict):
    """
    Sends the submitted form data to a Google Sheets webhook URL.
    """
    if not GOOGLE_SHEETS_WEBHOOK_URL:
        logger.warning("⚠️ Sheets webhook not configured")
        return

    try:
        response = requests.post(GOOGLE_SHEETS_WEBHOOK_URL, json=form_data)

        if response.ok:
            logger.info("✅ Data posted to Google Sheets")
        else:
            logger.error(f"❌ Failed to send data to Google Sheets: {response.text}")
    except Exception as e:
        logger.exception(f"❌ Exception while posting to Sheets: {e}")
