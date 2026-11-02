"""Billing metering wiring in `BaseSession` (WebRTC + LiveKit path) — fix
round 2, Task 7.

Round 1 added an executable test for telephony's independent wiring
(`test_telephony_billing.py`) but left `base_session.py`/`voice_agent.py` —
the originally-scoped surface, covering two of the three voice transports —
without any test driving a real `UsageMeter` through the real code. This
file closes that gap for `BaseSession`; `test_voice_agent_billing.py` closes
it for `VoiceAgent`.

Reuses `_patched_collaborators` from `test_base_session.py` (same file that
constructs `BaseSession` via its real `__init__` across ~90 other tests) so
these tests exercise the exact same construction path, not a bespoke one.

Global-state hygiene: `_patched_collaborators` now pins
`billing_metering_enabled = False` by default (added in this round — it was
previously unset, and a bare `MagicMock` attribute is truthy, meaning every
one of the ~90 unrelated tests in `test_base_session.py` was silently
registering a real `UsageMeter` into the process-global
`billing.context._sessions` registry with no cleanup). Tests here that need
billing on set it explicitly and pop their own session id afterward; the
autouse fixture below is a safety net in case a test fails before its own
cleanup runs.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_base_session import _FakeAudioOutput, _patched_collaborators


@pytest.fixture(autouse=True)
def _cleanup_billing_sessions():
    from noble_agent.billing import context as billing_ctx

    yield
    for sid in [k for k in billing_ctx._sessions if k.startswith("sid-billing-")]:
        billing_ctx.pop_session_meter(sid)


class TestProcessAudioFrameBilling:
    async def test_vad_and_stt_metered_when_gate_open(self) -> None:
        """Gate mode 'off' (default): the whole frame passes straight through
        as one real STT chunk; VAD chunks it into fixed vad_chunk_ms pieces."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            from noble_agent.server.base_session import VAD_CHUNK_BYTES, BaseSession

            s = BaseSession("sid-billing-vad-stt-1")
            s.stt = AsyncMock()
            data = b"\x00\x01" * VAD_CHUNK_BYTES  # exactly 2 VAD chunks, gate-open passthrough

            await s.process_audio_frame(data)

            _seq, rows = s.billing.drain()
            by_component = {r.component: r for r in rows}
            vad = by_component["vad"]
            stt = by_component["stt"]
            # VAD không đếm chunk: units=0 — số chunk 32ms không quy ra đơn giá
            # nào; cơ sở tính tiền của VAD là audio_sec (giây audio đã quét).
            assert vad.units == 0
            assert round(vad.audio_sec, 4) == round(2 * cols["settings"].vad_chunk_ms / 1000.0, 4)
            assert round(stt.audio_sec, 4) == round(len(data) / (cols["settings"].stt_sample_rate * 2), 4)

    async def test_stt_excludes_synthetic_silence_when_gate_closed(self) -> None:
        """The rule this whole feature exists to enforce: when the input gate
        is closed, the agent still feeds STT synthetic keepalive silence (so
        the recognizer's endpoint timing stays correct) — but that silence
        must NOT enter audio_sec, because the customer didn't speak it.
        VAD still fires (it runs regardless of the gate)."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            cols["settings"].stt_input_gate_mode = "rms"
            from noble_agent.server.base_session import VAD_CHUNK_BYTES, BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-billing-stt-silence-1")
            s.stt = AsyncMock()
            gate_stub = MagicMock(spec=SttInputGate)
            gate_stub.mode = "rms"
            gate_stub.gate.return_value = []  # gate closed — no real audio forwarded
            silence = b"\x00" * 320
            gate_stub.keepalive.return_value = silence  # synthetic silence still reaches STT
            s._input_gate = gate_stub

            await s.process_audio_frame(b"\x00" * VAD_CHUNK_BYTES)

            # STT DID receive audio (the synthetic silence, proving this isn't
            # passing merely because STT was never called)...
            s.stt.send.assert_awaited_once_with(silence)
            # ...but the meter must show no "stt" row at all — not even a
            # zero-valued one, since add_audio("stt", ...) must never be
            # called on this branch.
            _seq, rows = s.billing.drain()
            by_component = {r.component: r for r in rows}
            assert "vad" in by_component  # sanity: the meter is alive and VAD still fired
            assert "stt" not in by_component


class TestSpvEmbedBilling:
    async def test_meters_units_and_audio_sec_from_segment_length(self) -> None:
        """`_spv_embed` bills the span it is HANDED (the tracker owns the buffer
        now), so the metered audio_sec can never drift from what was embedded."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            cols["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-billing-sv-1")
            span = b"\x11\x22" * 400  # 800 bytes

            fake_emb = MagicMock()
            fake_emb.embed = MagicMock(return_value=MagicMock())
            with patch("noble_agent.server.base_session.SpeakerEmbedder") as MockEmbedder:
                MockEmbedder.get_instance.return_value = fake_emb
                await s._spv_embed(span)

            _seq, rows = s.billing.drain()
            sv = {r.component: r for r in rows}["speaker_verify"]
            assert sv.units == 1
            assert round(sv.audio_sec, 4) == round(len(span) / (cols["settings"].stt_sample_rate * 2), 4)

    async def test_meters_even_when_embed_fails(self) -> None:
        """Embed raised → still billed: the vendor call was made (cost spent)."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            cols["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-billing-sv-2")
            span = b"\x11\x22" * 400

            fake_emb = MagicMock()
            fake_emb.embed = MagicMock(side_effect=RuntimeError("boom"))
            with patch("noble_agent.server.base_session.SpeakerEmbedder") as MockEmbedder:
                MockEmbedder.get_instance.return_value = fake_emb
                assert await s._spv_embed(span) is None

            _seq, rows = s.billing.drain()
            sv = {r.component: r for r in rows}["speaker_verify"]
            assert sv.units == 1


class TestOnFinalBilling:
    async def test_on_final_meters_transcript_chars_even_when_filtered(self) -> None:
        """`text_units` của (stt, conversation) = KÝ TỰ transcript final — cơ sở
        khớp hoá đơn output-text-token của Soniox. Đo ở ĐẦU `_on_final`, TRƯỚC
        mọi filter (hallucination/echo/speaker): vendor đã transcribe là giá vốn
        đã tiêu, kể cả khi ta vứt final đó đi. Test này ép filter vứt final để
        chứng minh điểm đo nằm trước filter."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            from noble_agent.server.base_session import BaseSession

            s = BaseSession("sid-billing-stt-text-1")
            s._halluc_filter.is_hallucination = MagicMock(return_value=True)  # bail ngay sau điểm đo

            await s._on_final("xin chào bên mình")

            _seq, rows = s.billing.drain()
            stt = {(r.component, r.purpose): r for r in rows}[("stt", "conversation")]
            assert stt.text_units == len("xin chào bên mình")


