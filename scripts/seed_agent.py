"""Cấp phát hạ tầng + phát api_key cho workspace demo. Idempotent-ish.

VÌ SAO CẦN SCRIPT NÀY: sau `make up` bạn không có cách nào chạy `make agent-gia`
— khoá chỉ hiện đúng một lần, qua `POST /agent/admin/tenants/<id>/provision`, và đường đó
cần token quản trị. Script này làm cùng việc bằng credential runtime, để đường
ống dev thông được mà không phải bật API rồi curl.

IN KHOÁ THÔ RA STDOUT là chấp nhận được ở đây và CHỈ ở đây: có guard chỉ-localhost,
và không có nó thì `make up` xong vẫn không đấu nối được. Ở production khoá đi qua
API và chỉ hiện một lần trên màn hình admin.

Chạy: make seed-agent
"""

import asyncio
import sys
from urllib.parse import urlparse

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.modules.enrollment import service
from portal.modules.enrollment.ha_tang import HaTang
from scripts.dev_seed import WORKSPACE

TENANT_DEMO = WORKSPACE[0][0]
"""Workspace đầu trong dev_seed. Một khoá demo là đủ để chứng minh đường ống."""


def _chan_ngoai_localhost(dsn: str) -> None:
    host = urlparse(dsn.replace("postgresql+asyncpg", "postgresql")).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1", "postgres"):
        sys.exit(f"TỪ CHỐI: Postgres {host!r} không phải localhost. Script này chỉ dành cho dev.")


async def main() -> None:
    c = get_settings()
    _chan_ngoai_localhost(c.database_url)

    pool = await create_pool(c.database_url, min_size=1, max_size=2)
    try:
        # ĐỪNG thêm lại tham số `kind` ("chat"/"voice") ở đây — `0919` đã bỏ cột
        # `control.deployments.kind`, và lời gọi cũ còn sót lại làm `make seed-agent`
        # ném TypeError suốt từ đó (không ai chạy nên không ai thấy).
        khoa = await service.cap_phat(pool, HaTang.tu_cai_dat(), TENANT_DEMO, "dev", "seed_agent")
    finally:
        await pool.close()

    print(f"\n  khoá {khoa.id} · workspace {TENANT_DEMO}")
    print(f"  AGENT_API_KEY={khoa.api_key}")
    print(f"\n  chạy thử:  make agent-gia KEY={khoa.api_key}\n")


if __name__ == "__main__":
    asyncio.run(main())
