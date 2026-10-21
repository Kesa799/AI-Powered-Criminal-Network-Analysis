"""Smoke-test every ATLAS GET endpoint and report status codes."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8000"
BADGE = "IND-LE-8402"
PASSWORD = "password123"

session = requests.Session()
r = session.post(
    f"{BASE}/api/auth/login",
    json={"badgeNumber": BADGE, "password": PASSWORD},
    timeout=30,
)
r.raise_for_status()
session.headers.update({"Authorization": "Bearer " + r.json()["token"]})

# Pick a case that actually has evidence.
cases = session.get(f"{BASE}/api/cases", params={"limit": 50}, timeout=60).json()
items = cases.get("items", cases) if isinstance(cases, dict) else cases
case_ids = [c["case_id"] for c in items]
target = next((c for c in case_ids if c.startswith("CASE_0") and c[5:].isdigit()), case_ids[0])
print(f"testing against case {target} ({len(case_ids)} cases in the registry)\n")

evidence = session.get(f"{BASE}/api/evidence", params={"case_id": target, "limit": 50}, timeout=60).json()
ev_items = evidence.get("items", [])
ev_id = ev_items[0]["evidence_id"] if ev_items else ""

CHECKS = [
    ("health", "GET", "/api/health", None),
    ("auth/me", "GET", "/api/auth/me", None),
    ("cases", "GET", "/api/cases?limit=50", None),
    ("case detail", "GET", f"/api/cases/{target}", None),
    ("case insights", "GET", f"/api/cases/{target}/insights", None),
    ("case ai-dossier", "GET", f"/api/cases/{target}/ai-dossier", None),
    ("case findings", "GET", f"/api/cases/{target}/findings", None),
    ("case rankings", "GET", "/api/cases/rankings?limit=10", None),
    ("entities search", "GET", "/api/entities/search?q=a&limit=10", None),
    ("evidence list", "GET", f"/api/evidence?case_id={target}&limit=50", None),
    ("evidence cases", "GET", "/api/evidence/cases", None),
    ("evidence detail", "GET", f"/api/evidence/{ev_id}", None),
    ("evidence mentions", "GET", f"/api/evidence/{ev_id}/results/mentions", None),
    ("evidence sources", "GET", f"/api/evidence/{ev_id}/results/sources", None),
    ("evidence reviews", "GET", f"/api/evidence/{ev_id}/reviews", None),
    ("evidence original", "GET", f"/api/evidence/{ev_id}/original", None),
    ("graph all", "GET", "/api/graph?limit=500&include_isolated=true", None),
    ("graph case", "GET", f"/api/graph?case_id={target}&limit=500", None),
    ("graph status", "GET", "/api/graph/status", None),
    ("graph export cypher", "GET", "/api/graph/export/cypher", None),
    ("graph sync to neo4j", "POST", "/api/graph/sync", None),
    ("boards", "GET", f"/api/boards?case_id={target}", None),
    ("integrity cases", "GET", "/api/v1/integrity/cases", None),
    ("integrity summary", "GET", "/api/v1/integrity/cases/summary", None),
    ("integrity evidence", "GET", f"/api/v1/integrity/evidence?case_id={target}", None),
    ("integrity timeline", "GET", f"/api/v1/integrity/cases/{target}/timeline", None),
    ("integrity certificate", "GET", f"/api/v1/integrity/evidence/{ev_id}/certificate", None),
    ("blockchain ledger", "GET", "/api/v1/blockchain/ledger", None),
    ("blockchain verify chain", "GET", "/api/v1/blockchain/verify-chain", None),
    ("blockchain verify case", "GET", f"/api/v1/blockchain/verify-case/{target}", None),
    ("frontend index", "GET", "/", None),
]

failures = []
for name, method, path, _ in CHECKS:
    t0 = time.time()
    try:
        resp = session.request(method, f"{BASE}{path}", timeout=120)
        code = resp.status_code
        size = len(resp.content)
        detail = ""
        if code >= 400:
            detail = resp.text[:160].replace("\n", " ")
    except Exception as exc:
        code = 0
        size = 0
        detail = str(exc)[:160]
    ms = (time.time() - t0) * 1000
    mark = "ok " if 200 <= code < 300 else "FAIL"
    print(f"  [{mark}] {code:>3}  {name:<24} {size:>8}B  {ms:>7.0f}ms  {detail}")
    if not (200 <= code < 300):
        failures.append((name, code, detail))

print()
if failures:
    print(f"{len(failures)} endpoint(s) failed:")
    for name, code, detail in failures:
        print(f"  {name}: HTTP {code} {detail}")
    sys.exit(1)
print(f"all {len(CHECKS)} endpoints responded successfully")
