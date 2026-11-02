"""StreamingClient model-resolution tests.

Covers the new behavior where `model` may be either a single string (main-
agent path: same name flows through every provider until one accepts it)
or a `dict[str, str]` of provider-name → model (summary / semcache paths:
each provider gets its own configured model, and empty entries skip that
provider).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.llm.client import (
    StreamingClient,
    _is_transient,
    _normalize_for_openai_compat,
    _resolve_model,
)
from noble_agent.storage.models import ThreadMessage


def test_resolve_model_string_returns_verbatim():
    assert _resolve_model("gpt-4o-mini", "anthropic") == "gpt-4o-mini"
    assert _resolve_model("gpt-4o-mini", "openai") == "gpt-4o-mini"


def test_resolve_model_dict_picks_per_provider():
    m = {"anthropic": "claude-haiku-4-5", "openai": "gpt-4o-mini"}
    assert _resolve_model(m, "anthropic") == "claude-haiku-4-5"
    assert _resolve_model(m, "openai") == "gpt-4o-mini"
    # Missing key → empty (caller will skip this provider).
    assert _resolve_model(m, "gemini") == ""
    # Explicit empty also empty.
    assert _resolve_model({"openai": ""}, "openai") == ""


def _make_fake_provider(return_text: str = "ok"):
    """Build a SimpleNamespace shaped like AsyncOpenAI: .chat.completions.create()."""
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=return_text))])
    create = AsyncMock(return_value=resp)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


async def test_complete_once_skips_provider_with_empty_model():
    """If `model` is a dict missing the first provider, that provider must
    be skipped (no call), and the next provider gets its mapped model."""
    p1, c1 = _make_fake_provider("from-anthropic")
    p2, c2 = _make_fake_provider("from-openai")
    client = StreamingClient(providers=[("anthropic", p1), ("openai", p2)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"openai": "gpt-4o-mini"},  # anthropic entry missing
        temperature=0.1,
        max_tokens=10,
    )

    assert out == "from-openai"
    c1.assert_not_called()
    c2.assert_awaited_once()
    # Ensure each provider got ITS configured model name.
    assert c2.call_args.kwargs["model"] == "gpt-4o-mini"


async def test_complete_once_string_model_flows_through_chain():
    """Single-string model: first provider succeeds, name is sent verbatim."""
    p1, c1 = _make_fake_provider("ok")
    p2, c2 = _make_fake_provider("never")
    client = StreamingClient(providers=[("anthropic", p1), ("openai", p2)])

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-pinned",
        temperature=0.1,
        max_tokens=10,
    )

    assert c1.call_args.kwargs["model"] == "claude-pinned"
    c2.assert_not_called()


async def test_complete_once_dict_falls_through_on_provider_error():
    """If anthropic raises, the dict's openai entry is used next."""

    async def boom(*_a, **_kw):
        raise RuntimeError("anthropic 500")

    p1 = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))
    p2, c2 = _make_fake_provider("from-openai")
    client = StreamingClient(providers=[("anthropic", p1), ("openai", p2)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"anthropic": "claude-x", "openai": "gpt-4o-mini"},
        temperature=0.1,
        max_tokens=10,
    )
    assert out == "from-openai"
    assert c2.call_args.kwargs["model"] == "gpt-4o-mini"


async def test_complete_once_request_timeout_forwarded_to_each_provider():
    """`request_timeout` must bound EACH provider attempt (passed as `timeout=`
    into the create kwargs) so a slow/failing model fails fast and the chain
    falls through — real per-provider fallback, not one overall cap."""
    p1, c1 = _make_fake_provider("ok")
    client = StreamingClient(providers=[("gemini", p1)])

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"gemini": "gemini-2.5-flash"},
        temperature=0.2,
        max_tokens=10,
        request_timeout=12.0,
    )
    assert c1.call_args.kwargs["timeout"] == 12.0


