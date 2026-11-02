"""Adapter Qdrant. AsyncQdrantClient — bản đồng bộ nuốt event loop của worker.

Hình dạng collection là HỢP ĐỒNG với repo agent: 8 collection đang sống trên EC2 có
đúng hình dạng dưới đây và agent đang query chúng. Đổi số chiều hay tên vector là
breaking change mà không test nào ở repo agent bắt được.
"""

import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from portal.modules.kb.contracts import IndexPoint

log = logging.getLogger(__name__)

DENSE_SIZE = 1024
VISUAL_SIZE = 768
SPARSE_NAME = "bm25"

_CHI_MUC_PAYLOAD: tuple[tuple[str, str], ...] = (
    ("status", "keyword"),
    ("project_id", "keyword"),
    ("doc_type", "keyword"),
    ("record_id", "integer"),
)

_NS = uuid.NAMESPACE_URL


@dataclass(frozen=True, slots=True)
class PointIn:
    point_id: str
    vectors: dict[str, Any]
    payload: dict


def point_id_of(doc_type: str, record_id: int, idx: int) -> str:
    """`uuid5(doc_type:record_id:idx)` — quy ước đã dùng cho 381 point đang sống.

    KHÔNG chứa tên bảng, nên miền giá trị doc_type phải đóng: một `tong_quan` từ
    documents sẽ ghi đè point của projects. Xem contracts.TITLE_PREFIXES.
    """
    return str(uuid.uuid5(_NS, f"{doc_type}:{record_id}:{idx}"))


def tach_tien_to(text: str, old_name: str) -> tuple[str, str] | None:
    """`("<old_name> — <mục>", "phần còn lại")`, hoặc `None` nếu dòng đầu không phải tiền tố."""
    head, sep, body = text.partition("\n\n")
    if not sep or not (head == old_name or head.startswith(f"{old_name} — ")):
        return None
    return head, body


@dataclass(frozen=True, slots=True)
class VectorPoint:
    point_id: str
    record_id: int
    doc_type: str
    text: str
    project_name: str
    vector: list[float] | None = None
    score: float = 0.0


def _vector_point(p: Any) -> VectorPoint:
    pl = dict(p.payload or {})
    text = str(pl.get("text") or "")
    name = str(pl.get("project_name") or "")
    bare = tach_tien_to(text, name) if name else None
    vec = p.vector.get("dense") if isinstance(p.vector, dict) else None
    return VectorPoint(
        point_id=str(p.id),
        record_id=int(pl.get("record_id") or 0),
        doc_type=str(pl.get("doc_type") or ""),
        text=bare[1] if bare else text,
        project_name=name,
        vector=list(vec) if vec is not None else None,
        score=float(getattr(p, "score", 0.0) or 0.0),
    )


