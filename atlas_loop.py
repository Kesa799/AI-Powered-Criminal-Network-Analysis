"""Event loop factory for ATLAS.

uvicorn's built-in ``asyncio`` loop factory selects ``ProactorEventLoop`` on
Windows. That loop's IOCP-based accept path raises ``OSError: [WinError 64]
The specified network name is no longer available`` when a client resets a
connection, and the server then silently stops accepting new connections while
the process stays alive -- requests are refused even though nothing crashed.

``SelectorEventLoop`` does not have that failure mode, so ATLAS uses it on
every platform. It is also what uvicorn already uses on Linux/macOS, so the
behaviour is consistent across environments.

Usage:
    uvicorn backend.main:app --loop atlas_loop:atlas_loop_factory
"""
from __future__ import annotations

import asyncio


def atlas_loop_factory(use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """Return the event loop uvicorn should use for this process."""
    return asyncio.SelectorEventLoop()
