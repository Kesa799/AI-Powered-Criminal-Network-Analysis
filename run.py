import uvicorn
import os
import sys

# Ensure current project directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Use Selector event loop on Windows to prevent WinError 64 IOCP connection resets.
# On Linux (Render), standard auto/uvloop is used.
extra_run_kwargs = {}
if sys.platform == "win32":
    try:
        import atlas_loop
        atlas_loop.atlas_loop_factory()
        if hasattr(uvicorn.config, "LOOP_SETUPS") and "atlas_loop:atlas_loop_factory" in uvicorn.config.LOOP_SETUPS:
            extra_run_kwargs["loop"] = "atlas_loop:atlas_loop_factory"
    except Exception:
        pass

# The port is configurable via PORT (Render, Heroku) or ATLAS_PORT.
PORT = int(os.getenv("PORT", os.getenv("ATLAS_PORT", "8000")))
HOST = os.getenv("ATLAS_HOST", "0.0.0.0")

if __name__ == "__main__":
    print("=" * 60)
    print("  ATLAS Criminal Network Intelligence & Forensic Analysis API")
    print("  Member 2: Backend, Database & Application Management")
    print("=" * 60)
    print(f"  Serving API & Frontend at: http://127.0.0.1:{PORT}")
    print(f"  Interactive Swagger Docs at: http://127.0.0.1:{PORT}/docs")
    print("=" * 60)
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        **extra_run_kwargs,
    )
