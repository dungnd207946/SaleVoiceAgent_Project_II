"""One-time: convert Section A and D MCQ → natural customer questions.

Run:  python -m tests.bench_estate.scripts.convert_mcq_to_roleplay

Reads: docs/estate_cert/{BO_DE_AI_AGENT_DATASET.json, DE_THI_NHAN_VIEN.md}
Writes: tests/bench_estate/data/personas_mcq/{A,D}_questions.json
Skips: questions already cached (hash-keyed by question text).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from tests.bench_estate.loader import _load_json_dataset, _load_md_questions

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tests" / "bench_estate" / "data" / "personas_mcq"
DATASET_JSON = REPO_ROOT / "docs" / "estate_cert" / "BO_DE_AI_AGENT_DATASET.json"
QUESTIONS_MD = REPO_ROOT / "docs" / "estate_cert" / "DE_THI_NHAN_VIEN.md"

MODEL = os.getenv("ESTATE_CONVERT_MODEL", "gpt-5.4-nano-2026-03-17")

PROMPT = """Bạn là người soạn câu hỏi kiểm tra. Chuyển MCQ pháp lý/đạo đức BĐS
thành câu hỏi 1 câu mà KHÁCH THẬT có thể hỏi sale qua điện thoại.
Giọng tự nhiên tiếng Việt. KHÔNG được leak 4 đáp án A/B/C/D.
Trả về JSON: {"roleplay_question": "..."}"""


async def convert_one(client: AsyncOpenAI, mcq_text: str, choices: dict[str, str]) -> str:
    user = f"[MCQ]\n{mcq_text}\n\n"
    for k, v in choices.items():
        user += f"{k}. {v}\n"
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    data = json.loads(resp.choices[0].message.content)
    return data["roleplay_question"]


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


async def convert_section(section: str, json_questions: list[dict], md_questions: dict[int, dict]):
    out_path = OUT_DIR / f"{section}_questions.json"
    cache: dict[str, dict] = {}
    if out_path.exists():
        cache = {item["case_id"]: item for item in json.loads(out_path.read_text())}

    client = AsyncOpenAI()
    for q in json_questions:
        case_id = f"{section}-{q['id']}"
        md = md_questions.get(q["id"])
        if not md:
            print(f"  [skip] {case_id} — no MD entry")
            continue
        h = _hash(md["question"])
        if (cached := cache.get(case_id)) and cached.get("hash") == h:
            print(f"  [cache] {case_id}")
            continue
        try:
            rp = await convert_one(client, md["question"], md["choices"])
            cache[case_id] = {"case_id": case_id, "hash": h, "roleplay_question": rp}
            print(f"  [done] {case_id}: {rp[:60]}...")
        except Exception as e:
            print(f"  [fail] {case_id}: {e}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(list(cache.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"→ wrote {out_path} ({len(cache)} entries)")


async def main():
    sections = _load_json_dataset(DATASET_JSON)
    md = _load_md_questions(QUESTIONS_MD)
    for sec in ("A", "D"):
        await convert_section(sec, sections[sec], md)


if __name__ == "__main__":
    asyncio.run(main())
