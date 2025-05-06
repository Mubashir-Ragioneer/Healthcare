# app/db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import Depends


client = AsyncIOMotorClient(settings.MONGODB_URI)
db = client[settings.MONGODB_DB]

# Collections
appointments_collection = db.get_collection("appointments")
documents_collection = db.get_collection("documents")
reception_requests_collection = db.get_collection("reception_requests")
exam_requests_collection = db.get_collection("exam_requests")
quote_requests_collection = db.get_collection("quote_requests")
url_ingestions_collection = db.get_collection("url_ingestions")
kommo_tokens_collection = db.get_collection("kommo_tokens")
users_collection = db.get_collection("users") 


# Function to check DB connection
async def verify_mongodb_connection():
    try:
        await client.server_info()
        print("✅ MongoDB Atlas connection established")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {str(e)}")

async def get_db() -> AsyncIOMotorDatabase:
    return db
