"""Cổng canh việc OFFLOAD việc nặng CPU khỏi event loop.

Trước 2026-08-14 repo có **0** test loại này (`grep -rn "to_thread" tests/` không ra gì),
và đó đúng là lý do `to_webp` ở đường sinh ảnh thu nhỏ chạy trên event loop suốt mà không
ai thấy: `test_thumb_sinh.py` gọi `sinh_va_luu` đầu-cuối và xanh, vì nó không đo *cách*
hàm chạy.

Worker chạy MỘT việc một lúc, nên một lời gọi chặn không làm chậm một việc — nó làm **cả
hàng đợi đứng**, và trong lúc đó `tenant_conn` vẫn giữ một kết nối asyncpg mở.

KHUÔN ĐO lấy từ `tests/modules/test_worker.py` (test canh `SKIP LOCKED`): chạy thứ cần đo
song song với một nhịp `asyncio.sleep` ngắn, rồi khẳng định nhịp CÓ chạy. Nhịp không chạy =
event loop bị giữ.
"""

import asyncio
import time

from portal.modules.kb.storage import thumbnail

# Đủ dài để một event loop bị chặn chắc chắn bỏ nhịp, đủ ngắn để test không chậm.
_CHAN_GIAY = 0.4
_NHIP_GIAY = 0.02


class _StoreGia:
    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        return "https://x/" + key

    def key(self, *, tenant_id: str, path: str) -> str:
        return f"tenants/{tenant_id}/{path}"


async def _khoang_cach_lon_nhat(dung: asyncio.Event) -> float:
    """Khoảng cách LỚN NHẤT giữa hai nhịp liên tiếp, tính tới khi `dung` được set.

    ĐO KHOẢNG CÁCH, KHÔNG ĐẾM SỐ NHỊP. Bản đầu của test này đếm số nhịp trong một cửa sổ
    và nó XANH CẢ KHI bỏ `to_thread` — vì `create_task` chỉ xếp lịch, nhịp đầu tiên chưa
    chạy khi lời gọi chặn bắt đầu, nên cửa sổ đếm mở ra SAU khi loop đã được nhả. Một cổng
    canh mà không ai từng thấy nó đỏ thì chưa phải cổng.
    """
    lon_nhat = 0.0
    truoc = time.monotonic()
    while not dung.is_set():
        await asyncio.sleep(_NHIP_GIAY)
        gio = time.monotonic()
        lon_nhat = max(lon_nhat, gio - truoc)
        truoc = gio
    return lon_nhat


async def _do_khi_chay(viec) -> float:
    """Chạy `viec()` song song một nhịp, trả khoảng cách nhịp lớn nhất quan sát được."""
    dung = asyncio.Event()
    nhip = asyncio.create_task(_khoang_cach_lon_nhat(dung))
    # Nhả loop để nhịp CHẠY THẬT trước khi việc bắt đầu — thiếu dòng này là phép đo mù.
    await asyncio.sleep(_NHIP_GIAY * 2)
    try:
        await viec()
    finally:
        dung.set()
    return await nhip


async def test_sinh_thumb_khong_giu_event_loop(monkeypatch):
    """`to_webp` mở ảnh bằng Pillow, resize LANCZOS và encode WebP `method=6` — comment của
    chính nó gọi mức đó là "nén chậm nhất". Bỏ `to_thread` ở `sinh_va_luu` làm test này đỏ.
    """

    def _cham(data: bytes, *, width: int = 512) -> bytes:
        time.sleep(_CHAN_GIAY)
        return b"webp"

    monkeypatch.setattr(thumbnail, "to_webp", _cham)

    async def _viec():
        await thumbnail.sinh_va_luu(
            _StoreGia(),
            tenant_id="acme",
            media_url="media/a.webp",
            content_hash="h1",
            tai_ve=lambda: b"goc",
        )

    gap = await _do_khi_chay(_viec)
    assert gap < _CHAN_GIAY / 2, f"event loop bị giữ {gap:.2f}s trong lúc sinh thumb"


async def test_uri_anh_cua_vlm_khong_giu_event_loop(monkeypatch):
    """Đường VLM base64 ảnh nhiều MB, và đường OCR làm thế 20 lần liên tiếp cho một tài
    liệu. Cả `to_webp` lẫn `b64encode` phải nằm trong thread."""
    from portal.modules.kb.clients import vlm as vlm_mod

    def _cham(data: bytes, *, width: int = 1600) -> bytes:
        time.sleep(_CHAN_GIAY)
        return b"webp"

    monkeypatch.setattr(thumbnail, "to_webp", _cham)
    monkeypatch.setattr(vlm_mod.settings, "VLM_MAX_BYTES", 1)

    ra: list[str] = []

    async def _viec():
        ra.append(await vlm_mod.VlmClient._uri_anh(b"x" * 10, mime="image/png"))

    gap = await _do_khi_chay(_viec)
    assert ra[0].startswith("data:image/webp;base64,")
    assert gap < _CHAN_GIAY / 2, f"event loop bị giữ {gap:.2f}s trong lúc dựng uri ảnh"


async def test_anh_nho_hon_tran_khong_bi_thu_nho():
    """Thu nhỏ vô cớ là mất chữ trên ảnh mặt bằng — qwen-vl phải ĐỌC nhãn và số hiệu."""
    from portal.modules.kb.clients.vlm import VlmClient

    uri = await VlmClient._uri_anh(b"x" * 100, mime="image/png")
    assert uri.startswith("data:image/png;base64,"), "ảnh nhỏ bị đổi định dạng vô cớ"
