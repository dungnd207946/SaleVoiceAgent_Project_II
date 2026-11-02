"""Cron gọi lệnh này mỗi đêm — xếp job kiểm «tenant im lặng» cho mọi workspace.

    0 6 * * *  python -m portal.cli.kiem_tenant_im_lang

VÌ SAO LỆNH NÀY CHỈ XẾP HÀNG, KHÔNG TỰ KIỂM. Đúng luật đã ghi ở
`worker/__main__.py`: *«Job theo giờ KHÔNG dùng scheduler trong tiến trình: cron
gọi một lệnh ghi một hàng vào control.jobs. Như vậy job có dấu vết, và "job không
chạy" là thứ nhìn thấy được.»* Một lệnh cron tự làm hết việc rồi thoát thì lần nó
KHÔNG chạy không để lại gì — mà đó chính là chế độ hỏng mà cả cơ chế này tồn tại
để chặn. Sẽ khá mỉa mai nếu cái bắt-im-lặng lại chết im lặng.

VÌ SAO Ở `portal/cli/` CHỨ KHÔNG `scripts/`: Dockerfile không COPY `scripts/` vào
image, mà cron chạy trên production. Xem docstring `portal/cli/__init__.py`.

Xem `modules/ingest/jobs.py` để biết job làm gì, và docstring migration `0929` để
biết vì sao cần.
"""

import asyncio
import sys

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.modules.ingest.fanout import xep_moi_tenant
from portal.modules.ingest.jobs import KIND_IM_LANG


async def main_async() -> int:
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    try:
        so = await xep_moi_tenant(pool, kind=KIND_IM_LANG)
    finally:
        await pool.close()
    print(f"kiem-tenant-im-lang: đã xếp {so} job")
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
