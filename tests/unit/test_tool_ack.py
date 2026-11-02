"""Tests for the tool-call bridge-phrase ack feature (voice.py).

When the LLM fires a slow tool (RAG / DB lookup) we push a pre-canned
Vietnamese acknowledgement into the TTS queue so the caller doesn't hear
1-2 s of silence while the tool + second LLM call run.

Invariants:
- Fires once per turn, even if multiple slow tools run.
- Does NOT fire for tools in `settings.tool_ack_fast_tools`.
- Disabling via `settings.tool_ack_enabled = False` suppresses it entirely.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


async def _fake_tts_stream(_text: str):
    yield b"\x00" * 320
    yield b"\x00" * 320


def _build_agent(metrics, ack_assets: list[bytes] | None = None):
    from noble_agent.config import settings
    from noble_agent.voice.voice_agent import VoiceAgent

    # These tests exercise the ack fire/cancel mechanism, not the production
    # frequency thinning (probability + cooldown). Pin both to deterministic
    # "always eligible" so the assertions stay stable.
    settings.tool_ack_probability = 1.0
    settings.tool_ack_cooldown_s = 0.0

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._interrupted = False
    agent._metrics = metrics
    agent._billing = None  # billing metering off by default (fix round 2, Task 7)
    agent._last_ack_monotonic = 0.0
    mock_tts = MagicMock()
    mock_tts.stream = _fake_tts_stream
    agent._tts = mock_tts
    # Default: no pre-synth assets → tests exercise the live-TTS fallback
    # path where the ack text is visible on `_tts.stream()`.
    agent._ack_assets = ack_assets or []
    return agent


def _make_llm(tool_names: list[str], *, token_delay: float = 0.3):
    """Build a fake LLM that fires on_tool_start for each name then emits text.

    `token_delay` simulates a slow tool: the LLM stays silent for `token_delay`
    seconds after the tool starts before streaming its first token. The ack is
    deferred ~250 ms (see VoiceAgent.handle_utterance), so a delay > 0.25 s lets
    the canned ack fire before the LLM speaks — matching production, where a
    tool round-trip always outlasts the ack timer.
    """

    async def fake_stream_response(
        user_text,
        on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        on_agent_switch=None,
    ):
        for name in tool_names:
            if on_tool_start:
                on_tool_start(name, {"q": "x"})
        if token_delay:
            await asyncio.sleep(token_delay)
        on_token("Dạ.")
        return "Dạ."

    mock_llm = MagicMock()
    mock_llm.stream_response = fake_stream_response
    return mock_llm


async def _collect_tts_texts(agent, original_stream):
    """Monkeypatch tts stream to record every tts_text passed in."""
    seen: list[str] = []

    async def _recorder(text: str):
        seen.append(text)
        async for chunk in original_stream(text):
            yield chunk

    agent._tts.stream = _recorder
    return seen


@pytest.mark.asyncio
async def test_ack_fires_once_for_slow_tool() -> None:
    from noble_agent.config import settings
    from noble_agent.metrics import MetricsCollector

    agent = _build_agent(MetricsCollector())
    agent._llm = _make_llm(["kb_search"])

    seen = await _collect_tts_texts(agent, _fake_tts_stream)
    await agent.handle_utterance("tell me about NCTH")

    assert settings.tool_ack_text.rstrip(". ") in " ".join(seen), f"expected ack phrase in TTS stream, got: {seen!r}"


@pytest.mark.asyncio
async def test_ack_does_not_fire_for_fast_tools() -> None:
    from noble_agent.config import settings
    from noble_agent.metrics import MetricsCollector

    agent = _build_agent(MetricsCollector())
    agent._llm = _make_llm(["update_customer"])

    seen = await _collect_tts_texts(agent, _fake_tts_stream)
    await agent.handle_utterance("xin chào")

    ack = settings.tool_ack_text
    assert not any(ack in s for s in seen), f"ack should not fire for fast tools, got: {seen!r}"


@pytest.mark.asyncio
async def test_ack_fires_only_once_even_with_multiple_slow_tools() -> None:
    from noble_agent.config import settings
    from noble_agent.metrics import MetricsCollector

    agent = _build_agent(MetricsCollector())
    agent._llm = _make_llm(["kb_search", "get_project_overview", "search_units"])

    seen = await _collect_tts_texts(agent, _fake_tts_stream)
    await agent.handle_utterance("anh muốn tìm hiểu")

    ack = settings.tool_ack_text
    count = sum(1 for s in seen if ack in s)
    assert count == 1, f"ack should fire exactly once, got {count}. TTS texts: {seen!r}"


@pytest.mark.asyncio
async def test_ack_suppressed_when_llm_already_emitted_text() -> None:
    """If the LLM has already streamed any text when the tool call fires,
    skip the ack — otherwise the caller hears doubled bridge phrases
    (the LLM's own "Dạ để em kiểm tra..." plus our pre-synth one)."""
    from noble_agent.metrics import MetricsCollector

    agent = _build_agent(MetricsCollector(), ack_assets=[b"\x00" * 960 * 5])

    async def fake_stream_response(
        user_text,
        on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        on_agent_switch=None,
    ):
        # LLM emits text FIRST, THEN calls a slow tool.
        on_token("Dạ để em kiểm tra ngay ạ.")
        if on_tool_start:
            on_tool_start("kb_search", {"q": "x"})
        return "Dạ để em kiểm tra ngay ạ."

    mock_llm = MagicMock()
    mock_llm.stream_response = fake_stream_response
    agent._llm = mock_llm

    sent_audio: list[bytes] = []
    agent._send_audio = AsyncMock(side_effect=lambda b: sent_audio.append(b))

    await agent.handle_utterance("tell me about NCTH")

    # Pre-synth PCM must NOT appear in the audio stream — we suppressed it.
    total = b"".join(sent_audio)
    ack_pcm = agent._ack_assets[0]
    assert ack_pcm not in total, "ack should have been suppressed because LLM already spoke"


@pytest.mark.asyncio
async def test_ack_uses_pre_synth_asset_when_available() -> None:
    """When _ack_assets is populated, the ack should stream pre-synth PCM
    directly — NOT hit _tts.stream()."""
    from noble_agent.metrics import MetricsCollector

    fake_pcm = b"\x00" * 960 * 10  # ~0.4s @ 24 kHz
    agent = _build_agent(MetricsCollector(), ack_assets=[fake_pcm])
    agent._llm = _make_llm(["kb_search"])

    seen = await _collect_tts_texts(agent, _fake_tts_stream)
    sent_audio_calls: list[bytes] = []
    agent._send_audio = AsyncMock(side_effect=lambda b: sent_audio_calls.append(b))

    await agent.handle_utterance("tell me about NCTH")

    # No TTS stream invocation for the ack itself — it should have been
    # the LLM text only ("Dạ.").
    assert seen == ["Dạ."], f"pre-synth assets must NOT route through _tts.stream, got: {seen!r}"
    # The pre-synth bytes made it to send_audio (frame-chunked).
    total_sent = b"".join(sent_audio_calls)
    assert fake_pcm in total_sent, "pre-synth PCM must reach send_audio"


@pytest.mark.asyncio
async def test_ack_suppressed_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from noble_agent.config import settings
    from noble_agent.metrics import MetricsCollector

    monkeypatch.setattr(settings, "tool_ack_enabled", False)

    agent = _build_agent(MetricsCollector())
    agent._llm = _make_llm(["kb_search"])

    seen = await _collect_tts_texts(agent, _fake_tts_stream)
    await agent.handle_utterance("tell me about NCTH")

    assert not any(settings.tool_ack_text in s for s in seen), f"ack should be suppressed when disabled, got: {seen!r}"
