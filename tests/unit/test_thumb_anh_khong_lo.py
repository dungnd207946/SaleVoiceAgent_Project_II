"""Ảnh khổng lồ: trần chống bom của Pillow chặn đúng dữ liệu khách gửi.

Đo trên `aina_prod` 2026-08-25: có tấm 444M pixel (47,8 MB) — trần Pillow là 178M nên
`to_webp` ném `DecompressionBombError`, ảnh mất thumb, rồi mất luôn caption vì caption
rơi về URL ảnh gốc mà DashScope từ chối vì quá cỡ.
"""

import io

import pytest
from PIL import Image

from portal.modules.kb.storage import thumbnail


def _anh(w: int, h: int, fmt: str = "JPEG") -> bytes:
    ra = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(ra, format=fmt)
    return ra.getvalue()


def test_anh_thuong_van_ra_webp():
    webp = thumbnail.to_webp(_anh(1200, 800))
    assert webp[:4] == b"RIFF" and b"WEBP" in webp[:16]


def test_tran_pillow_khong_con_chan():
    """Trần 178M của Pillow phải tắt — nếu ai bật lại, ảnh 444M pixel của khách chết trở lại."""
    from PIL import Image as PILImage

    thumbnail.to_webp(_anh(60, 40))
    assert PILImage.MAX_IMAGE_PIXELS is None


def test_vuot_tran_cua_ta_thi_nem_loi_NOI_RO_KICH_THUOC(monkeypatch):
    """Ném thì phải nói ảnh bao nhiêu pixel — «không đọc được ảnh» đẩy người vận hành đi
    tìm một tệp hỏng không tồn tại. Dùng PNG vì `draft()` không giảm mẫu được nó."""
    monkeypatch.setattr(thumbnail, "_TRAN_PIXEL", 1000)
    with pytest.raises(ValueError, match=r"pixel .* vượt trần"):
        thumbnail.to_webp(_anh(100, 100, "PNG"))


def test_jpeg_khong_lo_KHONG_bi_tran_chan_vi_draft_da_giam_mau(monkeypatch):
    """Trần phải kiểm SAU `draft()`. Kiểm trước là chặn oan đúng những tấm 273M-477M pixel
    của khách — chúng là JPEG nên giảm mẫu về vài triệu pixel, RAM không thành vấn đề."""
    # Trần đặt GIỮA hai giá trị để bài này phân biệt được thứ tự: ảnh gốc 4000×2800 =
    # 11,2M pixel (vượt trần), sau `draft()` còn 1000×700 = 700K (dưới trần). Kiểm trước
    # thì đỏ, kiểm sau thì xanh. Ảnh thật của khách: 26667×16667 → 3333×2083 = 6,9M pixel.
    monkeypatch.setattr(thumbnail, "_TRAN_PIXEL", 1_000_000)
    webp = thumbnail.to_webp(_anh(4000, 2800))
    assert webp[:4] == b"RIFF"


def test_jpeg_duoc_giam_mau_khi_giai_ma(monkeypatch):
    """`draft()` là thứ giữ RAM ở mức MB thay vì GB. Không gọi nó thì nâng trần = OOM."""
    from PIL.JpegImagePlugin import JpegImageFile  # `draft` bị lớp con ghi đè

    goi: list = []
    thuc = JpegImageFile.draft

    def _spy(self, mode, size):
        goi.append((self.size, size))
        return thuc(self, mode, size)

    monkeypatch.setattr(JpegImageFile, "draft", _spy)
    thumbnail.to_webp(_anh(2400, 1600))
    assert goi, "phải gọi draft() trước khi load()"
