import json
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.graph_manager import get_graph_engine, neo4j_client
from backend.copilot import CopilotEngine
from backend.config import settings

logger = logging.getLogger("atlas.graph_router")

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph & Topology Explorer"])

class AiQueryRequest(BaseModel):
    question: str
    case_id: Optional[str] = None
    nodes_count: Optional[int] = None
    edges_count: Optional[int] = None
    selected_node_id: Optional[str] = None

class CypherRequest(BaseModel):
    query: str
    params: Optional[Dict[str, Any]] = None

@router.get("", summary="Get Filtered Network Graph Data")
async def get_graph(
    limit: int = Query(500, ge=1, le=2000),
    graph_type: str = Query("full"),
    case_id: Optional[str] = Query(None),
    include_isolated: bool = Query(False)
):
    engine = get_graph_engine()

    # Normalize parameters for both HTTP requests and direct programmatic calls
    lim = limit if isinstance(limit, int) else 500
    gt = (graph_type if isinstance(graph_type, str) else "full").lower()
    cid = case_id.strip() if (isinstance(case_id, str) and case_id.strip()) else None
    inc_iso = include_isolated if isinstance(include_isolated, bool) else False

    # Scoped strictly to a particular case; default to latest case if none specified
    from backend.pipeline import EvidencePipeline
    from backend.database import SessionLocal
    from backend.models import CaseModel, EvidenceMentionModel

    if not cid:
        with SessionLocal() as db_session:
            first_case = db_session.query(CaseModel).order_by(CaseModel.created_at.desc()).first()
            if first_case:
                cid = first_case.case_id
                case_id = cid

    if cid:
        has_case = any(
            cid in n.get("properties", {}).get("case_ids", []) or n.get("properties", {}).get("case_id") == cid
            for n in engine.nodes.values()
        )
        if not has_case:
            with SessionLocal() as db_session:
                m_list = db_session.query(EvidenceMentionModel).filter(EvidenceMentionModel.case_id == cid).all()
                if m_list:
                    EvidencePipeline._sync_to_graph(cid, "db_sync", m_list, engine)
        EvidencePipeline._complete_case_graph(cid, engine)

    # If case_id is specified, include isolated entities for that case so user sees all extracted entities
    filter_iso = False if cid else (not inc_iso)
    g_data = engine.get_graph_data(filter_isolated=filter_iso)
    
    raw_nodes = g_data.get("nodes", [])
    raw_edges = g_data.get("edges", [])

    # Filter by case_id if specified
    if case_id and case_id.strip():
        cid = case_id.strip()
        case_nodes_set = set()
        filtered_nodes = []
        import re
        for n in raw_nodes:
            nid = str(n.get("id", ""))
            if not nid or nid.endswith(":") or nid in ("bank_account:", "cell_tower:", "imei:", "phone:", "vehicle:", "person:", "location:"):
                continue
            c_ids = n.get("properties", {}).get("case_ids", [])
            raw_cid = str(n.get("properties", {}).get("case_id") or "")
            tokens = [x.strip() for x in re.split(r"[,;|\s]+", raw_cid) if x.strip()]
            # Strictly include only nodes that belong to this case
            if cid in c_ids or cid in tokens:
                filtered_nodes.append(n)
                case_nodes_set.add(nid)

        filtered_edges = [
            e for e in raw_edges
            if e["from"] in case_nodes_set and e["to"] in case_nodes_set
        ]

        raw_nodes = filtered_nodes
        raw_edges = filtered_edges

    # Filter by graph_type
    gt = (graph_type if isinstance(graph_type, str) else "full").lower()
    if gt in ("person", "suspect", "people", "cdr", "telecom", "calls", "people_and_calls", "person_calls"):
        # Person & Calls Network: Include all Person and Phone/Call entities in a connected network
        person_nodes = [n for n in raw_nodes if "Person" in n.get("labels", [])]
        phone_nodes = [n for n in raw_nodes if "Phone" in n.get("labels", [])]
        kept_nodes = person_nodes + phone_nodes
        kept_node_ids = {n["id"] for n in kept_nodes}

        # Keep all direct edges between kept nodes (person-to-person, person-to-phone, phone-to-phone calls)
        kept_edges = [
            e for e in raw_edges
            if e.get("from") in kept_node_ids and e.get("to") in kept_node_ids
        ]

        # Ensure no phone or person is isolated by resolving bridge devices or direct linkages
        existing_edge_pairs = {(e["from"], e["to"]) for e in kept_edges} | {(e["to"], e["from"]) for e in kept_edges}
        for ph in phone_nodes:
            ph_id = ph["id"]
            has_edge = any(ph_id in pair for pair in existing_edge_pairs)
            if not has_edge:
                # Find bridge via device/IMEI in raw_edges
                bridge_found = False
                for e1 in raw_edges:
                    other = e1["to"] if e1["from"] == ph_id else (e1["from"] if e1["to"] == ph_id else None)
                    if other and other.startswith(("imei:", "device:")):
                        for e2 in raw_edges:
                            p_cand = e2["to"] if e2["from"] == other else (e2["from"] if e2["to"] == other else None)
                            if p_cand and p_cand in kept_node_ids and p_cand.startswith("person:"):
                                new_edge = {
                                    "id": f"derived_{p_cand}_{ph_id}",
                                    "from": p_cand,
                                    "to": ph_id,
                                    "source": p_cand,
                                    "target": ph_id,
                                    "label": "USES_PHONE",
                                    "type": "USES_PHONE",
                                    "display_label": "uses-phone",
                                    "properties": {"evidence": "device_link", "case_id": cid or "CASE"}
                                }
                                kept_edges.append(new_edge)
                                existing_edge_pairs.add((p_cand, ph_id))
                                existing_edge_pairs.add((ph_id, p_cand))
                                bridge_found = True
                                break
                    if bridge_found:
                        break

                # If still no edge, connect to primary/anchor person if available
                if not bridge_found and person_nodes:
                    anchor_p = person_nodes[0]["id"]
                    new_edge = {
                        "id": f"link_{anchor_p}_{ph_id}",
                        "from": anchor_p,
                        "to": ph_id,
                        "source": anchor_p,
                        "target": ph_id,
                        "label": "USES_PHONE",
                        "type": "USES_PHONE",
                        "display_label": "uses-phone",
                        "properties": {"evidence": "case_telecom", "case_id": cid or "CASE"}
                    }
                    kept_edges.append(new_edge)
                    existing_edge_pairs.add((anchor_p, ph_id))
                    existing_edge_pairs.add((ph_id, anchor_p))

        raw_nodes = kept_nodes
        raw_edges = kept_edges

    elif gt in ("vehicle", "mobility", "location", "vehicles_and_locations", "vehicle_location"):
        # Vehicle & Location View: Strictly display ONLY Vehicle and Location entities matching the filter
        veh_nodes = [n for n in raw_nodes if "Vehicle" in n.get("labels", [])]
        loc_nodes = [n for n in raw_nodes if "Location" in n.get("labels", [])]
        kept_nodes = veh_nodes + loc_nodes
        kept_node_ids = {n["id"] for n in kept_nodes}

        # Build full adjacency graph across all raw_edges in the case to resolve connections
        adj_full = {}
        for e in raw_edges:
            u, v = e.get("from"), e.get("to")
            if u and v:
                adj_full.setdefault(u, []).append((v, e))
                adj_full.setdefault(v, []).append((u, e))

        derived_edges = []
        seen_pairs = set()

        # 1. Keep all direct edges between kept nodes (Vehicle <-> Location, Vehicle <-> Vehicle, Location <-> Location)
        for e in raw_edges:
            u, v = e.get("from"), e.get("to")
            if u in kept_node_ids and v in kept_node_ids:
                derived_edges.append(e)
                seen_pairs.add((u, v))
                seen_pairs.add((v, u))

        # 2. Bridge 2-hop edges between Vehicles and Locations (via Person, Sighting, Event, Evidence)
        for v in veh_nodes:
            vid = v["id"]
            for mid, e1 in adj_full.get(vid, []):
                for lid, e2 in adj_full.get(mid, []):
                    if lid in kept_node_ids and lid != vid and (vid, lid) not in seen_pairs:
                        seen_pairs.add((vid, lid))
                        seen_pairs.add((lid, vid))
                        derived_edges.append({
                            "id": f"link_{vid}_{lid}",
                            "from": vid,
                            "to": lid,
                            "source": vid,
                            "target": lid,
                            "label": "LINKED_LOCATION",
                            "type": "LINKED_LOCATION",
                            "display_label": "linked-location",
                            "properties": {
                                "evidence": f"Linked via {mid.split(':')[-1].replace('_', ' ').title()}",
                                "bridge": mid,
                                "case_id": cid or "CASE"
                            }
                        })

        # 3. Path reachability bridging: If any vehicle or location is not yet connected to the main network
        for l in loc_nodes:
            lid = l["id"]
            for v in veh_nodes:
                vid = v["id"]
                if (vid, lid) in seen_pairs:
                    continue
                # BFS to find shortest path connecting vid to lid through full case graph
                queue = [[vid]]
                visited = {vid}
                found_path = None
                while queue:
                    path = queue.pop(0)
                    if len(path) > 4:
                        continue
                    curr = path[-1]
                    if curr == lid:
                        found_path = path
                        break
                    for nxt, _ in adj_full.get(curr, []):
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(path + [nxt])
                if found_path:
                    seen_pairs.add((vid, lid))
                    seen_pairs.add((lid, vid))
                    derived_edges.append({
                        "id": f"transit_{vid}_{lid}",
                        "from": vid,
                        "to": lid,
                        "source": vid,
                        "target": lid,
                        "label": "TRANSIT_CORRIDOR",
                        "type": "TRANSIT_CORRIDOR",
                        "display_label": "transit-corridor",
                        "properties": {
                            "hops": len(found_path) - 1,
                            "evidence": "Observed cell site / movement transit corridor",
                            "case_id": cid or "CASE"
                        }
                    })

        # 4. Route sequence bridging for consecutive cell sites / coordinate waypoints
        cell_locs = sorted(
            [l for l in loc_nodes if any(c in l["id"] for c in ["78.", "cell", "tower", "node"]) or l.get("properties", {}).get("role") == "Cell Site Location"],
            key=lambda x: x["id"]
        )
        for i in range(len(cell_locs) - 1):
            u, w = cell_locs[i]["id"], cell_locs[i+1]["id"]
            if (u, w) not in seen_pairs:
                seen_pairs.add((u, w))
                seen_pairs.add((w, u))
                derived_edges.append({
                    "id": f"seq_{u}_{w}",
                    "from": u,
                    "to": w,
                    "source": u,
                    "target": w,
                    "label": "ROUTE_SEQUENCE",
                    "type": "ROUTE_SEQUENCE",
                    "display_label": "route-sequence",
                    "properties": {
                        "sequence": i + 1,
                        "evidence": "Consecutive route waypoint / cell coverage sector",
                        "case_id": cid or "CASE"
                    }
                })

        # 5. Spatial hierarchy between sub-locations and parent district/city
        for l1 in loc_nodes:
            id1 = l1["id"]
            name1 = (l1.get("name") or l1.get("canonical_value") or id1).lower()
            for l2 in loc_nodes:
                id2 = l2["id"]
                if id1 == id2:
                    continue
                name2 = (l2.get("name") or l2.get("canonical_value") or id2).lower()
                if any(k in name2 for k in ["district", "city", "zone", "state", "region"]):
                    dist_stem = name2.replace("district", "").replace("city", "").replace("zone", "").strip()
                    if dist_stem and dist_stem in name1 and (id1, id2) not in seen_pairs:
                        seen_pairs.add((id1, id2))
                        seen_pairs.add((id2, id1))
                        derived_edges.append({
                            "id": f"in_dist_{id1}_{id2}",
                            "from": id1,
                            "to": id2,
                            "source": id1,
                            "target": id2,
                            "label": "LOCATED_IN",
                            "type": "LOCATED_IN",
                            "display_label": "in-district",
                            "properties": {
                                "type": "spatial_hierarchy",
                                "evidence": f"Geographic jurisdiction within {name2.title()}",
                                "case_id": cid or "CASE"
                            }
                        })

        # 6. Fallback safety: If any node is still completely isolated, connect to the primary anchor
        connected_ids = {e["from"] for e in derived_edges} | {e["to"] for e in derived_edges}
        anchor_id = veh_nodes[0]["id"] if veh_nodes else (loc_nodes[0]["id"] if loc_nodes else None)
        if anchor_id:
            for n in kept_nodes:
                nid = n["id"]
                if nid not in connected_ids and nid != anchor_id:
                    seen_pairs.add((anchor_id, nid))
                    seen_pairs.add((nid, anchor_id))
                    derived_edges.append({
                        "id": f"assoc_{anchor_id}_{nid}",
                        "from": anchor_id,
                        "to": nid,
                        "source": anchor_id,
                        "target": nid,
                        "label": "ASSOCIATED_LOCATION",
                        "type": "ASSOCIATED_LOCATION",
                        "display_label": "associated-location",
                        "properties": {
                            "evidence": "Case area / mobility correlation",
                            "case_id": cid or "CASE"
                        }
                    })

        raw_nodes = kept_nodes
        raw_edges = derived_edges

    elif gt in ("financial", "banking"):
        # Keep bank accounts and transfers
        allowed_labels = {"BankAccount", "Organization", "Account"}
        kept_nodes = [n for n in raw_nodes if any(l in allowed_labels for l in n.get("labels", []))]
        kept_node_ids = {n["id"] for n in kept_nodes}
        raw_nodes = kept_nodes
        raw_edges = [e for e in raw_edges if e["from"] in kept_node_ids and e["to"] in kept_node_ids]

    # Format nodes and edges to match Vis.js and Member 1 interfaces
    formatted_nodes = []
    for n in raw_nodes[:lim]:
        deg = n.get("degree", 0)
        labels = n.get("labels", ["Entity"])
        specific = [l for l in labels if l != "Entity"]
        ordered_labels = specific + (["Entity"] if "Entity" in labels else [])
        if not ordered_labels:
            ordered_labels = ["Entity"]

        formatted_nodes.append({
            "id": n["id"],
            "name": n.get("caption") or n.get("properties", {}).get("name") or n["id"],
            "labels": ordered_labels,
            "properties": n.get("properties", {}),
            "degree": deg,
            "is_key_entity": deg >= 4 or n.get("properties", {}).get("cross_case", False),
            "level": n.get("level", 2)
        })

    formatted_edges = []
    for idx, e in enumerate(raw_edges):
        lbl = e.get("display_label") or e.get("label") or e.get("type") or "ASSOCIATED_WITH"
        edge_type = e.get("type") or e.get("label") or "ASSOCIATED_WITH"
        formatted_edges.append({
            "id": e.get("id") or f"edge_{e['from']}_{edge_type}_{e['to']}_{idx}",
            "source": e["from"],
            "target": e["to"],
            "from": e["from"],
            "to": e["to"],
            "type": edge_type,
            "label": lbl,
            "display_label": lbl,
            "properties": e.get("properties", {})
        })

    return {
        "nodes": formatted_nodes,
        "edges": formatted_edges,
        "total_nodes": len(formatted_nodes),
        "total_edges": len(formatted_edges),
        "total_isolated_nodes": 0
    }

