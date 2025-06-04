# app/schemas/specialist.py

from pydantic import BaseModel, AnyHttpUrl, Field
from typing import List, Optional, Union

class FindSpecialistRequest(BaseModel):
    query: str = Field(
        ...,
        description="User’s health question, e.g. ‘who should I see for cramps and diarrhea?’"
    )

class SpecialistProfile(BaseModel):
    response_message: str
    Name: str
    Specialization: str
    Registration: str
    Image: str
    doctor_description: str

class SpecialistSuggestion(BaseModel):
    # One of these will be populated depending on the response
    specialists: Optional[List[SpecialistProfile]] = None
    response_message: Optional[str] = None
    Name: Optional[str] = None
    Specialization: Optional[str] = None
    Registration: Optional[str] = None
    Image: Optional[str] = None
    doctor_description: Optional[str] = None
