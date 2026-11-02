"""Tìm bài viết của một ngày (giờ VN) qua sitemap, RSS, trang mục. Không lưu gì, chỉ trả URL/thời điểm."""

import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from portal.modules.kb.web.config import SourceSite
from portal.modules.kb.web.netguard import Resolve, is_public_url
from portal.modules.kb.web.normalize import canonical_url, fold

log = logging.getLogger(__name__)

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_XML_BYTES = 20_000_000
MAX_CHILDREN = 12
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
_ATOM = "{http://www.w3.org/2005/Atom}"
_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Entry:
    url: str
    when: datetime | None
    title: str = ""


def parse_when(s: str | None) -> datetime | None:
    """ISO (kể cả ngày trần, `Z`), RFC-822, hoặc kiểu Mỹ `M/D/YYYY h:mm:ss AM`. Không mang múi giờ ⇒ giờ VN."""
    if not s:
        return None
    s = s.strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = email.utils.parsedate_to_datetime(s)
        except (TypeError, ValueError):
            try:
                d = datetime.strptime(s, "%m/%d/%Y %I:%M:%S %p")  # RSS tuoitre: 9/30/2026 2:19:00 PM
            except ValueError:
                return None
    return d if d.tzinfo else d.replace(tzinfo=VN)


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_sitemap(xml: bytes) -> tuple[list[Entry], list[Entry]]:
    """Trả `(sitemap con, url)` — index chỉ có vế đầu, urlset chỉ có vế sau. Ném `ET.ParseError` nếu XML hỏng."""
    root = ET.fromstring(xml)
    children = [
        Entry(_text(el.find(f"{_SM}loc")), parse_when(_text(el.find(f"{_SM}lastmod"))))
        for el in root.iter(f"{_SM}sitemap")
    ]
    urls = []
    for el in root.iter(f"{_SM}url"):
        news = el.find(f"{_NEWS}news")
        when = parse_when(_text(news.find(f"{_NEWS}publication_date"))) if news is not None else None
        title = _text(news.find(f"{_NEWS}title")) if news is not None else ""
        urls.append(Entry(_text(el.find(f"{_SM}loc")), when or parse_when(_text(el.find(f"{_SM}lastmod"))), title))
    return [c for c in children if c.url], [u for u in urls if u.url]


def parse_rss(xml: bytes) -> list[Entry]:
    """RSS 2.0 (`<item>`) và Atom (`<entry>`). Ném `ET.ParseError` nếu XML hỏng."""
    root = ET.fromstring(xml)
    out = [
        Entry(_text(it.find("link")), parse_when(_text(it.find("pubDate"))), _text(it.find("title")))
        for it in root.iter("item")
    ]
    for it in root.iter(f"{_ATOM}entry"):
        link = it.find(f"{_ATOM}link")
        when = _text(it.find(f"{_ATOM}published")) or _text(it.find(f"{_ATOM}updated"))
        out.append(
            Entry(link.get("href", "") if link is not None else "", parse_when(when), _text(it.find(f"{_ATOM}title")))
        )
    return [e for e in out if e.url]


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=VN)
    return start, start + timedelta(days=1)


def pick_children(children: list[Entry], day: date, hint: str) -> list[str]:
    """Có `lastmod` thì chọn theo khoảng ngày (bỏ qua gợi ý tên file); không thì so `hint` với URL."""
    start, end = day_bounds(day)
    dated = [c for c in children if c.when is not None]
    if dated:
        chosen = [c.url for c in dated if start - timedelta(days=1) <= c.when <= end + timedelta(days=40)]
    elif hint:
        token = hint.format(y=day.year, m=day.month, mm=f"{day.month:02d}", d=day.day, dd=f"{day.day:02d}")
        chosen = [c.url for c in children if token in c.url]
    else:
        chosen = []
    return chosen[:MAX_CHILDREN]


def _in_day(entry: Entry, day: date) -> bool:
    start, end = day_bounds(day)
    return entry.when is not None and start <= entry.when < end


def looks_bds(entry: Entry, source: SourceSite, keywords: tuple[str, ...]) -> bool:
    """Nguồn có `category_paths` thì chỉ xét đường dẫn URL; không thì xét từ khoá trong URL+tiêu đề."""
    if source.category_paths:
        path = urlsplit(entry.url).path
        return any(path.startswith(p) for p in source.category_paths)
    hay = fold(f"{entry.url} {entry.title}")
    return any(fold(k) in hay for k in keywords)


def category_links(html: str, base_url: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    out: list[str] = []
    for href in _HREF.findall(html):
        u = urljoin(base_url, href)
        if rx.match(u) and u not in out:
            out.append(u)
    return out


class Discoverer:
    def __init__(self, http: httpx.AsyncClient, *, resolve: Resolve | None = None) -> None:
        self._http = http
        self._resolve = resolve

    async def _public(self, url: str) -> bool:
        """Sitemap con/trang mục có thể trỏ đi đâu cũng được — chỉ tải URL công khai."""
        if await is_public_url(url, self._resolve):
            return True
        log.debug("bỏ URL không công khai: %s", url)
        return False

    async def _get(self, url: str) -> bytes | None:
        """Đọc theo stream và dừng ngay khi vượt `MAX_XML_BYTES` — không nạp cả thân rồi mới so."""
        try:
            async with self._http.stream("GET", url, follow_redirects=True) as r:
                if r.status_code != 200:
                    return None
                buf = bytearray()
                async for part in r.aiter_bytes():
                    buf.extend(part)
                    if len(buf) > MAX_XML_BYTES:
                        log.warning("bỏ %s: vượt trần %d byte", url, MAX_XML_BYTES)
                        return None
                return bytes(buf)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            log.warning("không tải được %s: %s", url, exc)
            return None

    async def _sitemap(self, url: str) -> tuple[list[Entry], list[Entry]]:
        body = await self._get(url)
        if body is None:
            return [], []
        try:
            return parse_sitemap(body)
        except ET.ParseError:
            log.warning("sitemap hỏng: %s", url)
            return [], []

    async def day_entries(self, source: SourceSite, day: date, keywords: tuple[str, ...]) -> list[Entry]:
        dated: list[Entry] = []
        if source.sitemap_index:
            children, urls = await self._sitemap(source.sitemap_index)
            dated += urls
            for child in pick_children(children, day, source.child_hint):
                if await self._public(child):
                    dated += (await self._sitemap(child))[1]
        for url in source.news_sitemaps:
            dated += (await self._sitemap(url))[1]
        for url in source.rss:
            body = await self._get(url)
            if body is not None:
                try:
                    dated += parse_rss(body)
                except ET.ParseError:
                    log.warning("rss hỏng: %s", url)
        undated: list[Entry] = []
        for page in source.category_pages:
            body = await self._get(page) if await self._public(page) else None
            if body is not None:
                undated += [
                    Entry(u, None) for u in category_links(body.decode("utf-8", "ignore"), page, source.article_pattern)
                ]
        keep = [e for e in dated if _in_day(e, day)] + undated
        seen: set[str] = set()
        out: list[Entry] = []
        for e in keep:
            key = canonical_url(e.url)
            if key not in seen and looks_bds(e, source, keywords):
                seen.add(key)
                out.append(Entry(key, e.when, e.title))
        return out
