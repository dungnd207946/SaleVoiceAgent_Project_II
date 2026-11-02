"""Client embed — MockTransport, không gọi mạng thật trong CI.

Ba thứ được canh ở đây vì sai chúng thì hoặc 400 im lặng ở worker, hoặc không lỗi nào
mà chỉ có kết quả tìm kiếm tệ: `side="index"`, bearer token, và ảnh gửi dạng base64.

Miền giá trị đo trên service thật 2026-08-12 — `side` chỉ nhận `index|query`, và
`kind=sparse` trả về dưới khoá `sparse`, KHÔNG phải `embeddings`.
"""

import httpx
import pytest

from portal.modules.kb import settings
from portal.modules.kb.clients import embed as embed_mod
from portal.modules.kb.clients.embed import EmbedClient


def _client(handler) -> EmbedClient:
    c = EmbedClient(base_url="https://embed.test", token="tok")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.fixture
def cho(monkeypatch) -> list[float]:
    """Ghi lại các lần chờ thay vì chờ thật — backoff 1s+2s biến mỗi test retry thành
    3 giây. Trả list để test khẳng định ĐÚNG dãy backoff, không chỉ "có chờ"."""
    ghi: list[float] = []

    async def _fake(giay: float) -> None:
        ghi.append(giay)

    monkeypatch.setattr(embed_mod, "_cho", _fake)
    return ghi


async def test_dense_gui_side_index_va_token():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        ghi["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"embeddings": [[0.1] * 1024]})

    ra = await _client(handler).dense(["xin chào"])
    assert ghi["body"]["side"] == "index"
    assert ghi["body"]["kind"] == "dense"
    assert ghi["auth"] == "Bearer tok"
    assert len(ra[0]) == 1024


async def test_sparse_doc_duoc_khoa_sparse():
    """Service trả sparse dưới khoá `sparse`, dense dưới `embeddings` — hai khoá khác
    nhau. Chỉ đọc `embeddings` thì mọi lời gọi sparse raise ở tầng parse."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sparse": [{"indices": [3, 9], "values": [0.5, 0.2]}], "count": 1})

    ra = await _client(handler).sparse(["căn hộ 2 phòng ngủ"])
    assert ra[0]["indices"] == [3, 9]


async def test_visual_image_tai_anh_roi_gui_base64():
    """Service từ chối URL (400 "images không phải base64"), nên client phải tải ảnh
    về và encode — gửi thẳng URL là mọi ảnh im lặng không có vector visual."""
    import base64

    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        if req.method == "GET":
            return httpx.Response(200, content=b"\x89PNG-gia")
        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.2] * 768]})

    ra = await _client(handler).visual_image(["https://cdn.test/a.jpg"])
    assert ghi["body"]["images"] == [base64.b64encode(b"\x89PNG-gia").decode()]
    assert ghi["body"].get("texts") in (None, [])
    assert len(ra[0]) == 768


async def test_token_rong_thi_raise_ngay_luc_dung():
    """Fail-closed: gửi request không auth chỉ để nhận 401 là tốn một vòng mạng và
    một dòng log khó đọc."""
    with pytest.raises(ValueError, match="KB_SANTA_MODELS_TOKEN"):
        EmbedClient(base_url="https://embed.test", token="")


async def test_danh_sach_rong_khong_goi_mang():
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng cho danh sách rỗng")

    assert await _client(handler).dense([]) == []


async def test_response_hinh_dang_la_khong_nhan_dien_duoc_thi_no_ro_rang():
    """Chưa đo được hình dạng thật của response — nếu nó không khớp `{"embeddings": [...]}`
    lẫn list trần thì phải nổ với thông điệp đọc được, không được lặng lẽ trả `[]` (tầng
    trên sẽ ghi "đã index" cho thứ chưa hề lên Qdrant)."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_shape": True})

    with pytest.raises(ValueError, match="hình dạng"):
        await _client(handler).dense(["xin chào"])


