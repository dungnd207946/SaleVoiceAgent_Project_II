"""Judge LLM grader — three rubric types (P1 MCQ, P2 essay, P3 sales).

Uses gpt-5.4-nano-2026-03-17 (override via ESTATE_JUDGE_MODEL) with
structured-output JSON. Retry on malformed JSON 2x with exp backoff.
Pure JSON parsing — no schema library dep.

Per-case verdict thresholds (P2 + P3, both 0-20 scale):
- pass: total ≥ 14  (matches overall 70% pass threshold)
- needs_human_review = True: 10 ≤ total < 14
- fail: total < 10

For P1 MCQ (0-2 scale): pass if score ≥ 2; otherwise fail / refused / uncertain.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI

logger = logging.getLogger("bench_estate.judge")

JUDGE_MODEL = os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17")
JUDGE_TEMP = 0.0
JUDGE_MAX_TOKENS = 800
JUDGE_TIMEOUT_S = 30
JUDGE_RETRY = 2  # initial + 2 retries = 3 total attempts


@dataclass
class JudgeResult:
    mapped: str = ""  # "A"/"B"/"C"/"D"/"refused"/"uncertain" (MCQ only)
    score: float = 0.0
    score_max: float = 0.0
    verdict: Literal["pass", "fail", "uncertain", "refused", "judge_error"] = "fail"
    rationale: str = ""
    rubric_breakdown: dict[str, float] = field(default_factory=dict)
    needs_human_review: bool = False
    raw_response: str = ""
    cached: bool = False


# ── SQLite judge cache (M3.4) ─────────────────────────────────────────────────

_CACHE_PATH: Path | None = None


def _set_cache_path(p: Path | None) -> None:
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


def _cache_key(case_id: str, agent_output: str, model: str, rubric: str) -> str:
    h = hashlib.sha1(f"{case_id}|{agent_output}|{model}|{rubric}".encode()).hexdigest()
    return h


def _cache_get(key: str) -> dict | None:
    if not _CACHE_PATH:
        return None
    conn = sqlite3.connect(_CACHE_PATH)
    row = conn.execute("SELECT v FROM judge_cache WHERE k=?", (key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, value: dict) -> None:
    if not _CACHE_PATH:
        return
    conn = sqlite3.connect(_CACHE_PATH)
    conn.execute("INSERT OR REPLACE INTO judge_cache VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()


def _result_to_cacheable(r: JudgeResult) -> dict:
    return {
        "mapped": r.mapped,
        "score": r.score,
        "score_max": r.score_max,
        "verdict": r.verdict,
        "rationale": r.rationale,
        "rubric_breakdown": r.rubric_breakdown,
        "needs_human_review": r.needs_human_review,
        "raw_response": r.raw_response,
    }


def _result_from_cache(d: dict) -> JudgeResult:
    return JudgeResult(
        mapped=d.get("mapped", ""),
        score=float(d.get("score", 0.0)),
        score_max=float(d.get("score_max", 0.0)),
        verdict=d.get("verdict", "fail"),
        rationale=d.get("rationale", ""),
        rubric_breakdown={k: float(v) for k, v in (d.get("rubric_breakdown") or {}).items()},
        needs_human_review=bool(d.get("needs_human_review", False)),
        raw_response=d.get("raw_response", ""),
        cached=True,
    )


# ── Cost tracker + budget cap (M3.5) ─────────────────────────────────────────

# gpt-5.4-nano-2026-03-17 pricing (approximate, USD per 1M tokens)
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.4-nano-2026-03-17": (0.05, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
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


async def _call_openai(model: str, system: str, user: str) -> str:
    """One-shot OpenAI call returning raw response content. Patched in tests."""
    global _COST_USD
    if _BUDGET_USD is not None and _COST_USD >= _BUDGET_USD:
        raise BudgetExceeded(f"judge cost ${_COST_USD:.4f} ≥ cap ${_BUDGET_USD:.4f}")
    client = AsyncOpenAI()
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=JUDGE_TEMP,
            max_completion_tokens=JUDGE_MAX_TOKENS,
            response_format={"type": "json_object"},
        ),
        timeout=JUDGE_TIMEOUT_S,
    )
    usage = resp.usage
    if usage and model in _PRICING:
        in_rate, out_rate = _PRICING[model]
        _COST_USD += (usage.prompt_tokens / 1_000_000) * in_rate
        _COST_USD += (usage.completion_tokens / 1_000_000) * out_rate
    return resp.choices[0].message.content or ""


async def _call_with_retry(model: str, system: str, user: str) -> tuple[str, dict | None]:
    """Call _call_openai with up to JUDGE_RETRY retries on malformed JSON.

    Returns (raw_text, parsed_dict_or_None). None when all attempts fail to parse.
    """
    raw = ""
    for attempt in range(JUDGE_RETRY + 1):
        try:
            raw = await _call_openai(model, system, user)
            return raw, json.loads(raw)
        except (json.JSONDecodeError, TimeoutError) as e:
            # Retry only transient/parse errors. BudgetExceeded and other
            # programming errors propagate so the cost cap is not violated
            # and bugs surface immediately.
            logger.warning("judge attempt %d failed: %s", attempt + 1, e)
            if attempt < JUDGE_RETRY:
                await asyncio.sleep(1.0 * (3**attempt))
    return raw, None


# ── P1 MCQ ────────────────────────────────────────────────────────────────────

_MCQ_PROMPT = """Bạn là giám khảo chấm bài kiểm tra môi giới BĐS Việt Nam.
Đối chiếu câu trả lời thí sinh với đáp án chuẩn, chấm khách quan.
Trả JSON đúng schema, không thêm prose."""


def _build_mcq_user(case, agent_output: str) -> str:
    correct_text = case.choices[case.correct]
    choices_block = "\n".join(f"{k}. {v}" for k, v in case.choices.items())
    return (
        f"[CÂU HỎI GỐC]\n{case.question}\n\n"
        f"{choices_block}\n\n"
        f"[ĐÁP ÁN ĐÚNG]\n{case.correct}: {correct_text}\n\n"
        f"[BÀI LÀM CỦA THÍ SINH]\n{agent_output}\n\n"
        "NHIỆM VỤ:\n"
        "1. Map bài làm → 1 chữ A/B/C/D dựa trên nội dung."
        " Nếu từ chối/né → 'refused'. Nếu mơ hồ → 'uncertain'.\n"
        "2. Score 0..2: 2=đúng+giải thích đúng;"
        " 1=đúng nhưng giải thích sai HOẶC sai đáp án nhưng tinh thần đúng;"
        " 0=sai cả hai HOẶC từ chối.\n"
        "3. Verdict: pass (score≥2) | fail | refused | uncertain.\n"
        "4. Rationale 1-3 câu tiếng Việt.\n\n"
        'OUTPUT JSON: {"mapped":"A|B|C|D|refused|uncertain","score":<0|1|2>,"verdict":"...","rationale":"..."}'
    )


async def judge_mcq(*, case, agent_output: str, model: str = JUDGE_MODEL) -> JudgeResult:
    key = _cache_key(case.case_id, agent_output, model, "mcq")
    if hit := _cache_get(key):
        return _result_from_cache(hit)
    user = _build_mcq_user(case, agent_output)
    raw, parsed = await _call_with_retry(model, _MCQ_PROMPT, user)
    if parsed is None:
        return JudgeResult(verdict="judge_error", score_max=case.points, raw_response=raw)
    mapped = parsed.get("mapped", "")
    score_int = int(parsed.get("score", 0))
    ratio = score_int / 2.0
    result = JudgeResult(
        mapped=mapped,
        score=case.points * ratio,
        score_max=case.points,
        verdict=parsed.get("verdict", "fail"),
        rationale=parsed.get("rationale", ""),
        raw_response=raw,
    )
    _cache_put(key, _result_to_cacheable(result))
    return result


# ── P2 Essay rubric ───────────────────────────────────────────────────────────

_ESSAY_PROMPT = """Bạn là giám khảo chấm tự luận tình huống môi giới BĐS theo rubric 5 tiêu chí × 4 điểm.
Chấm khách quan, dựa trên checkpoints rubric đã cho. Trả JSON đúng schema."""


def _build_essay_user(case, transcript_text: str) -> str:
    rubric_lines = "\n".join(f"Turn {i + 1} expects: {', '.join(cp)}" for i, cp in enumerate(case.rubric_checkpoints))
    key_answers = "\n".join(f"  {k}: {v}" for k, v in case.key_answers.items())
    return (
        f"[BỐI CẢNH CASE]\n{case.case_text}\n\n"
        f"[CÁC LƯỢT ĐỐI THOẠI]\n{transcript_text}\n\n"
        f"[CHECKPOINTS RUBRIC]\n{rubric_lines}\n\n"
        f"[KEY ANSWERS]\n{key_answers}\n\n"
        f"{case.judge_extras}\n\n"
        "NHIỆM VỤ: chấm 5 tiêu chí mỗi 0-4:\n"
        "T1 Hiểu đề | T2 Pháp luật (Điều/Khoản) | T3 Tính toán | T4 Giải pháp | T5 Giao tiếp\n"
        "Threshold: pass≥14, needs_human_review: 10≤total<14, fail<10.\n"
        'OUTPUT JSON: {"scores":{"T1":N,"T2":N,"T3":N,"T4":N,"T5":N},"total":N,"verdict":"pass|fail",'
        '"checkpoints_hit":[...],"checkpoints_missed":[...],"rationale":"...","needs_human_review":bool}'
    )


def _verdict_from_total(total: float) -> str:
    return "pass" if total >= 14 else "fail"


async def judge_essay(*, case, transcript_text: str, model: str = JUDGE_MODEL) -> JudgeResult:
    key = _cache_key(case.case_id, transcript_text, model, "essay")
    if hit := _cache_get(key):
        return _result_from_cache(hit)
    user = _build_essay_user(case, transcript_text)
    raw, parsed = await _call_with_retry(model, _ESSAY_PROMPT, user)
    if parsed is None:
        return JudgeResult(verdict="judge_error", score_max=case.points, raw_response=raw)
    total = float(parsed.get("total", 0))
    result = JudgeResult(
        score=total,
        score_max=case.points,
        verdict=_verdict_from_total(total),
        rationale=parsed.get("rationale", ""),
        rubric_breakdown={k: float(v) for k, v in parsed.get("scores", {}).items()},
        needs_human_review=bool(parsed.get("needs_human_review", False)) or (10 <= total < 14),
        raw_response=raw,
    )
    _cache_put(key, _result_to_cacheable(result))
    return result


# ── P3 Sales rubric ───────────────────────────────────────────────────────────

_SALES_PROMPT = """Bạn là sales coach BĐS Việt Nam, đánh giá kỹ năng sale qua mẫu hội thoại.
Chấm khách quan theo rubric 5 tiêu chí × 4 điểm. Trả JSON đúng schema."""


def _build_sales_user(case, transcript_text: str) -> str:
    rubric_lines = "\n".join(
        f"Sale-turn {i + 1} expects: {', '.join(cp)}" for i, cp in enumerate(case.rubric_checkpoints)
    )
    return (
        f"[BỐI CẢNH KỊCH BẢN]\n{case.title} — {case.setup}\n\n"
        f"[ĐỐI THOẠI]\n{transcript_text}\n\n"
        f"[CHECKPOINTS RUBRIC]\n{rubric_lines}\n\n"
        f"{case.judge_extras}\n\n"
        "NHIỆM VỤ: chấm 5 tiêu chí Sale rubric 0-4:\n"
        "M1 Mở đầu & rapport | M2 SPIN khai thác nhu cầu | M3 Trình bày FAB+data"
        " | M4 Xử lý từ chối HEAR-D | M5 Chốt + nextstep\n"
        "Threshold: pass≥14, needs_human_review: 10≤total<14, fail<10.\n"
        'OUTPUT JSON: {"scores":{"M1":N,"M2":N,"M3":N,"M4":N,"M5":N},"total":N,"verdict":"pass|fail",'
        '"checkpoints_hit":[...],"checkpoints_missed":[...],"rationale":"...","needs_human_review":bool}'
    )


async def judge_sales(*, case, transcript_text: str, model: str = JUDGE_MODEL) -> JudgeResult:
    key = _cache_key(case.case_id, transcript_text, model, "sales")
    if hit := _cache_get(key):
        return _result_from_cache(hit)
    user = _build_sales_user(case, transcript_text)
    raw, parsed = await _call_with_retry(model, _SALES_PROMPT, user)
    if parsed is None:
        return JudgeResult(verdict="judge_error", score_max=case.points, raw_response=raw)
    total = float(parsed.get("total", 0))
    result = JudgeResult(
        score=total,
        score_max=case.points,
        verdict=_verdict_from_total(total),
        rationale=parsed.get("rationale", ""),
        rubric_breakdown={k: float(v) for k, v in parsed.get("scores", {}).items()},
        needs_human_review=bool(parsed.get("needs_human_review", False)) or (10 <= total < 14),
        raw_response=raw,
    )
    _cache_put(key, _result_to_cacheable(result))
    return result
