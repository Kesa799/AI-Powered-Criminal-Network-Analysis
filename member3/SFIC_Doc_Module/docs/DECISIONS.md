# ATLAS Dev 3 — Architectural Decisions & Amendments Log

This document records architectural decisions, deviations, and environment-specific adaptations for ATLAS Dev 3.

## Decision Log

### DEC-001: Python Version Target (3.12 preferred, 3.11 accepted; never 3.14)
- **Context:** Host environment has default Python 3.14.0 and CPython 3.11.15. Python 3.14 lacks pre-compiled wheels for key C-extensions (`pypdfium2`, `opencv-python-headless`).
- **Decision:** Target Python 3.12 (or 3.11). Set `requires-python = ">=3.11,<3.13"`, `ruff` target-version, and `mypy` python_version accordingly. Python 3.14 is explicitly forbidden.

### DEC-002: Windows Tesseract OCR Configuration & Mandatory Gate Testing
- **Context:** On Windows, Tesseract is typically installed via `winget` at `C:\Program Files\Tesseract-OCR\tesseract.exe` and is not automatically in system `PATH`.
- **Decision:** Support `TESSERACT_CMD` and optional `TESSDATA_PREFIX` in `config.py` and `.env.example`. `ocr/tesseract.py` configures `pytesseract.pytesseract.tesseract_cmd`. `scripts/check_env.py` verifies the path, version, and installed languages.
- **Enforcement:** Set `ATLAS_REQUIRE_TESSERACT=true` on this development machine. When set, `needs_tesseract` tests cannot be skipped, and Gate 1 fails if the binary is absent.

### DEC-003: Deterministic Windows-Safe Identifiers and Path Traversal Defense
- **Context:** Windows paths reject `:` and `+`. Timestamps with colons break folder creation. Unvalidated `case_id` values could allow path traversal.
- **Decision:** Format `run_id` as `RUN-YYYYMMDDTHHMMSSZ-<6hex>` without colons. Introduce a safe-filename helper ensuring characters like `:` or `+` are never in directory names. Validate `case_id` in `contracts/` with `^[A-Za-z0-9_-]{1,64}$` to block traversal at Gate 0. Uploaded files are reduced to `os.path.basename` and stored content-addressed.

### DEC-004: Cross-Platform Line Endings and SHA-256 Fixture Integrity
- **Context:** Git's default Windows CRLF conversion mutates newline characters, invalidating fixture SHA-256 hashes and tripping the synthetic-only guard.
- **Decision:** Enforce `* text=auto eol=lf` in `.gitattributes`, mark fixtures and binaries (`*.pdf`, `*.xlsx`, `*.png`, etc.) as binary (`-text`), and generate all synthetic fixtures with explicit `\n`.

### DEC-005: Windows Read-Only Original Store Assertion
- **Context:** Unix `0444` file mode bit semantics do not map directly to Windows permissions.
- **Decision:** On Windows, immutability tests assert that opening an existing original for write access raises `PermissionError` (or is denied via `os.access`), rather than inspecting POSIX mode bits.

### DEC-006: Explicit OCR Engine Selection (No Automatic Fallback)
- **Context:** Automatic engine fallback risks silent non-reproducibility of OCR text and confidence scores.
- **Decision:** OCR engine is selected strictly via `OCR_ENGINE` configuration (`tesseract` default, `paddle` optional challenger). If a requested engine or language is unavailable, fail loudly with an actionable exception.

### DEC-007: Reviewer Confirmation of OCR Identifiers (`CONFIRM_IDENTIFIER`)
- **Context:** Scanned FIRs produce OCR-derived identifiers flagged `review_required`. If permanently blocked from graph nodes, cross-case demo cannot link Case A and Case B.
- **Decision:** Implement reviewer promotion action (`CONFIRM_IDENTIFIER` / `CORRECT_IDENTIFIER`). Once confirmed, `confirmed_by` is set, promoting the identifier to `strong`/`confirmed` status, unblocking unified graph node generation and cross-case resolution.

### DEC-008: Scope & Documentation Framing
- **Context:** Overclaiming "production readiness" or "customer-facing enterprise" status misrepresents a hackathon prototype.
- **Decision:** Frame all documentation, reports, and limitations as a high-integrity demonstrable hackathon prototype for SIH judges. `PLAN.md` is the single source of truth; derived summary documents must never be passed to workers.

### DEC-009: No Editable Installs & Strict Worktree Subprocess Isolation
- **Context:** An editable install (`pip install -e .`) points Python to a single `src/` directory, causing parallel worker worktrees to accidentally import `main`'s code and pass tests falsely.
- **Decision:** Never use editable installs. Install third-party dependencies only (`uv pip install -r pyproject.toml --extra dev`). Pytest configures `pythonpath = ["src", "."]`. Subprocesses run with `PYTHONPATH=<current worktree>\src`. `verify.py` verifies that `atlas.__file__` resides strictly inside the active worktree directory. CLI entrypoint is `python -m atlas` via `src/atlas/__main__.py`.

