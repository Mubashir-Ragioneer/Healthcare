# tests/test_api.py
# tests/test_api.py

import os, sys
# Add the project root (the folder containing `app/`) to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from app.main import app

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Healthcare AI Assistant"}

def test_get_llm_settings():
    response = client.get("/admin/llm")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"prompt", "temperature", "max_tokens", "model"}

def test_list_doctors():
    response = client.get("/doctors")
    assert response.status_code == 200
    doctors = response.json()
    assert isinstance(doctors, list)
    assert all({"id", "name", "specialization"} <= d.keys() for d in doctors)

def test_book_appointment_validation_error():
    # Missing the "purpose" field
    payload = {
        "user_id": "user1",
        "doctor_id": "doc-1",
        "datetime": "2025-05-01T10:00:00Z"
    }
    response = client.post("/doctors/book", json=payload)
    assert response.status_code == 422  # Unprocessable Entity

def test_receptionist_after_hours(monkeypatch):
    # Simulate current time = 20:00 UTC
    import datetime
    class DummyDT:
        @classmethod
        def utcnow(cls):
            return datetime.datetime(2025, 1, 1, 20, 0, 0)
    monkeypatch.setattr("app.routers.receptionist.datetime", DummyDT)

    payload = {"name": "Alice", "phone": "+1234567890", "reason": "Help"}
    response = client.post("/reception/request", json=payload)
    assert response.status_code == 200
    assert "Office is closed" in response.json()["message"]
