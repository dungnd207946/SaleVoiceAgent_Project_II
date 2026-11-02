"""Đường text → collection `<slug>_documents`.

Trước 2026-08-10 file này là vỏ cho một `rag_service` bên santa-models. Service đó
không tồn tại; pipeline nay chạy trong chính Portal.

HÌNH DẠNG PAYLOAD LÀ HỢP ĐỒNG HAI ĐẦU với repo agent — xem
`docs/contracts/payload-qdrant.md`. Không có test nào ở hai repo bắt được một lần lệch
tên khoá: phía agent, test ghim tên khoá dùng trong FILTER nhưng KHÔNG ghim tên khoá được
RENDER (chúng tự dựng dict hit). Đổi tên khoá ở đây là sửa hợp đồng, không phải sửa code.
"""

import hashlib
import re

from portal.core.public_url import public_url_of
from portal.modules.kb import settings
from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.clients.external_images import IMG_MD_RE
from portal.modules.kb.clients.trang_thai import status_hieu_luc
from portal.modules.kb.contracts import IndexResult, TextDirective
from portal.modules.kb.index import chunker
from portal.modules.kb.index.store import PointIn, point_id_of

_PHAN_CACH_BAM = "␟"
_EXTERNAL_IMG = re.compile(r"!\[[^\]]*\]\(https?://")


def collection_name(workspace_slug: str) -> str:
    return f"{workspace_slug}_{settings.COLLECTION_SUFFIX_DOCUMENTS}"


def _chunks(directive: TextDirective) -> list[chunker.Chunk]:
    return chunker.split(directive.text, directive.chunk, root=directive.chunk_root)


def _tien_to(directive: TextDirective, c: chunker.Chunk) -> str:
    """Tiền tố RÚT GỌN: tên dự án + cấp cuối của đường dẫn section.

    Chunk thứ 5 của một tài liệu không mang tên dự án thì agent trả lời đúng nội dung cho
    sai dự án. Nhưng chỉ lấy CẤP CUỐI, không cả đường dẫn: đường dẫn đầy đủ đi vào payload
    `section_path`, và nhồi nó vào text sẽ ăn 8–12% trần 1000 ở MỌI chunk.
    """
    duoi = c.section_path[-1] if c.section_path else ""
    return f"{directive.anchor_name} — {duoi}".strip(" —")


def _text_payload(directive: TextDirective, c: chunker.Chunk) -> str:
    """`payload["text"]` — markdown NGUYÊN VẸN, kể cả `![alt](url)`. Agent đọc trường
    này để dựng `items`; xem `_text_de_nhung` cho chuỗi khác đi vào embed."""
    prefix = _tien_to(directive, c)
    return f"{prefix}\n\n{c.text}" if prefix else c.text


def _text_de_nhung(directive: TextDirective, c: chunker.Chunk) -> str:
    """Chuỗi ĐEM NHÚNG — khác `payload["text"]`, và khác có chủ ý.

    URL ảnh bị thay bằng chính `alt` của nó: một URL S3 dài ~130 ký tự không mang nghĩa
    nào cho phép tìm ngữ nghĩa, nó chỉ ăn chỗ trong vector. Đo trên sổ tay CTV: bỏ URL
    khỏi chuỗi nhúng nhấc ảnh mong đợi từ hạng 1 **7/10 lên 8/10**, và URL trong bài đo
    chỉ dài 67 ký tự — nhiễu thật gấp đôi.

    ⚠️ `payload["text"]` VẪN giữ markdown đầy đủ: đó là thứ agent đọc để dựng `items`,
    bỏ URL ở đó là mất luôn ảnh. Nên từ bản này `text` KHÔNG còn bằng chuỗi đã nhúng —
    `docs/contracts/payload-qdrant.md` §3 đã sửa theo.

    `IMG_MD_RE` là regex CỦA `external_images` — từng có một bản chép tay riêng ở đây,
    không cân bằng ngoặc tròn trong URL nên cắt cụt `file(1).png` và dán đuôi vào ảnh
    kế tiếp. Dùng chung để hai nơi không lệch nhau lần nữa.
    """
    prefix = _tien_to(directive, c)
    than = IMG_MD_RE.sub(lambda m: m.group(1), c.text)
    return f"{prefix}\n\n{than}" if prefix else than


