"""SQL của `tenant_data.data_conflicts`. Mọi câu chạy trong `tenant_conn()` của caller."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from portal.modules.kb.conflicts.facts import ordered

KIND_CONFLICT_CHECK = "kb_conflict_check"
_CHAIN_KINDS = ["kb_index", "kb_thumb", "kb_enrich", "kb_caption", KIND_CONFLICT_CHECK]
_CACH_LY = "tenant_id = portal.current_tenant()"


@dataclass(frozen=True)
class Side:
    entity: str | None
    record_id: int | None
    field: str | None
    label: str
    quote: str


@dataclass(frozen=True)
class Row:
    project_code: str
    left_hash: str
    right_hash: str
    status: str
    summary: str = ""
    left: Side | None = None
    right: Side | None = None


async def judged_pairs(conn: asyncpg.Connection, pairs: Collection[tuple[str, str]]) -> set[tuple[str, str]]:
    keys = {ordered(a, b) for a, b in pairs}
    if not keys:
        return set()
    lefts, rights = zip(*keys, strict=True)
    rows = await conn.fetch(
        f"""SELECT d.left_hash, d.right_hash FROM tenant_data.data_conflicts d
             JOIN unnest($1::text[], $2::text[]) AS k(l, r) ON (d.left_hash, d.right_hash) = (k.l, k.r)
            WHERE d.{_CACH_LY}""",
        list(lefts),
        list(rights),
    )
    return {(r["left_hash"], r["right_hash"]) for r in rows}


def _cols(side: Side | None) -> tuple:
    if side is None:
        return (None, None, None, None, None)
    return (side.entity, side.record_id, side.field, side.label, side.quote)


async def insert_rows(conn: asyncpg.Connection, rows: list[Row]) -> int:
    """Cặp đã có hàng thì giữ nguyên — `dismissed` không bao giờ bị mở lại. Trả số hàng `open` ghi được."""
    opened = 0
    for row in rows:
        left, right, a, b = row.left, row.right, row.left_hash, row.right_hash
        if (a, b) != ordered(a, b):
            left, right, a, b = right, left, b, a
        status = await conn.fetchval(
            """INSERT INTO tenant_data.data_conflicts
                  (tenant_id, project_code, left_hash, right_hash, status, summary,
                   left_entity, left_record_id, left_field, left_label, left_quote,
                   right_entity, right_record_id, right_field, right_label, right_quote)
                VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                ON CONFLICT (tenant_id, left_hash, right_hash) DO NOTHING
                RETURNING status""",
            row.project_code,
            a,
            b,
            row.status,
            row.summary,
            *_cols(left),
            *_cols(right),
        )
        opened += status == "open"
    return opened


async def resolve_stale(conn: asyncpg.Connection, project_code: str, current: set[str]) -> int:
    res = await conn.execute(
        f"""UPDATE tenant_data.data_conflicts SET status = 'resolved', resolved_at = now()
             WHERE {_CACH_LY} AND project_code = $1 AND status = 'open'
               AND NOT (left_hash = ANY($2::text[]) AND right_hash = ANY($2::text[]))""",
        project_code,
        list(current),
    )
    return int(res.split()[-1])


async def drop_stale_none(conn: asyncpg.Connection, project_code: str, current: set[str]) -> int:
    res = await conn.execute(
        f"""DELETE FROM tenant_data.data_conflicts
             WHERE {_CACH_LY} AND project_code = $1 AND status = 'none'
               AND NOT (left_hash = ANY($2::text[]) AND right_hash = ANY($2::text[]))""",
        project_code,
        list(current),
    )
    return int(res.split()[-1])


async def list_open(conn: asyncpg.Connection, project_code: str, since: datetime | None = None) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT * FROM tenant_data.data_conflicts
             WHERE {_CACH_LY} AND project_code = $1 AND status = 'open'
               AND ($2::timestamptz IS NULL OR created_at > $2)
             ORDER BY created_at DESC, id DESC""",
        project_code,
        since,
    )


SYSTEM_PROJECT = "__ALL__"


async def summary(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Mọi dự án kèm số cảnh báo `open` và lượt dò gần nhất. `control.jobs` không RLS nên lọc tenant tường minh."""
    return await conn.fetch(
        f"""WITH o AS (
              SELECT project_code, count(*) AS n FROM tenant_data.data_conflicts
               WHERE {_CACH_LY} AND status = 'open' GROUP BY project_code
            ), j AS (
              SELECT DISTINCT ON (payload->>'project_code') payload->>'project_code' AS project_code,
                     state, finished_at
                FROM control.jobs
               WHERE {_CACH_LY} AND kind = $1 AND state IN ('success', 'failed')
               ORDER BY payload->>'project_code', id DESC
            ), r AS (
              SELECT DISTINCT payload->>'project_code' AS project_code FROM control.jobs
               WHERE {_CACH_LY} AND kind = $1 AND state IN ('queued', 'running')
            )
            SELECT p.project_code, p.name, coalesce(o.n, 0)::int AS open,
                   (r.project_code IS NOT NULL) AS checking, coalesce(j.state = 'failed', false) AS failed,
                   j.finished_at AS checked_at
              FROM tenant_data.projects p
              LEFT JOIN o ON o.project_code = p.project_code
              LEFT JOIN j ON j.project_code = p.project_code
              LEFT JOIN r ON r.project_code = p.project_code
             WHERE p.{_CACH_LY} AND p.project_code <> $2
             ORDER BY coalesce(o.n, 0) DESC, p.name""",
        KIND_CONFLICT_CHECK,
        SYSTEM_PROJECT,
    )


async def check_status(conn: asyncpg.Connection, project_code: str) -> tuple[bool, bool, datetime | None]:
    """(còn job nạp/dò chưa xong, lượt dò xong gần nhất hỏng, lúc nó xong)."""
    row = await conn.fetchrow(
        f"""SELECT
              EXISTS (SELECT 1 FROM control.jobs WHERE {_CACH_LY} AND kind = ANY($2::text[])
                         AND state IN ('queued', 'running') AND payload->>'project_code' = $1) AS checking,
              j.state = 'failed' AS failed, j.finished_at
              FROM (SELECT 1) one
              LEFT JOIN LATERAL (
                SELECT state, finished_at FROM control.jobs
                 WHERE {_CACH_LY} AND kind = $3 AND state IN ('success', 'failed') AND payload->>'project_code' = $1
                 ORDER BY id DESC LIMIT 1
              ) j ON true""",
        project_code,
        _CHAIN_KINDS,
        KIND_CONFLICT_CHECK,
    )
    return bool(row["checking"]), bool(row["failed"]), row["finished_at"]


async def dismiss(conn: asyncpg.Connection, conflict_id: int, user_id: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""UPDATE tenant_data.data_conflicts SET status = 'dismissed', dismissed_at = now(), dismissed_by = $2
             WHERE {_CACH_LY} AND id = $1 AND status = 'open' RETURNING id, project_code""",
        conflict_id,
        user_id,
    )
