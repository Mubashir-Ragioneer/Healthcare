from openai import OpenAI
from app.core.config import settings
from app.db.pinecone import index

# Initialize OpenAI client
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL
)

async def get_embedding(query: str) -> list[float]:
    """Generate embedding for the input query text."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    return response.data[0].embedding

async def search_similar_chunks(query: str, top_k: int = 5) -> list[dict]:
    """Search Pinecone for document chunks most similar to the query."""
    query_vector = await get_embedding(query)

    search_result = index.query(
        vector=query_vector,
        top_k=top_k,
        include_metadata=True
    )

    return search_result['matches']