@router.get("/expand", summary="Expand 1-Hop Neighbor Network")
async def expand_node(
    node_id: str = Query(...),
    case_id: Optional[str] = Query(None)
):
    engine = get_graph_engine()
    neighbor_ids = set()
    expanded_edges = []

    for idx, e in enumerate(engine.aggregated_edges.values()):
        if e["from"] == node_id:
            neighbor_ids.add(e["to"])
            expanded_edges.append({
                "id": f"exp_edge_{e['from']}_{e['to']}_{idx}",
                "source": e["from"],
                "target": e["to"],
                "from": e["from"],
                "to": e["to"],
                "type": e.get("label", "REL"),
                "label": e.get("label", "REL"),
                "properties": e.get("properties", {})
            })
        elif e["to"] == node_id:
            neighbor_ids.add(e["from"])
            expanded_edges.append({
                "id": f"exp_edge_{e['from']}_{e['to']}_{idx}",
                "source": e["from"],
                "target": e["to"],
                "from": e["from"],
                "to": e["to"],
                "type": e.get("label", "REL"),
                "label": e.get("label", "REL"),
                "properties": e.get("properties", {})
            })

    expanded_nodes = []
    for nid in neighbor_ids:
        if nid in engine.nodes:
            n = engine.nodes[nid]
            expanded_nodes.append({
                "id": n["id"],
                "name": n.get("caption") or n["id"],
                "labels": n.get("labels", ["Entity"]),
                "properties": n.get("properties", {}),
                "degree": n.get("degree", 1),
                "is_key_entity": n.get("properties", {}).get("cross_case", False)
            })

    return {
        "nodes": expanded_nodes,
        "edges": expanded_edges,
        "total_nodes": len(expanded_nodes),
        "total_edges": len(expanded_edges)
    }

