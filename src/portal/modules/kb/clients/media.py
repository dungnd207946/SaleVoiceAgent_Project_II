"""Đường media → collection `<slug>_media`.

BỘ KHOÁ PAYLOAD LÀ HỢP ĐỒNG: 381 point đang sống trên EC2 có đúng bộ dưới đây và agent
đọc chúng. Không đổi tên khoá nào — kể cả `project_id`, vốn mang anchor_code và đặt
chưa hay. Đổi tên là việc của một đợt có kiểm chứng ở cả hai repo.
"""

import hashlib

from portal.core.public_url import public_url_of
from portal.modules.kb import settings
from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.clients.trang_thai import status_hieu_luc
from portal.modules.kb.contracts import NHAN_DANH_MUC, IndexResult, MediaDirective, split_caption
from portal.modules.kb.index.store import PointIn, point_id_of

_DOC_TYPE = ""


def collection_name(workspace_slug: str) -> str:
    return f"{workspace_slug}_{settings.COLLECTION_SUFFIX_MEDIA}"


def _text_and_hash(directive: MediaDirective) -> tuple[str, str]:
    caption = directive.caption or ""
    # Nhãn tiếng Việt chứ không phải mã thô: truy vấn của agent là tiếng Việt có dấu.
    nhan_danh_muc = NHAN_DANH_MUC.get(directive.category, directive.category)
    text = f"{nhan_danh_muc} {caption}".strip()
    return text, hashlib.sha256(f"{directive.media_url}␟{caption}".encode()).hexdigest()


class MediaClient(LocalIndexClient):
    target = "media"
    media_collection = True

    def collection(self, workspace_slug: str) -> str:
        return collection_name(workspace_slug)

    def content_hash_of(self, directive: MediaDirective) -> str:
        return _text_and_hash(directive)[1]

    async def index(self, directive: MediaDirective) -> IndexResult:
        name = self.collection(directive.workspace_slug)
        caption = directive.caption or ""
        text, content_hash = _text_and_hash(directive)
        caption_sach, _ = split_caption(caption)

        dense = await self._embed.dense([text])
        if len(dense) != 1:
            raise ValueError(f"embed dense trả {len(dense)} vector cho 1 nội dung")
        text_vec = dense[0]
        # Thumb trước: model visual nhìn ở 256px, còn ảnh gốc có thể 47 MB tải qua Internet.
        image_src = directive.thumb_url or directive.file_url or directive.media_url
        visual = await self._embed.visual_image([image_src]) if directive.content_type == "image" else []

        vectors = {"text": text_vec}
        if visual:
            vectors["visual"] = visual[0]

        point = PointIn(
            point_id=point_id_of(_DOC_TYPE, directive.record_id, 0),
            vectors=vectors,
            payload={
                "project_id": directive.anchor_code,
                "project_name": directive.anchor_name,
                "record_id": directive.record_id,
                "content_type": directive.content_type,
                "category": directive.category,
                "caption": caption_sach,
                "media_url": public_url_of(directive.media_url),
                "thumb_url": public_url_of(directive.thumb_url or ""),
                "content_hash": content_hash,
                "status": status_hieu_luc(directive.status, directive.anchor_status),
            },
        )
        await self._store.delete_by_record(name, record_id=directive.record_id, doc_type=_DOC_TYPE)
        n = await self._store.upsert(name, [point])
        return IndexResult(points_upserted=n, content_hash=content_hash)