async def test_complete_once_request_timeout_still_falls_back():
    """With a per-provider `request_timeout`, a first-provider failure still
    falls through to the next provider (fallback is not cut short)."""

    async def boom(*_a, **_kw):
        raise RuntimeError("gemini timed out")

    p1 = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))
    p2, c2 = _make_fake_provider("from-openai")
    client = StreamingClient(providers=[("gemini", p1), ("openai", p2)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini"},
        temperature=0.2,
        max_tokens=10,
        request_timeout=12.0,
    )
    assert out == "from-openai"
    assert c2.call_args.kwargs["timeout"] == 12.0


async def test_complete_once_primary_reorders_chain():
    """`primary='openai'` must put openai ahead of anthropic, even though
    anthropic appears first in the provider list. This is how the summary /
    semcache paths pin their preferred provider while keeping fallback."""
    p_ant, c_ant = _make_fake_provider("from-anthropic")
    p_oai, c_oai = _make_fake_provider("from-openai")
    client = StreamingClient(providers=[("anthropic", p_ant), ("openai", p_oai)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"anthropic": "claude-x", "openai": "gpt-x"},
        temperature=0.1,
        max_tokens=10,
        primary="openai",
    )

    assert out == "from-openai"
    c_ant.assert_not_called()  # primary won — anthropic never touched
    assert c_oai.call_args.kwargs["model"] == "gpt-x"


async def test_complete_once_unknown_primary_is_silently_ignored():
    """A stale `primary='gemini'` (provider not configured) must not break
    the chain — the client falls back to default order."""
    p_ant, c_ant = _make_fake_provider("from-anthropic")
    client = StreamingClient(providers=[("anthropic", p_ant)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"anthropic": "claude-x"},
        temperature=0.1,
        max_tokens=10,
        primary="gemini",
    )
    assert out == "from-anthropic"


async def test_complete_once_primary_falls_back_to_secondary_on_error():
    """Primary openai blows up → fall back to anthropic (with anthropic's
    own configured model)."""

    async def boom(*_a, **_kw):
        raise RuntimeError("openai 500")

    p_oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))
    p_ant, c_ant = _make_fake_provider("from-anthropic")
    client = StreamingClient(providers=[("anthropic", p_ant), ("openai", p_oai)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model={"anthropic": "claude-x", "openai": "gpt-x"},
        temperature=0.1,
        max_tokens=10,
        primary="openai",
    )
    assert out == "from-anthropic"
    assert c_ant.call_args.kwargs["model"] == "claude-x"


# ── thinking toggle ──────────────────────────────────────────────────────────


def _make_stream_provider(text_pieces: list[str]):
    """Provider whose create() returns an async generator of OpenAI-shaped
    streaming chunks carrying `text_pieces` as delta.content."""

    def _chunk(piece):
        return MagicMock(choices=[MagicMock(delta=MagicMock(content=piece, tool_calls=None))])

    async def gen():
        for p in text_pieces:
            yield _chunk(p)
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=None), finish_reason="stop")])

    create = AsyncMock(return_value=gen())
    provider = MagicMock()
    provider.chat.completions.create = create
    return provider, create


async def _collect_stream(client, provider_name, pieces):
    tokens: list[str] = []

    async def on_token(t):
        tokens.append(t)

    content, _tc = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=on_token,
    )
    return content, tokens


async def test_stream_strips_think_and_sends_disable_kwarg_when_disabled():
    provider, create = _make_stream_provider(["hi ", "<think>", "secret", "</think>", "answer"])
    client = StreamingClient(providers=[("openai", provider)], enable_thinking=False)

    content, tokens = await _collect_stream(client, "openai", None)

    assert content == "hi answer"
    assert "".join(tokens) == "hi answer"
    assert create.call_args.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


async def test_stream_no_strip_and_no_kwarg_when_thinking_enabled():
    # Default (enable_thinking=True) must be a pure passthrough — regression guard.
    provider, create = _make_stream_provider(["a", "<think>", "b", "</think>"])
    client = StreamingClient(providers=[("openai", provider)])

    content, tokens = await _collect_stream(client, "openai", None)

    assert content == "a<think>b</think>"
    assert "extra_body" not in create.call_args.kwargs
    assert "reasoning_effort" not in create.call_args.kwargs


async def test_stream_disable_gemini_sends_reasoning_effort():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("gemini", provider)], enable_thinking=False)

    await _collect_stream(client, "gemini", None)

    assert create.call_args.kwargs["reasoning_effort"] == "none"


async def test_stream_disable_anthropic_adds_no_extra_kwargs():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("anthropic", provider)], enable_thinking=False)

    await _collect_stream(client, "anthropic", None)

    assert "extra_body" not in create.call_args.kwargs
    assert "reasoning_effort" not in create.call_args.kwargs


