"""Tải ảnh: tải hụt phải NÓI ra, không đội lốt «ảnh hỏng».

Đo trong một đợt nạp thật 2026-08-25: 71 lần `ValueError: cannot identify image file`
mà tệp nguồn hoàn toàn hợp lệ — byte thiếu vì 8 làn thumb chia nhau 2 MB/s và trần
timeout 30 giây phẳng, rồi Pillow nhận nửa tệp và báo sai nguyên nhân.
"""

import httpx
import pytest

from portal.modules.kb import jobs
from portal.modules.kb.contracts import TemporaryFetchError


class _Resp:
    def __init__(self, data: bytes, headers: dict) -> None:
        self.content = data
        self.headers = headers

    def raise_for_status(self) -> None:
        return None


def _tiem(monkeypatch, ra):
    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url):
            if isinstance(ra, Exception):
                raise ra
            return ra

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_tai_du_thi_qua(monkeypatch):
    _tiem(monkeypatch, _Resp(b"12345", {"content-length": "5"}))
    assert await jobs._tai_anh("https://x/a.jpg") == b"12345"


async def test_tai_hut_thi_nem_loi_TAM_THOI(monkeypatch):
    """Tạm thời chứ không vĩnh viễn: job phải thử lại, vì tệp nguồn không hỏng."""
    _tiem(monkeypatch, _Resp(b"123", {"content-length": "9"}))
    with pytest.raises(TemporaryFetchError, match="tải hụt: nhận 3/9 byte"):
        await jobs._tai_anh("https://x/a.jpg")


async def test_khong_khai_content_length_thi_khong_doan(monkeypatch):
    """Nguồn không khai độ dài thì ta không có cơ sở kết luận — đừng ném oan."""
    _tiem(monkeypatch, _Resp(b"123", {}))
    assert await jobs._tai_anh("https://x/a.jpg") == b"123"


@pytest.mark.parametrize("loi", [httpx.ReadTimeout("quá hạn"), httpx.ConnectError("đứt")])
async def test_loi_mang_thanh_loi_tam_thoi(monkeypatch, loi):
    _tiem(monkeypatch, loi)
    with pytest.raises(TemporaryFetchError):
        await jobs._tai_anh("https://x/a.jpg")
