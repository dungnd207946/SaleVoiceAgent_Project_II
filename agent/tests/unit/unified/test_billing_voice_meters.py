"""Quy tắc đo thời lượng — cái nào vào hoá đơn, cái nào chỉ là giá vốn."""

from noble_agent.billing.meter import UsageMeter


def _rows(m: UsageMeter) -> dict[str, object]:
    _seq, rows = m.drain()
    return {r.component: r for r in rows}


def test_vad_counts_audio_seconds_and_cpu_separately():
    m = UsageMeter(session_id="s1", channel="voice")
    for _ in range(10):  # 10 chunk × 32 ms
        m.add_audio("vad", audio_sec=0.032, wall_ms=0.4, units=1)
    vad = _rows(m)["vad"]
    assert round(vad.audio_sec, 3) == 0.32
    assert round(vad.wall_ms, 1) == 4.0
    assert vad.units == 10


def test_stt_bills_real_audio_not_synthetic_silence():
    """Im lặng do agent tự bơm vào STT (keepalive) vẫn nằm trong hoá đơn nhà
    cung cấp, nhưng khách KHÔNG nói nó — nên nó thuộc wall_ms (giá vốn), không
    thuộc audio_sec (hoá đơn)."""
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("stt", audio_sec=4.2, wall_ms=12400.0)  # 4,2 s khách nói / 12,4 s stream mở
    stt = _rows(m)["stt"]
    assert stt.audio_sec == 4.2
    assert stt.wall_ms == 12400.0


def test_tts_counts_both_audio_seconds_and_characters():
    """ElevenLabs tính theo ký tự, VieNeu theo giây — ghi cả hai để Portal
    chọn theo hợp đồng của từng backend."""
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("tts", audio_sec=6.1, wall_ms=820.0, units=138)
    tts = _rows(m)["tts"]
    assert tts.audio_sec == 6.1
    assert tts.units == 138


def test_speaker_verify_counts_embeddings():
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("speaker_verify", audio_sec=1.5, wall_ms=95.0, units=1)
    sv = _rows(m)["speaker_verify"]
    assert sv.units == 1


def test_call_row_is_session_scoped():
    m = UsageMeter(session_id="s1", channel="voice")
    m.turn_idx = 7
    m.add_audio("call", purpose="session", audio_sec=38.6, units=1)
    call = _rows(m)["call"]
    assert call.turn_idx is None
    assert call.purpose == "session"
    assert call.audio_sec == 38.6
