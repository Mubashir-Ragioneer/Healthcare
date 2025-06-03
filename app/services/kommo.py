# app/services/kommo.py

import os
import json
import requests
from datetime import datetime as dt
import asyncio
from dateutil.parser import parse


KOMMO_TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kommo_token.json"))
SUBDOMAIN = "imf"


def load_kommo_token():
    if not os.path.exists(KOMMO_TOKEN_FILE):
        print("Kommo token file not found.")
        return None
    with open(KOMMO_TOKEN_FILE, "r") as f:
        print("Loading Kommo token from file...")
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

    # Parse dates
    dt_str = appointment.get("datetime")
    if not dt_str:
        raise ValueError("Missing 'datetime' in appointment payload.")
    dt_obj = parse(str(dt_str)) if not isinstance(dt_str, dt) else dt_str

    name = appointment.get("patient_name", "Unknown Patient").strip()

    # 1. Create Contact
    contact_payload = [{
        "first_name": name,
        "custom_fields_values": [
            {"field_code": "PHONE", "values": [{"value": appointment["phone"]}]},
            {"field_code": "EMAIL", "values": [{"value": appointment["email"]}]}
        ]
    }]
    contact_res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/contacts", headers=headers, json=contact_payload)
    if not contact_res.ok:
        print(f"Contact creation failed: {contact_res.status_code}")
        print(contact_res.text)
        raise Exception("Contact creation failed")

    contact_id = contact_res.json()['_embedded']['contacts'][0]['id']

    # 2. Create Lead
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
        print("Appointment pushed as Kommo Lead successfully!")
        print(lead_res.json())
        return True  # NEW: indicate success to caller
    else:
        print(f"Lead creation failed: {lead_res.status_code}")
        print(lead_res.text)
        raise Exception("Kommo lead creation failed")

