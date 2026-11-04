"""Đường text → collection `<prefix>_documents`.

HÌNH DẠNG PAYLOAD LÀ HỢP ĐỒNG với repo agent (`kb_search`):
  entity · record_id · doc_type · title · text · chunk_idx · content_hash
  · product_id · brand_id · brand · category  (+ product_ids cho bài viết)
  · file_id · file_name                        (chỉ kb_file)
Đổi tên khoá ở đây là sửa hợp đồng, không phải sửa code.
"""

import hashlib

from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.clients.external_images import IMG_MD_RE
from portal.modules.kb.contracts import IndexResult, TextDoc
from portal.modules.kb.index import chunker
from portal.modules.kb.index.store import PointIn, point_id_of

_PHAN_CACH_BAM = "␟"


def _tien_to(doc: TextDoc, c: chunker.Chunk) -> str:
    """Tiêu đề bản ghi + cấp CUỐI của section. Đoạn thứ 5 của bảng thông số không mang tên
    máy thì agent trả lời đúng thông số cho SAI máy. Chỉ cấp cuối để không ăn trần ký tự."""
    duoi = c.section_path[-1] if c.section_path else ""
    if duoi == doc.title:
        duoi = ""
    return f"{doc.title} — {duoi}".strip(" —")


def text_payload(doc: TextDoc, c: chunker.Chunk) -> str:
    """`payload["text"]` — markdown NGUYÊN VẸN kể cả `![alt](url)`: agent đọc trường này."""
    prefix = _tien_to(doc, c)
    return f"{prefix}\n\n{c.text}" if prefix else c.text


def _text_de_nhung(doc: TextDoc, c: chunker.Chunk) -> str:
    """Chuỗi ĐEM NHÚNG: URL ảnh thay bằng alt — URL dài không mang nghĩa, chỉ làm nhiễu vector."""
    prefix = _tien_to(doc, c)
    than = IMG_MD_RE.sub(lambda m: m.group(1), c.text)
    return f"{prefix}\n\n{than}" if prefix else than


def hash_of_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest() if text else ""


def chunks_of(doc: TextDoc) -> list[chunker.Chunk]:
    return chunker.split(doc.text, doc.chunk)


class RagClient(LocalIndexClient):
    media_collection = False

    async def index(self, doc: TextDoc, *, content_hash: str = "") -> IndexResult:
        """Xoá point cũ của bản ghi rồi ghi mới — số chunk có thể giảm, ghi đè theo id không đủ."""
        chunks = chunks_of(doc)
        texts = [_text_de_nhung(doc, c) for c in chunks]
        content_hash = content_hash or hash_of_text(_PHAN_CACH_BAM.join(c.text for c in chunks))

        await self.delete(record_id=doc.record_id, doc_type=doc.doc_type)
        if not texts:
            return IndexResult(points_upserted=0, content_hash=content_hash)

        dense = await self._embed.dense(texts)
        sparse = await self._embed.sparse(texts)
        if len(dense) != len(texts) or len(sparse) != len(texts):
            raise ValueError(f"embed trả thiếu: {len(texts)} chunk nhưng {len(dense)} dense / {len(sparse)} sparse")

        meta = doc.meta.payload()
        points = [
            PointIn(
                point_id=point_id_of(doc.doc_type, doc.record_id, i),
                vectors={"dense": dense[i], "bm25": {"indices": s["indices"], "values": s["values"]}},
                payload={
                    "entity": doc.doc_type,
                    "record_id": doc.record_id,
                    "doc_type": doc.doc_type,
                    "title": doc.title,
                    "text": text_payload(doc, c),
                    "chunk_idx": i,
                    "content_hash": content_hash,
                    **meta,
                },
            )
            for i, (c, s) in enumerate(zip(chunks, sparse, strict=True))
        ]
        n = await self._store.upsert(self.collection, points)
        return IndexResult(points_upserted=n, content_hash=content_hash)
