"""Phoenix (self-hosted OTEL) LLM-tracing unit tests.

All offline — `phoenix.otel` + the openinference instrumentors are NOT
installed, so every test that reaches the heavy path injects mock modules
into `sys.modules` first. No live collector is ever contacted.

Design notes the tests pin as regression guards:
  - `batch=True` on `register(...)` → background BatchSpanProcessor (never
    a synchronous SimpleSpanProcessor blocking the LLM hot path).
  - empty `phoenix_collector_endpoint` → clean no-op, `register` never called.
  - idempotent per-process init (`_initialized` flag).
  - any init failure is swallowed (log + return False), never aborts boot.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from noble_agent.config import UnifiedSettings


def _default(name: str):
    """Class-level field default — independent of any live `.env` override."""
    return UnifiedSettings.model_fields[name].default


# ─────────────────────────── Step 1: config fields ────────────────────────────


def test_phoenix_settings_defaults():
    assert _default("phoenix_collector_endpoint") == ""
    assert _default("phoenix_api_key") == ""
    assert _default("phoenix_project_name") == "noble-voice-agent"


def test_phoenix_env_alias(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://host:6006")
    monkeypatch.setenv("PHOENIX_API_KEY", "abc123")
    s = UnifiedSettings(_env_file=None)
    assert s.phoenix_collector_endpoint == "http://host:6006"
    assert s.phoenix_api_key == "abc123"


# ─────────────────────────── init_tracing helpers ─────────────────────────────


class _SettingsStub:
    """Minimal duck-type stand-in for UnifiedSettings — only the fields
    `init_tracing` reads."""

    def __init__(self, endpoint: str = "", api_key: str = "", project_name: str = "noble-voice-agent"):
        self.phoenix_collector_endpoint = endpoint
        self.phoenix_api_key = api_key
        self.phoenix_project_name = project_name


def _install_phoenix_mocks(monkeypatch):
    """Inject mock `phoenix.otel` + openinference instrumentor modules into
    sys.modules so the function-local imports inside `init_tracing` resolve
    without the real (uninstalled) `tracing` extra.

    Returns (register_mock, anthropic_instr_cls, openai_instr_cls).
    """
    register = MagicMock(name="register", return_value="TRACER_PROVIDER")

    phoenix_pkg = types.ModuleType("phoenix")
    phoenix_otel = types.ModuleType("phoenix.otel")
    phoenix_otel.register = register
    phoenix_pkg.otel = phoenix_otel

    anthropic_instr_cls = MagicMock(name="AnthropicInstrumentor")
    openai_instr_cls = MagicMock(name="OpenAIInstrumentor")

    oi_pkg = types.ModuleType("openinference")
    oi_instr_pkg = types.ModuleType("openinference.instrumentation")
    oi_anthropic = types.ModuleType("openinference.instrumentation.anthropic")
    oi_anthropic.AnthropicInstrumentor = anthropic_instr_cls
    oi_openai = types.ModuleType("openinference.instrumentation.openai")
    oi_openai.OpenAIInstrumentor = openai_instr_cls
    oi_instr_pkg.anthropic = oi_anthropic
    oi_instr_pkg.openai = oi_openai
    oi_pkg.instrumentation = oi_instr_pkg

    for name, mod in {
        "phoenix": phoenix_pkg,
        "phoenix.otel": phoenix_otel,
        "openinference": oi_pkg,
        "openinference.instrumentation": oi_instr_pkg,
        "openinference.instrumentation.anthropic": oi_anthropic,
        "openinference.instrumentation.openai": oi_openai,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return register, anthropic_instr_cls, openai_instr_cls


@pytest.fixture(autouse=True)
def _reset_tracing_flag():
    """Reset the per-process `_initialized` flag around every test so the
    module state doesn't leak between cases."""
    from noble_agent.observability import phoenix_tracing

    phoenix_tracing.reset_tracing_for_tests()
    yield
    phoenix_tracing.reset_tracing_for_tests()


@pytest.fixture()
def _clean_settings_singleton():
    """Seed the config singleton from env only (no `.env`), then restore.

    The repo's live `.env` (unrelated in-flight work) currently has
    inline-comment lines that break `UnifiedSettings()` parsing; the wiring
    tests must not depend on it. Build with `_env_file=None` so only real env
    vars are read."""
    import noble_agent.config as cfg

    saved = cfg._settings
    cfg._settings = UnifiedSettings(_env_file=None)
    yield
    cfg._settings = saved


# ─────────────────────────── Step 2: no-op when unset ─────────────────────────