def push_lead_to_kommo(data: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    name = data.get("user_id", "Unknown User")  # You may map to actual name later
    message = data.get("message", "")
    mode = data.get("mode", "find_specialist")
    tag = "Find Specialist" if mode == "find_specialist" else "Find Test"

    lead_payload = [{
        "name": f"{tag} Inquiry",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,
        "status_id": 82549323,
        "custom_fields_values": [
            {
                "field_id": 747486,  # Notes / problem
                "values": [{"value": message}]
            }
        ],
        "tags": [
            {"name": tag}
        ]
    }]

    lead_res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/leads", headers=headers, json=lead_payload)
    if lead_res.status_code not in [200, 201]:
        print("Kommo Lead failed:", lead_res.text)
        raise Exception("Kommo lead creation failed")

    return True


async def push_clinical_trial_lead(data: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    # Compose a rich note for Kommo from the form data
    note_parts = [
        f"Diagnosis: {data.get('diagnosis', 'N/A')}",
        f"Medications: {data.get('medications', 'N/A')}",
        f"Test Results Summary: {data.get('test_results_description', 'N/A')}"
    ]

    if data.get("uploaded_file_path"):
        note_parts.append(f"Uploaded file: {os.path.basename(data['uploaded_file_path'])}")

    note = "\n".join(note_parts)

    lead_payload = [{
        "name": f"Clinical Trial - {data['full_name']}",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,
        "status_id": 82549323,
        "custom_fields_values": [
            {
                "field_id": 747486,  # Notes field
                "values": [{"value": note}]
            }
        ],
        "tags": [
            {"name": "Clinical Trial IBD"},
            {"name": data.get("lead_source", "unknown")}
        ]
    }]

    lead_res = requests.post(
        f"https://{SUBDOMAIN}.kommo.com/api/v4/leads",
        headers=headers,
        json=lead_payload
    )

    if lead_res.status_code not in [200, 201]:
        print("Kommo Clinical Trial Lead failed:", lead_res.text)
        raise Exception("Clinical Trial lead creation failed")

    print("Kommo Clinical Trial Lead submitted.")

def post_to_google_sheets(form_data: dict):
    SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")

    if not SHEETS_WEBHOOK_URL:
        print("Sheets webhook not configured")
        return

    try:
        response = requests.post(SHEETS_WEBHOOK_URL, json=form_data)
        if not response.ok:
            print("Failed to send data to Google Sheets:", response.text)
    except Exception as e:
        print("Exception while posting to Sheets:", str(e))



async def push_user_message_to_kommo(user_id: str, message: str, mode: str):
    lead_data = {
        "name": f"{mode} | user_id: {user_id}",
        "custom_fields_values": [...],
        "tags": [{"name": "Live Chat"}],
        "created_at": int(datetime.utcnow().timestamp())
    }
    # (1) Create or update lead
    # (2) Save lead_id for webhook matching later

    # Optional: Add the message as a note
    await post_note_to_lead(lead_id, f"[{mode}] {message}")


def push_exam_lead_to_kommo(data: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    lead_payload = [{
        "name": f"Exam - {data['specialization']} ({data['exam_type']})",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,  # Adjust as needed
        "status_id": 82549323,    # Adjust as needed
        "custom_fields_values": [
            {
                "field_id": 367116,  # datetime
                "values": [{"value": format_kommo_datetime(data["scheduled_time"])}]
            },
            {
                "field_id": 747486,  # purpose / notes
                "values": [{"value": data.get("purpose", "") }]
            }
        ],
        "tags": [
            {"name": "Exam Request"},
            {"name": data.get("specialization", "Unknown")}
        ]
    }]

    res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/leads", headers=headers, json=lead_payload)
    if res.status_code not in [200, 201]:
        print("Kommo exam lead creation failed:", res.text)
        raise Exception("Failed to create Kommo exam lead")
    print("Kommo Exam Lead submitted.")


def load_kommo_token():
    if not os.path.exists(KOMMO_TOKEN_FILE):
        print("Kommo token file not found.")
        return None
    with open(KOMMO_TOKEN_FILE, "r") as f:
        print("Loading Kommo token from file...")
        return json.load(f)

def push_receptionist_request_to_kommo(data: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    note = f"User wants to speak to a receptionist.\nName: {data['name']}\nPhone: {data['phone']}\nReason: {data['reason']}"

    lead_payload = [{
        "name": f"Receptionist - {data['name']}",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,
        "status_id": 82549323,
        "custom_fields_values": [
            {
                "field_id": 747486,  # Descrição do Problema do Paciente
                "values": [{"value": note}]
            }
        ],
        "tags": [
            {"name": "Receptionist Request"}
        ]
    }]

    res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/leads", headers=headers, json=lead_payload)
    if res.status_code not in [200, 201]:
        print("Kommo receptionist lead failed:", res.text)
        raise Exception("Failed to create Kommo receptionist lead")

    print("Kommo Receptionist Lead submitted.")

def push_quote_to_kommo(data: dict):
    kommo_auth = load_kommo_token()
    if not kommo_auth or "access_token" not in kommo_auth:
        raise Exception("No Kommo token stored.")

    headers = {
        "Authorization": f"Bearer {kommo_auth['access_token']}",
        "Content-Type": "application/json",
    }

    # Compose the lead payload
    note = f"Category: {data['category']}\nSubcategory: {data['subcategory']}\nDetails: {data['details']}"

    lead_payload = [{
        "name": f"Quotation - {data['category']} | {data['subcategory']}",
        "price": 0,
        "created_at": int(dt.utcnow().timestamp()),
        "pipeline_id": 10765347,  # Adjust if needed
        "status_id": 82549323,    # Adjust if needed
        "custom_fields_values": [
            {
                "field_id": 747486,  # Notes field
                "values": [{"value": note}]
            }
        ],
        "tags": [
            {"name": "Quotation Request"}
        ]
    }]

    res = requests.post(f"https://{SUBDOMAIN}.kommo.com/api/v4/leads", headers=headers, json=lead_payload)
    if res.status_code not in [200, 201]:
        print("Kommo quotation lead creation failed:", res.text)
        raise Exception("Failed to create Kommo quotation lead")
    print("Kommo Quotation Lead submitted.")
