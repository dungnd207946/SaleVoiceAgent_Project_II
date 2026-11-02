"""CLI entry: dispatches to unified server when USE_UNIFIED_AGENT=true,
otherwise falls back to the legacy noble_agent.__main__."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_src_path() -> None:
    """Add src/ to sys.path when running from repo root without pip install."""
    src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if src not in sys.path:
        sys.path.insert(0, src)


def _apply_transport_flag() -> None:
    """Honour `--transport={aiortc,livekit}` by setting TRANSPORT_BACKEND env
    before any config import reads it. Mirrors legacy noble_agent.__main__.
    """
    argv = sys.argv
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--transport="):
            os.environ["TRANSPORT_BACKEND"] = arg.split("=", 1)[1]
            del argv[i]
            return
        if arg == "--transport" and i + 1 < len(argv):
            os.environ["TRANSPORT_BACKEND"] = argv[i + 1]
            del argv[i : i + 2]
            return
        i += 1


def _load_dotenv() -> None:
    """Load repo-root `.env` into `os.environ` so `os.getenv(...)` calls
    everywhere see the same values pydantic-settings reads. Walks up from
    this file to find the nearest `.env`. `override=False` keeps shell
    exports and CLI flags higher priority than `.env`.
    """
    try:
        from dotenv import load_dotenv as _ld
    except ImportError:
        return
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            _ld(candidate, override=False)
            return


def main() -> None:
    _ensure_src_path()
    _apply_transport_flag()
    _load_dotenv()

    from noble_agent.config import get_settings

    settings = get_settings()
    if not settings.use_unified_agent:
        raise SystemExit(
            "USE_UNIFIED_AGENT must be true: the legacy multi-agent path has been "
            "removed. Set USE_UNIFIED_AGENT=true in your .env."
        )

    # The LiveKit transport runs a worker that registers OUTBOUND to
    # livekit-server (no public listener) — NOT the WebSocket server. Routing
    # both transports through run_server() made the agent-lk container bind
    # ws_port too, colliding with the agent container under network_mode: host.
    if settings.transport_backend == "livekit":
        from noble_agent.transport.livekit.worker import run_worker

        run_worker()
    else:
        from noble_agent.server.http import run_server

        run_server()


if __name__ == "__main__":
    main()
