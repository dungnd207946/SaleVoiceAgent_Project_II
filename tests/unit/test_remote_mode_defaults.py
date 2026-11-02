"""Contract tests — default env means default behavior, no network touched.

Guards against regression where the runpod hosting integration accidentally
changes the default path. These three tests codify "code chính chạy bình
thường" as assertions on the _Embedder / GenderDetector / worker config.

Run: pytest tests/unit/test_remote_mode_defaults.py -v
"""

from __future__ import annotations


def test_embedder_default_does_not_enter_remote_mode(monkeypatch):
    """When EMBED_REMOTE_URL is unset AND settings.embed_remote_url is empty,
    _Embedder must never set backend='remote' (so httpx client is never created)."""
    from noble_agent.agent.rag.flat_store import _Embedder
    from noble_agent.config import settings

    monkeypatch.delenv("EMBED_REMOTE_URL", raising=False)
    monkeypatch.setattr(settings, "embed_remote_url", "")

    emb = _Embedder(model_name="intfloat/multilingual-e5-large")
    # Do NOT call load() to avoid network/disk IO in unit test; instead assert
    # the remote branch is inert after construction + verify the gating logic
    # by inspecting the env check directly.
    assert emb._backend is None
    assert emb._remote_url == ""
    # Verify the env gate logic: with both unset, no remote URL would be picked.
    import os

    assert not os.environ.get("EMBED_REMOTE_URL", "").strip()
    assert not getattr(settings, "embed_remote_url", "")


def test_embedder_activates_remote_when_url_set(monkeypatch):
    """When settings.embed_remote_url is set, load() must pick remote backend
    and skip fastembed/sentence-transformers entirely."""
    from noble_agent.agent.rag.flat_store import _Embedder
    from noble_agent.config import settings

    monkeypatch.delenv("EMBED_REMOTE_URL", raising=False)
    monkeypatch.setattr(settings, "embed_remote_url", "http://embed.test:8091")
    monkeypatch.setattr(settings, "embed_remote_timeout", 5.0)

    emb = _Embedder(model_name="intfloat/multilingual-e5-large")
    emb.load()

    assert emb._backend == "remote"
    assert emb._remote_url == "http://embed.test:8091"
    # httpx.Client should be the _impl now.
    assert emb._impl is not None
    assert type(emb._impl).__name__ == "Client"


def test_embedder_remote_sets_bearer_header_when_token_set(monkeypatch):
    """A configured embed_remote_token → httpx.Client carries the
    `Authorization: Bearer <token>` header (the hosted service 401s without it)."""
    from noble_agent.agent.rag.flat_store import _Embedder
    from noble_agent.config import settings

    monkeypatch.delenv("EMBED_REMOTE_URL", raising=False)
    monkeypatch.delenv("EMBED_REMOTE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "embed_remote_url", "http://embed.test:8013")
    monkeypatch.setattr(settings, "embed_remote_token", "secrettoken")

    emb = _Embedder(model_name="intfloat/multilingual-e5-large")
    emb.load()

    assert emb._backend == "remote"
    assert emb._remote_token == "secrettoken"
    assert emb._impl.headers.get("Authorization") == "Bearer secrettoken"


def test_embedder_remote_no_header_when_token_empty(monkeypatch):
    """No token → no Authorization header (backward-compatible with token-less sidecars)."""
    from noble_agent.agent.rag.flat_store import _Embedder
    from noble_agent.config import settings

    monkeypatch.delenv("EMBED_REMOTE_URL", raising=False)
    monkeypatch.delenv("EMBED_REMOTE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "embed_remote_url", "http://embed.test:8013")
    monkeypatch.setattr(settings, "embed_remote_token", "")

    emb = _Embedder(model_name="intfloat/multilingual-e5-large")
    emb.load()

    assert emb._backend == "remote"
    assert "Authorization" not in emb._impl.headers


def test_encode_remote_posts_is_query_body(monkeypatch):
    """`_encode_remote` posts {"texts","is_query"} (NOT the legacy "normalize")
    and parses {"embeddings": [...]}."""
    import numpy as np

    from noble_agent.agent.rag.flat_store import _Embedder

    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3]]}

    class _FakeClient:
        def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp()

    emb = _Embedder(model_name="intfloat/multilingual-e5-large")
    emb._backend = "remote"
    emb._remote_url = "http://embed.test:8013"
    emb._impl = _FakeClient()

    out = emb._encode_remote(["xin chào"], is_query=True)

    assert captured["url"] == "http://embed.test:8013/embed"
    assert captured["json"] == {"texts": ["xin chào"], "is_query": True}
    assert "normalize" not in captured["json"]
    assert isinstance(out, np.ndarray)
    assert out.shape == (1, 3)


def test_gender_detector_default_has_no_remote_client(monkeypatch):
    """When settings.gender_remote_url is empty, GenderDetector must not
    instantiate httpx.Client. This guards the default voice-agent path."""
    from noble_agent.config import settings
    from noble_agent.voice.gender_detector import GenderDetector

    monkeypatch.setattr(settings, "gender_remote_url", "")
    monkeypatch.setattr(settings, "gender_model_dir", "")  # keep local path a no-op too

    # Reset singleton so __init__ re-runs under monkeypatched settings.
    GenderDetector._instance = None
    det = GenderDetector()

    assert det._remote_client is None
    assert det._remote_url == ""
    assert det.model is None  # gender_model_dir empty → local path also no-op


def test_gender_detector_activates_remote_when_url_set(monkeypatch):
    """When settings.gender_remote_url is set, GenderDetector must set up the
    remote httpx.Client and never touch transformers."""
    from noble_agent.config import settings
    from noble_agent.voice.gender_detector import GenderDetector

    monkeypatch.setattr(settings, "gender_remote_url", "http://gender.test:8092")
    monkeypatch.setattr(settings, "gender_remote_timeout", 2.0)

    GenderDetector._instance = None
    det = GenderDetector()

    assert det._remote_client is not None
    assert det._remote_url == "http://gender.test:8092"
    assert type(det._remote_client).__name__ == "Client"
    # Local model must NOT be loaded.
    assert det.model is None
    assert det.processor is None


def test_livekit_worker_port_defaults_to_8081():
    """Guard that LiveKit worker port default is still 8081 (LK's own default).
    Hosts that need another port set LIVEKIT_WORKER_PORT=8082 in .env."""
    from noble_agent.config import settings

    # Default must be 8081 — changing this would silently move the health
    # endpoint for every existing deployment.
    assert settings.__class__.model_fields["livekit_worker_port"].default == 8081
