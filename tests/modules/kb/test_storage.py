"""Cách ly kho tệp: một lỗi ghép đường dẫn là workspace A đọc được file của B.

Postgres không đứng giữa chuyện này. Lưới thật là IAM policy theo tiền tố (spec §6.1).
"""

import pytest

from portal.modules.kb import settings
from portal.modules.kb.storage import object_store, thumbnail


def test_key_luon_nam_duoi_prefix_cua_tenant():
    assert object_store.build_key(tenant_id="kb_acme", path="docs/a.pdf") == "tenants/kb_acme/docs/a.pdf"
    assert object_store.build_key(tenant_id="kb_acme", path="/docs/a.pdf") == "tenants/kb_acme/docs/a.pdf"


def test_khoa_da_mang_tien_to_cua_chinh_tenant_thi_khong_cong_lan_hai():
    """`POST /realestate/uploads` trả khoá ĐẦY ĐỦ (`tenants/<tenant>/kb-bds/<sha>/<tên>`)
    và frontend lưu nguyên văn nó vào `media.media_url` / `documents.file_url`.

    Cộng tiền tố lần hai cho ra `tenants/x/tenants/x/…` — một khoá không tồn tại. Không
    ai báo lỗi lúc ghép: `presign_get` vẫn ký được, chỉ 404 lúc tải; còn `doc()` thì ném
    `KhongTimThay` và mọi job enrich nhánh documents failed.
    """
    khoa_upload = "tenants/kb_acme/kb-bds/abc123/csbh.pdf"
    assert object_store.build_key(tenant_id="kb_acme", path=khoa_upload) == khoa_upload
    assert object_store.build_key(tenant_id="kb_acme", path=f"/{khoa_upload}") == khoa_upload


def test_chi_tien_to_cua_CHINH_tenant_moi_duoc_giu_nguyen():
    """`tenants/<tenant khác>/…` KHÔNG phải khoá của mình — nó bị lồng xuống dưới tiền
    tố của chính tenant, không được nhận là "đã có tiền tố" và trả nguyên văn."""
    assert (
        object_store.build_key(tenant_id="kb_acme", path="tenants/kb_other/docs/a.pdf")
        == "tenants/kb_acme/tenants/kb_other/docs/a.pdf"
    )


def test_chan_duong_dan_thoat_ra_khoi_prefix():
    """`../` thoát khỏi prefix và IAM policy theo tiền tố sẽ cho qua."""
    with pytest.raises(ValueError, match="đường dẫn không hợp lệ"):
        object_store.build_key(tenant_id="kb_acme", path="../kb_other/docs/a.pdf")
    with pytest.raises(ValueError, match="đường dẫn không hợp lệ"):
        object_store.build_key(tenant_id="kb_acme", path="  ")


def test_chan_tenant_id_khong_hop_le():
    with pytest.raises(ValueError, match="tenant_id không hợp lệ"):
        object_store.build_key(tenant_id="KB Acme", path="a.pdf")
    # Dấu `-` được phép Ở GIỮA nhưng KHÔNG ở ký tự đầu — cùng hình dạng với
    # `tenants_id_check`, nơi ký tự đầu vẫn phải là `[a-z]`.
    with pytest.raises(ValueError, match="tenant_id không hợp lệ"):
        object_store.build_key(tenant_id="-kb-acme", path="a.pdf")


def test_cho_phep_tenant_id_co_gach_ngang():
    """tenant_id import từ hệ ngoài mang dấu `-` (vd `noble-homes_k3n7_retail`).

    Chặn ở đây nghĩa là mọi upload/presign KB của tenant đó chết với ValueError,
    trong khi tên ấy hợp lệ với `control.tenants` sau migration 0911.
    """
    assert (
        object_store.build_key(tenant_id="noble-homes_k3n7_retail", path="docs/a.pdf")
        == "tenants/noble-homes_k3n7_retail/docs/a.pdf"
    )


