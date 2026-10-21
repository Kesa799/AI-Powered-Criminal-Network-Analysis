"""Sanity checks for the LLM pacing wiring (run from the project root)."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "member3" / "SFIC_Doc_Module" / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from atlas.config import get_settings
from atlas.llm.client import _build_rate_limiter, get_llm_client

cfg = get_settings(reload=True)
print(f"model        = {cfg.LLM_MODEL}")
print(f"max_out      = {cfg.LLM_MAX_COMPLETION_TOKENS}")
print(f"rpm          = {cfg.LLM_MAX_REQUESTS_PER_MINUTE}")
print(f"min_interval = {cfg.LLM_MIN_INTERVAL_S}")

a = _build_rate_limiter(cfg)
b = _build_rate_limiter(cfg)
print(f"limiter cached across calls = {a is b}")
print(f"effective min_interval      = {a.min_interval_s}")
print(f"window requests             = {a.max_requests} per {a.window_s}s")

client = get_llm_client(settings=cfg)
print(f"client model                = {client.model_name}")
print(f"client limiter is cached    = {client._rate_limiter is a}")

# The limiter must actually wait between calls.
t0 = time.monotonic()
a.acquire()
first = time.monotonic() - t0
t0 = time.monotonic()
a.acquire()
second = time.monotonic() - t0
print(f"first acquire  = {first:.2f}s (expected ~0)")
print(f"second acquire = {second:.2f}s (expected >= {a.min_interval_s})")
assert second >= a.min_interval_s - 0.5, "limiter did not enforce the minimum interval"
print("OK")
