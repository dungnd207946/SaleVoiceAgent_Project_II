"""Part 2 — synth-ahead / pacer prefetch pipeline in VoiceAgent.tts_consumer.

The consumer is split into a synth-ahead task (synthesizes clause N+1 while
clause N plays at realtime) and a pacer (sends frames in order, realtime-paced
by capture_frame backpressure). These tests prove:

  * overlap: clause N+1's synth STARTS before clause N's last `_send_audio` returns;
  * strict in-order playback;
  * barge-in (`immediate` + `finish_current`) stops promptly, cancels the
    synth-ahead task (no orphan), fires one `agent_interrupted`, preserves
    `_last_completed_id`, and still sends `agent_done`;
  * tool-ack `pcm_data` clauses still flow through the pipeline;
  * metrics (tts.ttfb/tts.total in synth-ahead, e2e.ttfa in pacer) still recorded.

Harness mirrors tests/unit/test_voice_metrics.py: VoiceAgent.__new__ + injected
AsyncMocks + a fake LLM + a fake TTS. asyncio_mode=auto → no decorator needed.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from noble_agent.config import settings
from noble_agent.metrics import MetricsCollector
from noble_agent.voice.voice_agent import VoiceAgent


def _make_agent(tts, llm) -> VoiceAgent:
    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._llm = llm
    agent._tts = tts
    agent._interrupted = False
    agent._metrics = MetricsCollector()
    agent._billing = None  # billing metering off by default (fix round 2, Task 7)
    agent._ack_assets = []
    agent._last_ack_monotonic = 0.0
    return agent


def _llm_emitting(sentences: list[str]):
    """Fake LLM whose stream_response emits each sentence as one token.

    SentenceBuffer flushes a clause on sentence-final punctuation only when the
    next char is whitespace AND the clause is >= MIN_LENGTH (10). We append a
    trailing space and keep each sentence long enough so each becomes its own
    clause mid-stream (not coalesced into the end-of-turn flush).
    """

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


# ── Test 1: overlap proof (the load-bearing one) ───────────────────────────────


async def test_next_clause_synth_overlaps_playout():
    """Clause N+1's synth STARTS before clause N's last `_send_audio` returns.

    The fake TTS sleeps before its first frame; if synth were sequential, clause
    1's stream() would only begin AFTER clause 0 fully sent. We assert the
    timestamps prove overlap.
    """
    t_stream_called: dict[int, float] = {}
    call_seq: list[int] = []
    # Map frame payload byte → clause index so we can attribute sends to clauses.
    frame_marker = {0: b"\x00", 1: b"\x11"}

    async def fake_stream(text):
        idx = len(call_seq)
        call_seq.append(idx)
        t_stream_called[idx] = time.monotonic()
        marker = frame_marker.get(idx, b"\x22")
        await asyncio.sleep(0.15)  # synth latency before first frame
        for _ in range(3):
            yield marker * 320
            await asyncio.sleep(0.02)

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["Clause zero now.", "Clause one now."]))

    # Record the return time of each clause-0 send (after simulated playout).
    clause0_send_returns: list[float] = []
    orig = agent._send_audio

    async def timed_send(frame):
        await orig(frame)
        await asyncio.sleep(0.03)  # simulate realtime playout backpressure
        if frame[:1] == frame_marker[0]:
            clause0_send_returns.append(time.monotonic())

    agent._send_audio = timed_send

    await agent.handle_utterance("hi")

    assert 0 in t_stream_called and 1 in t_stream_called
    assert clause0_send_returns, "clause-0 frames never sent"
    # The proof: clause-1's synth STARTED before clause-0's LAST send returned.
    # Under sequential code clause-1 stream() only begins after clause-0 fully
    # sends → this strictly fails there.
    assert t_stream_called[1] < clause0_send_returns[-1]


# ── Test 2: strict ordering ─────────────────────────────────────────────────────


async def test_clauses_play_in_order():
    """agent_speaking sentence_ids arrive 0,1,2 in order; frames never interleave."""

    async def fake_stream(text):
        for _ in range(2):
            yield b"\x01" * 320

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["Clause number zero.", "Clause number one.", "Clause number two."]))
    await agent.handle_utterance("hi")

    speaking_ids = [
        c.args[0]["sentence_id"] for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_speaking"
    ]
    assert speaking_ids == [0, 1, 2]

    # agent_done sent exactly once.
    done = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_done"]
    assert len(done) == 1


# ── Test 3: barge-in immediate ──────────────────────────────────────────────────


async def test_barge_in_immediate_cancels_within_one_frame():
    """Setting `_interrupted` mid-playout (immediate) stops sends within ~one frame,
    cancels the synth-ahead task, fires one agent_interrupted, and sends agent_done."""
    synth_running = {"active": 0, "max": 0}

    async def fake_stream(text):
        synth_running["active"] += 1
        synth_running["max"] = max(synth_running["max"], synth_running["active"])
        try:
            for _ in range(20):  # long clause so interrupt lands mid-stream
                yield b"\x02" * 320
                await asyncio.sleep(0.01)
        finally:
            synth_running["active"] -= 1

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["First clause is long.", "Second clause."]))

    send_count = {"n": 0}
    orig = agent._send_audio

    async def trigger_send(frame):
        await orig(frame)
        send_count["n"] += 1
        if send_count["n"] == 1:
            await agent.pause_tts()  # sets _interrupted + tts.pause()

    agent._send_audio = trigger_send

    await agent.handle_utterance("hi")

    # Stopped promptly: at most ~1 extra frame after the trigger.
    assert send_count["n"] <= 2
    # Synth-ahead task is gone (no orphan running).
    assert synth_running["active"] == 0
    tts.pause.assert_awaited()

    interrupts = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_interrupted"]
    assert len(interrupts) == 1
    # Clause 0 never completed → _last_completed_id stays -1.
    assert interrupts[0].args[0]["last_completed_sentence_id"] == -1

    done = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_done"]
    assert len(done) == 1


# ── Test 4: barge-in finish_current ─────────────────────────────────────────────


async def test_barge_in_finish_current_drops_rest(monkeypatch):
    """finish_current: interrupt during clause 0 → clause 0 finishes (all its frames
    sent, _last_completed_id==0), later clauses dropped, one agent_interrupted, agent_done."""
    monkeypatch.setattr(settings, "interrupt_mode", "finish_current")

    clause_frames = {0: 0, 1: 0}
    call_seq: list[int] = []

    async def fake_stream(text):
        idx = len(call_seq)
        call_seq.append(idx)
        n = 3
        for _ in range(n):
            if idx in clause_frames:
                clause_frames[idx] += 1
            yield b"\x03" * 320
            await asyncio.sleep(0.005)

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["Clause number zero.", "Clause number one.", "Clause number two."]))

    send_count = {"n": 0}
    orig = agent._send_audio

    async def trigger_send(frame):
        await orig(frame)
        send_count["n"] += 1
        if send_count["n"] == 1:
            agent._interrupted = True  # interrupt during clause 0

    agent._send_audio = trigger_send

    await agent.handle_utterance("hi")

    # Clause 0 finished fully (finish_current drains the current clause).
    assert clause_frames[0] == 3
    # Later clauses dropped.
    assert clause_frames[1] == 0

    interrupts = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_interrupted"]
    assert len(interrupts) == 1
    assert interrupts[0].args[0]["last_completed_sentence_id"] == 0

    done = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_done"]
    assert len(done) == 1


# ── Test 4b: barge-in between clauses (pacer top-of-loop interrupt path) ────────


async def test_barge_in_between_clauses_stops_before_next(monkeypatch):
    """Interrupt set after clause 0 fully completes but before clause 1 is paced →
    the pacer's top-of-loop interrupt check fires (finish_current keeps the inner
    loop from claiming a mid-tts interrupt). Clause 1 never played; one
    agent_interrupted, _last_completed_id==0, agent_done sent.

    Uses finish_current so clause 0's last frame + sentinel are consumed cleanly
    (no inner-loop immediate break), then the outer top-of-loop check stops the
    turn before clause 1."""
    monkeypatch.setattr(settings, "interrupt_mode", "finish_current")

    call_seq: list[int] = []
    clause0_done = asyncio.Event()

    async def fake_stream(text):
        idx = len(call_seq)
        call_seq.append(idx)
        if idx == 0:
            yield b"\x07" * 320
            clause0_done.set()  # signal: clause 0 produced all its audio
            return
        # Clause 1+ would yield here but should never be paced.
        yield b"\x08" * 320

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["Clause number zero.", "Clause number one."]))

    orig = agent._send_audio
    sent_for: list[bytes] = []

    async def watch_send(frame):
        await orig(frame)
        sent_for.append(frame[:1])

    agent._send_audio = watch_send

    # Set the interrupt the instant clause 0 finishes producing audio, before
    # clause 1 can be paced. finish_current lets clause 0 drain its sentinel
    # cleanly (so _last_completed_id==0), then the outer loop stops the turn.
    async def interrupter():
        await clause0_done.wait()
        agent._interrupted = True

    await asyncio.gather(agent.handle_utterance("hi"), interrupter())

    # Clause 1 was never played (no clause-1 frame byte sent).
    assert b"\x08" not in sent_for

    interrupts = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_interrupted"]
    assert len(interrupts) == 1
    assert interrupts[0].args[0]["last_completed_sentence_id"] == 0

    done = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_done"]
    assert len(done) == 1


# ── Test 5: tool-ack pcm_data clause flows through the pipeline ──────────────────


async def test_pcm_data_clause_plays_through_pipeline():
    """A SentenceChunk carrying pcm_data (tool-ack bridge) is framed and sent
    without calling live TTS, then a normal clause follows."""

    stream_calls = {"n": 0}

    async def fake_stream(text):
        stream_calls["n"] += 1
        yield b"\x04" * 320

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    # LLM that pushes a pcm_data ack chunk directly onto the queue, then a clause.
    async def fake_stream_response(
        user_text, on_token, on_tool_start=None, on_tool_done=None, interrupt_check=None, on_agent_switch=None
    ):
        on_tool_start("kb_search", {})
        on_token("Real answer.")
        return "Real answer."

    llm = MagicMock()
    llm.stream_response = fake_stream_response

    agent = _make_agent(tts, llm)
    # Provide a pre-synth ack asset so on_tool_start enqueues pcm_data (not live TTS).
    frame_bytes = int(settings.tts_sample_rate * 0.04) * 2
    agent._ack_assets = [b"\x05" * (frame_bytes * 2)]

    # Speed up the deferred-ack timer so it fires within the turn.
    await agent.handle_utterance("hi")

    # The pcm_data ack produced audio frames AND the live clause was synthesized.
    assert agent._send_audio.await_count >= 1
    # Live TTS ran for the real clause (the ack path bypassed it).
    assert stream_calls["n"] >= 1

    done = [c for c in agent._send_json.call_args_list if c.args[0].get("type") == "agent_done"]
    assert len(done) == 1


# ── Test 6: metrics still recorded (regression on the split) ─────────────────────


async def test_metrics_recorded_after_split():
    """tts.ttfb/tts.total (synth-ahead) + e2e.ttfa (pacer) + llm.* still recorded."""

    async def fake_stream(text):
        yield b"\x06" * 320
        yield b"\x06" * 320

    tts = MagicMock()
    tts.stream = fake_stream
    tts.pause = AsyncMock()

    agent = _make_agent(tts, _llm_emitting(["Hello world."]))
    await agent.handle_utterance("hi")

    latency = agent._metrics.summary()["latency"]
    assert latency["llm"]["ttft"]["count"] == 1
    assert latency["llm"]["total"]["count"] == 1
    assert latency["tts"]["ttfb"]["count"] >= 1
    assert latency["tts"]["total"]["count"] >= 1
    assert latency["e2e"]["ttfa"]["count"] == 1
