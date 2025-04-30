# app/services/feegow.py
import httpx
import os

FEEGOW_API_URL = "https://api.feegow.com/v1/api/appoints/new-appoint"
FEEGOW_TOKEN = os.getenv("FEEGOW_API_TOKEN")  # Add this to .env

async def forward_to_feegow(appointment: dict):
    payload = {
        "local_id": 0,
        "paciente_id": 5,  # You must map this properly
        "profissional_id": 10,  # Map from your doctor_id
        "especialidade_id": 95,  # Map from doctor or user
        "procedimento_id": 5,
        "data": appointment["scheduled_time"].strftime("%d-%m-%Y"),
        "horario": appointment["scheduled_time"].strftime("%H:%M:%S"),
        "valor": 550,
        "plano": 1,
        "convenio_id": 13,
        "convenio_plano_id": 3,
        "canal_id": 5,
        "tabela_id": 8,
        "notas": appointment.get("purpose", ""),
        "celular": "(12) 34567-8912",  # Optional: get from user if available
        "telefone": "(12) 3456-891)",
        "email": "email@email.com",
        "sys_user": 123456  # Optional: map from doctor or admin
    }

    headers = {
        "x-access-token": FEEGOW_TOKEN,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(FEEGOW_API_URL, json=payload, headers=headers)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPStatusError as e:
            print("❌ Feegow API Error:", e.response.text)
        except Exception as e:
            print("❌ Unexpected error while sending to Feegow:", str(e))
