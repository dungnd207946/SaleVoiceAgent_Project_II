"""LiveKit worker `_prewarm` TTS warm-up + idle-process regression guards.

`_prewarm` runs once per job-process at worker boot, BEFORE any caller is
dispatched. Loading the santa-tts (vieneu) backbone there moves the ~40s
model load off the per-call hot path so the first greeting isn't silent.

These tests are all sync (`_prewarm` is sync) and monkeypatch every heavy
collaborator (SileroVAD, GenderDetector, FlatStore/qdrant ensure, and the
vieneu loader) so no real model / GPU / `tts-vieneu` optional dep is needed.
They copy the recorder + `reset_settings_for_tests()` style from
`test_main_transport_routing.py`.
"""

from __future__ import annotations

import noble_agent.transport.livekit.worker as worker_mod
import noble_agent.voice.prewarm as prewarm_mod
import noble_agent.voice.tts.vieneu as vieneu_mod
from noble_agent.config import get_settings, reset_settings_for_tests


class _FakeJobProcess:
    """Stand-in for `livekit.agents.JobProcess` — `_prewarm` ignores it."""


def _resync_prewarm_settings(monkeypatch) -> None:
    """Re-bind `prewarm.py`'s module-level `settings` to the freshly-reset instance.

    `voice/prewarm.py` binds `settings = get_settings()` at import time (not a live
    proxy), so the TTS-backend gate reads whatever settings existed the first time
    the module was imported. In-session that's a prior test's (or the repo `.env`'s)
    settings, so `reset_settings_for_tests()` + env monkeypatch alone doesn't reach
    it. Rebinding here makes `prewarm_voice_models()` read this test's config.
    """
    monkeypatch.setattr(prewarm_mod, "settings", get_settings())


def _stub_heavy_collaborators(monkeypatch) -> None:
    """No-op the non-TTS heavy prewarm loads so the test is fast + offline.

    `_prewarm` imports these function-locally, so patching the import
    targets at their source modules is the seam.
    """
    import noble_agent.agent.rag.flat_store_adapter as flat_adapter_mod
    import noble_agent.voice.gender_detector as gender_mod
    import noble_agent.voice.vad as vad_mod

    monkeypatch.setattr(vad_mod, "SileroVAD", lambda *a, **k: object())
    monkeypatch.setattr(gender_mod.GenderDetector, "get_instance", classmethod(lambda cls: object()))

    async def _noop_flat_store():
        return None

    monkeypatch.setattr(flat_adapter_mod, "_ensure_flat_store", _noop_flat_store)


def _patch_loader(monkeypatch) -> list[int]:
    """Replace `vieneu._load_tts` with a call-counter recorder; return the log."""
    calls: list[int] = []

    def _recorder():
        calls.append(1)
        return (object(), object())

    monkeypatch.setattr(vieneu_mod, "_load_tts", _recorder)
    return calls


def test_prewarm_warms_vieneu_tts_once(monkeypatch):
    """(a) backend resolves to vieneu → `_load_tts` called exactly once."""
    monkeypatch.setenv("TTS_BACKEND", "vieneu")
    monkeypatch.setenv("SMART_TURN_ENABLED", "false")
    reset_settings_for_tests()
    _resync_prewarm_settings(monkeypatch)
    _stub_heavy_collaborators(monkeypatch)
    calls = _patch_loader(monkeypatch)

    worker_mod._prewarm(_FakeJobProcess())

    assert calls == [1]
    reset_settings_for_tests()


def test_prewarm_skips_tts_when_elevenlabs(monkeypatch):
    """(b) backend resolves to elevenlabs → `_load_tts` NOT called."""
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")
    monkeypatch.setenv("SMART_TURN_ENABLED", "false")
    reset_settings_for_tests()
    _resync_prewarm_settings(monkeypatch)
    _stub_heavy_collaborators(monkeypatch)
    calls = _patch_loader(monkeypatch)

    worker_mod._prewarm(_FakeJobProcess())

    assert calls == []
    reset_settings_for_tests()


