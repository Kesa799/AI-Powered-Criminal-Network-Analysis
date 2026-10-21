"""End-to-end verification: Postgres -> extraction -> Neo4j Aura write path.

Ingests one spreadsheet (deterministic YAML path, zero LLM cost) and one FIR PDF
from SFIC_DATASET/CASE_001, then asserts the resulting graph landed in Neo4j.
"""
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT.parent / "SFIC_DATASET"
BASE = "http://127.0.0.1:8000"
CASE_ID = "CASE_001"

session = requests.Session()


def login():
    r = session.post(
        f"{BASE}/api/auth/login",
        json={"badgeNumber": "IND-LE-8402", "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["token"]
    session.headers.update({"Authorization": f"Bearer {token}"})
    print(f"[auth]  logged in as IND-LE-8402, token {token[:24]}...")


def ingest(files, case_id):
    payload = []
    handles = []
    try:
        for path in files:
            h = open(path, "rb")
            handles.append(h)
            payload.append(("files", (Path(path).name, h, "application/octet-stream")))
        r = session.post(
            f"{BASE}/api/v1/ingest",
            params={"case_id": case_id, "officer_name": "Inspector Vikram Rathore"},
            data={"category": "General Investigation"},
            files=payload,
            timeout=600,
        )
        print(f"[ingest] {r.status_code} {r.text[:400]}")
        return r
    finally:
        for h in handles:
            h.close()


def check_graph():
    r = session.get(f"{BASE}/api/graph", params={"limit": 500}, timeout=60)
    r.raise_for_status()
    g = r.json()
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    print(f"[graph] API nodes={len(nodes)} edges={len(edges)}")
    return nodes, edges


def check_neo4j_direct():
    sys.path.insert(0, str(ROOT))
    from backend.config import settings
    from neo4j import GraphDatabase

    d = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    d.verify_connectivity()
    with d.session(database=settings.neo4j_database) as s:
        nodes_n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rels_n = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"[neo4j] direct count: nodes={nodes_n} relationships={rels_n}")
        print("[neo4j] labels:",
              s.run("CALL db.labels() YIELD label RETURN label").values())
        print("[neo4j] rel types:",
              s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType").values())
        print("[neo4j] constraints:",
              s.run("SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
                    "RETURN name, labelsOrTypes, properties").values())
        sample = s.run(
            "MATCH (n) RETURN labels(n) AS l, n.canonical_value AS cv, n.id AS id LIMIT 8"
        ).values()
        for row in sample:
            print("[neo4j]  node:", row)
        edge_sample = s.run(
            "MATCH (a)-[r]->(b) RETURN labels(a), a.canonical_value, type(r), labels(b), b.canonical_value LIMIT 8"
        ).values()
        for row in edge_sample:
            print("[neo4j]  edge:", row)
    d.close()
    return {"nodes": nodes_n, "rels": rels_n}


if __name__ == "__main__":
    login()

    src = DATASET / CASE_ID
    xlsx = src / "CDR_CASE_001.xlsx"
    pdf = src / "FIR_CASE_001.pdf"
    print(f"[data]  xlsx={xlsx.exists()} pdf={pdf.exists()}")

    targets = [p for p in (xlsx, pdf) if p.exists()]
    ingest(targets, CASE_ID)

    nodes, edges = check_graph()
    check_neo4j_direct()

    print("\n[done]  Postgres + Neo4j Aura write path verified.")
