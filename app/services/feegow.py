# app/services/feegow.py

import requests
import os
from datetime import datetime

FEEGOW_API_URL = "https://api.feegow.com/v1/api/appoints/new-appoint"
FEEGOW_TOKEN = os.getenv("FEEGOW_API_TOKEN", "your-feegow-access-token")


def forward_to_feegow(appointment: dict):
    headers = {
        "Content-Type": "application/json",
        "x-access-token": FEEGOW_TOKEN  # 👈 correct header key
    }


    # Safely convert datetime fields to strings
    def to_iso(dt):
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)

    payload = {
        "patient": {
            "name": appointment.get("patient_name"),
            "email": appointment.get("email"),
            "phone": appointment.get("phone"),
            "gender": appointment.get("gender"),
            "birthdate": to_iso(appointment.get("birthdate"))[:10] or "2000-01-01"
        },
        "appointment": {
            "datetime": to_iso(appointment.get("scheduled_time")),
            "doctor": appointment.get("doctor_name"),
            "specialization": appointment.get("specialization"),
            "notes": appointment.get("notes", "N/A")
        }
    }

    print("📡 Pushing appointment to Feegow...")
    response = requests.post(FEEGOW_API_URL, headers=headers, json=payload)

    if response.status_code == 200:
        print("✅ Appointment pushed to Feegow successfully!")
        print(response.json())
    else:
        print(f"❌ Feegow API Error: {response.text}")
        response.raise_for_status()
