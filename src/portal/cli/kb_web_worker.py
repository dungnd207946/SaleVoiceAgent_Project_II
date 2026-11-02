"""Worker riêng của container crawl: chạy job kb/web (`kbweb_run`, `kbweb_project`) + lịch của tenant.

    python -m portal.cli.kb_web_worker

Chỉ import `kb/web/jobs.py`, không gọi `load_handlers()` — worker chính và worker này không nhặt việc của nhau.
`scheduler.loop` đọc `tenant_data.kbweb_schedules` mỗi phút và xếp `kbweb_run` — không còn systemd timer.
"""

import asyncio
import logging

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.jobs import concurrency_of, thu_hoi_viec_ket
from portal.modules.kb.web import jobs, pipeline, scheduler
from portal.modules.kb.web.contracts import KIND_PROBE, KIND_PROJECT, KIND_PURGE, KIND_RUN
from portal.worker.__main__ import chay_toi_khi_dung, reclaim_loop, run_lane

log = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lanes = (
        concurrency_of(KIND_PROJECT)
        + concurrency_of(KIND_RUN)
        + concurrency_of(KIND_PROBE)
        + concurrency_of(KIND_PURGE)
    )
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=lanes + 3)
    try:
        async with pipeline.open_deps() as rt:
            jobs.share_runtime(rt)
            await thu_hoi_viec_ket(pool)
            log.info("kb/web worker chạy %d làn + lịch", lanes)
            await chay_toi_khi_dung(
                pool,
                [reclaim_loop(pool), scheduler.loop(pool, redis=rt.redis), *[run_lane(pool) for _ in range(lanes)]],
            )
    finally:
        jobs.share_runtime(None)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
