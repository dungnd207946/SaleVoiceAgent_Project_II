import io
import re

import pytest

from portal.modules.kb.clients import external_images

MINH = "https://portal.noble.vn/api/v1/public/files/"
# PNG 1×1 hợp lệ — Pillow đọc được, nên nhánh thumb chạy thật chứ không giả.
# (Hex của brief gốc có IDAT CRC sai — dựng lại bằng `Image.new("RGBA",(1,1)).save()`,
# xem task-3-report.md.)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c48900"
    "00000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae42"
    "6082"
)


class KhoGia:
    """Kho trong bộ nhớ. `key` idempotent đúng như `object_store.build_key`."""

    def __init__(self):
        self.doi_tuong: dict[str, bytes] = {}

    def key(self, *, tenant_id: str, path: str) -> str:
        tien_to = f"tenants/{tenant_id}/"
        return path if path.startswith(tien_to) else f"{tien_to}{path}"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.doi_tuong[key] = data
        return f"presigned://{key}"


@pytest.fixture
def base_cong_khai(monkeypatch):
    """`get_settings()` KHÔNG cache (xem CLAUDE.md), nên đặt env là đủ."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.noble.vn")


def _http_gia(monkeypatch, tra_loi):
    """`tra_loi(url)` → (status, content_type, body) hoặc ném."""

    class R:
        def __init__(self, url):
            self.status, self.headers_ct, self._body = tra_loi(url)
            self.headers = {"content-type": self.headers_ct}

        def raise_for_status(self):
            if self.status >= 400:
                # Không dựng httpx.HTTPStatusError: nó đòi request/response thật.
                # `mirror_images` bắt rộng nên kiểu ngoại lệ không quan trọng.
                raise RuntimeError(f"HTTP {self.status}")

        async def aiter_bytes(self):
            yield self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, _method, url):
            return R(url)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)


@pytest.mark.asyncio
async def test_keo_ve_va_viet_lai_link(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "Câu dẫn.\n\n![Màn đăng nhập](https://s3.khach.vn/1.png)\n"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert warnings == []
    assert "s3.khach.vn" not in new_url
    assert MINH in new_url
    assert "![Màn đăng nhập](" in new_url  # alt giữ nguyên
    raw = [k for k in kho.doi_tuong if "/kb/anh/" in k and not k.endswith(".thumb.webp")]
    thumb = [k for k in kho.doi_tuong if k.endswith(".thumb.webp")]
    assert len(raw) == 1 and len(thumb) == 1


@pytest.mark.asyncio
async def test_hai_tai_lieu_dung_chung_anh_chi_ton_mot_ban(monkeypatch, base_cong_khai):
    """Khoá băm theo NỘI DUNG ảnh, không theo URL — nên cùng byte ra cùng khoá."""
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    a, _ = await external_images.mirror_images("![x](https://s3.khach.vn/1.png)", tenant_id="t1", store=kho)
    b, _ = await external_images.mirror_images("![y](https://cdn.khac.vn/2.png)", tenant_id="t1", store=kho)
    assert a.split("(")[1] == b.split("(")[1]


@pytest.mark.asyncio
async def test_anh_404_giu_url_goc_va_ghi_canh_bao(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (404, "text/html", b"no"))
    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert new_url == text  # giữ nguyên, KHÔNG ra `![x]()`
    assert len(warnings) == 1
    assert "s3.khach.vn/1.png" in warnings[0]


@pytest.mark.asyncio
async def test_khong_phai_anh_thi_tu_choi(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "text/html", b"<html>"))
    kho = KhoGia()
    new_url, warnings = await external_images.mirror_images("![x](https://s3.khach.vn/a)", tenant_id="t1", store=kho)
    assert kho.doi_tuong == {}
    assert "content-type" in warnings[0]
    assert new_url == "![x](https://s3.khach.vn/a)"


@pytest.mark.asyncio
async def test_vuot_tran_byte_thi_dung_som(monkeypatch, base_cong_khai):
    """`_fetch_one` phải DỪNG NGAY khi `buf` vượt trần, không đọc trọn thân rồi mới đo.

    Thân giả trả về NHIỀU MẨU nhỏ (không phải một `bytes` đã ghép sẵn) — nếu ai thay
    vòng lặp `async for part in r.aiter_bytes()` bằng `r.content` (đọc hết một lần),
    `da_yield["n"]` sẽ bằng `so_manh` và bài này đỏ, dù kết luận cuối (bỏ qua, có cảnh
    báo) vẫn y hệt. Đếm số mẩu ĐÃ ĐƯỢC YIELD là cách duy nhất phân biệt hai cài đặt đó.
    """
    chunk = b"x" * 1024
    nguong_manh = external_images.MAX_BYTES // len(chunk)  # số mẩu để CHẠM trần
    so_manh = nguong_manh * 10  # thân giả LỚN HƠN NHIỀU trần — "dừng sớm" phải rõ rệt
    da_yield = {"n": 0}

    class R:
        def __init__(self, _url):
            self.headers = {"content-type": "image/png"}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            for _ in range(so_manh):
                da_yield["n"] += 1
                yield chunk

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, _method, url):
            return R(url)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    kho = KhoGia()

    _, warnings = await external_images.mirror_images("![x](https://s3.khach.vn/1.png)", tenant_id="t1", store=kho)

    assert kho.doi_tuong == {}
    assert "vượt trần" in warnings[0]
    # Dừng SỚM: số mẩu tiêu thụ chỉ vừa đủ chạm trần, KHÔNG phải toàn bộ thân giả.
    assert da_yield["n"] <= nguong_manh + 1
    assert da_yield["n"] < so_manh // 2


@pytest.mark.asyncio
async def test_vuot_tran_image_numbers_thi_keo_100_dau(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "\n\n".join(f"![a{i}](https://s3.khach.vn/{i}.png)" for i in range(external_images.MAX_IMAGES + 5))

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert any("vượt trần" in c for c in warnings)
    # 5 ảnh cuối GIỮ URL gốc, không mất
    assert f"https://s3.khach.vn/{external_images.MAX_IMAGES + 4}.png" in new_url


@pytest.mark.asyncio
async def test_base_chua_cau_hinh_thi_giu_url_goc(monkeypatch):
    """`public_url_of` trả rỗng khi PUBLIC_BASE_URL trống — viết rỗng vào link là
    `![x]()`, một ảnh mất mà không lỗi nào. Phải giữ URL gốc."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert new_url == text
    assert any("PUBLIC_BASE_URL" in c for c in warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("loai_loi", ["timeout", "transport"])
async def test_loi_mang_tam_thoi_khong_nem_ma_ghi_canh_bao_rieng(monkeypatch, base_cong_khai, loai_loi):
    """`httpx.TimeoutException`/`TransportError` là lỗi TẠM THỜI (`contracts.TemporaryError`)
    nhưng `mirror_images` KHÔNG được ném nó lên: `handle_kb_file_index` (nơi hàm này
    chạy) đăng ký `retries=0` (`jobs.py`), nên ném ở đây không mua được lượt thử lại
    nào — nó chỉ biến "1 ảnh timeout" thành "cả tệp `loi`". Khác doctrine
    `jobs._tai_anh`/`_thumb_neu_thieu`, vốn chạy dưới job CÓ retry.

    Bài này khẳng định CẢ HAI vế: (1) hàm trả về bình thường, không ném; (2) câu cảnh
    báo nói RÕ đây là lỗi TẠM THỜI (khác cảnh báo của lỗi vĩnh viễn như 404) — người
    đọc log cần biết tải lại tệp có ích hay không."""
    import httpx

    loi = httpx.ReadTimeout("boom") if loai_loi == "timeout" else httpx.ConnectError("boom")

    def no(_u):
        raise loi

    _http_gia(monkeypatch, no)
    kho = KhoGia()

    new_url, warnings = await external_images.mirror_images(
        "![x](https://s3.khach.vn/1.png)", tenant_id="t1", store=kho
    )

    assert new_url == "![x](https://s3.khach.vn/1.png)"  # giữ URL gốc, không mất ảnh
    assert kho.doi_tuong == {}
    assert len(warnings) == 1
    assert "tạm thời" in warnings[0]
    assert "s3.khach.vn/1.png" in warnings[0]


@pytest.mark.asyncio
async def test_mot_anh_timeout_khong_lam_mat_anh_khac_trong_cung_tai_lieu(monkeypatch, base_cong_khai):
    """Đúng cái mà toàn bộ doctrine `retries=0` này tồn tại để bảo vệ: MỘT ảnh timeout
    trong nhiều ảnh không được kéo cả tài liệu xuống. Ảnh còn lại phải được mirror
    xong xuôi (kể cả thumb), link được viết lại, và cảnh báo chỉ nói về ảnh hỏng."""
    import httpx

    def tra_loi(u):
        if u.endswith("/timeout.png"):
            raise httpx.ReadTimeout("boom")
        return 200, "image/png", PNG

    _http_gia(monkeypatch, tra_loi)
    kho = KhoGia()
    text = "![a](https://s3.khach.vn/ok1.png)\n\n![b](https://s3.khach.vn/timeout.png)\n\n![c](https://s3.khach.vn/ok2.png)\n"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert "s3.khach.vn/timeout.png" in new_url  # ảnh hỏng giữ URL gốc
    assert new_url.count(MINH) == 2  # hai ảnh còn lại ĐÃ được viết lại
    assert len(warnings) == 1
    assert "tạm thời" in warnings[0] and "timeout.png" in warnings[0]
    raw = [k for k in kho.doi_tuong if "/kb/anh/" in k and not k.endswith(".thumb.webp")]
    thumb = [k for k in kho.doi_tuong if k.endswith(".thumb.webp")]
    assert len(raw) == 1 and len(thumb) == 1  # ok1/ok2 cùng nội dung ⇒ cùng khoá, 1 bản


@pytest.mark.asyncio
async def test_text_khong_anh_khong_cham_mang(monkeypatch, base_cong_khai):
    def no(_u):
        raise AssertionError("không được gọi mạng khi text không có ảnh")

    _http_gia(monkeypatch, no)
    new_url, warnings = await external_images.mirror_images("Chỉ có chữ.", tenant_id="t1", store=KhoGia())
    assert new_url == "Chỉ có chữ." and warnings == []


@pytest.mark.asyncio
async def test_base_la_dia_chi_noi_bo_thi_giu_url_goc_va_noi_dung(monkeypatch):
    """`PUBLIC_BASE_URL` CÓ đặt (khác hẳn `test_base_chua_cau_hinh_thi_giu_url_goc`, nơi
    biến RỖNG) nhưng trỏ vào loopback — mặc định của một máy dev chưa đổi `.env`. Cảnh
    báo không được nói "chưa cấu hình" cho trường hợp này: nó ĐÃ cấu hình, chỉ là
    khách không mở được `localhost` của ta."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8100")
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert new_url == text  # giữ URL gốc, giống ca chưa cấu hình
    assert len(warnings) == 1
    assert "chưa cấu hình" not in warnings[0]  # nói khác — ca này ĐÃ có giá trị
    assert "localhost" in warnings[0]  # và nói ĐÚNG lý do: địa chỉ nội bộ


@pytest.mark.asyncio
async def test_thumb_hong_khong_lam_mat_anh_da_luu(monkeypatch, base_cong_khai):
    """`store.put()` của ảnh gốc đã xong khi `thumbnail.sinh_va_luu` ném — ảnh gốc là
    sản phẩm chính (`jobs._thumb_neu_thieu` nói vậy về chính docstring của nó), thumb
    chỉ là tối ưu hiển thị. Một lỗi ở bước SAU không được xoá công của bước TRƯỚC:
    ảnh phải ở lại trong kho và link phải được viết lại, kèm một cảnh báo về thumb."""
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))

    from portal.modules.kb.storage import thumbnail

    async def hong(*_a, **_k):
        raise RuntimeError("lỗi ghi thumb")

    monkeypatch.setattr(thumbnail, "sinh_va_luu", hong)

    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert "s3.khach.vn" not in new_url  # link ĐÃ viết lại — không rơi về URL gốc
    assert MINH in new_url
    raw = [k for k in kho.doi_tuong if "/kb/anh/" in k and not k.endswith(".thumb.webp")]
    assert len(raw) == 1  # ảnh gốc còn nguyên trong kho, không mồ côi
    assert not any(k.endswith(".thumb.webp") for k in kho.doi_tuong)  # không có thumb
    assert len(warnings) == 1
    assert "thu nhỏ" in warnings[0] or "thumb" in warnings[0].lower()


@pytest.mark.asyncio
async def test_gioi_han_dong_thoi_giu_dung_thu_tu_va_anh_xa(monkeypatch, base_cong_khai):
    """Bounded concurrency (cùng tinh thần `LANE_ENRICH`) không được đổi KẾT QUẢ: cảnh
    báo phải giữ đúng thứ tự nguồn (không phải thứ tự hoàn tất) và mỗi URL nguồn phải
    map đúng khoá CỦA CHÍNH NÓ trong bảng viết lại — không bị hoán đổi giữa các ảnh
    đang tải song song.

    Ảnh SỐ NHỎ được cho "ngủ" LÂU HƠN ảnh số lớn, nên nếu không tải song song thì thứ
    tự hoàn tất sẽ khác thứ tự bắt đầu — bài này khai thác đúng sự đảo đó để bắt lỗi.
    """
    import asyncio

    from PIL import Image

    n = 12
    dem = {"dang_chay": 0, "dinh": 0}

    def anh(mau: int) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (2, 2), (mau, 0, 0)).save(buf, format="PNG")
        return buf.getvalue()

    noi_dung = {i: anh(10 + i) for i in range(n)}  # mỗi ảnh một nội dung riêng

    class R:
        def __init__(self, url):
            self.i = int(url.rsplit("/", 1)[-1].split(".")[0])
            self.ok = self.i % 2 == 0
            self.headers = {"content-type": "image/png"}

        def raise_for_status(self):
            if not self.ok:
                raise RuntimeError(f"HTTP 404 ({self.i})")

        async def aiter_bytes(self):
            dem["dang_chay"] += 1
            dem["dinh"] = max(dem["dinh"], dem["dang_chay"])
            await asyncio.sleep((n - self.i) * 0.001)  # nhỏ ⇒ ngủ lâu ⇒ hoàn tất sau
            dem["dang_chay"] -= 1
            yield noi_dung[self.i]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, _method, url):
            return R(url)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    kho = KhoGia()
    text = "\n\n".join(f"![a{i}](https://s3.khach.vn/{i}.png)" for i in range(n))

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    # Có chạy SONG SONG thật (đỉnh > 1), nhưng KHÔNG vượt trần đã khai báo.
    assert 1 < dem["dinh"] <= external_images.MAX_CONCURRENT_FETCHES

    # Cảnh báo (các ảnh lẻ, 404) giữ ĐÚNG THỨ TỰ NGUỒN — tăng dần theo i — dù ảnh chỉ
    # số nhỏ hoàn tất SAU ảnh chỉ số lớn.
    le = [i for i in range(n) if i % 2]
    assert warnings == [f"https://s3.khach.vn/{i}.png: RuntimeError: HTTP 404 ({i})" for i in le]

    # Mỗi URL chẵn map ĐÚNG khoá của CHÍNH nội dung ảnh đó — không hoán đổi qua lại.
    cap = dict(re.findall(r"!\[(a\d+)\]\(([^)]+)\)", new_url))
    for i in range(n):
        url_moi = cap[f"a{i}"]
        if i % 2:
            assert url_moi == f"https://s3.khach.vn/{i}.png"
            continue
        assert url_moi.startswith(MINH)
        khoa = url_moi[len(MINH) :]
        assert kho.doi_tuong[khoa] == noi_dung[i]
