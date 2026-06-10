from openai import OpenAI
import os

# Uses the same env variables your app uses
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")

if not api_key or not base_url:
    raise RuntimeError("OPENAI_API_KEY or OPENAI_BASE_URL not set")

client = OpenAI(
    api_key=api_key,
    base_url=base_url,  # /v1 will be appended automatically
)

models = client.models.list()

print("Available models for this key + base_url:")
for m in models.data:
    print("-", m.id)