async def test_complete_once_strips_think_when_disabled():
    p, _c = _make_fake_provider("answer<think>reasoning</think> done")
    client = StreamingClient(providers=[("openai", p)], enable_thinking=False)

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=10,
    )
    assert out == "answer done"


async def test_complete_once_keeps_think_when_enabled():
    p, _c = _make_fake_provider("answer<think>r</think>")
    client = StreamingClient(providers=[("openai", p)])  # default enabled

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=10,
    )
    assert out == "answer<think>r</think>"


async def test_complete_once_all_skipped_raises():
    """No mapped entries at all → no provider is called → RuntimeError."""
    p1, c1 = _make_fake_provider("never")
    client = StreamingClient(providers=[("anthropic", p1)])
    with pytest.raises(RuntimeError):
        await client.complete_once(
            messages=[{"role": "user", "content": "hi"}],
            model={"openai": "gpt-4o-mini"},  # anthropic skipped
            temperature=0.1,
            max_tokens=10,
        )
    c1.assert_not_called()


# ── real-OpenAI vs vLLM/local request shaping ────────────────────────────────
#
# Real OpenAI reasoning models (api.openai.com) reject `max_tokens` (require
# `max_completion_tokens`), reject the vLLM-only `chat_template_kwargs` thinking
# switch, and reject `temperature != 1`. vLLM / local / gemini keep the old
# behavior. Detection is by `base_url` host — both real OpenAI and vLLM use the
# `openai` provider slot and the same SDK. MagicMock auto-creates `base_url`, so
# tests MUST set it explicitly to a real host string.

_OPENAI_URL = "https://api.openai.com/v1/"
_VLLM_URL = "http://localhost:8000/v1"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


async def test_stream_real_openai_uses_max_completion_tokens():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)])

    await _collect_stream(client, "openai", None)

    kwargs = create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 50
    assert "max_tokens" not in kwargs


async def test_stream_vllm_openai_keeps_max_tokens():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("openai", provider)])

    await _collect_stream(client, "openai", None)

    kwargs = create.call_args.kwargs
    assert kwargs["max_tokens"] == 50
    assert "max_completion_tokens" not in kwargs


async def test_stream_gemini_keeps_max_tokens():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _GEMINI_URL
    client = StreamingClient(providers=[("gemini", provider)])

    await _collect_stream(client, "gemini", None)

    kwargs = create.call_args.kwargs
    assert kwargs["max_tokens"] == 50
    assert "max_completion_tokens" not in kwargs


async def test_complete_once_real_openai_uses_max_completion_tokens():
    provider, create = _make_fake_provider("ok")
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)])

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=33,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 33
    assert "max_tokens" not in kwargs


async def test_complete_once_vllm_openai_keeps_max_tokens():
    provider, create = _make_fake_provider("ok")
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("openai", provider)])

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=33,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["max_tokens"] == 33
    assert "max_completion_tokens" not in kwargs


# ── Fix #2: real OpenAI must not get chat_template_kwargs ─────────────────────


async def test_stream_real_openai_omits_chat_template_kwargs_when_thinking_disabled():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)], enable_thinking=False)

    await _collect_stream(client, "openai", None)

    assert "extra_body" not in create.call_args.kwargs


async def test_stream_vllm_openai_keeps_chat_template_kwargs_when_disabled():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("openai", provider)], enable_thinking=False)

    await _collect_stream(client, "openai", None)

    assert create.call_args.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


async def test_complete_once_real_openai_omits_chat_template_kwargs_when_disabled():
    provider, create = _make_fake_provider("ok")
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)], enable_thinking=False)

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=10,
    )

    assert "extra_body" not in create.call_args.kwargs


# ── Fix #4: real OpenAI reasoning models — temperature=1 + reasoning_effort ───


async def test_stream_real_openai_forces_temperature_1_and_reasoning_effort():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)], openai_reasoning_effort="low")

    content, _tokens = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.7,
        max_tokens=50,
        on_token=_noop_token,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["temperature"] == 1
    assert kwargs["reasoning_effort"] == "low"


async def test_stream_real_openai_reasoning_effort_unset_sentinel_omitted():
    """The 'none' sentinel means 'unset' — do not send reasoning_effort, but
    still force temperature=1 (reasoning models reject temperature != 1)."""
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)], openai_reasoning_effort="none")

    await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.7,
        max_tokens=50,
        on_token=_noop_token,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["temperature"] == 1
    assert "reasoning_effort" not in kwargs


