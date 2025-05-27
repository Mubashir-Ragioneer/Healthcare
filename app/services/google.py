# app/services/google.py

import os
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.core.logger import logger


# Load from environment
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_FILE = os.path.abspath("service-account.json")
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def upload_file_to_drive(local_path: str, filename: str) -> str:
    """
    Uploads a file to Google Drive and returns a public shareable link.
    """
    if not GOOGLE_DRIVE_FOLDER_ID or not SERVICE_ACCOUNT_FILE:
        raise ValueError("Missing GOOGLE_DRIVE_FOLDER_ID or SERVICE_ACCOUNT_FILE")

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=GOOGLE_DRIVE_SCOPES
    )

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

    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


def post_to_google_sheets(form_data: dict):
    """
    Sends the submitted form data to a Google Sheets webhook URL.
    """
    SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")

    if not SHEETS_WEBHOOK_URL:
        print("⚠️ Sheets webhook not configured")
        return

    try:
        response = requests.post(SHEETS_WEBHOOK_URL, json=form_data)
        
        if not response.ok:
            print("❌ Failed to send data to Google Sheets:", response.text)
        else:
            print("✅ Data posted to Google Sheets")  # ✅ Success log
    
    except Exception as e:
        print("❌ Exception while posting to Sheets:", str(e))
