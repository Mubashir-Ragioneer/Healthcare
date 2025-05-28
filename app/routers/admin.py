# app/routers/admin.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import List, Dict
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.core.config import settings
from app.models.appointment import AppointmentInDB
from app.db.mongo import appointments_collection
from app.db.mongo import users_collection
from app.services.kommo import push_appointment_to_kommo
from app.services.feegow import forward_to_feegow
from app.routers.deps import require_admin
from app.utils.responses import format_response  # ✅ uniform response wrapper
from app.models.user import UserCreate
from passlib.context import CryptContext
from app.routers.deps import get_current_user
from app.utils.errors import NotFoundError, BadRequestError, ForbiddenError, InternalServerError
from app.utils.pagination import build_pagination, build_sort
from fastapi import Query


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


router = APIRouter(tags=["admin"])

# MongoDB setup
mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
db = mongo_client[settings.MONGODB_DB]
llm_settings_collection = db["llm_settings"]

# -----------------------------
# LLM Settings Schema
# -----------------------------

class LLMSettings(BaseModel):
    prompt: str = Field(..., description="System prompt for the LLM")
    temperature: float = Field(..., ge=0.0, le=1.0)
    max_tokens: int = Field(..., gt=0)
    model: str = Field(...)

    @validator("model")
    def validate_model(cls, v):
        allowed = {"gpt-4o","gpt-4o-mini", "gpt-3.5-turbo", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"}
        if v not in allowed:
            raise ValueError(f"Unsupported model: {v}")
        return v

# -----------------------------
# Admin Routes
# -----------------------------

@router.get("/llm", summary="Get current LLM settings")
async def get_llm_settings(current_user: dict = Depends(require_admin)):
    cfg = await llm_settings_collection.find_one({"_id": "config"})
    if not cfg:
        raise HTTPException(status_code=404, detail="LLM config not set")
    cfg.pop("_id", None)
    return format_response(success=True, data={"llm_settings": cfg})


@router.put("/llm", summary="Update LLM settings")
async def update_llm_settings(
    cfg: LLMSettings,
    current_user: dict = Depends(require_admin)
):
    await llm_settings_collection.update_one(
        {"_id": "config"},
        {"$set": cfg.dict()},
        upsert=True
    )
    return format_response(success=True, data={"llm_settings": cfg.dict()}, message="LLM settings updated")

@router.get("/unsynced", summary="View unsynced appointments")
async def get_unsynced_appointments(current_user: dict = Depends(require_admin)):
    query = {
        "$or": [
            {"kommo_synced": {"$ne": True}},
            {"feegow_synced": {"$ne": True}}
        ]
    }
    docs = await appointments_collection.find(query).to_list(length=100)
    return format_response(success=True, data={"unsynced_appointments": docs})

@router.post("/resync/{appointment_id}", summary="Resync a failed appointment")
async def resync_appointment(
    appointment_id: str,
    current_user: dict = Depends(require_admin)
):
    rec = await appointments_collection.find_one({"id": appointment_id})
    if not rec:
        raise HTTPException(status_code=404, detail="Appointment not found")

    feegow_synced = False
    kommo_synced = False

    try:
        await forward_to_feegow(rec)
        feegow_synced = True
    except Exception as e:
        print(f"❌ Feegow resync failed: {e}")

    try:
        await push_appointment_to_kommo(rec)
        kommo_synced = True
    except Exception as e:
        print(f"❌ Kommo resync failed: {e}")

    await appointments_collection.update_one(
        {"id": appointment_id},
        {"$set": {
            "feegow_synced": feegow_synced,
            "kommo_synced": kommo_synced
        }}
    )

    updated = await appointments_collection.find_one({"id": appointment_id})
    return format_response(success=True, data={"appointment": updated}, message="Resync completed")

@router.get("/sync-report", summary="Get sync summary report")
async def sync_report(current_user: dict = Depends(require_admin)):
    total = await appointments_collection.count_documents({})
    kommo_ok = await appointments_collection.count_documents({"kommo_synced": True})
    feegow_ok = await appointments_collection.count_documents({"feegow_synced": True})
    report = {
        "total_appointments": total,
        "kommo_synced": kommo_ok,
        "feegow_synced": feegow_ok,
        "kommo_unsynced": total - kommo_ok,
        "feegow_unsynced": total - feegow_ok
    }
    return format_response(success=True, data={"sync_report": report})

@router.post("/create-admin", summary="Create or promote an admin user")
async def create_admin(user: UserCreate, current_user: dict = Depends(require_admin)):
    existing = await users_collection.find_one({"email": user.email})

    if existing:
        await users_collection.update_one(
            {"email": user.email},
            {"$set": {"role": "admin"}}
        )
        return {"message": f"✅ User '{user.email}' promoted to admin"}
    
    hashed_password = pwd_context.hash(user.password)
    await users_collection.insert_one({
        "email": user.email,
        "password": hashed_password,
        "role": "admin"
    })
    return {"message": f"✅ Admin user '{user.email}' created successfully"}


@router.get("/all-users", summary="Get all users (admins and regular users)")
async def get_all_users(
    page: int = 1,
    page_size: int = 20,
    search: str = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_user: dict = Depends(require_admin),
):
    """
    Fetch all users (admins and non-admins) with pagination, search, and sorting.
    """
    try:
        skip, limit = build_pagination(page, page_size)
        sort = build_sort(sort_by, sort_order)

        query = {}
        if search:
            query["$or"] = [
                {"email": {"$regex": search, "$options": "i"}},
                {"name": {"$regex": search, "$options": "i"}},
            ]

        total = await users_collection.count_documents(query)
        cursor = users_collection.find(query).sort(sort).skip(skip).limit(limit)
        users = []
        async for user in cursor:
            user["_id"] = str(user["_id"])
            user.pop("password", None)
            users.append({
            "id": user["_id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role", "user"),
            "diagnosis": user.get("diagnosis"),
            "verified": user.get("verified", False),
            "created_at": user.get("created_at"),
        })

        return {
            "success": True,
            "users": users,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        raise InternalServerError(f"Failed to fetch users: {e}")


@router.get("/Get-All-Admins", summary="List all admin users")
async def list_admin_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None, description="Search by email or name"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_user: dict = Depends(require_admin)
):
    """
    Return a paginated, searchable, sortable list of all admin users in the database.
    """
    query = {"role": "admin"}
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"name": {"$regex": search, "$options": "i"}},
        ]
    sort_direction = -1 if sort_order.lower() == "desc" else 1
    cursor = users_collection.find(query).sort(sort_by, sort_direction).skip((page - 1) * page_size).limit(page_size)
    admins = []
    async for user in cursor:
        user["_id"] = str(user["_id"])
        admins.append({
            "id": user["_id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role"),
        })
    total = await users_collection.count_documents(query)
    return format_response(
        success=True,
        data={
            "admins": admins,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            }
        }
    )