async def test_stream_vllm_openai_keeps_passed_temperature_and_no_reasoning_effort():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("openai", provider)], openai_reasoning_effort="low")

    await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.7,
        max_tokens=50,
        on_token=_noop_token,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["temperature"] == 0.7
    assert "reasoning_effort" not in kwargs


async def test_complete_once_real_openai_forces_temperature_1_and_reasoning_effort():
    provider, create = _make_fake_provider("ok")
    provider.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("openai", provider)], openai_reasoning_effort="low")

    await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.3,
        max_tokens=10,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["temperature"] == 1
    assert kwargs["reasoning_effort"] == "low"


# ── named "vllm" provider slot: request-shaping sanity (no client change) ─────
#
# The distinct "vllm" slot must be shaped like the openai-compat (vLLM) path:
# `max_tokens` (NOT `max_completion_tokens`, since the localhost base_url is not
# real OpenAI), the Qwen `chat_template_kwargs` thinking switch when disabled,
# and NO gemini message normalization. These guard the plan's "no client change"
# assumption for provider_name == "vllm".


async def test_stream_vllm_named_slot_keeps_max_tokens():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("vllm", provider)])

    await _collect_stream(client, "vllm", None)

    kwargs = create.call_args.kwargs
    assert kwargs["max_tokens"] == 50
    assert "max_completion_tokens" not in kwargs


async def test_stream_vllm_named_slot_gets_chat_template_kwargs_when_disabled():
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("vllm", provider)], enable_thinking=False)

    await _collect_stream(client, "vllm", None)

    kwargs = create.call_args.kwargs
    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "max_completion_tokens" not in kwargs


async def test_stream_vllm_named_slot_messages_not_gemini_normalized():
    # A tool-role message keeps its `name` key (gemini-normalize would drop it).
    provider, create = _make_stream_provider(["ok"])
    provider.base_url = _VLLM_URL
    client = StreamingClient(providers=[("vllm", provider)])
    msgs = [{"role": "tool", "tool_call_id": "t1", "name": "kb_search", "content": "x"}]

    async def on_token(_):
        return None

    await client.stream_completion(
        messages=msgs,
        tools=[],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=on_token,
    )

    sent = create.call_args.kwargs["messages"]
    assert sent is msgs  # passthrough (same object) → NOT gemini-normalized
    assert sent[0].get("name") == "kb_search"


async def test_stream_vllm_named_slot_falls_back_to_openai_on_error():
    """vLLM primary blows up transiently → fall back to the next slot (openai)."""

    async def boom(*_a, **_kw):
        raise RuntimeError("vllm connection refused")

    p_vllm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))
    p_vllm.base_url = _VLLM_URL
    p_oai, c_oai = _make_stream_provider(["from-openai"])
    p_oai.base_url = _OPENAI_URL
    client = StreamingClient(providers=[("vllm", p_vllm), ("openai", p_oai)])

    content, _tc = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )

    assert content == "from-openai"
    c_oai.assert_awaited_once()


# ── Fix #3: parallel index-less tool calls must not merge ────────────────────


def _tc(index, tool_id, name, args):
    """OpenAI streaming tool-call delta shape (mirrors the legacy accumulator
    test helper). `index` may be None for Gemini's compat endpoint."""
    return SimpleNamespace(
        index=index,
        id=tool_id,
        function=SimpleNamespace(name=name, arguments=args),
    )


def _make_tool_stream(tool_chunks: list[list]):
    """Provider whose create() yields one streaming chunk per element of
    `tool_chunks` (each element is a list of tool-call deltas), then a final
    stop chunk with no content/tool_calls."""

    def _chunk(tool_calls):
        return MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=tool_calls))])

    async def gen():
        for tcs in tool_chunks:
            yield _chunk(tcs)
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=None), finish_reason="stop")])

    create = AsyncMock(return_value=gen())
    provider = MagicMock()
    provider.chat.completions.create = create
    return provider, create


async def _noop_token(_t):
    return None


async def _run_tool_stream(provider):
    client = StreamingClient(providers=[("openai", provider)])
    _content, tcs = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )
    return tcs


