"""`Prober` — thử nguồn mới: tìm kênh bài, đếm bài, tải thử; http trước, trình duyệt sau."""

import asyncio
from datetime import date

import httpx
import pytest

from portal.modules.kb.web.discover import Discoverer
from portal.modules.kb.web.fetch import Fetched
from portal.modules.kb.web.probe import Prober

TODAY = date(2026, 10, 5)
HOME = "https://bao.vn/"


def _item(path, when, title):
    return f"<item><link>https://bao.vn/{path}</link><pubDate>{when}</pubDate><title>{title}</title></item>"


RSS = (
    '<?xml version="1.0"?><rss><channel>'
    + "".join(
        [
            _item("bat-dong-san/du-an-moi-123.html", "Mon, 05 Oct 2026 08:00:00 +0700", "Dự án mới"),
            _item("bat-dong-san/gia-nha-124.html", "Sun, 04 Oct 2026 08:00:00 +0700", "Giá nhà"),
            _item("the-thao/bong-da-125.html", "Mon, 05 Oct 2026 08:00:00 +0700", "Bóng đá"),
        ]
    )
    + "</channel></rss>"
)
HOME_HTML = (
    "<html><head><title>Báo Vui - Tin tức</title>"
    '<link rel="alternate" type="application/rss+xml" href="/rss/bds.rss"></head><body></body></html>'
)


async def _public(host):
    return ["93.184.216.34"]


class FakeFetcher:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def fetch(self, url, mode="http"):
        self.calls.append((url, mode))
        return Fetched(url, "ok" if self.ok else "fetch_failed", "t", "nội dung")


class FakeBrowser:
    available = True

    def __init__(self, html="", status=200):
        self._html, self._status = html, status
        self.calls = []

    async def html(self, url):
        self.calls.append(url)
        return (self._html, self._status) if self._html else None


def _prober(routes: dict, *, fetcher=None, browser=None):
    def handler(r: httpx.Request):
        key = str(r.url)
        if key in routes:
            v = routes[key]
            return v if isinstance(v, httpx.Response) else httpx.Response(200, text=v)
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Prober(
        http=http,
        discover=Discoverer(http, resolve=_public),
        fetcher=fetcher or FakeFetcher(),
        browser=browser,
        resolve=_public,
    )


async def test_rss_khai_trong_html_ra_ok_dem_bai_va_tai_thu():
    f = FakeFetcher()
    p = _prober({HOME: HOME_HTML, "https://bao.vn/rss/bds.rss": RSS}, fetcher=f)
    r = await p.probe("bao.vn", today=TODAY)
    assert r.status == "ok" and r.site.kind == "news" and r.site.fetch_mode == "http"
    assert r.site.rss == ("https://bao.vn/rss/bds.rss",) and r.site.name == "Báo Vui"
    assert r.articles == 2, "bài bóng đá bị lọc từ khoá BĐS"
    assert r.pages_tested == 2 and r.pages_ok == 2
    assert [m for _, m in f.calls] == ["http", "http"]


async def test_trang_chan_va_khong_co_trinh_duyet_thi_blocked():
    p = _prober({HOME: httpx.Response(403, text="<title>Just a moment...</title>")})
    r = await p.probe(HOME, today=TODAY)
    assert r.status == "blocked" and r.site is None and "trình duyệt" in r.note


async def test_trang_chan_http_nhung_trinh_duyet_qua_thi_fetch_mode_browser():
    b = FakeBrowser(HOME_HTML)
    p = _prober(
        {HOME: httpx.Response(403, text="<title>Just a moment...</title>"), "https://bao.vn/rss/bds.rss": RSS},
        browser=b,
    )
    r = await p.probe(HOME, today=TODAY)
    assert r.status == "ok" and r.site.fetch_mode == "browser" and b.calls == [HOME]
    assert "trình duyệt" in r.note


async def test_khong_kenh_bai_thi_no_feed_va_theo_doi_nhu_trang_co_dinh():
    p = _prober({HOME: "<html><title>Sở Quy hoạch</title><body>Thông báo</body></html>"})
    r = await p.probe(HOME, today=TODAY)
    assert r.status == "no_feed" and r.site.kind == "living" and r.site.rss == () and r.articles == 0


async def test_trang_muc_co_link_bai_thi_thanh_category_page():
    links = "".join(f'<a href="/tin-tuc/bai-so-{i}-{1000 + i}.html">b</a>' for i in range(6))
    url = "https://bao.vn/tin-tuc/"
    p = _prober({url: f"<html><title>Tin</title><body>{links}</body></html>"})
    r = await p.probe(url, today=TODAY)
    assert r.status == "ok" and r.site.category_pages == (url,)
    assert r.site.article_pattern == r"^https://(www\.)?bao\.vn/.+-\d+\.html?$"
    assert r.pages_tested == 2


async def test_dem_bai_qua_han_van_ok_va_bao_chua_dem():
    """Sitemap index lớn (cafeland) đi hết sitemap con mất hơn trần — nguồn vẫn dùng được, chỉ chưa đếm."""
    links = "".join(f'<a href="/tin-tuc/bai-so-{i}-{1000 + i}.html">b</a>' for i in range(6))
    html = HOME_HTML.replace("<body></body>", f"<body>{links}</body>")
    f = FakeFetcher()
    p = _prober({HOME: html, "https://bao.vn/rss/bds.rss": RSS}, fetcher=f)

    async def slow_entries(site, day, keywords):
        await asyncio.sleep(5)
        return []

    p._discover.day_entries = slow_entries
    r = await p.probe(HOME, today=TODAY, timeout=1.0)
    assert r.status == "ok" and r.articles == 0 and "chưa đếm" in r.note
    assert r.pages_tested == 2 and r.pages_ok == 2, "vẫn thử tải bài lấy từ link trang chủ"


async def test_tim_thay_bai_nhung_khong_doc_duoc_thi_blocked():
    p = _prober({HOME: HOME_HTML, "https://bao.vn/rss/bds.rss": RSS}, fetcher=FakeFetcher(ok=False))
    r = await p.probe(HOME, today=TODAY)
    assert r.status == "blocked" and r.articles == 2 and r.pages_ok == 0


async def test_url_noi_bo_thi_private():
    p = _prober({})
    assert (await p.probe("http://10.0.0.5/x", today=TODAY)).status == "private"


async def test_qua_han_thi_timeout():
    async def slow(r):
        await asyncio.sleep(1)
        return httpx.Response(200, text=HOME_HTML)

    http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    p = Prober(http=http, discover=Discoverer(http, resolve=_public), fetcher=FakeFetcher(), resolve=_public)
    r = await p.probe(HOME, today=TODAY, timeout=0.2)
    assert r.status == "timeout"


@pytest.mark.parametrize("raw", ["bao.vn", "http://bao.vn", "https://bao.vn/"])
async def test_chuan_hoa_url_thieu_scheme(raw):
    p = _prober(
        {
            "https://bao.vn/": HOME_HTML,
            "http://bao.vn/": HOME_HTML,
            "https://bao.vn/rss/bds.rss": RSS,
            "http://bao.vn/rss/bds.rss": RSS,
        }
    )
    assert (await p.probe(raw, today=TODAY)).status == "ok"
