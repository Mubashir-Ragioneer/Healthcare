# app/services/vector_store.py

from typing import List
from sentence_transformers import SentenceTransformer
from app.db.pinecone import index
from uuid import uuid4

# Load embedding model
embedder = SentenceTransformer("intfloat/multilingual-e5-large")

CHUNK_SIZE = 300  # characters per chunk
CHUNK_OVERLAP = 50

def chunk_text(text: str) -> List[str]:
    """
    Splits large text into overlapping chunks for embedding.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks

def upsert_text_to_pinecone(doc_id: str, text: str):
    """
    Chunks, embeds, and upserts text into Pinecone.
    """
    chunks = chunk_text(text)
    embeddings = embedder.encode(chunks).tolist()

    vectors = [{
        "id": f"{doc_id}-{i}",
        "values": embeddings[i],
        "metadata": {"chunk_text": chunks[i], "doc_id": doc_id}
    } for i in range(len(chunks))]

    index.upsert(vectors)
