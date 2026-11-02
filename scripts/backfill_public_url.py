"""Điền `media.public_url`/`public_thumb_url` từ hai cột khoá.

Chạy sau `alembic upgrade head`, và chạy lại mỗi khi đổi `PUBLIC_BASE_URL` — giá trị
cũ mang domain cũ và nằm sẵn trong DB.

    DATABASE_URL=... PUBLIC_BASE_URL=https://portal.noblex.vn \
    uv run python scripts/backfill_public_url.py [--that]

Không có `--that` thì chỉ đếm, không ghi.
"""

import asyncio
import os
import sys

_SQL = """
UPDATE tenant_data.media
   SET public_url = CASE
           WHEN media_url = '' THEN ''
           WHEN media_url LIKE 'http://%' OR media_url LIKE 'https://%' THEN media_url
           ELSE $1 || media_url
       END,
       public_thumb_url = CASE
           WHEN coalesce(thumb_url, '') = '' THEN ''
           WHEN thumb_url LIKE 'http://%' OR thumb_url LIKE 'https://%' THEN thumb_url
           ELSE $1 || thumb_url
       END
"""


def duong_dan_goc() -> str:
    """Base công khai đã kiểm, kèm `PUBLIC_PATH`.

    Qua `kiem_base` chứ không nối thẳng: câu UPDATE dưới ghi đè `public_url` của MỌI hàng
    media, nên một `localhost` lọt vào đây không hỏng một hàng mà hỏng cả bảng — và hỏng
    im lặng, vì mọi thứ vẫn chạy trơn tru.
    """
    from portal.core.public_url import PUBLIC_PATH, kiem_base

    return kiem_base(os.environ["PUBLIC_BASE_URL"]).rstrip("/") + PUBLIC_PATH


async def main() -> int:
    import asyncpg

    that = "--that" in sys.argv
    dsn = os.environ["DATABASE_URL"]
    base = duong_dan_goc()

    conn = await asyncpg.connect(dsn)
    try:
        # RLS lọc theo `app.tenant_id`; script vận hành chạy cho MỌI tenant nên phải
        # nối bằng role bỏ qua RLS (`MIGRATOR_URL`) hoặc chạy từng tenant một.
        so = await conn.fetchval("SELECT count(*) FROM tenant_data.media")
        print(f"{so} hàng media, base = {base}")
        if not that:
            print("chưa ghi gì — thêm --that để chạy thật")
            return 0
        kq = await conn.execute(_SQL, base)
        print(f"đã ghi: {kq}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