### DEC-010: Test Data Independence from Git-Ignored Directories
- **Context:** `data/` is git-ignored, so fresh worker worktrees do not have access to pre-generated test data or synthetic manifests.
- **Decision:** Unit and integration tests must not depend on git-ignored `data/`. A pytest session fixture generates the required synthetic files into `tmp_path`, creates a transient test manifest, and sets `DATA_DIR` dynamically. `python -m synth.generate` remains the standalone demo script.

### DEC-011: Strict Fixture Determinism on Local Windows Environment
- **Context:** ReportLab, OpenPyXL, and Pillow embed timestamps and metadata, and OS fonts vary across environments, causing byte/hash differences between runs.
- **Decision:** Use ReportLab `invariant=1`; pin OpenPyXL core properties and ZIP timestamps; strip/pin Pillow PDF metadata; vendor `DejaVu Sans` font into `synth/fonts/DejaVuSans.ttf` with its license. Determinism is asserted across two consecutive runs on the same machine.

### DEC-012: Enforce UTF-8 Everywhere
- **Context:** Windows defaults to `cp1252`, corrupting Hindi (Devanagari) and Tamil scripts and quote matching.
- **Decision:** All file I/O must specify `encoding="utf-8"`, JSON serialization must specify `ensure_ascii=False`, and all subprocesses run with `PYTHONUTF8=1`. Gate 0 includes a Devanagari/Tamil round-trip test.

### DEC-013: OCR Test Independence in Wave 1
- **Context:** B1's real-OCR test previously depended on D1's synthetic fixtures, which created an inter-worker dependency deadlock in Wave 1.
- **Decision:** Worker B1 renders its own clean test page using the vendored `synth/fonts/DejaVuSans.ttf` font, ensuring complete independence from D1.

### DEC-014: Machine-Verifiable Gate Evidence (`gate_N.json`)
- **Context:** Autonomous agents self-reporting "all passed" in chat cannot be trusted.
- **Decision:** `scripts/verify.py` writes machine-readable evidence to `outputs/gates/gate_N.json` containing the commit hash, clean-tree boolean, test counts, and names of skipped tests. Merging to `main` requires that the report's commit matches branch HEAD, the tree is clean, and zero tests are skipped on this machine.

### DEC-015: Honest Mock Provider Transparency
- **Context:** Demo videos recorded using scripted mock responses deceive evaluators about extraction capabilities.
- **Decision:** Whenever `run.provider == "mock"`, all outputs (HTML report, `/results`, CLI) must display the prominent banner: `SCRIPTED MOCK PROVIDER: not live extraction`. The final submitted demo video must be recorded using a live model on synthetic data.

### DEC-016: Windows Worktree Paths and Subprocess Safety
- **Context:** Windows `MAX_PATH` limitations and PowerShell quotation issues cause failures with long nested paths and shell strings.
- **Decision:** Worktrees are created at short paths `C:\w\<name>`. `git config core.longpaths true` is enabled. All subprocesses pass list arguments without `shell=True`.

### DEC-017: CLI Convention
- **Context:** The plan mixed `atlas <cmd>` and `python -m atlas <cmd>`, yet DEC-009 forbids installing the package, so no `atlas` console script exists.
- **Decision:** Every command is `python -m atlas <cmd>`. Docs, tests and reports use only that form.

### DEC-018: Optional Tests Are Deselected, Not Skipped
- **Context:** DEC-014 requires zero skipped tests, but PaddleOCR and Indic-font tests cannot run on every machine.
- **Decision:** Such tests carry the `optional` marker and are deselected by default (`-m "not optional"`). The gate file lists them under `not_run_optional`. Any other skip fails the gate.

### DEC-019: Orchestrator Vendors the Font and Test Harness in Wave 0
- **Context:** B1 (OCR) needs `synth/fonts/DejaVuSans.ttf` while D1 owns `synth/`, which would race in parallel Wave 1.
- **Decision:** The orchestrator vendors the font and license, and creates `tests/conftest.py` with a lazy `synthetic_dataset` fixture, in Wave 0. D1 implements `synth.generate.generate_all(out_dir, seed) -> manifest_path` and must not modify `synth/fonts/`.

### DEC-020: One Shared Interpreter and a Dependency Freeze
- **Context:** Worktrees at `C:\w\<name>` have no `.venv` of their own, and parallel dependency edits would conflict.
- **Decision:** All agents use the main repo's `.venv` interpreter by absolute path, with `PYTHONPATH=<worktree>\src`. `pyproject.toml` declares every dependency in Wave 0. Only the orchestrator changes dependencies afterward.

### DEC-021: PowerShell 5.1 Compatibility
- **Decision:** No `&&` in any documented command; use `;` or separate lines.

### DEC-022: AtlasSettings uses extra="ignore" not extra="forbid"
- **Context:** The `.env` file contains non-Atlas environment variables like `PYTHONUTF8=1`. With `extra="forbid"`, pydantic-settings rejected these, causing all config tests to fail.
- **Decision:** `AtlasSettings` uses `extra="ignore"` so non-Atlas env vars in `.env` are silently discarded. The `extra="forbid"` rule from PLAN.md section 4 applies to contract records (Pydantic models), not the settings loader.