async def test_stream_none_index_parallel_tools_not_concatenated():
    """Gemini compat: two tool calls with index=None and distinct ids must stay
    SEPARATE — args must not collapse into one Frankenstein JSON string."""
    provider, _create = _make_tool_stream(
        [
            [_tc(None, "call_A", "update_customer", '{"name":"Hùng"}')],
            [_tc(None, "call_B", "kb_search", '{"project_name":"Noble Crystal"}')],
        ]
    )

    tcs = await _run_tool_stream(provider)

    assert tcs is not None
    assert len(tcs) == 2
    assert [tc["function"]["name"] for tc in tcs] == ["update_customer", "kb_search"]
    assert tcs[0]["function"]["arguments"] == '{"name":"Hùng"}'
    assert tcs[1]["function"]["arguments"] == '{"project_name":"Noble Crystal"}'


async def test_stream_present_index_args_fragments_still_concatenate():
    """Real OpenAI: one tool call's args stream across deltas at a STABLE index.
    Continuation deltas carry index=0 with no name/id and must concatenate."""
    provider, _create = _make_tool_stream(
        [
            [_tc(0, "call_A", "kb_search", '{"proj')],
            [_tc(0, None, None, 'ect":"NCLB"}')],
        ]
    )

    tcs = await _run_tool_stream(provider)

    assert tcs is not None
    assert len(tcs) == 1
    assert tcs[0]["function"]["name"] == "kb_search"
    assert tcs[0]["function"]["arguments"] == '{"project":"NCLB"}'


async def test_stream_present_index_two_distinct_tools_stay_separate():
    """Two tool calls at distinct present indexes preserve order and stay split."""
    provider, _create = _make_tool_stream(
        [
            [_tc(0, "call_A", "update_customer", '{"name":"Hùng"}')],
            [_tc(1, "call_B", "kb_search", '{"project_name":"NCLB"}')],
        ]
    )

    tcs = await _run_tool_stream(provider)

    assert tcs is not None
    assert [tc["function"]["name"] for tc in tcs] == ["update_customer", "kb_search"]
    assert tcs[0]["function"]["arguments"] == '{"name":"Hùng"}'
    assert tcs[1]["function"]["arguments"] == '{"project_name":"NCLB"}'


async def test_stream_none_index_blank_name_returned_as_separate_raw_entry():
    """The blank-name DROP lives in runner.py (see runner.py:65-73), not the
    client. The client must return both index-less entries as SEPARATE raw
    tool calls (distinct ids) so the runner can drop the blank one without the
    accumulator having merged it into the valid call."""
    provider, _create = _make_tool_stream(
        [
            [_tc(None, "call_bad", None, "{}")],
            [_tc(None, "call_ok", "update_customer", '{"name":"Hùng"}')],
        ]
    )

    tcs = await _run_tool_stream(provider)

    assert tcs is not None
    assert len(tcs) == 2
    assert tcs[0]["id"] == "call_bad"
    assert tcs[0]["function"]["name"] == ""
    assert tcs[1]["id"] == "call_ok"
    assert tcs[1]["function"]["name"] == "update_customer"
    assert tcs[1]["function"]["arguments"] == '{"name":"Hùng"}'


# ── L1: gemini-only OpenAI-compat message normalization ──────────────────────
#
# Gemini's OpenAI-compat endpoint rejects (400 INVALID_ARGUMENT) the canonical
# OpenAI shape this package stores internally: a stray `name` key on tool
# messages, tool_calls entries without an `index`, and empty/missing
# `function.arguments`. `_normalize_for_openai_compat` reshapes the outgoing
# message list AT THE GEMINI BOUNDARY ONLY (mirroring how anthropic_provider
# translates), returning NEW dicts so the runner's reused `messages` list is
# never mutated. openai / vLLM / anthropic paths must get the list untouched.


def _post_tool_history() -> list[dict]:
    """Realistic post-tool-result history in canonical OpenAI shape, built via
    ThreadMessage.to_openai so the fixture matches what the runner persists.

    The assistant turn carries THREE tool calls: one with empty args (must
    default to "{}"), one valid, and one with an empty id (must be dropped).
    None carry an `index`. The tool-result message carries the stray `name`.
    """
    assistant = ThreadMessage(
        role="assistant",
        content="",
        tool_calls=[
            {"id": "call_A", "type": "function", "function": {"name": "kb_search", "arguments": ""}},
            {
                "id": "call_B",
                "type": "function",
                "function": {"name": "update_customer", "arguments": '{"name":"Hùng"}'},
            },
            {"id": "", "type": "function", "function": {"name": "stray", "arguments": "{}"}},
        ],
    ).to_openai()
    tool_result = ThreadMessage(
        role="tool", tool_call_id="call_A", name="kb_search", content="...kb result..."
    ).to_openai()
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Anh tên Hùng, muốn tìm hiểu Noble Crystal"},
        assistant,
        tool_result,
    ]


