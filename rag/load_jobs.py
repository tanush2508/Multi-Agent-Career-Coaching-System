import os
import json
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# -------------------------
# JSearch config (optional)
# -------------------------
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")
JSEARCH_BASE_URL = "https://api.openwebninja.com/jsearch/search"

# -------------------------
# Adzuna config
# -------------------------
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search"

# -------------------------
# Search tool config (Serper)
# -------------------------
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_URL = "https://google.serper.dev/search"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "jobs_raw.json"
CLEAN_PATH = DATA_DIR / "jobs_clean.json"

# -------------------------
# LLM for company picking
# -------------------------
_llm_company_picker = ChatOpenAI(model="openai.gpt-4.1-mini", temperature=0.2)


def _split_query_location(q: str) -> Tuple[str, str]:
    q_strip = (q or "").strip()
    lower = q_strip.lower()
    token = " in "
    if token in lower:
        idx = lower.rfind(token)
        what = q_strip[:idx].strip()
        where = q_strip[idx + len(token):].strip()
        return what, where
    return q_strip, ""


# ---------------------------------------------------------------------
# JSearch fetch (optional)
# ---------------------------------------------------------------------
def _fetch_jobs_from_jsearch(
    queries: List[str],
    pages_per_query: int = 1,
) -> List[Dict[str, Any]]:
    if not JSEARCH_API_KEY:
        print("[JSEARCH] Missing JSEARCH_API_KEY; skipping JSearch fetch.")
        return []

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_jobs: List[Dict[str, Any]] = []
    headers = {"x-api-key": JSEARCH_API_KEY, "Accept": "*/*"}

    for q in queries:
        for page in range(1, pages_per_query + 1):
            params = {
                "query": q,
                "page": page,
                "num_pages": 1,
                "country": "us",
                "language": "en",
                "date_posted": "month",
                "work_from_home": "false",
                "employment_types": "FULLTIME",
                "job_requirements": "no_experience",
                "radius": 25,
            }

            print(f"[JSEARCH] Fetching page {page} for query='{q}'")
            resp = requests.get(JSEARCH_BASE_URL, headers=headers, params=params, timeout=30)

            # Stop early on auth errors
            if resp.status_code == 401:
                print("[JSEARCH] 401 Unauthorized. Check JSEARCH_API_KEY. Stopping JSearch early.")
                return all_jobs

            try:
                resp.raise_for_status()
            except Exception as e:
                print(f"[JSEARCH] Error for query='{q}', page={page}: {e}")
                print("Response text:", resp.text[:500])
                continue

            data = resp.json()
            items = data.get("data")
            if items is None and isinstance(data, list):
                items = data

            count = len(items or [])
            print(f"[JSEARCH] Got {count} items for query='{q}', page={page}")
            if items:
                all_jobs.extend(items)

    print(f"[JSEARCH] Total raw jobs fetched: {len(all_jobs)}")
    return all_jobs


def _clean_jobs_jsearch(raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []

    for j in raw_jobs:
        job_id = j.get("job_id")
        if not job_id:
            continue

        title = j.get("job_title") or ""
        company = j.get("employer_name") or ""
        city = j.get("job_city") or ""
        state = j.get("job_state") or ""
        country = j.get("job_country") or ""

        location_parts = [p for p in [city, state, country] if p]
        location = ", ".join(location_parts) if location_parts else ""

        description = j.get("job_description") or ""
        employment_type = j.get("job_employment_type") or ""
        publisher = j.get("job_publisher") or "jsearch"

        cleaned.append(
            {
                "job_id": str(job_id),
                "title": title,
                "company": company,
                "location": location,
                "employment_type": employment_type,
                "publisher": publisher,
                "description": description,
            }
        )

    print(f"[JSEARCH] Cleaned jobs: {len(cleaned)}")
    return cleaned


# ---------------------------------------------------------------------
# Adzuna fetch + clean
# ---------------------------------------------------------------------
def _fetch_jobs_from_adzuna(
    queries: List[str],
    pages_per_query: int = 1,
    results_per_page: int = 20,
) -> List[Dict[str, Any]]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[ADZUNA] Missing ADZUNA_APP_ID or ADZUNA_APP_KEY in .env; skipping Adzuna fetch.")
        return []

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_results: List[Dict[str, Any]] = []

    headers = {"Accept": "application/json"}

    for q in queries:
        what, where = _split_query_location(q)

        for page in range(1, pages_per_query + 1):
            url = f"{ADZUNA_BASE_URL}/{page}"

            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "what": what,
                **({"where": where} if where else {}),
                "results_per_page": results_per_page,
                "content-type": "application/json",
            }

            print(f"[ADZUNA] Fetching page {page} for query='{q}' (what='{what}', where='{where}')")
            resp = requests.get(url, headers=headers, params=params, timeout=30)

            try:
                resp.raise_for_status()
            except Exception as e:
                print(f"[ADZUNA] Error for query='{q}', page={page}: {e}")
                print("Response text:", resp.text[:500])
                continue

            data = resp.json()
            items = data.get("results") or []
            print(f"[ADZUNA] Got {len(items)} items for query='{q}', page={page}")

            if items:
                all_results.extend(items)

    print(f"[ADZUNA] Total raw jobs fetched: {len(all_results)}")
    return all_results


