"""Clean up verification artifacts left in ATLAS by the test scripts.

Two kinds of leftovers are removed:

1. **Throwaway cases.** Scripts under ``scripts/`` upload evidence into cases
   such as ``CASE_TEST_007`` or ``CASE_VERIFY_999``. Those are test artifacts,
   not investigations, and they clutter the case registry, the graph and the
   cross-case link reports.
2. **Duplicate evidence.** Every upload creates a fresh evidence row, so a file
   that was ingested more than once leaves several rows (and several copies of
   its mentions) behind. Only the newest row per file name is kept - that is
   the one produced by the current pipeline, with live LLM extraction.

The Neo4j mirror is cleaned in the same pass: nodes that only ever belonged to
a throwaway case are deleted, and shared nodes have the throwaway case ids
removed from their ``case_ids`` property.

Usage:
    python scripts/cleanup_test_artifacts.py --dry-run
    python scripts/cleanup_test_artifacts.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests

from evidence_provenance import has_model_derived_mentions

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT.parent / "SFIC_DATASET"
BASE = "http://127.0.0.1:8000"
BADGE = "IND-LE-8402"
PASSWORD = "password123"

NEO4J_URI = ""
NEO4J_USER = ""
NEO4J_PASSWORD = ""
NEO4J_DATABASE = "neo4j"

session = requests.Session()


def load_neo4j_settings() -> None:
    """Read the Neo4j connection settings from the project's .env file."""
    global NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    values: Dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    NEO4J_URI = values.get("NEO4J_URI", "")
    NEO4J_USER = values.get("NEO4J_USERNAME") or values.get("NEO4J_USER", "")
    NEO4J_PASSWORD = values.get("NEO4J_PASSWORD", "")
    NEO4J_DATABASE = values.get("NEO4J_DATABASE", "neo4j")


def neo4j_driver():
    if not NEO4J_URI:
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None
    # The "+s" URI schemes carry their own TLS configuration, and the driver
    # rejects an explicit `encrypted`/`trusted_certificates` for them.
    kwargs = {}
    if not NEO4J_URI.startswith(("neo4j+s", "bolt+s")):
        kwargs["encrypted"] = True
    return GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), **kwargs
    )


