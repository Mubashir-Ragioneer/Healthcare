# app/services/vector_store.py

from typing import List
from app.db.pinecone import index
from app.core.config import settings
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor
import asyncio

# OpenAI embedding setup
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)
executor = ThreadPoolExecutor()

# 🔧 Generate embedding asynchronously using a thread pool
async def embed_text(text: str) -> List[float]:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(executor, lambda: client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ))
    return res.data[0].embedding

# 🧩 Chunking utility
def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# 🚀 Upsert chunks with embeddings to Pinecone
async def upsert_to_pinecone(doc_id: str, text: str, user_id: str) -> int:
    chunks = chunk_text(text)
    embeddings = await asyncio.gather(*[embed_text(chunk) for chunk in chunks])

    vectors = [
        {
            "id": f"{doc_id}-{i}",
            "values": embedding,
            "metadata": {
                "chunk_text": chunk,
                "doc_id": doc_id,
                "user_id": user_id
            }
        }
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    index.upsert(vectors)
    print(f"📌 Upserted {len(vectors)} chunks to Pinecone for doc_id: {doc_id}")
    return len(vectors)
