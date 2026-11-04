"""Addressee gate — quyết định câu nói của khách có hướng tới agent hay không.

Chống "nói leo": khách quay sang nói chuyện với người bên cạnh trong lúc agent
đang nói thì KHÔNG được tính là barge-in. Hai tầng: heuristic thuần (0ms) và
LLM one-shot (chỉ ca mơ hồ). Fail-open: mọi đường lỗi đều trả DIRECTED ở tầng
dispatch (classify) — thà ngắt oan còn hơn làm agent điếc.

Spec: docs/superpowers/specs/2026-08-12-addressee-gate-design.md
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from enum import StrEnum

logger = logging.getLogger("addressee")


class Verdict(StrEnum):
    DIRECTED = "directed"
    SIDE_TALK = "side_talk"
    UNSURE = "unsure"


# Backchannel: câu chỉ gồm các token đệm — khách đang "ừ hử" theo, không phải
# ngắt lời. So khớp token-set sau khi bỏ dấu câu, nên "dạ dạ" / "à vâng" đều dính.
_BACKCHANNEL_TOKENS = {
    "ừ", "ừm", "ờ", "à", "ạ", "dạ", "vâng", "vầng", "ok", "okay", "oke", "uh", "ừa", "ha", "hử", "hả",
}

# Gọi đích danh agent → DIRECTED. agent_name (lowercase) được thêm lúc runtime.
_AGENT_CALL_PATTERNS = ("em ơi", "em à", "này em", "alo", "a lô")

# Gọi đích danh người khác (xưng hô gia đình/đồng hành) → SIDE_TALK.
_OTHER_CALL_PATTERNS = (
    "anh ơi", "chị ơi", "con ơi", "mẹ ơi", "bố ơi", "ba ơi", "ông ơi", "bà ơi",
    "cưng ơi", "bé ơi", "vợ ơi", "chồng ơi",
)

_PUNCT_RE = re.compile(r"[.,!?;:…\"'()\-]+")


def _normalize(text: str) -> str:
    return " ".join(_PUNCT_RE.sub(" ", text.lower()).split())


def classify_heuristic(text: str, *, agent_name: str = "") -> Verdict:
    """Tầng 1 — thuần chuỗi, 0ms, 0 chi phí. UNSURE nghĩa là 'để tầng sau quyết'."""
    norm = _normalize(text)
    if not norm:
        return Verdict.UNSURE

    tokens = norm.split()
    if tokens and all(t in _BACKCHANNEL_TOKENS for t in tokens):
        return Verdict.SIDE_TALK

    if agent_name and agent_name.lower() in norm:
        return Verdict.DIRECTED
    if any(p in norm for p in _AGENT_CALL_PATTERNS):
        return Verdict.DIRECTED
    if any(p in norm for p in _OTHER_CALL_PATTERNS):
        return Verdict.SIDE_TALK
    return Verdict.UNSURE


class EpisodeTracker:
    """Đếm speech-ms cho một 'interrupt episode' — pure logic, dùng chung
    BaseSession + telephony. feed() mỗi VAD chunk; trả 'pause' đúng MỘT lần
    khi speech tích lũy đủ ngưỡng, 'reset' khi im lặng đủ lâu trước khi đạt
    ngưỡng (blip: ho, 'ừ' ngắn), None cho mọi chunk còn lại."""

    def __init__(self, min_speech_ms: int, chunk_ms: int, silence_reset_ms: int = 320) -> None:
        self._min_speech_ms = min_speech_ms
        self._chunk_ms = chunk_ms
        self._silence_reset_ms = silence_reset_ms
        self._speech_ms = 0
        self._silence_ms = 0
        self._fired = False

    def feed(self, is_speech: bool) -> str | None:
        if self._fired:
            return None
        if is_speech:
            self._speech_ms += self._chunk_ms
            self._silence_ms = 0
            if self._speech_ms >= self._min_speech_ms:
                self._fired = True
                return "pause"
            return None
        self._silence_ms += self._chunk_ms
        if self._silence_ms >= self._silence_reset_ms:
            self.reset()
            return "reset"
        return None

    def reset(self) -> None:
        self._speech_ms = 0
        self._silence_ms = 0
        self._fired = False


# Import mức module để test patch được noble_agent.voice.addressee_gate.get_settings.
from noble_agent.config import get_settings  # noqa: E402

_LLM_PROMPT = """Bạn là bộ lọc hội thoại của tổng đài viên tên {agent_name} (nữ, xưng "em").
Bối cảnh cuộc gọi tư vấn bất động sản đang diễn ra:
- Câu {agent_name} đang nói (tính đến giờ): "{agent_line}"
{context_line}
- Khách vừa nói: "{text}"

