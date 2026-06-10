import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("THEIRSTACK_API_KEY")
if not API_KEY:
    raise RuntimeError("THEIRSTACK_API_KEY not set in .env")

url = "https://api.theirstack.com/v1/jobs/search"

body = {
    "page": 0,
    "limit": 10,
    "posted_at_max_age_days": 15,
    "blur_company_data": False,
    "order_by": [
        {
            "desc": True,
            "field": "date_posted"
        }
    ],
    "job_country_code_or": ["US"],
    "include_total_results": False,
}

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}

resp = requests.post(url, headers=headers, json=body, timeout=30)
print("Status:", resp.status_code)
print("Raw text (first 500 chars):")
print(resp.text[:500])

try:
    data = resp.json()
    # This depends on their exact response schema; often "results" or "data"
    items = data.get("results") or data.get("data") or (data if isinstance(data, list) else [])
    print(f"\nParsed {len(items)} jobs")
    if items:
        print("\nFirst job keys:", list(items[0].keys()))
except Exception as e:
    print("JSON parse error:", e)
