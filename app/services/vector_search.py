# app/services/vector_search.py
from openai import OpenAI
from app.core.config import settings
from app.db.pinecone import index
from typing import List
from concurrent.futures import ThreadPoolExecutor
import asyncio

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)
executor = ThreadPoolExecutor()

async def get_embedding(query: str) -> List[float]:
    """Asynchronously generate embedding for the input text."""
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, lambda: client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ))
    return response.data[0].embedding

async def search_similar_chunks(query: str, top_k: int = 3) -> List[dict]:
    """Search Pinecone for chunks similar to the query, scoped by user_id."""
    query_vector = await get_embedding(query)
    search_result = index.query(
        vector=query_vector,
        top_k=top_k,
        include_metadata=True
    )
    return search_result["matches"]
