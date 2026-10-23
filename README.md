# ATLAS — AI-Powered Criminal Network Analysis System

ATLAS is an investigation-intelligence platform designed to transform fragmented case evidence into a connected, explainable knowledge graph.

It ingests heterogeneous evidence such as FIRs, police reports, CDRs, financial records, witness statements, forensic reports, vehicle/device records and intelligence notes; extracts and resolves entities; detects cross-case relationships; and provides graph-based investigative analysis with source provenance and integrity tracking.

> **Goal:** Turn disconnected investigation records into evidence-backed, searchable and explainable intelligence while keeping the investigator in control.

## Core Capabilities

- **Case & Evidence Management** — Create investigation cases and upload case-wise evidence in PDF, CSV, XLSX and text formats.
- **Document Intelligence** — Extract text from digital/scanned documents, parse spreadsheets and normalize identifiers.
- **Entity Intelligence** — Detect persons, phones, IMEIs, vehicles, accounts, locations and organizations with source provenance.
- **Entity Resolution** — Reconcile aliases, spelling variants and duplicate identities using exact identifiers and contextual similarity.
- **Knowledge Graph** — Build and explore relationships between entities, cases and evidence using Neo4j with an in-memory graph engine for analysis.
- **Cross-Case Intelligence** — Detect shared entities and identifiers across previously isolated investigations.
- **Network Analytics** — Degree, PageRank, betweenness, shortest-path and pattern analysis for investigative prioritization.
- **Entity Search & Profiles** — Search identifiers globally and inspect connected evidence and one-hop relationships.
- **Investigation Board** — Manually organize entities, notes, evidence and hypotheses without modifying the system-generated graph.
- **AI Investigation Assistant** — Ask natural-language questions over available graph/evidence context and generate evidence-grounded investigative summaries.
- **Evidence Integrity** — SHA-256 hashing, tamper-evident audit-chain verification, access timelines and chain-of-custody certificates.
- **Reports & Findings** — Maintain investigator findings and generate case-oriented analytical outputs.

## Architecture

```text
Investigator Interface
React + TypeScript + Vite
          │
          ▼
FastAPI Application Layer
          │
 ┌────────┼───────────────┐
 ▼        ▼               ▼
PostgreSQL /         Neo4j Graph      Evidence Store
Supabase             + NetworkX       Original Files
Operational Data     Analytics        + SHA-256
          │
          ▼
Document & Entity Intelligence
OCR • Parsing • Normalization • Entity Resolution
          │
          ▼
Cross-Case & Network Analytics
          │
          ▼
Evidence-Backed Investigator Outputs
```

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, vis-network, React Flow |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy |
| Operational Database | PostgreSQL / Supabase |
| Graph Intelligence | Neo4j, Cypher, NetworkX |
| Document Processing | PyMuPDF, pypdf, OpenPyXL, Tesseract OCR |
| Entity Resolution | RapidFuzz, phonenumbers, rule/context-based matching |
| Retrieval | Upstash Vector |
| Local AI Support | Ollama |
| Security & Integrity | JWT, RBAC, SHA-256, tamper-evident audit chain |

## Project Structure

```text
AI-Powered-Criminal-Network-Analysis/
├── backend/                 # FastAPI APIs, database, auth, analytics, integrity
├── member1/                 # React investigator interface
├── member3/                 # Document processing and entity intelligence
├── member4/                 # Knowledge-graph / analytics modules
├── member5/                 # Investigation assistant
├── data/                    # Evidence storage and integrity receipts
├── scripts/                 # Dataset / ingestion utilities
├── requirements.txt
├── run.py
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL/Supabase database
- Tesseract OCR for scanned documents
- Neo4j 5+ for persistent graph storage *(optional; ATLAS can use its in-memory graph engine)*
- Ollama *(optional, for local model inference)*

### 1. Clone

```bash
git clone https://github.com/Kesa799/AI-Powered-Criminal-Network-Analysis.git
cd AI-Powered-Criminal-Network-Analysis
```

### 2. Install Backend Dependencies

```bash
python -m venv .venv
```

**Windows**

```bash
.venv\Scripts\activate
```

**Linux / macOS**

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Create a `.env` file in the project root.

```env
SECRET_KEY=change_this_secret

DATABASE_URL=postgresql://user:password@host:5432/database
SUPABASE_PASSWORD=your_database_password

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j

UPSTASH_URL=
UPSTASH_TOKEN=

OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b

ATLAS_REQUIRE_TESSERACT=true
SEED_SAMPLE_DATA=false
```

> Keep secrets out of Git. Do not commit `.env`.

### 4. Build the Frontend

```bash
cd member1
npm install
npm run build
cd ..
```

### 5. Run ATLAS

```bash
python run.py
```

Open:

- **Application:** `http://127.0.0.1:8000`
- **Swagger API Docs:** `http://127.0.0.1:8000/docs`
- **Health Check:** `http://127.0.0.1:8000/api/health`

## Investigation Workflow

```text
Case Creation
    ↓
Evidence Upload
    ↓
OCR / Parsing / Normalization
    ↓
Entity & Event Extraction
    ↓
Entity Resolution
    ↓
Knowledge Graph Update
    ↓
Cross-Case & Network Analytics
    ↓
Graph Explorer / Alerts / Reports / Investigation Board
```

Every derived entity or finding is designed to remain linked to its supporting source evidence.

## Privacy & Deployment Direction

ATLAS is designed toward privacy-sensitive deployment for investigative environments:

- case-scoped access and role-based controls
- cryptographic evidence integrity
- source-linked analytical provenance
- local model support
- container/on-premise deployment path
- investigator verification for uncertain analytical outputs

The prototype demonstrates the end-to-end investigation workflow; production deployment requires additional security hardening, encryption-at-rest, hardened identity management and infrastructure controls.

## Dataset

The repository includes synthetic multi-case investigation data for development and validation. The dataset is designed to contain hidden cross-case relationships so that entity resolution and graph analytics must discover the links from the evidence rather than from a pre-supplied ground-truth list.

**No real police or personally identifiable investigation data is required for the demo dataset.**

---

**Team Novelex**  
Seva First Innovation Challenge 2026
