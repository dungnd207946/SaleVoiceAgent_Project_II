"""Nguồn ảnh cho vector visual. Đo trên prod 2026-08-25: ảnh gốc 11,5 MB mất 4,16s
(tải + embed), thumb 31 KB mất 0,26s — và model là siglip2-base-patch16-256, nó nhìn
ảnh ở 256px nên bản gốc không cho thêm gì."""

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.contracts import MediaDirective


class FakeEmbed:
    def __init__(self) -> None:
        self.images_sent: list[str] = []

    async def dense(self, texts):
        return [[0.1] * 1024]

    async def visual_image(self, urls):
        self.images_sent.extend(urls)
        return [[0.2] * 768]


class FakeVectorStore:
    async def delete_by_record(self, *a, **kw):
        return 0

    async def upsert(self, name, points):
        return len(points)


def _directive(**kw) -> MediaDirective:
    defaults = dict(
        workspace_slug="ws",
        record_id=1,
        anchor_code="P1",
        content_type="image",
        category="tong_quan",
        media_url="https://cdn.example.com/goc.jpg",
        file_url=None,
        caption="ảnh sân vườn",
        thumb_url="tenants/t1/kb-bds/thumb/abc.webp",
        anchor_name="Dự án 1",
        status="published",
        anchor_status="published",
    )
    defaults.update(kw)
    return MediaDirective(**defaults)


async def test_dung_thumb_khi_co():
    embed = FakeEmbed()
    await MediaClient(embed=embed, store=FakeVectorStore()).index(_directive())
    assert embed.images_sent == ["tenants/t1/kb-bds/thumb/abc.webp"]


async def test_roi_ve_anh_goc_khi_chua_co_thumb():
    embed = FakeEmbed()
    await MediaClient(embed=embed, store=FakeVectorStore()).index(_directive(thumb_url=None))
    assert embed.images_sent == ["https://cdn.example.com/goc.jpg"]
