"""VoiceAgent phải báo facade cắt history khi khách ngắt lời — trên CẢ đường transport
cancel task lẫn đường chỉ set cờ; và CHỈ khi LLM đã trả lời xong (history đã persist)."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

from tests.unit.test_voice_agent_pause import _make_full_agent

_SENT = ["Dạ chào anh, câu một đây ạ.", "Đây là câu thứ hai dài hơn.", "Và câu thứ ba cuối cùng."]


def _slow_tts_agent(sentences, delay=0.05):
    agent = _make_full_agent(sentences)

    async def slow_stream(text):
        for _ in range(3):
            await asyncio.sleep(delay)
            yield b"\x01" * 320

    agent._tts.stream = slow_stream
    agent._llm.note_interrupted = AsyncMock(return_value=True)
    return agent


async def _wait_spoken(agent, n, timeout=2.0):
    t0 = asyncio.get_event_loop().time()
    while len(getattr(agent, "_spoken_texts", [])) < n:  # attr chỉ có sau khi handle_utterance bắt đầu
        await asyncio.sleep(0.005)
        assert asyncio.get_event_loop().time() - t0 < timeout, "chưa phát đủ clause"


async def test_cancelled_during_playback_trims_to_spoken_text():
    agent = _slow_tts_agent(_SENT)
    task = asyncio.ensure_future(agent.handle_utterance("hi"))
    await _wait_spoken(agent, 1)
    agent.interrupt()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    agent._llm.note_interrupted.assert_awaited_once()
    spoken = agent._llm.note_interrupted.call_args.kwargs["spoken_text"]
    assert spoken.startswith("Dạ chào anh, câu một đây ạ.")
    assert "câu thứ ba" not in spoken


async def test_flag_only_interrupt_also_trims():
    agent = _slow_tts_agent(_SENT)
    task = asyncio.ensure_future(agent.handle_utterance("hi"))
    await _wait_spoken(agent, 1)
    agent.interrupt()  # không cancel task — pacer tự thoát khi thấy cờ
    await task
    agent._llm.note_interrupted.assert_awaited_once()


async def test_no_trim_when_llm_not_finished():
    agent = _slow_tts_agent(_SENT)

    async def never_returns(*a, **k):
        await asyncio.sleep(10)

    agent._llm.stream_response = never_returns
    task = asyncio.ensure_future(agent.handle_utterance("hi"))
    await asyncio.sleep(0.02)
    agent.interrupt()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    agent._llm.note_interrupted.assert_not_awaited()


async def test_uninterrupted_turn_does_not_trim():
    agent = _slow_tts_agent(_SENT, delay=0.001)
    await agent.handle_utterance("hi")
    agent._llm.note_interrupted.assert_not_awaited()


async def test_llm_without_hook_is_tolerated():
    agent = _slow_tts_agent(_SENT)
    agent._llm = MagicMock()
    agent._llm.stream_response = _make_full_agent(_SENT)._llm.stream_response
    task = asyncio.ensure_future(agent.handle_utterance("hi"))
    await _wait_spoken(agent, 1)
    agent.interrupt()
    await task  # không nổ dù _llm không có note_interrupted (MagicMock sync)
