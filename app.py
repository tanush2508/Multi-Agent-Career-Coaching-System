import io

import streamlit as st

st.set_page_config(page_title="Multi-Agent Career Coach", layout="wide")

st.title("🎓 Multi-Agent Career Coaching System")
st.write("If you see this title, `app.py` is loading correctly.")

# ---------------------------------------------------------------------
# Try imports and show errors in the UI if they fail
# ---------------------------------------------------------------------

IMPORT_OK = True
IMPORT_ERROR = None

try:
    from dotenv import load_dotenv
    from PyPDF2 import PdfReader

    from graph.state import SharedState, ResumeProfile
    from graph.graph_resume import build_resume_graph
    from graph.interview_agent import (
        generate_questions_node,
        evaluate_answer_node,
    )
    from rag.retriever import get_job_description_by_id
except Exception as e:
    IMPORT_OK = False
    IMPORT_ERROR = e

if not IMPORT_OK:
    st.error("❌ Import error in `app.py`.")
    st.code(repr(IMPORT_ERROR), language="python")
    st.stop()

# If we reach here, imports worked
load_dotenv()
st.success("✅ Imports loaded correctly.")

# ---------------------------------------------------------------------
# Session State Setup  (keep this as a SharedState object)
# ---------------------------------------------------------------------

if "app_state" not in st.session_state:
    # This creates an empty SharedState model; defaults are in graph/state.py
    st.session_state.app_state = SharedState()

if "resume_graph" not in st.session_state:
    st.session_state.resume_graph = build_resume_graph()

app_state: SharedState = st.session_state.app_state


# ---------------------------------------------------------------------
# Helper: convert SharedState -> dict for LangGraph
# ---------------------------------------------------------------------

def _state_to_dict(state: SharedState) -> dict:
    # pydantic v2 uses model_dump, v1 uses dict
    if hasattr(state, "model_dump"):
        return state.model_dump()
    return state.dict()


# ---------------------------------------------------------------------
# Helper: Extract text from uploaded file
# ---------------------------------------------------------------------

def _extract_text_from_upload(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    name: str = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)

    st.warning("Unsupported file type. Please upload a .txt or .pdf file.")
    return ""


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------

st.sidebar.header("Steps")
st.sidebar.markdown("1. Upload resume\n2. Review matches\n3. Practice interviews")


# ---------------------------------------------------------------------
# Step 1: Resume upload & analysis
# ---------------------------------------------------------------------

st.header("1. Upload and Analyze Your Resume")

uploaded_file = st.file_uploader(
    "Upload your resume (.txt or .pdf)", type=["txt", "pdf"]
)

if st.button("Analyze Resume", type="primary"):
    text = _extract_text_from_upload(uploaded_file)

    if not text.strip():
        st.error("Could not read any text from the file. Please check the format.")
    else:
        # Work with SharedState object
        app_state: SharedState = st.session_state.app_state

        # Initialize / update resume_profile
        app_state.resume_profile = ResumeProfile(
            raw_text=text,
            skills=[],
            experience_summary="",
            years_experience=None,
            suggestions=[],
        )

        graph = st.session_state.resume_graph

        # LangGraph expects a dict-like state, so convert
        state_dict = _state_to_dict(app_state)
        new_state_dict = graph.invoke(state_dict)

        # Convert back into SharedState so the rest of the app can use dot-access
        st.session_state.app_state = SharedState(**new_state_dict)
        app_state = st.session_state.app_state

        st.success("Resume analyzed and job matches generated!")

# Always re-read the current SharedState
app_state: SharedState = st.session_state.app_state

