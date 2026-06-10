import os
import requests
from typing import List, Dict, Any

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_URL = "https://google.serper.dev/search"


def serper_search(query: str, k: int = 10) -> List[Dict[str, Any]]:
    """
    Web search via Serper.dev (Google Search API).
    Returns a list of dicts: {title, link, snippet}.
    """
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY is not set in .env")

    payload = {"q": query, "num": k}
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }

    resp = requests.post(SERPER_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in (data.get("organic") or []):
        link = item.get("link")
        if not link:
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "link": link,
                "snippet": item.get("snippet", ""),
            }
        )
    return results
