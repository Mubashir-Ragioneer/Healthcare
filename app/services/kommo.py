# app/services/kommo.py

import json
import os
import requests
from datetime import datetime

# Path where token is saved
KOMMO_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "kommo_token.json")
KOMMO_TOKEN_FILE = os.path.abspath(KOMMO_TOKEN_FILE)

SUBDOMAIN = "imf"  # Replace with your actual subdomain


def load_kommo_token():
    if not os.path.exists(KOMMO_TOKEN_FILE):
        print("⚠️ Kommo token file not found.")
        return None
    with open(KOMMO_TOKEN_FILE, "r") as f:
        print("📥 Loading Kommo token from file...")
        return json.load(f)


def push_appointment_to_kommo(appointment: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    url = f"https://{SUBDOMAIN}.kommo.com/api/v4/leads"
    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    # ✅ Corrected payload: name, price, created_at as scalars
    payload = {
        "name": [f"Appointment - {appointment.get('patient_name', 'Healthcare Appointment')}"],  # ✅ array
        "price": [0],  # ✅ array
        "created_at": [int(datetime.utcnow().timestamp())],  # ✅ array
        "custom_fields_values": [
                {
                "field_code": "PHONE",
                "values": [{"value": appointment.get("phone")}]
            },
            {
                "field_code": "EMAIL",
                "values": [{"value": appointment.get("email")}]
            },
            {
                "field_id": 123456,  # Replace with actual field ID if needed
                "values": [{"value": appointment.get("notes", "")}]
            }
        ],
        "_embedded": {
            "contacts": [
                {
                    "first_name": appointment.get("patient_name", "Unknown")
                }
            ]
        },
        "tags": [
            {"name": "healthcare"},
            {"name": appointment.get("appointment_type", "general")}
        ]
    }

    print("📡 Pushing appointment to Kommo...")
    print("📦 Payload JSON:", json.dumps(payload, indent=2))
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        print("✅ Appointment pushed as Kommo Lead successfully!")
        print(response.json())
    else:
        print(f"❌ Failed to push lead. Status: {response.status_code}")
        print(response.text)
        raise Exception("Kommo lead push failed")
