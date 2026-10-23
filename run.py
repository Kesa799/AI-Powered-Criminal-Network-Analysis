import uvicorn
import os
import sys

# Ensure current project directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Use the Selector event loop on every platform. uvicorn otherwise picks
# ProactorEventLoop on Windows, which silently stops accepting connections
# after a client reset (WinError 64). See atlas_loop.py for details.
import atlas_loop
atlas_loop.atlas_loop_factory()
LOOP_FACTORY = "atlas_loop:atlas_loop_factory"

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
        loop=LOOP_FACTORY,
    )
