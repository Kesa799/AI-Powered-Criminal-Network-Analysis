"""Inspect the shape of the Neo4j mirror (node labels, properties, case_ids)."""
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
    "MATCH (n:Entity) RETURN labels(n) AS l, keys(n) AS k LIMIT 3",
    "MATCH (n:Entity) RETURN n.id AS id, n.case_ids AS case_ids, n.case_id AS case_id LIMIT 8",
    "MATCH (n:Entity) WHERE any(c IN coalesce(n.case_ids, []) WHERE c STARTS WITH 'CASE_TEST' OR c IN ['CASE_0010','CASE_NEW_001','CASE_IMG_TEST','CASE_VERIFY_999']) RETURN count(n) AS nodes_touching_test_cases",
    "MATCH (n:Entity) WHERE all(c IN coalesce(n.case_ids, []) WHERE c STARTS WITH 'CASE_TEST' OR c IN ['CASE_0010','CASE_NEW_001','CASE_IMG_TEST','CASE_VERIFY_999']) AND size(coalesce(n.case_ids,[])) > 0 RETURN count(n) AS nodes_only_test_cases",
]

for q in QUERIES:
    res = requests.post(f"{BASE}/api/graph/cypher", json={"query": q}, headers=h, timeout=120)
    print(q[:100])
    print("   ", res.text[:900])
    print()
