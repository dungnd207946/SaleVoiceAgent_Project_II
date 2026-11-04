#!/usr/bin/env python3
"""Kiểm tra file câu (texts.jsonl) trước khi gọi ElevenLabs.

Mỗi dòng của texts.jsonl là một object JSON:
    {"id": "dt_00001", "text": "...", "raw_text": "...", "category": "tra_gop"}
- text      (bắt buộc) câu ở DẠNG ĐỌC: không chữ số, không ký hiệu, không viết tắt.
- id        (tuỳ chọn) chỉ gồm [A-Za-z0-9_-]; bỏ trống thì gen_audio tự đặt theo hash.
- raw_text  (tuỳ chọn) câu gốc dạng viết (có số, ký hiệu) — để đối chiếu luật chuẩn hoá.
- category  (tuỳ chọn) nhóm tình huống, dùng để thống kê độ phủ.

Lỗi (ERROR) làm script thoát mã 1; cảnh báo (WARN) chỉ in ra để xem lại.

Chạy:
    python3 check_texts.py texts.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

# ~4 từ/giây — đo trên bộ santa (142.629 từ / 10,0 giờ)
WORDS_PER_SEC = 4.0
MIN_WORDS, MAX_WORDS = 3, 70  # 70 từ ≈ 17-18 giây, chừa biên cho giới hạn 20 giây
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DIGIT_RE = re.compile(r"\d")
# Ký hiệu TTS hay đọc sai hoặc làm hỏng metadata.csv (dấu | là dấu ngăn cột)
BAD_SYMBOLS = "|/\\%&@#$+=*<>^~_`{}[]₫"
BAD_SYMBOL_RE = re.compile("[" + re.escape(BAD_SYMBOLS) + "]")
ALLCAPS_RE = re.compile(r"\b[A-ZĐ]{2,}\b")
MIXED_ALNUM_RE = re.compile(r"\b(?=\w*[A-Za-z])(?=\w*\d)\w+\b")
ALLOWED_PUNCT = set(" ,.?!;:-'\"()…")

# ── Luật đọc của TEXT_SPEC mục 3 ─────────────────────────────────────────────
LEXICON_FILE = Path(__file__).resolve().parent / "lexicon_latin.txt"
# Âm tiết tiếng Việt viết không dấu ("anh", "gi", "ga", "bai"): không phải từ Latin.
VN_SYLLABLE_RE = re.compile(
    r"(ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnprstvx])?"
    r"(uye|uya|oai|oay|oeo|uoi|ieu|yeu|uay|uou|ai|ao|au|ay|eo|eu|ia|ie|iu|oa|oe|oi|oo|ua|ue|ui|uo|uy|ye|[aeiouy])"
    r"(ch|ng|nh|[cmnpt])?"
)
TOKEN_STRIP = ".,?!;:()\"'…"
# (regex, thông báo) — dạng đọc lệch với bộ chuẩn hoá (_int_to_vi) hoặc với luật đã chốt
FORBIDDEN = [
    (re.compile(r"\bngàn\b"), "'ngàn' → 'nghìn'"),
    (re.compile(r"\btrăm linh\b"), "'trăm linh' → 'trăm lẻ'"),
    (re.compile(r"\bmươi tư\b"), "'mươi tư' → 'mươi bốn'"),
    (re.compile(r"\bmươi một\b"), "'mươi một' → 'mươi mốt'"),
    (re.compile(r"\bgi ga\b(?! bai\b| héc\b)"), "'gi ga' phải là 'gi ga bai' (hoặc 'gi ga héc')"),
    (re.compile(r"\btê ra\b(?! bai\b)"), "'tê ra' phải là 'tê ra bai'"),
    (re.compile(r"\bét xì\b"), "S luôn đọc 'ét'"),
    (re.compile(r"\bmờ bê\b|\bnờ\b"), "bảng chữ cái 3.4: M = 'em', N = 'en'"),
]
SUSPECT = [
    (re.compile(r"\bmươi năm\b"), "'mươi năm' — nếu là số thì phải 'mươi lăm'"),
    (re.compile(r"\bchấm\b"), "'chấm' — số thập phân đọc 'phẩy'"),
]


def is_allowed_char(ch: str) -> bool:
    if ch in ALLOWED_PUNCT:
        return True
    cat = unicodedata.category(ch)
    return cat.startswith("L") or cat == "Mn"


def norm_key(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w]+", " ", t).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("texts", type=Path)
    ap.add_argument("--show", type=int, default=15, help="Số dòng lỗi/cảnh báo in ra mỗi loại")
    ap.add_argument("--lexicon", type=Path, default=LEXICON_FILE, help="danh sách từ Latin được phép")
    ap.add_argument("--latin-stats", action="store_true", help="in số lần xuất hiện của từng từ Latin")
    args = ap.parse_args()
    lexicon = {
        w.strip() for w in args.lexicon.read_text(encoding="utf-8").splitlines()
        if w.strip() and not w.startswith("#")
    }
    latin_count: collections.Counter[str] = collections.Counter()

    errors: dict[str, list[str]] = collections.defaultdict(list)
    warns: dict[str, list[str]] = collections.defaultdict(list)
    ids: set[str] = set()
    seen: dict[str, int] = {}
    cats: collections.Counter[str] = collections.Counter()
    n = total_chars = total_words = 0

    with open(args.texts, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            where = f"dòng {ln}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors["JSON hỏng"].append(f"{where}: {exc}")
                continue
            text = row.get("text")
            if not isinstance(text, str) or not text.strip():
                errors["thiếu text"].append(where)
                continue
            n += 1
            text = text.strip()
            if text != unicodedata.normalize("NFC", text):
                warns["chưa ở dạng NFC (sẽ tự chuẩn hoá khi sinh audio)"].append(where)
            rid = row.get("id")
            if rid is not None:
                if not isinstance(rid, str) or not ID_RE.match(rid):
                    errors["id không hợp lệ"].append(f"{where}: {rid!r}")
                elif rid in ids:
                    errors["id trùng"].append(f"{where}: {rid}")
                else:
                    ids.add(rid)

            if DIGIT_RE.search(text):
                errors["còn chữ số (phải viết thành chữ)"].append(f"{where}: {text[:90]}")
            if BAD_SYMBOL_RE.search(text):
                errors["còn ký hiệu (| / % & @ + ...)"].append(f"{where}: {text[:90]}")
            odd = sorted({ch for ch in text if not is_allowed_char(ch)} - set("0123456789" + BAD_SYMBOLS))
            if odd:
                errors["ký tự lạ"].append(f"{where}: {''.join(odd)!r}")
            for m in MIXED_ALNUM_RE.findall(text):
                warns["từ lẫn chữ và số"].append(f"{where}: {m}")

            for i, tok in enumerate(t.strip(TOKEN_STRIP) for t in text.split()):
                if not tok:
                    continue
                if re.fullmatch(r"[A-ZĐ]", tok) and not (i == 0 and tok == "A"):
                    errors["chữ cái đứng riêng (viết tên đọc, mục 3.4: ét, dét, ích...)"].append(f"{where}: {tok}")
                elif ALLCAPS_RE.fullmatch(tok) and tok not in lexicon:
                    errors["viết tắt HOA (đánh vần theo mục 3.4)"].append(f"{where}: {tok}")
                elif re.fullmatch(r"[A-Za-z][A-Za-z\-]*", tok):
                    vn = VN_SYLLABLE_RE.fullmatch(tok.lower()) and not re.search(r"[fjwzFJWZ]", tok)
                    lex = tok if tok in lexicon else tok[0].lower() + tok[1:] if i == 0 else None
                    if lex in lexicon:  # đầu câu: "Camera" = "camera"
                        latin_count[lex] += 1
                    elif not vn or (i > 0 and tok[0].isupper() and len(tok) > 1 and not tok.istitle()):
                        errors["từ Latin ngoài lexicon_latin.txt"].append(f"{where}: {tok}")
            low = text.lower()
            for rx, msg in FORBIDDEN:
                if rx.search(low):
                    errors[f"sai luật đọc: {msg}"].append(f"{where}: {text[:90]}")
            for rx, msg in SUSPECT:
                if rx.search(low):
                    warns[msg].append(f"{where}: {text[:90]}")

            words = len(text.split())
            if words < MIN_WORDS:
                warns[f"câu ngắn (< {MIN_WORDS} từ)"].append(f"{where}: {text}")
            if words > MAX_WORDS:
                errors[f"câu dài (> {MAX_WORDS} từ, dễ vượt 20 giây)"].append(f"{where}: {words} từ")
            if text[-1] not in ".?!…":
                warns["không kết thúc bằng . ? !"].append(f"{where}: …{text[-40:]}")

            key = norm_key(text)
            if key in seen:
                errors["câu trùng"].append(f"{where} trùng dòng {seen[key]}")
            else:
                seen[key] = ln
            cats[row.get("category") or "(không có)"] += 1
            total_chars += len(text)
            total_words += words

    def dump(title: str, bag: dict[str, list[str]]) -> None:
        for kind, items in sorted(bag.items(), key=lambda kv: -len(kv[1])):
            print(f"\n[{title}] {kind}: {len(items)}")
            for it in items[: args.show]:
                print(f"   {it}")
            if len(items) > args.show:
                print(f"   ... còn {len(items) - args.show}")

    dump("ERROR", errors)
    dump("WARN", warns)

    if args.latin_stats:
        print("\n=== Từ Latin (TEXT_SPEC 3.6: mỗi từ ≥ 20 lần) ===")
        for w in sorted(lexicon, key=lambda w: latin_count[w]):
            print(f"   {w:<16} {latin_count[w]:>5}{'   ← thiếu' if latin_count[w] < 20 else ''}")

    hours = total_words / WORDS_PER_SEC / 3600
    print("\n=== Thống kê ===")
    print(f"số câu           : {n}")
    print(f"tổng ký tự       : {total_chars:,}  (≈ số credit ElevenLabs tiêu, tuỳ model)")
    print(f"tổng từ          : {total_words:,}  (trung bình {total_words / max(n, 1):.1f} từ/câu)")
    print(f"ước lượng audio  : ~{hours:.1f} giờ (giả định {WORDS_PER_SEC:g} từ/giây)")
    print("theo category    :")
    for c, k in cats.most_common():
        print(f"   {c:<28} {k:>6}  ({k / max(n, 1):.1%})")

    n_err = sum(len(v) for v in errors.values())
    print(f"\n{'KHÔNG ĐẠT' if n_err else 'ĐẠT'}: {n_err} lỗi, {sum(len(v) for v in warns.values())} cảnh báo")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