def _stable_id_from_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def _clean_jobs_adzuna(raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []

    for j in raw_jobs:
        raw_id = j.get("id")
        redirect_url = j.get("redirect_url") or ""
        title = j.get("title") or ""
        company = (j.get("company") or {}).get("display_name") or ""
        location = (j.get("location") or {}).get("display_name") or ""
        description = j.get("description") or ""

        contract_time = j.get("contract_time") or ""
        contract_type = j.get("contract_type") or ""
        employment_type = " ".join([x for x in [contract_time, contract_type] if x]).strip()

        if raw_id is not None:
            job_id = f"adzuna:{raw_id}"
        else:
            job_id = "adzuna:" + _stable_id_from_text(f"{title}|{company}|{location}|{redirect_url}")

        cleaned.append(
            {
                "job_id": str(job_id),
                "title": title,
                "company": company,
                "location": location,
                "employment_type": employment_type,
                "publisher": "adzuna",
                "description": description,
            }
        )

    print(f"[ADZUNA] Cleaned jobs: {len(cleaned)}")
    return cleaned


# ---------------------------------------------------------------------
# Serper search
# ---------------------------------------------------------------------
def _serper_search(query: str, k: int = 8) -> List[Dict[str, str]]:
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY is not set in .env")

    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "num": k}
    resp = requests.post(SERPER_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    out = []
    for item in (data.get("organic") or []):
        link = item.get("link")
        if link:
            out.append(
                {
                    "title": item.get("title", ""),
                    "link": link,
                    "snippet": item.get("snippet", ""),
                }
            )
    return out


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


# ---------------------------------------------------------------------
# LLM company picker (fixes your "$84k" / "Best Tech" issue)
# ---------------------------------------------------------------------
def _choose_companies_from_scratch(queries: List[str]) -> List[str]:
    """
    Uses an LLM to choose REAL companies (big/mid/startups) from resume-driven queries.
    Returns company names only, as JSON.
    """
    payload = {
        "queries": queries,
        "instructions": [
            "Return ONLY valid JSON. No markdown. No extra text.",
            "Return 30 real company names total.",
            "Include a balanced mix: 10 big tech, 10 mid-size, 10 startups.",
            "Must be company names only (not salaries, not article titles, not generic words).",
            "Prefer US-based companies or companies hiring in the US.",
        ],
        "schema": {"companies": ["Company1", "Company2"]},
    }

    resp = _llm_company_picker.invoke([{"role": "user", "content": json.dumps(payload)}])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)

    try:
        data = json.loads(content)
        companies = data.get("companies") if isinstance(data, dict) else []
        companies = [c.strip() for c in companies if isinstance(c, str) and c.strip()]
        companies = companies[:30]
        print(f"[CRAWL] LLM company targets: {companies[:15]} ... (n={len(companies)})")
        return companies
    except Exception:
        print("[CRAWL] Failed to parse LLM companies JSON. Falling back.")
        return ["Google", "Microsoft", "Amazon", "Apple", "Meta", "NVIDIA", "Stripe", "Databricks", "Snowflake", "Notion"]


# ---------------------------------------------------------------------
# Discover careers URLs (ATS-first)
# ---------------------------------------------------------------------
def _discover_careers_urls(companies: List[str], queries: List[str], max_per_company: int = 1) -> List[Dict[str, str]]:
    kw = " ".join([w for w in re.split(r"\s+", " ".join(queries)) if len(w) > 2][:12])

    targets: List[Dict[str, str]] = []
    for c in companies:
        c = (c or "").strip()
        if not c:
            continue

        # Prefer ATS boards that we can crawl reliably
        search_queries = [
            f"{c} jobs lever",
            f"{c} jobs greenhouse",
            f"{c} careers lever",
            f"{c} careers greenhouse",
            f"{c} careers {kw}",
        ]

        picked = 0
        used_domains = set()

        for sq in search_queries:
            try:
                hits = _serper_search(sq, k=8)
            except Exception:
                continue

            # 1) Try ATS URLs first
            chosen_url = None
            for h in hits:
                url = (h.get("link") or "").strip()
                ul = url.lower()
                if "jobs.lever.co/" in ul or "boards.greenhouse.io/" in ul:
                    chosen_url = url
                    break

            # 2) Otherwise take a careers page
            if not chosen_url:
                for h in hits:
                    url = (h.get("link") or "").strip()
                    if any(x in url.lower() for x in ("careers", "jobs", "work-with-us", "join")):
                        chosen_url = url
                        break

            if not chosen_url:
                continue

            d = _domain(chosen_url)
            if d in used_domains:
                continue
            used_domains.add(d)

            targets.append({"company": c, "careers_url": chosen_url})
            picked += 1
            if picked >= max_per_company:
                break

    print(f"[CRAWL] Discovered careers URLs: {len(targets)}")
    return targets


