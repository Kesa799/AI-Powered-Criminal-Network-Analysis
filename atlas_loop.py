"""Event loop factory for ATLAS.

uvicorn's built-in ``asyncio`` loop factory selects ``ProactorEventLoop`` on
Windows. That loop's IOCP-based accept path raises ``OSError: [WinError 64]
The specified network name is no longer available`` when a client resets a
connection, and the server then silently stops accepting new connections while
the process stays alive -- requests are refused even though nothing crashed.

``SelectorEventLoop`` does not have that failure mode, so ATLAS uses it on
Windows. Linux and macOS use standard event loop implementations.

Usage:
    uvicorn backend.main:app
"""
from __future__ import annotations

import asyncio
import sys
import uvicorn.config


def atlas_loop_factory(use_subprocess: bool = False) -> None:
    """Return the event loop uvicorn should use for this process."""
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass


# Safely register in uvicorn's LOOP_SETUPS if available on this platform/version
if hasattr(uvicorn.config, "LOOP_SETUPS"):
    try:
        uvicorn.config.LOOP_SETUPS["atlas_loop:atlas_loop_factory"] = "atlas_loop:atlas_loop_factory"
    except Exception:
        pass
