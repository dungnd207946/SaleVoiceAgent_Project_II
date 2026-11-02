from datetime import date, datetime

import httpx
import pytest

from portal.modules.kb.web.config import SourceSite
from portal.modules.kb.web.discover import (
    VN,
    Discoverer,
    Entry,
    category_links,
    day_bounds,
    looks_bds,
    parse_rss,
    parse_sitemap,
    parse_when,
    pick_children,
)

DAY = date(2026, 9, 28)


async def _public(host):
    return ["93.184.216.34"]


INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://ex.vn/sitemaps-2026-9-26-30.xml</loc></sitemap>
<sitemap><loc>https://ex.vn/sitemaps-2026-8-26-31.xml</loc></sitemap></sitemapindex>"""

# bytes literal chỉ nhận ASCII — "Giá chung cư..." phải qua str + encode(), không viết b"""...""" trực tiếp
# (bản trong brief viết b"""...""" với dấu tiếng Việt, đó là SyntaxError thật, đã kiểm bằng python3 -c).
URLSET = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://ex.vn/bat-dong-san/cau-hong-ha-1.html</loc><lastmod>2026-09-28T10:00:00+07:00</lastmod></url>
<url><loc>https://ex.vn/the-thao/bong-da-2.html</loc><lastmod>2026-09-28T11:00:00+07:00</lastmod></url>
<url><loc>https://ex.vn/bat-dong-san/cu-3.html</loc><lastmod>2026-09-27T23:59:00+07:00</lastmod></url>
<url><loc>https://ex.vn/x-4.html</loc><news:news><news:publication_date>2026-09-28T08:00:00+07:00</news:publication_date>
<news:title>Giá chung cư Hà Nội tăng</news:title></news:news></url></urlset>""".encode()

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Tin A</title><link>https://ex.vn/bat-dong-san/a-5.html</link>
<pubDate>Sun, 28 Sep 2026 03:00:00 +0000</pubDate></item>
</channel></rss>"""

SRC = SourceSite(
    domain="ex.vn",
    name="Ex",
    whitelisted=True,
    fetch_mode="http",
    kind="news",
    rss=("https://ex.vn/rss.rss",),
    sitemap_index="https://ex.vn/sitemap.xml",
    child_hint="-{y}-{m}-",
    news_sitemaps=(),
    category_pages=(),
    article_pattern="",
    category_paths=("/bat-dong-san",),
)


def test_parse_when_gan_mui_gio_vn_cho_ngay_tran():
    assert parse_when("2026-09-28").utcoffset().total_seconds() == 7 * 3600
    assert parse_when("khong phai ngay") is None


def test_parse_sitemap_index_va_urlset():
    children, urls = parse_sitemap(INDEX)
    assert len(children) == 2 and urls == []
    _, urls = parse_sitemap(URLSET)
    assert urls[3].title == "Giá chung cư Hà Nội tăng"
    assert urls[3].when is not None


def test_chon_sitemap_con_theo_goi_y_khi_khong_co_lastmod():
    children, _ = parse_sitemap(INDEX)
    assert pick_children(children, DAY, "-{y}-{m}-") == ["https://ex.vn/sitemaps-2026-9-26-30.xml"]


def test_ranh_gioi_ngay_theo_gio_vn():
    start, end = day_bounds(DAY)
    assert start.isoformat() == "2026-09-28T00:00:00+07:00"
    assert (end - start).days == 1


def test_loc_bai_bds_theo_chuyen_muc_hoac_tu_khoa():
    assert looks_bds(Entry("https://ex.vn/bat-dong-san/a.html", None), SRC, ())
    assert not looks_bds(Entry("https://ex.vn/the-thao/a.html", None), SRC, ())
    src2 = SourceSite(**{f: getattr(SRC, f) for f in SRC.__slots__ if f != "category_paths"}, category_paths=())
    assert looks_bds(Entry("https://ex.vn/x-4.html", None, "Giá chung cư Hà Nội tăng"), src2, ("chung cư",))


def test_lay_link_bai_tu_trang_muc():
    html = '<a href="/tin-tuc/abc-123.html">x</a><a href="https://khac.vn/y">y</a><a href="/lien-he">z</a>'
    assert category_links(html, "https://cafeland.vn/tin-tuc/", r"^https://cafeland\.vn/tin-tuc/.+-\d+\.html$") == [
        "https://cafeland.vn/tin-tuc/abc-123.html"
    ]


def test_parse_rss():
    (e,) = parse_rss(RSS)
    assert e.url == "https://ex.vn/bat-dong-san/a-5.html"
    assert e.when.date() == DAY


async def test_day_entries_gom_sitemap_va_rss_dung_ngay_dung_chuyen_muc():
    routes = {
        "https://ex.vn/sitemap.xml": INDEX,
        "https://ex.vn/sitemaps-2026-9-26-30.xml": URLSET,
        "https://ex.vn/rss.rss": RSS,
    }

    def handler(req: httpx.Request) -> httpx.Response:
        body = routes.get(str(req.url))
        return httpx.Response(200, content=body) if body else httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http, resolve=_public).day_entries(SRC, DAY, ("chung cư",))}
    assert got == {"https://ex.vn/bat-dong-san/cau-hong-ha-1.html", "https://ex.vn/bat-dong-san/a-5.html"}


