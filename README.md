# ATLAS — Criminal Intelligence & Forensic Network Analysis System

**ATLAS** is an advanced, enterprise-grade criminal investigation and link-analysis intelligence platform. It ingests complex, multi-source, multi-format investigative evidence (scanned PDF FIRs, Call Detail Records (CDRs), bank transaction spreadsheets, cell tower location logs, and field reports), deterministically extracts and normalizes entities, computes provenance citations, detects cross-case overlaps, and visualizes criminal syndicates via an interactive knowledge graph with an autonomous AI copilot.

---

## 🏗️ System Architecture & Integrated Modules

```
+-----------------------------------------------------------------------------------------+
|                        MEMBER 1: FRONTEND & INVESTIGATION WORKSPACE                     |
|      React 19 | TypeScript | Vite | Vis.js Network Studio | ForceAtlas2 | Responsive    |
+-----------------------------------------------------------------------------------------+
                                             ▲
                                             │ HTTP REST / WebSocket (/api/*)
                                             ▼
+-----------------------------------------------------------------------------------------+
|                MEMBER 2: BACKEND, DATABASE & APPLICATION CORE (THIS SERVICE)            |
|       FastAPI App | PostgreSQL (Supabase) | Upstash Vector | JWT RBAC | Audit Ledger    |
+-----------------------------------------------------------------------------------------+
       │                                     │                                    │
       ▼                                     ▼                                    ▼
+-----------------------+   +---------------------------------+   +-----------------------+
|  MEMBER 3: EXTRACTION |   |  MEMBER 4: KNOWLEDGE GRAPH      |   |  MEMBER 5: AI COPILOT |
|  SFIC Document Module |   |  KnowledgeGraphEngine, Neo4j,   |   |  Vector RAG Search,   |
|  Dual-Path OCR & YAML,|   |  In-Memory Fast Engine,         |   |  Natural Language     |
|  Provenance Quotation,|   |  Centrality (PageRank/Between), |   |  Graph Inferences,    |
|  Anti-Prompt-Injection|   |  Cypher Script Exporters        |   |  Dossier Generation   |
+-----------------------+   +---------------------------------+   +-----------------------+
```

---

## 🚀 Setup & Installation Instructions

Follow these step-by-step instructions to set up, configure, and launch ATLAS locally or on a server.

### 1. Prerequisites
Ensure you have the following installed on your system:
- **Python 3.10+** (Tested on Python 3.11 and 3.13)
- **Node.js 18+** and **npm** (Required to compile frontend assets)
- **Git**
- *(Optional)* **Tesseract OCR** (If processing raw scanned images offline without cloud OCR)
- *(Optional)* **Neo4j 5+** (Optional: the backend automatically uses its high-performance in-memory graph engine if Neo4j is offline)
- *(Optional)* **Ollama** (If running offline local LLMs such as `qwen2.5:3b`)

---

### 2. Clone the Repository

```bash
git clone https://github.com/Kesa799/AI-Powered-Criminal-Network-Analysis.git
cd AI-Powered-Criminal-Network-Analysis
```

---

### 3. Configure Environment Variables

Copy the sample environment file to create your local `.env`:

```bash
# On Linux / macOS:
cp .env.example .env

# On Windows (PowerShell):
Copy-Item .env.example .env
```

Open `.env` in your text editor and configure your secrets and services:

```ini
# General Runtime
ENVIRONMENT=development
SECRET_KEY=your_secure_jwt_random_secret_here

# PostgreSQL / Supabase Connection
DATABASE_URL=postgresql://user:password@host:5432/dbname
SUPABASE_PASSWORD=your_database_password

# Upstash Vector (For forensic document RAG)
UPSTASH_URL=https://your-database-id-vector.upstash.io
UPSTASH_TOKEN=your_upstash_token_here

# LLM Extraction Provider (Groq, OpenAI, or Mock)
GROQ_API_KEY=gsk_your_groq_api_key
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-120b

# Output token ceiling per extraction call. Without it the provider truncates
# the generated JSON mid-object and reports the truncation as a schema error.
LLM_MAX_COMPLETION_TOKENS=8192

# Client-side pacing so the provider's token-per-minute budget is not exceeded
LLM_MAX_REQUESTS_PER_MINUTE=1
LLM_MIN_INTERVAL_S=60

# Graph & Pipeline Configuration
SEED_SAMPLE_DATA=false
ATLAS_SYNTHETIC_ONLY=false
# Tesseract is required for scanned evidence. The binary is discovered
# automatically (Program Files, %LOCALAPPDATA%\Programs, or PATH).
ATLAS_REQUIRE_TESSERACT=true
```

