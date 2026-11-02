"""Khách ngắt lời khi TTS còn đang phát → cắt câu trả lời trong history về phần ĐÃ NGHE.

Vì sao: LLM stream xong (và orchestrator đã persist toàn bộ câu trả lời) sớm hơn nhiều
so với TTS phát; khách ngắt lời giữa chừng thì lượt sau model tin rằng mình đã nói
những câu khách chưa hề nghe (đã giới thiệu căn X, đã hỏi Y…). `VoiceAgent` theo dõi
đúng các clause đã phát (`spoken_text_this_turn`); ở đây thay content của assistant
cuối bằng phần đó kèm dấu ngắt để model biết chỗ dừng.

Thuần: không I/O, trả history MỚI (không sửa tại chỗ). Facade `NobleAgent.note_interrupted`
làm phần load / save.
"""

from __future__ import annotations

import re

from noble_agent.storage.models import ThreadMessage

INTERRUPT_MARK = "(bị khách ngắt lời ở đây)"
UNSPOKEN_MARK = "(bị khách ngắt lời trước khi kịp nói)"
# "[ack]" và các marker hiển thị khác mà pacer đưa vào spoken_texts nhưng không đọc ra loa.
_TAG_RE = re.compile(r"\[[^\]]{1,30}\]\s*")


def _clean(spoken: str) -> str:
    return " ".join(_TAG_RE.sub("", spoken or "").split())


def _last_spoken_assistant(history: list[ThreadMessage]) -> int | None:
    """Chỉ số assistant CÓ content sau user message cuối; None khi không có."""
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if m.role == "user":
            return None
        if m.role == "assistant" and (m.content or "").strip():
            return i
    return None


def trim_last_assistant(history: list[ThreadMessage], spoken_text: str) -> tuple[list[ThreadMessage], int | None]:
    """Trả (history mới, chỉ số message đã cắt). (history cũ, None) khi không cần cắt."""
    idx = _last_spoken_assistant(history)
    if idx is None:
        return history, None
    msg = history[idx]
    spoken = _clean(spoken_text)
    if spoken and spoken == " ".join((msg.content or "").split()):
        return history, None  # khách đã nghe trọn
    new_content = f"{spoken} {INTERRUPT_MARK}" if spoken else UNSPOKEN_MARK
    trimmed = msg.model_copy(update={"content": new_content})
    return history[:idx] + [trimmed] + history[idx + 1 :], idx
