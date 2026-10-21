"""Print Groq's current rate-limit envelope with a minimal (near-free) request."""
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent

key = ""
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("GROQ_API_KEY="):
        key = line.split("=", 1)[1].strip()

model = "openai/gpt-oss-120b"
r = requests.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json={
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_completion_tokens": 4,
    },
    timeout=60,
)
print("status:", r.status_code)
if r.status_code >= 400:
    print("body:", r.text[:400])
for k, v in sorted(r.headers.items()):
    if "ratelimit" in k.lower() or "retry" in k.lower():
        print(f"  {k}: {v}")
