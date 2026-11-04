import math


def test_embed_window_bytes():
    # window seconds → bytes (int16 @ 16kHz). 3.0s → 96000 bytes.
    sample_rate = 16000
    window_sec = 3.0
    assert int(window_sec * sample_rate) * 2 == 96000


def test_hangover_chunk_math():
    assert math.ceil(300 / 32) == 10
