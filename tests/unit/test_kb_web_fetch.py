"""Tầng 1 (http tĩnh): tải trang + bóc nội dung. Không container, mọi HTTP qua MockTransport."""

import asyncio
import time

import httpx
import pytest

from portal.modules.kb.web.fetch import Fetcher, extract, looks_challenged

DOAN = (
    "Đại lộ Thăng Long mở rộng đoạn qua huyện Đan Phượng đã hoàn thành phần mặt đường "
    "với mười làn xe, giúp thời gian di chuyển từ khu vực phía tây vào trung tâm Hà Nội giảm đáng kể. "
)
BAI = (
    "<html><head><title>Đại lộ mở rộng</title>"
    '<meta property="article:published_time" content="2026-09-28T08:00:00+07:00"></head>'
    "<body><article><h1>Đại lộ mở rộng</h1>"
    + "".join(f"<p>{DOAN * 3}</p>" for _ in range(6))
    + "</article></body></html>"
)


async def _public(host):
    return ["93.184.216.34"]


def _fetcher(handler, **kw) -> Fetcher:
    kw.setdefault("resolve", _public)
    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), delay_sec=0, **kw)


# ─── looks_challenged ─────────────────────────────────────────────────────────


def test_nhan_ra_trang_challenge():
    assert looks_challenged(200, '<html><body><script>document.cookie="D1N=1";window.location.reload(true);</script>')
    assert looks_challenged(403, "<title>Just a moment...</title>")
    assert not looks_challenged(200, BAI)


def test_503_trang_nho_cung_bi_coi_la_challenge():
    # 403/503 kèm thân trang NGẮN (< 20_000 ký tự) — dấu hiệu gián tiếp của trang chặn,
    # kể cả khi không khớp marker nào (đúng nhánh fallback theo status code).
    assert looks_challenged(503, "<html><body>Access denied</body></html>")


def test_503_trang_dai_khong_bi_coi_la_challenge():
    # cùng status 503 nhưng thân trang đủ dài (>= 20_000) thì không suy diễn — có thể
    # là lỗi server thoáng qua trên một trang thật, không phải trang chặn bot.
    assert not looks_challenged(503, "<html>" + "x" * 20_000 + "</html>")


# ─── extract (hàm thuần, CPU-bound — Fetcher gọi qua to_thread) ───────────────


def test_extract_bai_binh_thuong():
    title, text, when = extract(BAI, "https://ex.vn/a.html")
    assert title == "Đại lộ mở rộng"
    assert "mười làn xe" in text
    assert when is not None
    assert (when.year, when.month, when.day) == (2026, 9, 28)


def test_extract_html_rong_khong_nem_loi():
    assert extract("<html><body></body></html>", "https://ex.vn/z") == ("", "", None)


def test_extract_khong_phai_html_khong_nem_loi():
    assert extract('{"a": 1, "b": 2}', "https://ex.vn/z.json") == ("", "", None)


# ─── Fetcher.fetch — trang bình thường ────────────────────────────────────────


async def test_bai_binh_thuong_ra_ok_co_noi_dung():
    f = await _fetcher(lambda r: httpx.Response(200, text=BAI)).fetch("https://ex.vn/a.html")
    assert f.status == "ok"
    assert f.title == "Đại lộ mở rộng"
    assert "mười làn xe" in f.text
    assert f.published_at is not None


# ─── challenge / lỗi mạng / lỗi HTTP ───────────────────────────────────────────


async def test_trang_chan_bot_ra_needs_browser():
    f = await _fetcher(lambda r: httpx.Response(403, text="<title>Just a moment...</title>")).fetch("https://ex.vn/b")
    assert f.status == "needs_browser"


async def test_404_va_loi_mang_ra_fetch_failed():
    assert (await _fetcher(lambda r: httpx.Response(404)).fetch("https://ex.vn/c")).status == "fetch_failed"

    def hong(r):
        raise httpx.ConnectError("x")

    assert (await _fetcher(hong).fetch("https://ex.vn/d")).status == "fetch_failed"


async def test_500_ra_fetch_failed():
    assert (await _fetcher(lambda r: httpx.Response(500, text="lỗi server")).fetch("https://ex.vn/e500")).status == (
        "fetch_failed"
    )


async def test_timeout_ra_fetch_failed():
    def hong(r):
        raise httpx.ReadTimeout("timeout")

    assert (await _fetcher(hong).fetch("https://ex.vn/timeout")).status == "fetch_failed"


async def test_content_type_khong_phai_html_ra_fetch_failed():
    def handler(r):
        return httpx.Response(200, json={"a": 1, "b": 2})

    assert (await _fetcher(handler).fetch("https://ex.vn/data.json")).status == "fetch_failed"


async def test_url_qua_dai_ra_fetch_failed_khong_nem():
    # httpx.InvalidURL KHÔNG kế thừa httpx.HTTPError — nếu Fetcher chỉ bắt HTTPError,
    # url hỏng dạng này thoát ra ngoài fetch() thành exception chưa bắt.
    url = "http://" + "a" * 70_000 + ".com/x"
    f = await _fetcher(lambda r: httpx.Response(200, text=BAI)).fetch(url)
    assert f.status == "fetch_failed"


async def test_extract_nem_loi_ra_fetch_failed_khong_nem(monkeypatch):
    import portal.modules.kb.web.fetch as fetch_mod

    def hong(html, url):
        raise RuntimeError("bóc nội dung hỏng")

    monkeypatch.setattr(fetch_mod, "extract", hong)
    f = await _fetcher(lambda r: httpx.Response(200, text=BAI)).fetch("https://ex.vn/hong-extract")
    assert f.status == "fetch_failed"