# Show analysis if available
if app_state.resume_profile:
    rp = app_state.resume_profile

    st.subheader("Resume Summary")
    if rp.experience_summary:
        st.write(rp.experience_summary)
    else:
        st.write("_Summary not computed yet. Click 'Analyze Resume' above._")

    # 🔹 Approx. Years of Experience
    st.subheader("Approx. Years of Experience")
    if rp.years_experience is not None:
        st.write(f"{rp.years_experience:.1f} years")
    else:
        st.write("_Not estimated yet._")

    st.subheader("Key Skills")
    if rp.skills:
        st.write(", ".join(rp.skills))
    else:
        st.write("_No skills extracted yet._")

    st.subheader("Suggestions to Improve Your Resume")
    if rp.suggestions:
        for s in rp.suggestions:
            st.markdown(f"- {s}")
    else:
        st.write("_No suggestions yet._")

st.markdown("---")


# ---------------------------------------------------------------------
# Step 2: Job matches
# ---------------------------------------------------------------------

st.header("2. Job Matches")

if app_state.job_matches:
    for i, jm in enumerate(app_state.job_matches):
        label = (
            f"{jm.title or 'Job'} at {jm.company or 'Company'} "
            f"({jm.location or 'Location'}) — Score: {jm.score:.2f}"
        )

        with st.expander(label):
            # Fetch job description snippet for more context
            full_desc = get_job_description_by_id(jm.job_id) or ""
            if full_desc:
                preview = full_desc[:700]
                if len(full_desc) > 700:
                    preview += "..."
            else:
                preview = ""

            st.markdown("**Job overview:**")
            if preview:
                st.write(preview)
            else:
                st.write("_No description available from the API for this job._")

            st.markdown("**Why this is a good match for you:**")
            if jm.rationale:
                st.write(jm.rationale)
            else:
                st.write("_No detailed rationale generated._")

            st.markdown("---")

            if st.button("Select this job for interview practice", key=f"select_{i}"):
                # Mutate SharedState object directly
                app_state.selected_job_id = jm.job_id
                app_state.interview_questions = []
                app_state.feedback_history = []
                st.session_state.app_state = app_state
                st.success("Selected job for interview practice.")
else:
    st.write("_No job matches yet. Upload and analyze a resume first._")

st.markdown("---")


# ---------------------------------------------------------------------
# Step 3: Interview practice
# ---------------------------------------------------------------------

st.header("3. Interview Practice")

if app_state.selected_job_id:
    job_desc = get_job_description_by_id(app_state.selected_job_id)

    if job_desc:
        with st.expander("View selected job description"):
            preview = job_desc[:2500]
            if len(job_desc) > 2500:
                preview += "..."
            st.write(preview)

    # --- Generate questions button (always visible once a job is selected) ---
    if st.button("Generate Interview Questions", type="primary"):
        # Use the current SharedState
        app_state = st.session_state.app_state
        app_state = generate_questions_node(app_state)
        st.session_state.app_state = app_state
        app_state = st.session_state.app_state  # re-read
        if app_state.interview_questions:
            st.success(f"Generated {len(app_state.interview_questions)} questions.")
        else:
            st.error("Failed to generate questions. Try again.")

    # --- Show questions if we have any ---
    app_state = st.session_state.app_state  # make sure we have the latest
    if app_state.interview_questions:
        st.subheader("Questions and Feedback")

        for idx, q in enumerate(app_state.interview_questions):
            st.markdown(f"**Q{idx + 1}. {q.question}**  _({q.dimension})_")

            answer_key = f"answer_{idx}"
            user_answer = st.text_area(
                "Your answer",
                key=answer_key,
                placeholder="Type your answer here...",
            )

            if st.button("Get Feedback", key=f"feedback_{idx}") and user_answer.strip():
                app_state = st.session_state.app_state
                app_state = evaluate_answer_node(app_state, idx, user_answer)
                st.session_state.app_state = app_state

                fb = app_state.feedback_history[-1]
                st.markdown(f"**Score:** {fb.score}/5")
                st.markdown("**Strengths:**")
                for s in fb.strengths:
                    st.markdown(f"- {s}")
                st.markdown("**Areas for improvement:**")
                for im in fb.improvements:
                    st.markdown(f"- {im}")
                st.markdown(f"**Summary:** {fb.summary}")
else:
    st.write("_Select a job in Step 2 to start interview practice._")
