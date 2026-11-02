"""Wire protocol for the STT/TTS WebSocket services.

Quy ước: binary frame = PCM int16 thô; text frame = JSON control. Module thuần
Python (chỉ json) nên dùng được ở cả client lẫn server và test không cần dep nặng.
"""

from __future__ import annotations

import json

# Message types (giá trị khóa "type" trong JSON control frame)
PARTIAL = "partial"
FINAL = "final"
EOS = "eos"
SYNTHESIZE = "synthesize"
END = "end"

AUTH_HEADER = "Authorization"
_BEARER = "Bearer "


def transcript_msg(kind: str, text: str) -> str:
    """STT server → client: {"type": "partial"|"final", "text": ...}."""
    return json.dumps({"type": kind, "text": text})


def synthesize_msg(text: str, voice: str | None = None) -> str:
    """TTS client → server: {"type": "synthesize", "text": ..., "voice"?: ...}."""
    msg: dict = {"type": SYNTHESIZE, "text": text}
    if voice is not None:
        msg["voice"] = voice
    return json.dumps(msg)


def control_msg(kind: str) -> str:
    """Control frame mang đúng một khóa "type" (eos / end)."""
    return json.dumps({"type": kind})


def parse(raw: str) -> dict:
    """Decode một text frame JSON thành dict."""
    return json.loads(raw)


def auth_headers(token: str) -> dict[str, str]:
    """Header client gửi kèm; rỗng khi token tắt."""
    return {AUTH_HEADER: f"{_BEARER}{token}"} if token else {}


def token_from_headers(headers) -> str:
    """Trích bearer token từ headers (mapping-like .get); "" nếu không có/không hợp lệ."""
    val = ""
    try:
        val = headers.get(AUTH_HEADER, "") or ""
    except AttributeError:
        val = ""
    return val[len(_BEARER) :] if val.startswith(_BEARER) else ""


def check_token(headers, expected: str) -> bool:
    """True nếu auth tắt (expected rỗng) hoặc token khớp."""
    if not expected:
        return True
    return token_from_headers(headers) == expected