# --- edge case: ranh giới ngày VN cho RSS (RFC-822 có/không offset) ---


def test_parse_when_rfc822_khong_dau_hai_cham_trong_offset():
    d = parse_when("Tue, 29 Sep 2026 23:30:00 +0700")
    assert d.utcoffset().total_seconds() == 7 * 3600
    assert d.hour == 23 and d.minute == 30


async def test_day_entries_ranh_gioi_ngay_qua_rss_23h30_vs_00h30():
    rss = b"""<?xml version="1.0"?><rss><channel>
    <item><title>Trong ngay</title><link>https://ex.vn/bat-dong-san/trong-ngay.html</link>
    <pubDate>Mon, 28 Sep 2026 23:30:00 +0700</pubDate></item>
    <item><title>Sang hom sau</title><link>https://ex.vn/bat-dong-san/hom-sau.html</link>
    <pubDate>Tue, 29 Sep 2026 00:30:00 +0700</pubDate></item>
    </channel></rss>"""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss) if str(req.url) == "https://ex.vn/rss.rss" else httpx.Response(404)

    src = SourceSite(**{f: getattr(SRC, f) for f in SRC.__slots__ if f != "sitemap_index"}, sitemap_index="")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http, resolve=_public).day_entries(src, DAY, ())}
    assert got == {"https://ex.vn/bat-dong-san/trong-ngay.html"}


# --- edge case: gộp trùng URL thấy qua cả sitemap lẫn RSS (khác tham số theo dõi) ---


async def test_day_entries_gop_trung_url_qua_sitemap_va_rss():
    urlset = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://ex.vn/bat-dong-san/trung-6.html?utm_source=fb</loc>
    <lastmod>2026-09-28T09:00:00+07:00</lastmod></url></urlset>"""
    rss = b"""<?xml version="1.0"?><rss><channel>
    <item><title>Trung</title><link>https://ex.vn/bat-dong-san/trung-6.html</link>
    <pubDate>Mon, 28 Sep 2026 10:00:00 +0700</pubDate></item></channel></rss>"""
    routes = {"https://ex.vn/rss.rss": rss}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=routes.get(str(req.url), urlset))

    src = SourceSite(
        **{f: getattr(SRC, f) for f in SRC.__slots__ if f != "news_sitemaps"},
        news_sitemaps=("https://ex.vn/news-sitemap.xml",),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = await Discoverer(http, resolve=_public).day_entries(src, DAY, ())
    urls = [e.url for e in got]
    assert urls.count("https://ex.vn/bat-dong-san/trung-6.html") == 1


# --- edge case: sitemap con lẫn lộn — có lastmod thì bỏ qua nhánh gợi ý tên file ---


def test_pick_children_uu_tien_lastmod_bo_qua_hint_khi_co_hang_khong_co_ngay():
    children = [
        Entry("https://ex.vn/sitemaps-co-ngay.xml", parse_when("2026-09-28T00:00:00+07:00")),
        Entry("https://ex.vn/sitemaps-2026-9-khac.xml", None),
    ]
    assert pick_children(children, DAY, "-{y}-{m}-") == ["https://ex.vn/sitemaps-co-ngay.xml"]


def test_pick_children_khong_lastmod_khong_hint_tra_ve_rong():
    children = [Entry("https://ex.vn/sitemaps-x.xml", None)]
    assert pick_children(children, DAY, "") == []


# --- edge case: XML hỏng ---


def test_parse_sitemap_xml_hong_nem_loi():
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        parse_sitemap(b"<khong dong>")


async def test_day_entries_khong_sap_khi_sitemap_hong():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<khong dong the nao het>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = await Discoverer(http, resolve=_public).day_entries(SRC, DAY, ())
    assert got == []


# --- edge case: lỗi mạng (timeout/500) trên một nguồn không làm sập day_entries ---


async def test_day_entries_khong_sap_khi_mot_nguon_timeout_hoac_500():
    def handler(req: httpx.Request) -> httpx.Response:
        if "sitemap.xml" in str(req.url):
            raise httpx.ConnectTimeout("qua han", request=req)
        if "rss.rss" in str(req.url):
            return httpx.Response(500)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = await Discoverer(http, resolve=_public).day_entries(SRC, DAY, ())
    assert got == []


# --- edge case: trang mục (không ngày) được gộp bất kể mốc ngày, vẫn lọc theo looks_bds ---


async def test_day_entries_trang_muc_khong_can_ngay_van_loc_chuyen_muc():
    html = '<a href="/bat-dong-san/muc-7.html">x</a><a href="/the-thao/khac.html">y</a>'

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://ex.vn/tin-tuc/":
            return httpx.Response(200, content=html.encode())
        return httpx.Response(404)

    override = ("sitemap_index", "rss", "category_pages", "article_pattern")
    src = SourceSite(
        **{f: getattr(SRC, f) for f in SRC.__slots__ if f not in override},
        sitemap_index="",
        rss=(),
        category_pages=("https://ex.vn/tin-tuc/",),
        article_pattern=r"^https://ex\.vn/.+\.html$",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http, resolve=_public).day_entries(src, DAY, ())}
    assert got == {"https://ex.vn/bat-dong-san/muc-7.html"}


# --- edge case: parse_rss cũng hiểu Atom feed ---


def test_parse_rss_hieu_atom_feed():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Atom A</title><link href="https://ex.vn/bat-dong-san/atom-8.html"/>
    <published>2026-09-28T09:00:00+07:00</published></entry></feed>"""
    (e,) = parse_rss(atom)
    assert e.url == "https://ex.vn/bat-dong-san/atom-8.html"
    assert e.title == "Atom A"
    assert e.when.date() == DAY


