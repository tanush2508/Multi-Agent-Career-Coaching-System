# Multi-Agent Career Coaching System

An end-to-end AI system that helps students and early-career professionals **discover relevant jobs**, **prepare for interviews**, and **receive structured feedback**, using a combination of **LLMs**, **retrieval-augmented generation (RAG)**, **job APIs**, and a **dynamic web crawler**.

Built as part of a **Cornell Information Science project**, this system emphasizes **real-world job coverage**, **resume-aware reasoning**, and **high-quality direct-apply opportunities**.

---

## What This System Does

### 1. Resume Understanding

When a user provides a resume, the system extracts and builds a structured **resume profile** containing:

- **Experience summary**  
  A concise textual summary of the candidate’s background.

- **Skills**  
  A normalized list of technical and role-specific skills (e.g., Python, React, ML, UX).

- **Years of experience (estimated)**  
  Used to avoid recommending roles that are far above or below the candidate’s seniority.

- **Domain signals**  
  Inferred focus areas (e.g., frontend, ML, data science, UX) used to guide job discovery.

This resume profile is reused throughout the pipeline to keep all downstream decisions consistent and personalized.

---

### 2. Job Discovery (High Coverage + High Quality)

The system fetches jobs using **three complementary layers**:

#### A. Job APIs (Maximum Volume)

- **JSearch API**
- **Adzuna API**

These provide broad coverage across many job boards and domains.

#### B. Search-Driven Company Discovery (No Hardcoding)

Using a search tool (**Serper**), the system dynamically discovers:

- Big tech companies  
- Mid-size tech companies  
- Startups  

based on the resume’s inferred domain and role interests.

#### C. Company Career-Site Crawler (Direct-Apply Jobs)

Many companies do not post all roles on job boards. To handle this, the system:

- Discovers official career pages (including **Greenhouse**, **Lever**, **Workday**)  
- Crawls career pages responsibly  
- Extracts structured job data via **JobPosting JSON-LD**  
- Falls back to lightweight internal link traversal when needed  

This layer significantly improves:

- Job freshness  
- Job completeness  
- Direct-apply opportunities  

---

### 3. Job Cleaning, Merging, and Deduplication

All jobs (API + crawl) are normalized into a single schema:

- `job_id` (stable across sources)  
- `title`  
- `company`  
- `location`  
- `employment_type`  
- `description`  
- `publisher / source`  

Duplicates are removed before saving.

---

### 4. Semantic Job Matching (RAG)

- All jobs are embedded using **OpenAI embeddings**
- Resume context is embedded into a single query
- Jobs are ranked using **cosine similarity**
- Top-K jobs are returned with relevance scores

This allows matching based on **meaning**, not keyword overlap.

---

### 5. Interview Preparation

For a selected job, the system:

- Generates tailored interview questions
- Uses resume + job description as context
- Evaluates candidate answers using a strict scoring rubric
- Returns structured **JSON feedback** (`score`, `strengths`, `improvements`, `summary`)

The evaluator **never rewrites answers** and **never invents details**.

---

## Why a Crawler Is Used (in Addition to APIs)

Job APIs alone are insufficient because:

- Many companies post jobs **only on their own career portals**
- APIs may lag behind real postings
- Some APIs require company slugs or have limited coverage

The crawler:

- Finds jobs APIs miss
- Works dynamically (no hardcoded company lists)
- Focuses on direct-apply, high-quality listings

This makes the system far more realistic and useful.

---

## Environment Variables

Create a `.env` file with the following:

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.ai.it.cornell.edu/
TZ=America/New_York

JSEARCH_API_KEY=
ADZUNA_APP_KEY=
SERPER_API_KEY=
```
Notes
OPENAI_BASE_URL is configured for Cornell’s OpenAI proxy

SERPER_API_KEY is required for dynamic company discovery

The crawler gracefully skips if a key is missing

Requirements
Install dependencies using:

bash
Copy code
pip install -r requirements.txt
requirements.txt

nginx
Copy code
streamlit
langchain
langgraph
openai
chromadb
langchain-community
pydantic
python-dotenv
pandas
numpy
langchain-openai
Running the System
Fetch Jobs
bash
Copy code
python -m rag.load_jobs
This will:

Fetch jobs from APIs

Discover companies dynamically

Crawl career pages

Build a unified job dataset

Reset Embeddings Cache (after new fetch)
Handled automatically, or manually via:

python
Copy code
reset_jobs_cache()
Run the App
bash
Copy code
streamlit run app.py
Key Design Principles
Resume-aware from start to finish

No hardcoded companies or roles

High-quality direct-apply jobs

Structured, deterministic outputs

Defensive parsing and error handling

Realistic constraints (rate limits, missing data, noise)

Status
The system is fully functional end-to-end:

Job ingestion

Crawling

Embeddings

Matching

Interview generation and evaluation

Optimizations (rate limiting, crawl caps, job filtering) can be added depending on scale.
