# app/core/credentials.py

import os
import json
import pathlib
from google.oauth2 import service_account

# File paths
BASE_DIR = pathlib.Path(__file__).parent.parent.resolve()
CREDENTIALS_DIR = os.path.join(BASE_DIR, "credentials")
SERVICE_ACCOUNT_FILE = os.path.join(CREDENTIALS_DIR, "service-account.json")

# Create directory if it doesn't exist
os.makedirs(CREDENTIALS_DIR, exist_ok=True)

# Reconstruct credentials from environment
service_account_json = {
    "type": os.getenv("GCP_TYPE"),
    "project_id": os.getenv("GCP_PROJECT_ID"),
    "private_key_id": os.getenv("GCP_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GCP_PRIVATE_KEY", "").replace("\\n", "\n"),
    "client_email": os.getenv("GCP_CLIENT_EMAIL"),
    "client_id": os.getenv("GCP_CLIENT_ID"),
    "auth_uri": os.getenv("GCP_AUTH_URI"),
    "token_uri": os.getenv("GCP_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GCP_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GCP_CLIENT_X509_CERT_URL"),
}

# Save it to file
with open(SERVICE_ACCOUNT_FILE, "w") as f:
    json.dump(service_account_json, f)

# ✅ Exported credentials object
def get_gcp_credentials(scopes=["https://www.googleapis.com/auth/drive"]):
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )
