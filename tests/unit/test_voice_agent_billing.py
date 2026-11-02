"""Billing metering wiring in `VoiceAgent` (TTS) — fix round 2, Task 7.

Companion to `test_base_session_billing.py` (VAD/STT/speaker_verify/call) and
`test_telephony_billing.py` (telephony's independent path). Together these
close the gap the round-2 review found: the originally-scoped surface
(`base_session.py` + `voice_agent.py`, covering two of the three voice
transports) had no executable test driving a real `UsageMeter` through the
real code, while telephony — the round-1 scope expansion — already had one.

Harness mirrors `test_voice_metrics.py` exactly (same fake TTS/LLM shape,
same `VoiceAgent.__new__` construction) so this exercises the real
`handle_utterance` → `_synth_ahead` clause-synth loop, not a re-implementation
of its arithmetic. `on_token("Hello world.")` is chosen deliberately: at
13 chars it clears `settings.min_sentence_length` (10) and ends in a hard
sentence boundary, so `SentenceBuffer` emits exactly one `SentenceChunk` with
`text == "Hello world."` verbatim (no stripping/splitting) — confirmed by the
same assumption `test_voice_agent_pause.py::test_accumulates_across_clauses_in_pacer_order`
already relies on for its own assertions.

Fix round 2 also found (not just a test gap): `_synth_ahead` reads
`self._billing` unconditionally. Every pre-existing test in this codebase
that constructs `VoiceAgent` via `__new__` and drives a real
`handle_utterance` call did NOT set `_billing` (it didn't exist before this
feature) — so the moment a clause actually synthesized at least one frame,
`_synth_ahead` raised `AttributeError` *after* queuing frames but *before*
putting the clause-complete sentinel, hanging `_pacer` forever waiting for a
sentinel that would never arrive. This wasn't a slow test — it was an
infinite hang, caught only because `pytest` interrupted it as a slow build
artifact of a run that timed out at 120s while it was being explored. Fixed
by adding `agent._billing = None` to the five affected pre-existing test
files' bare-construction helpers (`test_voice_metrics.py`,
`test_voice_agent_pause.py`, `test_tool_ack.py`,
`test_voice_media_forwarding.py`, `test_voice_tts_pipeline.py`) — matching
the codebase's own established convention of explicitly setting `_metrics`
(not getattr-guarded) rather than adding an inconsistent getattr guard only
for billing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from noble_agent.billing.meter import UsageMeter
from noble_agent.config import settings as real_settings
from noble_agent.metrics import MetricsCollector
from noble_agent.voice.voice_agent import VoiceAgent


def _agent_with_meter(meter, *, num_frames: int, frame_bytes: bytes, sentence: str) -> VoiceAgent:
    async def fake_tts_stream(text):
        for _ in range(num_frames):
            yield frame_bytes

    mock_tts = MagicMock()
    mock_tts.stream = fake_tts_stream

    async def fake_stream_response(
        user_text,
        on_token,
        on_tool_start=None,
        on_tool_done=None,
        interrupt_check=None,
        on_agent_switch=None,
    ):
        on_token(sentence)
        return sentence

    mock_llm = MagicMock()
    mock_llm.stream_response = fake_stream_response

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._llm = mock_llm
    agent._tts = mock_tts
    agent._interrupted = False
    agent._metrics = MetricsCollector()
    agent._billing = meter
    return agent


class TestVoiceAgentTTSBilling:
    async def test_handle_utterance_meters_tts_audio_sec_and_char_units(self) -> None:
        meter = UsageMeter(session_id="sid-va-billing-1", channel="voice")
        frame = b"\x00" * 320
        num_frames = 3
        sentence = "Hello world."  # 13 chars, clears min_sentence_length=10, hard boundary

        agent = _agent_with_meter(meter, num_frames=num_frames, frame_bytes=frame, sentence=sentence)
        await agent.handle_utterance("test input")

        _seq, rows = meter.drain()
        tts_rows = [r for r in rows if r.component == "tts"]
        assert len(tts_rows) == 1
        expected_audio_sec = (len(frame) * num_frames) / (real_settings.tts_sample_rate * 2)
        assert round(tts_rows[0].audio_sec, 4) == round(expected_audio_sec, 4)
        # units = số clause synth; ký tự (cơ sở tính tiền ElevenLabs) đi text_units
        assert tts_rows[0].units == 1
        assert tts_rows[0].text_units == len(sentence)

    async def test_billing_off_is_noop_and_does_not_hang(self) -> None:
        """`agent._billing = None` (the default) must let handle_utterance run
        to completion — this is the exact scenario that hung indefinitely
        before the fix round 2 correction (see module docstring)."""
        frame = b"\x00" * 320
        agent = _agent_with_meter(None, num_frames=2, frame_bytes=frame, sentence="Hi there.")
        await agent.handle_utterance("test input")  # must not raise or hang
        assert agent._metrics.summary()["latency"]["tts"]["total"]["count"] == 1
