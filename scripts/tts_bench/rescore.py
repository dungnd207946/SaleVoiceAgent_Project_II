"""Tính lại CER sau khi loại chênh lệch chữ-số vs chữ-viết.

Vấn đề: STT xuất "3 000" cho "ba nghìn", nên CER thô đo lỗi biểu diễn số của
STT chứ không đo lỗi TTS -- mọi cấu hình cùng ra một con số. Ở đây tách hai phép đo:

  cer_words  -- bỏ toàn bộ chữ số và từ chỉ số ở CẢ HAI phía, đo phát âm từ thường.
  case alnum -- văn bản gốc vốn đã viết bằng chữ số, nên CER thô ở đó đo đúng
                độ chính xác đọc số và được giữ nguyên.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from score_stt import edit_distance

NUM_WORDS = {
    "không",
    "một",
    "hai",
    "ba",
    "bốn",
    "năm",
    "sáu",
    "bảy",
    "tám",
    "chín",
    "mười",
    "mươi",
    "trăm",
    "nghìn",
    "ngàn",
    "triệu",
    "tỉ",
    "tỷ",
    "lăm",
    "linh",
}


def strip_numbers(text: str) -> str:
    toks = [t for t in text.split() if not re.fullmatch(r"\d+", t) and t not in NUM_WORDS]
    return " ".join(toks)


base = Path(__file__).parent
rows = [r for r in json.loads((base / "results_stt.json").read_text()) if not r.get("error")]

out = []
for r in rows:
    ref_w, hyp_w = strip_numbers(r["ref"]), strip_numbers(r["hyp"])
    cer_w = edit_distance(ref_w, hyp_w) / max(len(ref_w), 1) * 100
    wer_w = edit_distance(ref_w.split(), hyp_w.split()) / max(len(ref_w.split()), 1) * 100
    out.append({**r, "cer_words_pct": round(cer_w, 2), "wer_words_pct": round(wer_w, 2)})

(base / "results_stt_rescored.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

cases = ["greet", "alnum", "mixed", "long", "emo_happy", "emo_sorry", "emo_laugh"]
cfgs = sorted({r["config"] for r in out})
m = {(r["config"], r["case"]): r for r in out}

print("CER sau khi loại chênh lệch chữ-số (đo phát âm từ thường, % — càng thấp càng tốt)")
print(f"{'config':28s}" + "".join(f"{c[:9]:>11s}" for c in cases))
print("-" * (28 + 11 * len(cases)))
for c in cfgs:
    line = f"{c:28s}"
    for cs in cases:
        r = m.get((c, cs))
        line += f"{r['cer_words_pct']:11.2f}" if r else f"{'-':>11s}"
    print(line)

print("\nCase alnum — CER thô (văn bản gốc dùng chữ số, nên đây là độ chính xác đọc số):")
for c in cfgs:
    r = m.get((c, "alnum"))
    if r:
        print(f"  {c:28s} {r['cer_pct']:6.2f}%")
