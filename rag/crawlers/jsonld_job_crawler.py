from __future__ import annotations

import hashlib
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ---------------------------
# Helpers
# ---------------------------

def _stable_id(*parts: str) -> str:
    s = "|".join([p.strip().lower() for p in parts if p])
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:20]


def _clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _normalize_url(url: str) -> str:
    # drop fragments, keep query
    try:
        p = urlparse(url)
        return p._replace(fragment="").geturl()
    except Exception:
        return url


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


# ---------------------------
# ATS detection
# ---------------------------

def _detect_ats(url: str) -> Tuple[str, Optional[str]]:
    """
    Return (ats_name, slug) when possible.
    ats_name in: lever, greenhouse, unknown
    """
    u = (url or "").strip()
    ul = u.lower()

    # Lever: https://jobs.lever.co/<slug>/...
    if "jobs.lever.co/" in ul:
        slug = ul.split("jobs.lever.co/", 1)[1].split("/", 1)[0].strip()
        return "lever", slug or None

    # Greenhouse: https://boards.greenhouse.io/<slug>/...
    if "boards.greenhouse.io/" in ul:
        slug = ul.split("boards.greenhouse.io/", 1)[1].split("/", 1)[0].strip()
        return "greenhouse", slug or None

    return "unknown", None


# ---------------------------
# ATS crawlers
# ---------------------------

def _crawl_lever(slug: str, company: str) -> List[Dict[str, Any]]:
    """
    Lever public postings endpoint:
      https://api.lever.co/v0/postings/<slug>?mode=json
    """
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

        # Lever descriptions are often HTML
        desc = _clean_text(it.get("description") or "")

        apply_url = (it.get("hostedUrl") or it.get("applyUrl") or "").strip()
        if not title and not apply_url:
            continue

        job_id = "lever:" + _stable_id(slug, title, apply_url)

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
    """
    Greenhouse board endpoint:
      https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
    """
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

        # Greenhouse "content" is HTML
        desc = _clean_text(it.get("content") or "")

        apply_url = (it.get("absolute_url") or "").strip()
        if not title and not apply_url:
            continue

        job_id = "gh:" + _stable_id(slug, title, apply_url)

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


# ---------------------------
# JSON-LD fallback crawler
# ---------------------------

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

        candidates: List[Dict[str, Any]] = []
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


def _jsonld_to_jobs(postings: List[Dict[str, Any]], company: str, fallback_url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in postings:
        title = str(p.get("title") or "").strip()
        desc = _clean_text(str(p.get("description") or ""))
        url = str(p.get("url") or fallback_url).strip()

        loc = ""
        jl = p.get("jobLocation")
        if isinstance(jl, dict):
            addr = jl.get("address") or {}
            if isinstance(addr, dict):
                loc = str(addr.get("addressLocality") or addr.get("addressRegion") or "").strip()
        elif isinstance(jl, list) and jl and isinstance(jl[0], dict):
            addr = jl[0].get("address") or {}
            if isinstance(addr, dict):
                loc = str(addr.get("addressLocality") or addr.get("addressRegion") or "").strip()

        job_id = "crawl:" + _stable_id(company, title, url)
        out.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company or "unknown",
                "location": loc,
                "employment_type": "",
                "publisher": "careers_crawl",
                "description": desc,
                "url": url,
            }
        )
    return out


def _light_follow_links(start_url: str, html: str, max_pages: int = 3) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_domain = _domain(start_url)

    # collect candidate internal links
    candidates: List[str] = []
    for a in soup.find_all("a", href=True):
        u = urljoin(start_url, a["href"])
        u = _normalize_url(u)
        if _domain(u) != base_domain:
            continue
        if any(k in u.lower() for k in ("jobs", "careers", "positions", "openings", "opening", "greenhouse", "lever")):
            candidates.append(u)

    # dedupe preserve order
    seen = set()
    out = []
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max_pages:
            break
    return out


# ---------------------------
# Public entry point
# ---------------------------

def crawl_careers_targets(
    targets: List[Dict[str, Any]],
    max_pages: int = 3,
) -> List[Dict[str, Any]]:
    """
    Input: [{company, careers_url}]
    Output: list of cleaned job dicts (your schema)

    Strategy:
      1) If URL is Lever/Greenhouse -> use ATS JSON endpoint (reliable)
      2) Else try JSON-LD on page
      3) Else lightly follow a few internal links and try JSON-LD there
    """
    jobs: List[Dict[str, Any]] = []

    for t in targets:
        company = (t.get("company") or "").strip()
        start_url = (t.get("careers_url") or "").strip()
        if not start_url:
            continue

        # 1) ATS-first
        ats, slug = _detect_ats(start_url)
        if ats == "lever" and slug:
            ats_jobs = _crawl_lever(slug, company)
            if ats_jobs:
                jobs.extend(ats_jobs)
            continue

        if ats == "greenhouse" and slug:
            ats_jobs = _crawl_greenhouse(slug, company)
            if ats_jobs:
                jobs.extend(ats_jobs)
            continue

        # 2) HTML JSON-LD fallback
        try:
            html = _fetch_html(start_url)
        except Exception:
            continue

        postings = _extract_jobposting_jsonld(html)
        if postings:
            jobs.extend(_jsonld_to_jobs(postings, company, start_url))
            continue

        # 3) Link follow for a few internal pages
        links = _light_follow_links(start_url, html, max_pages=max_pages)
        for u in links:
            # ATS detection on followed links too
            ats2, slug2 = _detect_ats(u)
            if ats2 == "lever" and slug2:
                jobs.extend(_crawl_lever(slug2, company))
                continue
            if ats2 == "greenhouse" and slug2:
                jobs.extend(_crawl_greenhouse(slug2, company))
                continue

            try:
                sub_html = _fetch_html(u)
            except Exception:
                continue
            postings = _extract_jobposting_jsonld(sub_html)
            if postings:
                jobs.extend(_jsonld_to_jobs(postings, company, u))

    # Final dedupe by job_id
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for j in jobs:
        jid = j.get("job_id")
        if not jid or jid in seen:
            continue
        seen.add(jid)
        deduped.append(j)

    return deduped
