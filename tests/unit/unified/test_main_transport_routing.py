"""`noble-agent` CLI entry routing.

Regression guard for the deploy bug where the `agent-lk` container ran the
WebSocket server (`run_server`, port `ws_port`) instead of the LiveKit worker
(`run_worker`), so both `agent` and `agent-lk` fought over the same host port
under `network_mode: host`. `main()` must dispatch on `TRANSPORT_BACKEND`:
`livekit` → `run_worker`, anything else → `run_server`.
"""

from __future__ import annotations

import sys

import noble_agent.__main__ as main_mod
import noble_agent.server.http as http_mod
import noble_agent.transport.livekit.worker as worker_mod
from noble_agent.config import reset_settings_for_tests


def _patch_entrypoints(monkeypatch) -> list[str]:
    """Replace both blocking entrypoints with recorders; return the call log."""
    calls: list[str] = []
    monkeypatch.setattr(http_mod, "run_server", lambda: calls.append("server"))
    monkeypatch.setattr(worker_mod, "run_worker", lambda: calls.append("worker"))
    return calls


def test_main_routes_livekit_transport_to_worker(monkeypatch):
    # Mirrors the agent-lk compose command: `noble-agent --transport livekit start`.
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    monkeypatch.setattr(sys, "argv", ["noble-agent", "--transport", "livekit", "start"])
    reset_settings_for_tests()
    calls = _patch_entrypoints(monkeypatch)

    main_mod.main()

    assert calls == ["worker"]
    reset_settings_for_tests()


def test_main_routes_aiortc_transport_to_server(monkeypatch):
    # Mirrors the agent compose command: `noble-agent --no-reload`.
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    monkeypatch.setenv("TRANSPORT_BACKEND", "aiortc")
    monkeypatch.setattr(sys, "argv", ["noble-agent", "--no-reload"])
    reset_settings_for_tests()
    calls = _patch_entrypoints(monkeypatch)

    main_mod.main()

    assert calls == ["server"]
    reset_settings_for_tests()
