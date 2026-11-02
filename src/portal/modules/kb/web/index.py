"""Adapter Qdrant cho collection dùng chung `public_web` (không tenant)."""

import logging
from collections.abc import Sequence
from datetime import datetime

from qdrant_client import AsyncQdrantClient, models

from portal.modules.kb.index.store import DENSE_SIZE, SPARSE_NAME
from portal.modules.kb.web.compose import card_id, item_from_payload, payload_of, point_kind, searchable
from portal.modules.kb.web.contracts import COLLECTION, POINT_CARD, Item
from portal.modules.kb.web.locate import place_labels
from portal.modules.kb.web.normalize import same_project
from portal.modules.kb.web.usage import meter

log = logging.getLogger(__name__)

_INDEXES: tuple[tuple[str, models.PayloadSchemaType], ...] = (
    ("kind", models.PayloadSchemaType.KEYWORD),
    ("location", models.PayloadSchemaType.KEYWORD),
    ("projects", models.PayloadSchemaType.KEYWORD),
    ("published_at", models.PayloadSchemaType.DATETIME),
    ("updated_at", models.PayloadSchemaType.DATETIME),
)

_PAGE_SIZE = 500
MAX_SCAN = 5000
"""Trần số point quét trong `cards_near` — dossier/digest mang cùng khoá `location`
với thẻ, nên một khu vực đông dự án có thể cần lật nhiều trang mới gặp đủ thẻ.
Không cap thì một adapter lỗi (hàng nghìn point rác cùng location) làm quét vô hạn."""


class WebIndex:
    def __init__(self, *, client: AsyncQdrantClient, embed, collection: str = COLLECTION) -> None:
        self._c = client
        self._embed = embed
        self.collection = collection

    async def ensure(self) -> None:
        """Idempotent — gọi lại ở mỗi lượt chạy job không được xoá dữ liệu đã có."""
        if not await self._c.collection_exists(self.collection):
            await self._c.create_collection(
                self.collection,
                vectors_config={"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)},
                sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
        for key, schema in _INDEXES:
            try:
                await self._c.create_payload_index(self.collection, field_name=key, field_schema=schema, wait=True)
            except Exception as exc:  # noqa: BLE001 — Qdrant không có kiểu lỗi riêng cho "đã có"
                if "already exists" not in str(exc).lower():
                    raise

    async def get(self, ids: Sequence[str]) -> list[Item]:
        points = await self._c.retrieve(self.collection, ids=list(ids), with_payload=True)
        by_id = {str(p.id): item_from_payload(p.payload or {}) for p in points}
        return [by_id[i] for i in ids if i in by_id]

    async def replace(
        self,
        id_space: Sequence[str],
        items: Sequence[Item],
        now: datetime,
        *,
        written_at: datetime | None = None,
        header: str = "",
    ) -> int:
        """Upsert `items` vào `id_space[:len(items)]`, xoá phần còn lại của `id_space`.

        `now` thành `updated_at`; `written_at` (mặc định `now`) là ngày ghi ở dòng đầu `text`;
        `header` (tên, địa danh, loại) là dòng tiêu đề sau đó — được embed cùng nội dung.
        `kind` suy từ id (`point_kind`), bên gọi không tự khai.

        `id_space` là toàn bộ dải id của MỘT họ (dossier một dự án, hoặc digest một
        vùng) — phần thừa phải xoá để dự án rút từ 5 mục còn 2 không để lại rác.
        """
        items = list(items)[: len(id_space)]
        if items:
            payloads = [
                payload_of(
                    item,
                    now,
                    kind=point_kind(id_space[i], item.projects),
                    written_at=written_at,
                    header=header,
                )
                for i, item in enumerate(items)
            ]
            texts = [searchable(p["text"]) for p in payloads]
            dense = await self._embed.dense(texts)
            if (m := meter()) is not None:
                m.embed(texts)
            sparse = await self._embed.sparse(texts)
            if len(dense) != len(items) or len(sparse) != len(items):
                raise ValueError(f"embed trả thiếu: {len(items)} mục, {len(dense)} dense, {len(sparse)} sparse")
            await self._c.upsert(
                self.collection,
                points=[
                    models.PointStruct(
                        id=id_space[i],
                        vector={"dense": dense[i], SPARSE_NAME: models.SparseVector(**sparse[i])},
                        payload=payloads[i],
                    )
                    for i in range(len(items))
                ],
                wait=True,
            )
        stale = list(id_space[len(items) :])
        if stale:
            existing = [str(p.id) for p in await self._c.retrieve(self.collection, ids=stale, with_payload=False)]
            if existing:
                await self._c.delete(self.collection, points_selector=models.PointIdsList(points=existing), wait=True)
        return len(items)

    async def delete(self, ids: Sequence[str]) -> int:
        """Xoá các điểm có trong `ids` (điểm không tồn tại thì bỏ qua). Trả số điểm đã xoá."""
        if not ids or not await self._c.collection_exists(self.collection):
            return 0
        existing = [str(p.id) for p in await self._c.retrieve(self.collection, ids=list(ids), with_payload=False)]
        if existing:
            await self._c.delete(self.collection, points_selector=models.PointIdsList(points=existing), wait=True)
        return len(existing)

    async def cards_near(
        self,
        location: Sequence[str],
        exclude: str,
        limit: int = 20,
        *,
        page_size: int = _PAGE_SIZE,
        max_scan: int = MAX_SCAN,
    ) -> list[Item]:
        """Thẻ dự án lân cận theo địa danh trùng — loại điểm không phải thẻ (dossier/digest)
        và loại thẻ `same_project` với `exclude` (so dạng chuẩn hoá, không so chuỗi thô).

        Dossier/digest cùng `location` với thẻ nên MỘT trang quét không đủ — lật trang
        theo `offset` tới khi đủ `limit` thẻ, hết trang (`offset is None`), hoặc chạm
        `max_scan` (rồi cảnh báo, KHÔNG ném — thiếu vài thẻ vẫn tốt hơn treo request).
        """
        location = place_labels(location)
        if not location:
            return []
        loc = models.Filter(
            must=[
                models.FieldCondition(key="kind", match=models.MatchValue(value=POINT_CARD)),
                models.FieldCondition(key="location", match=models.MatchAny(any=list(location))),
            ]
        )
        out: list[Item] = []
        offset = None
        scanned = 0
        while True:
            points, offset = await self._c.scroll(
                self.collection, scroll_filter=loc, limit=page_size, offset=offset, with_payload=True
            )
            scanned += len(points)
            for p in points:
                pid = str(p.id)
                it = item_from_payload(p.payload or {})
                name = it.projects[0] if it.projects else ""
                if name and pid == card_id(name) and not same_project(name, exclude):
                    out.append(it)
                    if len(out) >= limit:
                        return out
            if offset is None:
                return out
            if scanned >= max_scan:
                log.warning(
                    "cards_near: chạm max_scan=%d cho collection=%s, location=%r — có thể còn thẻ chưa quét tới",
                    max_scan,
                    self.collection,
                    location,
                )
                return out
