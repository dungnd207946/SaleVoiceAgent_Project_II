"""Golden set retrieval v2: nhiều chunk vàng + golden answer (spec §7.1).

`evidence` phải NGUYÊN VĂN từ chunk — matcher normalized substring. `chunk_id`
ưu tiên khi backend trả id. Loader từ chối mọi dòng không 'approved'.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KEYS = {"id", "tenant", "query", "golden_chunks", "answer", "project_code", "status"}
_CHUNK_KEYS = {"chunk_id", "evidence"}


@dataclass(frozen=True)
class GoldenChunk:
    chunk_id: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class GoldenCase:
    id: str
    tenant: str
    query: str
    chunks: tuple[GoldenChunk, ...]
    answer: str = ""
    project_code: str = ""
    status: str = "draft"


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def parse_golden(data: dict, *, source: str) -> GoldenCase:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: golden case must be a mapping")
    unknown = set(data) - _KEYS
    if unknown:
        raise ValueError(f"{source}: unknown golden keys {sorted(unknown)} (schema v2 — 'evidence' → 'golden_chunks')")
    for key in ("id", "tenant", "query"):
        if not data.get(key) or not isinstance(data[key], str):
            raise ValueError(f"{source}: needs a non-empty string {key!r}")
    raw_chunks = data.get("golden_chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError(f"{source}: needs a non-empty 'golden_chunks' list")
    chunks: list[GoldenChunk] = []
    for i, rc in enumerate(raw_chunks):
        if not isinstance(rc, dict) or set(rc) - _CHUNK_KEYS:
            raise ValueError(f"{source}: golden_chunks[{i}] must be a mapping with keys {sorted(_CHUNK_KEYS)}")
        chunk = GoldenChunk(chunk_id=str(rc.get("chunk_id", "") or ""), evidence=str(rc.get("evidence", "") or ""))
        if not chunk.chunk_id and not chunk.evidence:
            raise ValueError(f"{source}: golden_chunks[{i}] needs chunk_id or evidence")
        chunks.append(chunk)
    return GoldenCase(
        id=data["id"], tenant=data["tenant"], query=data["query"], chunks=tuple(chunks),
        answer=str(data.get("answer", "") or ""),
        project_code=str(data.get("project_code", "") or ""),
        status=str(data.get("status", "draft") or "draft"),
    )


def load_golden(path: Path) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            case = parse_golden(json.loads(line), source=f"{path.name}:{lineno}")
            if case.status != "approved":
                raise ValueError(
                    f"{path.name}:{lineno}: case {case.id!r} has status {case.status!r} — "
                    "runner chỉ nhận file toàn 'approved' (duyệt bằng labeller trước)"
                )
            out.append(case)
    return out


def ranks_of(case: GoldenCase, hits: list[dict]) -> list[int | None]:
    """Rank của TỪNG golden chunk trong hits. Greedy theo rank — mỗi hit match
    tối đa một golden chunk (chunk_id trước, evidence-substring sau) để
    context_recall không double-count."""
    remaining = list(enumerate(case.chunks))
    ranks: dict[int, int] = {}
    for rank, hit in enumerate(hits):
        hit_id = str(hit.get("id", ""))
        hit_text = _norm(str(hit.get("text", "")))
        for j, (ci, chunk) in enumerate(remaining):
            id_match = chunk.chunk_id and hit_id == chunk.chunk_id
            ev_match = chunk.evidence and _norm(chunk.evidence) in hit_text
            if id_match or ev_match:
                ranks[ci] = rank
                remaining.pop(j)
                break
    return [ranks.get(i) for i in range(len(case.chunks))]
