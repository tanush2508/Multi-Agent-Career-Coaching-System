# career_coach/rag/retriever.py

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from .load_jobs import load_and_clean_jobs

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CLEAN_PATH = DATA_DIR / "jobs_clean.json"

# Use Cornell proxy embedding model
_embeddings = OpenAIEmbeddings(model="openai.text-embedding-3-small")

# Caches (in-memory copies of jobs + embeddings)
_JOBS_CACHE: Optional[List[Dict[str, Any]]] = None
_JOB_EMBEDDINGS: Optional[np.ndarray] = None


def reset_jobs_cache() -> None:
    """
    Clear in-memory jobs + embeddings so the next call to get_top_jobs()
    will reload jobs from disk and recompute embeddings.

    Call this right after load_and_clean_jobs(force_refresh=True, queries=...)
    when you fetch new jobs based on the current resume.
    """
    global _JOBS_CACHE, _JOB_EMBEDDINGS
    _JOBS_CACHE = None
    _JOB_EMBEDDINGS = None
    print("[retriever] Cache reset.")


def _load_jobs() -> List[Dict[str, Any]]:
    """
    Load jobs from jobs_clean.json.

    If the file does not exist, we automatically call
    load_and_clean_jobs(force_refresh=True) with default queries.
    """
    global _JOBS_CACHE

    if _JOBS_CACHE is not None:
        return _JOBS_CACHE

    if not CLEAN_PATH.exists():
        print(
            "[retriever] jobs_clean.json not found. "
            "Calling load_and_clean_jobs(force_refresh=True)..."
        )
        jobs = load_and_clean_jobs(force_refresh=True)
        _JOBS_CACHE = jobs
        return jobs

    try:
        data = json.loads(CLEAN_PATH.read_text(encoding="utf-8"))
        print(f"[retriever] Loaded {len(data)} jobs from jobs_clean.json")
        _JOBS_CACHE = data
        return data
    except Exception as e:
        print("[retriever] Failed to read jobs_clean.json:", e)
        # As a fallback, refresh from API with default queries
        jobs = load_and_clean_jobs(force_refresh=True)
        _JOBS_CACHE = jobs
        return jobs


def _ensure_embeddings() -> np.ndarray:
    """
    Ensure we have a 2D array of job embeddings with shape (n_jobs, dim).
    """
    global _JOB_EMBEDDINGS
    if _JOB_EMBEDDINGS is not None:
        return _JOB_EMBEDDINGS

    jobs = _load_jobs()
    if not jobs:
        _JOB_EMBEDDINGS = np.zeros((0, 1), dtype="float32")
        return _JOB_EMBEDDINGS

    texts = [
        f"{j.get('title', '')}\n{j.get('description', '')}"
        for j in jobs
    ]

    vectors = _embeddings.embed_documents(texts)
    job_vecs = np.array(vectors, dtype="float32")

    # Ensure 2D
    if job_vecs.ndim == 1:
        job_vecs = job_vecs.reshape(1, -1)

    _JOB_EMBEDDINGS = job_vecs
    print(f"[retriever] Built embeddings matrix of shape {_JOB_EMBEDDINGS.shape}")
    return _JOB_EMBEDDINGS


def get_top_jobs(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    Given a text query (built from resume details), return top-k job dicts
    with an added 'score' field for cosine similarity.
    """
    query = (query or "").strip()
    if not query:
        print("[retriever] Empty query passed to get_top_jobs; returning [].")
        return []

    jobs = _load_jobs()
    if not jobs:
        print("[retriever] No jobs available in jobs_clean.json")
        return []

    job_vecs = _ensure_embeddings()
    if job_vecs.size == 0:
        return []

    # Embed query
    q_vec = np.array(_embeddings.embed_query(query), dtype="float32")

    # Make sure q_vec is 1D (dim,)
    if q_vec.ndim > 1:
        q_vec = q_vec.flatten()

    # Cosine similarity
    job_norms = np.linalg.norm(job_vecs, axis=1)
    q_norm = np.linalg.norm(q_vec)
    denom = (job_norms * q_norm) + 1e-8  # avoid div by zero

    sims = (job_vecs @ q_vec) / denom

    # Top-k indices
    k = min(k, len(jobs))
    idxs = np.argsort(-sims)[:k]

    results: List[Dict[str, Any]] = []
    for idx in idxs:
        j = jobs[idx].copy()
        j["score"] = float(sims[idx])
        results.append(j)

    return results


def get_job_description_by_id(job_id: str) -> Optional[str]:
    """
    Helper for the interview screen: look up a job's full description by job_id.
    """
    jobs = _load_jobs()
    for j in jobs:
        if j.get("job_id") == job_id:
            return j.get("description") or ""
    return None