### DEC-023: LLM Layer SDK Versions, Structured Output Formats, and Error Mapping
- **Context:** PLAN.md Section 5.9, Section 8 (F2 task card), and Hard Rule 9 require verifying official structured output and error handling for installed SDK versions, recording choices in DECISIONS.md, and encapsulating provider-specific schema translations inside adapters without mutating frozen contracts.
- **Environment SDK Versions Verified:**
  - `openai`: version 3.29.0
  - `google-genai`: version 2.30.0
- **OpenAI Adapter (`OpenAiAdapter`):**
  - Uses `client.chat.completions.create` with `response_format={"type": "json_schema", "json_schema": {"name": "model_output", "strict": True, "schema": MODEL_SCHEMA}}` and `temperature=0`.
  - Maps `openai.RateLimitError` (429) extracting `Retry-After` header when available, `openai.AuthenticationError` and `openai.PermissionDeniedError` (401/403) to secret-safe `AuthError`, `openai.InternalServerError` (5xx) to `ServerError`, `openai.LengthFinishReasonError` / `finish_reason == "length"` to `TruncatedOutputError`, and `finish_reason == "content_filter"` / `message.refusal` to `RefusalError`.
- **Google GenAI Adapter (`GeminiAdapter`):**
  - Uses `client.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=gemini_schema, temperature=0, system_instruction=...))`.
  - **Schema Translation:** Google GenAI 2.30.0 requires OpenAPI 3.0 types and rejects Draft-7 multi-type lists (e.g. `type: ["string", "null"]` raises `ValueError: ['string', 'null'] is not a valid Type`). `GeminiAdapter` encapsulates `convert_schema_for_gemini()` to convert `type: ["string", "null"]` to `type: "string", nullable: True` and cleans `None` from `enum` arrays with `nullable: True`. Frozen contracts in `contracts/model_schema.py` remain untouched.
  - Maps `google.genai.errors.ClientError` (401/403) to secret-safe `AuthError`, `ClientError` (429) to `RateLimitError`, `google.genai.errors.ServerError` (5xx) to `ServerError`, `FinishReason.MAX_TOKENS` to `TruncatedOutputError`, and safety finish reasons (`SAFETY`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII`, `IMAGE_SAFETY`) to `RefusalError`.
- **Retry Matrix & Secret Safety:**
  - `execute_with_retry` enforces Section 5.9 retry rules: 429/5xx/timeout/connection errors retry up to `LLM_MAX_ATTEMPTS` (default 3) with base 2.0s exponential backoff and jitter, honoring `Retry-After`. Truncated output signals truncation via `TruncatedOutputError` with optional `split_fn` re-run. Schema violations allow exactly 1 retry of that chunk before raising `SchemaViolationError`. 401/403 and safety refusals fail fast with 0 retries. All error messages are guaranteed secret-safe.

### DEC-024: Person-name filtering is configuration-driven, not hardcoded
- **Context:** The extractor wrongly accepted generic phrases and bank narrations ("The Person", "Service Reversal", "Ordinary course of business") as PERSON. The prior fix embedded an entity blacklist and regexes directly in `normalize/names.py`, which is both brittle and violates the "nothing hardcoded, nothing predefined" requirement.
- **Decision:** Entity filtering is loaded from `config/entity_filters.yaml` (`PersonNameFilter`), with an explicit-path argument, the `ENTITY_FILTER_CONFIG` environment override, and a packaged fallback. Behavior combines lexicon membership (generic terms, role terms, narration terms) with structural rules (function words, generic prefixes, minimum letters, maximum token count). No entity-name literal appears in Python source; changing the YAML changes behavior with no code change (proved by `tests/unit/test_entity_filters_config.py`).

### DEC-025: Single retry layer and client-side pacing
- **Context:** Live Groq runs failed with 429s because the runner wrapped `execute_with_retry` around adapters that already retried internally (nested 3x3 bursts), because there was no delay between chunks, and because `Retry-After: "6s"` failed `float()` parsing.
- **Decision:** Adapters (`OpenAiAdapter`, `GeminiAdapter`) declare `handles_retries = True`; `execute_with_retry` short-circuits to a single `client.extract(...)` call for such clients, so retries happen exactly once per layer. `llm/pacing.py` provides `parse_retry_after` (handles `6s`, `1m30s`, `500ms`, HTTP dates, plain numbers) and a `RateLimiter` (sliding window + derived minimum interval + `notify_retry_after`). New settings `LLM_MAX_REQUESTS_PER_MINUTE` (30), `LLM_RATE_WINDOW_S` (60.0) and `LLM_MIN_INTERVAL_S` (0.0 = derived) control pacing; the hardcoded inter-chunk `time.sleep(1.0)` was removed from the runner. All pacing values live in configuration, not source.

### DEC-026: Development web UI is a separate, auth-free testing surface
- **Context:** There was no simple way to upload a document and inspect extracted entities and connections during development.
- **Decision:** A small self-contained page is served at `GET /` by `atlas.api.ui` (no CDN, no client-side entity lists), launched with `python -m atlas ui`. `GET /ui/config` exposes available providers and schema enum values so the page hardcodes nothing. `POST /ui/run` writes uploads to a `tempfile.mkdtemp` directory using basename-only names, runs the pipeline synchronously, and returns entities, relationships, events and a graph payload. The route is intentionally auth-free because it is a dev/testing surface only; it enforces `validate_case_id` and the size limit, and it surfaces the `SCRIPTED MOCK PROVIDER: not live extraction` banner (DEC-015) whenever the run uses the mock provider.

### DEC-027: Model-reported `unit_id` is resolved deterministically inside the chunk
- **Context:** A live Groq run (`openai/gpt-oss-120b`, 2026-10-19, `data/synth/SURVEILLANCE_A.txt`) completed in 16.5 s with **0 mentions and 14 rejections**. Every rejection was `unit_not_in_chunk`: the prompt shows headers like `[UNIT DOC-45de563df99f:p001:l000005]` but the model echoed only the trailing segment `l000005`, and `verify_model_output` required an exact match plus a `doc_id` prefix.
- **Decision:** `atlas.provenance.verify.resolve_unit_id` resolves a reported reference strictly against the units actually present in the chunk: (1) exact match wins, (2) otherwise a reference that is a unique `:<segment>` suffix of exactly one chunk unit is accepted, (3) anything matching nothing, more than one unit, or a unit belonging to another document returns `None` and the item is rejected. Resolution is reference lookup, not repair: the quote must still verify verbatim in the resolved unit and all provenance (page, lines, bbox) is computed from that unit, so no identifier, page or quote is ever invented. Applied to mentions, relationships and events. Result on the same input: 0 → **6 mentions, 2 relationships, 2 events, 1 rejection**. Tests: `tests/unit/test_provenance_unit_refs.py` (exact, unique suffix, ambiguous-`None`, foreign-doc-`None`, unknown-`None`, mention/relationship provenance).

### DEC-028: Live providers require an explicit `LLM_MODEL`; no hardcoded model fallbacks
- **Context:** Hard Rule 9 forbids hardcoding model names from memory, yet `llm/client.py` silently defaulted to `gpt-4o-mini`, `gemini-2.0-flash` and `openai/gpt-oss-120b` whenever `LLM_MODEL` was empty. The developer's `.env` had `LLM_MODEL=` empty, so the running system depended on an unverified hardcoded default.
- **Verified live (2026-10-19, Groq, installed `openai` 3.29.0):** model `openai/gpt-oss-120b` at `https://api.groq.com/openai/v1` accepts `response_format={"type": "json_schema", "strict": true}` and returned a schema-valid payload in 2.03 s (2 mentions).
- **Decision:** `llm/client.py` no longer contains any model-name literal: `_require_model(cfg, provider)` raises a secret-safe `ConfigError` naming `LLM_MODEL` when it is empty for `openai`, `gemini` or `groq`. The model id is supplied by configuration (`LLM_MODEL=openai/gpt-oss-120b`) and recorded here. Adapter constructor defaults remain only for direct adapter construction in unit tests; the live path always passes an explicit model.

### DEC-029: The dev UI offers only the providers the operator enables
- **Context:** The page offered `mock`, `groq` and `gemini` because credentials for each happened to be visible to the process, which is confusing when the deployment is "Groq only". Choosing `mock` also produced zero entities for every unscripted file, with no explanation.
- **Decision:** New setting `LLM_PROVIDERS_ENABLED` (comma-separated, empty by default) is the authoritative allow-list for `GET /ui/config` and `POST /ui/run`; when it names nothing usable the configured `LLM_PROVIDER` is offered alone. `POST /ui/run` rejects any provider outside that list with HTTP 400, and an omitted provider field falls back to `LLM_PROVIDER` instead of a hardcoded `mock`. With one provider enabled the page renders a static provider badge instead of a dropdown. `python -m atlas run --provider` now also defaults to `LLM_PROVIDER` (previously it always overrode configuration with `mock`). Local `.env` is set to `LLM_PROVIDER=groq`, `LLM_MODEL=openai/gpt-oss-120b`, `LLM_PROVIDERS_ENABLED=groq`.

### DEC-030: Registration of uploads as synthetic is an explicit opt-in in the dev UI
- **Context:** With `ATLAS_SYNTHETIC_ONLY=true` (Hard Rule 1) any file whose SHA-256 is not in `data/synthetic_manifest.json` is rejected before the model is called, so a live run on an unregistered upload returns `rejected_input` with zero entities. Nothing in the page explained that.
- **Decision:** No rule was weakened. The page now (a) publishes the run `state` as a coloured banner with a plain-language `state_note`, (b) explains the synthetic-manifest refusal and names the CLI remedy, and (c) offers an unchecked checkbox "I confirm these uploads are synthetic" which, when ticked, calls the existing attestation path (`atlas.ingest.synthetic_guard.register_synthetic_files`, the same JSON format as `python -m atlas register-synthetic`) before the run. Registration is a human declaration recorded in a git-ignored manifest, is idempotent, and remains the only way a live provider may see an uploaded file.

### DEC-031: Dev-UI run feedback, upload streaming and temp cleanup
- **Context:** A blocking request with no feedback is indistinguishable from a hang (a stopped server produced a page that appeared to load for ~10 minutes), and an upload was fully buffered in memory before the size check.
- **Decision:** `POST /ui/run` streams each upload to disk in 1 MiB blocks and aborts as soon as `MAX_FILE_MB` is exceeded (no full-file buffering), skips empty files with a warning, and uses `tempfile.TemporaryDirectory` so uploaded bytes are removed when the request finishes. The page shows a live elapsed-seconds counter and a Cancel button (`AbortController`) while a run is in flight, reports the duration in the run summary, and distinguishes `completed` / `completed_with_warnings` / `rejected_input` / `failed` in a state banner. User-facing messages never include file contents; unexpected failures return a type-only message and log the traceback through the PII-scrubbing logger. A provider error surfaces a `rejected_input` explanation rather than a silent "no output".

### DEC-032: Role/rank tokens no longer discard a genuinely named person
- **Context:** The config-driven filter (DEC-024) rejected any PERSON whose surface text contained a role token, so the real named officer "Sub-Inspector K. Rathore" from `data/synth/SURVEILLANCE_A.txt` was dropped as a `schema_violation`.
- **Decision:** Narration vocabulary still rejects a phrase outright (real names never contain "reversal", "deposit", "ordinary"). A role token now rejects the phrase only when no genuine name token remains, so bare roles ("Investigating Officer", "Inspector K") are still refused while "Sub-Inspector K. Rathore" and "Officer Ramesh Kumar" are kept; the role itself is captured separately in `stated_role`. Behaviour remains entirely lexicon-driven (`config/entity_filters.yaml`) with no entity strings in source. Tests: `tests/unit/test_person_name_roles.py`.

### DEC-033: Run results are downloadable as JSON from the dev UI
- **Context:** Extraction results were only visible as rendered tables, so they could not be saved as a file, and the pipeline's own artifacts under `outputs/{case_id}/{run_id}/` were undiscoverable from the page.
- **Decision:** The page gained a "Download JSON" button that saves the exact payload it renders (`state`, `state_note`, documents, mentions, relationships, events, review items, rejections, warnings, graph) as `atlas_<case_id>_<run_id>.json`, serialized client-side from the last response: no second model call and no server-side run cache. In addition, `GET /ui/runs/{case_id}/{run_id}/{artifact}` serves the pipeline's canonical artifacts as file attachments (`result.json`, `review_queue.json`, `receipt.json`, `events.jsonl`, `trace.jsonl`), and `GET /ui/config` publishes those names so the page hardcodes nothing. The route validates `case_id` through the frozen contract helper, requires `run_id` to match the generated `RUN-YYYYMMDDTHHMMSSZ-<6hex>` format, accepts only allow-listed artifact names, and requires the resolved path to remain inside `OUTPUT_DIR` (defence in depth against path traversal). Verified live on 2026-10-19: a UI run (groq, `openai/gpt-oss-120b`, state `completed_with_warnings`) downloaded 22,056 bytes of `application/json` that parse back to 6 mentions, 2 relationships, 3 events and a 10-node/8-edge graph; the artifact route returned `200` with `content-disposition: attachment; filename="<case_id>_<run_id>_result.json"`. Tests: `tests/contract/test_api_ui.py`.

### DEC-034: Documentation is kept true to the configured provider; stale commands and gate statuses removed
- **Context:** Docs written before DEC-027…DEC-033 still prescribed `LLM_MODEL=mock-extraction-model` / `gpt-4o` (SETUP.md), listed only `openai` and `gemini` as live adapters (LIMITATIONS.md), showed subcommands that do not exist (`atlas extract`, `atlas ingest`, `atlas resolve`, `atlas report`, `python -m atlas.eval.runner`), and CHECKLIST.md still marked gates 4 and 5 as pending although `outputs/gates/gate_4.json` and `gate_5.json` record zero failures. README.md also linked `docs/PLAN.md` (the file is at the repository root) and ran the demo through `scripts/demo.py` instead of the documented entry point.
- **Decision:** Documents must satisfy three checks: (1) no model id is ever presented as a default — every live example sets `LLM_MODEL` explicitly; (2) every command shown is verified against `python -m atlas --help`; (3) live-provider lists include `groq`. The developer UI (provider allow-list, live elapsed counter, synthetic-manifest refusal message, JSON download and artifact links) is now documented in README.md §4.6 and docs/SETUP.md §4.4. Updated: `README.md`, `docs/SETUP.md`, `docs/MODEL_GUIDE.md`, `docs/DEVELOPER_INTEGRATION_GUIDE.md`, `docs/LIMITATIONS.md`, `docs/CHECKLIST.md`, `docs/EVALUATION.md`, `docs/IMPLEMENTATION_REVIEW.md`. `PLAN.md` and `AGENTS.md` were deliberately left untouched (orchestrator-owned and frozen after Gate 0); the divergent `PLAN.md` env-key list is reported rather than silently rewritten.
- **Also in this change (local hygiene, git-ignored only):** run residue under `outputs/` (per-case directories, `demo_summary.json`, `entity_store.db`, `ui_demo.json`, a local verify log) and an empty `tmp/` were deleted. `outputs/gates/` (gate evidence) and `data/` (synthetic fixtures, manifest, originals, receipts) were preserved so the demo still runs offline; no tracked file outside `docs/` and `README.md` was changed and no code was deleted (every module listed in CHECKLIST.md §1 was confirmed live, e.g. `llm/retry.py` is still imported by `pipeline/runner.py`).





### DEC-035: Groq model selection for ATLAS strict-schema extraction (SUPERSEDED by DEC-036)

> **Superseded.** The conclusion recorded here - that the openai/gpt-oss-* reasoning
> models are incompatible with Groq's strict json_schema decoder - was **wrong**. The
> real cause was a missing max_completion_tokens, which truncated the generated
> document mid-object and surfaced as the same json_validate_failed code. See
> **DEC-036** for the corrected diagnosis, the full verification matrix and the
> configuration change. The evidence below is kept because it is what the
> investigation actually observed; the interpretation is what was wrong.

- **Context:** DEC-028 and DEC-029 record `openai/gpt-oss-120b` as the verified live model on 2026-10-19. In production integration against the ATLAS backend (2026-10-21) that model stopped working: every request returned HTTP 400 with body `{"error":{"message":"Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.","type":"invalid_request_error","code":"json_validate_failed","failed_generation":""}}`. The generation was empty, so extraction silently yielded 0 mentions. The retry loop then burned 3 attempts per chunk and surfaced only the generic `OpenAI API error with status 400`.
- **Verified live (2026-10-21, Groq, `openai` 3.35.1, all 11 models the key can reach, replaying the real ATLAS system + user prompt and the frozen `MODEL_SCHEMA` under `response_format={"type":"json_schema","strict":true}`):**
  - `openai/gpt-oss-20b` - HTTP 400 `json_validate_failed`, empty generation (both strict and plain modes).
  - `openai/gpt-oss-120b` - HTTP 400, "max completion tokens reached before generating a valid document"; reasoning tokens consume the whole budget.
  - `openai/gpt-oss-safeguard-20b` - HTTP 413 request too large.
  - `canopylabs/orpheus-*`, `allam-2-7b`, `meta-llama/llama-prompt-guard-*` - no structured-output support for this schema.
  - `qwen/qwen3.8-27b` - PASS. Valid schema-conformant JSON, 3 mentions from `FIR_CASE_001.pdf`, repeatable 5/5 (1.4-44.3 s, identical output).
- **Root cause:** the `openai/gpt-oss-*` family are reasoning models. Under Groq's constrained decoder the reasoning channel is incompatible with strict `json_schema`, so the constrained generation is empty (`failed_generation: ""`) or the reasoning tokens exhaust the completion budget before any schema-conformant content is emitted. This is a provider-side incompatibility, not a prompt or schema defect.
- **Decision:** The operator-configured `LLM_MODEL` for Groq is set to `qwen/qwen3.8-27b`. No code change was made to the adapter, the prompt or the frozen schema. `LLM_MODEL` remains the single source of truth (DEC-028) - no model id is hardcoded - and the verified id is recorded here per Hard Rule 9.
- **Also noted:** `atlas.llm.client.get_llm_client` resolves the model from `cfg.LLM_MODEL` and ignores the `model_version` argument threaded through `PipelineRunner.run`. A caller that overrides the model at the call site therefore still hits the configured model. The configured value is the effective one.

### DEC-036: `max_completion_tokens` must be set explicitly; the verified Groq model is `openai/gpt-oss-120b`
- **Context:** DEC-035 concluded that the `openai/gpt-oss-*` family is fundamentally incompatible with Groq's strict `json_schema` decoder because reasoning models "put everything in the reasoning channel". **That conclusion was wrong and is superseded by this entry.** DEC-035's own evidence pointed at the real cause and it was misread: the HTTP 400 body carried the key field `failed_generation`, which was a *partially written, schema-shaped* JSON document, not an empty string. The generation was being cut off, not suppressed.
- **Actual root cause:** the adapter never sent `max_completion_tokens`, so the provider applied its own default. When the generation exceeded it, the constrained decoder aborted mid-object and Groq reported the truncation under the `json_validate_failed` code - an error that reads like a schema problem but is a length problem. Two distinct provider errors were conflated under one code:
  - `openai/gpt-oss-20b`: `failed_generation: ""` (empty).
  - `openai/gpt-oss-120b` and `qwen/qwen3.8-27b` on larger documents: `failed_generation: "{\"events\": [], \"mentions\": [ ... \"quote\": \"Vikra"` - truncated mid-string, with the body stating `max completion tokens reached before generating a valid document ... missing required content: 'relationships', 'notes'`.
- **Verified live (2026-10-21, Groq, `openai` 3.35.1, the real ATLAS system + user prompt and the frozen `MODEL_SCHEMA` under `response_format={"type":"json_schema","strict":true}`, with `max_completion_tokens=8192`):**
  - `openai/gpt-oss-120b` - PASS. Schema-valid, 8 mentions, `finish_reason=stop`, completion 2255 tokens.
  - `qwen/qwen3.8-27b` - PASS. Schema-valid, 19 mentions, completion 2143 tokens.
  - `openai/gpt-oss-20b` - still FAIL: `Generated JSON does not match the expected schema`. The 20B model is genuinely weaker at this task, independent of truncation.
  - `openai/gpt-oss-safeguard-20b` - HTTP 413 request too large. `canopylabs/orpheus-*` - terms not accepted. `allam-2-7b` - `max_completion_tokens` ceiling 4096. `meta-llama/llama-prompt-guard-*` - ceiling 512. `whisper-*` - not chat models.
- **Rate-limit envelope of this Groq account (measured from the `x-ratelimit-*` response headers):** 1000 requests/minute, 8000 tokens/minute (TPM). Per-model output ceilings differ and decide the choice:
  - `qwen/qwen3.8-27b` is additionally subject to an **output-tokens-per-minute limit of 1000**. Its expected output for an ATLAS chunk is 1045-2143 tokens, so the provider rejects the request outright: `Request too large for model ... on output tokens per minute (OTPM): Limit 1000, Requested 2143`. This model is unusable for the ATLAS extraction payload on this tier.
  - `openai/gpt-oss-120b` has **no OTPM limit**. A call costs ~2500 prompt + ~2200 output tokens against the 8000 TPM budget, so roughly one call per 30 s.
- **Decision:** `LLM_MODEL` for Groq is `openai/gpt-oss-120b` - the model member3 originally verified in DEC-028, which the truncation bug had masked. A new setting `LLM_MAX_COMPLETION_TOKENS` (default 8192, `0` leaves the provider default in place) is threaded from `AtlasSettings` through `llm/client.py` into `OpenAiAdapter`, and sent as `max_completion_tokens` only when positive. The SDK client is now constructed with `max_retries=0` because this adapter owns its own retry loop and that loop is paced by the rate limiter; letting the SDK retry underneath burst extra requests past the configured request budget.
- **Pacing:** `LLM_MAX_REQUESTS_PER_MINUTE` and `LLM_MIN_INTERVAL_S` already existed and were already honoured by `RateLimiter.from_settings`; the deployment sets `LLM_MAX_REQUESTS_PER_MINUTE=2` and `LLM_MIN_INTERVAL_S=32` so consecutive calls fit the 8000 TPM budget. The provider's `Retry-After` / `x-ratelimit-reset-tokens` headers are already parsed by the adapter and fed back into the limiter via `notify_retry_after`.
- **Not changed:** the prompt, the frozen `MODEL_SCHEMA`, and the contracts. The schema itself is unchanged; only the request envelope grew.

### DEC-037: The client-side rate limiter is process-wide, and a 429 waits for the token window
- **Context:** DEC-036 configured `LLM_MAX_REQUESTS_PER_MINUTE` / `LLM_MIN_INTERVAL_S` and assumed they paced the provider. In the ATLAS backend they did not. The backend builds a fresh `PipelineRunner` (and therefore a fresh `OpenAiAdapter` and a fresh `RateLimiter`) for every document, and `RateLimiter` keeps its sliding-window state on the instance. A limiter rebuilt per document therefore never observes the previous call, so the minimum interval was never enforced: the observed request rate was one call every 7-13 s against an 8000 TPM budget, and the provider answered with HTTP 429. The retry then waited only the provider's `Retry-After` hint (3 s), which is shorter than the ~17 s the token window actually needs to refill, so all three attempts could be spent before the budget returned and the document silently fell back to the local regex/NER extractor.
- **Decision:** Two changes, both inside the adapter layer, neither touching the prompt, the frozen schema or the contracts.
  1. `llm/client.py` now caches the limiter per pacing configuration in a module-level dictionary guarded by a lock. A repeated `get_llm_client()` call - which happens once per document - reuses the same limiter, so its window state and last-call timestamp survive across documents. Changing the pacing configuration produces a new limiter rather than mutating the live one.
  2. `llm/openai_adapter.py` now derives the retry delay from the **maximum** of `Retry-After` and `x-ratelimit-reset-tokens` instead of the first header it finds. `Retry-After` can be shorter than the budget that actually blocked the request, and `x-ratelimit-reset-tokens` is when the token budget refills. `x-ratelimit-reset-requests` is deliberately **not** used: it is the horizon of the request-count sliding window (minutes away even when the request budget is not what blocked the call) and using it would stall the pipeline for tens of minutes.
- **Verified live (2026-10-21, Groq, `openai/gpt-oss-120b`):** with the limiter cached, the second `acquire()` in the same process waits the full configured interval (measured 40.00 s with `LLM_MIN_INTERVAL_S=40`), and a real document ingest now completes in 39-40 s per file with **no 429 responses** in the provider log. The deployment uses `LLM_MAX_REQUESTS_PER_MINUTE=2` and `LLM_MIN_INTERVAL_S=40`, which puts one extraction call (~1500-2500 prompt + ~1000-2200 output tokens) inside the 8000 TPM budget with headroom.
- **Not changed:** the prompt, the frozen `MODEL_SCHEMA`, the contracts, and the retry matrix in `llm/retry.py` (attempt count and backoff are still as specified).

### DEC-038: Tesseract is discovered, not assumed to be under Program Files
- **Context:** `AtlasSettings.TESSERACT_CMD` defaulted to `C:\Program Files\Tesseract-OCR\tesseract.exe`. On a machine where Tesseract is installed per-user (the current deployment has it under `%LOCALAPPDATA%\Programs\Tesseract-OCR`) that default is wrong, and the failure is silent in the worst way: a PDF with no text layer produced **zero source units**, so the extraction stage had nothing to quote against and the document came out with zero mentions. The pipeline reported the page as processed, and the only clue was a per-page warning string. The symptom was therefore indistinguishable from "this document contains nothing of interest", and the mock-provider end-to-end test (`test_clean_fir_end_to_end`) failed with the same empty result.
- **Decision:** `TESSERACT_CMD` is resolved at configuration load time instead of being a hard-coded guess. An explicitly configured path is always honoured verbatim (so a wrong setting is reported by the OCR engine rather than silently replaced). Only the *default* is resolved, and it is resolved against the locations Tesseract is actually installed in - the system-wide `Program Files` path, the per-user `%LOCALAPPDATA%\Programs` path, the macOS Homebrew and Linux paths, and finally `tesseract` on `PATH`. The resolution lives in `atlas/config.py`; no extraction, OCR or contract code changed.
- **Verified live (2026-10-21, Windows 11, Tesseract 5.4.0):** the setting now resolves to `C:\Users\<user>\AppData\Local\Programs\Tesseract-OCR\tesseract.exe`, `eng` and `osd` are listed as available languages, and `tests/integration/test_pipeline_runner.py::test_clean_fir_end_to_end` - the mock-provider FIR end-to-end that previously extracted **0 mentions** - now passes. `python scripts/verify.py --gate 5 --cumulative` is green: 566 passed, 0 failed, 0 skipped, with `ruff check`, `ruff format --check` and `mypy src/atlas` all clean.
- **Also fixed, same root cause class:** three API contract tests in `tests/contract/test_api_ui.py` failed because the live-provider code paths could not be reached without a provider credential in the environment. The `mock_env` fixture now provides a placeholder `GROQ_API_KEY` so the allow-list, the missing-model check and the synthetic-guard refusal are all exercised as intended. No provider call is made - the synthetic guard and the model check both refuse before any request - and no real credential is stored in the repository.
- **Not changed:** the prompt, the frozen `MODEL_SCHEMA`, the contracts, `atlas/ports/`, and every extraction, OCR and quote-verification rule. The fix is configuration discovery only.

### DEC-039: An exhausted daily token budget fails fast and is never retried
- **Context:** The retry matrix in `llm/retry.py` (PLAN.md section 5.9) treats every HTTP 429 the same way: retry up to `LLM_MAX_ATTEMPTS` with a backoff that honours `Retry-After`. That is right for a **per-minute** rate limit, where the budget refills within seconds. It is wrong for a **daily** token budget, where the provider refuses with a body that names the window and a hint measured in minutes: `Rate limit reached for model openai/gpt-oss-120b in organization ... on tokens per day (TPD): Limit 200000, Used 198961, Requested 2884. Please try again in 13m17.04s.` Retrying that three times spends 40 minutes to reach the same refusal, and - because the refusal comes back as a *failed chunk* rather than an exception - the caller cannot tell a budget exhaustion from a document that simply has no entities.
- **Evidence (2026-10-21, Groq, `openai/gpt-oss-120b`):** the error body was read directly with a plain HTTP call. The account limit is `200000` tokens per day, and the body reports the *used* count, the *requested* count and the wait hint. The `x-ratelimit-*` response headers are **not** the signal for this condition: on the refused request they showed `x-ratelimit-remaining-tokens: 8000` (a full per-minute budget) and `x-ratelimit-remaining-requests: 978`, because the daily refusal happens before the per-minute accounting is touched. The budget is organisation-wide, not per model: a call to `qwen/qwen3.8-27b` was refused with the same TPD message, and one small `qwen` call that happened to fit inside the last ~1000 free tokens did succeed. There is therefore no second model with a separate daily budget to fall back to.
- **Decision:** The daily-budget refusal is classified as its own condition and is **not** retried.
  - `llm/retry.py` gains `QuotaExceededError(ProviderError)`, which carries the provider's `retry_after` hint. It joins `AuthError`, `RefusalError` and `RetryExhaustedError` in the fail-fast branch of `execute_with_retry`, so a `QuotaExceededError` propagates immediately instead of consuming the attempt budget.
  - `llm/openai_adapter.py` reads the provider's error body and recognises a daily-budget refusal by the markers `tokens per day` and `(tpd)`. A 429 whose body carries those markers raises `QuotaExceededError`; every other 429 keeps the existing `RateLimitError` path and its normal retry behaviour.
  - A successful call now logs its token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) at INFO level. Token counts only - never the prompt or the completion - so an operator can see what a document costs against the daily budget.
  - The adapter's 429 log line was extended to print the `x-ratelimit-*` / `retry-after` headers, which is what made the distinction between a per-minute limit and a daily budget visible in the first place.
- **Verified live (2026-10-21):** with the budget exhausted, a refusal now surfaces as `Provider daily token budget exhausted: provider=groq model=openai/gpt-oss-120b wait_s=597.0` and the process returns in ~60 s instead of ~40 min. Two new unit tests cover both branches: `test_openai_adapter_daily_token_budget_fails_fast` (one call, then `QuotaExceededError` carrying the provider's hint) and `test_openai_adapter_per_minute_limit_is_still_retried` (a 429 without the daily markers still retries to `RetryExhaustedError`).
- **Not changed:** the prompt, the frozen `MODEL_SCHEMA`, the contracts, the attempt count for ordinary 429/5xx/timeout conditions, and the backoff schedule. The deviation from the section 5.9 matrix is deliberate and narrow: it adds a fail-fast case the matrix does not contemplate, and it changes nothing for the cases the matrix does specify.
