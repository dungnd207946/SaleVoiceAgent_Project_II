"""Chấm điểm khách quan: phiên âm lại audio TTS bằng Soniox STT async, tính CER/WER.

Lưu ý thiên lệch: dùng STT của Soniox để chấm cả hai nhà cung cấp. STT đo độ
DỄ HIỂU của audio, không đo độ tự nhiên. Kết quả cần đọc kèm nghe thủ công.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from _common import UA, api_key, ssl_context

API = "https://api.soniox.com/v1"
STT_MODEL = os.environ.get("STT_MODEL", "stt-async-v5")
SSL_CTX = ssl_context()


def _req(
    path: str, *, method: str = "GET", body: dict | None = None, data: bytes | None = None, ctype: str | None = None
) -> dict:
    headers = {"Authorization": f"Bearer {api_key('soniox')}", "User-Agent": UA}
    payload = data
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(f"{API}{path}", data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180, context=SSL_CTX) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} {path}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
    return json.loads(raw) if raw else {}


def upload(path: Path) -> str:
    boundary = f"----bench{uuid.uuid4().hex}"
    parts = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: audio/mpeg\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    res = _req("/files", method="POST", data=parts, ctype=f"multipart/form-data; boundary={boundary}")
    return res["id"]


def transcribe(file_id: str) -> str:
    job = _req(
        "/transcriptions", method="POST", body={"file_id": file_id, "model": STT_MODEL, "language_hints": ["vi", "en"]}
    )
    tid = job["id"]
    for _ in range(120):
        status = _req(f"/transcriptions/{tid}")
        state = status.get("status")
        if state == "completed":
            break
        if state == "error":
            raise RuntimeError(f"STT lỗi: {status.get('error_message')}")
        time.sleep(1.5)
    else:
        raise RuntimeError("STT quá thời gian chờ")
    out = _req(f"/transcriptions/{tid}/transcript")
    if "text" in out:
        return out["text"]
    return "".join(t.get("text", "") for t in out.get("tokens", []))


def norm(text: str) -> str:
    """Chuẩn hoá để so sánh: bỏ dấu câu, hạ chữ thường, gộp khoảng trắng."""
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"\[[^\]]*\]", " ", text)  # bỏ audio tag [excited] ...
    text = re.sub(
        r"[^\w\sàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệ"
        r"ìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữự"
        r"ỳýỷỹỵđ]",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(a: list[str] | str, b: list[str] | str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> None:
    base = Path(__file__).parent
    cases = {}
    for cf in ("cases.json", "cases_emotion.json"):
        if (base / cf).exists():
            cases.update({c["id"]: c for c in json.loads((base / cf).read_text())})
    files = sorted((base / "out").glob("*__*.mp3"))
    if not files:
        sys.exit("Không có file audio trong out/")
    results = []
    for f in files:
        case_id, config = f.stem.split("__", 1)
        case = cases.get(case_id)
        if case is None:
            continue
        try:
            text = transcribe(upload(f))
        except RuntimeError as exc:
            print(f"FAIL {f.name}: {exc}", file=sys.stderr, flush=True)
            results.append({"case": case_id, "config": config, "error": str(exc)})
            continue
        ref, hyp = norm(case["text"]), norm(text)
        cer = edit_distance(ref, hyp) / max(len(ref), 1)
        wer = edit_distance(ref.split(), hyp.split()) / max(len(ref.split()), 1)
        results.append(
            {
                "case": case_id,
                "config": config,
                "cer_pct": round(cer * 100, 2),
                "wer_pct": round(wer * 100, 2),
                "ref": ref,
                "hyp": hyp,
            }
        )
        print(f"{config:30s} {case_id:8s} CER={cer * 100:5.2f}%  WER={wer * 100:5.2f}%", flush=True)
    (base / "results_stt.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("\n-> results_stt.json")


if __name__ == "__main__":
    main()
