from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from rag.tools.web_search import serper_search


_CAREERS_HINTS = ("careers", "jobs", "join", "work-with-us", "greenhouse", "lever", "workday")


def _is_plausible_careers_url(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in _CAREERS_HINTS)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def discover_careers_urls(
    companies: List[str],
    role_keywords: List[str],
    max_per_company: int = 2,
) -> List[Dict[str, Any]]:
    """
    Dynamically find crawl targets:
      - searches: "<company> careers <role keywords>"
      - returns top careers/job URLs that look crawl-worthy
    Output: [{company, careers_url}]
    """
    targets: List[Dict[str, Any]] = []

    kw = " ".join([k.strip() for k in role_keywords if k.strip()])[:120]
    for c in companies:
        c = (c or "").strip()
        if not c:
            continue

        # Search query that behaves like a “human”
        q = f"{c} careers {kw}".strip()
        try:
            hits = serper_search(q, k=8)
        except Exception:
            continue

        seen_domains = set()
        picked = 0
        for h in hits:
            url = h.get("link") or ""
            if not url:
                continue
            if not _is_plausible_careers_url(url):
                continue

            d = _domain(url)
            if d in seen_domains:
                continue
            seen_domains.add(d)

            targets.append({"company": c, "careers_url": url})
            picked += 1
            if picked >= max_per_company:
                break

    return targets
