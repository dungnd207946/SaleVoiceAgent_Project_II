"""Mặt tiền công khai: DTO + Protocol. File duy nhất module khác được import.

Hai Protocol là seam để `fake.py` thay santa-models và S3 trong test.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

Target = Literal["documents", "media"]
Op = Literal["upsert", "delete"]
IndexState = Literal["queued", "indexing", "indexed", "error", "deleted", "skipped"]


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    """KHÔNG còn `strategy` (2026-08-14): chunker chỉ còn MỘT chiến lược hierarchical.

    `min_chars` là ngưỡng chống mảnh vụn — chunk ngắn hơn nó được gộp vào chunk trước
    cùng cha. `0` = tắt phép gộp.
    """

    max_chars: int = 1000
    overlap: int = 100
    min_chars: int = 300


@dataclass(frozen=True, slots=True)
class TextDirective:
    """Directive cho rag_service (§4.1)."""

    workspace_slug: str
    record_id: int
    doc_type: str
    anchor_code: str
    anchor_name: str
    section: str
    text: str
    chunk: ChunkSpec
    chunk_root: tuple[str, ...] = ()
    source_file_url: str | None = None
    extract_profile: str | None = None
    status: str = ""
    anchor_status: str = ""
    updated_at: object | None = None
    file_url: str | None = None
    file_name: str | None = None
    thumb_url: str | None = None
    entity: str = ""
    images_mirrored: bool = False
    """Đã chạy `external_images.mirror_images` trên `text` chưa.

    Cờ CHỨ KHÔNG phải phép kiểm «text không còn URL lạ»: soi xong mà một ảnh 404 thì
    URL gốc CỐ Ý ở lại (xem `mirror_images`), nên một phép kiểm theo nội dung sẽ đánh trượt
    đúng ca hợp lệ. Cái cần canh là «đường nạp có gọi soi hay không»."""


@dataclass(frozen=True, slots=True)
class MediaDirective:
    """Directive cho media_service (§4.1)."""

    workspace_slug: str
    record_id: int
    anchor_code: str
    content_type: Literal["image", "video", "tour_360"]
    category: str
    media_url: str
    file_url: str | None = None
    caption: str | None = None
    caption_profile: str | None = None
    thumb_url: str | None = None
    anchor_name: str = ""
    status: str = ""
    anchor_status: str = ""


@dataclass(frozen=True, slots=True)
class IndexResult:
    points_upserted: int = 0
    points_deleted: int = 0
    content_hash: str = ""
    caption: str | None = None
    extracted_text: str | None = None
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class IndexPoint:
    """Một point trong collection, trả từ `store.scroll_points`.

    `caption` lấy thẳng từ payload mà scroll đã tải sẵn, để job thu hồi caption (Task 11)
    không phải gọi lại `payload_of()` cho từng point — rỗng ở entity không phải media.
    """

    point_id: str
    record_id: int
    content_hash: str
    caption: str = ""


class IndexClient(Protocol):
    async def index(self, directive: TextDirective | MediaDirective) -> IndexResult: ...

    def content_hash_of(self, directive: TextDirective | MediaDirective) -> str:
        """Hash của nội dung SẼ ghi ra, tính mà không gọi embed — nền của chế độ delta.

        Đồng bộ vì thuần CPU. Phải khớp từng bit với `IndexResult.content_hash` mà
        `index()` trả về, nếu không delta bỏ qua record đã đổi và không ai thấy.
        """
        ...

    async def delete(
        self, *, workspace_slug: str, record_id: int, doc_type: str = "", entity: str = ""
    ) -> IndexResult: ...

    async def create_collection(self, *, workspace_slug: str) -> None: ...

    async def drop_collection(self, *, workspace_slug: str) -> None: ...


class ObjectStore(Protocol):
    async def presign_get(self, *, key: str, ttl_sec: int = 300) -> str: ...

    async def put(self, *, key: str, data: bytes, content_type: str) -> str: ...

    async def delete(self, *, key: str) -> None: ...

    async def doc(self, *, key: str) -> bytes:
        """Đọc byte. Cần cho bóc chữ: Docling nhận tệp, không nhận URL."""
        ...

    def key(self, *, tenant_id: str, path: str) -> str:
        """Mọi key phải đi qua đây — nó ghép prefix tenants/<tenant>/."""
        ...


@dataclass(frozen=True, slots=True)
class ChildBlockSpec:
    """Bảng con gộp vào doc của anchor thành MỘT khối, thay vì một doc_type riêng."""

    table: str
    name_col: str
    section: str
    subsection: str
    fields: tuple[str, ...]
    field_labels: Mapping[str, str]
    value_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    anchor_col: str = "project_code"
    # Trường có nhãn nằm ở đây in riêng một dòng «Nhãn: giá trị» thay vì gộp vào dòng tóm tắt.
    line_fields: tuple[str, ...] = ()
    # Cấp con lồng trong từng hàng: hàng của `child` có `child.parent_col` bằng `key_col` của hàng này.
    key_col: str = ""
    parent_col: str = ""
    child: "ChildBlockSpec | None" = None
    orphan_heading: str = ""


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """Một nguồn embed. `source/query.py` sinh SQL từ đây nên nó vertical-agnostic."""

    table: str
    doc_type: str
    fields: tuple[str, ...]
    extra_cols: tuple[str, ...] = ()
    anchor_col: str = "project_code"
    is_anchor: bool = False
    section_col: str | None = None
    field_labels: Mapping[str, str] = field(default_factory=dict)
    noi_dung_da_markdown: bool = False
    doc_type_from: Callable[[dict], str] | None = None
    child_block: ChildBlockSpec | None = None
    # Đổi giá trị thô thành chữ trước khi ghép (jsonb, tiền). Trả rỗng thì bỏ trường.
    formatters: Mapping[str, Callable[[object], str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerticalSpec:
    """Phần template mà ingest cần. `fields`/`enums`/`completeness` là đồ của M4."""

    key: str
    anchor_table: str
    anchor_code_col: str
    embed_sources: tuple[EntitySpec, ...]
    media_visual: tuple[str, ...]
    media_anchor_col: str = "project_code"
    caption_profiles: dict[str, str] = field(default_factory=dict)
    document_extract: dict[str, str] = field(default_factory=dict)


class TaiLieuOut(BaseModel):
    """Một hàng của màn «Tài liệu tra cứu». camelCase vì đây là hợp đồng HTTP —
    khớp từng field với `odyssey-portal-frontend/src/features/kb/api.ts` (FE không sửa gì)."""

    id: int
    tenFile: str
    loai: str
    kichThuoc: int
    state: str
    """`dang_xu_ly · san_sang · loi` — CHECK của migration 0300. Chỉ `san_sang`
    nghĩa là point đã lên Qdrant (BR06)."""
    chunkCount: int
    loiMessage: str
    """Rỗng trừ khi `state == 'loi'`. Phải nói LÝ DO VÀ CÁCH SỬA, không chỉ "Lỗi"."""
    uploadedAt: datetime
    uploadedBy: str | None


class NoiDungDoanOut(BaseModel):
    """Một đoạn (chunk) đã nhúng, dựng lại từ payload Qdrant — spec Task 15.

    `sectionPath` là CẤP CUỐI của đường dẫn tiêu đề (chunker giữ cả đường dẫn nhưng
    `rag.py` chỉ gắn cấp cuối vào text trước khi nhúng — payload không mang phần còn
    lại). Rỗng cho đoạn nằm ngoài mọi tiêu đề.
    """

    idx: int
    text: str
    sectionPath: str
    overlapsPrev: bool
    """`text` mở đầu bằng phần đuôi lặp lại của đoạn trước — chunker mượn lại nó
    (overlap cấu hình, hoặc dòng văn xuôi mượn trước ảnh, xem `index/chunker.py`).
    Đoạn đầu tiên luôn `False`."""


KIND_DELETE_INDEX = "kb_delete"
KIND_INDEX = "kb_index"
KIND_KB_FILE_INDEX = "kb_file_index"
"""Job nạp MỘT tệp của kho «Tài liệu tra cứu» — spec 2026-08-20."""

DOC_TYPE_KB_FILE = "kb_file"
"""doc_type của point kb_files trong `<slug>_documents`. PHẢI rời khỏi mọi doc_type
khác — nó là vị từ xoá; `tests/modules/kb/test_doc_type_roi_nhau.py` canh."""

LOAI_HO_TRO = ("pdf", "docx", "xlsx", "md")
"""KB_01 §I.2 — khớp CHECK `kb_files_loai_check` của migration 0300.
Không hỗ trợ: ảnh scan không lớp chữ · file đặt mật khẩu.