def test_phan_biet_file_noi_bo_voi_url_ngoai():
    """§4.2d — bỏ nhánh này thì mọi media YouTube/kuula fail index."""
    assert object_store.is_internal_key("media/mb.webp") is True
    assert object_store.is_internal_key("https://youtu.be/abc") is False


def test_ten_thumb_dat_canh_file_goc():
    assert thumbnail.thumb_key("tenants/kb_acme/media/mb.jpg") == "tenants/kb_acme/media/mb.thumb.webp"
    # Không có phần mở rộng thì thêm hậu tố, không cắt mất thư mục.
    assert thumbnail.thumb_key("tenants/kb_acme/media/mb") == "tenants/kb_acme/media/mb.thumb.webp"


def _anh(w: int, h: int, mode: str = "RGB") -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new(mode, (w, h), "red").save(buf, format="PNG")
    return buf.getvalue()


def _co(data: bytes) -> tuple[str, int, int]:
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(data))
    return im.format, im.width, im.height


def test_to_webp_ra_dung_dinh_dang_va_be_ngang():
    ra = thumbnail.to_webp(_anh(2000, 1000))
    assert _co(ra) == ("WEBP", settings.THUMB_WIDTH, settings.THUMB_WIDTH // 2)


def test_giu_ty_le_khung_hinh():
    """Ảnh dọc cũng phải giữ tỉ lệ — mặt bằng méo là bản vẽ sai tỉ lệ."""
    fmt, w, h = _co(thumbnail.to_webp(_anh(800, 1600)))
    assert (w, h) == (settings.THUMB_WIDTH, settings.THUMB_WIDTH * 2)


def test_khong_phong_to_anh_nho_hon():
    """Phóng to một ảnh 200px lên 512px cho ra ảnh mờ NẶNG HƠN bản gốc."""
    fmt, w, h = _co(thumbnail.to_webp(_anh(200, 100)))
    assert (w, h) == (200, 100)


def test_anh_co_kenh_alpha_khong_no():
    assert _co(thumbnail.to_webp(_anh(1024, 1024, "RGBA")))[0] == "WEBP"


def test_thumb_nho_hon_anh_goc():
    goc = _anh(2000, 1000)
    assert len(thumbnail.to_webp(goc)) < len(goc)


def test_byte_khong_phai_anh_bao_loi_ro():
    with pytest.raises(ValueError, match="không đọc được"):
        thumbnail.to_webp(b"khong phai anh")


def test_khoa_thumb_cua_anh_noi_bo_dat_canh_anh_goc():
    assert (
        thumbnail.thumb_key_cho_media(media_url="kb-bds/ab/mb.jpg", content_hash="deadbeef")
        == "kb-bds/ab/mb.thumb.webp"
    )


def test_khoa_thumb_cua_url_ngoai_dung_content_hash():
    """`thumb_key()` KHÔNG dùng được cho URL ngoài: nó sẽ cho ra
    `https://host/a__intro.thumb.webp` — một chuỗi không phải khoá S3."""
    assert (
        thumbnail.thumb_key_cho_media(media_url="https://cdn.x/a__intro.jpg", content_hash="deadbeef")
        == "kb-bds/thumb/deadbeef.thumb.webp"
    )


def test_url_ngoai_thieu_hash_thi_suy_tu_url():
    """`content_hash` là `NOT NULL DEFAULT ''` nên có thể rỗng. Suy từ URL để khoá vẫn
    ổn định giữa các lần chạy — sinh khoá ngẫu nhiên là mỗi lần backfill một object mới."""
    a = thumbnail.thumb_key_cho_media(media_url="https://cdn.x/a.jpg", content_hash="")
    b = thumbnail.thumb_key_cho_media(media_url="https://cdn.x/a.jpg", content_hash="")
    assert a == b
    assert a.startswith("kb-bds/thumb/") and a.endswith(settings.THUMB_SUFFIX)
    assert a != thumbnail.thumb_key_cho_media(media_url="https://cdn.x/b.jpg", content_hash="")
