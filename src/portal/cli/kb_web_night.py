"""Chuỗi đêm của kb/web cho MỘT tenant — lệnh vận hành tay; lịch thật do `kb/web/scheduler.py` trong
`portal.cli.kb_web_worker` đọc từ `tenant_data.kbweb_schedules`.

    python -m portal.cli.kb_web_night --tenant anphu                  crawl 2 ngày → living → bản tin → dọn → xếp việc
    python -m portal.cli.kb_web_night --tenant anphu --weekly              xếp lượt sâu cho 1/N số dự án
    python -m portal.cli.kb_web_night --tenant anphu --rebuild             xếp lượt dựng lại
    python -m portal.cli.kb_web_night --tenant anphu --backfill 2024-10-01 2026-09-28
    python -m portal.cli.kb_web_night --tenant anphu --discover-only --day 2026-09-29

Một bước hỏng không dừng các bước sau (bản tin/xếp việc vẫn chạy trên dữ liệu đã có), mã thoát 1.
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta

import httpx

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.modules.kb import settings as kb_settings
from portal.modules.kb.web import config, pipeline
from portal.modules.kb.web.contracts import MODE_REBUILD, MODE_WEEKLY
from portal.modules.kb.web.discover import VN, Discoverer
from portal.modules.kb.web.fanout import queue_projects

log = logging.getLogger("kb_web_night")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kb_web_night", description="Chuỗi đêm kb/web của một tenant (mặc định: lượt đêm)."
    )
    p.add_argument("--tenant", required=True, help="tenant_id (control.tenants.id)")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--weekly",
        action="store_true",
        help="xếp lượt sâu chỉ cho 1/N số dự án (N = --slices, mặc định KB_WEB_DEEP_SLICES), id %% N == ngày %% N",
    )
    g.add_argument("--rebuild", action="store_true", help="xếp lượt dựng lại cho mọi dự án published")
    g.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"), type=date.fromisoformat, help="crawl từng ngày")
    g.add_argument("--discover-only", action="store_true", help="chỉ đếm bài tìm được mỗi nguồn, không tải")
    p.add_argument("--day", type=date.fromisoformat, help="ngày đích (mặc định hôm qua giờ VN)")
    p.add_argument("--slices", type=int, help="số lát cắt của --weekly")
    return p


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = build_parser()
    a = p.parse_args(argv)
    if a.day and (a.weekly or a.rebuild or a.backfill):
        p.error("--day chỉ dùng cho lượt đêm hoặc --discover-only")
    if a.backfill and a.backfill[0] > a.backfill[1]:
        p.error("--backfill FROM phải <= TO")
    if a.slices is not None and (a.slices < 1 or not a.weekly):
        p.error("--slices phải >= 1 và chỉ dùng với --weekly")
    return a


def _print(steps: list[pipeline.Step]) -> bool:
    ok = True
    for st in steps:
        print(f"{st.name}: {st.error or st.count}")
        ok &= not st.error
    return ok


async def _discover_only(tenant: str, day: date) -> int:
    """Chỉ đọc mạng + cấu hình: không Qdrant (open_deps sẽ tạo collection), không LLM."""
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    try:
        async with tenant_conn(pool, tenant) as c:
            cfg = await config.load_for_tenant(c)
    finally:
        await pool.close()
    async with httpx.AsyncClient(timeout=kb_settings.HTTP_TIMEOUT_SEC) as http:
        discover = Discoverer(http)
        for s in cfg.sources:
            entries = await discover.day_entries(s, day, cfg.bds_keywords)
            print(f"{s.domain}: {len(entries)} bài ngày {day}")
    return 0


async def _queue_only(tenant: str, mode: str, today: date | None, slices: int | None) -> int:
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    try:
        n = await queue_projects(pool, mode, today=today, tenant_id=tenant, slices=slices)
        print(f"xếp {n} việc {mode}")
    finally:
        await pool.close()
    return 0


async def main_async(argv: list[str], *, now: datetime | None = None) -> int:
    a = parse_args(argv)
    now = now or datetime.now(UTC)
    today = now.astimezone(VN).date()
    if a.weekly:
        return await _queue_only(a.tenant, MODE_WEEKLY, today, a.slices)
    if a.rebuild:
        return await _queue_only(a.tenant, MODE_REBUILD, None, None)
    target = a.day or today - timedelta(days=1)
    if a.discover_only:
        return await _discover_only(a.tenant, target)
    async with pipeline.open_deps() as rt:
        deps = await rt.for_tenant(a.tenant)
        if a.backfill:
            day, end = a.backfill
            steps = []
            while day <= end:
                steps.append(await pipeline.run_step(f"crawl {day}", pipeline.crawl_day(deps, day)))
                day += timedelta(days=1)
            return 0 if _print(steps) else 1
        return 0 if _print(await pipeline.run_nightly(deps, now, target=target)) else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(main_async(sys.argv[1:])))


if __name__ == "__main__":
    main()
