"""Verify that the knowledge graph can be restored from the Neo4j mirror."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "member4"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.config import settings
from member4.graph_engine import KnowledgeGraphEngine
from member4.neo4j_client import Neo4jClient

client = Neo4jClient(
    uri=settings.neo4j_uri,
    user=settings.neo4j_user,
    password=settings.neo4j_password,
    database=settings.neo4j_database,
)
assert client.connect(), "could not connect to Neo4j"

engine = KnowledgeGraphEngine(neo4j_client=client)
stats = engine.load_from_neo4j()
print("restored:", stats)

data = engine.get_graph_data(filter_isolated=False)
print("nodes:", len(data.get("nodes", [])), "edges:", len(data.get("edges", [])))

# Every restored edge must point at a node that exists.
ids = {n["id"] for n in data.get("nodes", [])}
dangling = [e for e in data.get("edges", []) if e["from"] not in ids or e["to"] not in ids]
print("dangling edges:", len(dangling))

by_label = {}
for n in data.get("nodes", []):
    for lbl in n.get("labels", []):
        by_label[lbl] = by_label.get(lbl, 0) + 1
print("labels:", by_label)

by_type = {}
for e in data.get("edges", []):
    t = e.get("label")
    by_type[t] = by_type.get(t, 0) + 1
print("edge types:", by_type)

cases = {}
for n in data.get("nodes", []):
    for c in n.get("properties", {}).get("case_ids", []):
        cases[c] = cases.get(c, 0) + 1
print("cases:", dict(sorted(cases.items())))

assert not dangling, "restored graph has edges pointing at missing nodes"
print("OK")
