"""Billing metering trên đường telephony (PSTN/AudioSocket) — fix round 1.

`TelephonySession` KHÔNG kế thừa `BaseSession` (độc lập, xem
telephony/session.py) nên phải đo riêng, không tự động ăn theo Task 7. Test ở
đây dùng cùng cách dựng "bare session" như `test_telephony_addressee.py`
(`TelephonySession.__new__` + set thủ công các attribute mà method động tới)
để tránh phải chạy `run()`/AudioSocket/ARI thật.

Phạm vi cố ý hẹp: `_handle_audio` (VAD + STT) đo được trực tiếp, không cần I/O
thật. `_cleanup` thì mock 2 lời gọi I/O thật duy nhất nó đụng
(`billing.sink.flush`) để chạy được method thật mà không cần Postgres — phần
còn lại của `_cleanup` (persist customer, summary, memory snapshot) bị bỏ qua
bằng `caller_number=""`,
đúng nhánh có sẵn trong code, không phải giả lập.

KHÔNG có test cho speaker-verify: telephony không có `SpeakerTracker`/
`_spv_embed` — xem class docstring `TelephonySession` (subset của BaseSession,
"không speaker gates").
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

from noble_agent.billing.meter import UsageMeter
from noble_agent.telephony.session import VAD_CHUNK_BYTES, TelephonySession
from noble_agent.voice.addressee_gate import EpisodeTracker
from noble_agent.voice.vad import VADState


def _bare_tel_session() -> TelephonySession:
    """Same construction pattern as test_telephony_addressee._bare_tel_session,
    extended with the attributes `_handle_audio` and `_cleanup` touch."""
    s = TelephonySession.__new__(TelephonySession)
    s.call_id = "call-1"
    s.session_id = "tel-call-1"
    s.caller_number = ""
    s.agent = AsyncMock()
    s.agent.interrupt = MagicMock()
    s.vad = MagicMock()
    s.vad.process_chunk = MagicMock(return_value={"is_speech": False, "state": VADState.IDLE})
    s.stt = None
    s.metrics = MagicMock()
    s._vad_buf = b""
    s._audio_ring = bytearray()
    s._agent_task = None
    s._stt_audio_start = 0.0
    s._stt_stream_open = 0.0
    s._addr_gate_enabled = False
    s._addr_episode_verdict = None
    s._addr_paused = False
    s._addr_episode_active = False
    s._addr_deadline_handle = None
    s._addr_episode_gen = 0
    s._addr_tracker = EpisodeTracker(min_speech_ms=400, chunk_ms=32)
    s._last_user_text = ""
    s._bg_tasks = set()
    s._keepalive_task = None
    s._running = True
    s._start_time = time.monotonic()
    s.billing = None
    return s


class TestTelephonyHandleAudioBilling:
    async def test_vad_and_stt_metered_at_16khz(self) -> None:
        """`_handle_audio` receives data already resampled 8k→16k (done by the
        caller, `_audio_loop`) — audio_sec must divide by stt_sample_rate
        (16000), not the raw 8kHz Asterisk rate."""
        s = _bare_tel_session()
        s.billing = UsageMeter(session_id=s.session_id, channel="voice")
        s.stt = AsyncMock()
        data = b"\x00\x01" * (VAD_CHUNK_BYTES // 2)  # exactly one VAD chunk, 16-bit PCM
        assert len(data) == VAD_CHUNK_BYTES

        await s._handle_audio(data)

        _seq, rows = s.billing.drain()
        by_component = {r.component: r for r in rows}
        vad = by_component["vad"]
        stt = by_component["stt"]
        assert round(vad.audio_sec, 3) == 0.032  # settings.vad_chunk_ms / 1000
        # VAD không đếm chunk: units=0 — cơ sở tính tiền là audio_sec.
        assert vad.units == 0
        assert round(stt.audio_sec, 3) == round(len(data) / (16000 * 2), 3)
        s.stt.send.assert_awaited_once_with(data)

    async def test_billing_off_is_noop(self) -> None:
        """`self.billing is None` (flag off, the default) must not raise and
        must not fabricate any usage."""
        s = _bare_tel_session()
        s.billing = None
        s.stt = AsyncMock()
        data = b"\x00\x01" * (VAD_CHUNK_BYTES // 2)

        await s._handle_audio(data)  # must not raise

        s.stt.send.assert_awaited_once_with(data)


class TestTelephonyOnFinalBilling:
    async def test_on_final_meters_transcript_chars(self) -> None:
        """(stt, conversation).text_units = ký tự transcript final — như
        BaseSession, đo ở đầu `_on_final` trước mọi gate."""
        s = _bare_tel_session()
        s.billing = UsageMeter(session_id=s.session_id, channel="voice")
        s._addr_gate_enabled = False
        s._trigger_agent = AsyncMock()

        await s._on_final("alo em nghe đây")

        _seq, rows = s.billing.drain()
        stt = {(r.component, r.purpose): r for r in rows}[("stt", "conversation")]
        assert stt.text_units == len("alo em nghe đây")


class TestTelephonyCleanupBilling:
    async def test_cleanup_adds_call_row_and_flushes_then_pops(self) -> None:
        s = _bare_tel_session()
        s.billing = UsageMeter(session_id=s.session_id, channel="voice")
        s.billing.add_audio("vad", audio_sec=1.0, wall_ms=1.0, units=10)  # usage accrued mid-call
        s._start_time = time.monotonic() - 5.0  # ~5s call

        with (
            patch("noble_agent.billing.sink.flush", new=AsyncMock(return_value=True)) as mock_flush,
            patch("noble_agent.billing.context.pop_session_meter") as mock_pop,
            patch("noble_agent.billing.sink.forget_session") as mock_forget,
        ):
            await s._cleanup()

        mock_flush.assert_awaited_once()
        (flushed_meter,), _kwargs = mock_flush.call_args
        assert flushed_meter is s.billing
        mock_pop.assert_called_once_with(s.session_id)
        mock_forget.assert_called_once_with(s.session_id)

        # The "call" row was appended (audio_sec ~= 5s) before flush ran —
        # since flush is mocked, drain() still shows it as pending.
        _seq, rows = s.billing.drain()
        call_rows = [r for r in rows if r.component == "call"]
        assert len(call_rows) == 1
        assert call_rows[0].turn_idx is None
        assert call_rows[0].purpose == "session"
        assert call_rows[0].audio_sec > 4.5

    async def test_cleanup_meters_stt_stream_open_time_and_open_count(self) -> None:
        """Thời gian stream STT mở + số lần mở đi trên dòng RIÊNG
        `(stt, purpose='stream')`, session-scoped (turn_idx NULL) — Portal được
        mời tính tiền theo wall_ms khi hợp đồng STT thu theo thời gian kết nối.
        Để hai cột đó bằng 0 vĩnh viễn là biến mọi dòng hoá đơn theo hướng dẫn
        đó thành 0."""
        s = _bare_tel_session()
        s.billing = UsageMeter(session_id=s.session_id, channel="voice")
        s.stt = AsyncMock()
        s._stt_stream_open = time.monotonic() - 3.0  # stream mở 3s

        with (
            patch("noble_agent.billing.sink.flush", new=AsyncMock(return_value=True)),
            patch("noble_agent.billing.context.pop_session_meter"),
            patch("noble_agent.billing.sink.forget_session"),
        ):
            await s._cleanup()

        _seq, rows = s.billing.drain()
        stt = {(r.component, r.purpose): r for r in rows}[("stt", "stream")]
        assert stt.wall_ms >= 3000.0
        assert stt.units == 1
        assert stt.turn_idx is None
        assert stt.audio_sec == 0.0

    async def test_cleanup_billing_off_is_noop(self) -> None:
        s = _bare_tel_session()
        s.billing = None

        await s._cleanup()  # must not raise with billing disabled
