#!/usr/bin/env python3
"""Sinh audio huấn luyện TTS từ texts.jsonl bằng ElevenLabs, rồi đóng gói dataset.

Đầu ra (cùng định dạng bộ santa, dùng thẳng cho OmniVoice / VieNeu):
    <out>/raw_audio/<id>.wav     24 kHz, mono, 16-bit PCM (lấy pcm_24000, không qua mp3)
    <out>/metadata.csv           file_name|text|speaker
    <out>/omnivoice_train.jsonl  {"id","audio_path","text","language_id"}
    <out>/omnivoice_dev.jsonl
    <out>/progress.jsonl         nhật ký từng câu đã sinh (để chạy tiếp)
    <out>/errors.jsonl           câu lỗi (chạy lại lệnh để thử lại)
    <out>/suspicious.csv         câu có tốc độ đọc bất thường — nên nghe lại

API key: biến môi trường ELEVENLABS_API_KEY, hoặc dòng ELEVENLABS_API_KEY=... trong
file .env cạnh script. Không bao giờ in key ra màn hình.

Chạy:
    python3 gen_audio.py --dry-run                      # đếm ký tự, xem quota, không tốn credit
    python3 gen_audio.py --limit 10 --out out_thu       # sinh thử 10 câu để nghe
    python3 gen_audio.py                                # sinh toàn bộ (chạy lại = chạy tiếp)
    python3 gen_audio.py --finalize-only                # chỉ đóng gói lại từ wav đã có
"""

from __future__ import annotations

import argparse
import array
import concurrent.futures as cf
import hashlib
import json
import math
import os
import random
import statistics
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from pathlib import Path

API = "https://api.elevenlabs.io"
SR = 24000
MIN_SEC, MAX_SEC = 1.0, 20.0  # khớp prepare_santa_jsonl.py / extract_audio_tokens
HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- cấu hình
def load_dotenv() -> None:
    """Nạp tts-data/.env vào os.environ (biến đã export sẵn được ưu tiên)."""
    env_file = HERE / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        k = k.strip()
        if sep and k and not k.startswith("#"):
            v = v.strip().strip('"').strip("'")
            if v and not os.environ.get(k):
                os.environ[k] = v


def load_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("Thiếu ELEVENLABS_API_KEY (export biến môi trường hoặc ghi vào tts-data/.env)")
    return key


def read_texts(path: Path) -> list[dict]:
    rows, ids = [], set()
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = unicodedata.normalize("NFC", row["text"].strip())
            rid = row.get("id") or hashlib.sha1(text.encode()).hexdigest()[:12]
            if rid in ids:
                sys.exit(f"id trùng ở dòng {ln}: {rid} — chạy check_texts.py trước")
            ids.add(rid)
            rows.append({"id": rid, "text": text, "category": row.get("category")})
    return rows


# ---------------------------------------------------------------- HTTP
class Fatal(Exception):
    """Lỗi không thử lại được (sai key, sai voice, hết quota...)."""