def test_normalize_for_openai_compat_strips_tool_name_and_shapes_args():
    msgs = _post_tool_history()
    out = _normalize_for_openai_compat(msgs, "gemini")

    # System + user pass through unchanged in content.
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1]["role"] == "user"

    # Assistant tool_calls: empty-id entry dropped → 2 remain, each indexed.
    assistant = out[2]
    tcs = assistant["tool_calls"]
    assert [tc["id"] for tc in tcs] == ["call_A", "call_B"]
    assert [tc["index"] for tc in tcs] == [0, 1]
    # Empty args defaulted to a valid JSON-object string; valid args preserved.
    assert tcs[0]["function"]["arguments"] == "{}"
    assert tcs[1]["function"]["arguments"] == '{"name":"Hùng"}'
    assert assistant["content"] == ""  # never None

    # Tool-result message: stray `name` dropped, ids/content preserved.
    tool_msg = out[3]
    assert "name" not in tool_msg
    assert tool_msg["tool_call_id"] == "call_A"
    assert tool_msg["content"] == "...kb result..."

    # Immutability: the caller's list/dicts are untouched.
    assert "name" in msgs[3]
    assert "index" not in msgs[2]["tool_calls"][0]
    assert len(msgs[2]["tool_calls"]) == 3  # empty-id entry still present in input


def test_normalize_for_openai_compat_passthrough_for_non_gemini():
    msgs = _post_tool_history()

    for provider_name in ("openai", "anthropic"):
        out = _normalize_for_openai_compat(msgs, provider_name)
        # Same list object returned → other providers are provably untouched.
        assert out is msgs
        # Tool message still has its name; assistant tool_call has no index.
        assert "name" in out[3]
        assert "index" not in out[2]["tool_calls"][0]
        assert len(out[2]["tool_calls"]) == 3


async def test_stream_gemini_normalizes_outgoing_messages():
    provider, create = _make_tool_stream([])
    provider.base_url = _GEMINI_URL
    client = StreamingClient(providers=[("gemini", provider)])

    await client.stream_completion(
        messages=_post_tool_history(),
        tools=[{"type": "function", "function": {"name": "x"}}],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )

    sent = create.call_args.kwargs["messages"]
    assert "name" not in sent[3]  # tool-result stray name dropped
    tcs = sent[2]["tool_calls"]
    assert [tc["id"] for tc in tcs] == ["call_A", "call_B"]  # empty-id dropped
    assert tcs[0]["index"] == 0
    assert tcs[0]["function"]["arguments"] == "{}"


async def test_stream_openai_messages_unchanged():
    provider, create = _make_tool_stream([])
    provider.base_url = _VLLM_URL  # openai slot, vLLM host
    client = StreamingClient(providers=[("openai", provider)])

    msgs = _post_tool_history()
    await client.stream_completion(
        messages=msgs,
        tools=[{"type": "function", "function": {"name": "x"}}],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=_noop_token,
    )

    sent = create.call_args.kwargs["messages"]
    assert sent is msgs  # untouched list object
    assert "name" in sent[3]
    assert "index" not in sent[2]["tool_calls"][0]
    assert len(sent[2]["tool_calls"]) == 3


async def test_complete_once_gemini_normalizes_outgoing_messages():
    provider, create = _make_fake_provider("ok")
    provider.base_url = _GEMINI_URL
    client = StreamingClient(providers=[("gemini", provider)])

    await client.complete_once(
        messages=_post_tool_history(),
        model="m",
        temperature=0.1,
        max_tokens=10,
    )

    sent = create.call_args.kwargs["messages"]
    assert "name" not in sent[3]
    assert sent[2]["tool_calls"][0]["index"] == 0
    assert sent[2]["tool_calls"][0]["function"]["arguments"] == "{}"