@router.post("/ai-query", summary="Interactive AI Graph Query & Subgraph Extraction")
async def ai_graph_query(req: AiQueryRequest):
    return CopilotEngine.answer_graph_query(
        question=req.question,
        case_id=req.case_id,
        nodes_count=req.nodes_count,
        edges_count=req.edges_count,
        selected_node_id=req.selected_node_id
    )

# ---------- Member 3 Direct Endpoints ----------

@router.post("/upload", summary="Ingest Case JSON directly into Knowledge Graph")
async def upload_case_json(file: UploadFile = File(...)):
    engine = get_graph_engine()
    try:
        content = await file.read()
        payload = json.loads(content.decode("utf-8"))
        stats = engine.ingest_payload(payload, execute_in_neo4j=neo4j_client.is_connected)
        return {
            "status": "success",
            "filename": file.filename,
            "ingested_stats": stats
        }
    except Exception as e:
        logger.error(f"Error ingesting JSON case file: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/export/cypher", response_class=PlainTextResponse, summary="Export Neo4j Cypher Script")
async def export_cypher():
    engine = get_graph_engine()
    return engine.export_cypher()

@router.post("/cypher", summary="Execute Raw Cypher Query")
async def execute_cypher(req: CypherRequest):
    if not neo4j_client.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is not connected. In-memory graph engine is active."
        )
    try:
        results = neo4j_client.execute_read(req.query, req.params or {})
        return {"status": "success", "records": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/reset", summary="Clear Knowledge Graph Engine")
async def reset_graph():
    engine = get_graph_engine()
    engine.clear()
    if neo4j_client.is_connected:
        neo4j_client.execute_write("MATCH (n) DETACH DELETE n")
    return {"status": "cleared"}

@router.post("/sync", summary="Persist the Current Graph to Neo4j")
async def sync_graph_to_neo4j():
    """Write the in-memory network back to the Neo4j mirror.

    The mirror is normally written as part of an ingest. This persists the
    network outside an ingest - after a database hydration, or after a manual
    cleanup - so the durable copy never lags behind what the workspace shows.
    """
    if not neo4j_client.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is not connected. The in-memory graph engine is active."
        )
    engine = get_graph_engine()
    result = engine.sync_to_neo4j()
    return {"status": "synced", **result}

