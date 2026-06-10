# career_coach/graph/interview_agent.py

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from .state import SharedState, InterviewQuestion, InterviewFeedback
from rag.retriever import get_job_description_by_id

load_dotenv()

# ---------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------
MIN_ANSWER_WORDS = 10  # answers shorter than this are auto-scored as 1/5

# One model for questions, one for feedback (you can tune temps later)
_llm_questions = ChatOpenAI(
    model="openai.gpt-4.1-mini",
    temperature=0.5,
)

_llm_feedback = ChatOpenAI(
    model="openai.gpt-4.1-mini",
    temperature=0.2,
)

# ---------------------------------------------------------------------
# Prompt loaders
# ---------------------------------------------------------------------


def _load_questions_prompt() -> str:
    path = (
        Path(__file__).resolve().parent.parent  # graph/ -> career_coach/
        / "prompts"
        / "interview_questions.md"
    )
    return path.read_text(encoding="utf-8")


def _load_feedback_prompt() -> str:
    path = (
        Path(__file__).resolve().parent.parent  # graph/ -> career_coach/
        / "prompts"
        / "interview_feedback.md"
    )
    return path.read_text(encoding="utf-8")


_QUESTIONS_PROMPT = _load_questions_prompt()
_FEEDBACK_PROMPT = _load_feedback_prompt()

# ---------------------------------------------------------------------
# Robust parsing helpers
# ---------------------------------------------------------------------


def _parse_questions(content: str) -> List[Dict[str, Any]]:
    content = content.strip()
    if not content:
        print("[interview_agent] Empty LLM questions response")
        return []

    # 1) Direct JSON
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            return data["questions"]
    except json.JSONDecodeError:
        pass

    # 2) Try bracket slice
    start = content.find("[")
    end = content.rfind("]") + 1
    if 0 <= start < end:
        snippet = content[start:end]
        try:
            data = json.loads(snippet)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("questions"), list):
                return data["questions"]
        except json.JSONDecodeError:
            pass

    print("[interview_agent] Failed to parse questions JSON, raw content:")
    print(content[:800])
    return []


def _parse_feedback(content: str) -> Dict[str, Any]:
    """
    Expected JSON:

    {
      "score": 1-5,
      "strengths": ["...", "..."],
      "improvements": ["...", "..."],
      "summary": "..."
    }
    """
    content = content.strip()
    if not content:
        print("[interview_agent] Empty LLM feedback response")
        return {}

    # 1) Direct JSON
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 2) Try brace slice
    start = content.find("{")
    end = content.rfind("}") + 1
    if 0 <= start < end:
        snippet = content[start:end]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 3) Fallback: hard-fail (so invalid JSON cannot look "okay")
    print("[interview_agent] Failed to parse feedback JSON, raw content:")
    print(content[:800])
    return {
        "score": 1,
        "strengths": [],
        "improvements": ["Model returned invalid JSON. Re-try evaluation."],
        "summary": "Evaluator output was not valid JSON, so feedback could not be reliably parsed.",
    }


def _coerce_str_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        out: List[str] = []
        for item in x:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    s = str(x).strip()
    return [s] if s else []


def _clamp_score_1_5(raw_score: Any) -> int:
    try:
        val = int(round(float(raw_score)))
    except (TypeError, ValueError):
        val = 3
    return max(1, min(5, val))


def _make_feedback_item(
    *,
    question_index: int,
    question: str,
    user_answer_text: str,
    score: int,
    strengths: List[str],
    improvements: List[str],
    summary: str,
) -> InterviewFeedback:
    """
    Robust to field name mismatch: some models use 'user_answer', others 'answer'.
    """
    fields = getattr(InterviewFeedback, "model_fields", {}) or {}

    base_kwargs = dict(
        question_index=question_index,
        question=question,
        score=score,
        strengths=strengths,
        improvements=improvements,
        summary=summary,
    )

    if "user_answer" in fields:
        return InterviewFeedback(**base_kwargs, user_answer=user_answer_text)

    if "answer" in fields:
        return InterviewFeedback(**base_kwargs, answer=user_answer_text)

    # Last resort
    try:
        return InterviewFeedback(**base_kwargs, user_answer=user_answer_text)
    except Exception:
        return InterviewFeedback(**base_kwargs, answer=user_answer_text)


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------