def _project_filter(
    anchor_code: str,
    *,
    record_id: int | None = None,
    doc_types: Collection[str] = (),
    exclude_record_id: int | None = None,
    exclude_doc_types: Collection[str] = (),
) -> models.Filter:
    must: list[models.Condition] = [models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))]
    if record_id is not None:
        must.append(models.FieldCondition(key="record_id", match=models.MatchValue(value=record_id)))
    if doc_types:
        must.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=sorted(doc_types))))
    must_not: list[models.Condition] = []
    if exclude_record_id is not None:
        # record_id chỉ duy nhất trong một bảng: chỉ bỏ point của bản ghi đó trong các doc_type cho trước.
        own: list[models.Condition] = [
            models.FieldCondition(key="record_id", match=models.MatchValue(value=exclude_record_id))
        ]
        if exclude_doc_types:
            own.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=sorted(exclude_doc_types))))
        must_not.append(models.Filter(must=own))
    return models.Filter(must=must, must_not=must_not or None)


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
        """Tạo chỉ mục payload cho các khoá agent LỌC theo. Idempotent, trả tên khoá đã tạo.

        TÁCH KHỎI `ensure_collection` vì hàm đó thoát sớm khi collection đã tồn tại — đặt ở
        đó thì 8 collection đang sống không bao giờ có chỉ mục mới.

        Qdrant lọc được cả khi không có chỉ mục (nó quét), nên thiếu chỉ mục là chậm chứ
        không sai. Nhưng `status` nằm trên MỌI truy vấn của cả hai đường đọc (đó là mệnh đề
        duy nhất ngăn nội dung nháp tới khách), nên nó là khoá đáng lập chỉ mục nhất.

        `already exists` không phải lỗi: hàm này chạy lại ở mỗi lần nạp.
        """
        da_tao: list[str] = []
        for khoa, kieu in _CHI_MUC_PAYLOAD:
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

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str = "") -> int:
        """`record_id` MỘT MÌNH không định danh được point trong `<slug>_documents`.

        Ba bảng (`projects`/`zones`/`documents`) dùng chung collection đó và mỗi bảng có
        sequence riêng, nên `projects#5` và `zones#5` cùng tồn tại. Vị từ thứ hai là
        `doc_type` — ba tập giá trị của ba bảng RỜI NHAU (`tong_quan` / `phan_khu` /
        `csbh|phap_ly|huong_dan|khac`), và `tests/modules/kb/test_doc_type_roi_nhau.py`
        canh đúng tính chất đó. Mất tính rời nhau là xoá nhầm point của bảng khác.

        Khoá `entity` từng gánh việc này (2026-08-10 → 2026-08-14) nhưng đã bị bỏ khỏi
        payload vì nó suy được từ `doc_type`; chỗ chặn khi caller không có `doc_type` nằm
        ở `clients/base.py::_chan_xoa_mu`.

        `doc_type=""` đúng ở `_media`: một record đúng một point, một bảng nguồn.
        """
        if not await self._c.collection_exists(name):
            return 0
        must: list[models.Condition] = [
            models.FieldCondition(key="record_id", match=models.MatchValue(value=record_id))
        ]
        if doc_type:
            must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
        await self._c.delete(name, points_selector=models.Filter(must=must), wait=True)
        return 1

    async def count_by_doc_type(self, name: str, *, doc_type: str) -> int:
        if not await self._c.collection_exists(name):
            return 0
        loc = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])
        return (await self._c.count(name, count_filter=loc, exact=True)).count

    async def delete_by_doc_type(self, name: str, *, doc_type: str) -> int:
        """Xoá MỌI point của một loại. Chỉ dùng cho di trú — đường thường xoá theo record."""
        dem = await self.count_by_doc_type(name, doc_type=doc_type)
        if dem:
            loc = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])
            await self._c.delete(name, points_selector=loc, wait=True)
        return dem

    async def set_payload_theo_du_an(
        self,
        name: str,
        *,
        anchor_code: str,
        gia_tri: dict,
        chi_record_ids: list[int] | None = None,
    ) -> int:
        """Cập nhật payload của MỌI point thuộc một dự án — KHÔNG chạm vector.

        Đây là thứ làm "công bố tức thì" thành hiện thực: đổi trạng thái hay đổi tên không đổi
        nội dung, nên nhúng lại là trả tiền cho một vector y hệt. Một lời gọi cho cả dự án,
        không phải 116 lượt nhúng.

        `chi_record_ids` giới hạn thêm theo danh sách id — nhánh CÔNG BỐ cần nó: cột `status`
        per-record vẫn tồn tại và API vẫn đặt được, nên một lời gọi phẳng theo dự án sẽ BẬT SAI
        một hàng con đang nháp. Payload không còn giữ trạng thái thô (đã bỏ — Postgres là nguồn
        sự thật để soi) nên danh sách phải lấy từ Postgres rồi truyền vào đây.

        Trả về số point khớp vị từ, đo TRƯỚC khi ghi: Qdrant không trả số hàng đã cập nhật, và
        `0` là dấu hiệu vị từ sai — thứ duy nhất phân biệt "không có gì để đổi" với "lọc trượt".
        """
        if not await self._c.collection_exists(name):
            return 0
        must: list[models.Condition] = [
            models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))
        ]
        if chi_record_ids is not None:
            if not chi_record_ids:
                return 0
            must.append(models.FieldCondition(key="record_id", match=models.MatchAny(any=list(chi_record_ids))))
        loc = models.Filter(must=must)
        dem = (await self._c.count(name, count_filter=loc, exact=True)).count
        if dem:
            await self._c.set_payload(name, payload=gia_tri, points=loc, wait=True)
        return dem

    async def doi_ten_trong_text(self, name: str, *, anchor_code: str, ten_cu: str, ten_moi: str) -> int:
        """Ghi lại tiền tố tên dự án trong `text` của từng point — KHÔNG chạm vector.

        So thẳng vào chuỗi sắp ghi đè (`tach_tien_to`), không dựng lại tiền tố từ một khoá
        payload khác — payload không còn `section_path` từ 2026-08-19.
        """
        if ten_cu == ten_moi or not await self._c.collection_exists(name):
            return 0
        n = truot = 0
        for diem, pl in await self._scroll_payload(name, anchor_code):
            tach = tach_tien_to(str(pl.get("text") or ""), ten_cu)
            if tach is None:
                truot += 1
                continue
            dong_dau, than = tach
            moi = f"{ten_moi}{dong_dau[len(ten_cu) :]}"
            await self._c.set_payload(name, payload={"text": f"{moi}\n\n{than}"}, points=[diem], wait=True)
            n += 1
        if truot:
            log.warning("đổi nhãn %s: %d point có tiền tố không khớp %r — text giữ tên cũ", anchor_code, truot, ten_cu)
        return n

    async def _scroll_payload(self, name: str, anchor_code: str) -> list[tuple[str, dict]]:
        loc = models.Filter(must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))])
        ra: list[tuple[str, dict]] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name, scroll_filter=loc, limit=256, offset=offset, with_payload=True, with_vectors=False
            )
            ra.extend((str(p.id), dict(p.payload or {})) for p in batch)
            if offset is None:
                return ra

    async def scroll_points(self, name: str, *, anchor_code: str = "") -> list[IndexPoint]:
        """`anchor_code=""` = quét CẢ collection.

        Lọc theo `project_id`, KHÔNG theo `anchor_code`: khoá `anchor_code` đã bị bỏ khỏi
        payload 2026-08-14 (nó trùng đúng giá trị `project_id` — xem hợp đồng payload §6).
        Point hệ cũ cũng không có nó, nên mệnh đề theo `anchor_code` loại sạch cả point cũ
        lẫn point mới; `project_id` là khoá duy nhất có ở cả ba thế hệ point.
        """
        loc = (
            models.Filter(must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))])
            if anchor_code
            else None
        )
        ra: list[IndexPoint] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name,
                scroll_filter=loc,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            ra.extend(
                IndexPoint(
                    point_id=str(p.id),
                    record_id=int((p.payload or {}).get("record_id", 0)),
                    content_hash=str((p.payload or {}).get("content_hash", "")),
                    caption=str((p.payload or {}).get("caption", "")),
                )
                for p in batch
            )
            if offset is None:
                return ra

    async def scroll_payloads(self, name: str, *, anchor_code: str = "") -> list[tuple[str, dict]]:
        """`(point_id, payload)` đầy đủ. Khác `scroll_points`, hàm đó rút payload xuống
        bốn trường cho reconcile nên `text`/`project_id`/`status` mất."""
        if not await self._c.collection_exists(name):
            return []
        loc = (
            models.Filter(must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))])
            if anchor_code
            else None
        )
        ra: list[tuple[str, dict]] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name, scroll_filter=loc, limit=256, offset=offset, with_payload=True, with_vectors=False
            )
            ra.extend((str(p.id), dict(p.payload or {})) for p in batch)
            if offset is None:
                return ra

    async def points_with_vectors(
        self, name: str, *, anchor_code: str, record_id: int | None = None, doc_types: Collection[str] = ()
    ) -> list[VectorPoint]:
        """Đoạn của một dự án kèm vector `dense` — đầu vào của bộ dò mâu thuẫn."""
        if not await self._c.collection_exists(name):
            return []
        loc = _project_filter(anchor_code, record_id=record_id, doc_types=doc_types)
        ra: list[VectorPoint] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name, scroll_filter=loc, limit=256, offset=offset, with_payload=True, with_vectors=["dense"]
            )
            ra.extend(_vector_point(p) for p in batch)
            if offset is None:
                return ra

    async def similar(
        self,
        name: str,
        *,
        vector: list[float],
        anchor_code: str,
        exclude_record_id: int | None,
        doc_types: Collection[str],
        limit: int,
        min_score: float,
        exclude_doc_types: Collection[str] = (),
    ) -> list[VectorPoint]:
        """Đoạn gần nhất trong cùng dự án, bỏ đoạn của chính bản ghi, sắp theo điểm giảm dần."""
        res = await self._c.query_points(
            name,
            query=vector,
            using="dense",
            query_filter=_project_filter(
                anchor_code,
                doc_types=doc_types,
                exclude_record_id=exclude_record_id,
                exclude_doc_types=exclude_doc_types,
            ),
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return [_vector_point(p) for p in res.points]

    async def count(self, name: str) -> int:
        return (await self._c.count(name, exact=True)).count

    async def payload_of(self, name: str, *, point_id: str) -> dict:
        """Đọc payload một point. Dùng cho job thu hồi caption và test hợp đồng payload."""
        got = await self._c.retrieve(name, ids=[point_id], with_payload=True)
        return dict(got[0].payload or {}) if got else {}

    async def payload_many(self, name: str, point_ids: list[str]) -> dict[str, dict]:
        """Đọc payload của NHIỀU point theo id trong MỘT lượt gọi (Task 15 — xem lại nội
        dung đã nạp: dựng lại id bằng `point_id_of` cho `idx = 0..chunk_count-1`).

        Id không tồn tại (`chunk_count` lệch thực tế) đơn giản là vắng mặt trong dict trả
        về — `retrieve` của Qdrant tự bỏ qua, không ném.
        """
        if not point_ids or not await self._c.collection_exists(name):
            return {}
        got = await self._c.retrieve(name, ids=point_ids, with_payload=True)
        return {str(p.id): dict(p.payload or {}) for p in got}

    async def describe(self, name: str) -> dict:
        """Dùng cho test hợp đồng hình dạng — không dùng ở đường chạy thật."""
        info = await self._c.get_collection(name)
        params = info.config.params
        ra: dict[str, Any] = {"sparse": dict(params.sparse_vectors or {})}
        vectors = params.vectors
        if hasattr(vectors, "size"):
            ra["dense"] = vectors.size
        else:
            ra.update({k: v.size for k, v in (vectors or {}).items()})
        return ra
