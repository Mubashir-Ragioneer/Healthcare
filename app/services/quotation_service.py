# app/services/quotation_service.py

import uuid
from datetime import datetime, timedelta
from pydantic import BaseModel, ConfigDict

class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quote_id: str
    eta: datetime
    status: str

async def request_quote(
    category: str,
    subcategory: str,
    details: str,
    user_id: str,
) -> QuoteResponse:
    """
    Simulate generating a quotation request.
    ETA is 2 days from now.
    """
    return QuoteResponse(
        quote_id=str(uuid.uuid4()),
        eta=datetime.utcnow() + timedelta(days=2),
        status="pending",
    )
