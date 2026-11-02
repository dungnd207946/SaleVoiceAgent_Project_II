"""Chỉ tải URL công khai: http(s), host không phải loopback/private/link-local/reserved.

URL đến từ sitemap/RSS/Gemini — tức là bên ngoài quyết. Không chặn thì một link trỏ vào
`169.254.169.254` hay `redis:6379` được container crawl tải hộ. Kiểm cả IP viết thẳng lẫn IP
phân giải ra; còn khe DNS rebinding giữa lúc kiểm và lúc nối — chấp nhận cho dữ liệu công khai.
"""

import asyncio
import socket
from collections.abc import Awaitable, Callable
from ipaddress import IPv6Address, ip_address
from urllib.parse import urlsplit

Resolve = Callable[[str], Awaitable[list[str]]]

MAX_REDIRECTS = 5


async def system_resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _public_ip(value: str) -> bool:
    ip = ip_address(value.split("%", 1)[0])
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def is_public_url(url: str, resolve: Resolve | None = None) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        return _public_ip(host)
    except ValueError:
        pass
    try:
        addrs = await (resolve or system_resolve)(host)
        return bool(addrs) and all(_public_ip(a) for a in addrs)
    except (OSError, UnicodeError, ValueError):
        return False