class TestStopBilling:
    async def test_stop_meters_stt_stream_open_time_and_open_count(self) -> None:
        """Thời gian stream STT mở + số lần mở đi trên dòng RIÊNG
        `(stt, purpose='stream')`, session-scoped (turn_idx NULL) — không được
        trộn vào `(stt, conversation)` (giây khách nói, per-turn), nếu không sẽ
        sinh dòng lai kiểu `turn_idx=1 wall_ms=112748` như đã thấy trên bảng
        thật. Chúng chỉ biết được lúc đóng phiên; để bằng 0 là mọi dòng hoá đơn
        kiểu đó ra 0."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            from noble_agent.server.base_session import BaseSession

            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
                patch("noble_agent.billing.sink.flush", new_callable=AsyncMock, return_value=True),
            ):
                s = BaseSession("sid-billing-stt-wall-1")
                s.stt = AsyncMock()
                s._audio_output = _FakeAudioOutput()
                s._stt_stream_open = time.monotonic() - 3.0  # stream STT mở 3s

                await s.stop()

            _seq, rows = s.billing.drain()
            stt = {(r.component, r.purpose): r for r in rows}[("stt", "stream")]
            assert stt.wall_ms >= 3000.0
            assert stt.units == 1
            assert stt.turn_idx is None
            assert stt.audio_sec == 0.0

    async def test_teardown_summary_call_is_metered_with_purpose_summary(self) -> None:
        """`generate_call_summary` chạy trên đường teardown, nơi KHÔNG ai set
        meter ContextVar (nó chỉ sống trong handle_turn) → `capture.record` return
        sớm và cả tóm tắt cuối cuộc gọi (prompt mang toàn bộ hội thoại) miễn phí.
        `stop()` phải gắn meter quanh pipeline teardown."""
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            from noble_agent.agent.summary import generator as summary_gen
            from noble_agent.billing import capture
            from noble_agent.server.base_session import BaseSession

            async def _fake_summary(*_a, **_kw):
                # Đứng đúng chỗ lời gọi LLM thật trong generate_call_summary.
                capture.record("anthropic", "claude-x", None, purpose="summary")
                return {"summary": "x"}

            with (
                patch(
                    "noble_agent.storage.session_store.load_customer",
                    new_callable=AsyncMock,
                    return_value={"phone": "0900000000"},
                ),
                patch("noble_agent.storage.session_store.save_customer_persistent", new_callable=AsyncMock),
                patch(
                    "noble_agent.storage.session_store.load_history_from_state",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch("noble_agent.storage.pg_data_plane.persist_conversation", new_callable=AsyncMock),
                # Neutralise every fire-and-forget on the teardown path (memory
                # snapshot + session_ended event) without touching their modules.
                patch("noble_agent.storage.persist.fire_and_forget", side_effect=lambda coro: coro.close()),
                patch.object(summary_gen, "generate_call_summary", _fake_summary),
                patch("noble_agent.billing.sink.flush", new_callable=AsyncMock, return_value=True),
            ):
                s = BaseSession("sid-billing-teardown-1")
                s.stt = AsyncMock()
                s._audio_output = _FakeAudioOutput()

                await s.stop()

            _seq, rows = s.billing.drain()
            purposes = {r.purpose for r in rows}
            assert "summary" in purposes, "lời gọi summary lúc đóng phiên phải được đếm"

    async def test_stop_adds_call_row_and_flushes(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].billing_metering_enabled = True
            from noble_agent.server.base_session import BaseSession

            with (
                patch("noble_agent.storage.session_store.load_customer", new_callable=AsyncMock, return_value={}),
                patch("noble_agent.billing.sink.flush", new_callable=AsyncMock, return_value=True) as mock_flush,
            ):
                s = BaseSession("sid-billing-stop-1")
                s.stt = AsyncMock()
                s._audio_output = _FakeAudioOutput()
                s._session_start = time.monotonic() - 5.0  # force a known ~5s session duration
                s.billing.add_audio("vad", audio_sec=1.0, wall_ms=1.0, units=10)  # usage accrued mid-call

                await s.stop()

            mock_flush.assert_awaited_once()
            (flushed_meter,), _kwargs = mock_flush.call_args
            assert flushed_meter is s.billing

            # flush() was mocked, so nothing was actually committed — drain()
            # still shows the "call" row stop() added before calling flush().
            _seq, rows = s.billing.drain()
            call_rows = [r for r in rows if r.component == "call"]
            assert len(call_rows) == 1
            assert call_rows[0].turn_idx is None
            assert call_rows[0].purpose == "session"
            assert call_rows[0].audio_sec > 4.5
