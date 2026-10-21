"""Bulk ingest the SFIC_DATASET into ATLAS (Postgres + Neo4j Aura).

Design notes
------------
* **Resumable.** Files already present in the case's evidence list are skipped,
  so the script can be re-run across days without re-spending LLM tokens.
* **Round-robin across cases.** Narrative PDFs are consumed one per case in
  turn, so every case gains narrative evidence early instead of one case
  absorbing the whole daily token budget.
* **Budget aware.** The Groq tier this deployment uses allows a finite number
  of tokens per day. When the provider starts refusing requests the backend
  records the failure in the evidence item's ``job.warnings``; this script
  detects that and stops cleanly instead of hammering the provider.
* **Per-file tolerance.** One bad file never aborts the run.

Usage:
    python scripts/ingest_dataset.py                 # all cases, resumable
    python scripts/ingest_dataset.py --max-files 20  # stop after 20 files
    python scripts/ingest_dataset.py --kind pdf      # only pdf (or xlsx)
    python scripts/ingest_dataset.py --cases CASE_001 CASE_002
    python scripts/ingest_dataset.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

from evidence_provenance import has_model_derived_mentions

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT.parent / "SFIC_DATASET"
BASE = "http://127.0.0.1:8000"
BADGE = "IND-LE-8402"
PASSWORD = "password123"
OFFICER = "Inspector Vikram Rathore"

# Backoff between retries of a failed upload. The backend's database lives
# behind a remote pooler, so a transient DNS failure there shows up as a 500.
RETRY_BACKOFF_S = 20.0

# When the provider refuses because its daily token budget is spent it states
# when to try again. Honouring that hint paces the ingest to the provider's
# own budget instead of hammering it.
#
# The daily budget is a token bucket that refills slowly (one day's worth of
# tokens over 24 hours), so a refused file can wait for *hours* before the
# provider's hint comes due. The cap is therefore on the total time a single
# file may spend waiting, not on the number of attempts: a three-attempt cap
# would abandon a file after roughly one provider hint and stop the run.
MAX_QUOTA_RETRIES = 200
MAX_QUOTA_WAIT_S = 3600.0
MAX_QUOTA_WAIT_TOTAL_S = 20 * 3600.0

# The daily budget is a token bucket: it refills with a day's worth of tokens
# over 24 hours, so the provider's own "try again in Xs" hint only tells us when
# the bucket holds enough room for the chunk that was refused. A document is
# extracted in several chunks, and every chunk is charged against the same
# bucket, so a document that starts when only one chunk's worth of room is free
# is refused at its second chunk - after the first chunk has already been paid
# for. The wait is therefore extended by the time it takes the bucket to refill
# with the document's own cost.
BUDGET_REFILL_TOKENS_PER_S = 200000.0 / 86400.0

# The cost estimate is deliberately generous. It decides how long to wait for
# the bucket to refill, and over-estimating only lengthens the wait, while
# under-estimating lets the provider refuse the later chunks of a document whose
# earlier chunks were already paid for.
TOKEN_COST_FACTOR = 2.5
PER_CHUNK_OVERHEAD_TOKENS = 400
TOKEN_COST_FLOOR = 2000

# Substrings that identify a provider refusal in a job warning.
RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "tokens per day",
    "tokens per minute",
    "retry",
    "quota",
)

session = requests.Session()


def login() -> None:
    r = session.post(
        f"{BASE}/api/auth/login",
        json={"badgeNumber": BADGE, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    session.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    print("[auth] ok", flush=True)


def existing_evidence(case_id: str) -> Tuple[set[str], Dict[str, str]]:
    """Split a case's evidence into (usable filenames, stale filename -> id).

    A file counts as usable only when the model produced its mentions. A row
    that holds nothing, a row whose mentions came from the local regex/NER
    extractor, and a row whose pipeline run was refused by the provider are
    all worth reprocessing.
    """
    r = session.get(f"{BASE}/api/evidence", params={"case_id": case_id, "limit": 1000}, timeout=120)
    r.raise_for_status()
    usable: set[str] = set()
    stale: Dict[str, str] = {}
    for item in r.json().get("items", []):
        job = item.get("job", {}) or {}
        name = item.get("filename")
        if not name:
            continue
        warnings = " ".join(str(w) for w in (job.get("warnings") or [])).lower()
        used_local_extractor = "ner extractor" in warnings or "regex" in warnings
        has_mentions = (job.get("mention_count") or 0) > 0 and job.get("status") != "Failed"

        if not has_mentions or used_local_extractor:
            stale[name] = item.get("evidence_id")
            continue

        if name.lower().endswith(".pdf"):
            # A PDF is extracted by the model; a row that only holds locally
            # extracted mentions was never really read by the model.
            derived = has_model_derived_mentions(session, BASE, item.get("evidence_id"))
            if derived is False:
                stale[name] = item.get("evidence_id")
                continue

        usable.add(name)
    return usable, stale


def delete_evidence(evidence_id: str) -> bool:
    try:
        r = session.delete(f"{BASE}/api/evidence/{evidence_id}", timeout=60)
        return r.status_code < 400
    except Exception:
        return False


def round_robin(groups: List[List]) -> Iterable:
    """Yield items from each group in turn, so every group advances evenly."""
    idx = 0
    while any(idx < len(g) for g in groups):
        for g in groups:
            if idx < len(g):
                yield g[idx]
        idx += 1


def upload(case_id: str, path: Path, timeout_s: int = 900, retries: int = 4) -> Dict:
    """Upload one file and return the resulting evidence item.

    The backend talks to a remote Postgres pooler, so a transient DNS or
    connection failure surfaces as a 500 rather than a 4xx. That is an
    infrastructure hiccup, not a bad file, so the upload is retried with a
    backoff before it is reported as an error.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        handles = []
        try:
            handle = open(path, "rb")
            handles.append(handle)
            files = {"files": (path.name, handle, "application/octet-stream")}
            data = {
                "case_id": case_id,
                "category": "General Investigation",
                "uploader": OFFICER,
            }
            r = session.post(
                f"{BASE}/api/evidence/uploads",
                files=files,
                data=data,
                timeout=timeout_s,
            )
            if r.status_code >= 500 and attempt < retries:
                print(
                    f"    [retry {attempt + 1}/{retries}] {path.name}: server error {r.status_code}",
                    flush=True,
                )
                time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            r.raise_for_status()
            items = r.json().get("items", [])
            return items[0] if items else {}
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            print(
                f"    [retry {attempt + 1}/{retries}] {path.name}: {exc}",
                flush=True,
            )
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
        finally:
            for h in handles:
                h.close()
    if last_exc is not None:
        raise last_exc
    return {}


