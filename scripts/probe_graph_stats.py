"""Summarise the current state of the Neo4j mirror (counts by label and type)."""
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8000"

r = requests.post(
    f"{BASE}/api/auth/login",
    json={"badgeNumber": "IND-LE-8402", "password": "password123"},
    timeout=30,
)
r.raise_for_status()
h = {"Authorization": "Bearer " + r.json()["token"]}

QUERIES = [
    ("nodes by label", "MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC"),
    ("relationships by type", "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC"),
    ("distinct cases", "MATCH (n:Entity) UNWIND coalesce(n.case_ids,[]) AS c RETURN c, count(*) AS n ORDER BY c"),
    ("total nodes", "MATCH (n) RETURN count(n) AS nodes"),
    ("total rels", "MATCH ()-[r]->() RETURN count(r) AS rels"),
]

for title, q in QUERIES:
    res = requests.post(f"{BASE}/api/graph/cypher", json={"query": q}, headers=h, timeout=180)
    res.raise_for_status()
    print(f"--- {title} ---")
    for rec in res.json().get("records", []):
        print("   ", rec)
    print()
