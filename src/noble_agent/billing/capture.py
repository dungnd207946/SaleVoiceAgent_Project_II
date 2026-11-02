"""Chuẩn hoá object usage của provider về bốn cột rời nhau của ta.

Bốn cột (input / output / cache_write / cache_read) **không giao nhau**, vì đơn
giá của chúng khác nhau. Anthropic vốn đã tách rời. OpenAI thì ``prompt_tokens``
ĐÃ BAO GỒM phần cached, nên phải trừ ra — không trừ là đếm phần cached hai lần
với giá của input thường.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("noble_agent.billing.capture")


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def normalize_usage(usage: Any) -> dict | None:
    """Trả dict bốn cột + cờ ``exact``, hoặc None khi không có gì để đọc."""
    if usage is None:
        return None

    # Anthropic (qua adapter của ta)
    if hasattr(usage, "input_tokens"):
        out = getattr(usage, "output_tokens", None)
        return {
            "input_tokens": _int(usage.input_tokens),
            "output_tokens": _int(out),
            "cache_write_tokens": _int(getattr(usage, "cache_creation_input_tokens", 0)),
            "cache_read_tokens": _int(getattr(usage, "cache_read_input_tokens", 0)),
            "exact": out is not None,
        }

    # OpenAI-compat
    if hasattr(usage, "prompt_tokens"):
        prompt = _int(usage.prompt_tokens)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = _int(getattr(details, "cached_tokens", 0)) if details is not None else 0
        completion = getattr(usage, "completion_tokens", None)
        out = _int(completion)
        # Có endpoint KHÔNG kể thinking token vào `completion_tokens` nhưng VẪN
        # tính tiền chúng như output, chỉ để lại dấu ở `total_tokens`. Đo thật
        # trên Gemini OpenAI-compat 2026-08-18: thinking BẬT ⇒ prompt=36,
        # completion=12, total=332 (284 token bị bỏ ngoài); thinking TẮT ⇒ khớp
        # đúng. Dồn phần chênh vào output để bốn cột của ta luôn cộng lại bằng
        # `total_tokens`. No-op với endpoint đã khớp (OpenAI / vLLM / DashScope —
        # đã probe). Thiếu nó thì bật `NOBLE_LLM_ENABLE_THINKING` là đếm thiếu
        # output ~95%, im lặng.
        total = _int(getattr(usage, "total_tokens", 0))
        if total > 0:
            out = max(out, total - prompt)
        return {
            "input_tokens": max(0, prompt - cached),
            "output_tokens": out,
            "cache_write_tokens": 0,
            "cache_read_tokens": cached,
            "exact": completion is not None,
        }

    return None


def record(provider: str, model: str, usage: Any, *, purpose: str, wall_ms: float = 0.0) -> None:
    """Ghi usage của MỘT lời gọi LLM vào meter hiện hành. No-op khi không có meter.

    Provider không trả usage ⇒ vẫn ghi một dòng ``exact=False`` với token 0:
    việc lời gọi đã xảy ra là một sự thật cần biết, và tỷ lệ ``exact=False``
    chính là thước đo mức doanh thu đang bị bỏ sót.

    ``wall_ms`` là thời gian của chính lời gọi (contract §2.1 ``llm.wall_ms``) —
    giá vốn nội bộ, không tính cho khách. Đo được kể cả khi provider không trả
    usage, nên nó vẫn được ghi trên dòng ``exact=False``.
    """
    from noble_agent.billing.context import current_meter

    meter = current_meter()
    if meter is None:
        return

    # Guard normalization independently: any exception → norm = None
    norm = None
    try:
        norm = normalize_usage(usage)
    except Exception:  # noqa: BLE001
        logger.debug("billing: normalize_usage failed", exc_info=True)

    # Single write site guarded: use norm if available, otherwise inexact defaults
    try:
        if norm is None:
            meter.add_llm(purpose=purpose, provider=provider, model=model, wall_ms=wall_ms, exact=False)
        else:
            meter.add_llm(purpose=purpose, provider=provider, model=model, wall_ms=wall_ms, **norm)
    except Exception:  # noqa: BLE001 — đo lường không được làm hỏng lượt
        logger.debug("billing: record usage failed", exc_info=True)
