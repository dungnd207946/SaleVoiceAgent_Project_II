"""Mặt tiền công khai của module kb: DTO HTTP, hằng job, kiểu dữ liệu giữa các tầng.

HAI LUỒNG vào cùng một kho Qdrant:
  A. «Tài liệu tra cứu» (`shop.kb_files`): upload → bóc chữ → chunk → nhúng.
  B. Dữ liệu DB (sản phẩm · chính sách · bài viết · FAQ · gói dịch vụ · ảnh SP): trigger
     `shop.kb_enqueue` tự xếp `kb_index`/`kb_delete`, handler dựng văn bản rồi nhúng.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from portal.core.dto import CamelOut

Entity = Literal["product", "policy", "article", "faq", "service_package", "product_media"]
ENTITIES: tuple[str, ...] = ("product", "policy", "article", "faq", "service_package", "product_media")
"""Khớp CHECK `kb_index_state.entity` và đối số của trigger `shop.kb_enqueue`."""

ENTITY_MEDIA = "product_media"
"""Thực thể DUY NHẤT đi vào collection `_media`; còn lại vào `_documents`."""

DOC_TYPE_KB_FILE = "kb_file"
"""doc_type của point kb_files. Rời khỏi mọi tên entity — nó cùng `record_id` là vị từ xoá
và là thành phần của point id, trùng tên là ghi đè point của bảng khác."""

KIND_INDEX = "kb_index"
KIND_DELETE = "kb_delete"
KIND_KB_FILE_INDEX = "kb_file_index"
KIND_REINDEX_ALL = "kb_reindex_all"
KINDS: tuple[str, ...] = (KIND_INDEX, KIND_DELETE, KIND_KB_FILE_INDEX, KIND_REINDEX_ALL)

RETRY_VIEC_KB = 2
LANE_INDEX = 4

LOAI_HO_TRO = ("pdf", "docx", "xlsx", "md")
"""Khớp CHECK `kb_files.file_type`. Không hỗ trợ: PDF scan không lớp chữ · tệp đặt mật khẩu."""

MD_EMPTY_MESSAGE = "Tệp Markdown không có nội dung nào — kiểm lại tệp rồi tải lên lại."
NO_TEXT_MESSAGE = (
    "Không bóc được chữ từ tệp này — PDF dạng scan (không có lớp chữ) chưa được hỗ trợ. "
    "Hãy tải bản PDF có lớp chữ, hoặc DOCX/Markdown."
)
SYSTEM_ERROR_MESSAGE = "Lỗi hệ thống khi nạp tài liệu — bấm «Nạp lại» hoặc tải lại tệp."


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    """`min_chars` là ngưỡng chống mảnh vụn — chunk ngắn hơn được gộp vào chunk trước cùng cha."""

    max_chars: int = 1000
    overlap: int = 100
    min_chars: int = 300


@dataclass(frozen=True, slots=True)
class DocMeta:
    """Khoá payload để agent LỌC. Dùng chung cho mọi point của `_documents` và `_media`."""

    product_id: int | None = None
    brand_id: int | None = None
    brand: str | None = None
    category: str | None = None
    product_ids: tuple[int, ...] = ()
    """Chỉ bài viết: mọi sản phẩm được gắn. `product_id` khi đó là sản phẩm duy nhất (nếu chỉ một)."""
    file_id: int | None = None
    file_name: str | None = None

    def payload(self) -> dict:
        ra: dict = {
            "product_id": self.product_id,
            "brand_id": self.brand_id,
            "brand": self.brand,
            "category": self.category,
        }
        if self.product_ids:
            ra["product_ids"] = list(self.product_ids)
        if self.file_id is not None:
            ra["file_id"] = self.file_id
            ra["file_name"] = self.file_name or ""
        return ra


@dataclass(frozen=True, slots=True)
class TextDoc:
    """Một bản ghi đã dựng thành văn bản, sẵn sàng chunk + nhúng vào `_documents`."""

    doc_type: str
    """= entity, hoặc `kb_file`."""
    record_id: int
    title: str
    text: str
    meta: DocMeta = field(default_factory=DocMeta)
    chunk: ChunkSpec = field(default_factory=ChunkSpec)


@dataclass(frozen=True, slots=True)
class MediaDoc:
    """Một ảnh/video sản phẩm cho `_media`. `caption` là thứ đem nhúng (vector `text`)."""

    record_id: int
    title: str
    caption: str
    media_type: str
    media_url: str
    meta: DocMeta = field(default_factory=DocMeta)
    color: str | None = None


@dataclass(frozen=True, slots=True)
class IndexResult:
    points_upserted: int = 0
    content_hash: str = ""


class ObjectStore(Protocol):
    """Kho tệp nhìn từ module kb. Cài thật: `storage/object_store.S3Store`."""

    def key(self, *, path: str) -> str: ...

    async def put(self, *, key: str, data: bytes, content_type: str) -> None: ...

    async def doc(self, *, key: str) -> bytes: ...

    async def delete(self, *, key: str) -> None: ...


class TemporaryError(RuntimeError):
    """Lỗi TẠM THỜI (mạng) — phân biệt với lỗi vĩnh viễn để cảnh báo nói đúng cách sửa."""


# ─── DTO HTTP ───────────────────────────────────────────────────────────────────


class KbFileOut(CamelOut):
    id: int
    file_name: str
    s3_key: str
    size_bytes: int
    file_type: str
    product_id: int | None
    brand_id: int | None
    state: str
    """`processing · ready · error`. Chỉ `ready` nghĩa là point đã lên Qdrant."""
    chunk_count: int
    error_message: str | None
    """Có khi `state == 'error'` — nói LÝ DO và CÁCH SỬA, không chỉ "Lỗi"."""
    uploaded_at: datetime


class ChunkOut(CamelOut):
    """Một đoạn đã nhúng, dựng lại từ payload Qdrant — thứ agent thật sự đọc."""

    idx: int
    text: str
    section: str
    """Cấp tiêu đề cuối của đoạn; rỗng nếu đoạn nằm ngoài mọi tiêu đề."""
    overlaps_prev: bool
    """`text` mở đầu bằng phần đuôi lặp lại của đoạn trước (overlap của chunker)."""


class DemOut(CamelOut):
    state: str
    count: int


class DemEntityOut(DemOut):
    entity: str


class DemJobOut(DemOut):
    kind: str


class KbStatusOut(CamelOut):
    records: list[DemEntityOut]
    """Sổ `kb_index_state` theo (entity, state)."""
    files: list[DemOut]
    """`kb_files` theo state."""
    jobs: list[DemJobOut]
    """Job kb_* đang `queued`/`running`/`failed`."""


class ReindexOut(CamelOut):
    job_id: int | None = Field(description="Null = đã có một lượt reindex đang chờ")
