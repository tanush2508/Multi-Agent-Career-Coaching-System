from typing import List, Optional
from pydantic import BaseModel


class ResumeProfile(BaseModel):
    raw_text: str
    skills: List[str] = []
    experience_summary: str = ""
    years_experience: Optional[float] = None
    suggestions: List[str] = []
    # 🌟 NEW: candidate-specific job search queries inferred from resume
    job_search_queries: List[str] = []


class JobMatch(BaseModel):
    job_id: str
    score: float
    rationale: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None


class InterviewQuestion(BaseModel):
    question: str
    dimension: str
    ideal_answer_notes: str


class InterviewFeedback(BaseModel):
    question: str
    user_answer: str
    score: int
    strengths: List[str]
    improvements: List[str]
    summary: str


class SharedState(BaseModel):
    """
    Overall state we pass between agents / UI.
    """
    resume_profile: Optional[ResumeProfile] = None
    job_matches: List[JobMatch] = []
    selected_job_id: Optional[str] = None
    interview_questions: List[InterviewQuestion] = []
    feedback_history: List[InterviewFeedback] = []
