"""Thử một nguồn người dùng vừa gõ: tải được không, có kênh bài mới (RSS/sitemap/trang mục) không, bài đọc được không.

Chạy ĐỒNG BỘ trong request (trần `TIMEOUT_SEC`), không qua job — người dùng đang đứng chờ ở ô «Thêm nguồn».
Thử http trước, trình duyệt sau (cùng `TieredFetcher` của tenant); cả hai thua mới báo `blocked`.
Kết quả là một `SourceSite` đề xuất + số liệu để màn hình hiện và để lưu thành hàng `kbweb_sources`.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx

from portal.modules.kb.web.config import BDS_KEYWORDS, SourceSite
from portal.modules.kb.web.discover import Discoverer, parse_rss, parse_sitemap
from portal.modules.kb.web.fetch import USER_AGENT, looks_challenged
from portal.modules.kb.web.netguard import is_public_url
from portal.modules.kb.web.normalize import domain_of

log = logging.getLogger(__name__)

TIMEOUT_SEC = 15.0
COUNT_SHARE = 0.5
"""Phần của `timeout` dành cho bước đếm bài qua kênh — site có sitemap index lớn (cafeland) đi hết
mọi sitemap con mất hơn 15 giây; hết phần này thì vẫn thử tải bài từ trang chủ và báo «chưa đếm»."""
PAGES_TO_TEST = 2
MIN_CATEGORY_LINKS = 5
STATUS_OK = "ok"
STATUS_BLOCKED = "blocked"
STATUS_NO_FEED = "no_feed"
STATUS_TIMEOUT = "timeout"
STATUS_PRIVATE = "private"
STATUSES = (STATUS_OK, STATUS_BLOCKED, STATUS_NO_FEED, STATUS_TIMEOUT, STATUS_PRIVATE)

_FEED_LINK = re.compile(r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]*>""", re.IGNORECASE)
_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ARTICLE_TAIL = re.compile(r"-\d+\.html?$|-\d{5,}$")
_FEED_GUESSES = ("/rss", "/feed", "/rss.xml", "/feed.xml")
_SITEMAP_GUESSES = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")


@dataclass(frozen=True, slots=True)
class ProbeResult:
    url: str
    status: str
    site: SourceSite | None = None
    articles: int = 0
    """Bài tìm được qua kênh của nguồn trong hai ngày gần nhất (sau lọc từ khoá BĐS)."""
    pages_tested: int = 0
    pages_ok: int = 0
    note: str = ""
    sample: tuple[str, ...] = ()


def _name_of(html: str, domain: str) -> str:
    m = _TITLE.search(html)
    if not m:
        return domain
    title = re.split(r"\s[-|–]\s", re.sub(r"\s+", " ", m.group(1)).strip())[0].strip()
    return title[:60] or domain


def _declared_feeds(html: str, base: str) -> list[str]:
    out = []
    for tag in _FEED_LINK.findall(html):
        if m := _HREF.search(tag):
            out.append(urljoin(base, m.group(1)))
    return out


