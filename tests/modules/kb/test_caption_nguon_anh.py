"""Ảnh > 10 MB bị DashScope từ chối `400 Multimodal file size is too large` khi gửi
bằng URL — đo trên prod 2026-08-25: 24% ảnh của một tenant thật rơi vào đó và mất
caption trong im lặng. Thumb 31 KB thì mô tả được."""

import pytest

from portal.modules.kb import jobs as kb_jobs


class FakeVlm:
    def __init__(self) -> None:
        self.urls_sent: list[str] = []
        self.bytes_sent: list[bytes] = []

    async def caption(self, image_url, *, profile):
        self.urls_sent.append(image_url)
        return "mô tả từ url"

    async def caption_bytes(self, data, *, mime, profile):
        self.bytes_sent.append(data)
        return "mô tả từ byte"

    async def aclose(self):
        return None


class FakeStore:
    async def doc(self, *, key: str) -> bytes:
        return b"RIFF____WEBPthumb"


@pytest.fixture
def fake_vlm(monkeypatch) -> FakeVlm:
    v = FakeVlm()
    monkeypatch.setattr(kb_jobs, "_vlm", lambda: v)
    monkeypatch.setattr(kb_jobs, "object_store", lambda: FakeStore())
    return v


async def test_co_thumb_thi_gui_byte_thumb(fake_vlm):
    caption, _ = await kb_jobs._caption_anh(
        tenant_id="t1",
        media_url="https://cdn.example.com/goc.jpg",
        profile="caption",
        thumb_url="tenants/t1/kb-bds/thumb/abc.webp",
    )
    assert caption == "mô tả từ byte"
    assert fake_vlm.bytes_sent == [b"RIFF____WEBPthumb"]
    assert fake_vlm.urls_sent == []


async def test_khong_co_thumb_thi_van_gui_url(fake_vlm):
    caption, _ = await kb_jobs._caption_anh(
        tenant_id="t1",
        media_url="https://cdn.example.com/goc.jpg",
        profile="caption",
        thumb_url="",
    )
    assert caption == "mô tả từ url"
    assert fake_vlm.urls_sent == ["https://cdn.example.com/goc.jpg"]