def login() -> None:
    r = session.post(
        f"{BASE}/api/auth/login",
        json={"badgeNumber": BADGE, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    session.headers.update({"Authorization": "Bearer " + r.json()["token"]})
    print("[auth] ok", flush=True)


def real_case_ids() -> set[str]:
    """Case ids that the dataset actually defines."""
    if not DATASET.is_dir():
        return set()
    return {p.name.upper() for p in DATASET.iterdir() if p.is_dir()}


def cypher(query: str, params: Dict | None = None) -> dict:
    """Run a read query through the API's cypher endpoint."""
    r = session.post(
        f"{BASE}/api/graph/cypher",
        json={"query": query, "params": params or {}},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()


def list_cases() -> List[dict]:
    r = session.get(f"{BASE}/api/cases", params={"limit": 500}, timeout=120)
    r.raise_for_status()
    payload = r.json()
    return payload.get("items", payload) if isinstance(payload, dict) else payload


def evidence_for(case_id: str) -> List[dict]:
    r = session.get(f"{BASE}/api/evidence", params={"case_id": case_id, "limit": 1000}, timeout=120)
    r.raise_for_status()
    return r.json().get("items", [])


def delete_evidence(evidence_id: str) -> bool:
    try:
        r = session.delete(f"{BASE}/api/evidence/{evidence_id}", timeout=120)
        return r.status_code < 400
    except Exception as exc:
        print(f"    ! failed to delete {evidence_id}: {exc}", flush=True)
        return False


def delete_case(case_id: str) -> bool:
    try:
        r = session.delete(f"{BASE}/api/cases/{case_id}", params={"confirm": "true"}, timeout=300)
        return r.status_code < 400
    except Exception as exc:
        print(f"    ! failed to delete case {case_id}: {exc}", flush=True)
        return False


def clean_neo4j(test_cases: List[str]) -> None:
    """Remove throwaway cases from the Neo4j mirror.

    The `/api/graph/cypher` endpoint runs in a read transaction, so the writes
    are issued straight through the driver with the same credentials the
    backend uses.
    """
    if not test_cases:
        return
    params = {"cases": test_cases}

    driver = neo4j_driver()
    if driver is None:
        print("  neo4j: skipped (no driver available)", flush=True)
        return

    def run(query: str, p: Dict | None = None) -> int:
        with driver.session(database=NEO4J_DATABASE) as session:
            res = session.run(query, p or {})
            records = list(res)
            if not records:
                return 0
            first = records[0]
            values = list(first.values())
            return int(values[0]) if values and isinstance(values[0], int) else 0

    try:
        removed = run(
            """
            MATCH (n:Entity)
            WHERE size(coalesce(n.case_ids, [])) > 0
              AND all(c IN n.case_ids WHERE c IN $cases)
            RETURN count(n) AS nodes
            """,
            params,
        )
        run(
            """
            MATCH (n:Entity)
            WHERE size(coalesce(n.case_ids, [])) > 0
              AND all(c IN n.case_ids WHERE c IN $cases)
            DETACH DELETE n
            """,
            params,
        )
        print(f"  neo4j: removed {removed} test-only node(s)", flush=True)

        stripped = run(
            """
            MATCH (n:Entity)
            WHERE any(c IN coalesce(n.case_ids, []) WHERE c IN $cases)
            SET n.case_ids = [c IN coalesce(n.case_ids, []) WHERE NOT c IN $cases]
            SET n.case_id = reduce(acc = '', c IN n.case_ids |
                CASE WHEN acc = '' THEN c ELSE acc + ', ' + c END)
            SET n.cross_case = size(n.case_ids) > 1
            RETURN count(*) AS updated
            """,
            params,
        )
        print(f"  neo4j: {stripped} shared node(s) had the test ids stripped", flush=True)

        # Relationships carry a single `case_id` string rather than a list.
        edges = run(
            """
            MATCH ()-[r]->()
            WHERE r.case_id IN $cases
            RETURN count(r) AS edges
            """,
            params,
        )
        run(
            """
            MATCH ()-[r]->()
            WHERE r.case_id IN $cases
            DELETE r
            """,
            params,
        )
        print(f"  neo4j: removed {edges} test-only relationship(s)", flush=True)

        broken = run(
            """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE a.id IS NULL OR b.id IS NULL
            RETURN count(r) AS broken
            """
        )
        print(f"  neo4j: {broken} relationship(s) point at a node without an id", flush=True)

        left = run(
            """
            MATCH (n:Entity)
            WHERE any(c IN coalesce(n.case_ids, []) WHERE c IN $cases)
            RETURN count(n) AS left
            """,
            params,
        )
        print(f"  neo4j: {left} node(s) still reference a test case", flush=True)
    finally:
        driver.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove ATLAS test artifacts and duplicate evidence.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-duplicates", action="store_true")
    args = ap.parse_args()

    load_neo4j_settings()
    login()
    keep = real_case_ids()
    if not keep:
        print("[fatal] dataset directory not found, cannot tell real cases from test cases", file=sys.stderr)
        return 2

    cases = list_cases()
    by_id = {str(c.get("case_id")): c for c in cases}
    test_cases = sorted(cid for cid in by_id if cid.upper() not in keep)

    print(f"[cases] {len(cases)} total, {len(test_cases)} test artifact(s): {test_cases}", flush=True)

    if args.dry_run:
        for cid in test_cases:
            print(f"  would delete case {cid} ({by_id[cid].get('evidence_count')} evidence)")
        for cid in sorted(keep):
            items = evidence_for(cid)
            names: Dict[str, List[dict]] = {}
            for it in items:
                names.setdefault(str(it.get("filename")), []).append(it)
            dups = {n: v for n, v in names.items() if len(v) > 1}
            if dups:
                print(f"  {cid}: {sum(len(v) - 1 for v in dups.values())} duplicate evidence row(s)")
        return 0

    for cid in test_cases:
        print(f"[case] deleting {cid}", flush=True)
        if delete_case(cid):
            print(f"  deleted {cid}", flush=True)
        else:
            print(f"  ! could not delete {cid}", flush=True)

    if not args.keep_duplicates:
        for cid in sorted(keep):
            items = evidence_for(cid)
            names: Dict[str, List[dict]] = {}
            for it in items:
                names.setdefault(str(it.get("filename")), []).append(it)
            removed = 0
            for name, rows in names.items():
                if len(rows) < 2:
                    continue
                # Keep the newest row that the model actually extracted. A row
                # whose mentions only came from the local regex/NER extractor is
                # not a model extraction, so it is never the keeper.
                rows.sort(key=lambda r: str(r.get("uploaded_at") or ""))
                with_mentions = [
                    r for r in rows if ((r.get("job") or {}).get("mention_count") or 0) > 0
                ]
                model_rows = [
                    r
                    for r in with_mentions
                    if not str(name).lower().endswith(".pdf")
                    or has_model_derived_mentions(session, BASE, r.get("evidence_id")) is True
                ]
                keeper = (model_rows or with_mentions or rows)[-1]
                for row in rows:
                    if row is keeper:
                        continue
                    if delete_evidence(row["evidence_id"]):
                        removed += 1
            if removed:
                print(f"[dupes] {cid}: removed {removed} duplicate evidence row(s)", flush=True)

    clean_neo4j(test_cases)

    remaining = {str(c.get("case_id")) for c in list_cases()}
    print(f"[done] {len(remaining)} case(s) remain: {sorted(remaining)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
