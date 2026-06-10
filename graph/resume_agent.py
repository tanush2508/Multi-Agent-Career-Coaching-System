# career_coach/graph/resume_agent.py

import json
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from .state import SharedState, ResumeProfile

load_dotenv()

# Use Cornell proxy model
_llm = ChatOpenAI(
    model="openai.gpt-4.1-mini",
    temperature=0.2,
)


def _load_prompt() -> str:
    """
    Load the system prompt for resume analysis from prompts/resume_analyzer.md
    """
    prompt_path = (
        Path(__file__)
        .resolve()
        .parent.parent  # graph/ -> career_coach/
        / "prompts"
        / "resume_analyzer.md"
    )
    return prompt_path.read_text(encoding="utf-8")


_RESUME_PROMPT = _load_prompt()


def _parse_resume_response(content: str) -> dict:
    """
    Try to parse the model output as JSON.
    If parsing fails, just return {} instead of crashing.
    """
    content = content.strip()
    if not content:
        print("[resume_agent] Empty LLM response")
        return {}

    # 1) Try direct JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2) Try to slice between the first { and last }
    start = content.find("{")
    end = content.rfind("}") + 1
    if 0 <= start < end:
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass

    # 3) Give up, but don't crash
    print("[resume_agent] Failed to parse JSON from LLM output. Raw content:")
    print(content)
    return {}


def _estimate_years_from_text(text: str) -> Optional[float]:
    """
    Very rough heuristic: look for year numbers like 2020, 2022, etc.
    Approximate experience as (max_year - min_year + 1), clamped 0–10.
    """
    years = sorted(
        {int(m.group(1)) for m in re.finditer(r"(20\d{2})", text)}
    )
    if len(years) < 2:
        return None

    approx = float(years[-1] - years[0] + 1)
    # clamp
    approx = max(0.0, min(10.0, approx))
    return approx


def _coerce_years_experience(data: dict, resume_text: str) -> Optional[float]:
    """
    Coerce the 'years_experience' field from the model into a float.
    If missing or invalid, try to estimate from the resume text.
    """
    raw = data.get("years_experience")
    years: Optional[float] = None

    # If model already returns a number
    if isinstance(raw, (int, float)):
        years = float(raw)

    # If model returns a string, try to parse it
    elif isinstance(raw, str):
        cleaned = raw.lower()
        # strip units like "years", "+", etc.
        for token in ["years", "year", "yrs", "yr", "+"]:
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.strip()
        try:
            years = float(cleaned)
        except ValueError:
            years = None

    # If model returns a dict like {"value": 2}
    elif isinstance(raw, dict):
        val = raw.get("value")
        if isinstance(val, (int, float)):
            years = float(val)
        elif isinstance(val, str):
            try:
                years = float(val.strip())
            except ValueError:
                years = None

    # If still None, fall back to heuristic
    if years is None:
        years = _estimate_years_from_text(resume_text)

    # Final clamp
    if years is not None:
        years = max(0.0, min(10.0, years))

    return years


def resume_analyzer_node(state: SharedState) -> SharedState:
    """
    Uses the LLM to analyze the resume and populate:
      - skills
      - experience_summary
      - years_experience
      - suggestions
      - job_search_queries (used later to call the job API)

    If JSON parsing fails, it still fills experience_summary using the raw text.
    """
    if not state.resume_profile or not state.resume_profile.raw_text.strip():
        return state

    resume_text = state.resume_profile.raw_text

    messages = [
        {"role": "system", "content": _RESUME_PROMPT},
        {"role": "user", "content": resume_text},
    ]

    resp = _llm.invoke(messages)
    content = resp.content if isinstance(resp.content, str) else str(resp.content)

    data = _parse_resume_response(content)

    # If JSON parsing fails, data == {}, but we still use the raw content as summary
    skills = data.get("skills") or []
    experience_summary = data.get("experience_summary") or content
    years_experience = _coerce_years_experience(data, resume_text)
    suggestions = data.get("suggestions") or []

    # 🌟 NEW: grab job_search_queries from the JSON
    job_search_queries = data.get("job_search_queries") or []

    state.resume_profile = ResumeProfile(
        raw_text=resume_text,
        skills=skills,
        experience_summary=experience_summary,
        years_experience=years_experience,
        suggestions=suggestions,
        job_search_queries=job_search_queries,
    )

    return state