@router.delete("/delete-user-by-email/{email}", summary="Delete any user by email")
async def delete_user_by_email(
    email: str,
    current_user: dict = Depends(require_admin)
):
    """
    Deletes a user by email. Admins cannot delete themselves or any Owner.
    Only the Owner can delete other Owners (including self).
    """
    email = email.strip().lower()
    current_email = current_user.get("email", "").strip().lower()
    current_role = current_user.get("role")

    if email == current_email:
        if current_role != "owner":
            raise ForbiddenError("Only the Owner can delete themselves.")

    user = await users_collection.find_one({"email": email})
    if not user:
        raise NotFoundError("User not found.")

    target_role = user.get("role")

    if target_role == "owner" and current_role != "owner":
        raise ForbiddenError("Only the Owner can delete another Owner.")

    result = await users_collection.delete_one({"email": email})
    if result.deleted_count == 0:
        raise InternalServerError("Failed to delete user.")

    return format_response(
        success=True,
        message=f"User '{email}' has been deleted."
    )

@router.delete("/remove-admin-by-email/{email}", summary="Demote an admin to user by email")
async def remove_admin_by_email(
    email: str,
    current_user: dict = Depends(require_admin)
):
    """
    Demote an admin to a regular user, by email.
    Admins cannot demote themselves or the Owner.
    Only the Owner can demote other Owners.
    """
    email = email.strip().lower()
    current_email = current_user.get("email", "").strip().lower()
    current_role = current_user.get("role")

    if email == current_email:
        raise ForbiddenError("You cannot demote yourself.")

    user = await users_collection.find_one({"email": email})
    if not user:
        raise NotFoundError("User not found.")

    target_role = user.get("role")

    if target_role == "owner":
        if current_role != "owner":
            raise ForbiddenError("Only the Owner can demote another Owner.")
    
    if target_role != "admin" and target_role != "owner":
        raise BadRequestError("Target user is not an admin or owner.")

    await users_collection.update_one(
        {"email": email},
        {"$set": {"role": "user"}}
    )

    return format_response(
        success=True,
        message=f"User '{email}' has been demoted to 'user'."
    )
@router.post("/transfer-ownership/{new_owner_email}", summary="Transfer ownership to another user")
async def transfer_ownership(
    new_owner_email: str,
    current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") != "owner":
        raise ForbiddenError("Only the current Owner can transfer ownership.")

    user = await users_collection.find_one({"email": new_owner_email})
    if not user:
        raise NotFoundError("Target user not found")

    # Downgrade current owner to admin
    await users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": {"role": "admin"}}
    )

    # Promote new owner
    await users_collection.update_one(
        {"email": new_owner_email},
        {"$set": {"role": "owner"}}
    )

    return format_response(success=True, message=f"Ownership transferred to {new_owner_email}")


@router.get("/me")
async def whoami(current_user: dict = Depends(get_current_user)):
    return current_user

@router.get("/clinical-trials", summary="List clinical trial form submissions")
async def list_clinical_trial_uploads(current_user: dict = Depends(require_admin)):
    from app.db.mongo import db
    collection = db["clinical_trial_uploads"]

    uploads = await collection.find().sort("submitted_at", -1).to_list(length=100)
    for u in uploads:
        u["_id"] = str(u["_id"])
        if "submitted_at" in u and hasattr(u["submitted_at"], "isoformat"):
            u["submitted_at"] = u["submitted_at"].isoformat()

    return format_response(success=True, data={"submissions": uploads})

@router.post("/cleanup", summary="Manually trigger old file cleanup")
async def cleanup_files(current_user: dict = Depends(require_admin)):
    from app.services.cleanup import delete_old_files

    deleted = delete_old_files()
    return format_response(
        success=True,
        message=f"{len(deleted)} old file(s) deleted.",
        data={"deleted_files": deleted}
    )
