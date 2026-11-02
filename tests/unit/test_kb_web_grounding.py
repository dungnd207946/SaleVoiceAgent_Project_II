"""Grounding qua Gemini + trần lượt gọi mỗi ngày. Không container: bộ đếm Redis test
bằng một FAKE tối giản (incrby/expire/ttl) — file này ở `tests/unit`, không Docker."""

from datetime import date, timedelta

import httpx
import pytest

from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.grounding import VN, Grounding, GroundingBudget, GroundingUnreachable, _key_for

REDIR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA"
REDIR2 = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB"


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.host == "generativelanguage.googleapis.com":
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "groundingMetadata": {
                            "groundingChunks": [
                                {"web": {"uri": REDIR, "title": "mytour.vn"}},
                                {"web": {"uri": "https://thang.vn/x", "title": "thang.vn"}},
                            ]
                        }
                    }
                ]
            },
        )
    if str(req.url) == REDIR:
        return httpx.Response(302, headers={"location": "https://mytour.vn/bai-viet/truong-dan-phuong"})
    return httpx.Response(404)


async def _public(host):
    return ["93.184.216.34"]


def _g(handler, cap=10, redis=None, resolve=_public) -> Grounding:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Grounding(
        api_key="k", http=http, budget=GroundingBudget(redis, cap=cap), model="gemini-2.5-flash", resolve=resolve
    )


# ─── Đúng ba bài của brief ───────────────────────────────────────────────────


async def test_tra_url_goc_tu_header_location():
    assert await _g(_handler).search("trường học Đan Phượng") == [
        "https://mytour.vn/bai-viet/truong-dan-phuong",
        "https://thang.vn/x",
    ]


async def test_het_tran_ngay_thi_khong_goi():
    g = _g(_handler, cap=1)
    assert await g.search("q1")
    assert await g.search("q2") == []


async def test_429_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _g(lambda r: httpx.Response(429)).search("q")


# ─── Edge case bổ sung: mã lỗi HTTP ─────────────────────────────────────────


async def test_5xx_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _g(lambda r: httpx.Response(503)).search("q")


async def test_4xx_khac_khong_phai_loi_tam_thoi():
    """400/403 là lỗi CỦA CHÍNH REQUEST (key sai, payload sai) — thử lại vô ích, không
    phải `TemporaryError`."""
    with pytest.raises(httpx.HTTPStatusError):
        await _g(lambda r: httpx.Response(400)).search("q")


async def test_loi_mang_khi_goi_gemini_la_tam_thoi():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    with pytest.raises(GroundingUnreachable):
        await _g(handler).search("q")
    assert issubclass(GroundingUnreachable, TemporaryError)


# ─── Edge case: hình dạng response thiếu/rỗng ──────────────────────────────


async def test_khong_co_candidates_tra_rong():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert await _g(handler).search("q") == []


async def test_candidates_rong_tra_rong():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    assert await _g(handler).search("q") == []


async def test_thieu_grounding_metadata_tra_rong():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {}}]})

    assert await _g(handler).search("q") == []


# ─── Edge case: resolve redirect ────────────────────────────────────────────


async def test_redirect_khong_co_location_bi_bo_qua_link_khac_van_giu():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "groundingMetadata": {
                                "groundingChunks": [
                                    {"web": {"uri": REDIR}},
                                    {"web": {"uri": "https://ok.vn/a"}},
                                ]
                            }
                        }
                    ]
                },
            )
        if str(req.url) == REDIR:
            return httpx.Response(302)  # không có header location
        return httpx.Response(404)

    assert await _g(handler).search("q") == ["https://ok.vn/a"]


async def test_redirect_khong_phai_302_bi_bo_qua():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={"candidates": [{"groundingMetadata": {"groundingChunks": [{"web": {"uri": REDIR}}]}}]},
            )
        if str(req.url) == REDIR:
            return httpx.Response(200, text="not a redirect")
        return httpx.Response(404)

    assert await _g(handler).search("q") == []


