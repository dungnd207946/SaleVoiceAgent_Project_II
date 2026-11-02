import pytest

from portal.modules.kb.contracts import ChunkSpec, TextDirective


def _directive(text: str, **kw) -> TextDirective:
    return TextDirective(
        workspace_slug="ws",
        record_id=1,
        doc_type="kb_file",
        anchor_code="__ALL__",
        anchor_name="sotay.md",
        section="",
        text=text,
        chunk=ChunkSpec(),
        **kw,
    )


def test_directive_mac_dinh_chua_soi_anh():
    assert _directive("x").images_mirrored is False


def test_cong_nem_khi_text_con_anh_ngoai_ma_chua_soi():
    """Bất biến: một đường nạp thứ ba viết sau này mà quên gọi `mirror_images` phải vỡ TO
    TIẾNG, chứ không âm thầm nhúng URL của khách vào vector."""
    from portal.modules.kb.clients.rag import _check_mirrored

    with pytest.raises(ValueError, match="chưa soi ảnh ngoài"):
        _check_mirrored(_directive("![x](https://s3.khach.vn/1.png)"))


def test_cong_im_lang_khi_da_soi():
    """Đã soi rồi mà URL gốc còn đó là ca HỢP LỆ — ảnh 404 giữ URL gốc (Task 3)."""
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("![x](https://s3.khach.vn/1.png)", images_mirrored=True))


def test_cong_im_lang_khi_text_khong_co_anh_ngoai():
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("Chỉ có chữ."))


def test_cong_im_lang_voi_link_da_tro_kho_minh():
    """Link đã viết lại vẫn là `![](https://…)` — cổng KHÔNG được bắt nó khi đã soi."""
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("![x](https://portal.vn/api/v1/public/files/a.png)", images_mirrored=True))