# ---------------------------------------------------------------------
# ATS + fallback crawler
# ---------------------------------------------------------------------
def _fetch_html(url: str, timeout: int = 20) -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _fetch_json(url: str, timeout: int = 20) -> Any:
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _detect_ats(url: str) -> Tuple[str, Optional[str]]:
    u = (url or "").strip().lower()
    if "jobs.lever.co/" in u:
        slug = u.split("jobs.lever.co/", 1)[1].split("/", 1)[0].strip()
        return "lever", slug or None
    if "boards.greenhouse.io/" in u:
        slug = u.split("boards.greenhouse.io/", 1)[1].split("/", 1)[0].strip()
        return "greenhouse", slug or None
    return "unknown", None


def _clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _crawl_lever(slug: str, company: str) -> List[Dict[str, Any]]:
    if not slug:
        return []
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        items = _fetch_json(url, timeout=30) or []
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for it in items:
        title = (it.get("text") or "").strip()
        categories = it.get("categories") or {}
        loc = (categories.get("location") or "").strip()
        desc = _clean_text(it.get("description") or "")
        apply_url = (it.get("hostedUrl") or it.get("applyUrl") or "").strip()

        if not title and not apply_url:
            continue

        job_id = "lever:" + _stable_id_from_text(f"{slug}|{title}|{apply_url}")
        out.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company or slug,
                "location": loc,
                "employment_type": "",
                "publisher": "lever",
                "description": desc,
                "url": apply_url,
            }
        )
    return out


def _crawl_greenhouse(slug: str, company: str) -> List[Dict[str, Any]]:
    if not slug:
        return []
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        data = _fetch_json(url, timeout=30) or {}
    except Exception:
        return []

    items = data.get("jobs") or []
    out: List[Dict[str, Any]] = []
    for it in items:
        title = (it.get("title") or "").strip()
        loc = ((it.get("location") or {}).get("name") or "").strip()
        desc = _clean_text(it.get("content") or "")
        apply_url = (it.get("absolute_url") or "").strip()

        if not title and not apply_url:
            continue

        job_id = "gh:" + _stable_id_from_text(f"{slug}|{title}|{apply_url}")
        out.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company or slug,
                "location": loc,
                "employment_type": "",
                "publisher": "greenhouse",
                "description": desc,
                "url": apply_url,
            }
        )
    return out


def _extract_jobposting_jsonld(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        candidates = []
        if isinstance(data, dict):
            candidates = [data]
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]

        for obj in candidates:
            t = obj.get("@type")
            is_job = (t == "JobPosting") or (isinstance(t, list) and "JobPosting" in t)
            if is_job:
                out.append(obj)

    return out


def _postings_to_clean_jobs(postings: List[Dict[str, Any]], company: str, fallback_url: str) -> List[Dict[str, Any]]:
    out = []
    for p in postings:
        title = str(p.get("title") or "").strip()
        desc = _clean_text(str(p.get("description") or ""))
        url = str(p.get("url") or fallback_url).strip()

        loc = ""
        jl = p.get("jobLocation")
        if isinstance(jl, dict):
            addr = jl.get("address") or {}
            if isinstance(addr, dict):
                loc = str(addr.get("addressLocality") or addr.get("addressRegion") or "")
        elif isinstance(jl, list) and jl and isinstance(jl[0], dict):
            addr = jl[0].get("address") or {}
            if isinstance(addr, dict):
                loc = str(addr.get("addressLocality") or addr.get("addressRegion") or "")

        job_id = "crawl:" + _stable_id_from_text(f"{company}|{title}|{url}")

        out.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": loc,
                "employment_type": "",
                "publisher": "careers_crawl",
                "description": desc,
                "url": url,
            }
        )
    return out


