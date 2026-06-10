# career_coach/graph/job_matcher_agent.py

import json
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from .state import SharedState, JobMatch
from rag.retriever import get_top_jobs, reset_jobs_cache   # 🔹 NEW
from rag.load_jobs import load_and_clean_jobs              # 🔹 NEW

load_dotenv()

# LLM used only for re-ranking + rationales
_llm = ChatOpenAI(
    model="openai.gpt-4.1-mini",
    temperature=0.3,
)


def _load_prompt() -> str:
    prompt_path = (
        Path(__file__)
        .resolve()
        .parent.parent  # graph/ -> career_coach/
        / "prompts"
        / "job_matcher.md"
    )
    return prompt_path.read_text(encoding="utf-8")


_JOB_MATCHER_PROMPT = _load_prompt()


def _build_query_from_resume(state: SharedState) -> str:
    """
    Build a semantic query string from the structured resume profile.
    This is what we feed to the embedding retriever.
    """
    rp = state.resume_profile
    if not rp:
        return ""

    parts: List[str] = []

    if rp.skills:
        parts.append("Skills: " + ", ".join(rp.skills))

    if rp.experience_summary:
        parts.append("Summary: " + rp.experience_summary)

    if rp.years_experience is not None:
        parts.append(f"Years of experience: {rp.years_experience:.1f}")

    if not parts:
        parts.append(rp.raw_text[:1000])

    return "\n".join(parts)


def _parse_matches(content: str) -> List[Dict[str, Any]]:
    """
    Try to parse the LLM output as a JSON list of job match dicts.

    Expected (from prompts/job_matcher.md):

    [
      {
        "job_id": "123",
        "score": 0.87,
        "rationale": "Short explanation..."
      },
      ...
    ]
    """
    content = content.strip()
    if not content:
        return []

    # 1) Direct JSON
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 2) Slice [ ... ]
    start = content.find("[")
    end = content.rfind("]") + 1
    if 0 <= start < end:
        try:
            data = json.loads(content[start:end])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    print("[job_matcher_agent] Failed to parse JSON from LLM output:")
    print(content[:800])
    return []


def job_matcher_node(state: SharedState) -> SharedState:
    """
    Main node for the job matcher agent.

    1. Builds a query from resume_profile.
    2. Uses resume_profile.job_search_queries to fetch jobs from JSearch.
    3. Uses embedding retriever to get candidate jobs.
    4. Calls LLM to pick + re-rank best matches.
    5. Stores them as state.job_matches (list[JobMatch]).

    If the LLM output isn't valid JSON, we fall back to using
    the raw embedding similarity scores.
    """
    if not state.resume_profile or not state.resume_profile.raw_text.strip():
        return state

    rp = state.resume_profile

    # 1) Build semantic query for embeddings
    query = _build_query_from_resume(state)
    if not query.strip():
        return state

    # 2) Use job_search_queries from resume to FETCH jobs dynamically
    job_queries = rp.job_search_queries or []
    if job_queries:
        print("[job_matcher_agent] Using resume-based job_search_queries:", job_queries)
        # This overwrites jobs_clean.json with fresh results from JSearch
        load_and_clean_jobs(force_refresh=True, queries=job_queries)
        # Reset in-memory cache so retriever reloads and re-embeds
        reset_jobs_cache()
    else:
        print(
            "[job_matcher_agent] No job_search_queries in resume_profile; "
            "using whatever is already in jobs_clean.json."
        )

    # 3) Now retrieve candidates from the freshly-updated jobs_clean.json
    candidates = get_top_jobs(query, k=15)
    if not candidates:
        print("[job_matcher_agent] get_top_jobs returned no candidates.")
        return state

    # 4) Ask LLM to re-rank and pick top matches
    payload = {
        "resume": {
            "skills": rp.skills,
            "experience_summary": rp.experience_summary,
            "years_experience": rp.years_experience,
        },
        "candidates": candidates,
    }

    messages = [
        {"role": "system", "content": _JOB_MATCHER_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]

    try:
        resp = _llm.invoke(messages)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        print("[job_matcher_agent] Raw LLM output (first 800 chars):")
        print(content[:800])
    except Exception as e:
        print("[job_matcher_agent] Error calling LLM for job matching:", e)
        content = ""

    match_dicts = _parse_matches(content)

    job_matches: List[JobMatch] = []
    by_id: Dict[str, Dict[str, Any]] = {j["job_id"]: j for j in candidates}

    if match_dicts:
        # ✅ LLM JSON path
        for m in match_dicts:
            job_id = m.get("job_id")
            if not job_id:
                continue

            job = by_id.get(job_id)
            if not job:
                continue

            final_score = float(m.get("score", job.get("score", 0.0)))
            rationale = m.get("rationale", "")

            job_matches.append(
                JobMatch(
                    job_id=job_id,
                    title=job.get("title") or "",
                    company=job.get("company") or "",
                    location=job.get("location") or "",
                    score=final_score,
                    rationale=rationale,
                )
            )
    else:
        # ❗ Fallback: no JSON, just use candidates directly
        print(
            "[job_matcher_agent] No JSON parsed from LLM; "
            "falling back to similarity-based matches."
        )
        top_k = min(5, len(candidates))
        for j in candidates[:top_k]:
            job_matches.append(
                JobMatch(
                    job_id=j["job_id"],
                    title=j.get("title") or "",
                    company=j.get("company") or "",
                    location=j.get("location") or "",
                    score=float(j.get("score", 0.0)),
                    rationale=(
                        "Baseline match based on semantic similarity between this job "
                        "and your skills, experience summary, and years of experience."
                    ),
                )
            )

    state.job_matches = job_matches
    return state
