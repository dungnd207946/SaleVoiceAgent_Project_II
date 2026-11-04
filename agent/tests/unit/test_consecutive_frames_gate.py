import struct

from noble_agent.voice.audio_guard import ConsecutiveFramesGate

FRAME = 640  # 20ms @ 16kHz int16


def _frame(amp: int) -> bytes:
    return struct.pack(f"<{FRAME // 2}h", *([amp] * (FRAME // 2)))


def test_requires_n_consecutive_loud_frames():
    gate = ConsecutiveFramesGate(min_rms=160, required_consecutive=3)
    loud = _frame(1000)
    assert gate.feed(loud) is False  # 1
    assert gate.feed(loud) is False  # 2
    assert gate.feed(loud) is True  # 3 → confirmed
    assert gate.confirmed is True


def test_silence_resets_immediately():
    gate = ConsecutiveFramesGate(min_rms=160, required_consecutive=3)
    loud = _frame(1000)
    for _ in range(3):
        gate.feed(loud)
    assert gate.confirmed is True
    gate.feed(_frame(0))  # one silent frame
    assert gate.confirmed is False
