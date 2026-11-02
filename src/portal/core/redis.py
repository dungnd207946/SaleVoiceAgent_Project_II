"""Factory client Redis. Không giữ singleton — caller quản vòng đời.

Cùng khuôn `core/db/pool.py`: một hàm, không state module-level. Xem docstring
của api/app.py để biết vì sao.
"""

from redis.asyncio import Redis


def create_redis(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)
