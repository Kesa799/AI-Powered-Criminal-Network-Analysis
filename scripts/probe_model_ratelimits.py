"""Compare the rate-limit envelope Groq enforces per model.

Uses the SDK's raw-response path so the rate-limit headers are visible, and
issues a real ATLAS-schema request so the provider's expected-output estimate
(which is what its output-token-per-minute pre-flight check uses) is realistic.
"""
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
client = OpenAI(
    api_key=cfg.GROQ_API_KEY.get_secret_value(),
    base_url="https://api.groq.com/openai/v1",
    timeout=180,
    max_retries=0,
)

captured = {}
_orig = OpenAiAdapter._call_raw


def spy(self, system, user, schema):
    captured["system"] = system
    captured["user"] = user
    raise SystemExit(0)


OpenAiAdapter._call_raw = spy
from atlas.pipeline.runner import PipelineRunner

pdf = ROOT.parent / "SFIC_DATASET" / "CASE_001" / "FORENSIC_DEVICE_CASE_001.pdf"
try:
    PipelineRunner(settings=cfg).run(
        case_id="CASE_001", file_paths=[pdf], provider="groq", model_version=cfg.LLM_MODEL
    )
except SystemExit:
    pass
finally:
    OpenAiAdapter._call_raw = _orig

system, user = captured["system"], captured["user"]

for model in ("openai/gpt-oss-120b", "qwen/qwen3.8-27b"):
    for max_out in (4096, 8192):
        print(f"\n=== {model} max_out={max_out} ===", flush=True)
        t0 = time.time()
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "model_output", "strict": True, "schema": MODEL_SCHEMA},
                },
                temperature=0.0,
                max_completion_tokens=max_out,
            )
            resp = raw.http_response
            r = raw.parse()
            u = r.usage
            print(f"  OK {time.time()-t0:.1f}s completion={u.completion_tokens} prompt={u.prompt_tokens}")
            for k, v in sorted(resp.headers.items()):
                if "ratelimit" in k.lower() or "retry" in k.lower():
                    print(f"    {k}: {v}")
        except Exception as exc:
            resp = getattr(exc, "response", None)
            body = ""
            hdrs = {}
            if resp is not None:
                hdrs = resp.headers
                try:
                    body = resp.text
                except Exception:
                    pass
            print(f"  ERR {time.time()-t0:.1f}s {body[:330]}")
            for k, v in sorted(hdrs.items()):
                if "ratelimit" in k.lower() or "retry" in k.lower():
                    print(f"    {k}: {v}")
        time.sleep(3)
