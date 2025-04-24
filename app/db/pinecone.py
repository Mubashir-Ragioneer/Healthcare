from pinecone import Pinecone, ServerlessSpec
from app.core.config import settings

# Initialize client
pc = Pinecone(api_key=settings.PINECONE_API_KEY)

index_name = settings.PINECONE_INDEX

# Create index if it doesn't exist
if index_name not in [i.name for i in pc.list_indexes()]:
    pc.create_index(
        name=index_name,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        )
    )

# Load index
index = pc.Index(index_name)
