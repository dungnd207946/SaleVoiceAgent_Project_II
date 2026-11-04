"""Đường ảnh sản phẩm → collection `<prefix>_media`. Một ảnh = một point.

Hai vector: `text` (nhúng caption — tên máy, màu, mô tả) và `visual` (nhúng chính tấm ảnh,
cho tìm-bằng-ảnh). Không có job VLM sinh caption: caption dựng từ `alt_text` + tên sản phẩm
+ tên màu là đủ để agent tìm "ảnh iPhone 16 Pro màu titan sa mạc". `visual` là phần PHỤ —
tải/nhúng ảnh hỏng thì point vẫn lên với vector `text` (xem `EmbedClient.visual_image`).

Payload: entity · record_id · doc_type · title · caption · media_type · media_url · color
· content_hash · product_id · brand_id · brand · category.
"""

from portal.core.public_url import public_url_of
from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.contracts import ENTITY_MEDIA, IndexResult, MediaDoc
from portal.modules.kb.index.store import PointIn, point_id_of

_ANH = ("image", "thumbnail", "image_360")


class MediaClient(LocalIndexClient):
    media_collection = True

    async def index(self, doc: MediaDoc, *, content_hash: str) -> IndexResult:
        dense = await self._embed.dense([doc.caption])
        if len(dense) != 1:
            raise ValueError(f"embed dense trả {len(dense)} vector cho 1 caption")
        vectors: dict = {"text": dense[0]}
        if doc.media_type in _ANH:
            visual = await self._embed.visual_image([doc.media_url])
            if visual:
                vectors["visual"] = visual[0]

        point = PointIn(
            point_id=point_id_of(ENTITY_MEDIA, doc.record_id, 0),
            vectors=vectors,
            payload={
                "entity": ENTITY_MEDIA,
                "record_id": doc.record_id,
                "doc_type": ENTITY_MEDIA,
                "title": doc.title,
                "caption": doc.caption,
                "media_type": doc.media_type,
                "media_url": public_url_of(doc.media_url),
                "color": doc.color,
                "content_hash": content_hash,
                **doc.meta.payload(),
            },
        )
        await self.delete(record_id=doc.record_id, doc_type=ENTITY_MEDIA)
        n = await self._store.upsert(self.collection, [point])
        return IndexResult(points_upserted=n, content_hash=content_hash)
