"""Streaming markdown stripper cho reply hội thoại.

Persona quy định output là VĂN NÓI thuần (đọc qua TTS, chat hiển thị plain
text) nhưng qwen3.7-flash xả bullet/bold vào 2/3 lượt mở màn (đo 2026-08-24).
Đường voice đã có ``voice/tts/_normalize`` lo; lớp này chặn cho chat stream +
history, cùng pattern feed/flush với ``ThinkStripper``.

Chỉ gỡ marker cấu trúc, giữ nguyên nội dung:
  - ``**`` (bold) và backtick: gỡ mọi nơi, kể cả khi bị cắt giữa hai chunk.
  - ``- `` / ``* `` / ``+ `` / ``1. `` / ``# `` ở ĐẦU DÒNG: gỡ marker giữ chữ.
  - Dấu ``-``/``*`` giữa câu (A-0501, "2 * 3") giữ nguyên.
"""

from __future__ import annotations

import re

_BULLET_RE = re.compile(r"^(?:[-*+][ \t]+|#{1,6}[ \t]+|\d{1,3}\.[ \t]+)")
# Tiền tố CHƯA đủ để kết luận là bullet — giữ lại chờ chunk sau.
_MAYBE_BULLET_RE = re.compile(r"^(?:[-+]|#{1,6}|\d{1,3}\.?)$")


class MarkdownStripper:
    def __init__(self) -> None:
        self._buf = ""
        self._line_start = True

    def feed(self, piece: str) -> str:
        if piece:
            self._buf += piece
        out: list[str] = []
        while self._buf:
            if self._line_start:
                m = _BULLET_RE.match(self._buf)
                if m:
                    self._buf = self._buf[m.end() :]
                    continue
                if _MAYBE_BULLET_RE.match(self._buf):
                    break  # có thể còn thành bullet — chờ thêm
                if self._buf == "*" or self._buf == "**":
                    break  # "*" đầu dòng: chưa biết là bullet "* " hay bold "**"
                self._line_start = False
                continue
            nl = self._buf.find("\n")
            star = self._buf.find("*")
            tick = self._buf.find("`")
            idxs = [i for i in (nl, star, tick) if i != -1]
            if not idxs:
                out.append(self._buf)
                self._buf = ""
                break
            cut = min(idxs)
            out.append(self._buf[:cut])
            ch = self._buf[cut]
            if ch == "\n":
                out.append("\n")
                self._buf = self._buf[cut + 1 :]
                self._line_start = True
            elif ch == "`":
                self._buf = self._buf[cut + 1 :]
            else:  # "*"
                rest = self._buf[cut:]
                if rest.startswith("**"):
                    self._buf = self._buf[cut + 2 :]
                elif rest == "*":
                    self._buf = "*"  # cuối buffer — chờ chunk sau quyết định
                    break
                else:
                    out.append("*")  # "*" đơn giữa câu là nội dung thật
                    self._buf = self._buf[cut + 1 :]
        return "".join(out)

    def flush(self) -> str:
        buf, self._buf = self._buf, ""
        return buf.replace("**", "")


def strip_markdown(text: str) -> str:
    """Bản non-streaming cho chuỗi trọn vẹn."""
    s = MarkdownStripper()
    return s.feed(text) + s.flush()
