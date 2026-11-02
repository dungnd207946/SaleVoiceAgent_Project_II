from noble_agent.config import UnifiedSettings


def test_kb_search_settings_defaults(monkeypatch):
    for var in ("KB_SEARCH_TOP_K", "KB_SEARCH_MIN_SCORE"):
        monkeypatch.delenv(var, raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.kb_search_top_k == 5
    assert s.kb_search_min_score == 0.0


def test_kb_search_tuning_from_env(monkeypatch):
    monkeypatch.setenv("KB_SEARCH_TOP_K", "8")
    monkeypatch.setenv("KB_SEARCH_MIN_SCORE", "0.35")
    s = UnifiedSettings(_env_file=None)
    assert s.kb_search_top_k == 8
    assert s.kb_search_min_score == 0.35


def test_retired_service_settings_are_gone():
    """query_rag:8016 is retired — its URL/token/timeout fields must not linger, or
    a stale .env value reads like live config."""
    s = UnifiedSettings(_env_file=None)
    for gone in ("kb_search_url", "kb_search_token", "kb_search_timeout"):
        assert not hasattr(s, gone), f"{gone} should have been removed with the service"