> **Verified model:** `openai/gpt-oss-120b` is the model confirmed working with ATLAS's strict
> `json_schema` extraction contract on Groq. Two provider-side constraints decide this:
>
> - Groq's default `max_completion_tokens` truncates the generated JSON mid-object and
>   reports the truncation as HTTP 400 `json_validate_failed`. Setting
>   `LLM_MAX_COMPLETION_TOKENS` fixes it.
> - Groq enforces a 1000 output-token/minute ceiling on `qwen/qwen3.8-27b`. At the
>   default chunk size that model's extractions exceed the ceiling and the provider
>   rejects the request outright; with `LLM_MAX_COMPLETION_TOKENS=1000` and a smaller
>   `LLM_CHUNK_CHARS` it becomes usable as a second worker.
> - The tier allows 8000 tokens/minute and one extraction costs 2500-4700 tokens, so two
>   calls inside the same window are refused. Calls are therefore spaced 60s apart
>   (`LLM_MIN_INTERVAL_S=60`), which keeps at most one call's tokens in any window.
>
> See `member3/SFIC_Doc_Module/docs/DECISIONS.md` (DEC-036) for the full verification
> matrix and the measured rate-limit envelope.

> **Daily budget.** On top of the per-minute limits above, the Groq free tier allows
> **200,000 tokens per day per model** - each model on the account has its own allowance,
> and the allowance refills at 200,000 tokens per 24 hours (about 2.31 tokens/second). The
> adapter fails fast on that refusal (DEC-039) and the bulk ingest paces itself to the
> provider's own retry hint, so an exhausted budget costs time, never data. Because the
> budget is per model, running one API instance per model multiplies the daily throughput
> of a single key (DEC-040).

---

### 4. Set Up the Python Virtual Environment & Backend Dependencies

It is recommended to use a virtual environment:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment:
# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# On Windows (Command Prompt):
.venv\Scripts\activate.bat
```

Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

---

### 5. Install Frontend Dependencies & Build Assets

The frontend is built with React 19, Vite, and Vis.js in the `member1` folder. Build the production bundle so FastAPI can serve it statically:

```bash
# Navigate to the frontend directory
cd member1

# Install node dependencies
npm install

# Build production assets (emits to member1/dist)
npm run build

# Return to root directory
cd ..
```

> **Note:** Once `npm run build` completes, the compiled bundle in `member1/dist` is automatically served directly by FastAPI at the root URL.

---

### 6. Run the Application

Start the unified backend and frontend server:

```bash
python run.py
```

Or using Uvicorn directly:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --loop atlas_loop:atlas_loop_factory
```

> **Note:** The `--loop atlas_loop:atlas_loop_factory` flag is required on Windows. Uvicorn's default
> `ProactorEventLoop` silently stops accepting connections after a client resets a TCP connection
> (`WinError 64`), leaving the process alive but refusing every request. `atlas_loop.py` selects the
> `SelectorEventLoop` instead, which uvicorn already uses on Linux and macOS.

---

### 7. Access the System

