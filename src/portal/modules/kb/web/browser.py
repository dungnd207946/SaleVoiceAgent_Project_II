"""Tầng 2: tải trang bằng trình duyệt thật (Playwright/Chromium) cho trang chặn bot hoặc dựng bằng JS.

Gói `playwright` mọi vai đều cài, nhưng chỉ image `crawl-worker` cài Chromium. Thiếu gói hoặc không khởi động
được trình duyệt thì `BrowserFetcher` tự tắt (`available = False`) và trả `needs_browser` như trước,
không làm chết tiến trình. `TieredFetcher` ghép hai tầng: http trước, trình duyệt khi http bị chặn/rỗng,
dưới trần `browser_daily` của tenant (`BrowserBudget`, Redis theo ngày VN).
"""

import asyncio
import contextlib
import logging
from datetime import datetime

from portal.modules.kb.web.contracts import STATUS_FAILED, STATUS_NEEDS_BROWSER
from portal.modules.kb.web.fetch import USER_AGENT, Fetched, extract, looks_challenged
from portal.modules.kb.web.grounding import VN
from portal.modules.kb.web.netguard import Resolve, is_public_url

log = logging.getLogger(__name__)

TIMEOUT_SEC = 45.0
CHALLENGE_WAIT_SEC = 8.0
_BLOCKED_RESOURCES = ("image", "media", "font", "stylesheet")
_KEY_PREFIX = "kbweb:browser:"
_TTL_SEC = 2 * 86400


class BrowserBudget:
    """Trần số lượt mở trình duyệt mỗi ngày (giờ VN) của một tenant — cùng khuôn `GroundingBudget`."""

    def __init__(self, redis=None, *, tenant: str, cap: int) -> None:
        self._redis = redis
        self._tenant = tenant
        self._cap = cap
        self._local = 0

    async def take(self) -> bool:
        if self._redis is None:
            if self._local + 1 > self._cap:
                return False
            self._local += 1
            return True
        key = f"{_KEY_PREFIX}{self._tenant}:{datetime.now(VN):%Y-%m-%d}"
        used = await self._redis.incrby(key, 1)
        if used == 1 or await self._redis.ttl(key) < 0:
            await self._redis.expire(key, _TTL_SEC)
        return used <= self._cap


class BrowserFetcher:
    def __init__(
        self, *, resolve: Resolve | None = None, timeout_sec: float = TIMEOUT_SEC, concurrency: int = 2
    ) -> None:
        self._resolve = resolve
        self._timeout = timeout_sec
        self._gate = asyncio.Semaphore(concurrency)
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        self.available = True

    async def _ensure(self):
        async with self._lock:
            if self._browser is not None or not self.available:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                log.warning("playwright chưa cài — tầng trình duyệt tắt, trang chặn bot giữ dấu needs_browser")
                self.available = False
                return None
            try:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=True, args=["--no-sandbox"])
            except Exception as exc:
                log.warning("không khởi động được Chromium (%s) — tầng trình duyệt tắt", exc)
                self.available = False
                await self.aclose()
            return self._browser

    async def html(self, url: str) -> tuple[str, int] | None:
        """HTML sau khi trình duyệt dựng xong + mã trả lời; `None` = không tải được/không công khai/tầng tắt."""
        if not await is_public_url(url, self._resolve):
            return None
        browser = await self._ensure()
        if browser is None:
            return None
        async with self._gate:
            try:
                html, status, final = await asyncio.wait_for(self._render(browser, url), self._timeout + 15)
            except Exception as exc:
                log.info("trình duyệt không tải được %s: %s", url, exc)
                return None
        if not await is_public_url(final, self._resolve):
            return None
        return html, status

    async def fetch(self, url: str) -> Fetched:
        if not await is_public_url(url, self._resolve):
            return Fetched(url, STATUS_FAILED, reason="private", tier="browser")
        if not self.available:
            return Fetched(url, STATUS_NEEDS_BROWSER, reason="unavailable", tier="browser")
        got = await self.html(url)
        if got is None:
            reason = "unavailable" if not self.available else "network"
            status = STATUS_NEEDS_BROWSER if reason == "unavailable" else STATUS_FAILED
            return Fetched(url, status, reason=reason, tier="browser")
        html, status = got
        if looks_challenged(status, html):
            return Fetched(url, STATUS_NEEDS_BROWSER, reason="challenge", tier="browser")
        try:
            title, text, when = await asyncio.to_thread(extract, html, url)
        except Exception:
            log.warning("bóc nội dung lỗi: %s", url, exc_info=True)
            return Fetched(url, STATUS_FAILED, reason="extract", tier="browser")
        if not text.strip():
            return Fetched(url, STATUS_FAILED, reason="empty", tier="browser")
        return Fetched(url, "ok", title, text, when, tier="browser")

    async def _render(self, browser, url: str) -> tuple[str, int, str]:
        ctx = await browser.new_context(user_agent=USER_AGENT, locale="vi-VN", viewport={"width": 1280, "height": 900})
        try:
            await ctx.route("**/*", _skip_heavy)
            page = await ctx.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)
            status = resp.status if resp else 0
            with contextlib.suppress(Exception):  # trang có tracker kéo mãi, DOM đã đủ
                await page.wait_for_load_state("networkidle", timeout=10_000)
            html = await page.content()
            if looks_challenged(status, html):
                # challenge JS của Cloudflare tự giải sau vài giây rồi tải lại trang thật
                await page.wait_for_timeout(CHALLENGE_WAIT_SEC * 1000)
                html, status = await page.content(), 200
            return html, status, page.url
        finally:
            await ctx.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


async def _skip_heavy(route) -> None:
    if route.request.resource_type in _BLOCKED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


class TieredFetcher:
    """http trước; bị chặn/rỗng thì trình duyệt (nếu còn trần ngày). `mode="browser"` đi thẳng trình duyệt."""

    def __init__(self, http, browser: BrowserFetcher | None, budget: BrowserBudget) -> None:
        self._http = http
        self._browser = browser
        self._budget = budget

    async def fetch(self, url: str, mode: str = "http") -> Fetched:
        if mode != "browser":
            first = await self._http.fetch(url)
            if not first.retry_browser:
                return first
        else:
            first = Fetched(url, STATUS_NEEDS_BROWSER, reason="mode")
        if self._browser is None or not self._browser.available:
            return Fetched(url, STATUS_NEEDS_BROWSER, reason=first.reason)
        if not await self._budget.take():
            log.warning("hết trần trình duyệt trong ngày, giữ dấu needs_browser: %s", url)
            return Fetched(url, STATUS_NEEDS_BROWSER, reason="budget")
        second = await self._browser.fetch(url)
        return second if second.status == "ok" or mode == "browser" else _worse(first, second)


def _worse(first: Fetched, second: Fetched) -> Fetched:
    """Cả hai tầng hỏng: giữ `needs_browser` nếu một tầng bị chặn (còn hy vọng lượt sau), không thì lỗi tải."""
    if STATUS_NEEDS_BROWSER in (first.status, second.status):
        return Fetched(first.url, STATUS_NEEDS_BROWSER, reason=second.reason or first.reason)
    return second