async def test_500_thi_thu_lai_roi_thanh_cong(cho):
    """Service `device: cpu` trả 500/ReadTimeout khi bị dồn — không retry thì một job
    chết vì một lần nghẽn, và cách retry DUY NHẤT hiện có là chạy lại cả lượt nạp."""
    goi = []

    def handler(req: httpx.Request) -> httpx.Response:
        goi.append(1)
        if len(goi) < 3:
            return httpx.Response(500, text="nghẽn")
        return httpx.Response(200, json={"embeddings": [[0.1] * 1024]})

    ra = await _client(handler).dense(["xin chào"])
    assert len(ra) == 1
    assert len(goi) == 3
    # Backoff luỹ tiến: 1s rồi 2s. Retry ngay lập tức chỉ là spam đổi tên.
    assert cho == [1.0, 2.0]


async def test_timeout_cung_duoc_thu_lai(cho):
    """4 mục hỏng trên dev là ReadTimeout, KHÔNG phải status — bắt theo status thì
    đúng ca hay gặp nhất lại không được retry."""
    goi = []

    def handler(req: httpx.Request) -> httpx.Response:
        goi.append(1)
        if len(goi) < 2:
            raise httpx.ReadTimeout("quá 120 giây", request=req)
        return httpx.Response(200, json={"embeddings": [[0.1] * 1024]})

    assert len(await _client(handler).dense(["a"])) == 1
    assert len(goi) == 2


async def test_400_khong_thu_lai(cho):
    """4xx là lỗi của chính chỉ thị ta gửi — thử lại 3 lần cũng sai y hệt, chỉ giữ
    thêm một slot worker."""
    goi = []

    def handler(req: httpx.Request) -> httpx.Response:
        goi.append(1)
        return httpx.Response(400, text="side không hợp lệ")

    with pytest.raises(httpx.HTTPStatusError):
        await _client(handler).dense(["a"])
    assert len(goi) == 1
    assert cho == []


async def test_het_luot_thi_dense_van_no(cho):
    """Dense/sparse hết lượt phải NỔ, không trả `[]`: point không có vector nào thì
    không lên Qdrant được, mà tầng trên lại ghi sổ "đã index"."""
    goi = []

    def handler(req: httpx.Request) -> httpx.Response:
        goi.append(1)
        return httpx.Response(503, text="quá tải")

    with pytest.raises(httpx.HTTPStatusError):
        await _client(handler).dense(["a"])
    assert len(goi) == settings.RETRY_ATTEMPTS


async def test_visual_het_luot_thi_tra_rong(cho):
    """Visual thì NGƯỢC LẠI: `media.py` chỉ gán vector visual khi có, nên point vẫn lên
    Qdrant với vector text — mất tìm-bằng-ảnh, giữ tìm-bằng-caption. Đây là đường cứu
    4 ảnh 30–98 MB đang làm job đổ."""
    goi = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, content=b"\x89PNG-gia")
        goi.append(1)
        return httpx.Response(500, text="hết RAM")

    assert await _client(handler).visual_image(["https://cdn.test/to.jpg"]) == []
    assert len(goi) == settings.RETRY_ATTEMPTS