`md` thêm 2026-08-28: sổ tay khách soạn sẵn dạng Markdown, ảnh là URL tuyệt đối.
⚠️ CHECK `kb_files_loai_check` của `0300` phải đã nhận `md` — kiểm trước khi ship,
nếu không upload trả 500 ở câu INSERT chứ không phải 400 ở route."""

MD_EMPTY_MESSAGE = "Tệp Markdown không có nội dung nào — kiểm lại tệp rồi tải lên lại."
"""Markdown rỗng KHÔNG dùng chung câu với PDF scan: câu kia nói về «lớp chữ», một khái
niệm của tệp quét, và người tải lên một tệp .md sẽ không hiểu mình phải sửa gì."""

KIND_ENRICH = "kb_enrich"
KIND_SYNC_PROJECT = "kb_sync_project"
KIND_THUMB = "kb_thumb"
KIND_DOI_CO = "kb_doi_co"
KIND_DOI_NHAN = "kb_doi_nhan"
KIND_CAPTION_PREVIEW = "kb_caption_preview"
KIND_CAPTION = "kb_caption"
"""Sinh mô tả cho ảnh ĐÃ có hàng `media` mà chưa ai mô tả — nhánh cổng nạp API.

Khác `KIND_CAPTION_PREVIEW`: cái kia chạy cho ảnh CHƯA có hàng, trả caption về qua
`message` để form đọc và người duyệt trước khi lưu. Đường API không có form nào, nên
cái này ghi thẳng vào `media.caption_auto` rồi tự nối sang việc nạp."""
KIND_PROVISION = "kb_provision"
RETRY_VIEC_KB = 2

# Caption đi qua mạng của bên thứ ba: 429 thoáng qua cần nhiều lượt hơn việc KB thường.
RETRY_CAPTION = 4

# Trần đồng thời ba chặng nặng, theo số đo prod 2026-08-25: thumb thuần chờ mạng (12
# luồng đạt 8,47 MB/s), caption ~2,3s/ảnh và 4 lượt song song không nghẽn, index ăn CPU
# của embed service dùng chung với stt/tts.
LANE_THUMB = 8
LANE_CAPTION = 6
LANE_INDEX = 4
# Bóc chữ cũng là việc CHỜ MẠNG (OCR từng trang qua DashScope), không phải CPU: đo trên
# dữ liệu thật 2026-08-25, mỗi việc 165-362 giây và trần mặc định 1 làm 18 tài liệu mất
# gần một giờ. Tổng lượt VLM đồng thời vẫn bị `VlmRateGate` chặn.
LANE_ENRICH = 4
MODE_DELTA = "delta"
MODE_FULL = "full"
MEDIA_VISUAL_REAL_ESTATE: tuple[str, ...] = (
    "tong_quan",
    "ngoai_that",
    "noi_that",
    "tien_ich",
    "mat_bang",
    "vi_tri",
    "tien_do",
)


class TemporaryError(RuntimeError):
    """Lỗi TẠM THỜI — job phải thử lại, không được âm thầm đi tiếp.

    Nuốt một lỗi mạng nghĩa là mất mô tả hoặc mất thumb vì một cơn nghẽn vài giây, mà
    thumb nay là nguồn cho cả caption lẫn vector visual.
    """


class TemporaryFetchError(TemporaryError):
    """Tải tệp hỏng hoặc tải hụt."""


CATEGORY_TONG_QUAN = "tong_quan"

# Nhãn tiếng Việt CÓ DẤU: chuỗi này đi vào text embed, mà model dense là
# multilingual-e5-large còn truy vấn của agent là tiếng Việt — `noi_that` embed kém hẳn.
NHAN_DANH_MUC: dict[str, str] = {
    "tong_quan": "tổng quan",
    "ngoai_that": "ngoại thất",
    "noi_that": "nội thất",
    "tien_ich": "tiện ích",
    "mat_bang": "mặt bằng",
    "vi_tri": "vị trí",
    "tien_do": "tiến độ",
}

DONG_DANH_MUC = "Danh mục:"
MAX_NHAN = 2


def split_caption(text: str) -> tuple[str, list[str]]:
    """Tách mô tả khỏi dòng nhãn ở CUỐI. Nhãn lạ ngoài sổ bị loại."""
    dong = (text or "").rstrip().split("\n")
    if len(dong) < 2 or not dong[-1].lstrip().startswith(DONG_DANH_MUC):
        return text, []
    hop_le = set(NHAN_DANH_MUC.values())
    nhan = [t.strip() for t in dong[-1].split(DONG_DANH_MUC, 1)[1].split(",")]
    return "\n".join(dong[:-1]).rstrip(), [t for t in nhan if t in hop_le]


def normalize_caption(text: str) -> str:
    """Dựng lại caption với tối đa `MAX_NHAN` nhãn hợp lệ; không nhãn nào thì bỏ cả dòng."""
    mo_ta, nhan = split_caption(text)
    if not nhan:
        return mo_ta
    return f"{mo_ta}\n{DONG_DANH_MUC} {', '.join(nhan[:MAX_NHAN])}"


TITLE_SEPARATOR = " — "
TITLE_PREFIXES: dict[str, str] = {"CSBH": "csbh", "Pháp lý": "phap_ly", "Hướng dẫn": "huong_dan"}
DEFAULT_DOC_TYPE = "khac"

_PREFIX_BY_TYPE = {ma: nhan for nhan, ma in TITLE_PREFIXES.items()}


def split_title(title: str) -> tuple[str, str]:
    """`"CSBH — Bảng giá"` → `("csbh", "Bảng giá")`.

    Tiền tố lạ thì trả NGUYÊN VĂN cả câu: `"Quy trình — bước 2"` có dấu ngăn cách
    nhưng không phải tiêu đề đã phân loại, cắt nó đi là đổi tên tài liệu của user.
    """
    head, sep, tail = title.partition(TITLE_SEPARATOR)
    if sep and head in TITLE_PREFIXES:
        return TITLE_PREFIXES[head], tail
    return DEFAULT_DOC_TYPE, title


def join_title(doc_type: str, title: str) -> str:
    """Mã lạ thì LỖI, không rơi về `khac`: nuốt im lặng ở đây làm tài liệu đổi
    phân loại mà không ai thấy, và lớp `Literal` ở biên HTTP là thứ duy nhất còn chắn."""
    if doc_type not in _PREFIX_BY_TYPE and doc_type != DEFAULT_DOC_TYPE:
        raise ValueError(f"mã loại tài liệu không hợp lệ: {doc_type!r}")
    prefix = _PREFIX_BY_TYPE.get(doc_type)
    return f"{prefix}{TITLE_SEPARATOR}{title}" if prefix else title


def doc_type_of(row: dict) -> str:
    """Chữ ký khớp `EntitySpec.doc_type_from`."""
    return split_title(str(row["title"]))[0]


_ENQUEUE_FACADE = frozenset(
    {"dat_viec_nap", "dat_viec_thumb", "dat_viec_doi_co", "dat_viec_doi_nhan", "dat_viec_provision"}
)


# Dọn kho tri thức của một workspace — đường XOÁ CỨNG workspace gọi qua đây.
# Cùng cơ chế lười của `_ENQUEUE_FACADE` (nạp muộn để `contracts` không kéo theo
# qdrant-client), nhưng tách frozenset riêng: hai nhóm này nằm ở hai module `ops`
# khác nhau, gộp lại là buộc `__getattr__` phải đoán.
_TEARDOWN_FACADE = frozenset({"xoa_kho_cua_workspace"})

_WEB_FACADE = frozenset({"enqueue_web_project", "enqueue_web_purge"})


def __getattr__(name: str):
    if name in _ENQUEUE_FACADE:
        from portal.modules.kb.ops import enqueue as _enq

        return getattr(_enq, name)
    if name in _TEARDOWN_FACADE:
        from portal.modules.kb.ops import collections as _col

        return getattr(_col, name)
    if name in _WEB_FACADE:
        from portal.modules.kb.web import enqueue as _web

        return getattr(_web, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
