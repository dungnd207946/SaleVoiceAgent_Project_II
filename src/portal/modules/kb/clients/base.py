"""Phần chung của hai client index: mở collection, xoá theo bản ghi, đóng kết nối.

`rag.py`/`media.py` khác nhau đúng ở `index()` — hình dạng point và vector.
"""

from portal.modules.kb.index.store import QdrantStore


class LocalIndexClient:
    """Pipeline nội bộ: (chunk) → embed → Qdrant. Tên collection cố định theo cấu hình."""

    media_collection = False

    def __init__(self, *, embed, store: QdrantStore, collection: str) -> None:
        self._embed = embed
        self._store = store
        self.collection = collection

    async def ensure_collection(self) -> None:
        """Collection + chỉ mục payload, cả hai idempotent — gọi trước mỗi lượt ghi rẻ hơn
        một bước "provision" riêng mà ai đó sẽ quên chạy trên môi trường mới."""
        await self._store.ensure_collection(self.collection, media=self.media_collection)
        await self._store.ensure_payload_indexes(self.collection)

    async def delete(self, *, record_id: int, doc_type: str) -> None:
        await self._store.delete_by_record(self.collection, record_id=record_id, doc_type=doc_type)
