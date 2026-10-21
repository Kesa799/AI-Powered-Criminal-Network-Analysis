"""Find which Groq models can actually complete ATLAS strict-schema extraction.

Captures the real (system, user) prompt the pipeline builds for a dataset
PDF, then replays it against every model the account can reach, with and
without the json_schema response_format and with an explicit
max_completion_tokens (Groq's default can truncate a schema-valid document
mid-object and report the truncation as a schema validation failure).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "member3" / "SFIC_Doc_Module" / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from openai import OpenAI
from atlas.config import get_settings
from atlas.llm.openai_adapter import OpenAiAdapter
from atlas.contracts.model_schema import MODEL_SCHEMA

cfg = get_settings(reload=True)
key = cfg.GROQ_API_KEY.get_secret_value()
client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=120)

# --- capture the real prompt the pipeline would send -------------------------
captured = {}
_orig = OpenAiAdapter._call_raw


def spy(self, system, user, schema):
    captured["system"] = system
    captured["user"] = user
    raise SystemExit(0)


OpenAiAdapter._call_raw = spy

from atlas.pipeline.runner import PipelineRunner

pdf = ROOT.parent / "SFIC_DATASET" / "CASE_001" / "FORENSIC_DEVICE_CASE_001.pdf"
runner = PipelineRunner(settings=cfg)
try:
    runner.run(case_id="CASE_001", file_paths=[pdf], provider="groq", model_version=cfg.LLM_MODEL)
except SystemExit:
    pass
except Exception as exc:
    print(f"[capture] fallback path: {type(exc).__name__}: {exc}")

OpenAiAdapter._call_raw = _orig

if "user" not in captured:
    print("[capture] FAILED - no prompt captured")
    raise SystemExit(1)

system, user = captured["system"], captured["user"]
print(f"[capture] system_len={len(system)} user_len={len(user)}\n", flush=True)

# --- list every model the key can reach --------------------------------------
models = [m.id for m in client.models.list().data]
print(f"[capture] {len(models)} models reachable\n", flush=True)

MAX_OUT = int(sys.argv[1]) if len(sys.argv) > 1 else 8192

results = []
for m in models:
    for mode in ("json_schema", "plain"):
        kw = {}
        if mode == "json_schema":
            kw["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "model_output",
                    "strict": True,
                    "schema": MODEL_SCHEMA,
                },
            }
        if MAX_OUT:
            kw["max_completion_tokens"] = MAX_OUT
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                **kw,
            )
            content = r.choices[0].message.content or ""
            finish = r.choices[0].finish_reason
            try:
                parsed = json.loads(content)
                n = len(parsed.get("mentions", []))
                ok = f"json ok, mentions={n}, finish={finish}, len={len(content)}"
                status = "PASS" if n > 0 else "WEAK"
            except Exception:
                ok = f"NOT JSON ({len(content)} chars, finish={finish})"
                status = "WEAK"
        except Exception as exc:
            status = "FAIL"
            ok = f"{type(exc).__name__}: {str(exc).replace(chr(10), ' ')[:150]}"
        dt = time.time() - t0
        results.append((status, m, mode, f"{dt:.1f}s", ok))
        print(f"{status:5} {m:34} {mode:12} {dt:6.1f}s  {ok}", flush=True)

print("\n=== usable ===")
for status, m, mode, dt, ok in results:
    if status == "PASS":
        print(f"  {m} [{mode}] {dt}")