def test_prewarm_swallows_tts_load_error(monkeypatch):
    """(c) `_load_tts` raising must not crash `_prewarm` (lazy per-call fallback)."""
    monkeypatch.setenv("TTS_BACKEND", "vieneu")
    monkeypatch.setenv("SMART_TURN_ENABLED", "false")
    reset_settings_for_tests()
    _resync_prewarm_settings(monkeypatch)
    _stub_heavy_collaborators(monkeypatch)

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(vieneu_mod, "_load_tts", _boom)

    # Must return normally — exception swallowed inside the warm block.
    worker_mod._prewarm(_FakeJobProcess())

    reset_settings_for_tests()


def _patch_rag_warms(monkeypatch) -> dict[str, int]:
    """Count which RAG warm fired. `_prewarm` imports both function-locally, so
    the source modules are the seam."""
    import noble_agent.agent.rag.flat_store_adapter as flat_adapter_mod
    import noble_agent.agent.rag.qdrant_adapter as qdrant_adapter_mod

    hits = {"flat_store": 0, "embedder": 0}

    async def _rec_store():
        hits["flat_store"] += 1

    def _rec_embed(_text):
        hits["embedder"] += 1
        return [0.0]

    monkeypatch.setattr(flat_adapter_mod, "_ensure_flat_store", _rec_store)
    monkeypatch.setattr(qdrant_adapter_mod, "_embed_query", _rec_embed)
    return hits


def _run_prewarm_with_backend(monkeypatch, backend: str) -> dict[str, int]:
    monkeypatch.setenv("NOBLE_RAG_BACKEND", backend)
    monkeypatch.setenv("TTS_BACKEND", "elevenlabs")  # skip the vieneu load
    monkeypatch.setenv("SMART_TURN_ENABLED", "false")
    reset_settings_for_tests()
    _resync_prewarm_settings(monkeypatch)
    _stub_heavy_collaborators(monkeypatch)
    hits = _patch_rag_warms(monkeypatch)

    worker_mod._prewarm(_FakeJobProcess())

    reset_settings_for_tests()
    return hits


def test_prewarm_kb_service_warms_no_local_model(monkeypatch):
    """kb_service embeds over HTTP and retrieves in Qdrant → nothing in-process.

    Regression guard for a real outage: the gate used to be `== "qdrant"` else
    FlatStore, so kb_service loaded e5-large and encoded 285 chunks on CPU, blowing
    LiveKit's init timeout → kill/respawn loop, zero calls served.
    """
    assert _run_prewarm_with_backend(monkeypatch, "kb_service") == {"flat_store": 0, "embedder": 0}


def test_prewarm_grep_faq_and_empty_warm_nothing(monkeypatch):
    for backend in ("grep_faq", "empty"):
        assert _run_prewarm_with_backend(monkeypatch, backend) == {"flat_store": 0, "embedder": 0}


def test_prewarm_flat_store_warms_the_store(monkeypatch):
    assert _run_prewarm_with_backend(monkeypatch, "flat_store") == {"flat_store": 1, "embedder": 0}


def test_prewarm_qdrant_and_hipporag_warm_embedder_only(monkeypatch):
    """hipporag rides the same embedder (its sparse triple-seed embeds queries with
    it) but must NOT pull the FlatStore chunk encode."""
    for backend in ("qdrant", "hipporag"):
        assert _run_prewarm_with_backend(monkeypatch, backend) == {"flat_store": 0, "embedder": 1}


def test_worker_options_idle_default_is_one(monkeypatch):
    """(d) regression guard: `num_idle_processes` defaults to 1.

    `worker.py` keeps the line intentionally env-overridable
    (`int(os.environ.get("NUM_IDLE_PROCESSES", "1"))`). This guard asserts the
    resolved default is 1 when the env var is unset, so a future edit can't
    silently bump the default (>1 idle copies of santa-tts → A10G OOM).
    """
    monkeypatch.delenv("NUM_IDLE_PROCESSES", raising=False)
    reset_settings_for_tests()

    captured: dict[str, object] = {}

    def _capture_run_app(opts):
        captured["opts"] = opts

    monkeypatch.setattr(worker_mod.agents.cli, "run_app", _capture_run_app)
    # run_worker() now also starts the SP-D heartbeat daemon thread; neutralize it
    # here (this test only asserts WorkerOptions) so it doesn't beat against a real store.
    monkeypatch.setattr(worker_mod, "_start_heartbeat", lambda: None)

    worker_mod.run_worker()

    assert captured["opts"].num_idle_processes == 1
    reset_settings_for_tests()
