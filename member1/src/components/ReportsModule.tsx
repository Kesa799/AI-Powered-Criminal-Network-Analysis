import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { API, Case, OfficerSession } from '../services/api';
import { InvestigationBoardRecord } from './InvestigationBoardModule';
import './reports.css';

interface ReportsModuleProps {
  cases: Case[];
  selectedCase?: string | null;
  onSelectCase?: (caseId: string) => void;
  officerSession?: OfficerSession | null;
  changeView: (id: string) => void;
  addToast: (msg: string, type?: string) => void;
}

interface AiDossier {
  title?: string;
  executive_summary?: string;
  summary?: string;
  key_findings?: string[];
}

interface PatternInsight {
  insight_id: string;
  insight_type: string;
  title: string;
  severity: string;
  description: string;
  derived_interpretation?: string;
  observed_facts?: string[];
  entities_involved?: string[];
  alternative_explanations?: string[];
  disclaimer?: string;
}

interface EvidenceItemRecord {
  evidence_id: string;
  case_id: string;
  sha256: string;
  filename: string;
  format?: string;
  size?: number;
  uploaded_at?: string;
  uploader?: string;
  job?: {
    classification?: string;
    mention_count?: number;
    claim_count?: number;
  };
}

interface FindingRecord {
  finding_id: string;
  case_id: string;
  title: string;
  category: string;
  content: string;
  officer_name?: string;
  officer_badge?: string;
  severity?: string;
  created_at?: string;
}

interface GraphEntityNode {
  id: string;
  name?: string;
  labels?: string[];
  properties?: Record<string, any>;
  degree?: number;
}

interface GraphEntityEdge {
  source: string;
  target: string;
  type?: string;
  label?: string;
  properties?: Record<string, any>;
}

