"""Adapter Qdrant. AsyncQdrantClient — bản đồng bộ nuốt event loop của worker.

Hình dạng collection là HỢP ĐỒNG với repo agent: đổi số chiều hay tên vector là breaking
change mà không test nào phía agent bắt được.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

DENSE_SIZE = 1024
VISUAL_SIZE = 768
SPARSE_NAME = "bm25"

CHI_MUC_PAYLOAD: tuple[tuple[str, str], ...] = (
    ("entity", "keyword"),
    ("doc_type", "keyword"),
    ("record_id", "integer"),
    ("product_id", "integer"),
    ("brand_id", "integer"),
    ("brand", "keyword"),
    ("category", "keyword"),
    ("file_id", "integer"),
)
"""Khoá agent LỌC theo. Thiếu chỉ mục thì Qdrant vẫn lọc (quét) — chậm chứ không sai."""

_NS = uuid.NAMESPACE_URL


@dataclass(frozen=True, slots=True)
class PointIn:
    point_id: str
    vectors: dict[str, Any]
    payload: dict


def point_id_of(doc_type: str, record_id: int, idx: int) -> str:
    """`uuid5(doc_type:record_id:idx)` — tất định, nên nạp lại ghi ĐÈ chứ không nhân bản,
    và dựng lại được id để đọc nội dung đã nạp mà không phải scroll.

    `doc_type` là tên entity (hoặc `kb_file`): mỗi bảng một sequence riêng nên `product#5`
    và `faq#5` cùng tồn tại — thiếu `doc_type` trong id là ghi đè point của bảng khác."""
    return str(uuid.uuid5(_NS, f"{doc_type}:{record_id}:{idx}"))


def tach_tien_to(text: str, title: str) -> tuple[str, str] | None:
    """`("<title> — <mục>", "phần còn lại")`, hoặc `None` nếu dòng đầu không phải tiền tố."""
    head, sep, body = text.partition("\n\n")
    if not sep or not (head == title or head.startswith(f"{title} — ")):
        return None
    return head, body


class QdrantStore:
    def __init__(self, *, url: str, api_key: str = "") -> None:
        self._c = AsyncQdrantClient(url=url, api_key=api_key or None)
        self._closed = False

    async def aclose(self) -> None:
        """Idempotent: `rag` và `media` dùng chung một store, cả hai đều đóng nó."""
        if self._closed:
            return
        self._closed = True
        await self._c.close()

    async def ensure_collection(self, name: str, *, media: bool) -> None:
        """Idempotent: job retry gọi lại, lần hai không được xoá dữ liệu lần một."""
        if await self._c.collection_exists(name):
            return
        if media:
            vectors = {
                "text": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE),
                "visual": models.VectorParams(size=VISUAL_SIZE, distance=models.Distance.COSINE),
            }
            sparse = None
        else:
            vectors = {"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)}
            sparse = {SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)}
        await self._c.create_collection(name, vectors_config=vectors, sparse_vectors_config=sparse)

    async def ensure_payload_indexes(self, name: str) -> list[str]:
        """Tách khỏi `ensure_collection` (hàm đó thoát sớm khi collection đã có — đặt chỉ mục
        ở đó thì collection đang sống không bao giờ có chỉ mục mới). `already exists` không phải lỗi."""
        da_tao: list[str] = []
        for khoa, kieu in CHI_MUC_PAYLOAD:
            try:
                await self._c.create_payload_index(name, field_name=khoa, field_schema=kieu, wait=True)
                da_tao.append(khoa)
            except Exception as exc:  # noqa: BLE001 — Qdrant không có kiểu lỗi riêng cho "đã có"
                if "already exists" not in str(exc).lower():
                    raise
        return da_tao

    async def drop_collection(self, name: str) -> None:
        await self._c.delete_collection(name)

    async def upsert(self, name: str, points: list[PointIn]) -> int:
        if not points:
            return 0
        await self._c.upsert(
            name,
            points=[models.PointStruct(id=p.point_id, vector=p.vectors, payload=p.payload) for p in points],
            wait=True,
        )
        return len(points)

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str) -> None:
        """Vị từ LUÔN gồm cả `doc_type`: `record_id` một mình trùng giữa các bảng."""
        if not doc_type:
            raise ValueError(f"xoá record #{record_id} mà không có doc_type — sẽ cuốn theo point của bảng khác")
        if not await self._c.collection_exists(name):
            return
        loc = models.Filter(
            must=[
                models.FieldCondition(key="record_id", match=models.MatchValue(value=record_id)),
                models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)),
            ]
        )
        await self._c.delete(name, points_selector=loc, wait=True)

    async def payload_many(self, name: str, point_ids: list[str]) -> dict[str, dict]:
        """Payload của NHIỀU point trong MỘT lượt. Id không tồn tại thì vắng mặt, không ném."""
        if not point_ids or not await self._c.collection_exists(name):
            return {}
        got = await self._c.retrieve(name, ids=point_ids, with_payload=True)
        return {str(p.id): dict(p.payload or {}) for p in got}
