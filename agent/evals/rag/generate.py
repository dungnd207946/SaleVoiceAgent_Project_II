"""Generation stage cô lập cho RAG eval (spec §7.3) — KHÔNG qua agent.

Generator: prompt cố định "chỉ trả lời từ các đoạn sau"; đo faithfulness
(answer sinh ra vs chunks) + answer correctness (vs golden.answer) bằng judge.
Mọi call qua evals.judge_client (cache/budget dùng chung).

rag_refusal_rate: generator từ chối trong khi retrieval CÓ hit — tín hiệu
generator/prompt kém hoặc chunk đúng nhưng không chứa câu trả lời (golden sai).
"""

from __future__ import annotations

import logging
import os

from evals import judge_client
from evals.rag.golden import GoldenCase

logger = logging.getLogger("evals.rag.generate")

REFUSAL_MARKER = "không tìm thấy thông tin"
GEN_MODEL_ENV = "EVAL_RAG_GEN_MODEL"
_RUBRIC_V = "v1"

_GEN_SYSTEM = (
    "Bạn là trợ lý trả lời câu hỏi CHỈ dựa trên các đoạn văn được cung cấp.\n"
    "Không suy diễn, không dùng kiến thức ngoài. Nếu các đoạn không chứa câu "
    "trả lời, trả lời đúng một câu: 'Tôi không tìm thấy thông tin này.'"
)

_FAITH_SYSTEM = (
    "Bạn là giám khảo kiểm tra câu trả lời có được ĐỠ hoàn toàn bởi các đoạn văn nguồn không.\n"
    "Trả JSON đúng schema, không thêm prose."
)

_CORRECT_SYSTEM = (
    "Bạn là giám khảo chấm độ đúng của câu trả lời so với đáp án chuẩn.\n"
    "Trả JSON đúng schema, không thêm prose."
)


def gen_model() -> str:
    return os.getenv(GEN_MODEL_ENV) or judge_client.JUDGE_MODEL


def _chunks_block(retrieved: list[str]) -> str:
    return "\n---\n".join(f"[ĐOẠN {i + 1}]\n{t}" for i, t in enumerate(retrieved))


async def _generate(query: str, retrieved: list[str], model: str) -> str:
    user = f"{_chunks_block(retrieved)}\n\n[CÂU HỎI]\n{query}"
    return await judge_client.call_llm(model, _GEN_SYSTEM, user, json_mode=False, max_tokens=500)


async def _judge_faithful(case_id: str, answer: str, retrieved: list[str], model: str) -> dict | None:
    user = (
        f"{_chunks_block(retrieved)}\n\n[CÂU TRẢ LỜI CẦN KIỂM]\n{answer}\n\n"
        'OUTPUT JSON: {"faithful": true|false, "unsupported_claims": ["..."], "rationale": "..."}'
    )
    return await _judged(case_id, "faith", _FAITH_SYSTEM, user, model)


async def _judge_correct(case_id: str, answer: str, golden_answer: str, model: str) -> dict | None:
    user = (
        f"[ĐÁP ÁN CHUẨN]\n{golden_answer}\n\n[CÂU TRẢ LỜI CẦN CHẤM]\n{answer}\n\n"
        'OUTPUT JSON: {"correct": 0.0..1.0, "rationale": "..."}'
    )
    return await _judged(case_id, "correct", _CORRECT_SYSTEM, user, model)


async def _judged(case_id: str, rubric: str, system: str, user: str, model: str) -> dict | None:
    key = judge_client.cache_key("rag", rubric, _RUBRIC_V, case_id, user, model)
    if hit := judge_client.cache_get(key):
        return hit
    try:
        _raw, parsed = await judge_client.call_llm_json(model, system, user)
    except judge_client.BudgetExceeded:
        return None
    except Exception as e:  # noqa: BLE001 — lỗi transient không sập cả stage
        logger.warning("rag judge %s error for %s: %s", rubric, case_id, e)
        return None
    if parsed is not None:
        judge_client.cache_put(key, parsed)
    return parsed


async def run_generation(golden: list[GoldenCase], rows: list[dict], *, model: str) -> dict:
    row_by_id = {r["id"]: r for r in rows}
    out_rows: list[dict] = []
    eligible = graded = 0
    faithfuls: list[float] = []
    corrects: list[float] = []
    refusals: list[float] = []
    skipped_no_answer = 0

    for case in golden:
        row = row_by_id.get(case.id)
        if not case.answer:
            skipped_no_answer += 1
            continue
        if not row or not row.get("retrieved"):
            continue
        eligible += 1
        retrieved = list(row["retrieved"])
        try:
            gen_answer = await _generate(case.query, retrieved, model)
        except Exception as e:  # noqa: BLE001
            out_rows.append({"id": case.id, "gen_answer": "", "error": f"{type(e).__name__}: {e}"})
            continue

        refused = REFUSAL_MARKER in gen_answer.lower()
        if refused and row.get("hit"):
            refusals.append(1.0)
        else:
            refusals.append(0.0)

        faith = await _judge_faithful(case.id, gen_answer, retrieved, model)
        correct = await _judge_correct(case.id, gen_answer, case.answer, model)
        if faith is None or correct is None:
            out_rows.append({"id": case.id, "gen_answer": gen_answer, "refused": refused, "error": "judge_ungraded"})
            continue
        graded += 1
        faithfuls.append(1.0 if faith.get("faithful") else 0.0)
        try:
            corrects.append(max(0.0, min(1.0, float(correct.get("correct", 0.0)))))
        except (TypeError, ValueError):
            corrects.append(0.0)
        out_rows.append({
            "id": case.id, "gen_answer": gen_answer, "refused": refused,
            "faithful": bool(faith.get("faithful")), "correctness": corrects[-1], "error": "",
        })

    if skipped_no_answer:
        print(f"generation: bỏ qua {skipped_no_answer} case không có golden answer")
    return {
        "rows": out_rows,
        "metrics": {
            "faithfulness_rate": (sum(faithfuls) / len(faithfuls)) if faithfuls else None,
            "rag_answer_correctness_mean": (sum(corrects) / len(corrects)) if corrects else None,
            "rag_refusal_rate": (sum(refusals) / len(refusals)) if refusals else None,
            "generation_coverage": (graded / eligible) if eligible else None,
        },
    }