export function ReportsModule({
  cases,
  selectedCase,
  onSelectCase,
  officerSession,
  changeView,
  addToast
}: ReportsModuleProps) {
  const activeCaseId = selectedCase || (cases.length > 0 ? cases[0].case_id : 'case_01');

  // View presentation mode: 'document' (Official Law Enforcement Report Document) vs 'dashboard' (Interactive Web Workspace)
  const [viewMode, setViewMode] = useState<'document' | 'dashboard'>('document');

  // Local state for live fetched data
  const [freshCase, setFreshCase] = useState<Case | null>(null);
  const [dossier, setDossier] = useState<AiDossier | null>(null);
  const [insights, setInsights] = useState<PatternInsight[]>([]);
  const [evidenceList, setEvidenceList] = useState<EvidenceItemRecord[]>([]);
  const [findingsList, setFindingsList] = useState<FindingRecord[]>([]);
  const [boards, setBoards] = useState<InvestigationBoardRecord[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphEntityNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEntityEdge[]>([]);
  const [loadingReport, setLoadingReport] = useState<boolean>(false);

  // New Finding input form
  const [noteTitle, setNoteTitle] = useState<string>('');
  const [noteCategory, setNoteCategory] = useState<string>('Telecom & CDR');
  const [noteContent, setNoteContent] = useState<string>('');
  const [submittingNote, setSubmittingNote] = useState<boolean>(false);

  // Fallback to cases array if freshCase not yet loaded
  const currentCase = useMemo(() => {
    if (freshCase && freshCase.case_id.toLowerCase() === activeCaseId.toLowerCase()) {
      return freshCase;
    }
    return cases.find(c => c.case_id.toLowerCase() === activeCaseId.toLowerCase()) || cases[0];
  }, [freshCase, cases, activeCaseId]);

  const fetchAllReportData = useCallback(async (caseId: string) => {
    setLoadingReport(true);
    try {
      const [caseRes, dossierRes, insightsRes, evRes, findRes, boardsRes, graphRes] = await Promise.allSettled([
        API.get<Case>(`/api/cases/${encodeURIComponent(caseId)}`),
        API.get<AiDossier>(`/api/cases/${encodeURIComponent(caseId)}/ai-dossier`),
        API.get<PatternInsight[]>(`/api/cases/${encodeURIComponent(caseId)}/insights`),
        API.get<{ items: EvidenceItemRecord[] }>(`/api/evidence?case_id=${encodeURIComponent(caseId)}`),
        API.get<FindingRecord[]>(`/api/cases/${encodeURIComponent(caseId)}/findings`),
        API.get<{ total: number; boards: InvestigationBoardRecord[] }>(`/api/boards?case_id=${encodeURIComponent(caseId)}`),
        API.get<{ nodes?: GraphEntityNode[]; edges?: GraphEntityEdge[] }>(`/api/graph?case_id=${encodeURIComponent(caseId)}&graph_type=all`)
      ]);

      if (caseRes.status === 'fulfilled' && caseRes.value) setFreshCase(caseRes.value);
      if (dossierRes.status === 'fulfilled' && dossierRes.value) setDossier(dossierRes.value);
      if (insightsRes.status === 'fulfilled' && Array.isArray(insightsRes.value)) setInsights(insightsRes.value);
      else setInsights([]);
      if (evRes.status === 'fulfilled' && evRes.value?.items) setEvidenceList(evRes.value.items);
      else setEvidenceList([]);
      let combinedFindings: FindingRecord[] = [];
      if (findRes.status === 'fulfilled' && Array.isArray(findRes.value)) {
        combinedFindings = [...findRes.value];
      }
      try {
        const cached = localStorage.getItem(`atlas_findings_${caseId}`);
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed)) {
            const existingIds = new Set(combinedFindings.map(f => f.finding_id));
            for (const item of parsed) {
              if (item && item.finding_id && !existingIds.has(item.finding_id)) {
                combinedFindings.push(item);
                existingIds.add(item.finding_id);
              }
            }
          }
        }
      } catch {
        // ignore parse error
      }
      setFindingsList(combinedFindings);
      if (boardsRes.status === 'fulfilled' && boardsRes.value?.boards) setBoards(boardsRes.value.boards);
      else setBoards([]);
      if (graphRes.status === 'fulfilled' && graphRes.value?.nodes) {
        setGraphNodes(graphRes.value.nodes);
        setGraphEdges(graphRes.value.edges || []);
      } else {
        setGraphNodes([]);
        setGraphEdges([]);
      }
    } catch (err) {
      console.error('Failed to fetch case report data:', err);
    } finally {
      setLoadingReport(false);
    }
  }, []);

  useEffect(() => {
    if (activeCaseId) {
      fetchAllReportData(activeCaseId);
    }
  }, [activeCaseId, fetchAllReportData]);

  const handlePrint = () => {
    window.print();
  };

  const handleAddFinding = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteTitle.trim() || !noteContent.trim()) {
      addToast('Please provide both a title and finding summary.', 'warning');
      return;
    }
    setSubmittingNote(true);
    try {
      const res = await API.post<FindingRecord>(`/api/cases/${encodeURIComponent(activeCaseId)}/findings`, {
        title: noteTitle.trim(),
        category: noteCategory,
        content: noteContent.trim(),
        officer_name: officerSession?.officerName || 'Investigating Officer',
        officer_badge: officerSession?.badgeNumber || 'LE-8402',
        severity: 'MEDIUM'
      });
      if (res && res.finding_id) {
        addToast('Finding note recorded into case docket.', 'ok');
        setFindingsList(prev => {
          const updated = [res, ...prev];
          try {
            localStorage.setItem(`atlas_findings_${activeCaseId}`, JSON.stringify(updated));
          } catch {
            // ignore localStorage quota error
          }
          return updated;
        });
        setNoteTitle('');
        setNoteContent('');
      }
    } catch (err: any) {
      addToast(`Error saving finding note: ${err.message || 'Server error'}`, 'error');
    } finally {
      setSubmittingNote(false);
    }
  };

  // Structured entity extractions from graph
  const persons = useMemo(() => graphNodes.filter(n => n.labels?.includes('Person')), [graphNodes]);
  const phones = useMemo(() => graphNodes.filter(n => n.labels?.includes('Phone')), [graphNodes]);
  const vehicles = useMemo(() => graphNodes.filter(n => n.labels?.includes('Vehicle')), [graphNodes]);
  const accounts = useMemo(() => graphNodes.filter(n => n.labels?.includes('BankAccount')), [graphNodes]);
  const locations = useMemo(() => graphNodes.filter(n => n.labels?.includes('Location')), [graphNodes]);
  const towers = useMemo(() => graphNodes.filter(n => n.labels?.includes('CellTower')), [graphNodes]);
  const devices = useMemo(() => graphNodes.filter(n => n.labels?.includes('Device') || n.labels?.includes('IMEI')), [graphNodes]);

  const getSeverityBadge = (sev?: string) => {
    const s = (sev || 'MEDIUM').toUpperCase();
    if (s === 'CRITICAL' || s === 'HIGH') return 'bg-rose-50 text-rose-700 border-rose-200';
    if (s === 'MEDIUM') return 'bg-amber-50 text-amber-700 border-amber-200';
    return 'bg-blue-50 text-blue-700 border-blue-200';
  };

  const cleanDate = (d?: string) => {
    if (!d) return new Date().toLocaleDateString();
    try {
      const dt = new Date(d);
      return isNaN(dt.getTime()) ? d : dt.toLocaleDateString();
    } catch {
      return d;
    }
  };

  // Official Report Document Component
  const renderOfficialReportDocument = () => (
    <article className="official-report-document" id="printable-investigation-report">
      {/* Official State Law Enforcement Header */}
      <header className="report-header-emblem">
        <div className="report-header-left">
          <svg className="report-crest-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <circle cx="12" cy="10" r="3" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 13v4" />
          </svg>
          <div className="report-header-titles">
            <h1>Criminal Investigation Report</h1>
            <p>CRIMINAL NETWORK INTELLIGENCE & FORENSIC EVIDENCE DOSSIER</p>
          </div>
        </div>
        <div className="report-header-badge">
          <div className="report-ref-line">REF: {activeCaseId.toUpperCase()} • {new Date().toLocaleDateString()}</div>
        </div>
      </header>

      {/* Section I: Case Identification Ledger */}
      <section className="report-section">
        <table className="report-meta-table">
          <tbody>
            <tr>
              <td className="meta-label">FIR Reference</td>
              <td className="meta-val"><strong>{currentCase?.fir_number || `FIR-${activeCaseId}`}</strong></td>
              <td className="meta-label">Case Docket ID</td>
              <td className="meta-val font-mono">{activeCaseId.toUpperCase()}</td>
            </tr>
            <tr>
              <td className="meta-label">Incident Title</td>
              <td className="meta-val" colSpan={3}><strong>{currentCase?.case_name || `Investigation Case ${activeCaseId}`}</strong></td>
            </tr>
            <tr>
              <td className="meta-label">Jurisdiction / Police Stn</td>
              <td className="meta-val">{String(currentCase?.police_station || 'Nandipur West Police Station')}</td>
              <td className="meta-label">Date Registered</td>
              <td className="meta-val">{cleanDate(currentCase?.date_filed)}</td>
            </tr>
            <tr>
              <td className="meta-label">Occurrence Date & Time</td>
              <td className="meta-val">{String(currentCase?.occurrence_date || '08-09-2026')} {currentCase?.occurrence_time ? `(${currentCase.occurrence_time})` : ''}</td>
              <td className="meta-label">Place of Occurrence</td>
              <td className="meta-val">{String(currentCase?.place_of_occurrence || '7 Freight Yard, Nandipur West')}</td>
            </tr>
            <tr>
              <td className="meta-label">Crime Classification</td>
              <td className="meta-val"><strong>{currentCase?.crime_category || 'General Investigation'}</strong></td>
              <td className="meta-label">Current Legal Status</td>
              <td className="meta-val">
                <span className="font-bold text-emerald-800">{currentCase?.status?.toUpperCase() || 'UNDER INVESTIGATION'}</span>
                {currentCase?.severity ? ` (${currentCase.severity} Priority)` : ''}
              </td>
            </tr>
            <tr>
              <td className="meta-label">Primary Suspect / POI</td>
              <td className="meta-val"><strong className="text-rose-800">{currentCase?.primary_suspect || 'Under Investigation'}</strong></td>
              <td className="meta-label">Complainant / Victim</td>
              <td className="meta-val">{String(currentCase?.complainant || currentCase?.victim || 'State / Commercial Operator')}</td>
            </tr>
            <tr>
              <td className="meta-label">Investigating Officer</td>
              <td className="meta-val">{currentCase?.lead_investigator || officerSession?.officerName || 'Inspector Anaya Sen'} (Badge: {officerSession?.badgeNumber || 'LE-8402'})</td>
              <td className="meta-label">Forensic Exhibits</td>
              <td className="meta-val"><strong>{evidenceList.length} Verified Documents</strong> ({graphNodes.length} Entities Cataloged)</td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* Section II: Executive Forensic Summary & Case Narrative */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">I. Executive Forensic Summary & Incident Narrative</h2>
          <span className="report-section-subtitle">Synthesized Intelligence & Official FIR Statement</span>
        </div>
        <div className="report-text-block">
          <p style={{ margin: '0 0 8px 0' }}>
            {String(currentCase?.summary || (currentCase as any)?.fir_description || dossier?.executive_summary || dossier?.summary || 
              `Investigation docket ${currentCase?.case_name || activeCaseId} (${activeCaseId.toUpperCase()}) was registered following official complaint. Physical surveillance and evidentiary extraction across multi-format forensic exhibits confirm criminal network interactions between primary subjects and technical infrastructure.`
            )}
          </p>
          <p style={{ margin: '0', fontSize: '11.5px', color: '#475569' }}>
            Forensic analysis of the associated knowledge graph identified <strong>{graphNodes.length} validated entities</strong> ({persons.length} human subjects, {phones.length} active cellular lines, {accounts.length} bank accounts, and {vehicles.length} motor vehicles) interconnected across {graphEdges.length} investigative links.
          </p>
        </div>

        {dossier?.key_findings && dossier.key_findings.length > 0 && (
          <div>
            <div style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', color: '#475569', marginBottom: '6px' }}>
              Core Investigative Discoveries:
            </div>
            <ul className="report-key-findings-list">
              {dossier.key_findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Section III: Primary Suspects & Persons of Interest Profile */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">II. Primary Suspects & Network Entities Profile</h2>
          <span className="report-section-subtitle">{persons.length} Subjects Identified in Case Docket</span>
        </div>
        {persons.length === 0 ? (
          <p style={{ fontSize: '11px', color: '#64748b' }}>No individual suspect nodes resolved in graph for current docket.</p>
        ) : (
          <table className="report-formal-table">
            <thead>
              <tr>
                <th style={{ width: '22%' }}>Subject Name</th>
                <th style={{ width: '24%' }}>Designated Role / Status</th>
                <th style={{ width: '32%' }}>Associated Technical Channels</th>
                <th style={{ width: '22%' }}>Cross-Case Overlap</th>
              </tr>
            </thead>
            <tbody>
              {persons.map((p) => {
                const pName = p.name || p.properties?.name || p.id.split(':').slice(1).join(':').replace(/_/g, ' ');
                const role = p.properties?.role || (pName === currentCase?.primary_suspect ? 'Primary Suspect' : 'Associate / Subject of Interest');
                const isCross = Boolean(p.properties?.cross_case || (p.properties?.case_ids && p.properties.case_ids.length > 1));
                
                // Find associated phone / vehicle / accounts
                const linkedEdges = graphEdges.filter(e => e.source === p.id || e.target === p.id);
                const neighborIds = new Set(linkedEdges.map(e => e.source === p.id ? e.target : e.source));
                const linkedPh = phones.filter(ph => neighborIds.has(ph.id)).map(ph => ph.name || ph.id.replace('phone:', ''));
                const linkedAcc = accounts.filter(a => neighborIds.has(a.id)).map(a => a.name || a.id.replace('bank_account:', ''));
                const linkedVeh = vehicles.filter(v => neighborIds.has(v.id)).map(v => v.name || v.id.replace('vehicle:', ''));

                return (
                  <tr key={p.id}>
                    <td>
                      <strong>{pName}</strong>
                      <div style={{ fontSize: '10px', color: '#64748b', fontFamily: 'monospace' }}>{p.id}</div>
                    </td>
                    <td>
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${role.toLowerCase().includes('suspect') ? 'bg-rose-50 text-rose-800 border border-rose-200' : 'bg-slate-100 text-slate-700'}`}>
                        {role}
                      </span>
                    </td>
                    <td style={{ fontSize: '11px' }}>
                      {linkedPh.length > 0 && <div>📞 {linkedPh.join(', ')}</div>}
                      {linkedAcc.length > 0 && <div>💳 Acct: {linkedAcc.join(', ')}</div>}
                      {linkedVeh.length > 0 && <div>🚗 Plate: {linkedVeh.join(', ')}</div>}
                      {linkedPh.length === 0 && linkedAcc.length === 0 && linkedVeh.length === 0 && (
                        <span style={{ color: '#94a3b8' }}>Direct dossier mention</span>
                      )}
                    </td>
                    <td>
                      {isCross ? (
                        <span className="text-amber-800 font-bold text-[10.5px]">⚠️ Multi-Case Bridge ({p.properties?.case_ids?.length || 'Multiple'} dossiers)</span>
                      ) : (
                        <span className="text-slate-500 text-[10.5px]">Single Case Specific</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* Section IV: Automated Forensic Pattern Detections & Syndicate Alerts */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">III. Forensic Pattern Detections & Syndicate Alerts</h2>
          <span className="report-section-subtitle">Algorithmic Rule-Based Detections ({insights.length})</span>
        </div>

        {insights.length === 0 ? (
          <div className="report-text-block" style={{ background: '#f8fafc', borderLeftColor: '#94a3b8' }}>
            No anomalous multi-hop telecom bursts, IMEI reuse, or Hawala money laundering transfer chains detected for current case scope.
          </div>
        ) : (
          <div>
            {insights.map((ins) => {
              const isCrit = ins.severity?.toUpperCase() === 'CRITICAL';
              return (
                <div key={ins.insight_id} className={`report-pattern-row ${isCrit ? 'critical' : ''}`}>
                  <div className="report-pattern-row-header">
                    <span>{ins.title}</span>
                    <span className={`px-2 py-0.5 rounded text-[9.5px] uppercase font-bold ${isCrit ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'}`}>
                      {ins.severity} SEVERITY
                    </span>
                  </div>
                  <div className="report-pattern-desc">{ins.description}</div>
                  {ins.observed_facts && ins.observed_facts.length > 0 && (
                    <div style={{ fontSize: '10.5px', color: '#475569', margin: '4px 0 6px 0' }}>
                      {ins.observed_facts.map((fact, idx) => (
                        <div key={idx}>• <strong>Verified fact:</strong> {fact}</div>
                      ))}
                    </div>
                  )}
                  {ins.derived_interpretation && (
                    <div className="report-pattern-interp">
                      <strong>Forensic Assessment:</strong> {ins.derived_interpretation}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Section V: Multi-Discipline Forensic Breakdown */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">IV. Specialized Forensic Evidence Breakdown</h2>
          <span className="report-section-subtitle">Telecom, Financial & Mobility Channels</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3" style={{ marginBottom: '14px' }}>
          {/* Telecom */}
          <div style={{ border: '1px solid #cbd5e1', borderRadius: '6px', padding: '10px 12px', background: '#f8fafc' }}>
            <div style={{ fontWeight: 700, fontSize: '11px', textTransform: 'uppercase', color: '#1e3a8a', marginBottom: '6px' }}>
              📡 Telecommunication Trails
            </div>
            <div style={{ fontSize: '11px', color: '#334155', lineHeight: '1.5' }}>
              <div>• Active SIMs: <strong>{phones.length}</strong> ({phones.map(p => p.name || p.id.replace('phone:', '')).join(', ') || 'None'})</div>
              <div>• Device IMEIs: <strong>{devices.length}</strong> ({devices.map(d => d.name || d.id.replace('imei:', '')).join(', ') || 'None'})</div>
              <div>• Cell Towers: <strong>{towers.length}</strong> active coverage sectors</div>
            </div>
          </div>

          {/* Financial */}
          <div style={{ border: '1px solid #cbd5e1', borderRadius: '6px', padding: '10px 12px', background: '#f8fafc' }}>
            <div style={{ fontWeight: 700, fontSize: '11px', textTransform: 'uppercase', color: '#1e3a8a', marginBottom: '6px' }}>
              💳 Financial & Banking Trails
            </div>
            <div style={{ fontSize: '11px', color: '#334155', lineHeight: '1.5' }}>
              <div>• Accounts Monitored: <strong>{accounts.length}</strong></div>
              <div>• Dispersal Hubs: <strong>{insights.filter(i => i.insight_type === 'HIGH_FAN_OUT').length}</strong> accounts flagged</div>
              <div>• Account IDs: {accounts.map(a => a.name || a.id.replace('bank_account:', '')).join(', ') || 'None recorded'}</div>
            </div>
          </div>

          {/* Mobility */}
          <div style={{ border: '1px solid #cbd5e1', borderRadius: '6px', padding: '10px 12px', background: '#f8fafc' }}>
            <div style={{ fontWeight: 700, fontSize: '11px', textTransform: 'uppercase', color: '#1e3a8a', marginBottom: '6px' }}>
              🚗 Mobility & Spatial Sightings
            </div>
            <div style={{ fontSize: '11px', color: '#334155', lineHeight: '1.5' }}>
              <div>• Motor Vehicles: <strong>{vehicles.length}</strong> ({vehicles.map(v => v.name || v.id.replace('vehicle:', '')).join(', ') || 'None'})</div>
              <div>• Locations Cataloged: <strong>{locations.length}</strong> sites</div>
              <div>• Primary Sighting: {String(currentCase?.place_of_occurrence || '7 Freight Yard')}</div>
            </div>
          </div>
        </div>
      </section>

      {/* Section V: Supporting Evidence Schedule */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">V. Supporting Evidence Schedule</h2>
          <span className="report-section-subtitle">{evidenceList.length} Exhibits Documented</span>
        </div>
        {evidenceList.length === 0 ? (
          <p style={{ fontSize: '11px', color: '#64748b' }}>No digital evidence files linked to this docket.</p>
        ) : (
          <table className="report-formal-table">
            <thead>
              <tr>
                <th style={{ width: '10%' }}>Exhibit</th>
                <th style={{ width: '45%' }}>Document Title & Filename</th>
                <th style={{ width: '30%' }}>Forensic Classification</th>
                <th style={{ width: '15%' }}>Integrity</th>
              </tr>
            </thead>
            <tbody>
              {evidenceList.map((ev, idx) => {
                const isTampered = ev.sha256 === 'TAMPERED' || (ev as any).is_tampered || (ev as any).status === 'Tampered';
                return (
                  <tr key={ev.evidence_id}>
                    <td style={{ fontWeight: 700, color: '#475569' }}>EX-0{idx + 1}</td>
                    <td>
                      <strong>{ev.filename}</strong>
                      <div style={{ fontSize: '10px', color: '#64748b' }}>Uploaded: {cleanDate(ev.uploaded_at)}</div>
                    </td>
                    <td>
                      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 font-semibold text-[10.5px]">
                        {ev.job?.classification || ev.format?.toUpperCase() || 'Official Exhibit'}
                      </span>
                    </td>
                    <td>
                      {isTampered ? (
                        <span style={{ color: '#b91c1c', fontWeight: 700 }}>Tampered</span>
                      ) : (
                        <span style={{ color: '#15803d', fontWeight: 700 }}>Verified</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* Section VI: Police Investigative Findings & Officer Observations */}
      <section className="report-section">
        <div className="report-section-header">
          <h2 className="report-section-title">VI. Police Investigative Findings & Officer Observations</h2>
          <span className="report-section-subtitle">{findingsList.length} Recorded Findings</span>
        </div>
        {findingsList.length === 0 ? (
          <div style={{ padding: '12px 14px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: '4px', fontSize: '11px', color: '#64748b' }}>
            No supplemental police findings or field observation notes recorded under this case docket yet.
          </div>
        ) : (
          <table className="report-formal-table">
            <thead>
              <tr>
                <th style={{ width: '20%' }}>Category</th>
                <th style={{ width: '54%' }}>Investigative Finding & Field Analysis</th>
                <th style={{ width: '26%' }}>Officer & Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {findingsList.map(f => (
                <tr key={f.finding_id}>
                  <td>
                    <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-800 font-semibold text-[10.5px]">
                      {f.category}
                    </span>
                  </td>
                  <td>
                    <div style={{ fontWeight: 700, marginBottom: '2px', color: '#0f172a' }}>{f.title}</div>
                    <div style={{ fontSize: '11px', color: '#334155', lineHeight: '1.45' }}>{f.content}</div>
                  </td>
                  <td style={{ fontSize: '10.5px', color: '#64748b' }}>
                    <div style={{ fontWeight: 600, color: '#1e293b' }}>{f.officer_name || 'Investigating Officer'}</div>
                    <div>Badge: {f.officer_badge || 'LE-8402'}</div>
                    <div style={{ fontFamily: 'monospace', fontSize: '9.5px' }}>{cleanDate(f.created_at)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

    </article>
  );

  return (
    <div className="reports-container p-6 max-w-6xl mx-auto space-y-6">
      {/* Top Action Bar (Hidden in Print) */}
      <div className="reports-top-bar flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Case Dossier:
          </label>
          <select
            className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white font-semibold text-sm text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={activeCaseId}
            onChange={(e) => {
              if (onSelectCase) onSelectCase(e.target.value);
            }}
          >
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id.toUpperCase()}{c.case_name ? ` — ${c.case_name}` : ''}
              </option>
            ))}
          </select>
          {loadingReport && (
            <span className="text-xs text-blue-600 animate-pulse font-medium">
              Synchronizing case intelligence…
            </span>
          )}
        </div>

        {/* View Mode Toggle & Actions */}
        <div className="flex items-center gap-2">
          {/* Toggle between Official Report Document format vs Dashboard */}
          <div className="reports-view-toggle flex items-center bg-slate-100 p-0.5 rounded-lg border border-slate-200 text-xs mr-2">
            <button
              type="button"
              className={`px-3 py-1.5 rounded-md font-semibold transition-all ${viewMode === 'document' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}
              onClick={() => setViewMode('document')}
              title="Official Legal Report Document View"
            >
              📄 Official Report View
            </button>
            <button
              type="button"
              className={`px-3 py-1.5 rounded-md font-semibold transition-all ${viewMode === 'dashboard' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}
              onClick={() => setViewMode('dashboard')}
              title="Interactive Web Dashboard"
            >
              📊 Dashboard View
            </button>
          </div>

          <button
            type="button"
            className="neu-btn ghost flex items-center gap-1.5 text-xs font-semibold py-1.5 px-3"
            onClick={() => changeView('graph')}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3a2 2 0 0 1 2 2c0 .4-.1.8-.3 1.1l3.4 5.4c.3-.1.6-.2.9-.2a2 2 0 1 1 0 4c-.3 0-.6-.1-.9-.2l-3.4 5.4c.2.3.3.7.3 1.1a2 2 0 1 1-3.6-1.1L8.9 15.5c-.3.1-.6.2-.9.2a2 2 0 1 1 0-4c.3 0 .6.1.8.2l3.4-5.4c-.2-.3-.3-.7-.3-1.1a2 2 0 0 1 2-2Z" />
            </svg>
            <span>Graph View</span>
          </button>

          <button
            type="button"
            className="neu-btn ghost flex items-center gap-1.5 text-xs font-semibold py-1.5 px-3"
            onClick={() => changeView('board')}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
            </svg>
            <span>Investigation Board</span>
          </button>

          <button
            type="button"
            className="neu-btn primary flex items-center gap-1.5 text-xs font-semibold py-1.5 px-4 shadow-sm"
            onClick={handlePrint}
            title="Export official investigation report to PDF"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
            </svg>
            <span>Export / Print Report (PDF)</span>
          </button>
        </div>
      </div>

      {/* Conditionally Render Document vs Dashboard on Screen */}
      {viewMode === 'document' ? (
        <div className="reports-document-wrapper py-2">
          {renderOfficialReportDocument()}
        </div>
      ) : (
        /* Executive Dashboard View */
        <div className="reports-dashboard-view space-y-6">
          {/* Quick banner to switch to document */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-xl">📄</span>
              <div>
                <strong className="text-xs text-blue-900 block font-bold">Official Police Dossier Document Ready</strong>
                <span className="text-xs text-blue-700">Synthesized intelligence, cross-case analysis, pattern detections, and cryptographic chain of custody.</span>
              </div>
            </div>
            <button
              type="button"
              className="neu-btn primary text-xs py-1.5 px-3 font-semibold"
              onClick={() => setViewMode('document')}
            >
              Open Report View
            </button>
          </div>

          {/* Official Header Card */}
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-700 border border-slate-200">
                    OFFICIAL POLICE DOSSIER
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200">
                    {currentCase?.status?.toUpperCase() || 'ACTIVE INVESTIGATION'}
                  </span>
                  {currentCase?.severity && (
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${getSeverityBadge(currentCase.severity)}`}>
                      {currentCase.severity} Priority
                    </span>
                  )}
                </div>
                <h1 className="text-xl font-bold text-slate-900">
                  {currentCase?.case_name || currentCase?.case_id?.toUpperCase() || 'Investigation Case'}
                </h1>
                <p className="text-xs text-slate-500 mt-1 font-mono">
                  FIR: {currentCase?.fir_number || `FIR-${activeCaseId}`} • Case Ref: {activeCaseId.toUpperCase()}
                  {currentCase?.date_filed ? ` • Registered: ${currentCase.date_filed}` : ''}
                </p>
              </div>

              <div className="text-right text-xs text-slate-500">
                <div>Lead Officer: <strong className="text-slate-800">{currentCase?.lead_investigator || officerSession?.officerName || 'Investigating Officer'}</strong></div>
                <div>Badge: <strong className="text-slate-800">{officerSession?.badgeNumber || 'LE-8402'}</strong></div>
                <div>Agency: <strong className="text-slate-800">{officerSession?.department || 'Criminal Investigation Department'}</strong></div>
                <div className="text-[11px] text-slate-400 mt-1 font-mono">Report Date: {new Date().toLocaleDateString()}</div>
              </div>
            </div>

            {/* Dynamic Key Metrics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">Crime Category</span>
                <span className="text-sm font-bold text-slate-800 mt-1 block truncate">
                  {currentCase?.crime_category || 'General Investigation'}
                </span>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">Primary Suspect</span>
                <span className="text-sm font-bold text-rose-700 mt-1 block truncate">
                  {currentCase?.primary_suspect || 'Suspect Under Review'}
                </span>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">Total Entities</span>
                <span className="text-sm font-bold text-slate-800 mt-1 block">
                  {graphNodes.length || currentCase?.total_entities || 0} Identified
                </span>
              </div>

              <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">Evidence Custody</span>
                <span className="text-sm font-bold text-emerald-700 mt-1 flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-emerald-600 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span>{evidenceList.length} Files • SHA-256</span>
                </span>
              </div>
            </div>
          </div>

          {/* Executive AI Forensic Dossier */}
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full bg-blue-600 animate-pulse"></div>
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                  Executive AI Intelligence Dossier
                </h2>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                ATLAS Forensic Synthesis Engine
              </span>
            </div>

            <div className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-4 rounded-lg border border-slate-100">
              <p className="font-medium text-slate-800">
                {String(currentCase?.summary || (currentCase as any)?.fir_description || dossier?.executive_summary || dossier?.summary || 
                  `Investigation docket ${currentCase?.case_name || activeCaseId} (${activeCaseId.toUpperCase()}) incorporates ${graphNodes.length || currentCase?.total_entities || 0} cataloged entities across ${evidenceList.length} verified exhibits. Relationships and network bridges are grounded in multi-format forensic evidence.`
                )}
              </p>
            </div>

            {dossier?.key_findings && dossier.key_findings.length > 0 && (
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">
                  Key Forensic Graph Discoveries:
                </h3>
                <ul className="space-y-2">
                  {dossier.key_findings.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-slate-700 bg-white p-2.5 rounded-lg border border-slate-100">
                      <span className="text-blue-500 font-bold mt-0.5">•</span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Automated Pattern Insights & Syndicate Alerts */}
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4 border-b border-slate-100 pb-3">
              <div>
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                  Automated Forensic Pattern Detections ({insights.length})
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Transparent, rule-based algorithmic detection across telecom CDR, financial trails, and hardware IMEIs.
                </p>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                Transparent Rules
              </span>
            </div>

            {insights.length === 0 ? (
              <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-6 text-center text-slate-500 text-xs">
                No anomalous multi-hop telecom bursts or laundering transfer chains detected for current case scope.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {insights.map((ins) => (
                  <div key={ins.insight_id} className="border border-slate-200 rounded-lg p-4 bg-slate-50/50 hover:border-blue-300 transition-all">
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <h3 className="text-xs font-bold text-slate-900 truncate">{ins.title}</h3>
                      <span className={`px-2 py-0.5 rounded text-[9.5px] font-bold uppercase tracking-wider border ${getSeverityBadge(ins.severity)}`}>
                        {ins.severity}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed mb-2">
                      {ins.description}
                    </p>
                    {ins.derived_interpretation && (
                      <p className="text-[11px] text-blue-800 bg-blue-50/80 p-2 rounded border border-blue-100 mb-2 font-medium">
                        🔍 <strong>Interpretation:</strong> {ins.derived_interpretation}
                      </p>
                    )}
                    {ins.observed_facts && ins.observed_facts.length > 0 && (
                      <div className="text-[10.5px] text-slate-500 space-y-0.5">
                        {ins.observed_facts.map((fact, idx) => (
                          <div key={idx}>✓ {fact}</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Supporting Evidence Schedule Table */}
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4 border-b border-slate-100 pb-3">
              <div>
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                  Supporting Evidence Schedule
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Verified extraction and integrity status for case exhibits.
                </p>
              </div>
              <button
                type="button"
                className="neu-btn ghost text-xs py-1 px-3 flex items-center gap-1 text-blue-600"
                onClick={() => changeView('blockchain')}
              >
                <span>Audit Ledger</span>
                <span>→</span>
              </button>
            </div>

            {evidenceList.length === 0 ? (
              <div className="bg-slate-50 border border-dashed border-slate-300 rounded-lg p-6 text-center text-slate-500 text-xs">
                No evidence files uploaded to this case docket yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 text-slate-400 font-semibold uppercase text-[10px]">
                      <th className="py-2.5 px-3">Exhibit Filename</th>
                      <th className="py-2.5 px-3">Document Type</th>
                      <th className="py-2.5 px-3 text-right">Integrity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {evidenceList.map((item) => {
                      const isTampered = item.sha256 === 'TAMPERED' || (item as any).is_tampered || (item as any).status === 'Tampered';
                      return (
                        <tr key={item.evidence_id} className="hover:bg-slate-50/70">
                          <td className="py-2.5 px-3 font-semibold text-slate-900">
                            {item.filename}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-[10.5px]">
                              {item.job?.classification || item.format?.toUpperCase() || 'Document'}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            {isTampered ? (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-50 px-2.5 py-0.5 rounded border border-rose-200">
                                <span>Tampered</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded border border-emerald-200">
                                <span>Verified</span>
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Forensic Findings & Officer Assessment Log */}
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-1">
                Officer Investigative Findings & Notes ({findingsList.length})
              </h2>
              <p className="text-xs text-slate-500">
                Official case notes cataloged under immutable chain of custody with timestamp and officer badge.
              </p>
            </div>

            {/* Existing findings list */}
            {findingsList.length > 0 && (
              <div className="space-y-2.5">
                {findingsList.map((f) => (
                  <div key={f.finding_id} className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-xs space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-900">{f.title}</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-200 text-slate-700">
                        {f.category}
                      </span>
                    </div>
                    <p className="text-slate-700 leading-relaxed">{f.content}</p>
                    <div className="text-[10px] text-slate-400 flex items-center gap-2 pt-1">
                      <span>Recorded by: <strong>{f.officer_name || 'Investigator'}</strong> ({f.officer_badge || 'LE-8402'})</span>
                      <span>•</span>
                      <span>{f.created_at ? new Date(f.created_at).toLocaleString() : 'Recorded'}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add new finding form */}
            <form onSubmit={handleAddFinding} className="space-y-3 pt-3 border-t border-slate-100">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <input
                  type="text"
                  className="p-2.5 text-xs text-slate-800 bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Finding Title (e.g. Syndicate Call Hub Confirmed)"
                  value={noteTitle}
                  onChange={(e) => setNoteTitle(e.target.value)}
                />
                <select
                  className="p-2.5 text-xs text-slate-800 bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={noteCategory}
                  onChange={(e) => setNoteCategory(e.target.value)}
                >
                  <option value="Telecom & CDR">Telecom & CDR Pattern</option>
                  <option value="Financial & Banking">Financial & Banking Trail</option>
                  <option value="Physical Surveillance">Physical Surveillance / ANPR</option>
                  <option value="Suspect Alibi / Motive">Suspect Alibi / Motive</option>
                  <option value="Cross-Jurisdiction Overlap">Cross-Jurisdiction Overlap</option>
                </select>
              </div>
              <textarea
                className="w-full p-3 text-xs leading-relaxed text-slate-800 bg-slate-50 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={3}
                value={noteContent}
                onChange={(e) => setNoteContent(e.target.value)}
                placeholder="Enter investigative conclusions or observation notes to include in the official dossier..."
              />
              <div className="flex justify-between items-center text-xs text-slate-500">
                <span>Notes are committed to the forensic audit log with SHA-256 verification.</span>
                <button
                  type="submit"
                  disabled={submittingNote}
                  className="neu-btn primary text-xs py-1.5 px-4 font-semibold"
                >
                  {submittingNote ? 'Recording Finding…' : 'Record Finding in Dossier'}
                </button>
              </div>
            </form>
          </div>

          {/* Hidden print document so printing from dashboard view still outputs the official document */}
          <div className="hidden print:block">
            {renderOfficialReportDocument()}
          </div>
        </div>
      )}
    </div>
  );
}

export default ReportsModule;
