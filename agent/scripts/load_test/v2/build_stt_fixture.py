"""Build the STT load fixture: a real Vietnamese ack utterance resampled 24k→16k
with 1.5 s trailing silence appended (so sherpa's endpoint rule emits a `final`).

Run once; commits `fixture_16k.pcm`. Needs numpy + scipy (dev-only, not needed by
the load client at runtime).

    python scripts/load_test/v2/build_stt_fixture.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "assets/voice/acks/01_em_can_kiem_tra_thong_tin_trong_he_thong_quy_khach.pcm"
DST = Path(__file__).resolve().parent / "fixture_16k.pcm"
TRAILING_SILENCE_S = 3.0  # > sherpa rule1 (2.4s) so is_endpoint fires reliably on blasted audio


def main() -> None:
    raw = np.frombuffer(SRC.read_bytes(), dtype="<i2")  # 24 kHz int16 mono
    y = resample_poly(raw.astype(np.float32), 2, 3)  # 24k → 16k
    y = np.clip(y, -32768, 32767).astype("<i2")
    sil = np.zeros(int(16000 * TRAILING_SILENCE_S), dtype="<i2")
    out = np.concatenate([y, sil])
    DST.write_bytes(out.tobytes())
    print(f"wrote {DST}  @16k dur={len(out) / 16000:.2f}s  bytes={DST.stat().st_size}")


if __name__ == "__main__":
    main()