Once running:
- 🌐 **Web Application Portal:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- 📚 **Interactive Swagger API Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 📖 **ReDoc API Documentation:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- ❤️ **Health Check Endpoint:** [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

## 🔐 Demo Officer Credentials

The database comes pre-configured with the following role-based access control (RBAC) officer credentials:

| Officer Name | Badge Number | Password | Role & Clearance Level |
|---|---|---|---|
| **Inspector Vikram Rathore** | `IND-LE-8402` | `password123` | **Lead Detective** (Level 3 Clearance) |
| **Special Director Rajesh Sharma** | `ADMIN-001` | `admin123` | **Super Admin** (Level 4 Clearance) |
| **Intelligence Analyst Priya Sen** | `ANALYST-101` | `analyst123` | **Forensic Analyst** (Level 2 Clearance) |

> **Login API fields:** the badge number is sent as `badgeNumber` and the password as `password`.
> `POST /api/auth/login` with `{"badgeNumber": "IND-LE-8402", "password": "password123"}` returns
> a bearer token used as `Authorization: Bearer <token>` on every other endpoint.

---

## 🧪 Testing & Verification

Run the automated end-to-end integration test suite to verify extraction, hashing, quote provenance verification, and graph synchronization:

```bash
python scripts/test_pipeline.py
```

The automated test validates:
1. Ingestion of multi-page FIRs with SHA-256 evidence hashing and immutable receipt generation.
2. Deterministic zero-LLM spreadsheet parsing for Call Detail Records (CDRs) and Bank Transaction Statements.
3. Filtering and extraction gating preventing anomalous entities (`The Person`, `Service reversal`, `Ordinary business counterparty`).
4. Cross-case entity resolution detecting matches between independent cases.
5. Multi-hop Dijkstra shortest connection path tracing in the graph.
6. Merkle blockchain chain-of-custody verification.

---

## 📥 Ingesting a Dataset

`scripts/ingest_dataset.py` loads a folder of case folders (the layout of `SFIC_DATASET/`)
into ATLAS: each file is uploaded through the public evidence API, parsed by the pipeline,
extracted by the LLM and mirrored into the Neo4j knowledge graph.

```bash
# Everything, resumable - re-running skips files that were already extracted
python scripts/ingest_dataset.py

# Only the narrative PDFs of two cases
python scripts/ingest_dataset.py --kind pdf --cases CASE_001 CASE_002

# Plan the run without calling the API
python scripts/ingest_dataset.py --dry-run

# Read-only progress report: how much of the dataset is already extracted
python scripts/ingest_status.py

# One worker per model, each taking a disjoint shard of the dataset
python scripts/ingest_dataset.py --base http://127.0.0.1:8000 --shard 0 --num-shards 2
python scripts/ingest_dataset.py --base http://127.0.0.1:8001 --shard 1 --num-shards 2
```

The script is designed for a **finite provider token budget**:

- **Round-robin across cases**, so every case gains narrative evidence early instead of
  one case absorbing the whole day's budget.
- **Resumable.** A file that already produced model-derived mentions is skipped. A file
  that was recorded by a failed run (no mentions, or mentions that only came from the
  local regex/NER extractor) is deleted and reprocessed.
- **Budget aware.** When the provider refuses a request, the backend records the failure
  in the evidence item's `job.warnings`; the script reads the provider's own retry hint
  from that warning and waits for it, then retries the same file. It never guesses a
  shorter wait and never hammers an exhausted budget.
- **Waits for the whole document.** The provider's hint covers the request that was
  refused, and a document is extracted in several chunks that are charged against the
  same budget. The script therefore waits for the budget to refill with the document's
  own cost as well, so a document is not paid for twice and refused half way through.
  `--chunk-chars` tells the worker which chunk size its server runs with.
- **Per-file tolerance.** One bad document never aborts the run.

Extraction cost is real: one narrative PDF is roughly 1500-2500 prompt + 1000-2200 output
tokens, and the client paces itself to the provider's token-per-minute budget
(`LLM_MIN_INTERVAL_S`). A large dataset therefore takes minutes per file, not seconds.

> **Provider budget.** The Groq free tier allows **200,000 tokens per day per model** - the
> budget is *per model*, so each model on the account has its own allowance and several
> models can run side by side. It is a token bucket that refills at 200,000 tokens per 24
> hours (about 2.31 tokens/second) rather than a limit that resets at midnight. The whole
> `SFIC_DATASET` (82 narrative PDFs) needs roughly 300,000-400,000 tokens, so it cannot be
> extracted in a single day on that tier. When the budget is spent the provider refuses
> with
> `Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 198961 ...`,
> the adapter fails fast on it instead of retrying, the backend records the refusal in
> `job_warnings`, and the ingest script waits for the provider's stated hint. Re-running
> `python scripts/ingest_dataset.py` later resumes where it stopped - no work is lost.
> A paid Groq tier removes the limit.

**Running several workers at once.** Because the daily budget is per model, one ATLAS
instance per model multiplies the daily throughput of a single API key. Give each
instance its own port and its own model, then point one ingest worker at each:

```powershell
# Instance 1 - the verified primary model, large chunks
$env:ATLAS_PORT=8000; $env:LLM_MODEL="openai/gpt-oss-120b"; python run.py

# Instance 2 - a second model, smaller chunks and its output ceiling
$env:ATLAS_PORT=8001; $env:LLM_MODEL="qwen/qwen3.8-27b"
$env:LLM_CHUNK_CHARS=3000; $env:LLM_MAX_COMPLETION_TOKENS=1000; python run.py

# Two workers, disjoint shards of the same dataset.
# --chunk-chars must match the LLM_CHUNK_CHARS of the server each worker talks to.
python scripts/ingest_dataset.py --base http://127.0.0.1:8000 --shard 0 --num-shards 2 --chunk-chars 12000
python scripts/ingest_dataset.py --base http://127.0.0.1:8001 --shard 1 --num-shards 2 --chunk-chars 3000
```

`qwen/qwen3.8-27b` is capped by the provider at 1000 output tokens per minute, so it needs
`LLM_MAX_COMPLETION_TOKENS=1000` and a smaller `LLM_CHUNK_CHARS`; `openai/gpt-oss-120b` has
no such cap and is the model verified over the whole corpus. The per-model limits and the
measurements behind them are recorded in `docs/docs/MODEL_GUIDE.md` and in
`member3/SFIC_Doc_Module/docs/DECISIONS.md` (DEC-040).

A failed extraction is never papered over. When the model cannot read a document, the
evidence row keeps **zero** model-derived mentions and carries the provider's reason in
`job_warnings`; the local regex/NER extractor is not used to stand in for the model. See
`docs/docs/DECISIONS.md` (DEC-025) and `member3/SFIC_Doc_Module/docs/DECISIONS.md`
(DEC-039).

To remove the throwaway cases and duplicate evidence that the verification scripts leave
behind:

```bash
python scripts/cleanup_test_artifacts.py --dry-run
python scripts/cleanup_test_artifacts.py
```

---

## 📊 Key Platform Capabilities

### 1. Document Intelligence & Entity Extraction
- **Dual-Path Ingestion:** Spreadsheets and tabular logs (CDRs, bank statements, tower dumps) are parsed deterministically at zero LLM cost using YAML profile matching. Narratives (FIRs, inquiry notes) use nonce-fenced LLM extraction.
- **Quote-Verified Provenance:** Every single entity and relationship extracted from narrative text is mechanically verified against the verbatim quote in the source document. Hallucinations are automatically rejected.
- **Anomalous Entity Elimination:** Strict stopword and regex gating prevents bookkeeping labels, transaction descriptions, and preamble artifacts from polluting the graph.

### 2. Knowledge Graph Explorer & Visualizer
- **Hierarchical Swimlane Presentation:**
  - `Tier 1: Actors & Command` (Key operatives, persons, kingpins)
  - `Tier 2: Operations & Assets` (Bank accounts, burner phones, vehicles)
  - `Tier 3: Technical & Forensics` (Cell towers, IMEIs, physical locations)
- **Dynamic Filtering:** Instant subgraph toggling for `Full Ecosystem`, `CDR Telecom Only`, `Person Syndicate Only`, and `Financial Money Flows`.
- **Centrality Analytics:** Built-in calculation of PageRank, Betweenness Centrality, and Degree Centrality to identify ringleaders and bridge nodes.
- **Docked AI Copilot:** Integrated natural language investigative copilot supporting instant topology queries, money flow tracing, and syndicate summaries.

### 3. Forensic Integrity & Chain of Custody
- **Immutable Evidence Storage:** Raw bytes hashed with SHA-256 and stored in write-protected content-addressed storage.
- **Cryptographic Audit Ledger:** Tamper-evident Merkle tree blockchain recording all file uploads, officer access, and metadata modifications.
- **Certificate of Authenticity:** Instant export of court-admissible cryptographic chain-of-custody certificates.

---

## 📡 Core API Endpoints

| Category | Endpoint | Method | Description |
|---|---|---|---|
| **Health** | `/api/health` | `GET` | Service, database, and graph engine health status |
| **Auth** | `/api/auth/login` | `POST` | Officer login returning JWT bearer token |
| **Auth** | `/api/auth/me` | `GET` | Get current active officer profile and permissions |
| **Cases** | `/api/cases` | `GET` / `POST` | List all investigation cases or register a new case |
| **Cases** | `/api/cases/{case_id}` | `GET` | Comprehensive case overview and entity breakdown |
| **Cases** | `/api/cases/{case_id}/insights` | `GET` | 10 automated suspicious anomaly pattern detectors |
| **Cases** | `/api/cases/rankings` | `GET` | Graph centrality rankings (PageRank, Betweenness) |
| **Cases** | `/api/cases/shortest-path` | `GET` | Dijkstra multi-hop shortest connection path finder |
| **Evidence** | `/api/evidence/uploads` | `POST` | Multipart upload for PDF, CSV, XLSX, and TXT files |
| **Evidence** | `/api/evidence/{id}/original` | `GET` | Stream original evidence file (supports inline viewer) |
| **Graph** | `/api/graph` | `GET` | Fetch filtered network nodes and edges for Vis.js |
| **Graph** | `/api/graph/expand` | `GET` | Dynamic 1-hop neighbor expansion for selected node |
| **Graph** | `/api/graph/ai-query` | `POST` | LLM Graph Copilot for natural language topology Q&A |
| **Graph** | `/api/graph/export/cypher` | `GET` | Export live graph as standalone Neo4j Cypher script |
| **Integrity** | `/api/v1/blockchain/ledger` | `GET` | Inspect append-only cryptographic Merkle blocks |
| **Integrity** | `/api/v1/blockchain/verify-chain` | `GET` | Bit-level verification of entire chain-of-custody |
| **Canvases** | `/api/boards` | `GET` / `POST` | Investigator freeform pinning whiteboard canvases |

---

## 🛡️ License

This project was developed for the Smart India Hackathon (SIH) Forensic Intelligence track. All rights reserved.
