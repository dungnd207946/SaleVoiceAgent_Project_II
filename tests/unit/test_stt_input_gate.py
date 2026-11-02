import struct
from types import SimpleNamespace

from noble_agent.voice.stt_input_gate import SttInputGate

FRAME = 640


def _f(amp: int) -> bytes:
    return struct.pack(f"<{FRAME // 2}h", *([amp] * (FRAME // 2)))


def test_off_mode_passes_everything():
    g = SttInputGate(mode="off", preroll_chunks=3)
    assert g.gate(_f(0)) == [_f(0)]
    assert g.gate(_f(1000)) == [_f(1000)]


def test_rms_mode_withholds_then_flushes_preroll_on_rising_edge():
    g = SttInputGate(mode="rms", preroll_chunks=2, min_rms=160, required_consecutive=3)
    loud = _f(1000)
    out1 = g.gate(loud)  # frame 1 — not confirmed, withheld
    out2 = g.gate(loud)  # frame 2 — not confirmed, withheld
    assert out1 == [] and out2 == []
    out3 = g.gate(loud)  # frame 3 — rising edge: flush 2 preroll + current
    assert out3 == [loud, loud, loud]
    out4 = g.gate(loud)  # already active — passthrough
    assert out4 == [loud]


def test_preroll_respects_maxlen():
    g = SttInputGate(mode="rms", preroll_chunks=1, min_rms=160, required_consecutive=3)
    loud = _f(1000)
    g.gate(loud)  # withheld (deque holds last 1)
    g.gate(loud)  # withheld (deque still holds only last 1)
    out = g.gate(loud)  # rising edge → only 1 preroll + current
    assert out == [loud, loud]


def test_vad_mode_gates_on_is_speech_with_hangover():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=2)
    data = _f(1000)
    assert g.gate(data) == []  # vad not active yet
    g.feed_vad(True)
    assert g.gate(data) == [data]  # active
    g.feed_vad(False)  # hangover 2 → still active
    assert g.gate(data) == [data]
    g.feed_vad(False)  # hangover 1
    g.feed_vad(False)  # hangover 0 → inactive
    assert g.gate(data) == []


def test_keepalive_emits_silence_while_pending():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=1920)
    data = _f(1000)
    g.feed_vad(True)
    assert g.gate(data) == [data]  # active → utterance pending
    g.feed_vad(False)
    assert g.gate(data) == []  # gate closed → withheld
    assert g.keepalive(FRAME) == b"\x00" * FRAME


def test_keepalive_none_when_not_pending():
    g = SttInputGate(mode="vad", keepalive_max_bytes=1920)
    assert g.keepalive(FRAME) is None


def test_keepalive_stops_after_notify_final():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=1920)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)  # pending
    g.notify_final()
    assert g.keepalive(FRAME) is None


def test_keepalive_respects_cap():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=FRAME)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)  # pending, keepalive counter reset to 0
    assert g.keepalive(FRAME) == b"\x00" * FRAME  # 0 < FRAME → emit (now == FRAME)
    assert g.keepalive(FRAME) is None  # FRAME >= FRAME → stop


def test_keepalive_disabled_when_max_zero():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=0)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)
    assert g.keepalive(FRAME) is None


def test_from_settings_maps_mode_and_hangover():
    s = SimpleNamespace(
        stt_input_gate_mode="vad",
        audio_gate_preroll_chunks=4,
        audio_gate_min_rms=160.0,
        audio_gate_required_consecutive=3,
        audio_gate_barge_in_rms=2400.0,
        stt_vad_gate_hangover_ms=300,
        vad_chunk_ms=32,
        stt_gate_keepalive_max_sec=2.0,
        stt_sample_rate=16000,
    )
    g = SttInputGate.from_settings(s)
    assert g.mode == "vad"
    assert g._preroll.maxlen == 4
    assert g._vad_hangover_chunks == 10  # ceil(300/32)
    assert g.keepalive_max_bytes == 64000  # int(2.0 * 16000 * 2)


def test_keepalive_off_mode_never_emits():
    g = SttInputGate(mode="off", keepalive_max_bytes=1920)
    g.gate(_f(1000))  # off mode is always "active" but must not arm keepalive
    assert g.keepalive(FRAME) is None
