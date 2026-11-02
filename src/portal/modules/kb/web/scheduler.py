"""Lịch chạy kb/web đọc từ `tenant_data.kbweb_schedules` — thay systemd timer.

`loop(pool)` chạy trong `portal.cli.kb_web_worker`: mỗi `TICK_SEC` giây, với từng tenant active,
hàng lịch nào `enabled` và `next_run_at <= now` thì xếp job `kbweb_run` (gộp nếu đã có việc cùng
mode đang chờ) rồi tính `next_run_at` kế tiếp. Hàng chưa có `next_run_at` (vừa seed/vừa sửa) chỉ
được TÍNH mốc, không chạy ngay — bật lịch lúc 14h không có nghĩa là chạy lượt đêm lúc 14h.

Một tiến trình giữ `pg_try_advisory_lock` suốt đời để hai replica crawl-worker không cùng xếp.
Giờ tính theo VN (`at_time` người dùng đặt là giờ VN).
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta

import asyncpg

from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue
from portal.modules.kb.web.contracts import KIND_RUN, MODE_NIGHTLY, MODE_REBUILD, MODE_WEEKLY, SCHEDULE_MODES
from portal.modules.kb.web.discover import VN

log = logging.getLogger(__name__)

TICK_SEC = 60
LOCK_KEY = "kbweb_scheduler"
ACTOR = "lich"
ALIVE_KEY = "kbweb:worker:alive"
ALIVE_TTL_SEC = 180
"""Màn «Dữ liệu ngoài» đọc khoá này để biết crawl-worker có đang chạy không."""

_QUEUED = """SELECT 1 FROM control.jobs
              WHERE tenant_id = portal.current_tenant() AND kind = $1 AND state IN ('queued', 'running')
                AND payload->>'mode' = $2
              LIMIT 1"""


def _at(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=VN)


def _rule_day(year: int, month: int, rule: str) -> date:
    if rule == "d15":
        return date(year, month, 15)
    if rule == "first_sunday":
        first = date(year, month, 1)
        return first + timedelta(days=(6 - first.weekday()) % 7)
    return date(year, month, 1)


def next_run(
    mode: str, after: datetime, *, at: time, weekdays: list[int] = (), every_months: int = 0, day_rule: str = ""
) -> datetime | None:
    """Mốc chạy kế tiếp SAU `after` (giờ VN). `None` = lịch không có ngày nào (weekly rỗng weekdays).

    `rebuild` chạy ở các tháng có `(năm*12 + tháng-1) % every_months == 0` — không trạng thái, nên N = 3
    rơi đúng tháng 1/4/7/10 và N không chia hết 12 (vd 5) vẫn cách đều qua ranh giới năm."""
    start = after.astimezone(VN)
    if mode == MODE_NIGHTLY:
        cand = _at(start.date(), at)
        return cand if cand > start else cand + timedelta(days=1)
    if mode == MODE_WEEKLY:
        for i in range(8):
            day = start.date() + timedelta(days=i)
            if day.weekday() in weekdays and (cand := _at(day, at)) > start:
                return cand
        return None
    if mode == MODE_REBUILD:
        step = every_months or 1
        year, month = start.year, start.month
        for _ in range(2 * step + 2):
            if (year * 12 + month - 1) % step == 0 and (
                cand := _at(_rule_day(year, month, day_rule or "d1"), at)
            ) > start:
                return cand
            month, year = (month % 12 + 1, year + (month == 12))
        return None
    raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {SCHEDULE_MODES}")


def _next_of(row: asyncpg.Record, after: datetime) -> datetime | None:
    return next_run(
        row["mode"],
        after,
        at=row["at_time"],
        weekdays=list(row["weekdays"] or ()),
        every_months=row["every_months"] or 0,
        day_rule=row["day_rule"] or "",
    )


async def enqueue_run(
    conn: asyncpg.Connection, *, tenant_id: str, actor: str, mode: str, slices: int = 1
) -> int | None:
    """Xếp một lượt theo lịch cho tenant của `conn`. `None` = đã có lượt cùng mode đang chờ/chạy."""
    if mode not in SCHEDULE_MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {SCHEDULE_MODES}")
    if await conn.fetchval(_QUEUED, KIND_RUN, mode):
        return None
    return await enqueue(
        conn, tenant_id=tenant_id, kind=KIND_RUN, actor=actor, payload={"mode": mode, "slices": slices}
    )


async def tick_tenant(pool: asyncpg.Pool, tenant_id: str, now: datetime) -> int:
    """Trả số lượt đã xếp cho tenant. Hàng tới giờ: xếp + `last_run_at` + mốc kế; hàng chưa có mốc: chỉ tính mốc."""
    queued = 0
    async with tenant_conn(pool, tenant_id) as c:
        rows = await c.fetch(
            """SELECT mode, at_time, weekdays, every_months, day_rule, slices, next_run_at
                 FROM tenant_data.kbweb_schedules
                WHERE tenant_id = portal.current_tenant() AND enabled
                  AND (next_run_at IS NULL OR next_run_at <= $1)
                ORDER BY mode""",
            now,
        )
        for r in rows:
            nxt = _next_of(r, now)
            if r["next_run_at"] is not None:
                if await enqueue_run(c, tenant_id=tenant_id, actor=ACTOR, mode=r["mode"], slices=r["slices"]):
                    queued += 1
                await c.execute(
                    """UPDATE tenant_data.kbweb_schedules SET last_run_at = $2, next_run_at = $3
                        WHERE tenant_id = portal.current_tenant() AND mode = $1""",
                    r["mode"],
                    now,
                    nxt,
                )
            else:
                await c.execute(
                    """UPDATE tenant_data.kbweb_schedules SET next_run_at = $2
                        WHERE tenant_id = portal.current_tenant() AND mode = $1""",
                    r["mode"],
                    nxt,
                )
    return queued


async def tick(pool: asyncpg.Pool, now: datetime | None = None) -> int:
    now = now or datetime.now(VN)
    async with pool.acquire() as c:
        tenants = [
            r["id"]
            for r in await c.fetch(
                # Hồ sơ web chỉ phục vụ dự án bất động sản: tắt lĩnh vực đó ở «Quản lý lĩnh vực» là lịch dừng.
                """SELECT t.id FROM control.tenants t
                    WHERE t.lifecycle = 'active'
                      AND EXISTS (SELECT 1 FROM control.tenant_verticals v
                                   WHERE v.tenant_id = t.id AND v.vertical = 'realestate')
                    ORDER BY t.id"""
            )
        ]
    queued = 0
    for tid in tenants:
        try:
            queued += await tick_tenant(pool, tid, now)
        except Exception:
            log.exception("lịch kb/web của tenant %s hỏng", tid)
    return queued


async def loop(pool: asyncpg.Pool, *, tick_sec: float = TICK_SEC, redis=None) -> None:
    """Giữ một kết nối riêng cho advisory lock; không giành được thì chờ và thử lại (replica khác đang chạy)."""
    async with pool.acquire() as holder:
        while True:
            try:
                if redis is not None:
                    await redis.set(ALIVE_KEY, datetime.now(VN).isoformat(), ex=ALIVE_TTL_SEC)
                if await holder.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", LOCK_KEY):
                    n = await tick(pool)
                    if n:
                        log.info("lịch kb/web: xếp %d lượt", n)
            except Exception:
                log.exception("lịch kb/web: lượt kiểm hỏng")
            await asyncio.sleep(tick_sec)