def _normalize(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url if urlsplit(url).path else url + "/"


def _article_pattern(domain: str, links: list[str]) -> str:
    """Khuôn link bài suy từ các link cùng domain trên trang: đuôi `-<số>.html` hay `-<số dài>`."""
    html_tail = sum(1 for u in links if re.search(r"-\d+\.html?$", u))
    num_tail = sum(1 for u in links if re.search(r"-\d{5,}$", u))
    d = re.escape(domain)
    if html_tail >= MIN_CATEGORY_LINKS and html_tail >= num_tail:
        return rf"^https://(www\.)?{d}/.+-\d+\.html?$"
    if num_tail >= MIN_CATEGORY_LINKS:
        return rf"^https://(www\.)?{d}/.+-\d{{5,}}$"
    return ""


class Prober:
    def __init__(self, *, http: httpx.AsyncClient, discover: Discoverer, fetcher, browser=None, resolve=None) -> None:
        self._http = http
        self._discover = discover
        self._fetcher = fetcher
        self._browser = browser
        self._resolve = resolve

    async def probe(self, url: str, *, today: date, timeout: float = TIMEOUT_SEC) -> ProbeResult:
        url = _normalize(url)
        if not await is_public_url(url, self._resolve):
            return ProbeResult(url, STATUS_PRIVATE, note="Địa chỉ không phải trang web công khai.")
        try:
            return await asyncio.wait_for(self._probe(url, today, timeout * COUNT_SHARE), timeout)
        except TimeoutError:
            return ProbeResult(url, STATUS_TIMEOUT, note=f"Trang không trả lời trong {int(timeout)} giây.")

    async def _get_html(self, url: str) -> tuple[str, str] | None:
        """(html, tầng) — http trước; bị chặn/không có nội dung thì trình duyệt."""
        html, code = "", 0
        try:
            r = await self._http.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=10)
            html, code = r.text, r.status_code
        except httpx.HTTPError as exc:
            log.info("probe http %s: %s", url, exc)
        if code == 200 and html and not looks_challenged(code, html):
            return html, "http"
        if self._browser is None or not getattr(self._browser, "available", False):
            return None
        got = await self._browser.html(url)
        if got is None or looks_challenged(got[1], got[0]):
            return None
        return got[0], "browser"

    async def _feed_kind(self, feed: str) -> tuple[str, str] | None:
        """`('rss', url)` · `('index', url)` · `('urlset', url)` hay None nếu không đọc được."""
        body = await self._discover._get(feed)
        if body is None:
            return None
        try:
            children, urls = parse_sitemap(body)
            if children:
                return "index", feed
            if urls:
                return "urlset", feed
        except ET.ParseError:
            pass
        try:
            if parse_rss(body):
                return "rss", feed
        except ET.ParseError:
            pass
        return None

    async def _robots_sitemaps(self, base: str) -> list[str]:
        try:
            r = await self._http.get(urljoin(base, "/robots.txt"), timeout=5)
        except httpx.HTTPError:
            return []
        if r.status_code != 200:
            return []
        return [ln.split(":", 1)[1].strip() for ln in r.text.splitlines() if ln.lower().startswith("sitemap:")]

    async def _count(self, site: SourceSite, today: date, budget: float) -> list | None:
        """Bài hai ngày gần nhất qua kênh của nguồn; None nếu không đếm xong trong `budget` giây."""
        days = (today - timedelta(days=1), today)
        try:
            parts = await asyncio.wait_for(
                asyncio.gather(*(self._discover.day_entries(site, d, BDS_KEYWORDS) for d in days)), budget
            )
        except TimeoutError:
            return None
        return [e for part in parts for e in part]

    async def _probe(self, url: str, today: date, count_budget: float) -> ProbeResult:
        got = await self._get_html(url)
        if got is None:
            return ProbeResult(
                url,
                STATUS_BLOCKED,
                note="Không tải được trang, kể cả bằng trình duyệt. Trang có thể đang chặn tải tự động.",
            )
        html, tier = got
        domain = domain_of(url)
        base = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}/"
        candidates = list(dict.fromkeys(
            _declared_feeds(html, url)
            + [urljoin(base, g) for g in _FEED_GUESSES]
            + await self._robots_sitemaps(base)
            + [urljoin(base, g) for g in _SITEMAP_GUESSES]
        ))  # fmt: skip
        rss, index, urlsets = [], "", []
        for cand in candidates[:12]:
            if not await is_public_url(cand, self._resolve) or domain_of(cand) != domain:
                continue
            kind = await self._feed_kind(cand)
            if kind is None:
                continue
            if kind[0] == "rss":
                rss.append(cand)
            elif kind[0] == "index" and not index:
                index = cand
            elif kind[0] == "urlset":
                urlsets.append(cand)
        links = [urljoin(url, h) for h in _HREF.findall(html)]
        same = [u for u in dict.fromkeys(links) if domain_of(u) == domain and _ARTICLE_TAIL.search(urlsplit(u).path)]
        pattern = (
            _article_pattern(domain, same) if urlsplit(url).path.strip("/") or not (rss or index or urlsets) else ""
        )
        site = SourceSite(
            domain=domain,
            name=_name_of(html, domain),
            whitelisted=True,
            fetch_mode=tier,
            kind="news" if (rss or index or urlsets or pattern) else "living",
            rss=tuple(rss[:3]),
            sitemap_index=index,
            child_hint="",
            news_sitemaps=tuple(urlsets[:3]),
            category_pages=(url,) if pattern else (),
            article_pattern=pattern,
            category_paths=(),
        )
        if site.kind == "living":
            return ProbeResult(
                url,
                STATUS_NO_FEED,
                site=site,
                note="Không tìm thấy kênh bài mới (RSS/sitemap). Sẽ theo dõi như một trang cố định, kiểm mỗi tháng.",
            )
        counted = await self._count(site, today, count_budget)
        entries = counted or []
        sample = [e.url for e in entries[:PAGES_TO_TEST]] or same[:PAGES_TO_TEST]
        ok = 0
        for u in sample:
            if (await self._fetcher.fetch(u, mode=tier)).status == "ok":
                ok += 1
        if sample and ok == 0:
            return ProbeResult(
                url,
                STATUS_BLOCKED,
                site=site,
                articles=len(entries),
                pages_tested=len(sample),
                note="Tìm thấy danh sách bài nhưng không đọc được nội dung bài nào.",
                sample=tuple(sample),
            )
        notes = []
        if counted is None:
            notes.append("Kênh bài lớn, chưa đếm được bài trong lúc thử — lượt chạy mỗi đêm sẽ đếm đủ.")
        if tier == "browser":
            notes.append("Cần trình duyệt để tải — chậm hơn, tính vào trần trình duyệt mỗi ngày.")
        return ProbeResult(
            url,
            STATUS_OK,
            site=site,
            articles=len(entries),
            pages_tested=len(sample),
            pages_ok=ok,
            note=" ".join(notes),
            sample=tuple(sample),
        )
