"""Tầng 1: tải trang tĩnh qua http (không trình duyệt) + bóc nội dung bằng trafilatura."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import httpx
import trafilatura

from portal.modules.kb.web.contracts import STATUS_FAILED, STATUS_NEEDS_BROWSER, STATUS_OK
from portal.modules.kb.web.discover import parse_when
from portal.modules.kb.web.netguard import MAX_REDIRECTS, Resolve, is_public_url
from portal.modules.kb.web.normalize import domain_of

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
TIMEOUT_SEC = 20.0
MAX_BYTES = 3_000_000
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "attention required",
    "enable javascript and cookies",
    "document.cookie=",
)
_REDIRECT_CODES = (301, 302, 303, 307, 308)


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    status: str
    title: str = ""
    text: str = ""
    published_at: datetime | None = None
    reason: str = ""
    """Vì sao không `ok`: challenge · status · empty · network · extract · private · budget · unavailable."""
    tier: str = "http"
    """Tầng đã trả kết quả này: `http` hoặc `browser`."""

    @property
    def retry_browser(self) -> bool:
        """Tầng http thua theo kiểu trình duyệt có thể thắng: bị chặn, mã lạ, hoặc trang dựng bằng JS (rỗng)."""
        return self.status == STATUS_NEEDS_BROWSER or self.reason in ("status", "empty")


def looks_challenged(status_code: int, html: str) -> bool:
    head = html[:5000].lower()
    if any(m in head for m in CHALLENGE_MARKERS):
        return True
    return status_code in (403, 503) and len(html) < 20_000


def extract(html: str, url: str) -> tuple[str, str, datetime | None]:
    raw = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True, include_comments=False, include_tables=True
    )
    if not raw:
        return "", "", None
    d = json.loads(raw)
    return str(d.get("title") or ""), str(d.get("text") or ""), parse_when(d.get("date"))


class Fetcher:
    """Một client dùng chung; mỗi domain có cổng đồng thời + độ trễ riêng (lịch sự với nguồn)."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        per_domain: int = 2,
        delay_sec: float = 1.0,
        resolve: Resolve | None = None,
    ) -> None:
        self._http = http
        self._per_domain = per_domain
        self._delay = delay_sec
        self._resolve = resolve
        self._gates: dict[str, asyncio.Semaphore] = {}

    def _gate(self, domain: str) -> asyncio.Semaphore:
        return self._gates.setdefault(domain, asyncio.Semaphore(self._per_domain))

    async def fetch(self, url: str) -> Fetched:
        if not await is_public_url(url, self._resolve):
            log.debug("bỏ URL không công khai: %s", url)
            return Fetched(url, STATUS_FAILED, reason="private")
        async with self._gate(domain_of(url)):
            try:
                html, code = await self._download(url)
            except (httpx.HTTPError, httpx.InvalidURL, ValueError):
                return Fetched(url, STATUS_FAILED, reason="network")
            finally:
                if self._delay:
                    await asyncio.sleep(self._delay)
        if looks_challenged(code, html):
            return Fetched(url, STATUS_NEEDS_BROWSER, reason="challenge")
        if code != 200:
            return Fetched(url, STATUS_FAILED, reason="status")
        try:
            title, text, when = await asyncio.to_thread(extract, html, url)
        except Exception:
            log.warning("bóc nội dung lỗi: %s", url, exc_info=True)
            return Fetched(url, STATUS_FAILED, reason="extract")
        if not text.strip():
            return Fetched(url, STATUS_FAILED, reason="empty")
        return Fetched(url, STATUS_OK, title, text, when)

    async def _download(self, url: str) -> tuple[str, int]:
        """Tự theo redirect (≤ `MAX_REDIRECTS`) để kiểm host của TỪNG bước, không chỉ URL đầu."""
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"}
        for _ in range(MAX_REDIRECTS + 1):
            async with self._http.stream("GET", url, headers=headers, follow_redirects=False, timeout=TIMEOUT_SEC) as r:
                location = r.headers.get("location")
                if r.status_code in _REDIRECT_CODES and location:
                    url = urljoin(str(r.url), location)
                    if not await is_public_url(url, self._resolve):
                        raise ValueError(f"redirect sang URL không công khai: {url}")
                    continue
                buf = bytearray()
                async for part in r.aiter_bytes():
                    buf.extend(part)
                    if len(buf) > MAX_BYTES:
                        raise ValueError("trang vượt trần kích thước")
                return buf.decode(r.encoding or "utf-8", errors="ignore"), r.status_code
        raise ValueError(f"quá {MAX_REDIRECTS} lần redirect")