def generate_questions_node(state: SharedState) -> SharedState:
    if not state.selected_job_id:
        print("[interview_agent] No selected_job_id; cannot generate questions.")
        return state

    job_desc = get_job_description_by_id(state.selected_job_id)
    if not job_desc:
        print(
            "[interview_agent] No job description found for "
            f"job_id={state.selected_job_id}"
        )
        return state

    rp = state.resume_profile

    payload = {
        "job_description": job_desc,
        "resume_summary": rp.experience_summary if rp else "",
        "skills": rp.skills if rp and rp.skills else [],
        "years_experience": rp.years_experience if rp else None,
    }

    messages = [
        {"role": "system", "content": _QUESTIONS_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]

    try:
        resp = _llm_questions.invoke(messages)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        print("[interview_agent] Raw questions LLM output (first 800 chars):")
        print(content[:800])
    except Exception as e:
        print("[interview_agent] Error calling LLM for questions:", e)
        content = ""

    question_dicts = _parse_questions(content)

    questions: List[InterviewQuestion] = []

    if question_dicts:
        for qd in question_dicts:
            if not isinstance(qd, dict):
                continue

            q_text = qd.get("question")
            if not q_text:
                continue

            dim = qd.get("dimension", "general") or "general"
            raw_notes = qd.get("ideal_answer_notes", "")

            if isinstance(raw_notes, list):
                cleaned_items = [str(x).strip() for x in raw_notes if str(x).strip()]
                notes = "• " + "\n• ".join(cleaned_items) if cleaned_items else ""
            elif raw_notes is None:
                notes = ""
            else:
                notes = str(raw_notes).strip()

            questions.append(
                InterviewQuestion(
                    question=str(q_text).strip(),
                    dimension=str(dim).strip(),
                    ideal_answer_notes=notes,
                )
            )
    else:
        questions.append(
            InterviewQuestion(
                question=(
                    "Tell me about a project or experience that best demonstrates "
                    "your skills for this role."
                ),
                dimension="general",
                ideal_answer_notes=(
                    "Candidate should pick one strong, relevant project, "
                    "describe context, actions, and measurable impact."
                ),
            )
        )

    state.interview_questions = questions
    return state


def evaluate_answer_node(
    state: SharedState,
    question_index: int,
    answer: str,
) -> SharedState:
    """
    Evaluate a user's answer to a specific interview question.
    Appends one InterviewFeedback to state.feedback_history.
    """
    if not state.interview_questions:
        print("[interview_agent] No interview_questions in state.")
        return state

    if question_index < 0 or question_index >= len(state.interview_questions):
        print(
            f"[interview_agent] Invalid question_index={question_index}, "
            f"len(interview_questions)={len(state.interview_questions)}"
        )
        return state

    q = state.interview_questions[question_index]
    answer_clean = (answer or "").strip()

    # ✅ Hard guardrail: too-short answers auto-fail (and we skip LLM entirely)
    if len(answer_clean.split()) < MIN_ANSWER_WORDS:
        feedback_item = _make_feedback_item(
            question_index=question_index,
            question=q.question,
            user_answer_text=answer_clean,
            score=1,
            strengths=[],
            improvements=[
                "Your answer is too brief to evaluate.",
                "Name a specific project and your role.",
                "Explain the two modalities (e.g., images + sensor data), how you aligned/merged them (timestamps, IDs, schema), and the biggest integration challenge.",
                "Add 1–2 concrete actions you took (cleaning, syncing, feature fusion) and 1 measurable outcome.",
            ],
            summary="Answer was too short and did not include a concrete project, multimodal integration details, or actions taken.",
        )
        state.feedback_history.append(feedback_item)
        return state

    rp = state.resume_profile
    job_desc: Optional[str] = None
    if state.selected_job_id:
        job_desc = get_job_description_by_id(state.selected_job_id)

    payload = {
        "question": q.question,
        "dimension": q.dimension,
        "ideal_answer_notes": getattr(q, "ideal_answer_notes", ""),
        "answer": answer_clean,
        "resume_summary": rp.experience_summary if rp else "",
        "skills": rp.skills if rp and rp.skills else [],
        "years_experience": rp.years_experience if rp else None,
        "job_description": job_desc or "",
    }

    messages = [
        {"role": "system", "content": _FEEDBACK_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]

    try:
        resp = _llm_feedback.invoke(messages)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        print("[interview_agent] Raw feedback LLM output (first 800 chars):")
        print(content[:800])
    except Exception as e:
        print("[interview_agent] Error calling LLM for feedback:", e)
        content = ""

    fb_dict = _parse_feedback(content)

    score = _clamp_score_1_5(fb_dict.get("score", 3))
    strengths = _coerce_str_list(fb_dict.get("strengths"))
    improvements = _coerce_str_list(fb_dict.get("improvements"))
    summary = str(fb_dict.get("summary") or "").strip()

    feedback_item = _make_feedback_item(
        question_index=question_index,
        question=q.question,
        user_answer_text=answer_clean,
        score=score,
        strengths=strengths,
        improvements=improvements,
        summary=summary,
    )

    state.feedback_history.append(feedback_item)
    return state
