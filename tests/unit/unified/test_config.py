import pytest

from noble_agent.config import (
    UnifiedSettings,
    get_settings,
    provider_model_map,
    reset_settings_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def test_use_unified_agent_flag_default_false(monkeypatch):
    monkeypatch.delenv("USE_UNIFIED_AGENT", raising=False)
    # `_env_file=None` bypasses the repo's `.env` (which sets USE_UNIFIED_AGENT=true
    # for runtime) so this exercises the code default, matching the other
    # default-value tests in this file.
    assert UnifiedSettings(_env_file=None).use_unified_agent is False


def test_use_unified_agent_flag_reads_env(monkeypatch):
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    assert UnifiedSettings().use_unified_agent is True


def test_summary_keep_tail_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SUMMARY_KEEP_TAIL", raising=False)
    assert UnifiedSettings().summary_keep_tail == 4


def test_summary_threshold_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SUMMARY_K", raising=False)
    assert UnifiedSettings().summary_threshold_K == 8


def test_semcache_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SEMCACHE_ENABLED", raising=False)
    assert UnifiedSettings().semcache_enabled is False


def test_removed_fields_are_absent():
    s = UnifiedSettings()
    for name in ("default_agent", "max_handoff_chain", "auto_briefing_lookback", "briefing_model"):
        assert not hasattr(s, name), f"{name} should be removed from UnifiedSettings"


def test_agent_model_default_empty(monkeypatch):
    monkeypatch.delenv("NOBLE_AGENT_MODEL", raising=False)
    # `_env_file=None` bypasses the repo's `.env` (which may have the var set
    # for runtime) — keeps the default-value test deterministic.
    assert UnifiedSettings(_env_file=None).agent_model == ""


def test_agent_model_reads_env(monkeypatch):
    monkeypatch.setenv("NOBLE_AGENT_MODEL", "claude-sonnet-4-6")
    assert UnifiedSettings(_env_file=None).agent_model == "claude-sonnet-4-6"


def test_summary_model_default_empty(monkeypatch):
    monkeypatch.delenv("NOBLE_SUMMARY_MODEL", raising=False)
    assert UnifiedSettings(_env_file=None).summary_model == ""


def test_semcache_model_default_empty(monkeypatch):
    monkeypatch.delenv("NOBLE_SEMCACHE_MODEL", raising=False)
    assert UnifiedSettings(_env_file=None).semcache_model == ""


def test_provider_model_map_pulls_per_provider_models(monkeypatch):
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    s = UnifiedSettings(_env_file=None)
    assert provider_model_map(s) == {
        "vllm": "",
        "anthropic": "claude-haiku-4-5",
        "openai": "gpt-4o-mini",
        "dashscope": "qwen3.5-flash",
        "gemini": "gemini-2.5-flash",
    }


def test_provider_model_map_includes_dashscope(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen3.6-flash")
    s = UnifiedSettings(_env_file=None)
    assert provider_model_map(s)["dashscope"] == "qwen3.6-flash"


def test_primary_for_resolves_dashscope(monkeypatch):
    from noble_agent.config import primary_for

    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    s = UnifiedSettings(_env_file=None)
    assert primary_for(s, "qwen3.5-flash") == "dashscope"


def test_primary_for_matches_provider_with_configured_model(monkeypatch):
    from noble_agent.config import primary_for

    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("OPENAI_MODEL", "qwen3-pinned")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    s = UnifiedSettings(_env_file=None)
    assert primary_for(s, "claude-haiku-4-5") == "anthropic"
    assert primary_for(s, "qwen3-pinned") == "openai"
    assert primary_for(s, "gemini-2.5-flash") == "gemini"


def test_primary_for_returns_none_on_no_match(monkeypatch):
    from noble_agent.config import primary_for

    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("OPENAI_MODEL", "qwen3-pinned")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    s = UnifiedSettings(_env_file=None)
    # Empty → None.
    assert primary_for(s, "") is None
    # Unknown model name → None + warning (covered by another test).
    assert primary_for(s, "model-that-no-provider-has") is None


def test_vllm_fields_defaults(monkeypatch):
    for v in ("VLLM_BASE_URL", "VLLM_MODEL", "VLLM_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.vllm_base_url == "http://localhost:8000/v1"
    assert s.vllm_model == ""  # empty = provider OFF (opt-in)
    assert s.vllm_api_key == "EMPTY"  # openai SDK requires non-empty; vLLM ignores it


def test_vllm_fields_read_env(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8200/v1")
    monkeypatch.setenv("VLLM_MODEL", "hotline")
    monkeypatch.setenv("VLLM_API_KEY", "tok")
    s = UnifiedSettings(_env_file=None)
    assert s.vllm_base_url == "http://localhost:8200/v1"
    assert s.vllm_model == "hotline"
    assert s.vllm_api_key == "tok"


def test_provider_model_map_includes_vllm(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "hotline")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    s = UnifiedSettings(_env_file=None)
    m = provider_model_map(s)
    assert m["vllm"] == "hotline"
    assert m["openai"] == "gpt-4o-mini"


def test_primary_for_resolves_vllm(monkeypatch):
    from noble_agent.config import primary_for

    monkeypatch.setenv("VLLM_MODEL", "hotline")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    s = UnifiedSettings(_env_file=None)
    assert primary_for(s, "hotline") == "vllm"


def test_sherpa_preserve_case_default_true(monkeypatch):
    monkeypatch.delenv("SHERPA_PRESERVE_CASE", raising=False)
    assert UnifiedSettings(_env_file=None).sherpa_preserve_case is True


def test_sherpa_model_quantize_default_false(monkeypatch):
    monkeypatch.delenv("SHERPA_MODEL_QUANTIZE", raising=False)
    assert UnifiedSettings(_env_file=None).sherpa_model_quantize is False


def test_sherpa_model_quantize_reads_env(monkeypatch):
    monkeypatch.setenv("SHERPA_MODEL_QUANTIZE", "true")
    assert UnifiedSettings(_env_file=None).sherpa_model_quantize is True


def test_sherpa_hf_revision_default_prod(monkeypatch):
    monkeypatch.delenv("SHERPA_HF_REVISION", raising=False)
    assert UnifiedSettings(_env_file=None).sherpa_hf_revision == "prod"


def test_vieneu_hf_revision_default_prod(monkeypatch):
    monkeypatch.delenv("VIENEU_HF_REVISION", raising=False)
    assert UnifiedSettings(_env_file=None).vieneu_hf_revision == "prod"


def test_sherpa_model_name_field_removed(monkeypatch):
    assert not hasattr(UnifiedSettings(_env_file=None), "sherpa_model_name")


def test_sherpa_preserve_case_reads_env_false(monkeypatch):
    monkeypatch.setenv("SHERPA_PRESERVE_CASE", "false")
    assert UnifiedSettings(_env_file=None).sherpa_preserve_case is False


def test_get_settings_returns_singleton(monkeypatch):
    monkeypatch.setenv("USE_UNIFIED_AGENT", "false")
    a = get_settings()
    b = get_settings()
    assert a is b


def test_qdrant_collection_default_is_hybrid(monkeypatch):
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.qdrant_collection == "noble_kb_hybrid"
    assert s.qdrant_url == "http://localhost:6333"


def test_app_api_settings_defaults(monkeypatch):
    for var in ("NOBLE_APP_API_KEY", "CHAT_WS_REQUIRE_TOKEN", "APP_CONNECT_TOKEN_TTL_SECONDS", "APP_WS_PUBLIC_BASE"):
        monkeypatch.delenv(var, raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.noble_app_api_key == ""
    assert s.chat_ws_require_token is False
    assert s.app_connect_token_ttl_seconds == 120
    assert s.app_ws_public_base == ""


def test_livekit_token_public_default_false(monkeypatch):
    monkeypatch.delenv("LIVEKIT_TOKEN_PUBLIC", raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.livekit_token_public is False


def test_agent_name_default_luna():
    # `_env_file=None` bypasses the repo `.env` so this exercises the code default.
    assert UnifiedSettings(_env_file=None).agent_name == "Luna"


def test_agent_name_reads_env(monkeypatch):
    monkeypatch.setenv("NOBLE_AGENT_NAME", "Aria")
    assert UnifiedSettings().agent_name == "Aria"