# ── Gemini 3.x thought_signature passthrough ─────────────────────────────────
#
# Gemini 3.x rejects a replayed tool call that doesn't echo back the
# `extra_content.google.thought_signature` it returned with that call
# (https://ai.google.dev/gemini-api/docs/thought-signatures). It arrives as a
# sibling of `id`/`function` on the tool-call delta/object, whole in one chunk
# (not fragmented like `arguments`).

_THOUGHT_SIG = {"google": {"thought_signature": "EuwBCukB..."}}


async def test_stream_captures_gemini_thought_signature_extra_content():
    tc_delta = SimpleNamespace(
        index=None,
        id="call_A",
        function=SimpleNamespace(name="kb_search", arguments='{"project":"NCLB"}'),
        extra_content=_THOUGHT_SIG,
    )
    provider, _create = _make_tool_stream([[tc_delta]])

    tcs = await _run_tool_stream(provider)

    assert tcs is not None
    assert tcs[0]["extra_content"] == _THOUGHT_SIG


def test_normalize_for_openai_compat_preserves_thought_signature():
    assistant = ThreadMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_A",
                "type": "function",
                "function": {"name": "kb_search", "arguments": '{"project":"NCLB"}'},
                "extra_content": _THOUGHT_SIG,
            },
        ],
    ).to_openai()
    msgs = [{"role": "user", "content": "hi"}, assistant]

    out = _normalize_for_openai_compat(msgs, "gemini")

    assert out[1]["tool_calls"][0]["extra_content"] == _THOUGHT_SIG


# ── L2: error chaining + transient classification ────────────────────────────


def _raising_provider(exc: Exception):
    async def boom(*_a, **_kw):
        raise exc

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))


async def test_all_providers_failed_chains_original_exception_complete_once():
    err_a = RuntimeError("boom-A")
    err_b = RuntimeError("boom-B")
    client = StreamingClient(providers=[("anthropic", _raising_provider(err_a)), ("openai", _raising_provider(err_b))])

    with pytest.raises(RuntimeError) as ei:
        await client.complete_once(
            messages=[{"role": "user", "content": "hi"}],
            model="m",
            temperature=0.1,
            max_tokens=10,
        )

    assert ei.value.__cause__ is err_b
    assert str(ei.value.__cause__) == "boom-B"


async def test_all_providers_failed_chains_original_exception_stream():
    err_a = RuntimeError("boom-A")
    err_b = RuntimeError("boom-B")
    client = StreamingClient(providers=[("anthropic", _raising_provider(err_a)), ("openai", _raising_provider(err_b))])

    with pytest.raises(RuntimeError) as ei:
        await client.stream_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model="m",
            temperature=0.5,
            max_tokens=50,
            on_token=_noop_token,
        )

    assert ei.value.__cause__ is err_b
    assert str(ei.value.__cause__) == "boom-B"


class _StatusError(Exception):
    """Minimal stand-in for an httpx/openai error exposing `.status_code`."""

    def __init__(self, status_code: int, msg: str):
        super().__init__(msg)
        self.status_code = status_code


def test_is_transient_classifies_status_codes():
    assert _is_transient(_StatusError(429, "rate limited")) is True
    assert _is_transient(_StatusError(500, "server error")) is True
    assert _is_transient(_StatusError(503, "unavailable")) is True
    assert _is_transient(_StatusError(400, "bad request")) is False
    assert _is_transient(_StatusError(401, "unauthorized")) is False
    assert _is_transient(_StatusError(422, "unprocessable")) is False
    # Unknown / no status → transient (preserve today's fall-through resilience).
    assert _is_transient(RuntimeError("connection reset")) is True


async def test_non_transient_error_logged_at_error_level(caplog):
    err = _StatusError(400, "INVALID_ARGUMENT: bad tool_calls")
    client = StreamingClient(providers=[("gemini", _raising_provider(err))])

    with (
        caplog.at_level(logging.ERROR, logger="noble_agent.llm"),
        pytest.raises(RuntimeError) as ei,
    ):
        await client.complete_once(
            messages=[{"role": "user", "content": "hi"}],
            model="m",
            temperature=0.1,
            max_tokens=10,
        )

    assert ei.value.__cause__ is err
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    # The non-transient body must be surfaced loudly (not silently swallowed).
    assert any("INVALID_ARGUMENT" in r.getMessage() for r in error_records)


