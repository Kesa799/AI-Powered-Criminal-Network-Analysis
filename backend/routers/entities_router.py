import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import EvidenceMentionModel
from backend.graph_manager import get_graph_engine

logger = logging.getLogger("atlas.entities_router")

router = APIRouter(prefix="/api/entities", tags=["Entity Directory & Search"])

@router.get("/search", summary="Multi-Property Entity Search")
async def search_entities(
    q: str = Query("", description="Query string for name, phone, VIN, account"),
    entity_type: Optional[str] = Query(None, description="Filter by category (Person, Phone, Vehicle, BankAccount)"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    query_str = q.strip().lower()
    engine = get_graph_engine()
    results = []
    seen_keys = set()

    # 1. Search Knowledge Graph Nodes
    for nid, node in engine.nodes.items():
        # Skip invalid / empty placeholder ids
        if not nid or nid.endswith(":") or nid in ("bank_account:", "cell_tower:", "imei:", "phone:", "vehicle:", "person:", "location:"):
            continue

        labels = node.get("labels", [])
        props = node.get("properties", {})
        caption = str(node.get("caption") or "").lower()
        canon = str(props.get("canonical_value") or "").lower()
        name = str(props.get("name") or "").lower()

        # Check entity_type
        if entity_type and entity_type.lower() != "all":
            if not any(l.lower() == entity_type.lower() for l in labels):
                continue

        # Match query
        if not query_str or query_str in caption or query_str in canon or query_str in name or query_str in nid.lower():
            primary_label = next((l for l in labels if l != "Entity"), "Entity")
            display_title = node.get("caption") or props.get("name") or canon or nid
            norm_title = str(display_title).strip().lower()
            slug_val = norm_title.replace(" ", "_")

            # Check if this exact entity was already added
            canon_type_key = f"{primary_label.lower()}:{norm_title}"
            if canon_type_key in seen_keys or nid.lower() in seen_keys:
                continue

            seen_keys.add(nid.lower())
            seen_keys.add(canon_type_key)
            seen_keys.add(f"{primary_label.lower()}:{slug_val}")
            seen_keys.add(norm_title)
            if canon:
                seen_keys.add(f"{primary_label.lower()}:{canon}")

            results.append({
                "id": nid,
                "entity_id": nid,
                "name": display_title,
                "display_name": display_title,
                "labels": labels,
                "case_ids": props.get("case_ids", []),
                "properties": props
            })
            if len(results) >= limit:
                break

    # 2. If graph had few, check DB mentions for any missing entities without duplicating
    if len(results) < limit:
        m_query = db.query(EvidenceMentionModel)
        if query_str:
            m_query = m_query.filter(
                EvidenceMentionModel.normalized_value.ilike(f"%{query_str}%") |
                EvidenceMentionModel.raw_value.ilike(f"%{query_str}%")
            )
        if entity_type and entity_type.lower() != "all":
            m_query = m_query.filter(EvidenceMentionModel.type.ilike(f"%{entity_type}%"))
        
        db_mentions = m_query.limit(limit * 2).all()
        for m in db_mentions:
            m_val = str(m.normalized_value or m.raw_value or "").strip()
            if not m_val or m_val.lower() in ("unknown", "none", "n/a", "null"):
                continue

            m_type = str(m.type or "Entity").strip()
            m_norm = m_val.lower()
            m_slug = m_norm.replace(" ", "_")
            canon_type_key = f"{m_type.lower()}:{m_norm}"
            slug_id = f"{m_type.lower()}:{m_slug}"

            # Deduplication: Strictly skip if already in graph or already seen
            if (
                canon_type_key in seen_keys or
                slug_id in seen_keys or
                m_norm in seen_keys or
                slug_id in engine.nodes or
                f"{m_type.lower()}:{m_val}" in engine.nodes
            ):
                continue

            seen_keys.add(canon_type_key)
            seen_keys.add(slug_id)
            seen_keys.add(m_norm)

            results.append({
                "id": slug_id,
                "entity_id": slug_id,
                "name": m_val,
                "display_name": m_val,
                "labels": ["Entity", m_type],
                "case_ids": [m.case_id],
                "properties": {
                    "canonical_value": m.normalized_value,
                    "raw_value": m.raw_value,
                    "role": m.role,
                    "quote": m.quote,
                    "case_ids": [m.case_id]
                }
            })
            if len(results) >= limit:
                break

    return results

@router.get("/{entity_id:path}", summary="Get Entity Profile & 1-Hop Connections")
async def get_entity_profile(entity_id: str, db: Session = Depends(get_db)):
    engine = get_graph_engine()
    
    # 1. Direct match in graph
    node = engine.nodes.get(entity_id)

    # 2. Case-insensitive / slug variations in graph
    if not node:
        e_lower = entity_id.lower()
        e_slug = e_lower.replace(" ", "_")
        node = engine.nodes.get(e_lower) or engine.nodes.get(e_slug)

    # 3. Search graph by matching id, caption, name, or canonical_value
    if not node:
        clean_target = entity_id.split(":", 1)[-1].lower().replace("_", " ").strip()
        for nid, n in engine.nodes.items():
            n_cap = str(n.get("caption") or "").lower().strip()
            n_name = str(n.get("properties", {}).get("name") or "").lower().strip()
            n_canon = str(n.get("properties", {}).get("canonical_value") or "").lower().strip()
            n_nid_clean = nid.split(":", 1)[-1].lower().replace("_", " ").strip()
            if clean_target in (n_cap, n_name, n_canon, n_nid_clean):
                node = n
                entity_id = nid
                break

    # 4. If still not in graph, check DB mentions
    if not node:
        clean_target = entity_id.split(":", 1)[-1].strip()
        mention = db.query(EvidenceMentionModel).filter(
            (EvidenceMentionModel.id == entity_id) |
            (EvidenceMentionModel.normalized_value == entity_id) |
            (EvidenceMentionModel.normalized_value.ilike(clean_target)) |
            (EvidenceMentionModel.raw_value.ilike(clean_target))
        ).first()
        if mention:
            node = {
                "id": entity_id,
                "caption": mention.normalized_value or mention.raw_value,
                "labels": ["Entity", mention.type],
                "properties": {
                    "name": mention.normalized_value or mention.raw_value,
                    "canonical_value": mention.normalized_value,
                    "role": mention.role,
                    "quote": mention.quote,
                    "case_ids": [mention.case_id]
                }
            }
        else:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found.")

    # Find connections
    connections = []
    seen_conn = set()

    for idx, e in enumerate(engine.aggregated_edges.values()):
        rel = e.get("label", "CONNECTED")
        if e["from"] == entity_id:
            target_id = e["to"]
            target_node = engine.nodes.get(target_id, {})
            key = f"OUT_{rel}_{target_id}"
            if key not in seen_conn:
                seen_conn.add(key)
                connections.append({
                    "relationship": rel,
                    "rel_type": rel,
                    "direction": "OUTGOING",
                    "target_id": target_id,
                    "target_name": target_node.get("caption") or target_id,
                    "neighbor_labels": target_node.get("labels", ["Entity"]),
                    "properties": e.get("properties", {})
                })
        elif e["to"] == entity_id:
            src_id = e["from"]
            src_node = engine.nodes.get(src_id, {})
            key = f"IN_{rel}_{src_id}"
            if key not in seen_conn:
                seen_conn.add(key)
                connections.append({
                    "relationship": rel,
                    "rel_type": rel,
                    "direction": "INCOMING",
                    "target_id": src_id,
                    "target_name": src_node.get("caption") or src_id,
                    "neighbor_labels": src_node.get("labels", ["Entity"]),
                    "properties": e.get("properties", {})
                })

    return {
        "node": {
            "id": node["id"],
            "name": node.get("caption") or node.get("properties", {}).get("name") or node["id"],
            "labels": node.get("labels", ["Entity"]),
            "properties": node.get("properties", {})
        },
        "connections": connections
    }
