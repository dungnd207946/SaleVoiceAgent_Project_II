"""Job kb/web. CHỈ worker riêng import file này (`portal.cli.kb_web_worker`).

`kb/jobs.py` cố ý không import nó, nên worker chính không bao giờ nhặt kind `kbweb_project`/`kbweb_run`.

  · `kbweb_run {mode, slices}` — một lượt theo lịch của MỘT tenant: đêm = chuỗi `run_nightly`
    (crawl → living → bản tin → dọn → xếp hồ sơ); tuần/dựng lại = chỉ xếp việc hồ sơ.
  · `kbweb_project {project_code, mode}` — hồ sơ một dự án.
  · `kbweb_purge {project_name}` — dọn hồ sơ + thẻ của một dự án khỏi kho của tenant.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import asyncpg

from portal.core.jobs import JobResult, register
from portal.modules.kb.web import fanout, pipeline, probe_job
from portal.modules.kb.web.compose import card_id, dossier_ids, near_id
from portal.modules.kb.web.contracts import (
    KIND_PROBE,
    KIND_PROJECT,
    KIND_PURGE,
    KIND_RUN,
    MODE_INIT,
    MODE_NIGHTLY,
    SCHEDULE_MODES,
)
from portal.modules.kb.web.signal import load_projects
from portal.modules.kb.web.usage import metered

# Worker riêng mở Runtime một lần cho cả tiến trình; không có thì mỗi job tự mở.
_shared_runtime: pipeline.Runtime | None = None


def share_runtime(rt: pipeline.Runtime | None) -> None:
    global _shared_runtime
    _shared_runtime = rt


@asynccontextmanager
async def _runtime() -> AsyncIterator[pipeline.Runtime]:
    if _shared_runtime is not None:
        yield _shared_runtime
        return
    async with pipeline.open_deps() as rt:
        yield rt


async def handle_project(conn: asyncpg.Connection, payload: dict) -> JobResult:
    code = str(payload.get("project_code") or "")
    mode = str(payload.get("mode") or MODE_INIT)
    tenant = await conn.fetchval("SELECT portal.current_tenant()")
    project = next((p for p in await load_projects(conn) if p.code == code), None)
    if project is None:
        return JobResult(0, f"bỏ qua {code or '(trống)'}: không có hoặc chưa published")
    async with _runtime() as rt:
        deps = await rt.for_tenant(tenant)
        r = await pipeline.refresh_project(deps, project, mode, datetime.now(UTC))
    if not r.kept_old:
        return JobResult(count=r.count, message=f"{code} {mode}: {r.count} mục")
    if r.count == 0:
        return JobResult(count=0, message=f"{code} {mode}: giữ hồ sơ cũ — {r.kept_old}")
    return JobResult(count=r.count, message=f"{code} {mode}: {r.count} mục, dừng dựng giữa chừng — {r.kept_old}")


async def handle_run(conn: asyncpg.Connection, payload: dict) -> JobResult:
    mode = str(payload.get("mode") or MODE_NIGHTLY)
    slices = max(1, int(payload.get("slices") or 1))
    if mode not in SCHEDULE_MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {SCHEDULE_MODES}")
    tenant = await conn.fetchval("SELECT portal.current_tenant()")
    async with _runtime() as rt:
        deps = await rt.for_tenant(tenant)
        limits = await pipeline.load_limits(conn)
        if mode != MODE_NIGHTLY:
            n = await fanout.queue_projects(
                rt.pool, mode, tenant_id=tenant, slices=slices, asked_days=limits.asked_days, actor="lich"
            )
            return JobResult(count=n, message=f"{mode}: xếp {n} hồ sơ")
        steps = await pipeline.run_nightly(deps, datetime.now(UTC))
    message = "; ".join(f"{s.name}: {s.error or s.count}" for s in steps)
    if any(s.error for s in steps):
        raise RuntimeError(message)
    return JobResult(count=sum(s.count for s in steps), message=message)


async def handle_probe(conn: asyncpg.Connection, payload: dict) -> JobResult:
    tenant = await conn.fetchval("SELECT portal.current_tenant()")
    async with _runtime() as rt:
        deps = await rt.for_tenant(tenant)
        return await probe_job.run(rt, deps, str(payload.get("url") or ""), str(payload.get("token") or ""))


async def handle_purge(conn: asyncpg.Connection, payload: dict) -> JobResult:
    name = str(payload.get("project_name") or "")
    if not name:
        return JobResult(0, "bỏ qua: thiếu tên dự án")
    tenant = await conn.fetchval("SELECT portal.current_tenant()")
    async with _runtime() as rt:
        deps = await rt.for_tenant(tenant)
        n = await deps.index.delete([*dossier_ids(name), card_id(name), near_id(name)])
    return JobResult(count=n, message=f"dọn {n} điểm của {name}")


# Lượt dựng ban đầu/dựng lại chạy tới `MAX_BUILD_PASSES` lượt viết + Gemini — dài hơn xa 15 phút mặc định.
register(KIND_PROJECT, metered(handle_project), retries=2, max_concurrency=2, stuck_minutes=120)
# Thử nguồn: người dùng đang chờ trên màn, trần 15 s trong `Prober` — làn riêng để không xếp sau lượt đêm.
register(KIND_PROBE, handle_probe, retries=0, max_concurrency=1, stuck_minutes=5)
# Chuỗi đêm crawl mọi nguồn của tenant — có thể hàng giờ; không retry (crawl lại là xếp lượt mới).
register(KIND_RUN, metered(handle_run), retries=0, max_concurrency=1, stuck_minutes=360)
register(KIND_PURGE, handle_purge, retries=2, max_concurrency=1, stuck_minutes=10)