def summarize(item: Dict) -> str:
    job = item.get("job", {}) or {}
    warns = job.get("warnings") or []
    bits = [
        f"mentions={job.get('mention_count', 0)}",
        f"claims={job.get('claim_count', 0)}",
        f"status={job.get('status')}",
    ]
    if warns:
        bits.append(f"warnings={len(warns)}")
    return " ".join(bits)


def is_rate_limited(item: Dict) -> bool:
    """True when the provider refused the extraction call.

    The backend records the provider's own message in the evidence job
    warnings, so the refusal is detected from the recorded reason rather than
    from the HTTP status of the upload.
    """
    job = item.get("job", {}) or {}
    for w in job.get("warnings") or []:
        low = str(w).lower()
        if "extraction failed" in low and any(m in low for m in RATE_LIMIT_MARKERS):
            return True
    return False


def retry_hint_seconds(item: Dict) -> Optional[float]:
    """Return the provider's own 'try again in X' hint, in seconds."""
    job = item.get("job", {}) or {}
    for w in job.get("warnings") or []:
        m = re.search(r"retry after\s+([0-9]+(?:\.[0-9]+)?)\s*s", str(w), re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def estimate_document_tokens(path: Path, chunk_chars: int) -> int:
    """Estimate how many tokens the provider will charge for this document.

    A document is extracted in chunks, and each chunk is a separate request
    that is charged against the same daily budget. The estimate is used to work
    out how long the budget has to refill before the document can be extracted
    in one go, so it is deliberately generous: over-estimating only lengthens
    the wait, while under-estimating means the provider refuses the later
    chunks of a document whose earlier chunks were already paid for.

    Spreadsheets are parsed by the deterministic tabular path and never reach
    the model, so they cost nothing.
    """
    if path.suffix.lower() != ".pdf":
        return 0
    try:
        import pymupdf as fitz

        with fitz.open(path) as doc:
            pages = [page.get_text("text") or "" for page in doc]
    except Exception:
        return 0

    chars = sum(len(text) for text in pages)
    # The extractor groups pages into chunks of at most `chunk_chars`
    # characters, so a page counts as at least one chunk and a long page as
    # several.
    chunks = sum(max(1, -(-len(text) // chunk_chars)) for text in pages if text)
    est_input = chars / 4.0 + PER_CHUNK_OVERHEAD_TOKENS * chunks
    return int(TOKEN_COST_FACTOR * est_input + TOKEN_COST_FLOOR)


def main() -> int:
    global BASE

    ap = argparse.ArgumentParser(description="Bulk ingest SFIC_DATASET into ATLAS.")
    ap.add_argument("--kind", choices=["pdf", "xlsx", "all"], default="all")
    ap.add_argument("--cases", nargs="*", default=None, help="Limit to these case ids.")
    ap.add_argument("--max-files", type=int, default=0, help="Stop after N files (0 = no limit).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true", help="Ignore the resume state.")
    ap.add_argument(
        "--base",
        default=BASE,
        help="Base URL of the ATLAS API (default %(default)s).",
    )
    ap.add_argument(
        "--shard",
        type=int,
        default=0,
        help="Index of this worker's shard of the dataset (0-based).",
    )
    ap.add_argument(
        "--num-shards",
        type=int,
        default=1,
        help="How many shards the dataset is split into (default %(default)s).",
    )
    ap.add_argument(
        "--chunk-chars",
        type=int,
        default=12000,
        help=(
            "The server's LLM_CHUNK_CHARS, used to estimate how many tokens a "
            "document costs. Default %(default)s."
        ),
    )
    args = ap.parse_args()

    BASE = args.base.rstrip("/")
    chunk_chars = args.chunk_chars

    if args.num_shards < 1 or not (0 <= args.shard < args.num_shards):
        print("[fatal] --shard must be in [0, --num-shards)", file=sys.stderr)
        return 2

    if not DATASET.is_dir():
        print(f"[fatal] dataset not found: {DATASET}", file=sys.stderr)
        return 2

    case_dirs = sorted(p for p in DATASET.iterdir() if p.is_dir())
    if args.cases:
        wanted = {c.upper() for c in args.cases}
        case_dirs = [p for p in case_dirs if p.name.upper() in wanted]
    if not case_dirs:
        print("[fatal] no matching case directories", file=sys.stderr)
        return 2

    exts = {".pdf"} if args.kind == "pdf" else {".xlsx", ".xls"} if args.kind == "xlsx" else {".pdf", ".xlsx", ".xls"}

    groups: List[List[Tuple[str, Path]]] = []
    for cd in case_dirs:
        files = sorted(p for p in cd.iterdir() if p.is_file() and p.suffix.lower() in exts)
        if files:
            groups.append([(cd.name, f) for f in files])

    total = sum(len(g) for g in groups)
    print(f"[plan] {total} files across {len(groups)} cases", flush=True)

    if args.dry_run:
        for g in groups:
            print(f"  {g[0][0]}: {len(g)} files")
        return 0

    login()

    done: Dict[str, set[str]] = {}
    stale: Dict[str, Dict[str, str]] = {}
    if not args.reset:
        for g in groups:
            cid = g[0][0]
            try:
                usable, bad = existing_evidence(cid)
            except Exception as exc:
                print(f"[warn] could not read existing evidence for {cid}: {exc}", flush=True)
                usable, bad = set(), {}
            done[cid] = usable
            stale[cid] = bad
        skipped = sum(1 for g in groups for c, f in g if f.name in done.get(c, set()))
        n_stale = sum(len(v) for v in stale.values())
        if skipped:
            print(f"[resume] {skipped} file(s) already extracted, skipping them", flush=True)
        if n_stale:
            print(f"[resume] {n_stale} file(s) recorded with no mentions, will reprocess", flush=True)

    processed = 0
    failures = 0
    limited = False
    started = time.time()
    attempts: Dict[Tuple[str, str], int] = {}
    waited: Dict[Tuple[str, str], float] = {}

    # The round-robin order is deterministic, so sharding on the position in
    # that order is stable across runs: a worker always picks up the same
    # files it picked up before, which is what makes the resume work.
    ordered = list(round_robin(groups))
    if args.num_shards > 1:
        print(
            f"[shard] worker {args.shard}/{args.num_shards} owns "
            f"{len(ordered) // args.num_shards + (1 if args.shard < len(ordered) % args.num_shards else 0)} "
            f"of {len(ordered)} files",
            flush=True,
        )
        ordered = [item for i, item in enumerate(ordered) if i % args.num_shards == args.shard]
    queue = deque(ordered)
    while queue:
        case_id, path = queue.popleft()
        if args.max_files and processed >= args.max_files:
            print(f"[stop] reached --max-files={args.max_files}", flush=True)
            break
        if path.name in done.get(case_id, set()):
            continue

        key = (case_id, path.name)
        attempts[key] = attempts.get(key, 0) + 1

        stale_id = stale.get(case_id, {}).get(path.name)
        if stale_id and delete_evidence(stale_id):
            print(f"[retry] removed the empty record for {case_id}/{path.name}", flush=True)

        t0 = time.time()
        try:
            item = upload(case_id, path)
        except Exception as exc:
            failures += 1
            print(f"[error] {case_id}/{path.name}: {exc}", flush=True)
            time.sleep(2)
            continue

        processed += 1
        done.setdefault(case_id, set()).add(path.name)
        job = item.get("job", {}) or {}
        mentions = job.get("mention_count") or 0
        if mentions:
            print(
                f"[ok] {case_id}/{path.name}  {summarize(item)}  {time.time()-t0:.1f}s",
                flush=True,
            )
        else:
            print(
                f"[fail] {case_id}/{path.name}  no mentions extracted  "
                f"{time.time()-t0:.1f}s",
                flush=True,
            )

        if not is_rate_limited(item):
            if not mentions:
                failures += 1
            continue

        failures += 1
        hint = retry_hint_seconds(item)
        evidence_id = item.get("evidence_id")
        total_wait = waited.get(key, 0.0)
        # The provider's hint covers the chunk that was refused. The document
        # needs room for every one of its chunks, so the wait is extended by the
        # time it takes the budget to refill with the document's own cost -
        # otherwise the next attempt pays for the first chunk again and is
        # refused at the second one, for ever.
        doc_tokens = estimate_document_tokens(path, chunk_chars)
        extra_wait = doc_tokens / BUDGET_REFILL_TOKENS_PER_S
        if (
            hint is not None
            and hint <= MAX_QUOTA_WAIT_S
            and attempts[key] < MAX_QUOTA_RETRIES
            and total_wait < MAX_QUOTA_WAIT_TOTAL_S
        ):
            # The provider told us when its budget frees up. Wait exactly that
            # long and run the same file again rather than stopping the whole
            # ingest after one refusal.
            if evidence_id:
                delete_evidence(evidence_id)
            wait = hint + extra_wait
            waited[key] = total_wait + wait
            print(
                f"[wait] provider budget exhausted; waiting {wait:.0f}s "
                f"(provider hint {hint:.0f}s + {extra_wait:.0f}s for the "
                f"{doc_tokens} remaining tokens of {case_id}/{path.name}) "
                f"(attempt {attempts[key]}/{MAX_QUOTA_RETRIES}, "
                f"waited {waited[key]/60:.0f}min so far)",
                flush=True,
            )
            done[case_id].discard(path.name)
            queue.appendleft((case_id, path))
            time.sleep(wait + 5)
            continue

        print(
            "[stop] the provider refused the request (rate/quota limit) and no "
            "usable retry hint was given. Stopping instead of hammering it.",
            flush=True,
        )
        limited = True
        break

    elapsed = time.time() - started
    print(
        f"[done] processed={processed} errors={failures} elapsed={elapsed/60:.1f}min "
        f"rate_limited={limited}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
