"""Integration fixtures for the unified single-agent path.

Transport choice: direct-handler approach.
─────────────────────────────────────────
The server uses the `websockets` library directly (not ASGI/Starlette), so
httpx-ws is not a viable option without spinning up a real server process.
The existing legacy tests in tests/unit/test_text_chat.py confirm the pattern:
call run_text_turn / handle_text_session with a fake `send` callable and a
scripted fake LLM.

These integration tests drive the same seam — below the WS transport — so they
validate the full unified wiring (LLM → tool dispatch → callbacks → events)
without needing a real socket, a real Redis, or a real LLM endpoint.

Injection points
────────────────
* Redis: `noble_agent.storage.redis_client.set_redis_for_tests` — the
  module exposes this helper specifically for tests.
* LLM: monkeypatch `noble_agent.agent.llm.client.StreamingClient` so
  every `_build_runner` call gets our fake.
* Runner singleton: `reset_runner_for_tests()` between tests.
* Settings: `reset_settings_for_tests()` + env vars via monkeypatch.
"""

from __future__ import annotations

import json
from typing import Any

import fakeredis.aioredis
import pytest

from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

# ──────────────────────────────────────────────────────────────────────────────
# Environment / settings
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _force_unified_env(monkeypatch):
    """Force USE_UNIFIED_AGENT=true and stub API keys for all integration tests."""
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-integration")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    from noble_agent.config import reset_settings_for_tests
    from noble_agent.agent.facade import reset_runner_for_tests

    reset_settings_for_tests()
    reset_runner_for_tests()

    yield

    reset_settings_for_tests()
    reset_runner_for_tests()


# ──────────────────────────────────────────────────────────────────────────────
# Fake Redis
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_redis():
    """Provide an in-process FakeRedis and inject it into the unified package."""
    from noble_agent.storage import redis_client as _rc

    r = fakeredis.aioredis.FakeRedis()
    _rc.set_redis_for_tests(r)
    yield r
    _rc.set_redis_for_tests(None)  # clear singleton
    await r.aclose()


# ──────────────────────────────────────────────────────────────────────────────
# Fake LLM helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_client_class(responses_ref: list):
    """Return a StreamingClient-shaped class bound to `responses_ref`.

    IMPORTANT: stores a reference (not a copy) so that the test can append
    entries after the runner is built and before stream_completion is called.
    """

    class _FakeClient:
        """Scripted StreamingClient replacement.

        Script entries (consumed in order from responses_ref):
          ("text", "some reply")
              → emits tokens word-by-word, returns ("some reply", None)
          ("tool", name, args_dict)
              → returns ("", [tool_call_dict]) — runner dispatches the tool
          ("tool_then_text", name, args_dict, "follow-up text")
              → emits the tool call; inserts a "text" entry for the next call
        """

        def __init__(self, providers=None, **_kw):
            # Keep the same list reference (DO NOT copy).
            self._responses = responses_ref

        async def stream_completion(
            self,
            *,
            messages,
            tools,
            model,
            temperature,
            max_tokens,
            on_token,
            interrupt_check=None,
            primary=None,
        ):
            if not self._responses:
                return ("(no more stubs)", None)

            entry = self._responses.pop(0)
            kind = entry[0]

            if kind == "text":
                text = entry[1]
                for word in text.split(" "):
                    await on_token(word + " ")
                return (text, None)

            if kind == "tool":
                _, name, args_dict = entry
                tc = {
                    "id": "fake-tc-1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args_dict)},
                }
                return ("", [tc])

            if kind == "tool_then_text":
                _, name, args_dict, followup = entry
                tc = {
                    "id": "fake-tc-1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args_dict)},
                }
                # Push the follow-up so the next LLM call sees it.
                self._responses.insert(0, ("text", followup))
                return ("", [tc])

            return ("(unknown stub kind)", None)

        async def simple_completion(self, prompt, *, model, max_tokens=400, temperature=0.3):
            return "(stub summary)"

        async def complete_once(self, *, messages, model, temperature, max_tokens):
            return "(stub)"

    return _FakeClient


# ──────────────────────────────────────────────────────────────────────────────
# stub_responses + fake_llm fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_responses():
    """Mutable list shared between the test and FakeStreamingClient."""
    return []


@pytest.fixture
def fake_llm(monkeypatch, stub_responses):
    """Patch StreamingClient in-module so TurnRunner gets the scripted fake."""
    import noble_agent.agent.llm.client as _llm_mod

    monkeypatch.setattr(_llm_mod, "StreamingClient", _make_client_class(stub_responses))
    return stub_responses  # same list reference — test appends here


# ──────────────────────────────────────────────────────────────────────────────
# Built TurnRunner (shared across tests that want a fully wired runner)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def runner(fake_redis, fake_llm):
    """Fully wired TurnRunner: fake Redis + fake LLM (bound to stub_responses)."""
    from noble_agent.agent.base import load_agent_def
    from noble_agent.agent.orchestrator import TurnRunner
    from noble_agent.agent.llm.client import StreamingClient  # already patched
    from noble_agent.config import UnifiedSettings
    from noble_agent.storage.repo import StateRepo

    agent_def = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)
    repo = StateRepo(redis_client=fake_redis, ttl_seconds=3600)
    llm = StreamingClient(providers=[])  # creates _FakeClient bound to stub_responses
    settings = UnifiedSettings(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=20)
    return TurnRunner(repo=repo, agent_def=agent_def, llm=llm, rag=None, settings=settings)


# ──────────────────────────────────────────────────────────────────────────────
# Collector helper
# ──────────────────────────────────────────────────────────────────────────────


def make_collector() -> tuple[list[dict], Any]:
    """Return (events_list, async_send_callable)."""
    events: list[dict] = []

    async def send(ev: dict) -> None:
        events.append(ev)

    return events, send
