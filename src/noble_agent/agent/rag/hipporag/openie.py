"""OpenIE triple extraction for the HippoRAG graph (BUILD-TIME ONLY).

``parse_triples`` is a pure, defensive JSON parser (tolerates code fences, prose
wrappers, and an object with a ``triples`` key) that never raises — malformed
output degrades to ``[]``. ``extract`` wraps it around an injected async
completion function so the builder and the tests can share one code path.

This module is never imported on the query hot path.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("rag.hipporag.openie")

Triple = tuple[str, str, str]

_PROMPT = """Bạn là bộ trích xuất tri thức cho tư vấn bất động sản.
Trích các bộ ba (chủ thể, quan hệ, đối tượng) từ đoạn văn dưới đây.
Chủ thể/đối tượng là thực thể ngắn gọn (tên dự án, khu vực, tiện ích, loại căn,
khoảng giá, chủ đầu tư…). Quan hệ là một cụm động từ ngắn tiếng Việt.
CHỈ trả về một mảng JSON các mảng 3 phần tử, KHÔNG giải thích.

Ví dụ: [["Noble Crystal","ở","Tây Hồ"],["Noble Crystal","có","bể bơi"]]

Đoạn văn:
\"\"\"
{chunk}
\"\"\"
"""

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_prompt(chunk_text: str) -> str:
    return _PROMPT.format(chunk=chunk_text or "")


def _coerce_rows(data) -> list[Triple]:
    if isinstance(data, dict):
        data = data.get("triples") or data.get("results") or []
    if not isinstance(data, list):
        return []
    out: list[Triple] = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        subj, rel, obj = (str(row[0]).strip(), str(row[1]).strip(), str(row[2]).strip())
        if not subj or not obj:
            continue
        out.append((subj, rel, obj))
    return out


def parse_triples(text: str | None) -> list[Triple]:
    """Best-effort parse of an LLM OpenIE response into triples. Never raises."""
    if not text:
        return []
    text = text.strip()

    # 1) fenced block first
    m = _FENCE.search(text)
    candidates = [m.group(1).strip()] if m else []
    candidates.append(text)
    # 2) first bracketed span (array or object)
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            candidates.append(text[i : j + 1])

    for cand in candidates:
        try:
            return _coerce_rows(json.loads(cand))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return []


async def extract(chunk_text: str, complete_fn) -> list[Triple]:
    """Run OpenIE on one chunk. ``complete_fn`` is an async ``str -> str`` LLM
    call. Any error / unparsable output → ``[]`` (the chunk contributes no
    edges but never breaks the build)."""
    try:
        raw = await complete_fn(build_prompt(chunk_text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.openie] extract failed: %s", exc)
        return []
    return parse_triples(raw)
