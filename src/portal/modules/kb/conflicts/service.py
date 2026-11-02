"""Một lượt dò mâu thuẫn (spec §4.3). Chạy trong `tenant_conn()` của job."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import asyncpg

from portal.modules.kb.conflicts import repo, settings
from portal.modules.kb.conflicts.facts import (
    chunk_hash,
    has_checkable_fact,
    ordered,
    quote_found,
    same_kind,
    strip_label,
    value_in_quote,
    value_kind,
)
from portal.modules.kb.conflicts.fields import FieldValue, fields_block_hash, load_fields, render_block
from portal.modules.kb.conflicts.llm import PROFILE, Finding, Item, build_user_text, parse_findings
from portal.modules.kb.conflicts.repo import Row, Side
from portal.modules.kb.index.store import QdrantStore, VectorPoint
from portal.modules.kb.web.llm import TruncatedLlmError

log = logging.getLogger(__name__)

_CACH_LY = "tenant_id = portal.current_tenant()"


class Asker(Protocol):
    async def ask(self, profile: str, user_text: str) -> dict: ...


@dataclass
class CheckResult:
    calls: int = 0
    opened: int = 0
    resolved: int = 0

    def add(self, other: "CheckResult") -> None:
        self.calls += other.calls
        self.opened += other.opened
        self.resolved += other.resolved


@dataclass
class _Work:
    point: VectorPoint
    hash: str
    cands: list[VectorPoint] = field(default_factory=list)
    with_fields: bool = False


@dataclass
class _Project:
    code: str
    fields: list[FieldValue]
    block: str
    block_hash: str
    doc_points: list[VectorPoint]
    titles: dict[int, str]


async def _load_project(conn, store: QdrantStore, collection: str, project_code: str) -> _Project:
    fields = await load_fields(conn, project_code)
    rows = await conn.fetch(
        f"SELECT id, title FROM tenant_data.documents WHERE {_CACH_LY} AND project_code = $1", project_code
    )
    return _Project(
        code=project_code,
        fields=fields,
        block=render_block(fields),
        block_hash=fields_block_hash(fields),
        doc_points=await store.points_with_vectors(collection, anchor_code=project_code, doc_types=settings.DOC_TYPES),
        titles={int(r["id"]): str(r["title"] or "") for r in rows},
    )


def _current_hashes(p: _Project) -> set[str]:
    return {chunk_hash(pt.text) for pt in p.doc_points} | {f.hash for f in p.fields} | {p.block_hash}


async def _ask(llm: Asker, text: str, valid: set[str]) -> list[Finding]:
    return parse_findings(await llm.ask(PROFILE, text), valid_refs=valid)


async def _judge(llm: Asker, p: _Project, batch: list[_Work], result: CheckResult) -> list[tuple[_Work, Finding]]:
    """Gọi LLM cho một nhóm. JSON hỏng: chia đôi rồi thử lại một lần; vẫn hỏng thì ném."""
    try:
        return await _judge_once(llm, p, batch, result)
    except (ValueError, TruncatedLlmError):
        if len(batch) == 1:
            return await _judge_once(llm, p, batch, result)
        half = len(batch) // 2
        return [*await _judge_once(llm, p, batch[:half], result), *await _judge_once(llm, p, batch[half:], result)]


async def _judge_once(llm: Asker, p: _Project, batch: list[_Work], result: CheckResult) -> list[tuple[_Work, Finding]]:
    d_ref = {f"D{i + 1}": w for i, w in enumerate(batch)}
    cands: dict[str, VectorPoint] = {}
    for w in batch:
        for c in w.cands:
            cands.setdefault(c.point_id, c)
    c_ref = {f"C{i + 1}": c for i, c in enumerate(cands.values())}
    by_point = {c.point_id: ref for ref, c in c_ref.items()}
    field_refs = {f.ref for f in p.fields} if any(w.with_fields for w in batch) else set()
    text = build_user_text(
        p.block,
        [Item(ref, _label(p, w.point), w.point.text) for ref, w in d_ref.items()],
        [Item(ref, _label(p, c), c.text) for ref, c in c_ref.items()],
    )
    result.calls += 1
    findings = await _ask(llm, text, set(d_ref) | set(c_ref) | field_refs)
    out: list[tuple[_Work, Finding]] = []
    for f in findings:
        w = d_ref[f.left_ref]
        right_value = f.right_value
        if f.right_ref.startswith("C"):
            if f.right_ref not in {by_point[c.point_id] for c in w.cands}:
                continue
            source = c_ref[f.right_ref].text
        else:
            if not w.with_fields:
                continue
            fv = next(x for x in p.fields if x.ref == f.right_ref)
            source = f"{fv.label}: {fv.value}"
            # Đơn vị của trường hay nằm ở nhãn: «Phí quản lý (đồng/m²/tháng)».
            if value_kind(right_value) is None:
                right_value = f"{right_value} {fv.label}"
        if not (quote_found(f.left_quote, w.point.text) and quote_found(f.right_quote, source)):
            log.info("bỏ mâu thuẫn có trích dẫn không khớp nguồn: %s", f.summary)
            continue
        if not (value_in_quote(f.left_value, f.left_quote) and value_in_quote(f.right_value, f.right_quote)):
            log.info("bỏ mâu thuẫn có câu trích không chứa giá trị: %s %r ↔ %r", f.summary, f.left_value, f.right_value)
            continue
        if not same_kind(f.left_value, right_value):
            log.info("bỏ mâu thuẫn hai giá trị khác loại đại lượng: %s", f.summary)
            continue
        log.info("giữ mâu thuẫn %s: %r ↔ %r", f.attribute, f.left_value, f.right_value)
        # Phía phải mang point_id (đoạn) hoặc mã trường, không còn mã C của riêng lượt gọi này.
        right = c_ref[f.right_ref].point_id if f.right_ref.startswith("C") else f.right_ref
        quote = f.right_quote if f.right_ref.startswith("C") else strip_label(f.right_quote, fv.label)
        out.append((w, replace(f, right_ref=right, right_quote=quote)))
    return out


def _label(p: _Project, pt: VectorPoint) -> str:
    return p.titles.get(pt.record_id) or "Tài liệu"


def _doc_side(p: _Project, pt: VectorPoint, quote: str) -> Side:
    return Side(entity="documents", record_id=pt.record_id, field=None, label=_label(p, pt), quote=quote)


def _rows(p: _Project, works: Sequence[_Work], found: list[tuple[_Work, Finding]]) -> list[Row]:
    by_work: dict[int, list[Finding]] = {}
    for w, f in found:
        by_work.setdefault(id(w), []).append(f)
    rows: list[Row] = []
    fields = {f.ref: f for f in p.fields}
    for w in works:
        mine = by_work.get(id(w), [])
        for c in w.cands:
            hit = next((f for f in mine if f.right_ref == c.point_id), None)
            ch = chunk_hash(c.text)
            if hit is None:
                rows.append(Row(p.code, w.hash, ch, "none"))
            else:
                rows.append(
                    Row(
                        p.code,
                        w.hash,
                        ch,
                        "open",
                        hit.summary,
                        _doc_side(p, w.point, hit.left_quote),
                        _doc_side(p, c, hit.right_quote),
                    )
                )
        if w.with_fields:
            rows.append(Row(p.code, w.hash, p.block_hash, "none"))
            seen: set[str] = set()
            for f in mine:
                fv = fields.get(f.right_ref)
                if fv is None or fv.ref in seen:
                    continue
                seen.add(fv.ref)
                rows.append(
                    Row(
                        p.code,
                        w.hash,
                        fv.hash,
                        "open",
                        f.summary,
                        _doc_side(p, w.point, f.left_quote),
                        Side(
                            entity=fv.entity,
                            record_id=fv.record_id,
                            field=fv.field,
                            label=fv.label,
                            quote=f.right_quote,
                        ),
                    )
                )
    return rows


async def _run(conn: asyncpg.Connection, llm: Asker, p: _Project, works: list[_Work]) -> CheckResult:
    result = CheckResult()
    pairs = [(w.hash, chunk_hash(c.text)) for w in works for c in w.cands]
    pairs += [(w.hash, p.block_hash) for w in works if w.with_fields]
    judged = await repo.judged_pairs(conn, pairs)
    todo: list[_Work] = []
    for w in works:
        w.cands = [c for c in w.cands if ordered(w.hash, chunk_hash(c.text)) not in judged]
        w.with_fields = w.with_fields and ordered(w.hash, p.block_hash) not in judged
        if w.cands or w.with_fields:
            todo.append(w)
    found: list[tuple[_Work, Finding]] = []
    for i in range(0, len(todo), settings.BATCH):
        found += await _judge(llm, p, todo[i : i + settings.BATCH], result)
    result.opened = await repo.insert_rows(conn, _rows(p, todo, found))
    return result


async def _doc_works(store: QdrantStore, collection: str, p: _Project, record_id: int) -> list[_Work]:
    works: list[_Work] = []
    for pt in p.doc_points:
        if pt.record_id != record_id or pt.vector is None or not has_checkable_fact(pt.text):
            continue
        hits = await store.similar(
            collection,
            vector=pt.vector,
            anchor_code=p.code,
            exclude_record_id=record_id,
            exclude_doc_types=settings.DOC_TYPES,
            doc_types=settings.DOC_TYPES | {settings.FIELD_ANCHOR},
            limit=settings.TOP_K,
            min_score=settings.MIN_SCORE,
        )
        cands = [h for h in hits if h.doc_type != settings.FIELD_ANCHOR and has_checkable_fact(h.text)]
        with_fields = bool(p.fields) and any(h.doc_type == settings.FIELD_ANCHOR for h in hits)
        if cands or with_fields:
            works.append(_Work(pt, chunk_hash(pt.text), cands, with_fields))
    return works


async def _field_works(store: QdrantStore, collection: str, p: _Project) -> list[_Work]:
    if not p.fields:
        return []
    anchors = await store.points_with_vectors(collection, anchor_code=p.code, doc_types={settings.FIELD_ANCHOR})
    picked: dict[str, VectorPoint] = {}
    for a in anchors:
        if a.vector is None:
            continue
        for h in await store.similar(
            collection,
            vector=a.vector,
            anchor_code=p.code,
            exclude_record_id=None,
            doc_types=settings.DOC_TYPES,
            limit=settings.TOP_K,
            min_score=settings.MIN_SCORE,
        ):
            if has_checkable_fact(h.text):
                picked.setdefault(h.point_id, h)
    return [_Work(pt, chunk_hash(pt.text), [], True) for pt in picked.values()]


async def check_record(
    conn: asyncpg.Connection,
    *,
    store: QdrantStore,
    llm: Asker,
    collection: str,
    project_code: str,
    entity: str,
    record_id: int,
) -> CheckResult:
    p = await _load_project(conn, store, collection, project_code)
    resolved = await repo.resolve_stale(conn, project_code, _current_hashes(p))
    if entity == "documents":
        works = await _doc_works(store, collection, p, record_id)
    else:
        works = await _field_works(store, collection, p)
    result = await _run(conn, llm, p, works)
    result.resolved = resolved
    return result


async def check_project(
    conn: asyncpg.Connection, *, store: QdrantStore, llm: Asker, collection: str, project_code: str
) -> CheckResult:
    p = await _load_project(conn, store, collection, project_code)
    current = _current_hashes(p)
    total = CheckResult(resolved=await repo.resolve_stale(conn, project_code, current))
    for record_id in sorted({pt.record_id for pt in p.doc_points}):
        total.add(await _run(conn, llm, p, await _doc_works(store, collection, p, record_id)))
    total.add(await _run(conn, llm, p, await _field_works(store, collection, p)))
    await repo.drop_stale_none(conn, project_code, current)
    return total
