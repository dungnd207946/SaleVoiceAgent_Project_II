"""Xếp job dò mâu thuẫn, gộp với job đang chờ để lưu liên tiếp chỉ ra một lượt dò."""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.conflicts.repo import KIND_CONFLICT_CHECK

_WAITING = """SELECT 1 FROM control.jobs
               WHERE tenant_id = portal.current_tenant() AND kind = $1 AND state = 'queued'
                 AND payload->>'project_code' = $2
                 AND (payload->>'entity' IS NULL
                      OR ($3::text IS NOT NULL AND payload->>'entity' = $3
                          AND (payload->>'record_id')::bigint = $4))
               LIMIT 1"""


async def queue_check(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    project_code: str,
    entity: str | None = None,
    record_id: int | None = None,
) -> int | None:
    """`entity=None` = cả dự án. Đã có job chờ phủ được việc này thì trả None."""
    if await conn.fetchval(_WAITING, KIND_CONFLICT_CHECK, project_code, entity, record_id):
        return None
    payload: dict = {"project_code": project_code}
    if entity is not None:
        payload |= {"entity": entity, "record_id": record_id}
    return await enqueue(conn, tenant_id=tenant_id, kind=KIND_CONFLICT_CHECK, actor=actor, payload=payload)
