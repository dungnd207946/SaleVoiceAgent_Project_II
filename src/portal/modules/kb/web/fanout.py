"""Xếp việc hồ sơ web cho mọi dự án published của mọi tenant active — một `tenant_conn` mỗi tenant.

Không lặp `enqueue` trên một kết nối: `core.jobs.enqueue` suy tenant từ chính kết nối (xem `ingest/fanout.py`).
"""

import logging
from datetime import date, datetime

import asyncpg

from portal.core.db.session import tenant_conn
from portal.modules.kb.settings import get_env
from portal.modules.kb.web.compose import dossier_ids
from portal.modules.kb.web.contracts import MODE_INIT, MODE_REBUILD, MODE_WEEKLY, MODES
from portal.modules.kb.web.discover import VN
from portal.modules.kb.web.enqueue import enqueue_web_project
from portal.modules.kb.web.signal import asked_codes, load_projects

log = logging.getLogger(__name__)


async def queue_projects(
    pool: asyncpg.Pool,
    mode: str,
    *,
    today: date | None = None,
    tenant_id: str | None = None,
    slices: int | None = None,
    asked_days: int | None = None,
    actor: str = "cron",
) -> int:
    """Dựng lại: mọi dự án. Đêm: dự án đang được hỏi. Tuần: dự án đang được hỏi có
    `id % slices == today.toordinal() % slices` (`slices` mặc định `KB_WEB_DEEP_SLICES` = 2 —
    một nửa số dự án mỗi ngày; lịch của tenant truyền giá trị riêng). Dùng `toordinal()` thay vì
    `weekday()` để phép chia lát cắt vẫn đúng khi qua ranh giới tuần, với mọi giá trị `slices`.

    `tenant_id` = chỉ một tenant (job theo lịch của tenant); không có thì mọi tenant active.
    Trả số việc MỚI đã xếp (việc gộp vào việc đang chờ không tính). Một tenant hỏng không chặn
    tenant khác; hỏng ở đâu thì cuối lượt ném `RuntimeError` nêu tenant (việc đã xếp vẫn giữ)."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {MODES}")
    slices = slices or get_env().web_deep_slices
    slot = (today or datetime.now(VN).date()).toordinal() % slices
    if tenant_id:
        tenants = [tenant_id]
    else:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM control.tenants WHERE lifecycle = 'active' ORDER BY id")
        tenants = [r["id"] for r in rows]
    queued = 0
    failed: list[str] = []
    for tid in tenants:
        try:
            queued += await _queue_tenant(pool, tid, mode, slot, slices, asked_days, actor)
        except Exception:
            log.exception("xếp việc hồ sơ web cho tenant %s hỏng", tid)
            failed.append(tid)
    if failed:
        raise RuntimeError(f"đã xếp {queued} việc {mode}; {len(failed)} tenant hỏng: {', '.join(failed)}")
    return queued


async def _queue_tenant(
    pool: asyncpg.Pool, tenant_id: str, mode: str, slot: int, slices: int, asked_days: int | None, actor: str
) -> int:
    queued = 0
    async with tenant_conn(pool, tenant_id) as conn:
        projects = await load_projects(conn)
        if mode == MODE_WEEKLY:
            projects = [p for p in projects if p.id % slices == slot]
        if mode == MODE_REBUILD:
            codes = {p.code for p in projects}
        else:
            codes = await asked_codes(conn, projects, **({"days": asked_days} if asked_days else {}))
        for code in sorted(codes):
            if await enqueue_web_project(conn, tenant_id=tenant_id, actor=actor, project_code=code, mode=mode):
                queued += 1
    return queued


async def queue_missing(pool: asyncpg.Pool, index, *, tenant_id: str, actor: str = "cron") -> int:
    """Dự án published CHƯA có hồ sơ ⇒ xếp `init`, không cần khách đã hỏi — lượt đêm/tuần chỉ phủ dự án
    đang được hỏi, nên dự án chưa ai hỏi sẽ mãi không có hồ sơ nếu thiếu bước này."""
    queued = 0
    async with tenant_conn(pool, tenant_id) as conn:
        projects = await load_projects(conn)
        for p in projects:
            if await index.get(dossier_ids(p.name)):
                continue
            if await enqueue_web_project(conn, tenant_id=tenant_id, actor=actor, project_code=p.code, mode=MODE_INIT):
                queued += 1
    return queued
