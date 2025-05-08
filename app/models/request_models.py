# app/models/request_models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ReceptionRequest(BaseModel):
    name: str
    phone: str
    reason: str
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class ExamRequest(BaseModel):
    patient_name: str
    exam_type: str
    preferred_date: str
    notes: Optional[str] = ""
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class QuoteRequest(BaseModel):
    name: str
    email: str
    service_needed: str
    details: Optional[str] = ""
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ClinicalTrialForm(BaseModel):
    full_name: str
    diagnosis: str  # Crohn’s or Ulcerative Colitis
    medications: Optional[str] = ""
    test_results_description: Optional[str] = ""
    lead_source: Optional[str] = "nudii.com.br"
