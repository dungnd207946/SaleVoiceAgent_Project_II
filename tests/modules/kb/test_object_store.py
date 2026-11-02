"""`S3Store` uỷ quyền cho `KhoTep` — chạy trên MinIO thật, không mock S3.

Cùng lý lẽ với `tests/modules/config/test_kho_tep.py`: một mock S3 xanh cho đúng
những lỗi nó không biết là lỗi (thứ tự ghi, khoá không tồn tại trả rỗng thay vì
nổ lỗi). `build_key`/`is_internal_key`/`key()` đã có cổng riêng ở `test_storage.py`,
không lặp lại ở đây.
"""

import httpx
import pytest

from portal.core.storage import KhongTimThay
from portal.modules.kb.storage.object_store import S3Store

pytestmark = pytest.mark.integration


@pytest.fixture
def s3_store(kho_tep) -> S3Store:
    """`kho_tep` đã tạo & dọn sạch bucket thật trước mỗi test."""
    return S3Store(kho_tep)


async def test_ghi_roi_doc_lai_dung_byte(s3_store: S3Store) -> None:
    khoa = "tenants/kb_acme/docs/a.pdf"

    await s3_store.put(key=khoa, data=b"noi dung tai lieu that", content_type="application/pdf")

    assert await s3_store.doc(key=khoa) == b"noi dung tai lieu that"


async def test_khoa_day_du_tu_upload_di_qua_key_van_doc_duoc(s3_store: S3Store) -> None:
    """ĐÚNG ĐƯỜNG THẬT, không tắt qua `put`/`doc` với khoá dựng sẵn.

    `POST /realestate/uploads` trả khoá đầy đủ, frontend lưu nguyên văn vào
    `documents.file_url`, rồi `handle_enrich` gọi `store.key()` trên chính giá trị đó
    trước khi `doc()`. Nếu `key()` cộng tiền tố lần hai thì khoá không tồn tại và MỌI
    job enrich nhánh documents failed — test cũ không bắt được vì nó truyền khoá thẳng
    vào `put`/`doc`, không đi qua `key()`.
    """
    khoa_upload = "tenants/kb_acme/kb-bds/abc123/csbh.pdf"
    await s3_store.put(key=khoa_upload, data=b"byte cua tai lieu that", content_type="application/pdf")

    assert await s3_store.doc(key=s3_store.key(tenant_id="kb_acme", path=khoa_upload)) == b"byte cua tai lieu that"


async def test_presign_get_tra_url_tai_duoc_that(s3_store: S3Store) -> None:
    """URL từ `presign_get` phải là một URL TẢI ĐƯỢC thật, không chỉ đúng hình dạng
    chuỗi — nếu không thì lỗi ký sai chỉ lộ ra ở tận santa-models, xa chỗ sinh ra nó."""
    khoa = "tenants/kb_acme/docs/b.pdf"
    await s3_store.put(key=khoa, data=b"pdf that de tai", content_type="application/pdf")

    url = await s3_store.presign_get(key=khoa, ttl_sec=60)

    async with httpx.AsyncClient() as http:
        r = await http.get(url)
    assert r.status_code == 200, r.text
    assert r.content == b"pdf that de tai"


async def test_doc_khoa_khong_ton_tai_thi_bao_loi_ro_rang(s3_store: S3Store) -> None:
    """Fail loud: byte rỗng đi vào Docling thành "tài liệu không có chữ", và người
    dùng thấy ô trống thay vì một thông báo lỗi — `doc()` phải nổ, không trả `b""`."""
    with pytest.raises(KhongTimThay):
        await s3_store.doc(key="tenants/kb_acme/docs/khong-ton-tai.pdf")


async def test_delete_xoa_that_khoi_kho(s3_store: S3Store) -> None:
    khoa = "tenants/kb_acme/docs/c.pdf"
    await s3_store.put(key=khoa, data=b"se bi xoa", content_type="application/pdf")

    await s3_store.delete(key=khoa)

    with pytest.raises(KhongTimThay):
        await s3_store.doc(key=khoa)
