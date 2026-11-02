"""Nhãn đi vào TEXT được embed, không đi vào caption khách nhìn thấy."""

from portal.modules.kb.clients.media import MediaClient, _text_and_hash
from portal.modules.kb.contracts import MediaDirective


class FakeEmbed:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def dense(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 1024]

    async def visual_image(self, urls):
        return [[0.2] * 768]


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: list = []

    async def delete_by_record(self, *a, **kw):
        return 0

    async def upsert(self, name, points):
        self.points.extend(points)
        return len(points)


def _directive(caption: str) -> MediaDirective:
    return MediaDirective(
        workspace_slug="ws",
        record_id=1,
        anchor_code="P1",
        content_type="image",
        category="tong_quan",
        media_url="https://cdn.example.com/a.jpg",
        file_url=None,
        caption=caption,
        thumb_url="tenants/t1/kb-bds/thumb/a.webp",
        anchor_name="Dự án 1",
        status="published",
        anchor_status="published",
    )


def test_text_embed_mang_nhan_tieng_viet_cua_danh_muc():
    text, _ = _text_and_hash(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert "tổng quan" in text
    assert "tong_quan" not in text, "mã thô embed kém hơn từ tiếng Việt"
    assert "nội thất" in text


async def test_payload_caption_khong_mang_nhan():
    store = FakeVectorStore()
    await MediaClient(embed=FakeEmbed(), store=store).index(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert store.points[0].payload["caption"] == "Phòng ngủ."


def test_hash_doi_khi_nhan_doi():
    """Nhãn nằm trong caption nên hash đổi ⇒ delta tự nạp lại. Đây là cơ chế, không phải
    tình cờ: nhãn để ngoài caption thì hash không đổi và nó không bao giờ lên Qdrant."""
    _, h1 = _text_and_hash(_directive("Phòng ngủ."))
    _, h2 = _text_and_hash(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert h1 != h2
