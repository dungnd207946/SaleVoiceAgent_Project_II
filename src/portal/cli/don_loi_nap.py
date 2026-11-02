"""Cron gọi lệnh này — xếp job dọn `tenant_data.ingest_errors` cho mọi workspace.

    30 3 * * *  python -m portal.cli.don_loi_nap

LỆNH RIÊNG, KHÔNG GỘP vào `kiem_tenant_im_lang`: hai việc có nhịp hợp lý khác
nhau (cảnh báo im lặng đáng chạy hằng đêm, dọn rác thì hằng tuần cũng đủ), và một
lệnh làm hai việc thì ops không tắt được việc này mà giữ việc kia. Cả hai dùng
chung `fanout.xep_moi_tenant`, nên phần lặp tenant chỉ có một bản.

Vì sao lệnh chỉ XẾP HÀNG chứ không tự dọn, và vì sao ở `portal/cli/` chứ không
`scripts/`: xem `kiem_tenant_im_lang.py` — cùng hai lý do.

Chính sách cắt (tuổi + trần dòng) ở `repo.don_loi`; ngưỡng ở `Settings`.
"""

import asyncio
import sys

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.modules.ingest.fanout import xep_moi_tenant
from portal.modules.ingest.jobs import KIND_DON_LOI


async def main_async() -> int:
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    try:
        so = await xep_moi_tenant(pool, kind=KIND_DON_LOI)
    finally:
        await pool.close()
    print(f"don-loi-nap: đã xếp {so} job")
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
