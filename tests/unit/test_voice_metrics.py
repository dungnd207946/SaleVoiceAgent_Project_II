"""Tests for MetricsCollector integration in VoiceAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.metrics import MetricsCollector


@pytest.mark.asyncio
async def test_voice_agent_records_llm_and_tts_metrics():
    """handle_utterance should record llm.ttft, llm.total, tts.ttfb, tts.total, e2e.ttfa."""
    metrics = MetricsCollector()

    # Mock TTS that yields 2 chunks
    async def fake_tts_stream(text):
        yield b"\x00" * 320
        yield b"\x00" * 320

    mock_tts = MagicMock()
    mock_tts.stream = fake_tts_stream

    # Mock LLM that streams 1 sentence
    async def fake_stream_response(
        user_text,
        on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        on_agent_switch=None,
    ):
        on_token("Hello world.")
        return "Hello world."

    mock_llm = MagicMock()
    mock_llm.stream_response = fake_stream_response

    from noble_agent.voice.voice_agent import VoiceAgent

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._llm = mock_llm
    agent._tts = mock_tts
    agent._interrupted = False
    agent._metrics = metrics
    agent._billing = None  # billing metering off by default (fix round 2, Task 7)

    await agent.handle_utterance("test input")

    # Check that metrics were recorded
    summary = metrics.summary()
    latency = summary["latency"]

    assert "llm" in latency
    assert "ttft" in latency["llm"]
    assert "total" in latency["llm"]
    assert latency["llm"]["ttft"]["count"] == 1
    assert latency["llm"]["total"]["count"] == 1

    assert "tts" in latency
    assert "ttfb" in latency["tts"]
    assert latency["tts"]["ttfb"]["count"] >= 1

    assert "e2e" in latency
    assert "ttfa" in latency["e2e"]
    assert latency["e2e"]["ttfa"]["count"] == 1