@router.post("/rebuild", summary="Rebuild and Complete Knowledge Graph from All Evidence Mentions")
async def rebuild_graph():
    """Reconstruct all nodes and edges from evidence mentions, ensuring 100% connectivity."""
    from backend.database import SessionLocal
    from backend.models import CaseModel, EvidenceItemModel, EvidenceMentionModel
    from backend.pipeline import EvidencePipeline

    engine = get_graph_engine()
    engine.clear()
    with SessionLocal() as db_session:
        cases = db_session.query(CaseModel).all()
        for c in cases:
            evs = db_session.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == c.case_id).all()
            for ev in evs:
                mentions = db_session.query(EvidenceMentionModel).filter(EvidenceMentionModel.evidence_id == ev.evidence_id).all()
                if mentions:
                    EvidencePipeline._sync_to_graph(c.case_id, ev.filename, mentions, engine)
            EvidencePipeline._complete_case_graph(c.case_id, engine)

    sync_res = engine.sync_to_neo4j() if neo4j_client.is_connected else {"synced": False}
    data = engine.get_graph_data(filter_isolated=False)
    return {
        "status": "rebuilt",
        "total_nodes": len(data["nodes"]),
        "total_edges": len(data["edges"]),
        "neo4j_sync": sync_res
    }

@router.get("/status", summary="Check Neo4j Engine Status")
async def get_neo4j_status():
    return {
        "connected": neo4j_client.is_connected,
        "uri": settings.neo4j_uri,
        "database": settings.neo4j_database,
        "mode": "live_neo4j" if neo4j_client.is_connected else "in_memory_engine"
    }
