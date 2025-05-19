# app/schemas/specialist.py

from pydantic import BaseModel, AnyHttpUrl, Field
from typing import Optional

class FindSpecialistRequest(BaseModel):
    query: str = Field(
        ...,
        description="User’s health question, e.g. ‘who should I see for cramps and diarrhea?’"
    )

class SpecialistSuggestion(BaseModel):
    response_message: str
    Name:               str
    Specialization:     str
    Registration:       str
    Image: Optional[AnyHttpUrl] = None
    doctor_description: str
