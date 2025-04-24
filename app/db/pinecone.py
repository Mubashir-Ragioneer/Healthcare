from pinecone import Pinecone, CloudProvider, AwsRegion

from app.core.config import settings

# Initialize Pinecone client
pc = Pinecone(api_key=settings.PINECONE_API_KEY)

# Optionally create index if not exists
index_name = settings.PINECONE_INDEX

if index_name not in pc.list_indexes().names():
    pc.create_index_for_model(
        name=index_name,
        cloud=CloudProvider.AWS,
        region=AwsRegion.US_EAST_1,
        embed={
            "model": "multilingual-e5-large",
            "field_map": {"text": "chunk_text"},
            "metric": "cosine"
        }
    )

# Load index
index = pc.Index(index_name)