def http(method: str, url: str, key: str, body: dict | None = None, timeout: float = 120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("xi-api-key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def error_text(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:500]
    except Exception:
        return ""


def check_quota(key: str, need_chars: int) -> None:
    try:
        raw, _ = http("GET", f"{API}/v1/user/subscription", key, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and "permission" not in error_text(exc).lower():
            sys.exit("API key không hợp lệ (401).")
        print(f"(không đọc được quota: HTTP {exc.code} — key có thể thiếu quyền user_read; bỏ qua)")
        return
    sub = json.loads(raw)
    used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
    left = limit - used
    print(f"quota: đã dùng {used:,}/{limit:,} ký tự, còn {left:,} (gói {sub.get('tier')})")
    if need_chars > left:
        print(f"⚠️  cần ~{need_chars:,} ký tự, nhiều hơn phần còn lại — sẽ dừng giữa chừng khi hết quota")


def synth(key: str, text: str, args) -> tuple[bytes, str]:
    url = f"{API}/v1/text-to-speech/{args.voice_id}?output_format=pcm_{SR}"
    body: dict = {"text": text, "model_id": args.model, "seed": args.seed}
    if args.language:
        body["language_code"] = args.language
    vs = {
        k: v
        for k, v in {
            "stability": args.stability,
            "similarity_boost": args.similarity,
            "style": args.style,
            "speed": args.speed,
        }.items()
        if v is not None
    }
    if vs:
        body["voice_settings"] = vs

    for attempt in range(args.max_retries + 1):
        try:
            pcm, headers = http("POST", url, key, body)
            return pcm, headers.get("request-id", "")
        except urllib.error.HTTPError as exc:
            msg = error_text(exc)
            if exc.code in (401, 403) or "quota_exceeded" in msg or "voice_not_found" in msg:
                raise Fatal(f"HTTP {exc.code}: {msg}") from None
            if exc.code not in (408, 409, 429, 500, 502, 503, 504) or attempt == args.max_retries:
                raise RuntimeError(f"HTTP {exc.code}: {msg}") from None
            wait = float(exc.headers.get("Retry-After") or 0) or min(60, 2**attempt) + random.random()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == args.max_retries:
                raise RuntimeError(f"mạng: {exc}") from None
            wait = min(60, 2**attempt) + random.random()
        time.sleep(wait)
    raise RuntimeError("hết lượt thử")


# ---------------------------------------------------------------- audio
def trim_silence(pcm: bytes, pad_sec: float = 0.15, floor_db: float = -45.0) -> bytes:
    """Cắt khoảng lặng đầu/cuối, giữ lại pad_sec mỗi bên."""
    s = array.array("h")
    s.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        s.byteswap()
    hop = SR // 100  # khung 10 ms
    thr = 32768 * 10 ** (floor_db / 20)
    voiced = [
        i
        for i in range(0, len(s), hop)
        if math.sqrt(sum(x * x for x in s[i : i + hop]) / max(1, len(s[i : i + hop]))) > thr
    ]
    if not voiced:
        return pcm
    pad = int(pad_sec * SR)
    a, b = max(0, voiced[0] - pad), min(len(s), voiced[-1] + hop + pad)
    out = s[a:b]
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def write_wav(path: Path, pcm: bytes) -> float:
    tmp = path.with_suffix(".wav.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    tmp.replace(path)  # ghi nguyên tử: wav dở dang không bao giờ bị coi là xong
    return len(pcm) / 2 / SR


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# ---------------------------------------------------------------- đóng gói
def finalize(rows: list[dict], out: Path, args) -> None:
    audio = out / "raw_audio"
    kept, dropped = [], []
    for r in rows:
        p = audio / f"{r['id']}.wav"
        if not p.is_file():
            continue
        d = wav_duration(p)
        (kept if MIN_SEC <= d <= MAX_SEC else dropped).append({**r, "dur": d, "path": p})
    if not kept:
        print("Chưa có wav nào hợp lệ để đóng gói.")
        return

    # Tốc độ đọc bất thường thường là audio bị cắt cụt, đọc lặp hoặc tự chèn chữ
    rates = [len(k["text"]) / k["dur"] for k in kept]
    med = statistics.median(rates)
    sus = [(k, rt) for k, rt in zip(kept, rates) if not (med * 0.65 <= rt <= med * 1.5)]
    with open(out / "suspicious.csv", "w", encoding="utf-8") as f:
        f.write("file_name|ky_tu_moi_giay|thoi_luong|text\n")
        for k, rt in sorted(sus, key=lambda x: x[1]):
            f.write(f"{k['id']}.wav|{rt:.1f}|{k['dur']:.2f}|{k['text']}\n")
    if args.drop_suspicious:
        bad = {k["id"] for k, _ in sus}
        kept = [k for k in kept if k["id"] not in bad]

    with open(out / "metadata.csv", "w", encoding="utf-8") as f:
        f.write("file_name|text|speaker\n")
        for k in kept:
            f.write(f"{k['id']}.wav|{k['text']}|{args.speaker}\n")

    items = [
        {"id": k["id"], "audio_path": str(k["path"].resolve()), "text": k["text"], "language_id": "vi"}
        for k in kept
    ]
    random.Random(42).shuffle(items)
    dev_n = min(args.dev_size, max(1, len(items) // 20))
    for name, part in (("dev", items[:dev_n]), ("train", items[dev_n:])):
        with open(out / f"omnivoice_{name}.jsonl", "w", encoding="utf-8") as f:
            for it in part:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    secs = sum(k["dur"] for k in kept)
    print("\n=== Đóng gói ===")
    print(f"giữ lại      : {len(kept)} câu, {secs / 3600:.2f} giờ, trung bình {secs / len(kept):.1f} giây")
    print(f"loại (độ dài ngoài {MIN_SEC:g}-{MAX_SEC:g} giây): {len(dropped)}")
    print(f"đáng ngờ     : {len(sus)} câu (tốc độ trung vị {med:.1f} ký tự/giây) -> {out / 'suspicious.csv'}"
          + (" — ĐÃ LOẠI" if args.drop_suspicious else " — vẫn giữ, nên nghe lại"))
    print(f"chưa có audio: {len(rows) - len(kept) - len(dropped) - (len(sus) if args.drop_suspicious else 0)}")
    print(f"metadata     : {out / 'metadata.csv'}")
    print(f"omnivoice    : {out / 'omnivoice_train.jsonl'} ({len(items) - dev_n}), omnivoice_dev.jsonl ({dev_n})")


# ---------------------------------------------------------------- main
def _env_float(name: str) -> float | None:
    v = os.environ.get(name, "").strip()
    return float(v) if v else None


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--texts", type=Path, default=HERE / "texts.jsonl")
    ap.add_argument("--out", type=Path, default=HERE / "dataset")
    ap.add_argument("--voice-id", default=os.environ.get("ELEVENLABS_VOICE_ID"),
                    help="voice id ElevenLabs (hoặc biến ELEVENLABS_VOICE_ID)")
    ap.add_argument("--model", default="eleven_v4",
                    help="eleven_v4 (mặc định) | eleven_v3 | eleven_flash_v2_5 — cả ba hỗ trợ tiếng Việt")
    ap.add_argument("--language", default=os.environ.get("LANGUAGE_CODE", "vi"),
                    help="language_code (hoặc biến LANGUAGE_CODE); để rỗng nếu model báo lỗi")
    ap.add_argument("--speaker", default="speaker", help="tên giọng ghi vào cột speaker của metadata.csv")
    ap.add_argument("--seed", type=int, default=1234, help="giữ cố định để giọng đồng đều giữa các câu")
    # Bỏ trống ở cả cờ lẫn .env = dùng thiết lập đã lưu của voice.
    ap.add_argument("--stability", type=float, default=_env_float("STABILITY"))
    ap.add_argument("--similarity", type=float, default=_env_float("SIMILARITY_BOOST"))
    ap.add_argument("--style", type=float, default=_env_float("STYLE"))
    ap.add_argument("--speed", type=float, default=_env_float("SPEED"))
    ap.add_argument("--workers", type=int, default=3, help="số request song song (giới hạn theo gói)")
    ap.add_argument("--max-retries", type=int, default=6)
    ap.add_argument("--limit", type=int, help="chỉ sinh N câu đầu (để nghe thử)")
    ap.add_argument("--no-trim", action="store_true", help="không cắt lặng đầu/cuối")
    ap.add_argument("--dev-size", type=int, default=80)
    ap.add_argument("--drop-suspicious", action="store_true", help="loại câu tốc độ bất thường khỏi dataset")
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm ký tự và xem quota")
    ap.add_argument("--finalize-only", action="store_true", help="không gọi API, chỉ đóng gói lại")
    args = ap.parse_args()

    rows = read_texts(args.texts)
    if args.limit:
        rows = rows[: args.limit]
    audio = args.out / "raw_audio"
    audio.mkdir(parents=True, exist_ok=True)

    if args.finalize_only:
        finalize(rows, args.out, args)
        return

    todo = [r for r in rows if not (audio / f"{r['id']}.wav").is_file()]
    need = sum(len(r["text"]) for r in todo)
    print(f"tổng {len(rows)} câu, đã có {len(rows) - len(todo)}, cần sinh {len(todo)} câu ≈ {need:,} ký tự")

    key = load_api_key()
    check_quota(key, need)
    if args.dry_run or not todo:
        if not todo:
            finalize(rows, args.out, args)
        return
    if not args.voice_id:
        sys.exit("Thiếu --voice-id (hoặc biến ELEVENLABS_VOICE_ID)")

    print(f"model={args.model} voice={args.voice_id} workers={args.workers} -> {args.out}")
    print(f"language={args.language} seed={args.seed} stability={args.stability} "
          f"similarity={args.similarity} style={args.style} speed={args.speed}")
    lock, stop = threading.Lock(), threading.Event()
    done = fail = 0
    t0 = time.time()
    progress = open(args.out / "progress.jsonl", "a", encoding="utf-8")
    errors = open(args.out / "errors.jsonl", "a", encoding="utf-8")

    def job(r: dict) -> None:
        nonlocal done, fail
        if stop.is_set():
            return
        try:
            pcm, req_id = synth(key, r["text"], args)
            if not args.no_trim:
                pcm = trim_silence(pcm)
            dur = write_wav(audio / f"{r['id']}.wav", pcm)
            rec, ok = {"id": r["id"], "dur": round(dur, 3), "chars": len(r["text"]),
                       "model": args.model, "voice": args.voice_id, "request_id": req_id}, True
        except Fatal as exc:
            stop.set()
            rec, ok = {"id": r["id"], "error": str(exc), "fatal": True}, False
        except Exception as exc:
            rec, ok = {"id": r["id"], "error": str(exc)}, False
        with lock:
            (progress if ok else errors).write(json.dumps(rec, ensure_ascii=False) + "\n")
            (progress if ok else errors).flush()
            if ok:
                done += 1
            else:
                fail += 1
                print(f"  ✗ {r['id']}: {rec['error'][:160]}")
            n = done + fail
            if n % 25 == 0 or n == len(todo):
                rate = n / max(1e-6, time.time() - t0)
                eta = (len(todo) - n) / max(rate, 1e-6) / 60
                print(f"  {n}/{len(todo)}  ok={done} lỗi={fail}  {rate:.2f} câu/giây  còn ~{eta:.0f} phút")

    try:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(job, todo))
    except KeyboardInterrupt:
        stop.set()
        print("\nDừng. Chạy lại cùng lệnh để sinh tiếp phần còn thiếu.")
    finally:
        progress.close()
        errors.close()

    if stop.is_set():
        print("⛔ Dừng do lỗi không thử lại được (xem errors.jsonl, dòng fatal).")
    finalize(rows, args.out, args)
    if fail:
        print(f"\n{fail} câu lỗi — chạy lại cùng lệnh để thử lại các câu này.")


if __name__ == "__main__":
    main()
