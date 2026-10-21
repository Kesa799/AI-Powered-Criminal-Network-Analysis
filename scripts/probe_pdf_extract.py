"""Run the ATLAS member3 extraction pipeline on one file and print any raw
provider error body (not just the SDK's generic exception text).

Usage:
    python scripts/probe_pdf_extract.py <path-to-pdf> [model]

The OpenAI SDK swallows the provider's JSON error body behind a generic
BadRequestError, which makes provider-side failures such as Groq's
`json_validate_failed` indistinguishable from a malformed request. This
script patches the SDK transport to surface the body.
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "member3" / "SFIC_Doc_Module" / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import openai
from openai import OpenAI

_orig_post = OpenAI.post


def patched_post(self, *args, **kwargs):
    try:
        return _orig_post(self, *args, **kwargs)
    except openai.APIStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        print(f"  !! HTTP {exc.status_code}: {body[:1200]}", flush=True)
        raise


OpenAI.post = patched_post

from atlas.config import get_settings
from atlas.pipeline.runner import PipelineRunner


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    target = Path(sys.argv[1]).resolve()
    model = sys.argv[2] if len(sys.argv) > 2 else ""

    cfg = get_settings(reload=True)
    model = model or cfg.LLM_MODEL
    print(f"[probe] file={target.name} model={model} exists={target.exists()}", flush=True)

    case_id = target.parent.name
    runner = PipelineRunner(settings=cfg)
    try:
        res = runner.run(
            case_id=case_id,
            file_paths=[target],
            provider="groq",
            model_version=model,
        )
    except Exception as exc:
        print(f"[probe] FAILED: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return 1

    print(
        f"[probe] mentions={len(res.mentions)} relationships={len(res.relationships)} "
        f"events={len(res.events)} rejections={len(res.rejections)}",
        flush=True,
    )
    for w in res.warnings or []:
        print(f"  WARN {w}", flush=True)
    for rej in res.rejections:
        print(f"  REJ {getattr(rej, 'kind', None)}: {getattr(rej, 'reason', None)}", flush=True)
    for m in res.mentions:
        t = getattr(m.type, "value", m.type)
        print(f"  mention [{t}] {m.normalized_value}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
