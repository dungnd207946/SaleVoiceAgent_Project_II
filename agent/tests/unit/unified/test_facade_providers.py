"""Tests for `build_llm_providers` — the LLM provider-chain construction.

vLLM is a distinct, opt-in PRIMARY slot: built first only when `VLLM_MODEL`
is set, with OpenAI/Gemini as fallbacks and Anthropic appended LAST. When
`VLLM_MODEL` is empty the chain is unchanged from today (anthropic → openai
→ gemini).

`build_llm_providers` reads the global `get_settings()` singleton, so each
test monkeypatches env then `reset_settings_for_tests()` (autouse fixture).
"""

from __future__ import annotations

import pytest

import noble_agent.config as config_mod
from noble_agent.config import UnifiedSettings, reset_settings_for_tests


def _prime_settings_no_env_file() -> None:
    """Pin the global settings singleton to an `_env_file=None` instance.

    `build_llm_providers()` reads `get_settings()`, which otherwise loads the
    repo's real `.env` — so leftover keys there (e.g. `DASHSCOPE_API_KEY`)
    would leak into these ordering tests regardless of `monkeypatch.delenv`.
    `_env_file=None` bypasses the `.env` file while still honouring `os.environ`
    (so the per-test `monkeypatch.setenv` values are respected).
    """
    config_mod._settings = UnifiedSettings(_env_file=None)

_PROVIDER_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "VLLM_MODEL",
    "VLLM_BASE_URL",
    "VLLM_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DASHSCOPE_MODEL",
)


class _StubAnthropic:
    """Stand-in for AnthropicProvider so the chain can include an anthropic slot
    without the optional `anthropic` SDK being installed in the test env."""

    def __init__(self, **_kwargs):
        pass


@pytest.fixture(autouse=True)
def _clear():
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


@pytest.fixture(autouse=True)
def _stub_anthropic_provider(monkeypatch):
    # The real AnthropicProvider does `import anthropic` at construction; that
    # SDK is an optional dep. Swap in a stub so ordering tests are deterministic
    # regardless of whether the SDK is installed.
    import noble_agent.agent.llm.anthropic_provider as ap

    monkeypatch.setattr(ap, "AnthropicProvider", _StubAnthropic)


def _names(monkeypatch, **env):
    # Force a clean env: only what we set is present.
    for k in _PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reset_settings_for_tests()
    _prime_settings_no_env_file()
    from noble_agent.agent.facade import build_llm_providers

    return [n for n, _ in build_llm_providers()]


def test_no_vllm_slot_when_model_empty(monkeypatch):
    # VLLM_MODEL empty → chain identical to today: anthropic → openai → gemini
    names = _names(monkeypatch, ANTHROPIC_API_KEY="a", OPENAI_API_KEY="o", GEMINI_API_KEY="g")
    assert "vllm" not in names
    assert names == ["anthropic", "openai", "gemini"]


def test_vllm_built_first_when_model_set(monkeypatch):
    names = _names(
        monkeypatch,
        VLLM_MODEL="hotline",
        OPENAI_API_KEY="o",
        GEMINI_API_KEY="g",
        ANTHROPIC_API_KEY="a",
    )
    assert names[0] == "vllm"
    # 3-tier intent + anthropic safety tail (anthropic LAST):
    assert names == ["vllm", "openai", "gemini", "anthropic"]


def test_vllm_first_anthropic_skipped_when_unkeyed(monkeypatch):
    # No anthropic key → no anthropic tail; vllm still leads.
    names = _names(monkeypatch, VLLM_MODEL="hotline", OPENAI_API_KEY="o", GEMINI_API_KEY="g")
    assert names == ["vllm", "openai", "gemini"]


def test_dashscope_slot_built_when_keyed(monkeypatch):
    # DASHSCOPE_API_KEY present → a distinct `dashscope` slot, after openai.
    names = _names(
        monkeypatch,
        OPENAI_API_KEY="o",
        DASHSCOPE_API_KEY="d",
        GEMINI_API_KEY="g",
    )
    assert names == ["openai", "dashscope", "gemini"]


def test_dashscope_slot_absent_when_unkeyed(monkeypatch):
    names = _names(monkeypatch, OPENAI_API_KEY="o", GEMINI_API_KEY="g")
    assert "dashscope" not in names


def test_dashscope_slot_targets_configured_base_url(monkeypatch):
    for k in _PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "d")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    reset_settings_for_tests()
    _prime_settings_no_env_file()
    from noble_agent.agent.facade import build_llm_providers

    providers = dict(build_llm_providers())
    assert "dashscope" in providers
    assert "dashscope-intl.aliyuncs.com" in str(providers["dashscope"].base_url)


def test_vllm_slot_targets_configured_base_url(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VLLM_MODEL", "hotline")
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8200/v1")
    monkeypatch.setenv("VLLM_API_KEY", "EMPTY")
    reset_settings_for_tests()
    _prime_settings_no_env_file()
    from noble_agent.agent.facade import build_llm_providers

    providers = build_llm_providers()
    name, client = providers[0]
    assert name == "vllm"
    assert "localhost:8200" in str(client.base_url)
