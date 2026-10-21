"""Report how much of the SFIC_DATASET is already extracted by the model.

Prints one line per case with the number of dataset files recorded, how many
of those carry model-derived mentions, and how many files are still pending.
Read-only: it never touches the database or the provider.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest_dataset as ing  # noqa: E402

DATASET = ing.DATASET


def main() -> int:
    ing.login()
    total_files = 0
    total_done = 0
    pending: list[str] = []
    for case_dir in sorted(p for p in DATASET.iterdir() if p.is_dir()):
        case_id = case_dir.name
        files = sorted(
            p for p in case_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".pdf", ".xlsx"}
        )
        rel = {str(p.relative_to(case_dir)).replace("\\", "/") for p in files}
        usable, stale = ing.existing_evidence(case_id)
        done = {name for name in rel if name in usable}
        missing = sorted(rel - done)
        total_files += len(rel)
        total_done += len(done)
        pending.extend(f"{case_id}/{name}" for name in missing)
        print(
            f"{case_id}: {len(done)}/{len(rel)} extracted"
            + (f"  stale={len(stale)}" if stale else "")
            + (f"  pending={len(missing)}" if missing else "")
        )
    print(f"\nTOTAL {total_done}/{total_files} extracted; {len(pending)} pending")
    for item in pending:
        print(f"  pending: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
