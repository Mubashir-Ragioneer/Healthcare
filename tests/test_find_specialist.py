import pytest
from fastapi.testclient import TestClient
from app import app

# Create a TestClient using your FastAPI app
client = TestClient(app)

# Monkey‐patch the find_specialist_response used in the router
@pytest.fixture(autouse=True)
def stub_find_specialist(monkeypatch):
    def fake_find_specialist(query: str):
        # Return exactly the six‐field dict your schema expects
        return {
            "response_message": "Sure! Based on your symptoms, you should see a specialist.",
            "Name": "Dr. Test",
            "Specialization": "Gastroenterologia",
            "Registration": "CRM-SP: 000000 | RQE: 00000",
            "Image": "https://example.com/test-doctor.jpg",
            "doctor_description": "Expert in digestive health with 10 years experience."
        }
    # Patch the function where it's imported in the router
    monkeypatch.setattr("app.routers.chat.find_specialist_response", fake_find_specialist)

def test_find_specialist_success():
    payload = {"query": "I've been having stomach pain—who should I see?"}
    response = client.post("/chat/find-specialist", json=payload)
    assert response.status_code == 200

    data = response.json()
    # Ensure all expected keys are present
    expected_keys = {
        "response_message",
        "Name",
        "Specialization",
        "Registration",
        "Image",
        "doctor_description",
    }
    assert set(data.keys()) == expected_keys

    # Spot‐check some values
    assert data["Name"] == "Dr. Test"
    assert data["Image"].startswith("https://")

def test_find_specialist_bad_payload():
    # Missing the "query" key entirely
    response = client.post("/chat/find-specialist", json={})
    assert response.status_code == 422  # Unprocessable Entity for payload validation