async def test_loi_mang_khi_resolve_mot_link_bi_bo_qua_link_khac_van_giu():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "groundingMetadata": {
                                "groundingChunks": [
                                    {"web": {"uri": REDIR}},
                                    {"web": {"uri": REDIR2}},
                                ]
                            }
                        }
                    ]
                },
            )
        if str(req.url) == REDIR:
            raise httpx.ConnectError("boom", request=req)
        if str(req.url) == REDIR2:
            return httpx.Response(302, headers={"location": "https://good.vn/a"})
        return httpx.Response(404)

    assert await _g(handler).search("q") == ["https://good.vn/a"]


async def test_non_vertexaisearch_uri_giu_nguyen():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://a.vn/b"}}]}}]},
        )

    assert await _g(handler).search("q") == ["https://a.vn/b"]


async def test_url_goc_trung_lap_duoc_gop():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "groundingMetadata": {
                                "groundingChunks": [
                                    {"web": {"uri": REDIR}},
                                    {"web": {"uri": REDIR2}},
                                ]
                            }
                        }
                    ]
                },
            )
        if str(req.url) in (REDIR, REDIR2):
            return httpx.Response(302, headers={"location": "https://cung-mot-bai.vn/x"})
        return httpx.Response(404)

    assert await _g(handler).search("q") == ["https://cung-mot-bai.vn/x"]


# ─── Grounding: khởi tạo ────────────────────────────────────────────────────


async def test_khong_co_api_key_nem_value_error():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError):
        Grounding(api_key="", http=http, budget=GroundingBudget(cap=1), model="gemini-2.5-flash")


# ─── GroundingBudget: nhánh cục bộ (không Redis) ────────────────────────────


async def test_budget_cuc_bo_cho_dung_cap_lan_roi_tu_choi():
    b = GroundingBudget(cap=2)
    assert await b.take()
    assert await b.take()
    assert not await b.take()
    assert not await b.take(), "từ chối rồi vẫn phải tiếp tục từ chối, không hồi phục"


async def test_budget_cuc_bo_take_n_lon_hon_1():
    b = GroundingBudget(cap=5)
    assert await b.take(3)
    assert not await b.take(3), "3 + 3 > 5"
    assert await b.take(2), "3 + 2 == 5, còn vừa đủ"


async def test_het_tran_khong_goi_http_that_su():
    """Cap=0 nghĩa là từ chối ngay lượt đầu — `search` không được chạm HTTP."""
    called = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    g = _g(handler, cap=0)
    assert await g.search("q") == []
    assert not called


# ─── GroundingBudget: nhánh Redis (fake tối giản, không container) ─────────


class FakeRedis:
    """Đủ ba lệnh `GroundingBudget` cần: incrby/expire/ttl. Không TTL thật (không hết
    hạn tự nhiên) — bài test tự kiểm tra giá trị `_ttls` thay vì chờ đồng hồ."""

    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._ttls: dict[str, int] = {}

    async def incrby(self, key: str, n: int = 1) -> int:
        self._values[key] = self._values.get(key, 0) + n
        return self._values[key]

    async def expire(self, key: str, seconds: int) -> None:
        self._ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)


async def test_budget_redis_cho_dung_cap_lan_roi_tu_choi():
    r = FakeRedis()
    b = GroundingBudget(r, cap=2)
    assert await b.take()
    assert await b.take()
    assert not await b.take()


async def test_budget_redis_dat_ttl_ngay_lan_dau():
    r = FakeRedis()
    b = GroundingBudget(r, cap=5)
    await b.take()
    key = _key_for(datetime_now_vn_date())
    assert r._ttls.get(key, 0) > 0


def datetime_now_vn_date() -> date:
    from datetime import datetime

    return datetime.now(VN).date()


async def test_budget_redis_ngay_khac_nhau_dem_rieng():
    """Bộ đếm khoá theo NGÀY (giờ VN) — key của hôm qua đầy không ảnh hưởng hôm nay."""
    r = FakeRedis()
    hom_qua = _key_for(datetime_now_vn_date() - timedelta(days=1))
    r._values[hom_qua] = 999  # đã vượt xa mọi cap hợp lý

    b = GroundingBudget(r, cap=1)
    assert await b.take(), "key hôm nay còn trống, phải cho qua"