def _hash_of(chunks: list[chunker.Chunk]) -> str:
    """Băm NỘI DUNG THUẦN, KHÔNG gồm tiền tố — đây là cả lý do hàm này tồn tại riêng.

    Trước 2026-08-14 dấu tay tính trên chuỗi ĐÃ gắn tiền tố, nên đổi tên dự án làm dấu tay
    của MỌI phân khu và MỌI tài liệu con đổi theo ⇒ nhúng lại cả cây (một dự án có thể 116
    record) trong khi nội dung không đổi một chữ. Nay đổi tên chỉ cập nhật payload.

    `section_path` KHÔNG vào dấu tay cùng lý do: đổi tên phân khu là đổi nhãn, không đổi
    nội dung. Nội dung của một section thì vẫn gồm dòng tiêu đề của CHÍNH nó (chunker giữ
    dòng `##` trong text), nên đổi tiêu đề một mục vẫn được nhận là thay đổi thật.
    """
    return hashlib.sha256(_PHAN_CACH_BAM.join(c.text for c in chunks).encode()).hexdigest() if chunks else ""


def _updated_at(directive: TextDirective) -> str:
    v = directive.updated_at
    if v is None:
        return ""
    iso = getattr(v, "isoformat", None)
    return iso() if callable(iso) else str(v)


def _check_mirrored(directive: TextDirective) -> None:
    """Ném nếu directive chưa đi qua `external_images.mirror_images`.

    Hàm RIÊNG chứ không phải vài dòng trong `index`: cổng này phải test được mà không
    dựng cả client (embed + Qdrant + kho), và một bài test phải khẳng định ĐÚNG cái nó
    đo — bắt `AttributeError` của một instance nửa vời là đo nhầm thứ.
    """
    if not directive.images_mirrored and _EXTERNAL_IMG.search(directive.text):
        raise ValueError(
            f"directive {directive.doc_type}#{directive.record_id} chưa soi ảnh ngoài — "
            "gọi `external_images.mirror_images` trước khi băm và nhúng"
        )


class RagClient(LocalIndexClient):
    target = "documents"
    media_collection = False

    def collection(self, workspace_slug: str) -> str:
        return collection_name(workspace_slug)

    def content_hash_of(self, directive: TextDirective) -> str:
        return _hash_of(_chunks(directive))

    async def index(self, directive: TextDirective) -> IndexResult:
        _check_mirrored(directive)
        name = self.collection(directive.workspace_slug)
        chunks = _chunks(directive)
        texts = [_text_de_nhung(directive, c) for c in chunks]
        payload_texts = [_text_payload(directive, c) for c in chunks]

        await self._store.delete_by_record(name, record_id=directive.record_id, doc_type=directive.doc_type)
        if not texts:
            return IndexResult(points_upserted=0, content_hash="")

        content_hash = _hash_of(chunks)

        dense = await self._embed.dense(texts)
        sparse = await self._embed.sparse(texts)
        if len(dense) != len(texts) or len(sparse) != len(texts):
            raise ValueError(f"embed trả thiếu: {len(texts)} chunk nhưng {len(dense)} dense / {len(sparse)} sparse")

        status = status_hieu_luc(directive.status, directive.anchor_status)
        updated_at = _updated_at(directive)
        file_public_url = public_url_of(directive.file_url or "")
        thumb_url = public_url_of(directive.thumb_url or "")

        points = [
            PointIn(
                point_id=point_id_of(directive.doc_type, directive.record_id, i),
                vectors={"dense": dense[i], "bm25": {"indices": s["indices"], "values": s["values"]}},
                payload={
                    "project_id": directive.anchor_code,
                    "project_name": directive.anchor_name,
                    "record_id": directive.record_id,
                    "doc_type": directive.doc_type,
                    "text": payload_texts[i],
                    "content_hash": content_hash,
                    "updated_at": updated_at,
                    "status": status,
                    "file_public_url": file_public_url,
                    "file_name": directive.file_name or "",
                    "thumb_url": thumb_url,
                },
            )
            for i, s in enumerate(sparse)
        ]
        n = await self._store.upsert(name, points)
        return IndexResult(points_upserted=n, content_hash=content_hash)
