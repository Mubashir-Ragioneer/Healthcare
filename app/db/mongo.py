# db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client = AsyncIOMotorClient(settings.MONGODB_URI)
db = client[settings.MONGODB_DB]
appointments_collection = db.get_collection("appointments")