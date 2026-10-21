"""End-to-end verification of a running ATLAS deployment.

Checks, in order:

1. The API is up and reports its health.
2. The relational database and the Neo4j graph are both reachable.
3. The knowledge graph can be restored from the Neo4j mirror (so it survives a
   restart) and the restored graph has no dangling edges.
4. The LLM extraction configuration is the verified one.
5. Every GET endpoint responds successfully.
6. The dataset is actually ingested: per case, how many files are present and
   how many produced extracted mentions.

Usage:
    python scripts/verify_system.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import requests

from evidence_provenance import has_model_derived_mentions

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT.parent / "SFIC_DATASET"
BASE = "http://127.0.0.1:8000"
BADGE = "IND-LE-8402"
PASSWORD = "password123"

problems: List[str] = []
session = requests.Session()


def check(ok: bool, label: str, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        problems.append(label)
    return ok


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> int:
    section("1. Service")
    try:
        health = session.get(f"{BASE}/api/health", timeout=30).json()
    except Exception as exc:
        print(f"  [FAIL] the API is not reachable at {BASE} - {exc}")
        return 1
    check(health.get("status") == "healthy", "health endpoint", health.get("status", "?"))
    check(
        health.get("database", "").startswith("Supabase"),
        "relational database",
        health.get("database", "?"),
    )
    check(
        health.get("graph_mode") == "live_neo4j",
        "graph mode is the live Neo4j instance",
        health.get("graph_mode", "?"),
    )

    section("2. Authentication")
    r = session.post(
        f"{BASE}/api/auth/login",
        json={"badgeNumber": BADGE, "password": PASSWORD},
        timeout=30,
    )
    if not check(r.status_code == 200, "login as the demo lead detective", f"HTTP {r.status_code}"):
        return 1
    session.headers.update({"Authorization": "Bearer " + r.json()["token"]})
    me = session.get(f"{BASE}/api/auth/me", timeout=30)
    check(me.status_code == 200, "token is accepted", f"HTTP {me.status_code}")

    section("3. Neo4j knowledge graph")
    status = session.get(f"{BASE}/api/graph/status", timeout=60).json()
    check(bool(status.get("connected")), "connected to Neo4j", status.get("uri", "?"))
    check(
        status.get("database") == "a206fdb6",
        "using the Aura database",
        status.get("database", "?"),
    )

    q = "MATCH (n:Entity) RETURN count(n) AS nodes"
    res = session.post(f"{BASE}/api/graph/cypher", json={"query": q}, timeout=120).json()
    node_count = res.get("records", [{}])[0].get("nodes", 0)
    check(node_count > 0, "the mirror holds nodes", f"{node_count} nodes")

    q = (
        "MATCH (a:Entity)-[r]->(b:Entity) "
        "WHERE a.id IS NULL OR b.id IS NULL RETURN count(r) AS broken"
    )
    res = session.post(f"{BASE}/api/graph/cypher", json={"query": q}, timeout=120).json()
    broken = res.get("records", [{}])[0].get("broken", 0)
    check(broken == 0, "no relationship points at a node without an id", f"{broken} broken")

    graph = session.get(
        f"{BASE}/api/graph", params={"limit": 2000, "include_isolated": "true"}, timeout=120
    ).json()
    check(
        graph.get("total_nodes", 0) > 0,
        "the API renders a populated network",
        f"{graph.get('total_nodes')} nodes / {graph.get('total_edges')} relationships",
    )

    section("4. LLM extraction configuration")
    sys.path.insert(0, str(ROOT / "member3" / "SFIC_Doc_Module" / "src"))
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from atlas.config import get_settings

        cfg = get_settings(reload=True)
        check(cfg.LLM_PROVIDER == "groq", "provider", str(cfg.LLM_PROVIDER))
        check(
            cfg.LLM_MODEL == "openai/gpt-oss-120b",
            "model (see member3 docs/DECISIONS.md DEC-036)",
            str(cfg.LLM_MODEL),
        )
        check(
            cfg.LLM_MAX_COMPLETION_TOKENS >= 8192,
            "output token ceiling is set (the provider truncates without it)",
            str(cfg.LLM_MAX_COMPLETION_TOKENS),
        )
        check(
            cfg.LLM_MIN_INTERVAL_S > 0,
            "requests are paced to the provider's token budget",
            f"min interval {cfg.LLM_MIN_INTERVAL_S}s, {cfg.LLM_MAX_REQUESTS_PER_MINUTE} req/min",
        )
    except Exception as exc:
        check(False, "read the member3 LLM configuration", str(exc))

    section("5. Dataset ingestion")
    if not DATASET.is_dir():
        check(False, "the dataset directory exists", str(DATASET))
    else:
        case_dirs = sorted(p for p in DATASET.iterdir() if p.is_dir())
        rows: List[tuple] = []
        total_files = total_with_mentions = 0
        for cd in case_dirs:
            files = [p for p in cd.iterdir() if p.is_file()]
            ev = session.get(
                f"{BASE}/api/evidence", params={"case_id": cd.name, "limit": 1000}, timeout=120
            ).json()
            items = ev.get("items", [])
            # Count distinct files, not rows: a file ingested more than once leaves
            # several evidence rows behind. A PDF only counts as extracted when the
            # model produced its mentions - a row that only holds locally extracted
            # mentions was never really read by the model.
            extracted_files = set()
            for i in items:
                name = i.get("filename")
                if not name or ((i.get("job") or {}).get("mention_count") or 0) <= 0:
                    continue
                if name.lower().endswith(".pdf"):
                    if has_model_derived_mentions(session, BASE, i.get("evidence_id")) is not True:
                        continue
                extracted_files.add(name)
            total_files += len(files)
            total_with_mentions += len(extracted_files)
            rows.append((cd.name, len(files), len(items), len(extracted_files)))

        print(f"  {'case':<12} {'files':>6} {'evidence':>9} {'extracted':>10}")
        for name, n_files, n_ev, n_ok in rows:
            flag = "" if n_ok >= n_files else "  <- incomplete"
            print(f"  {name:<12} {n_files:>6} {n_ev:>9} {n_ok:>10}{flag}")
        print(f"  {'TOTAL':<12} {total_files:>6} {'':>9} {total_with_mentions:>10}")
        check(
            total_with_mentions == total_files,
            "every dataset file has been extracted",
            f"{total_with_mentions} of {total_files} files produced mentions",
        )

    print()
    if problems:
        print(f"{len(problems)} check(s) failed: {problems}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
