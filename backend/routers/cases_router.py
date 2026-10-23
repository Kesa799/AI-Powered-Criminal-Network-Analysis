import datetime
import hashlib
import re
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    CaseModel, EvidenceItemModel, EvidenceMentionModel, EvidenceSourceModel,
    CaseFindingModel, ActivityLogModel, BlockchainBlockModel
)
from backend.analytics import compute_rankings, find_shortest_path, detect_pattern_insights
from backend.copilot import CopilotEngine
from backend.graph_manager import get_graph_engine
from backend.blockchain_service import BlockchainService

router = APIRouter(prefix="/api/cases", tags=["Case Management & Intelligence"])

def extract_case_fir_details(c: CaseModel, db: Session) -> Dict[str, Any]:
    fir_item = db.query(EvidenceItemModel).filter(
        EvidenceItemModel.case_id == c.case_id,
        EvidenceItemModel.filename.ilike('%FIR%')
    ).first()

    data = {
        'fir_number': c.fir_number or f"FIR-{c.case_id}",
        'fir_description': c.summary or "",
        'occurrence_date': c.date_filed or "",
        'occurrence_time': "",
        'place_of_occurrence': "",
        'total_value': "",
        'complainant': c.victim or "",
        'police_station': "",
        'assigned_officer': c.lead_investigator or ""
    }

    if not fir_item:
        if not data['fir_description']:
            data['fir_description'] = (
                f"Investigation docket for {c.case_name} registered under FIR {data['fir_number']}. "
                f"Crime Category: {c.crime_category or 'General Investigation'}. Status: {c.status or 'UNDER_INVESTIGATION'}."
            )
        return data

    sources = db.query(EvidenceSourceModel).filter(
        EvidenceSourceModel.evidence_id == fir_item.evidence_id
    ).order_by(EvidenceSourceModel.page).all()

    if not sources:
        if not data['fir_description']:
            data['fir_description'] = (
                f"Investigation docket for {c.case_name} registered under FIR {data['fir_number']}. "
                f"Crime Category: {c.crime_category or 'General Investigation'}. Status: {c.status or 'UNDER_INVESTIGATION'}."
            )
        return data

    # Page 1 parsing
    p1 = sources[0].text or ''
    p1_lines = [l.strip() for l in p1.splitlines() if l.strip()]

    val_start = None
    for idx, l in enumerate(p1_lines):
        if 'Particulars of properties' in l:
            val_start = idx + 1
            break

    comp_name = None
    comp_occ = None
    if val_start is not None and val_start < len(p1_lines):
        vals = p1_lines[val_start:]
        if len(vals) > 1 and vals[0] != 'Not recorded':
            data['police_station'] = f"{vals[0]} {vals[1]} Police Station"
        if len(vals) > 3 and 'SYN-' in vals[3]:
            data['fir_number'] = vals[3]
        if len(vals) > 4 and re.match(r'^\d{2}-\d{2}-\d{4}$', vals[4]):
            data['date_filed'] = vals[4]

        for v_idx, v in enumerate(vals):
            if v in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
                if v_idx + 1 < len(vals) and re.match(r'^\d{2}-\d{2}-\d{4}$', vals[v_idx+1]):
                    data['occurrence_date'] = f"{vals[v_idx+1]} ({v})"
                if v_idx + 2 < len(vals) and ('-' in vals[v_idx+2] or ':' in vals[v_idx+2]):
                    data['occurrence_time'] = f"{vals[v_idx+2]} hrs"
            if any(term in v for term in ['Street', 'Road', 'Nagar', 'Market', 'Lane', 'Depot', 'Yard', 'Arcade', 'Foundry', 'Civic', 'Canal', 'Ring']):
                if not data['place_of_occurrence'] and 'Police' not in v:
                    data['place_of_occurrence'] = v
            if any(term in v for term in ['Local business operator', 'Workshop manager', 'Store supervisor', 'Resident', 'Shopkeeper', 'Manager', 'Supervisor', 'Warehouse supervisor']):
                comp_occ = v
            if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+$', v):
                if not comp_name and v not in ['Anaya Sen', 'Vikram Rathore', 'Pending classification']:
                    comp_name = v

    if comp_name:
        data['complainant'] = f"{comp_name} ({comp_occ})" if comp_occ else comp_name
    elif comp_occ:
        data['complainant'] = comp_occ

    # Page 2 parsing
    if len(sources) > 1:
        p2 = sources[1].text or ''
        p2_lines = [l.strip() for l in p2.splitlines() if l.strip()]

        for l in p2_lines:
            if re.match(r'^INR\s+[\d,]+', l):
                data['total_value'] = l
                break

        for idx, l in enumerate(p2_lines):
            if l in ['Inspector', 'Sub-Inspector']:
                if idx > 0 and p2_lines[idx-1] not in ['Signature of the Officer-in-charge, Police Station', 'Rank']:
                    data['assigned_officer'] = f"{l} {p2_lines[idx-1]}"
                    break

        narrative_lines = []
        started = False
        for l in p2_lines:
            if l == 'Not applicable':
                started = True
                continue
            if started:
                if any(k in l for k in ['Inspector', 'Sub-Inspector', 'SYN-O-', 'Not transferred', 'Date & time of despatch']):
                    break
                narrative_lines.append(l)

        if narrative_lines:
            raw_desc = ' '.join(narrative_lines).strip()
            if data.get('assigned_officer'):
                off_name = data['assigned_officer'].split(' ', 1)[-1].strip()
                if off_name and raw_desc.endswith(off_name):
                    raw_desc = raw_desc[:-len(off_name)].strip()
            data['fir_description'] = raw_desc

    if not data['fir_description']:
        data['fir_description'] = c.summary or (
            f"Investigation docket for {c.case_name} registered under FIR {data['fir_number']}. "
            f"Crime Category: {c.crime_category or 'General Investigation'}. Status: {c.status or 'UNDER_INVESTIGATION'}."
        )

    # Persist back to c.summary if missing or generic
    if not c.summary or c.summary.startswith("Investigation docket "):
        c.summary = data['fir_description']
        if data.get('fir_number'):
            c.fir_number = data['fir_number']
        try:
            db.commit()
        except Exception:
            db.rollback()

    return data

