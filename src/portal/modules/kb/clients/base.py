"""Phần chung của hai client thật: mở/đóng collection, xoá, liệt kê point.

`rag.py`/`media.py` khác nhau đúng ở `index()` — hình dạng chunk và vector.
"""

from portal.modules.kb.contracts import IndexResult, Target


class LocalIndexClient:
    """Cài `contracts.IndexClient` bằng pipeline nội bộ: chunk → embed → Qdrant.

    THAY CHO HttpIndexClient (gọi rag_service của santa-models). Service đó chưa bao giờ
    tồn tại và chủ dự án đã chốt Portal làm độc lập — xem spec 2026-08-10 §1.

    Lớp này giữ nguyên interface để `service.py` và mọi test hiện có không phải đổi một dòng.
    """

    target: Target = "documents"
    media_collection = False

    def __init__(self, *, embed, store) -> None:
        self._embed = embed
        self._store = store

    def collection(self, workspace_slug: str) -> str:
        raise NotImplementedError

    async def aclose(self) -> None:
        """Đóng httpx của embed và AsyncQdrantClient của store.

        Chịu được lời gọi thứ hai: `rag` và `media` dùng CHUNG một cặp (xem
        `jobs.dependencies`), nên khối dọn của worker đóng cả hai và nửa sau không
        được nổ.
        """
        await self._embed.aclose()
        await self._store.aclose()

    async def create_collection(self, *, workspace_slug: str) -> None:
        await self._store.ensure_collection(self.collection(workspace_slug), media=self.media_collection)

    async def ensure_payload_indexes(self, *, workspace_slug: str) -> list[str]:
        """Tách khỏi `create_collection` — xem `ops/collections.create`."""
        return await self._store.ensure_payload_indexes(self.collection(workspace_slug))

    async def drop_collection(self, *, workspace_slug: str) -> None:
        await self._store.drop_collection(self.collection(workspace_slug))

    async def set_payload(
        self,
        *,
        workspace_slug: str,
        anchor_code: str,
        gia_tri: dict,
        chi_record_ids: list[int] | None = None,
    ) -> int:
        """Cập nhật payload theo dự án, không chạm vector — xem `QdrantStore`."""
        return await self._store.set_payload_theo_du_an(
            self.collection(workspace_slug),
            anchor_code=anchor_code,
            gia_tri=gia_tri,
            chi_record_ids=chi_record_ids,
        )

    async def doi_ten_trong_text(self, *, workspace_slug: str, anchor_code: str, ten_cu: str, ten_moi: str) -> int:
        """Ghi lại tiền tố tên dự án trong `text` — xem `QdrantStore`."""
        return await self._store.doi_ten_trong_text(
            self.collection(workspace_slug), anchor_code=anchor_code, ten_cu=ten_cu, ten_moi=ten_moi
        )

    async def count_by_doc_type(self, *, workspace_slug: str, doc_type: str) -> int:
        return await self._store.count_by_doc_type(self.collection(workspace_slug), doc_type=doc_type)

    async def delete_by_doc_type(self, *, workspace_slug: str, doc_type: str) -> int:
        return await self._store.delete_by_doc_type(self.collection(workspace_slug), doc_type=doc_type)

    async def delete(self, *, workspace_slug: str, record_id: int, doc_type: str = "", entity: str = "") -> IndexResult:
        """`entity` GIỮ trong chữ ký nhưng KHÔNG còn là vị từ xoá (2026-08-14).

        Khoá `entity` đã bị bỏ khỏi payload (nó suy được từ `doc_type`, xem
        docs/contracts/payload-qdrant.md §6). Vị từ thứ hai nay là `doc_type`, và
        `_chan_xoa_mu` bên dưới là chỗ chặn khi caller không có nó.

        Tham số vẫn nhận vì `service.delete_index` và `delete_cascade` truyền nó, và nó
        vẫn cần cho việc CHỌN client (media hay rag) ở tầng trên.
        """
        self._chan_xoa_mu(record_id=record_id, doc_type=doc_type)
        n = await self._store.delete_by_record(self.collection(workspace_slug), record_id=record_id, doc_type=doc_type)
        return IndexResult(points_deleted=n)

    def _chan_xoa_mu(self, *, record_id: int, doc_type: str) -> None:
        """Nổ khi xoá ở collection `_documents` mà không biết `doc_type`.

        `<slug>_documents` chứa point của BA bảng dùng ba sequence riêng, nên `projects#5`
        và `documents#5` cùng tồn tại. Không có `doc_type` thì vị từ duy nhất còn lại là
        `record_id` — xoá một tài liệu sẽ cuốn theo point của dự án cùng số id, IM LẶNG.

        Trước 2026-08-14 khoá `entity` trong payload gánh việc này. Bỏ nó đi mà không thay
        bằng chỗ chặn nào là mở lại đúng cái lỗ đó, nên chỗ chặn phải NỔ chứ không được
        đoán: `service.delete_index` đã biết cách tra `doc_type` từ sổ, và nếu sổ rỗng thì
        nó không gọi tới đây lần nào.
        """
        if not self.media_collection and not doc_type:
            raise ValueError(
                f"xoá record #{record_id} ở {self.target!r} mà không có doc_type — "
                "vị từ duy nhất còn lại là record_id, sẽ cuốn theo point của bảng khác. "
                "Tra doc_type từ sổ kb_index_state trước khi gọi."
            )