async def test_transient_error_falls_through_to_next_provider():
    transient = _StatusError(503, "temporarily unavailable")
    p2, c2 = _make_fake_provider("from-openai")
    client = StreamingClient(providers=[("anthropic", _raising_provider(transient)), ("openai", p2)])

    out = await client.complete_once(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.1,
        max_tokens=10,
    )

    assert out == "from-openai"
    c2.assert_awaited_once()


# ── tool_choice forwarding (LLM_FORCE_TOOL_FIRST_ROUND plumbing) ─────────────

_TC_TOOLS = [{"type": "function", "function": {"name": "discover_projects", "parameters": {}}}]


async def _stream_with_tool_choice(client, tool_choice):
    async def on_token(_t): ...

    return await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=_TC_TOOLS,
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=on_token,
        tool_choice=tool_choice,
    )


async def test_stream_tool_choice_forwarded_for_openai_compat():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("gemini", provider)])
    await _stream_with_tool_choice(client, "required")
    assert create.call_args.kwargs["tool_choice"] == "required"


async def test_stream_tool_choice_not_sent_for_anthropic():
    # The Anthropic adapter speaks a different tool_choice dialect — never forward.
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("anthropic", provider)])
    await _stream_with_tool_choice(client, "required")
    assert "tool_choice" not in create.call_args.kwargs


async def test_stream_tool_choice_omitted_when_none():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("gemini", provider)])
    await _stream_with_tool_choice(client, None)
    assert "tool_choice" not in create.call_args.kwargs


async def test_stream_tool_choice_omitted_without_tools():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("gemini", provider)])

    async def on_token(_t): ...

    await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="m",
        temperature=0.5,
        max_tokens=50,
        on_token=on_token,
        tool_choice="required",
    )
    assert "tool_choice" not in create.call_args.kwargs


async def test_stream_tool_choice_dropped_for_dashscope_when_thinking_on():
    # DashScope trả 400 với tool_choice=required khi enable_thinking — không gửi.
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("dashscope", provider)], enable_thinking=True)
    await _stream_with_tool_choice(client, "required")
    assert "tool_choice" not in create.call_args.kwargs


async def test_stream_tool_choice_kept_for_dashscope_when_thinking_off():
    provider, create = _make_stream_provider(["ok"])
    client = StreamingClient(providers=[("dashscope", provider)], enable_thinking=False)
    await _stream_with_tool_choice(client, "required")
    assert create.call_args.kwargs["tool_choice"] == "required"


# ── MarkdownStripper (qwen xả bullet/bold vào chat — TTS đường voice đã có
#    _normalize lo, đây là lớp chặn cho chat stream + history) ────────────────

def _md_feed(pieces):
    from noble_agent.agent.llm.sanitize import MarkdownStripper

    s = MarkdownStripper()
    out = "".join(s.feed(p) for p in pieces)
    return out + s.flush()


def test_md_bold_stripped_even_split_across_chunks():
    assert _md_feed(["**No", "ble**", " Palace"]) == "Noble Palace"
    assert _md_feed(["giá ", "**9,6 tỷ**"]) == "giá 9,6 tỷ"


def test_md_line_start_bullets_and_numbers_stripped():
    assert _md_feed(["- Noble Palace\n- Sunrise City"]) == "Noble Palace\nSunrise City"
    assert _md_feed(["1. căn A\n", "2. căn B"]) == "căn A\ncăn B"
    assert _md_feed(["# Tiêu đề\nnội dung"]) == "Tiêu đề\nnội dung"


def test_md_keeps_legit_text_intact():
    assert _md_feed(["Căn A-0501 giá 4,05 tỷ - rất đẹp"]) == "Căn A-0501 giá 4,05 tỷ - rất đẹp"
    assert _md_feed(["gọi 1900 23 23 49 nhé"]) == "gọi 1900 23 23 49 nhé"
    assert _md_feed(["2 * 3 = 6"]) == "2 * 3 = 6"


async def test_md_stream_strips_tokens_and_returned_content():
    provider, create = _make_stream_provider(["**Nob", "le**", " Palace\n- giá tốt"])
    client = StreamingClient(providers=[("dashscope", provider)])
    tokens: list[str] = []

    async def on_token(t):
        tokens.append(t)

    content, _tc = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}], tools=[], model="m",
        temperature=0.5, max_tokens=50, on_token=on_token,
    )
    assert content == "Noble Palace\ngiá tốt"
    assert "".join(tokens) == "Noble Palace\ngiá tốt"
