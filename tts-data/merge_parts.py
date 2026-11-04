#!/usr/bin/env python3
"""Ghép parts/*.jsonl thành texts.jsonl: bỏ câu trùng, xáo trộn, đánh lại id dt_00001...

Xáo trộn (seed cố định) để nếu sinh audio bị ngắt giữa chừng (hết quota), phần đã có vẫn
trải đều mọi category. Chạy lại cho kết quả y hệt nếu parts/ không đổi.

    python3 merge_parts.py            # → texts.jsonl (xáo lại toàn bộ, id mới)
    python3 merge_parts.py --append   # giữ id cũ (đã có audio), nối câu mới vào cuối
"""

from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent


def key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFC", text).lower()).strip()


def main() -> None:
    if "--append" in sys.argv:
        append()
        return
    rows, seen, dup = [], set(), 0
    for part in sorted((HERE / "parts").glob("*.jsonl")):
        for line in part.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            k = key(r["text"])
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            rows.append(r)
    random.Random(2026).shuffle(rows)
    with open(HERE / "texts.jsonl", "w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            out = {"id": f"dt_{i:05d}", "text": unicodedata.normalize("NFC", r["text"].strip()),
                   "raw_text": r.get("raw_text", ""), "category": r["category"]}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"texts.jsonl: {len(rows)} câu (bỏ {dup} câu trùng giữa các phần)")


def append() -> None:
    """Giữ nguyên texts.jsonl (id đã có audio), chỉ nối câu mới từ parts/ vào cuối."""
    path = HERE / "texts.jsonl"
    old = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = {key(r["text"]) for r in old}
    new = []
    for part in sorted((HERE / "parts").glob("*.jsonl")):
        for line in part.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if key(r["text"]) not in seen:
                    seen.add(key(r["text"]))
                    new.append(r)
    random.Random(2026).shuffle(new)
    with open(path, "a", encoding="utf-8") as f:
        for i, r in enumerate(new, len(old) + 1):
            out = {"id": f"dt_{i:05d}", "text": unicodedata.normalize("NFC", r["text"].strip()),
                   "raw_text": r.get("raw_text", ""), "category": r["category"]}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"texts.jsonl: {len(old)} câu cũ + {len(new)} câu mới")


if __name__ == "__main__":
    main()
