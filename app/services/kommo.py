# app/services/kommo.py

import os
import json
import requests
from datetime import datetime as dt
from dateutil.parser import parse

KOMMO_TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kommo_token.json"))
SUBDOMAIN = "imf"


def load_kommo_token():
    if not os.path.exists(KOMMO_TOKEN_FILE):
        print("⚠️ Kommo token file not found.")
        return None
    with open(KOMMO_TOKEN_FILE, "r") as f:
        print("📥 Loading Kommo token from file...")
        return json.load(f)


def format_kommo_datetime(dt_obj):
    return dt_obj.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"


def push_appointment_to_kommo(appointment: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    # ✅ Parse dates
    dt_str = appointment.get("datetime")
    if not dt_str:
        raise ValueError("Missing 'datetime' in appointment payload.")
    dt_obj = parse(str(dt_str)) if not isinstance(dt_str, dt) else dt_str

    name = appointment.get("patient_name", "Unknown Patient").strip()

    # ✅ 1. Create Contact
    contact_payload = [{
        "first_name": name,
        "custom_fields_values": [
            {"field_code": "PHONE", "values": [{"value": appointment["phone"]}]},
            {"field_code": "EMAIL", "values": [{"value": appointment["email"]}]}
        ]
    }]
    contact_res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/contacts", headers=headers, json=contact_payload)
    if not contact_res.ok:
        print(f"❌ Contact creation failed: {contact_res.status_code}")
        print(contact_res.text)
        raise Exception("Contact creation failed")

    contact_id = contact_res.json()['_embedded']['contacts'][0]['id']

    # ✅ 2. Create Lead
    lead_payload = [{
        "name": f"Appointment - {name}",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,         # Atendimento
        "status_id": 82549323,           # Agendamento concluído com êxito
        "custom_fields_values": [
            {
                "field_id": 367116,      # Appointment datetime
                "values": [{"value": format_kommo_datetime(dt_obj)}]
            },
            {
                "field_id": 747486,      # Notes / problem
                "values": [{"value": appointment.get("notes", "")}]
            },
            {
                "field_id": 1011258,     # Virtual / Presencial
                "values": [{"enum_id": 855226 if appointment.get("appointment_type") == "Virtual" else 855228}]
            }
        ],
        "_embedded": {
            "contacts": [{"id": contact_id}]
        },
        "tags": [
            {"name": "healthcare"},
            {"name": appointment.get("appointment_type", "Unknown")}
        ]
    }]

    lead_res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/leads", headers=headers, json=lead_payload)
    if lead_res.status_code in [200, 201]:
        print("✅ Appointment pushed as Kommo Lead successfully!")
        print(lead_res.json())
        return True  # ✅ NEW: indicate success to caller
    else:
        print(f"❌ Lead creation failed: {lead_res.status_code}")
        print(lead_res.text)
        raise Exception("Kommo lead creation failed")