def test_init_tracing_noop_when_unset(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    assert phoenix_tracing.init_tracing(_SettingsStub(endpoint="")) is False
    register.assert_not_called()


def test_init_tracing_noop_when_whitespace(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    assert phoenix_tracing.init_tracing(_SettingsStub(endpoint="   ")) is False
    register.assert_not_called()


# ─────────────── Step 3: enabled path registers + instruments ─────────────────


def test_init_tracing_registers_and_instruments(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, anthropic_cls, openai_cls = _install_phoenix_mocks(monkeypatch)
    stub = _SettingsStub(endpoint="http://10.50.12.70:6006", api_key="SECRET")

    assert phoenix_tracing.init_tracing(stub) is True

    register.assert_called_once()
    _, kwargs = register.call_args
    assert kwargs["batch"] is True  # regression guard: background export, NOT sync
    assert kwargs["endpoint"] == "http://10.50.12.70:6006/v1/traces"
    assert kwargs["headers"] == {"Authorization": "Bearer SECRET"}
    assert kwargs["project_name"] == "noble-voice-agent"

    anthropic_cls.return_value.instrument.assert_called_once_with(tracer_provider="TRACER_PROVIDER")
    openai_cls.return_value.instrument.assert_called_once_with(tracer_provider="TRACER_PROVIDER")


# ─────────────── Step 4: endpoint normalization + empty-key header ────────────


def test_endpoint_appends_v1_traces(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    phoenix_tracing.init_tracing(_SettingsStub(endpoint="http://host:6006/"))
    assert register.call_args.kwargs["endpoint"] == "http://host:6006/v1/traces"


def test_endpoint_already_has_v1_traces_unchanged(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    phoenix_tracing.init_tracing(_SettingsStub(endpoint="http://host:6006/v1/traces"))
    assert register.call_args.kwargs["endpoint"] == "http://host:6006/v1/traces"


def test_no_auth_header_when_key_empty(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    assert phoenix_tracing.init_tracing(_SettingsStub(endpoint="http://host:6006", api_key="")) is True
    assert register.call_args.kwargs["headers"] == {}


# ─────────────────────────── Step 5: idempotency ──────────────────────────────


def test_init_tracing_idempotent(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    stub = _SettingsStub(endpoint="http://host:6006", api_key="K")
    assert phoenix_tracing.init_tracing(stub) is True
    assert phoenix_tracing.init_tracing(stub) is True
    register.assert_called_once()


# ─────────────────────── Step 6: failure never aborts boot ────────────────────


def test_init_tracing_swallows_errors(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    register, _, _ = _install_phoenix_mocks(monkeypatch)
    register.side_effect = RuntimeError("collector unreachable")
    assert phoenix_tracing.init_tracing(_SettingsStub(endpoint="http://host:6006")) is False


def test_init_tracing_handles_missing_dep(monkeypatch):
    from noble_agent.observability import phoenix_tracing

    # Simulate the `tracing` extra not installed: importing phoenix.otel raises.
    monkeypatch.setitem(sys.modules, "phoenix", None)
    monkeypatch.setitem(sys.modules, "phoenix.otel", None)
    assert phoenix_tracing.init_tracing(_SettingsStub(endpoint="http://host:6006")) is False


# ─────────────────────── Step 7: transport wiring ─────────────────────────────


def test_prewarm_calls_init_tracing(monkeypatch, _clean_settings_singleton):
    """LiveKit `_prewarm` (runs once per job-subprocess) must call
    `init_tracing` exactly once so each traced process registers its provider."""
    import noble_agent.agent.rag.flat_store_adapter as flat_adapter_mod
    import noble_agent.observability.phoenix_tracing as tracing_mod
    import noble_agent.transport.livekit.worker as worker_mod
    import noble_agent.voice.gender_detector as gender_mod
    import noble_agent.voice.prewarm as voice_prewarm_mod
    import noble_agent.voice.vad as vad_mod

    # No-op the non-tracing heavy prewarm loads (mirror test_worker_prewarm).
    monkeypatch.setattr(vad_mod, "SileroVAD", lambda *a, **k: object())
    monkeypatch.setattr(gender_mod.GenderDetector, "get_instance", classmethod(lambda cls: object()))
    monkeypatch.setattr(voice_prewarm_mod, "prewarm_voice_models", lambda: None)

    async def _noop_flat_store():
        return None

    monkeypatch.setattr(flat_adapter_mod, "_ensure_flat_store", _noop_flat_store)

    calls: list[object] = []
    monkeypatch.setattr(tracing_mod, "init_tracing", lambda s: calls.append(s) or True)

    class _FakeJobProcess:
        pass

    worker_mod._prewarm(_FakeJobProcess())

    assert len(calls) == 1


class _StopBoot(Exception):
    """Sentinel raised from the stubbed serve() to short-circuit boot."""


async def test_http_startup_calls_init_tracing(monkeypatch, _clean_settings_singleton):
    """aiortc `_run_server_async` must call `init_tracing(settings)` at boot.

    `_run_server_async` imports its collaborators function-locally, so we patch
    them at their source modules (the import seam)."""
    import websockets.asyncio.server as ws_server

    import noble_agent.observability.phoenix_tracing as tracing_mod
    import noble_agent.server.http as http_mod
    import noble_agent.storage.connection as conn_mod
    import noble_agent.voice.prewarm as prewarm_mod

    calls: list[object] = []
    monkeypatch.setattr(tracing_mod, "init_tracing", lambda s: calls.append(s) or True)

    class _FakeCM:
        async def initialize(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(conn_mod, "get_connection_manager", lambda: _FakeCM())
    monkeypatch.setattr(prewarm_mod, "prewarm_voice_models", lambda: None)

    # Short-circuit the boot right after the init sequence so no real socket
    # is opened (tracing init happens before serve()).
    def _boom_serve(*a, **k):
        raise _StopBoot

    monkeypatch.setattr(ws_server, "serve", _boom_serve)

    with pytest.raises(_StopBoot):
        await http_mod._run_server_async()

    assert len(calls) == 1
