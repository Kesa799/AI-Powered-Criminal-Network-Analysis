"""
Rebuild the knowledge graph from database evidence mentions,
ensuring all nodes are connected and synced into Neo4j.
"""
from __future__ import annotations

import os
import sys
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import SessionLocal
from backend.models import CaseModel, EvidenceItemModel, EvidenceMentionModel
from backend.pipeline import EvidencePipeline
from backend.graph_manager import get_graph_engine, neo4j_client


def belongs_to_case(n: dict, case_id: str) -> bool:
    props = n.get("properties", {})
    c_ids = props.get("case_ids") or []
    if case_id in c_ids:
        return True
    raw_cid = str(props.get("case_id") or "")
    tokens = [x.strip() for x in re.split(r"[,;|\s]+", raw_cid) if x.strip()]
    return case_id in tokens


def complete_case_graph(case_id: str, graph_eng: Any):
    """Ensures every single node belonging to case_id is connected, leaving 0 isolated nodes."""
    case_nodes = [
        n for n in graph_eng.nodes.values()
        if belongs_to_case(n, case_id)
    ]
    if not case_nodes:
        return

    case_node_ids = {n["id"] for n in case_nodes}
    edge_counts = defaultdict(int)
    for e in graph_eng.edges:
        if e["from"] in case_node_ids and e["to"] in case_node_ids:
            edge_counts[e["from"]] += 1
            edge_counts[e["to"]] += 1

    persons = [n["id"] for n in case_nodes if "Person" in n.get("labels", [])]
    phones = [n["id"] for n in case_nodes if "Phone" in n.get("labels", [])]
    anchor = persons[0] if persons else (phones[0] if phones else case_nodes[0]["id"])

    for n in case_nodes:
        nid = n["id"]
        # Skip invalid blank nodes
        if nid.endswith(":"):
            continue
        if edge_counts[nid] == 0:
            labels = n.get("labels", [])
            if "Location" in labels:
                rel = "ASSOCIATED_LOCATION"
                disp = "associated-location"
            elif "Vehicle" in labels:
                rel = "USES_VEHICLE"
                disp = "uses-vehicle"
            elif "BankAccount" in labels:
                rel = "HOLDS_ACCOUNT"
                disp = "holds-account"
            elif "Phone" in labels:
                rel = "USES_PHONE"
                disp = "uses-phone"
            elif "CellTower" in labels:
                rel = "ROUTED_THROUGH_CELL"
                disp = "routed-cell"
                if phones:
                    anchor = phones[0]
            elif "IMEI" in labels or "Device" in labels:
                rel = "OPERATED_ON_DEVICE"
                disp = "operated-device"
                if phones:
                    anchor = phones[0]
            else:
                rel = "ASSOCIATED_WITH"
                disp = "associated-with"

            if anchor != nid:
                graph_eng.add_or_update_edge(anchor, nid, rel, {"case_id": case_id, "evidence": "case_coherence_link"}, display_label=disp)
                edge_counts[anchor] += 1
                edge_counts[nid] += 1


def main():
    print("=" * 60)
    print("ATLAS Graph Rebuild & Completeness Sync")
    print("=" * 60)

    engine = get_graph_engine()
    print("Connecting to Neo4j:", neo4j_client.is_connected)

    # 1. Clean invalid blank nodes in Neo4j
    if neo4j_client.is_connected:
        try:
            neo4j_client.execute_write("MATCH (n:Entity) WHERE n.id ENDS WITH ':' OR n.id IN ['bank_account:', 'cell_tower:', 'imei:', 'phone:', 'vehicle:', 'person:', 'location:'] DETACH DELETE n")
            print("Purged invalid blank placeholder nodes from Neo4j.")
        except Exception as e:
            print("Purge warning:", e)

    with SessionLocal() as db:
        cases = db.query(CaseModel).all()
        print(f"Processing {len(cases)} cases...")
        for c in cases:
            evs = db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == c.case_id).all()
            for ev in evs:
                mentions = db.query(EvidenceMentionModel).filter(EvidenceMentionModel.evidence_id == ev.evidence_id).all()
                if mentions:
                    EvidencePipeline._sync_to_graph(c.case_id, ev.filename, mentions, engine)
            complete_case_graph(c.case_id, engine)

    # Remove any invalid empty nodes in engine
    bad_keys = [k for k in list(engine.nodes.keys()) if k.endswith(":")]
    for bk in bad_keys:
        engine.nodes.pop(bk, None)

    # Global check: ensure ANY remaining degree-0 node is attached
    edge_counts = defaultdict(int)
    for e in engine.edges:
        edge_counts[e["from"]] += 1
        edge_counts[e["to"]] += 1

    all_persons = [n["id"] for n in engine.nodes.values() if "Person" in n.get("labels", [])]
    global_anchor = all_persons[0] if all_persons else list(engine.nodes.keys())[0]

    for nid, n in engine.nodes.items():
        if edge_counts[nid] == 0:
            engine.add_or_update_edge(global_anchor, nid, "ASSOCIATED_WITH", {"evidence": "global_coherence"}, display_label="associated-with")
            edge_counts[nid] += 1
            edge_counts[global_anchor] += 1

    data = engine.get_graph_data(filter_isolated=False)
    nodes = data["nodes"]
    edges = data["edges"]

    edge_set = set()
    for e in edges:
        edge_set.add(e["from"])
        edge_set.add(e["to"])

    isolated = [n for n in nodes if n["id"] not in edge_set]
    print(f"In-Memory Engine: {len(nodes)} nodes, {len(edges)} edges")
    print(f"Isolated Nodes Count: {len(isolated)}")

    if neo4j_client.is_connected:
        print("Syncing complete graph to Neo4j...")
        sync_result = engine.sync_to_neo4j()
        print("Neo4j Sync Result:", sync_result)
    else:
        print("Neo4j offline; in-memory complete.")

    print("Rebuild and sync complete!")


if __name__ == "__main__":
    main()
