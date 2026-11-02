"""Sinh SQL từ EntitySpec — vertical-agnostic. Hàm thuần, test bằng cách so chuỗi.

Sinh chứ không viết tay: 4 nguồn embed là 4 câu gần giống nhau, mỗi bản copy là một cơ
hội quên `_CACH_LY`.

KHÔNG CÒN LỌC `status = 'published'` (2026-08-14). Hàng nháp CŨNG được nạp; trạng thái HIỆU
LỰC đi vào payload point và mệnh đề lọc của agent (`status == 'published'`) mới là chỗ ẩn nó.
Nhờ vậy công bố một dự án chỉ cần cập nhật payload chứ không phải nhúng lại cả cây — xem
docs/contracts/payload-qdrant.md §4. Đó cũng là lý do ba hàm `list_*` ĐÃ ĐỔI TÊN: chúng từng
tên `list_published_*` và cái tên đó nay nói sai.

⚠️ MỌI câu sinh ở đây PHẢI mang `_CACH_LY`. `0909_bo_rls_toan_bo` đã dỡ RLS khỏi
`tenant_data`, nên không còn lớp nào ở DB lọc tenant hộ. Ở file này thiếu vị từ đó
đặc biệt nguy hiểm vì cả 5 câu đều định vị bằng `id` (hoặc `anchor_col`) — khoá chỉ
unique TRONG một tenant — và kết quả của chúng đi thẳng vào Qdrant: một record của
tenant khác lọt vào đây là nó được EMBED rồi ghi vào collection của tenant này, tức
rò rỉ sang cả kho vector chứ không chỉ một response sai.

Vị từ đặt trên bảng CON (`c.`/`m.`) là đủ cho câu có JOIN: `ON (a.tenant_id, …) =
(c.tenant_id, …)` đã buộc anchor cùng tenant với con.
"""

import re

from portal.modules.kb import settings
from portal.modules.kb.contracts import ChildBlockSpec, EntitySpec, VerticalSpec

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

_VE_CHO_DUYET = {"documents": " AND NOT coalesce(c.body_cho_duyet, false)"}

_CACH_LY = "tenant_id = portal.current_tenant()"

_COT_SUY: dict[str, dict[str, str]] = {
    "documents": {
        # NỐI, không coalesce: `body` của bản ghi cổng nạp thường là siêu dữ liệu
        # («Phạm vi… Hiệu lực…») còn nội dung thật nằm ở `body_auto` do bóc từ tệp.
        # Coalesce làm siêu dữ liệu thắng và agent chỉ thấy 43 ký tự.
        "body": ("concat_ws(E'\\n\\n', nullif({p}body, ''), nullif({p}body_auto, '')) AS body")
    },
}


def _cot_doc(table: str, col: str, tien_to: str = "") -> str:
    mau = _COT_SUY.get(table, {}).get(col)
    return mau.format(p=tien_to) if mau else f"{tien_to}{col}"


def _safe_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"tên định danh không hợp lệ: {name!r}")
    return name


def read_record_sql(vertical: VerticalSpec, spec: EntitySpec) -> str:
    """Đọc một record để index, $1 = id. Bảng con JOIN anchor bằng FK tổ hợp."""
    schema = settings.SCHEMA
    table = _safe_ident(spec.table)
    anchor_col = _safe_ident(spec.anchor_col)
    field_cols = [_safe_ident(f) for f in (*spec.fields, *spec.extra_cols)]

    if spec.is_anchor:
        doc_cols = [_cot_doc(table, f) for f in field_cols]
        selected = ", ".join(["id", anchor_col, "name", "status", "status AS anchor_status", "updated_at", *doc_cols])
        return f"SELECT {selected} FROM {schema}.{table}\n WHERE {_CACH_LY} AND id = $1"

    anchor_table = _safe_ident(vertical.anchor_table)
    anchor_key = _safe_ident(vertical.anchor_code_col)
    selected = ", ".join(
        [
            "c.id",
            f"c.{anchor_col}",
            *[_cot_doc(table, f, "c.") for f in field_cols],
            "a.name AS anchor_name",
            "c.status",
            "a.status AS anchor_status",
            "c.updated_at",
        ]
    )
    return (
        f"SELECT {selected}\n"
        f"  FROM {schema}.{table} c\n"
        f"  JOIN {schema}.{anchor_table} a\n"
        f"       ON (a.tenant_id, a.{anchor_key}) = (c.tenant_id, c.{anchor_col})\n"
        f" WHERE c.{_CACH_LY} AND c.id = $1{_VE_CHO_DUYET.get(spec.table, '')}"
    )


def read_child_rows_sql(block: ChildBlockSpec) -> str:
    """Hàng con của MỘT anchor, $1 = mã anchor. Không lọc `status` (spec 2026-08-19 §D4)."""
    table = _safe_ident(block.table)
    anchor_col = _safe_ident(block.anchor_col)
    names = [block.name_col, *block.fields, *(c for c in (block.key_col, block.parent_col) if c)]
    cols = ", ".join(_safe_ident(c) for c in dict.fromkeys(names))
    return f"SELECT {cols} FROM {settings.SCHEMA}.{table}\n WHERE {_CACH_LY} AND {anchor_col} = $1 ORDER BY id"


def read_media_sql(vertical: VerticalSpec) -> str:
    """Đọc một hàng media, $1 = id. Media không nằm trong embed_sources nên có câu riêng."""
    schema = settings.SCHEMA
    anchor_table = _safe_ident(vertical.anchor_table)
    anchor_key = _safe_ident(vertical.anchor_code_col)
    media_col = _safe_ident(vertical.media_anchor_col)
    return (
        f"SELECT m.id, m.{media_col}, m.content_type, m.category, m.caption, m.caption_auto,\n"
        "       m.media_url, m.thumb_url, m.content_hash, m.file_name, a.name AS anchor_name,\n"
        "       m.status, a.status AS anchor_status, m.updated_at\n"
        f"  FROM {schema}.media m\n"
        f"  JOIN {schema}.{anchor_table} a\n"
        f"       ON (a.tenant_id, a.{anchor_key}) = (m.tenant_id, m.{media_col})\n"
        f" WHERE m.{_CACH_LY} AND m.id = $1"
    )


def list_ban_ghi_theo_anchor_sql(vertical: VerticalSpec, spec: EntitySpec) -> str:
    """Con published của MỘT anchor — cascade `ops/sync.py` dùng.

    Vị từ mã anchor để chỉ xếp job cho đúng dự án được yêu cầu, không phải mọi hàng
    published của cả tenant.
    """
    schema = settings.SCHEMA
    table = _safe_ident(spec.table)
    anchor_col = _safe_ident(vertical.anchor_code_col if spec.is_anchor else spec.anchor_col)
    return f"SELECT id FROM {schema}.{table}\n WHERE {_CACH_LY} AND {anchor_col} = $1 ORDER BY id"


def list_media_theo_anchor_sql(vertical: VerticalSpec) -> str:
    """Media published của MỘT anchor — nửa còn lại của cascade theo dự án."""
    schema = settings.SCHEMA
    anchor_col = _safe_ident(vertical.media_anchor_col)
    return f"SELECT id FROM {schema}.media\n WHERE {_CACH_LY} AND {anchor_col} = $1 ORDER BY id"