async def test_visual_tai_anh_that_bai_thi_tra_rong(cho):
    """Ảnh 404/URL chết cũng chỉ mất vector visual, không được làm đổ cả job."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(404)
        raise AssertionError("không được gọi /embed khi chưa tải được ảnh")

    assert await _client(handler).visual_image(["https://cdn.test/mat.jpg"]) == []


def _png(rong: int, cao: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    ra = BytesIO()
    Image.new("RGB", (rong, cao), (200, 30, 30)).save(ra, format="PNG")
    return ra.getvalue()


async def test_anh_qua_lon_thi_thu_nho_truoc_khi_gui(monkeypatch, cho):
    """Client TỰ tải ảnh rồi base64 — ảnh 98.7 MB trên dev thành ~131 MB trong body
    request, gửi cho một model chỉ dùng 256×256 (`siglip2-base-patch16-256`, device
    cpu). Đó là cả hai đầu của 4 job hỏng: ReadTimeout và 500."""
    import base64
    from io import BytesIO

    from PIL import Image

    monkeypatch.setattr(embed_mod.settings, "VISUAL_MAX_BYTES", 100)
    goc = _png(1200, 800)
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        if req.method == "GET":
            return httpx.Response(200, content=goc)
        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.2] * 768]})

    ra = await _client(handler).visual_image(["https://cdn.test/to.png"])
    assert len(ra) == 1

    gui = base64.b64decode(ghi["body"]["images"][0])
    assert len(gui) < len(goc)
    im = Image.open(BytesIO(gui))
    assert im.format == "WEBP"
    assert im.width == settings.VISUAL_IMAGE_WIDTH


async def test_anh_du_nho_thi_gui_nguyen_byte_goc(cho):
    """Không đổi định dạng ảnh vốn đã nhỏ: thêm một lượt giải mã/nén Pillow cho 870
    ảnh chỉ để ra một tệp tương đương."""
    import base64

    goc = _png(64, 64)
    assert len(goc) < settings.VISUAL_MAX_BYTES
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        if req.method == "GET":
            return httpx.Response(200, content=goc)
        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.2] * 768]})

    await _client(handler).visual_image(["https://cdn.test/nho.png"])
    assert base64.b64decode(ghi["body"]["images"][0]) == goc


async def test_byte_qua_lon_khong_phai_anh_thi_chi_mat_vector_visual(monkeypatch, cho):
    """Pillow không đọc được thì `to_webp` ném ValueError — nó phải rơi vào cùng đường
    degrade với lỗi mạng, không làm đổ job."""
    monkeypatch.setattr(embed_mod.settings, "VISUAL_MAX_BYTES", 10)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, content=b"day-khong-phai-anh")
        raise AssertionError("không được gọi /embed với byte không đọc được")

    assert await _client(handler).visual_image(["https://cdn.test/vo.bin"]) == []


async def test_ba_luot_chu_khong_nam():
    """120 giây timeout × 5 lượt = 10 phút một job giữ 1/4 slot worker. Ba lượt là con
    số đã chọn; đổi nó thì đổi cả tính toán này."""
    assert settings.RETRY_ATTEMPTS == 3


async def test_anh_qua_kho_lo_KHONG_lam_do_job(monkeypatch, cho):
    """Pillow từ chối giải mã ảnh trên ~179 triệu điểm ảnh (chống decompression bomb) bằng
    `DecompressionBombError` — KHÔNG phải ValueError, nên trước 2026-08-17 nó thoát khỏi vế
    degrade và giết cả job nạp. Ba ảnh thật trên dev rơi đúng ca này, mỗi ảnh ~991 triệu px."""
    from PIL import Image

    monkeypatch.setattr(embed_mod.settings, "VISUAL_MAX_BYTES", 10)

    def _no(*a, **kw):
        raise Image.DecompressionBombError("Image size (991949112 pixels) exceeds limit")

    monkeypatch.setattr("portal.modules.kb.storage.thumbnail.to_webp", _no)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, content=b"anh-khong-lo")
        raise AssertionError("không được gọi /embed khi không dựng nổi ảnh")

    assert await _client(handler).visual_image(["https://cdn.test/bom.png"]) == []


async def test_khoa_noi_bo_doc_tu_kho_khong_qua_http():
    """Thumb nằm trong MinIO cùng máy. Đi bằng HTTP là tự bắn ra ngoài rồi vòng lại,
    và với URL ngoài thì đó là tải lại ảnh gốc nhiều MB lần thứ hai."""
    http_called = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal http_called
        if "embed" not in str(req.url):
            http_called = True
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    class FakeStore:
        def __init__(self) -> None:
            self.keys_read: list[str] = []

        async def doc(self, *, key: str) -> bytes:
            self.keys_read.append(key)
            return b"RIFF____WEBPfake"

    kho = FakeStore()
    c = EmbedClient(base_url="https://embed.test", token="tok", objects=kho)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await c.visual_image(["tenants/t1/kb-bds/thumb/abc.webp"])

    assert kho.keys_read == ["tenants/t1/kb-bds/thumb/abc.webp"]
    assert http_called is False


async def test_url_ngoai_van_di_bang_http():
    def handler(req: httpx.Request) -> httpx.Response:
        if "embed" in str(req.url):
            return httpx.Response(200, json={"embeddings": [[0.1] * 768]})
        return httpx.Response(200, content=b"\xff\xd8\xffanh")

    c = EmbedClient(base_url="https://embed.test", token="tok", objects=None)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await c.visual_image(["https://cdn.example.com/a.jpg"]) != []