# ─── trần kích thước — CHẶN STREAM SỚM, không tải hết ─────────────────────────


async def test_trang_qua_lon_ra_fetch_failed():
    big = "a" * 3_100_000
    assert (await _fetcher(lambda r: httpx.Response(200, text=big)).fetch("https://ex.vn/e")).status == "fetch_failed"


class _CountingStream(httpx.AsyncByteStream):
    """Stream 50 MB tổng (100 khối 500KB) — nếu Fetcher đọc hết mới cắt thì `yielded` sẽ ra 100."""

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


async def test_vuot_tran_dung_doc_stream_som_khong_tai_het():
    stream = _CountingStream(b"a" * 500_000, n=100)

    def handler(r):
        return httpx.Response(200, stream=stream)

    f = await _fetcher(handler).fetch("https://ex.vn/big-stream")
    assert f.status == "fetch_failed"
    # 3_000_000 / 500_000 = 6 khối phủ trần; dừng quanh đó, không đọc hết 100 khối.
    assert stream.yielded < 20


# ─── redirect ──────────────────────────────────────────────────────────────────


async def test_redirect_duoc_di_theo():
    def handler(r):
        if r.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://ex.vn/new"})
        return httpx.Response(200, text=BAI)

    f = await _fetcher(handler).fetch("https://ex.vn/old")
    assert f.status == "ok"
    assert f.url == "https://ex.vn/old"


# ─── cổng theo domain: giới hạn đồng thời + không chặn domain khác ────────────


async def test_gate_gioi_han_dong_thoi_theo_domain():
    per_domain = 2
    in_flight = 0
    max_seen = 0

    async def handler(r):
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, text=BAI)

    f = _fetcher(handler, per_domain=per_domain)
    urls = [f"https://cung-mien.vn/p{i}" for i in range(6)]
    await asyncio.gather(*(f.fetch(u) for u in urls))
    assert max_seen == per_domain


async def test_gate_khong_chan_domain_khac():
    finished: list[str] = []

    async def handler(r):
        if r.url.host == "cham.vn":
            await asyncio.sleep(0.2)
        finished.append(r.url.host)
        return httpx.Response(200, text=BAI)

    f = _fetcher(handler, per_domain=1)
    slow = asyncio.create_task(f.fetch("https://cham.vn/a"))
    await asyncio.sleep(0.01)  # để request chậm chiếm gate của domain nó trước
    fast = await f.fetch("https://nhanh.vn/b")
    assert fast.status == "ok"
    # domain khác hoàn tất TRƯỚC domain chậm — chứng minh gate không chia sẻ giữa hai domain
    assert finished == ["nhanh.vn"]
    await slow


async def test_delay_gian_cach_hai_luot_cung_domain():
    delay = 0.05
    times: list[float] = []

    async def handler(r):
        times.append(time.monotonic())
        return httpx.Response(200, text=BAI)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    f = Fetcher(http, per_domain=1, delay_sec=delay, resolve=_public)
    await asyncio.gather(f.fetch("https://giancach.vn/a"), f.fetch("https://giancach.vn/b"))
    assert len(times) == 2
    # lượt hai không được bắt đầu sớm hơn khoảng `delay` tính từ lượt một — gate giữ đúng
    # trong finally NÊN vẫn chiếm chỗ lúc sleep, lượt hai chỉ vào được sau khi ngủ xong.
    assert times[1] - times[0] >= delay * 0.8


# ─── chặn URL nội bộ + trần redirect ────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://localhost:6379/",
        "ftp://ex.vn/x",
    ],
)
async def test_url_noi_bo_bi_chan_khong_gui_request(url):
    seen = []

    def handler(r):
        seen.append(str(r.url))
        return httpx.Response(200, text=BAI)

    f = await _fetcher(handler).fetch(url)
    assert f.status == "fetch_failed"
    assert seen == []


async def test_ten_mien_phan_giai_ra_ip_noi_bo_bi_chan():
    async def internal(host):
        return ["192.168.1.10"]

    seen = []
    f = await _fetcher(lambda r: seen.append(r) or httpx.Response(200, text=BAI), resolve=internal).fetch(
        "https://ex.vn/a"
    )
    assert f.status == "fetch_failed" and seen == []


async def test_redirect_sang_ip_noi_bo_bi_chan():
    seen = []

    def handler(r):
        seen.append(str(r.url))
        if r.url.host == "ex.vn":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text=BAI)

    f = await _fetcher(handler).fetch("https://ex.vn/old")
    assert f.status == "fetch_failed"
    assert seen == ["https://ex.vn/old"], "không được theo sang địa chỉ nội bộ"


async def test_redirect_tuong_doi_van_duoc_kiem_va_di_theo():
    def handler(r):
        if r.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text=BAI)

    assert (await _fetcher(handler).fetch("https://ex.vn/a")).status == "ok"


async def test_redirect_qua_5_buoc_ra_fetch_failed():
    seen = []

    def handler(r):
        seen.append(r.url.path)
        n = int(r.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"location": f"https://ex.vn/{n + 1}"})

    f = await _fetcher(handler).fetch("https://ex.vn/0")
    assert f.status == "fetch_failed"
    assert len(seen) == 6, "lượt đầu + đúng 5 lần theo redirect"


async def test_redirect_dung_5_buoc_van_tai_duoc():
    def handler(r):
        n = int(r.url.path.strip("/") or 0)
        if n < 5:
            return httpx.Response(302, headers={"location": f"https://ex.vn/{n + 1}"})
        return httpx.Response(200, text=BAI)

    assert (await _fetcher(handler).fetch("https://ex.vn/0")).status == "ok"