class CaseCreateRequest(BaseModel):
    case_id: str
    case_name: str
    fir_number: Optional[str] = None
    status: Optional[str] = "UNDER_INVESTIGATION"
    lead_investigator: Optional[str] = "Lead Investigator"
    uploaded_by: Optional[str] = None
    severity: Optional[str] = "High"
    crime_category: Optional[str] = "General Investigation"
    primary_suspect: Optional[str] = None
    victim: Optional[str] = None
    date_filed: Optional[str] = None
    summary: Optional[str] = None

class CaseFindingCreateRequest(BaseModel):
    title: str
    category: Optional[str] = "General Note"
    content: str
    officer_name: Optional[str] = "Investigator"
    officer_badge: Optional[str] = "LE-8402"
    severity: Optional[str] = "MEDIUM"
    attachments: Optional[List[Dict[str, Any]]] = []

@router.get("", summary="List Investigation Cases")
async def list_cases(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    cases = db.query(CaseModel).order_by(CaseModel.created_at.desc()).limit(limit).all()
    results = []
    for c in cases:
        ev_count = db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == c.case_id).count()
        ent_count = db.query(EvidenceMentionModel).filter(EvidenceMentionModel.case_id == c.case_id).count()
        fir_details = extract_case_fir_details(c, db)
        results.append({
            "case_id": c.case_id,
            "fir_number": fir_details.get("fir_number") or c.fir_number or f"FIR-{c.case_id}",
            "case_name": c.case_name,
            "status": c.status,
            "lead_investigator": fir_details.get("assigned_officer") or c.lead_investigator,
            "uploaded_by": c.uploaded_by,
            "severity": c.severity,
            "crime_category": c.crime_category,
            "primary_suspect": c.primary_suspect,
            "victim": fir_details.get("complainant") or c.victim,
            "date_filed": fir_details.get("date_filed") or c.date_filed or (c.created_at.strftime("%Y-%m-%d") if c.created_at else None),
            "summary": fir_details.get("fir_description") or c.summary,
            "fir_description": fir_details.get("fir_description") or c.summary,
            "occurrence_date": fir_details.get("occurrence_date"),
            "occurrence_time": fir_details.get("occurrence_time"),
            "place_of_occurrence": fir_details.get("place_of_occurrence"),
            "total_value": fir_details.get("total_value"),
            "complainant": fir_details.get("complainant") or c.victim,
            "police_station": fir_details.get("police_station"),
            "assigned_officer": fir_details.get("assigned_officer") or c.lead_investigator,
            "total_entities": ent_count if ent_count > 0 else c.total_entities,
            "evidences": c.evidences or [],
            "evidence_count": ev_count,
            "overlapping_cases": c.overlapping_cases or [],
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
    return results

@router.get("/rankings", summary="Graph Centrality Rankings")
async def get_rankings(
    metric: str = Query("pagerank", pattern="^(pagerank|betweenness|degree)$"),
    label: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    case_id: Optional[str] = Query(None)
):
    return compute_rankings(metric=metric, label=label, limit=limit, case_id=case_id)

@router.get("/shortest-path", summary="Dijkstra Shortest Path Finder")
async def get_shortest_path(
    suspect_name: Optional[str] = Query(None),
    victim_name: Optional[str] = Query(None),
    suspect_id: Optional[str] = Query(None),
    victim_id: Optional[str] = Query(None),
    max_depth: int = Query(5, ge=1, le=10)
):
    src = suspect_id or suspect_name
    dst = victim_id or victim_name
    if not src or not dst:
        raise HTTPException(status_code=400, detail="Must supply both suspect and victim/target parameters.")
    return find_shortest_path(src, dst, max_depth)

@router.post("", summary="Create Investigation Case")
async def create_case(req: CaseCreateRequest, db: Session = Depends(get_db)):
    cid = req.case_id.strip()
    existing = db.query(CaseModel).filter(CaseModel.case_id == cid).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Case with ID '{cid}' already exists.")

    new_case = CaseModel(
        case_id=cid,
        fir_number=req.fir_number or f"FIR-{cid}",
        case_name=req.case_name.strip(),
        status=req.status or "UNDER_INVESTIGATION",
        lead_investigator=req.lead_investigator or "Lead Detective",
        uploaded_by=req.uploaded_by,
        severity=req.severity or "High",
        crime_category=req.crime_category or "General Investigation",
        primary_suspect=req.primary_suspect,
        victim=req.victim,
        date_filed=req.date_filed or datetime.date.today().isoformat(),
        summary=req.summary,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow()
    )
    db.add(new_case)
    db.commit()
    db.refresh(new_case)

    # Log activity and blockchain block
    BlockchainService.append_block(
        db=db,
        case_id=cid,
        document_type="CASE_CREATION",
        data={"case_id": cid, "case_name": new_case.case_name, "fir_number": new_case.fir_number}
    )
    BlockchainService.log_activity(
        db=db,
        case_id=cid,
        action_type="CASE_CREATED",
        title=f"Case Docket Registered: {new_case.case_name}",
        description=f"Initial registration for {cid} under category '{new_case.crime_category}'.",
        officer_name=new_case.lead_investigator,
        status_type="verified",
        icon_type="case"
    )

    return {"case_id": cid, "case_name": new_case.case_name, "status": "created"}

@router.get("/{case_id}", summary="Get Case Details")
async def get_case(case_id: str, db: Session = Depends(get_db)):
    c = db.query(CaseModel).filter(CaseModel.case_id == case_id).first()
    if not c:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    
    ev_count = db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == case_id).count()
    ent_count = db.query(EvidenceMentionModel).filter(EvidenceMentionModel.case_id == case_id).count()

    fir_details = extract_case_fir_details(c, db)

    return {
        "case_id": c.case_id,
        "fir_number": fir_details.get("fir_number") or c.fir_number or f"FIR-{c.case_id}",
        "case_name": c.case_name,
        "status": c.status,
        "lead_investigator": fir_details.get("assigned_officer") or c.lead_investigator,
        "uploaded_by": c.uploaded_by,
        "severity": c.severity,
        "crime_category": c.crime_category,
        "primary_suspect": c.primary_suspect,
        "victim": fir_details.get("complainant") or c.victim,
        "date_filed": fir_details.get("date_filed") or c.date_filed or (c.created_at.strftime("%Y-%m-%d") if c.created_at else None),
        "summary": fir_details.get("fir_description") or c.summary,
        "fir_description": fir_details.get("fir_description") or c.summary,
        "occurrence_date": fir_details.get("occurrence_date"),
        "occurrence_time": fir_details.get("occurrence_time"),
        "place_of_occurrence": fir_details.get("place_of_occurrence"),
        "total_value": fir_details.get("total_value"),
        "complainant": fir_details.get("complainant") or c.victim,
        "police_station": fir_details.get("police_station"),
        "assigned_officer": fir_details.get("assigned_officer") or c.lead_investigator,
        "total_entities": ent_count if ent_count > 0 else c.total_entities,
        "evidences": c.evidences or [],
        "evidence_count": ev_count,
        "overlapping_cases": c.overlapping_cases or [],
        "created_at": c.created_at.isoformat() if c.created_at else None
    }

@router.get("/{case_id}/insights", summary="10 Pattern Insights for Case")
async def get_case_insights(case_id: str):
    return detect_pattern_insights(case_id)

@router.get("/{case_id}/ai-dossier", summary="Executive AI Dossier")
async def get_case_ai_dossier(case_id: str, db: Session = Depends(get_db)):
    c = db.query(CaseModel).filter(CaseModel.case_id == case_id).first()
    c_name = c.case_name if c else case_id
    return CopilotEngine.generate_dossier(case_id, c_name)

@router.delete("/{case_id}", summary="Delete Investigation Case")
async def delete_case(
    case_id: str,
    confirm: bool = Query(False),
    db: Session = Depends(get_db)
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true to delete case.")
    c = db.query(CaseModel).filter(CaseModel.case_id == case_id).first()
    if not c:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    # Remove evidence records, mentions, sources, findings
    db.query(EvidenceMentionModel).filter(EvidenceMentionModel.case_id == case_id).delete()
    db.query(EvidenceSourceModel).filter(EvidenceSourceModel.case_id == case_id).delete()
    db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == case_id).delete()
    db.query(CaseFindingModel).filter(CaseFindingModel.case_id == case_id).delete()
    db.delete(c)
    db.commit()

    return {"status": "deleted", "case_id": case_id}

@router.delete("/reset", summary="Admin Purge All Cases")
async def reset_cases(
    confirm: bool = Query(False),
    db: Session = Depends(get_db)
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true to reset database.")
    db.query(EvidenceMentionModel).delete()
    db.query(EvidenceSourceModel).delete()
    db.query(EvidenceItemModel).delete()
    db.query(CaseFindingModel).delete()
    db.query(CaseModel).delete()
    db.commit()
    get_graph_engine().clear()
    return {"status": "all_cases_purged"}

# ---------- Case Findings Endpoints ----------

@router.get("/{case_id}/findings", summary="List Case Finding Notes")
async def get_findings(case_id: str, db: Session = Depends(get_db)):
    findings = db.query(CaseFindingModel).filter(CaseFindingModel.case_id == case_id).all()
    results = []
    for f in findings:
        results.append({
            "finding_id": f.finding_id,
            "case_id": f.case_id,
            "title": f.title,
            "category": f.category,
            "content": f.content,
            "officer_name": f.officer_name,
            "officer_badge": f.officer_badge,
            "severity": f.severity,
            "attachments": f.attachments or [],
            "created_at": f.created_at,
            "updated_at": f.updated_at
        })
    return results

@router.post("/{case_id}/findings", summary="Add Case Finding Note")
async def add_finding(case_id: str, req: CaseFindingCreateRequest, db: Session = Depends(get_db)):
    fid = f"FIND-{abs(hash(req.title + datetime.datetime.utcnow().isoformat())) % 1000000}"
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    finding = CaseFindingModel(
        finding_id=fid,
        case_id=case_id,
        title=req.title,
        category=req.category or "General Note",
        content=req.content,
        officer_name=req.officer_name,
        officer_badge=req.officer_badge,
        severity=req.severity or "MEDIUM",
        attachments=req.attachments or [],
        created_at=now_iso,
        updated_at=now_iso
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    BlockchainService.log_activity(
        db=db,
        case_id=case_id,
        action_type="FINDING_ADDED",
        title=f"Finding Note Recorded: {req.title}",
        description=f"Investigative observation cataloged under '{req.category}'.",
        officer_name=req.officer_name or "Investigator",
        officer_badge=req.officer_badge or "LE-8402",
        status_type="info",
        icon_type="note"
    )

    return {
        "finding_id": finding.finding_id,
        "case_id": finding.case_id,
        "title": finding.title,
        "category": finding.category,
        "content": finding.content,
        "officer_name": finding.officer_name,
        "officer_badge": finding.officer_badge,
        "severity": finding.severity,
        "attachments": finding.attachments or [],
        "created_at": finding.created_at
    }

@router.delete("/{case_id}/findings/{finding_id}", summary="Delete Finding Note")
async def delete_finding(case_id: str, finding_id: str, db: Session = Depends(get_db)):
    f = db.query(CaseFindingModel).filter(
        CaseFindingModel.case_id == case_id,
        CaseFindingModel.finding_id == finding_id
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding note not found.")
    db.delete(f)
    db.commit()
    return {"status": "deleted", "finding_id": finding_id}
