"""Phần dùng chung của bộ bench TTS: SSL, User-Agent, khoá API, đo thời lượng audio."""

from __future__ import annotations

import os
import ssl
import subprocess
from pathlib import Path

# Cloudflare trước tts-rt.soniox.com chặn User-Agent mặc định của urllib (403, error 1010).
UA = "noble-tts-bench/1.0"

_ENV_VAR = {"soniox": "SONIOX_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


def ssl_context() -> ssl.SSLContext:
    """Context có CA dùng được trên cả python hệ thống lẫn venv của repo.

    Một số bản python framework trên macOS không kèm CA bundle nên
    `create_default_context()` trần sẽ ném CERTIFICATE_VERIFY_FAILED.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def api_key(provider: str) -> str:
    """Đọc khoá từ môi trường. Ném nếu thiếu — im lặng bỏ qua nhà cung cấp thì
    báo cáo cuối sẽ chỉ có một bên mà không ai nhận ra."""
    var = _ENV_VAR[provider]
    key = os.environ.get(var, "").strip()
    if not key:
        raise RuntimeError(f"thiếu {var} — xem README.md mục Khoá API")
    return key


def audio_duration(path: Path) -> float:
    """Thời lượng (giây). PCM/µ-law không có header nên suy từ kích thước tệp."""
    if path.suffix == ".ulaw":
        return path.stat().st_size / 8000  # µ-law 8kHz, 1 byte/mẫu
    if path.suffix == ".pcm":
        return path.stat().st_size / (16000 * 2)  # pcm_s16le mono 16kHz
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return round(float(out.stdout.strip()), 3)