Nếu câu khách vừa nói chứa CẢ phần nói với người khác LẪN nội dung hướng tới
{agent_name} (ví dụ: quay sang dặn người nhà rồi hỏi tiếp về dự án) → tính là DIRECTED.

Câu khách vừa nói là nói VỚI {agent_name}, hay khách đang nói với người khác bên cạnh
(ví dụ người nhà, đồng nghiệp)? Trả lời đúng MỘT từ:
DIRECTED (nói với {agent_name}) hoặc SIDE_TALK (nói với người khác)."""


def _parse_verdict(raw: str) -> Verdict:
    up = (raw or "").strip().upper()
    if "SIDE" in up:
        return Verdict.SIDE_TALK
    if "DIRECT" in up:
        return Verdict.DIRECTED
    return Verdict.UNSURE


def _render_dialogue(recent_dialogue: Sequence[tuple[str, str]], agent_name: str) -> str:
    """Render (role, text) cặp gần đây thành transcript block, mỗi dòng một entry.

    role "user" → "Khách: <text>", còn lại → "<agent_name>: <text>". Mỗi dòng
    cắt 200 ký tự. Rỗng → "" (caller fallback về last_user_text)."""
    if not recent_dialogue:
        return ""
    name = agent_name or "Luna"
    lines = []
    for role, text in recent_dialogue:
        label = "Khách" if role == "user" else name
        lines.append(f"{label}: {(text or '')[:200]}")
    return "\n".join(lines)


async def _classify_llm(
    text: str,
    *,
    agent_line: str,
    last_user_text: str,
    agent_name: str,
    recent_dialogue: Sequence[tuple[str, str]] = (),
) -> Verdict:
    """Tầng 2 — one-shot LLM, provider chain dùng chung (pattern snapshot._call_merge_llm).
    Trả UNSURE khi không có provider / lỗi / câu trả lời không parse được."""
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.agent.llm.client import StreamingClient
    from noble_agent.config import primary_for, provider_model_map

    settings = get_settings()
    providers = build_llm_providers()
    if not providers:
        logger.warning("[Addressee] no LLM providers configured")
        return Verdict.UNSURE
    client = StreamingClient(
        providers=providers,
        enable_thinking=False,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    primary = primary_for(settings, settings.addressee_llm_model or settings.agent_model)
    name = agent_name or "Luna"
    dialogue_block = _render_dialogue(recent_dialogue, name)
    if dialogue_block:
        context_line = f"- Đoạn hội thoại gần đây:\n{dialogue_block}"
    else:
        context_line = f'- Câu ngay trước đó của khách: "{(last_user_text or "")[:200]}"'
    prompt = _LLM_PROMPT.format(
        agent_name=name,
        agent_line=(agent_line or "")[:400],
        context_line=context_line,
        text=text[:300],
    )
    raw = await client.complete_once(
        messages=[{"role": "user", "content": prompt}],
        model=provider_model_map(settings),
        temperature=0.0,
        max_tokens=8,
        primary=primary,
        request_timeout=settings.addressee_llm_timeout_ms / 1000,
        purpose="addressee_gate",
    )
    return _parse_verdict(raw)


async def classify(
    text: str,
    *,
    agent_line: str = "",
    last_user_text: str = "",
    agent_name: str = "",
    recent_dialogue: Sequence[tuple[str, str]] = (),
) -> Verdict:
    """Entrypoint duy nhất cho session code. KHÔNG raise, KHÔNG trả UNSURE —
    mọi đường mơ hồ/lỗi đều fail-open thành DIRECTED (giữ behavior cũ)."""
    try:
        mode = get_settings().addressee_gate_mode
        if mode == "off":
            return Verdict.DIRECTED
        if mode in ("heuristic", "hybrid"):
            v = classify_heuristic(text, agent_name=agent_name)
            if v is not Verdict.UNSURE:
                return v
            if mode == "heuristic":
                return Verdict.DIRECTED
        v = await _classify_llm(
            text,
            agent_line=agent_line,
            last_user_text=last_user_text,
            agent_name=agent_name,
            recent_dialogue=recent_dialogue,
        )
        logger.info("[Addressee] LLM verdict=%s for %r", v.value, text[:80])
        return Verdict.DIRECTED if v is Verdict.UNSURE else v
    except Exception as exc:  # noqa: BLE001 — fail-open là invariant
        logger.warning("[Addressee] classify failed (%s) — fail-open DIRECTED", exc)
        return Verdict.DIRECTED
