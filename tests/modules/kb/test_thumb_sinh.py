"""Chặng sinh thumbnail: tải ảnh → WebP → ghi kho, trả về KHOÁ.

Trả KHOÁ chứ không trả URL mà `put()` đưa lại: `S3Store.put` trả presigned URL TTL
300 giây (`settings.PRESIGN_TTL_SEC`), lưu nó vào `media.thumb_url` là lưu một URL
chết sau 5 phút.
"""

from io import BytesIO

import pytest

from portal.modules.kb import settings
from portal.modules.kb.storage import thumbnail
from tests.modules.kb.fake import FakeObjectStore


def _anh(w: int = 1200, h: int = 800) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), "blue").save(buf, format="JPEG")
    return buf.getvalue()


async def test_tra_ve_khoa_khong_phai_url_presigned():
    kho = FakeObjectStore()
    khoa = await thumbnail.sinh_va_luu(
        kho, tenant_id="kb_acme", media_url="https://cdn.x/a.jpg", content_hash="beef", tai_ve=_anh
    )
    assert khoa == "tenants/kb_acme/kb-bds/thumb/beef.thumb.webp"
    assert not khoa.startswith("http")


async def test_ghi_dung_khoa_va_content_type_webp():
    kho = FakeObjectStore()
    khoa = await thumbnail.sinh_va_luu(
        kho, tenant_id="kb_acme", media_url="https://cdn.x/a.jpg", content_hash="beef", tai_ve=_anh
    )
    assert khoa in kho.stored
    from PIL import Image

    assert Image.open(BytesIO(kho.stored[khoa])).format == "WEBP"


async def test_thu_hep_be_ngang_theo_cai_dat():
    kho = FakeObjectStore()
    khoa = await thumbnail.sinh_va_luu(
        kho, tenant_id="kb_acme", media_url="https://cdn.x/a.jpg", content_hash="beef", tai_ve=_anh
    )
    from PIL import Image

    assert Image.open(BytesIO(kho.stored[khoa])).width == settings.THUMB_WIDTH


async def test_anh_noi_bo_dat_thumb_canh_anh_goc():
    kho = FakeObjectStore()
    khoa = await thumbnail.sinh_va_luu(
        kho, tenant_id="kb_acme", media_url="kb-bds/ab/mb.jpg", content_hash="beef", tai_ve=_anh
    )
    assert khoa == "tenants/kb_acme/kb-bds/ab/mb.thumb.webp"


async def test_byte_khong_phai_anh_khong_ghi_gi():
    """Ghi một object rác rồi trả khoá của nó là để `<img>` trỏ vào một tệp vỡ."""
    kho = FakeObjectStore()
    with pytest.raises(ValueError):
        await thumbnail.sinh_va_luu(
            kho,
            tenant_id="kb_acme",
            media_url="https://cdn.x/a.jpg",
            content_hash="beef",
            tai_ve=lambda: b"khong phai anh",
        )
    assert kho.stored == {}