def test_looks_bds_khong_category_khong_khop_tu_khoa_tra_ve_false():
    src2 = SourceSite(**{f: getattr(SRC, f) for f in SRC.__slots__ if f != "category_paths"}, category_paths=())
    assert not looks_bds(Entry("https://ex.vn/x-9.html", None, "Tin the thao"), src2, ("chung cư",))


def test_parse_when_kieu_my_12_gio_cua_tuoitre_la_gio_vn():
    assert parse_when("9/30/2026 2:19:00 PM") == datetime(2026, 9, 30, 14, 19, tzinfo=VN)
    assert parse_when("9/30/2026 12:05:00 AM") == datetime(2026, 9, 30, 0, 5, tzinfo=VN)
    assert parse_when("13/30/2026 2:19:00 PM") is None


# --- trần kích thước XML: dừng đọc stream sớm, không tải hết thân rồi mới so ---


class _CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunk: bytes, n: int) -> None:
        self.chunk = chunk
        self.n = n
        self.yielded = 0

    async def __aiter__(self):
        for _ in range(self.n):
            self.yielded += 1
            yield self.chunk

    async def aclose(self) -> None:
        pass


async def test_get_vuot_tran_xml_dung_doc_stream_som(monkeypatch):
    import portal.modules.kb.web.discover as discover_mod

    monkeypatch.setattr(discover_mod, "MAX_XML_BYTES", 1_000_000)
    stream = _CountingStream(b"<" * 200_000, n=100)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))) as http:
        assert await Discoverer(http, resolve=_public)._get("https://ex.vn/sitemap.xml") is None
    assert stream.yielded < 10


async def test_get_duoi_tran_tra_du_than_va_khong_200_tra_none():
    body = b"<urlset/>" * 1000
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))) as http:
        assert await Discoverer(http, resolve=_public)._get("https://ex.vn/a.xml") == body
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404, content=body))) as http:
        assert await Discoverer(http, resolve=_public)._get("https://ex.vn/a.xml") is None


async def test_get_theo_redirect():
    def handler(r):
        if r.url.path == "/old.xml":
            return httpx.Response(301, headers={"location": "https://ex.vn/new.xml"})
        return httpx.Response(200, content=b"<rss/>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await Discoverer(http, resolve=_public)._get("https://ex.vn/old.xml") == b"<rss/>"


# --- sitemap con và trang mục đến từ bên ngoài: chỉ tải URL công khai ---


async def test_sitemap_con_tro_vao_dia_chi_noi_bo_khong_duoc_tai():
    index = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>http://169.254.169.254/sitemaps-2026-9-26-30.xml</loc></sitemap>
    <sitemap><loc>https://ex.vn/sitemaps-2026-9-26-30.xml</loc></sitemap></sitemapindex>"""
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if str(req.url) == "https://ex.vn/sitemap.xml":
            return httpx.Response(200, content=index)
        if str(req.url) == "https://ex.vn/sitemaps-2026-9-26-30.xml":
            return httpx.Response(200, content=URLSET)
        return httpx.Response(404)

    src = SourceSite(**{f: getattr(SRC, f) for f in SRC.__slots__ if f != "rss"}, rss=())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http, resolve=_public).day_entries(src, DAY, ())}
    assert "https://ex.vn/bat-dong-san/cau-hong-ha-1.html" in got
    assert not [u for u in seen if "169.254" in u]


async def test_trang_muc_noi_bo_khong_duoc_tai():
    async def internal(host):
        return ["10.0.0.3"] if host == "noibo.vn" else ["93.184.216.34"]

    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, content=b'<a href="/bat-dong-san/a-1.html">x</a>')

    override = ("sitemap_index", "rss", "category_pages", "article_pattern")
    src = SourceSite(
        **{f: getattr(SRC, f) for f in SRC.__slots__ if f not in override},
        sitemap_index="",
        rss=(),
        category_pages=("http://127.0.0.1/tin/", "https://noibo.vn/tin/", "https://ex.vn/tin/"),
        article_pattern=r"^https://.+\.html$",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http, resolve=internal).day_entries(src, DAY, ())}
    assert seen == ["https://ex.vn/tin/"]
    assert got == {"https://ex.vn/bat-dong-san/a-1.html"}
