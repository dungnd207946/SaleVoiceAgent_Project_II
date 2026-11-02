"""Cổng hợp đồng schema — bắt lệch giữa khai báo lĩnh vực và bảng thật.

M4 sở hữu cột, module này sở hữu `embed_sources`. M4 thêm cột mà quên thêm vào
`embed_sources` thì không có triệu chứng: field đó chỉ đơn giản không bao giờ lên index.

`test_cot_cua_embed_sources_ton_tai` từng xfail vì M4 chưa ALTER projects theo 02a. M4 đã
ship (`0400_kb_real_estate`) và test tự chuyển sang xanh, đúng như dự kiến — marker đã gỡ.
Nó đỏ trở lại nghĩa là M4 vừa đổi/xoá một cột mà `embed_sources` còn trỏ tới.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE

from .conftest import TENANT

_CAU_COT = """
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'tenant_data' AND table_name = $1
"""


async def _cot(pool, table: str) -> set[str]:
    async with tenant_conn(pool, TENANT) as conn:
        rows = await conn.fetch(_CAU_COT, table)
    return {r["column_name"] for r in rows}


async def test_bang_cua_module_nay_ton_tai_dung_hinh_dang(pool, seed_kb):
    """Hai bảng module kb sở hữu: documents (0500) và kb_index_state (0501)."""
    assert {"id", "tenant_id", "project_code", "title", "body", "file_url", "status"} <= await _cot(pool, "documents")
    assert {
        "tenant_id",
        "entity",
        "record_id",
        "doc_type",
        "target",
        "state",
        "content_hash",
        "points",
        "error",
        "attempts",
        "indexed_at",
    } <= await _cot(pool, "kb_index_state")


async def test_khoa_unique_cua_kb_index_state_co_doc_type(pool, seed_kb):
    """Khoá thiếu `doc_type` thì hai dòng của `projects` ghi đè nhau."""
    async with tenant_conn(pool, TENANT) as conn:
        cols = await conn.fetch(
            """
            SELECT a.attname
              FROM pg_constraint c
              JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.conname = 'kb_index_state_record_key'
            """
        )
    assert {r["attname"] for r in cols} == {"tenant_id", "entity", "record_id", "doc_type"}


async def test_cot_cua_embed_sources_ton_tai(pool, seed_kb):
    """Mọi field trong `embed_sources` phải là cột thật của bảng tương ứng."""
    thieu: list[str] = []
    for spec in REAL_ESTATE.embed_sources:
        co = await _cot(pool, spec.table)
        thieu += [f"{spec.table}.{f}" for f in spec.fields if f not in co]
    assert not thieu, f"embed_sources trỏ cột không tồn tại: {thieu}"


async def test_anchor_col_khop_giua_khai_bao_va_bang_thuc(pool, seed_kb):
    """Cột anchor khai trong vertical PHẢI là cột thật của `projects`.

    Trước M4 test này nới lỏng bằng `or` vì 0004 gọi cột là `code` còn 02a gọi
    `project_code`. `0400_kb_real_estate` đã chốt `project_code`, nên nới lỏng nữa là
    giữ một cổng không bao giờ đỏ được: sai tên cột ở đây thì `source/query.py` sinh
    SQL trỏ cột không tồn tại và MỌI job ingest chết — đúng thứ test này phải bắt.
    """
    cot_projects = await _cot(pool, "projects")
    assert REAL_ESTATE.anchor_code_col in cot_projects, (
        f"vertical khai anchor_code_col={REAL_ESTATE.anchor_code_col!r} "
        f"nhưng projects không có cột đó (có: {sorted(cot_projects)})"
    )
    if REAL_ESTATE.anchor_code_col not in cot_projects:
        pytest.skip(f"projects.{REAL_ESTATE.anchor_code_col} chưa có — M4 sẽ rename `code` theo 02a")