def _crawl_targets_for_jobs(targets: List[Dict[str, str]], follow_links: int = 2) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []

    for t in targets:
        company = (t.get("company") or "").strip()
        start_url = (t.get("careers_url") or "").strip()
        if not start_url:
            continue

        # ATS-first
        ats, slug = _detect_ats(start_url)
        if ats == "lever" and slug:
            jobs.extend(_crawl_lever(slug, company))
            continue
        if ats == "greenhouse" and slug:
            jobs.extend(_crawl_greenhouse(slug, company))
            continue

        # HTML fallback
        try:
            html = _fetch_html(start_url)
        except Exception:
            continue

        postings = _extract_jobposting_jsonld(html)
        if postings:
            jobs.extend(_postings_to_clean_jobs(postings, company, start_url))
            continue

        # Light internal link follow (also ATS-detect on discovered links)
        soup = BeautifulSoup(html, "html.parser")
        base_domain = _domain(start_url)
        links = []

        for a in soup.find_all("a", href=True):
            u = urljoin(start_url, a["href"])
            if _domain(u) != base_domain:
                continue
            if any(x in u.lower() for x in ("jobs", "careers", "positions", "opening", "greenhouse", "lever")):
                links.append(u)

        seen = set()
        followed = 0
        for u in links:
            if u in seen:
                continue
            seen.add(u)

            ats2, slug2 = _detect_ats(u)
            if ats2 == "lever" and slug2:
                jobs.extend(_crawl_lever(slug2, company))
                followed += 1
                if followed >= follow_links:
                    break
                continue
            if ats2 == "greenhouse" and slug2:
                jobs.extend(_crawl_greenhouse(slug2, company))
                followed += 1
                if followed >= follow_links:
                    break
                continue

            try:
                sub = _fetch_html(u)
            except Exception:
                continue

            postings = _extract_jobposting_jsonld(sub)
            if postings:
                jobs.extend(_postings_to_clean_jobs(postings, company, u))

            followed += 1
            if followed >= follow_links:
                break

    print(f"[CRAWL] Extracted jobs via crawl: {len(jobs)}")
    return jobs


# ---------------------------------------------------------------------
# Dedupe + main entrypoint
# ---------------------------------------------------------------------
def _dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for job in jobs:
        jid = job.get("job_id")
        if not jid or jid in seen:
            continue
        seen.add(jid)
        out.append(job)
    return out


def load_and_clean_jobs(
    force_refresh: bool = False,
    queries: List[str] | None = None,
) -> List[Dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if CLEAN_PATH.exists() and not force_refresh:
        try:
            data = json.loads(CLEAN_PATH.read_text(encoding="utf-8"))
            print(f"[load_jobs] Loaded {len(data)} jobs from existing jobs_clean.json")
            return data
        except Exception as e:
            print("[load_jobs] Failed to read existing jobs_clean.json:", e)

    if queries is None or len(queries) == 0:
        queries = [
            "software engineer internship in New York",
            "data science internship in New York",
            "machine learning engineer entry level in New York",
            "backend developer internship remote",
            "ai engineer entry level remote",
        ]
        print("[load_jobs] Using default queries:", queries)
    else:
        print("[load_jobs] Using custom queries from resume:", queries)

    # ----------------------------
    # 1) Fetch API sources (volume)
    # ----------------------------
    raw_jsearch = _fetch_jobs_from_jsearch(queries, pages_per_query=3)
    raw_adzuna = _fetch_jobs_from_adzuna(queries, pages_per_query=3, results_per_page=50)

    raw_combined = {"jsearch": raw_jsearch, "adzuna": raw_adzuna}
    RAW_PATH.write_text(json.dumps(raw_combined, indent=2), encoding="utf-8")
    print(f"[load_jobs] Saved raw jobs to {RAW_PATH}")

    cleaned: List[Dict[str, Any]] = []
    cleaned.extend(_clean_jobs_jsearch(raw_jsearch))
    cleaned.extend(_clean_jobs_adzuna(raw_adzuna))

    # ----------------------------
    # 2) Resume-driven company portals crawl
    # ----------------------------
    if SERPER_API_KEY:
        try:
            companies = _choose_companies_from_scratch(queries)
            targets = _discover_careers_urls(companies, queries, max_per_company=1)
            crawled_jobs = _crawl_targets_for_jobs(targets, follow_links=2)
            cleaned.extend(crawled_jobs)
        except Exception as e:
            print(f"[CRAWL] Skipping crawl layer due to error: {e}")
    else:
        print("[CRAWL] SERPER_API_KEY not set; skipping crawl layer.")

    cleaned = _dedupe_jobs(cleaned)

    CLEAN_PATH.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    print(f"[load_jobs] Saved cleaned jobs to {CLEAN_PATH} ({len(cleaned)} total)")

    return cleaned


if __name__ == "__main__":
    jobs = load_and_clean_jobs(force_refresh=True)
    print(f"[load_jobs] Final count: {len(jobs)} cleaned jobs")
