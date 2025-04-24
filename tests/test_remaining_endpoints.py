# tests/test_remaining_endpoints.py

import os
import sys
import pytest
from fastapi.testclient import TestClient

# Add the project root (where `app/` lives) to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app

client = TestClient(app)


# --- Ingestion tests ---

def test_ingest_upload(monkeypatch):
    async def fake_process_file(file):
        return {"filename": file.filename, "status": "ok"}

    # Patch the function the router actually calls
    monkeypatch.setattr("app.routers.ingest.process_file", fake_process_file)

    files = [("files", ("test.txt", b"hello world", "text/plain"))]
    response = client.post("/ingest/upload/", files=files)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "success"
    assert isinstance(body["results"], list)
    assert body["results"][0]["filename"] == "test.txt"


def test_ingest_url(monkeypatch):
    async def fake_process_url(url):
        return {"url": url, "status": "ok"}

    monkeypatch.setattr("app.routers.ingest.process_url", fake_process_url)

    response = client.post("/ingest/url/", data={"url": "http://example.com"})
    assert response.status_code == 200

    assert response.json() == {
        "status": "success",
        "result": {"url": "http://example.com", "status": "ok"}
    }


# --- Chat tests ---

def test_chat_endpoint(monkeypatch):
    async def fake_chat_with_assistant(messages, user_id):
        return f"echo: {messages[-1]['content']}"

    monkeypatch.setattr(
        "app.routers.chat.chat_with_assistant",
        fake_chat_with_assistant
    )

    payload = {
        "messages": [{"role": "user", "content": "ping"}],
        "user_id": "user123"
    }
    response = client.post("/chat/", json=payload)
    assert response.status_code == 200
    assert response.json() == {"reply": "echo: ping"}


# --- Exam scheduling tests ---

def test_schedule_exam(monkeypatch):
    fake_resp = {
        "confirmation_id": "abc-123",
        "scheduled_time": "2025-05-10T09:30:00",
        "status": "scheduled"
    }

    async def fake_schedule_exam(
        specialization, exam_type, scheduled_time, user_id, purpose=None
    ):
        return fake_resp

    # Patch the function imported into the router
    monkeypatch.setattr(
        "app.routers.exam.schedule_exam",
        fake_schedule_exam
    )

    payload = {
        "specialization": "Cardiology",
        "exam_type": "ECG",
        "scheduled_time": "2025-05-10T09:30:00",
        "user_id": "user1",
        "purpose": "routine check"
    }
    response = client.post("/exam/schedule", json=payload)
    assert response.status_code == 201
    assert response.json() == fake_resp


# --- Quotation tests ---

def test_request_quotation(monkeypatch):
    fake_resp = {
        "quote_id": "q-456",
        "eta": "2025-05-12T00:00:00",
        "status": "pending"
    }

    async def fake_request_quote(category, subcategory, details, user_id):
        return fake_resp

    monkeypatch.setattr(
        "app.routers.quotation.request_quote",
        fake_request_quote
    )

    payload = {
        "category": "Diagnosis",
        "subcategory": "Blood Test",
        "details": "Check CBC levels",
        "user_id": "user1"
    }
    response = client.post("/quote/request", json=payload)
    assert response.status_code == 201
    assert response.json() == fake_resp
