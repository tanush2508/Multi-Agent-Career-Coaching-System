from pathlib import Path

import chromadb
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv

from .load_jobs import load_and_clean_jobs

load_dotenv()  # picks up OPENAI_API_KEY and OPENAI_BASE_URL

CHROMA_PATH = Path("chroma_store")  # folder created at project root
COLLECTION_NAME = "jobs"


def build_index():
    jobs = load_and_clean_jobs()
    if not jobs:
        raise ValueError("No jobs found to index. Check data/jobs_raw.csv.")

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    embedder = OpenAIEmbeddings(model="openai.text-embedding-3-small")

    texts = [
        job.description + "\n\n" + job.requirements
        for job in jobs
    ]
    ids = [job.id for job in jobs]
    metadatas = [
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
        }
        for job in jobs
    ]

    print(f"Embedding {len(jobs)} job postings...")
    embeddings = embedder.embed_documents(texts)

    # Clear old docs, then add
    collection.delete(where={})
    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=texts,
    )
    print("Index built successfully at", CHROMA_PATH)


if __name__ == "__main__":
    build_index()
