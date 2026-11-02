"""Kiểm chứng: TTS có đọc đúng số tiền và mã đơn không? Sinh N lần, phiên âm từng lần."""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import api_key  # noqa: E402
from bench_rest import elevenlabs_request, soniox_request  # noqa: E402
from score_stt import norm, transcribe, upload  # noqa: E402

TEXT = (
    "Đơn hàng NBX-4728 của mình sẽ giao vào ngày 21 tháng 8, phí thu hộ là "
    "1.250.000 đồng. Nếu cần hỗ trợ thêm mình gọi 1900 6885 nhé."
)
# Các chuỗi số phải xuất hiện đúng trong bản phiên âm
EXPECT = {"mã đơn": "4728", "tiền": "250", "hotline": "6885", "ngày": "21"}

TARGETS = [
    (
        "el-flash-v2_5",
        elevenlabs_request,
        {
            "model": "eleven_flash_v2_5",
            "voice": "iSFxP4Z6YNcx9OXl62Ic",
            "language_code": "vi",
            "stability": 1.0,
            "similarity_boost": 0.75,
            "speed": 1.13,
        },
    ),
    (
        "soniox-v2-sp1.15-rs",
        soniox_request,
        {"model": "tts-rt-v2", "voice": "Nina", "speed": 1.15, "reduce_silence": True},
    ),
]

N = int(os.environ.get("N", "5"))
out_dir = Path(__file__).parent / "out" / "verify"
out_dir.mkdir(parents=True, exist_ok=True)
report = []

for name, fn, cfg in TARGETS:
    key = api_key("elevenlabs" if name.startswith("el-") else "soniox")
    for i in range(N):
        audio, _ = fn(cfg, TEXT, key)
        p = out_dir / f"{name}_{i}.mp3"
        p.write_bytes(audio)
        hyp = norm(transcribe(upload(p)))
        digits = re.sub(r"[^\d ]", " ", hyp)
        miss = [k for k, v in EXPECT.items() if v not in hyp.replace(" ", "") and v not in digits.replace(" ", "")]
        report.append({"target": name, "run": i, "hyp": hyp, "missing": miss})
        flag = "OK  " if not miss else "SAI "
        print(f"{flag}{name:22s} #{i}  thiếu/sai: {miss or '-'}", flush=True)
        print(f"     số đọc được: {' '.join(digits.split())}", flush=True)

(Path(__file__).parent / "results_verify_digits.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
bad = {}
for r in report:
    if r["missing"]:
        bad[r["target"]] = bad.get(r["target"], 0) + 1
print("\n=== tổng hợp ===")
for name, _, _ in TARGETS:
    print(f"{name:22s} {bad.get(name, 0)}/{N} lần đọc sai")