async def test_budget_redis_va_lai_ttl_mat():
    """Tiến trình chết giữa `incrby` và `expire` lần trước để lại key KHÔNG hạn — lượt
    gọi kế tiếp phải phát hiện (`ttl < 0`) và vá lại, không để nó sống vĩnh viễn."""
    r = FakeRedis()
    key = _key_for(datetime_now_vn_date())
    r._values[key] = 1  # đã có giá trị nhưng KHÔNG có ttl (mồ côi)
    assert await r.ttl(key) == -1

    b = GroundingBudget(r, cap=10)
    assert await b.take()
    assert await r.ttl(key) > 0, "phải vá lại hạn cho bộ đếm mồ côi"


async def test_budget_redis_tu_choi_van_tang_bo_dem_khong_lui_lai():
    """Nhánh Redis: `INCRBY` chạy trước khi kiểm, nên một lượt bị từ chối VẪN làm bộ
    đếm tăng (không giữ nguyên ở đúng `cap`) — khác nhánh cục bộ. Đây là đánh đổi có
    chủ ý để giữ thao tác atomic dưới nhiều tiến trình (xem docstring `GroundingBudget`).
    Bài này chỉ canh rằng hành vi đó ổn định: từ chối một lần thì các lượt sau trong
    cùng ngày vẫn tiếp tục bị từ chối, không có gì "hồi phục" ngoài ý muốn."""
    r = FakeRedis()
    key = _key_for(datetime_now_vn_date())
    b = GroundingBudget(r, cap=1)
    assert await b.take()
    assert not await b.take()
    assert not await b.take()
    assert r._values[key] > 1, "bộ đếm vượt cap sau các lượt bị từ chối — hành vi đã biết"


async def test_exhausted_bat_khi_het_tran_va_grounding_bao_ra_ngoai():
    g = _g(_handler, cap=1)
    assert not g.exhausted
    await g.search("q1")
    assert not g.exhausted
    assert await g.search("q2") == []
    assert g.exhausted


async def test_exhausted_budget_cuc_bo_theo_lan_take_gan_nhat():
    b = GroundingBudget(cap=3)
    assert await b.take(2) and not b.exhausted
    assert not await b.take(2) and b.exhausted
    assert await b.take(1) and not b.exhausted


# ─── Chặn đích redirect không công khai ─────────────────────────────────────


def _one_redirect(target: str, seen: list[str]):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "groundingMetadata": {
                                "groundingChunks": [{"web": {"uri": REDIR}}, {"web": {"uri": "https://thang.vn/x"}}]
                            }
                        }
                    ]
                },
            )
        if str(req.url) == REDIR:
            return httpx.Response(302, headers={"location": target})
        return httpx.Response(404)

    return handler


@pytest.mark.parametrize(
    "target", ["http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/x", "http://localhost/x", "ftp://a.vn/x"]
)
async def test_dich_redirect_noi_bo_bi_bo_qua(target):
    seen: list[str] = []
    assert await _g(_one_redirect(target, seen)).search("q") == ["https://thang.vn/x"]
    assert target not in seen


async def test_dich_redirect_phan_giai_ra_ip_noi_bo_bi_bo_qua():
    async def internal(host):
        return ["192.168.0.9"] if host == "noi-bo.vn" else ["93.184.216.34"]

    seen: list[str] = []
    got = await _g(_one_redirect("https://noi-bo.vn/x", seen), resolve=internal).search("q")
    assert got == ["https://thang.vn/x"]


async def test_link_redirect_tro_vao_ip_noi_bo_khong_duoc_goi():
    bad = "http://127.0.0.1/grounding-api-redirect/X"
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200, json={"candidates": [{"groundingMetadata": {"groundingChunks": [{"web": {"uri": bad}}]}}]}
            )
        return httpx.Response(302, headers={"location": "https://ok.vn/a"})

    assert await _g(handler).search("q") == []
    assert bad not in seen


async def test_ghi_luot_tra_va_token_vao_bo_dem():
    from portal.modules.kb.web.usage import metering

    def handler(req):
        if req.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [{}],
                    "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 7, "thoughtsTokenCount": 3},
                },
            )
        return httpx.Response(404)

    with metering() as m:
        await _g(handler).search("q")
        await _g(handler, cap=0).search("q")
    assert m.tallies[("search", "google", "gemini-2.5-flash")].units == 1
    t = m.tallies[("llm", "google", "gemini-2.5-flash")]
    assert (t.input_tokens, t.output_tokens) == (30, 10)
