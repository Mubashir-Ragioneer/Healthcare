# scripts/load_doctors_from_excel.py

import asyncio
import pandas as pd
from uuid import uuid4
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def load_doctors():
    # Load Excel
    df = pd.read_excel("app\scripts\specialists_nudii.xlsx")

    # Setup MongoDB
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB]
    doctors_collection = db["doctors"]

    # Optional: clear old records
    await doctors_collection.delete_many({})

    # Prepare new records
    records = []
    for _, row in df.iterrows():
        records.append({
            "id": f"doc-{uuid4().hex[:8]}",
            "name": row["Name"],
            "specialization": row["Specialization"],
            "registration": row["Registration"],
            "image_url": row["Image"],
        })

    # Insert into MongoDB
    if records:
        await doctors_collection.insert_many(records)
        print(f"✅ Inserted {len(records)} doctors into MongoDB.")

if __name__ == "__main__":
    asyncio.run(load_doctors())
