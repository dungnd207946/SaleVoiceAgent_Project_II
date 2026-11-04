"""Soft-pause/resume của VoiceAgent pacer (addressee gate) — không cần TTS/LLM thật.

Construct qua __new__ (pattern sẵn có trong codebase — xem comment
voice_agent.py ~line 700) và test trực tiếp helper `_wait_if_paused` +
`_play_resume_ack` + invariant interrupt-giải-phóng-pause.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from noble_agent.metrics import MetricsCollector
from noble_agent.voice.voice_agent import VoiceAgent


def _bare_agent(sent: list[bytes]):
    a = VoiceAgent.__new__(VoiceAgent)
    a._interrupted = False
    a._playback_paused = False
    a._resume_event = asyncio.Event()
    a._resume_event.set()
    a._resume_with_ack = False
    a._resume_ack_pcm = b""

    async def _send(chunk: bytes) -> None:
        sent.append(chunk)

    a._send_audio = _send
    return a


class TestWaitIfPaused:
    async def test_not_paused_returns_false_immediately(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        assert await a._wait_if_paused([b"f0"]) is False
        assert sent == []

    async def test_resume_replays_clause_frames_after_ack(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._resume_ack_pcm = b"ACK!" * 400  # pre-synth asset path (không cần TTS)
        a.pause_playback()

        async def _resume_soon():
            await asyncio.sleep(0.01)
            a.resume_playback()

        task = asyncio.ensure_future(_resume_soon())
        committed = await a._wait_if_paused([b"f0", b"f1"])
        await task
        assert committed is False
        # ack frames trước, rồi replay đúng thứ tự clause frames
        assert sent[-2:] == [b"f0", b"f1"]
        assert len(sent) > 2  # có ack đứng trước

    async def test_commit_interrupt_while_paused_returns_true(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a.pause_playback()

        async def _interrupt_soon():
            await asyncio.sleep(0.01)
            a.interrupt()  # commit — phải tự giải phóng pause

        task = asyncio.ensure_future(_interrupt_soon())
        committed = await a._wait_if_paused([b"f0"])
        await task
        assert committed is True
        assert sent == []  # không replay gì khi commit

    async def test_pause_tts_also_releases_pause(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._tts = type("T", (), {})()  # không có .pause — nhánh getattr None
        a.pause_playback()

        async def _hard_pause_soon():
            await asyncio.sleep(0.01)
            await a.pause_tts()

        task = asyncio.ensure_future(_hard_pause_soon())
        committed = await a._wait_if_paused([])
        await task
        assert committed is True


class TestPlayResumeAck:
    async def test_asset_pcm_streamed_in_frames(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        with patch("noble_agent.voice.voice_agent.settings") as s:
            s.tts_sample_rate = 24000
            s.addressee_resume_ack_text = "Em xin phép được nói tiếp ạ."
            frame_bytes = int(24000 * 0.04) * 2
            a._resume_ack_pcm = b"\x01\x02" * frame_bytes  # 2 frames worth
            await a._play_resume_ack()
        assert len(sent) >= 2
        assert b"".join(sent) == a._resume_ack_pcm

    async def test_no_asset_no_text_is_noop(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        with patch("noble_agent.voice.voice_agent.settings") as s:
            s.addressee_resume_ack_text = ""
            a._resume_ack_pcm = b""
            await a._play_resume_ack()
        assert sent == []


class TestReviewRound1Findings:
    """Coverage added in review round 1 (Findings 2, 3, 4, 5)."""

    async def test_resume_not_parked_in_gate_still_plays_ack(self) -> None:
        """Finding 2 regression: pause()+resume() both land while the pacer
        is NOT currently blocked inside `_wait_if_paused` (e.g. it's still
        awaiting `frame_q.get()` during TTS TTFB). The very next gate call
        must still see the pending `_resume_with_ack` and play the ack +
        replay — not silently drop it just because `_playback_paused` is
        already False by the time the gate runs."""
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._resume_ack_pcm = b"ACK!" * 400  # pre-synth path, no TTS needed

        a.pause_playback()
        a.resume_playback()  # both land before the gate ever waits
        assert a._playback_paused is False  # not parked — the bug's premise

        committed = await a._wait_if_paused([b"f0", b"f1"])

        assert committed is False
        assert sent[-2:] == [b"f0", b"f1"]
        assert len(sent) > 2  # ack frames preceded the replay

    async def test_repause_during_replay_does_not_double_send(self) -> None:
        """Finding 3: a SECOND pause_playback() fired mid-replay (from inside
        the send callback, simulating another side-talk verdict arriving
        while the first resume's replay is still in flight) must re-park the
        gate instead of racing the remaining frames out, and must not
        re-send a frame that was already replayed."""
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._resume_ack_pcm = b"ACK!" * 400
        frames = [b"f0", b"f1", b"f2"]
        repaused = {"done": False}

        async def _send(chunk: bytes) -> None:
            sent.append(chunk)
            if chunk == b"f0" and not repaused["done"]:
                repaused["done"] = True
                a.pause_playback()

        a._send_audio = _send
        a.pause_playback()

        async def _resume_then_resume_again():
            await asyncio.sleep(0.01)
            a.resume_playback()  # ack #1 plays, f0 replays, re-pause fires
            await asyncio.sleep(0.01)
            assert a._playback_paused is True  # confirm it actually re-parked
            a.resume_playback()  # ack #2 plays, replay continues from f1

        task = asyncio.ensure_future(_resume_then_resume_again())
        committed = await a._wait_if_paused(frames)
        await task

        assert committed is False
        clause_part = [c for c in sent if c in frames]
        assert clause_part == [b"f0", b"f1", b"f2"]  # each frame exactly once, in order

    async def test_pause_after_interrupt_is_noop(self) -> None:
        """Finding 4: pause_playback() must no-op once _interrupted is
        already True — otherwise it clears _resume_event with no consumer
        left to ever set it again, wedging a later speak_text/handle_utterance
        turn that waits on the same event."""
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a.interrupt()
        assert a._resume_event.is_set()

        a.pause_playback()

        assert a._playback_paused is False
        assert a._resume_event.is_set()

    async def test_watchdog_timeout_resumes_without_ack(self) -> None:
        """Finding 5: if the verdict producer dies (pause() called but
        resume() never comes), the gate must fail OPEN after the watchdog
        timeout — resuming playback without ack/replay — instead of wedging
        the pacer (and agent_done) forever."""
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a.pause_playback()  # never resumed

        with patch("noble_agent.voice.voice_agent._PAUSE_WATCHDOG_S", 0.05):
            committed = await a._wait_if_paused([b"f0"])

        assert committed is False
        assert a._playback_paused is False
        assert a._resume_event.is_set()
        assert sent == []  # fail-open: no ack, no replay


def _llm_emitting(sentences: list[str]):
    """Fake LLM whose stream_response emits each sentence as one token —
    mirrors tests/unit/test_voice_tts_pipeline.py's harness. Each sentence
    must end in sentence-final punctuation + trailing space and be long
    enough (>=10 chars) that SentenceBuffer flushes it as its own clause."""

    async def fake_stream_response(
        user_text,
        on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        on_agent_switch=None,
    ):
        full = ""
        for s in sentences:
            tok = s + " "
            on_token(tok)
            full += tok
        return full

    llm = MagicMock()
    llm.stream_response = fake_stream_response
    return llm


def _make_full_agent(sentences: list[str]) -> VoiceAgent:
    async def fake_stream(text):
        yield b"\x01" * 320

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._llm = _llm_emitting(sentences)
    agent._tts = tts
    agent._interrupted = False
    agent._metrics = MetricsCollector()
    agent._billing = None  # billing metering off by default (fix round 2, Task 7)
    agent._ack_assets = []
    agent._last_ack_monotonic = 0.0
    return agent


class TestSpokenTextThisTurn:
    """`VoiceAgent.spoken_text_this_turn` — dialogue-ring context (2026-08-12 chiều)."""

    def test_property_joins_accumulated_clauses_with_space(self) -> None:
        a = VoiceAgent.__new__(VoiceAgent)
        a._spoken_texts = ["Dạ chào anh.", "Dự án ở quận 2 ạ."]
        assert a.spoken_text_this_turn == "Dạ chào anh. Dự án ở quận 2 ạ."

    def test_property_empty_when_attr_missing(self) -> None:
        a = VoiceAgent.__new__(VoiceAgent)
        assert a.spoken_text_this_turn == ""

    async def test_accumulates_across_clauses_in_pacer_order(self) -> None:
        agent = _make_full_agent(["Dạ chào anh ạ.", "Dự án này rất đẹp."])
        await agent.handle_utterance("hi")
        assert agent.spoken_text_this_turn == "Dạ chào anh ạ. Dự án này rất đẹp."

    async def test_handle_utterance_reset_clears_prior_turn_text(self) -> None:
        agent = _make_full_agent(["Dạ chào anh ạ."])
        agent._spoken_texts = ["stale text from a previous turn"]
        await agent.handle_utterance("hi")
        assert "stale" not in agent.spoken_text_this_turn
        assert agent.spoken_text_this_turn == "Dạ chào anh ạ."

    async def test_pause_resume_replay_does_not_double_append(self) -> None:
        """The pacer appends to `_spoken_texts` exactly once per clause, gated
        by `sent_speaking`, in the `if not sent_speaking:` block — NOT inside
        `_wait_if_paused`. So a pause→resume mid-clause (which replays the
        clause's already-sent frames via `_wait_if_paused`) must not touch
        `_spoken_texts` at all, regardless of how many frames get resent."""
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._resume_ack_pcm = b"ACK!" * 400  # pre-synth asset path (không cần TTS)
        a._spoken_texts = ["Dạ vâng ạ."]  # simulates the one-time sent_speaking append
        a.pause_playback()

        async def _resume_soon():
            await asyncio.sleep(0.01)
            a.resume_playback()

        task = asyncio.ensure_future(_resume_soon())
        committed = await a._wait_if_paused([b"f0", b"f1"])
        await task

        assert committed is False
        assert sent[-2:] == [b"f0", b"f1"]  # replay did happen
        assert a._spoken_texts == ["Dạ vâng ạ."]  # untouched by the replay
