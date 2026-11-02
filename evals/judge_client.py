"""Judge infra dùng chung: SQLite cache, budget cap, cost tracking, OpenAI-compat call, retry.

Tách từ quality/judge.py 2026-08-25, hành vi giữ nguyên; quality/judge.py và
rag/generate.py là 2 consumer. Rubric/prompt KHÔNG nằm ở đây — module này chỉ
là hạ tầng gọi LLM thuần (không import noble_agent).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("evals.judge_client")

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17"))
# Judge có thể chấm qua endpoint OpenAI-compat khác (vd. DashScope cho qwen):
# set EVAL_JUDGE_BASE_URL + EVAL_JUDGE_API_KEY; bỏ trống → SDK dùng OPENAI_* như cũ.
JUDGE_BASE_URL = os.getenv("EVAL_JUDGE_BASE_URL") or None
JUDGE_API_KEY = os.getenv("EVAL_JUDGE_API_KEY") or None
JUDGE_TEMP = 0.0
JUDGE_TIMEOUT_S = 30
JUDGE_RETRY = 2  # initial + 2 retries = 3 total attempts


# ── SQLite judge cache ────────────────────────────────────────────────────────

_CACHE_PATH: Path | None = None


def set_cache_path(p: Path | None) -> None:
    """Configure cache location. Call with None to disable. Tests use tmp_path."""
    global _CACHE_PATH
    _CACHE_PATH = p
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE IF NOT EXISTS judge_cache (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()


def cache_key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def cache_get(key: str) -> dict | None:
    if not _CACHE_PATH:
        return None
    conn = sqlite3.connect(_CACHE_PATH)
    row = conn.execute("SELECT v FROM judge_cache WHERE k=?", (key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def cache_put(key: str, value: dict) -> None:
    if not _CACHE_PATH:
        return
    conn = sqlite3.connect(_CACHE_PATH)
    conn.execute("INSERT OR REPLACE INTO judge_cache VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()


# ── Cost tracker + budget cap ─────────────────────────────────────────────────

# Pricing (approximate, USD per 1M tokens). Model NGOÀI bảng này vẫn chạy nhưng
# cost đếm 0 → --judge-budget-usd không bao giờ kích hoạt; thêm giá khi đổi model.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.4-nano-2026-03-17": (0.05, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "qwen3.7-plus": (0.40, 1.20),
    "qwen3.6-plus": (0.40, 1.20),
}

_COST_USD = 0.0
_BUDGET_USD: float | None = None


class BudgetExceeded(RuntimeError):
    pass


def set_budget(usd: float | None) -> None:
    """Cap total $ spent. Subsequent calls raise BudgetExceeded if cap reached."""
    global _BUDGET_USD
    _BUDGET_USD = usd


def reset_cost() -> None:
    """Reset cost counter to 0 (per-run init)."""
    global _COST_USD
    _COST_USD = 0.0


def get_cost_usd() -> float:
    return _COST_USD


# ── HTTP helpers ──────────────────────────────────────────────────────────────


async def call_llm(model: str, system: str, user: str, *, json_mode: bool = True, max_tokens: int = 800) -> str:
    """One-shot OpenAI-compat call. Raise BudgetExceeded khi chạm cap. Patched in tests."""
    global _COST_USD
    if _BUDGET_USD is not None and _COST_USD >= _BUDGET_USD:
        raise BudgetExceeded(f"judge cost ${_COST_USD:.4f} ≥ cap ${_BUDGET_USD:.4f}")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=JUDGE_BASE_URL, api_key=JUDGE_API_KEY)
    # Qwen3.x bật thinking mặc định: reasoning ăn hết max_completion_tokens nên
    # content về rỗng ("Expecting value: char 0") hoặc JSON cụt ("Unterminated
    # string"). Judge cần JSON deterministic, không cần thinking → tắt. Chỉ gửi
    # cho model qwen — endpoint OpenAI từ chối param lạ bằng 400.
    extra: dict = {"extra_body": {"enable_thinking": False}} if model.startswith("qwen") else {}
    if json_mode:
        extra["response_format"] = {"type": "json_object"}
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=JUDGE_TEMP,
            max_completion_tokens=max_tokens,
            **extra,
        ),
        timeout=JUDGE_TIMEOUT_S,
    )
    usage = resp.usage
    if usage and model in _PRICING:
        in_rate, out_rate = _PRICING[model]
        _COST_USD += (usage.prompt_tokens / 1_000_000) * in_rate
        _COST_USD += (usage.completion_tokens / 1_000_000) * out_rate
    return resp.choices[0].message.content or ""


async def call_llm_json(model: str, system: str, user: str, *, max_tokens: int = 800) -> tuple[str, dict | None]:
    """Call call_llm(json_mode=True) with up to JUDGE_RETRY retries on malformed JSON.

    Returns (raw_text, parsed_dict_or_None). None when all attempts fail to parse.
    """
    raw = ""
    for attempt in range(JUDGE_RETRY + 1):
        try:
            raw = await call_llm(model, system, user, json_mode=True, max_tokens=max_tokens)
            return raw, json.loads(raw)
        except (json.JSONDecodeError, TimeoutError) as e:
            # Retry only transient/parse errors. BudgetExceeded and other
            # programming errors propagate so the cost cap is not violated
            # and bugs surface immediately.
            logger.warning("judge attempt %d failed: %s", attempt + 1, e)
            if attempt < JUDGE_RETRY:
                await asyncio.sleep(1.0 * (3**attempt))
    return raw, None
