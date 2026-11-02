"""Sinh golden set DRAFT từ corpus Qdrant (read-only) — user duyệt tay rồi mới approved (spec §6).

Mỗi case sinh ra gắn với ĐÚNG MỘT chunk (schema v2 `golden_chunks` chỉ có 1 phần tử).
Không làm `--multi-chunk` đợt này — case nhiều chunk vàng tạo tay qua labeller.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_SYSTEM = """Bạn tạo bộ kiểm thử retrieval cho trợ lý BĐS tiếng Việt.
Với đoạn văn cho trước, sinh câu hỏi tự nhiên theo văn phong TRUY VẤN TÌM KIẾM
(ngắn gọn, như query gõ vào ô search — không phải câu chuyện dài dòng),
kèm câu trả lời đúng rút từ đoạn văn.
'evidence' PHẢI là một câu TRÍCH NGUYÊN VĂN (copy đúng từng ký tự) từ đoạn văn.
'answer' là câu trả lời chuẩn, ngắn gọn, chỉ dùng thông tin trong đoạn văn.
Trả JSON đúng schema."""


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


async def _call_llm(model: str, system: str, user: str) -> str:
    """Patched in tests.

    Endpoint OpenAI-compat cấu hình được (vd. DashScope cho qwen):
    EVAL_GOLDEN_BASE_URL/_API_KEY, rơi về EVAL_JUDGE_BASE_URL/_API_KEY (đặt một lần
    cho cả judge lẫn gen-golden), rỗng → SDK dùng OPENAI_* như cũ. Model qwen3.x
    bật thinking mặc định → reasoning ăn hết max tokens làm content rỗng, nên tắt
    (chỉ gửi enable_thinking cho model qwen — endpoint OpenAI từ chối param lạ).
    """
    from openai import AsyncOpenAI  # noqa: PLC0415

    base_url = os.getenv("EVAL_GOLDEN_BASE_URL") or os.getenv("EVAL_JUDGE_BASE_URL") or None
    api_key = os.getenv("EVAL_GOLDEN_API_KEY") or os.getenv("EVAL_JUDGE_API_KEY") or None
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    extra = {"extra_body": {"enable_thinking": False}} if model.startswith("qwen") else {}
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0, max_completion_tokens=600, response_format={"type": "json_object"},
        **extra,
    )
    return resp.choices[0].message.content or ""


async def gen_questions(chunk: dict, *, model: str, n: int = 2) -> list[dict]:
    user = (
        f"[ĐOẠN VĂN]\n{chunk['text']}\n\n"
        f"Sinh tối đa {n} cặp câu hỏi. "
        'OUTPUT JSON: {"pairs": [{"query": "...", "evidence": "...", "answer": "..."}]}'
    )
    raw = await _call_llm(model, _SYSTEM, user)
    try:
        pairs = json.loads(raw).get("pairs") or []
    except ValueError:
        return []
    text_norm = _norm(chunk["text"])
    # LLM bịa evidence = case rác: chỉ giữ cặp evidence nằm nguyên văn trong chunk, có answer.
    return [p for p in pairs[:n]
            if isinstance(p, dict) and p.get("query") and p.get("evidence") and p.get("answer")
            and _norm(p["evidence"]) in text_norm]


async def fetch_chunks(*, tenant: str, limit: int) -> list[dict]:
    from qdrant_client import AsyncQdrantClient  # noqa: PLC0415

    from noble_agent.config import settings  # noqa: PLC0415

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    points, _next = await client.scroll(
        collection_name=f"{tenant}_documents", limit=limit, with_payload=True, with_vectors=False)
    out = []
    for pt in points:
        payload = pt.payload or {}
        text = (payload.get("text") or "").strip()
        if text:
            out.append({"id": str(pt.id), "text": text, "project_code": str(payload.get("project_id", "") or "")})
    return out


def write_draft(cases: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps({**c, "status": "draft"}, ensure_ascii=False) + "\n")


def draft_path(tenant: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "data" / "golden" / tenant / f"draft-{stamp}.jsonl"


def default_model() -> str:
    return os.getenv("EVAL_GOLDEN_MODEL",
                     os.getenv("EVAL_JUDGE_MODEL", os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17")))
