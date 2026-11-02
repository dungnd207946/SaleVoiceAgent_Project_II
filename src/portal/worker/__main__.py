"""Tiến trình worker. Chạy: make worker

Handler đăng ký lúc import `modules/<m>/jobs.py` — `load_handlers()` liệt kê chúng.

Job theo giờ KHÔNG dùng scheduler trong tiến trình: cron trên máy chủ gọi một
lệnh ghi một hàng vào control.jobs. Như vậy job có dấu vết, và "job không chạy"
là thứ nhìn thấy được.
"""

import asyncio
import logging
import signal
from collections.abc import Coroutine
from typing import Any

import asyncpg

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.jobs import kinds_with_headroom, run_once, thu_hoi_viec_ket, tra_lai_viec_dang_giu

log = logging.getLogger(__name__)

IDLE_SLEEP_SEC = 2.0
RECLAIM_EVERY_SEC = 60.0
# Docker cho 10 giây từ SIGTERM tới SIGKILL; chờ các làn huỷ xong tối đa chừng này rồi trả việc.
CHO_HUY_GIAY = 5.0


def load_handlers() -> list[str]:
    """Import jobs.py của các module có job — `register()` chạy lúc import.

    `kb/web/jobs.py` cố ý KHÔNG ở đây: nó chạy ở worker riêng (`cli/kb_web_worker.py`).
    """
    import portal.modules.ingest.jobs
    import portal.modules.kb.conflicts.jobs
    import portal.modules.kb.jobs
    import portal.modules.nhan_vat.jobs

    return [
        portal.modules.ingest.jobs.__name__,
        portal.modules.kb.conflicts.jobs.__name__,
        portal.modules.kb.jobs.__name__,
        portal.modules.nhan_vat.jobs.__name__,
    ]


async def run_lane(pool: asyncpg.Pool) -> None:
    """Một làn: nhặt và chạy job thuộc những kind còn chỗ trống, mãi mãi."""
    while True:
        kinds = kinds_with_headroom()
        if not kinds or await run_once(pool, kinds=kinds) is None:
            await asyncio.sleep(IDLE_SLEEP_SEC)


async def reclaim_loop(pool: asyncpg.Pool) -> None:
    """Thu hồi việc kẹt theo NHỊP, không theo lúc rảnh.

    Bản cũ chỉ gọi khi hàng đợi rỗng, nên trong đúng một đợt backfill dài — lúc dễ có
    việc kẹt nhất — nó không bao giờ chạy.
    """
    while True:
        await asyncio.sleep(RECLAIM_EVERY_SEC)
        try:
            await thu_hoi_viec_ket(pool)
        except Exception:
            log.exception("thu hồi việc kẹt hỏng")


async def chay_toi_khi_dung(
    pool: asyncpg.Pool, vong: list[Coroutine[Any, Any, None]], dung: asyncio.Event | None = None
) -> None:
    """Chạy các vòng của worker tới khi nhận SIGTERM/SIGINT (deploy dừng container) hoặc một vòng chết, rồi
    huỷ các làn và trả việc đang dở về hàng đợi để container mới nhặt ngay. `dung` để test tự bấm dừng."""
    loop = asyncio.get_running_loop()
    tin_hieu = dung is None
    dung = dung or asyncio.Event()
    if tin_hieu:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, dung.set)
    tasks = [asyncio.create_task(v) for v in vong]
    cho = asyncio.create_task(dung.wait())
    try:
        xong, _ = await asyncio.wait([*tasks, cho], return_when=asyncio.FIRST_COMPLETED)
    finally:
        if tin_hieu:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)
        cho.cancel()
        for t in tasks:
            t.cancel()
        await asyncio.wait(tasks, timeout=CHO_HUY_GIAY)
        ids = await tra_lai_viec_dang_giu(pool)
        if ids:
            log.warning("worker dừng: trả %d việc về hàng đợi %s", len(ids), ids)
    for t in xong:
        if t is not cho and not t.cancelled() and t.exception() is not None:
            raise t.exception()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("handler đã nạp: %s", load_handlers() or "(chưa có)")

    budget = get_settings().worker_budget
    pool = await create_pool(get_settings().database_url, max_size=budget + 4)
    try:
        await thu_hoi_viec_ket(pool)
        log.info("chạy %d làn", budget)
        await chay_toi_khi_dung(pool, [reclaim_loop(pool), *[run_lane(pool) for _ in range(budget)]])
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
