"""Mô tả nháp cho ảnh CHƯA có hàng `media` — người dùng vừa tải tệp lên."""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from tests.modules.kb.fake import FakeObjectStore

TENANT = "kb_acme"


class _FakeVlm:
    def __init__(self) -> None:
        self.goi: list[str] = []
        self.goi_byte: list[str] = []

    async def caption(self, image_url: str, *, profile: str) -> str:
        self.goi.append(profile)
        return "mô tả cho URL ngoài"

    async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
        self.goi_byte.append(profile)
        return "mô tả cho ảnh trong kho"


def _anh_gia() -> bytes:
    from io import BytesIO

    from PIL import Image

    Image.new("RGB", (400, 300), "green").save(buf := BytesIO(), format="JPEG")
    return buf.getvalue()


@pytest.fixture
def vlm_gia(monkeypatch):
    v = _FakeVlm()
    monkeypatch.setattr(jobs, "_vlm", lambda: v)
    return v


async def test_anh_trong_kho_gui_byte(pool, seed_kb, vlm_gia, monkeypatch):
    store = FakeObjectStore()
    store.stored["tenants/kb_acme/kb-bds/abc/a.jpg"] = _anh_gia()
    monkeypatch.setattr(jobs, "object_store", lambda: store)
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_caption_preview(
            conn, {"media_url": "tenants/kb_acme/kb-bds/abc/a.jpg", "vertical": "real_estate"}
        )
    assert ra.message == "mô tả cho ảnh trong kho"
    assert vlm_gia.goi_byte == ["caption"]


async def test_url_ngoai_gui_url(pool, seed_kb, vlm_gia, monkeypatch):
    monkeypatch.setattr(jobs, "object_store", lambda: FakeObjectStore())
    async with tenant_conn(pool, TENANT) as conn:
        ra = await jobs.handle_caption_preview(conn, {"media_url": "https://cdn.test/a.jpg", "vertical": "real_estate"})
    assert ra.message == "mô tả cho URL ngoài"
    assert vlm_gia.goi == ["caption"]


async def test_khong_dung_toi_hang_media_nao(pool, seed_kb, vlm_gia, monkeypatch):
    """Cả điểm của handler này: ảnh chưa được lưu, nên không có gì để ghi vào DB."""
    monkeypatch.setattr(jobs, "object_store", lambda: FakeObjectStore())
    async with tenant_conn(pool, TENANT) as conn:
        truoc = await conn.fetchval("SELECT count(*) FROM tenant_data.media")
        await jobs.handle_caption_preview(conn, {"media_url": "https://cdn.test/a.jpg"})
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.media") == truoc
