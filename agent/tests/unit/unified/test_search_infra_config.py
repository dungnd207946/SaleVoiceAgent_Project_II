"""Settings for the search infra shared by kb_search + send_media.

`QDRANT_URL` is the app's single Qdrant endpoint (the legacy `qdrant`/`hipporag`
backends read the same one, just a different collection). `EMBED_SERVICE_URL`
defaults empty on purpose: only the visual branch needs it, so unconfigured means
send_media searches on text alone rather than dialling a wrong host.
"""
from noble_agent.config import UnifiedSettings

_VARS = (
    "EMBED_BACKEND",
    "EMBED_MODEL",
    "EMBED_DIM",
    "EMBED_SPARSE_MODEL",
    "EMBED_SERVICE_URL",
    "EMBED_TIMEOUT",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "QDRANT_TIMEOUT",
    "MEDIA_SEARCH_CACHE_TTL",
)


def _clean(monkeypatch):
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)


def test_search_infra_defaults(monkeypatch):
    _clean(monkeypatch)
    s = UnifiedSettings(_env_file=None)
    assert s.embed_backend == "gemini"
    assert s.embed_model == ""  # empty = backend default
    assert s.embed_dim == 1024  # must match the collection's dense size
    assert s.embed_sparse_model == "Qdrant/bm25"  # must match ingest's model
    assert s.embed_service_url == ""  # only visual + backend=service need it
    assert s.qdrant_api_key == ""
    assert s.embed_timeout == 30.0
    assert s.qdrant_timeout == 10.0
    assert s.media_search_cache_ttl == 300.0


def test_search_infra_from_env(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EMBED_BACKEND", "service")
    monkeypatch.setenv("EMBED_MODEL", "custom-embed")
    monkeypatch.setenv("EMBED_DIM", "768")
    monkeypatch.setenv("EMBED_SPARSE_MODEL", "Qdrant/bm42-all-minilm-l6-v2-attentions")
    monkeypatch.setenv("EMBED_SERVICE_URL", "http://embed:8013/embed")
    monkeypatch.setenv("QDRANT_URL", "http://172.17.0.1:6433")
    monkeypatch.setenv("QDRANT_API_KEY", "qkey")
    monkeypatch.setenv("EMBED_TIMEOUT", "45")
    monkeypatch.setenv("QDRANT_TIMEOUT", "5")
    monkeypatch.setenv("MEDIA_SEARCH_CACHE_TTL", "60")
    s = UnifiedSettings(_env_file=None)
    assert s.embed_backend == "service"
    assert s.embed_model == "custom-embed"
    assert s.embed_dim == 768
    assert s.embed_sparse_model == "Qdrant/bm42-all-minilm-l6-v2-attentions"
    assert s.embed_service_url == "http://embed:8013/embed"
    assert s.qdrant_url == "http://172.17.0.1:6433"
    assert s.qdrant_api_key == "qkey"
    assert s.embed_timeout == 45.0
    assert s.qdrant_timeout == 5.0
    assert s.media_search_cache_ttl == 60.0


def test_split_qdrant_settings_are_gone():
    """QDRANT_URL is the single endpoint — the separate SEARCH_QDRANT_* block was
    removed, so a value left under the old name must not silently do nothing."""
    s = UnifiedSettings(_env_file=None)
    for gone in ("search_qdrant_url", "search_qdrant_api_key", "search_qdrant_timeout"):
        assert not hasattr(s, gone), f"{gone} should have been folded into qdrant_*"


def test_embed_remote_is_unset_by_default(monkeypatch):
    """EMBED_REMOTE_* belongs to the legacy flat_store path, not this seam."""
    monkeypatch.delenv("EMBED_REMOTE_URL", raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.embed_remote_url == ""
