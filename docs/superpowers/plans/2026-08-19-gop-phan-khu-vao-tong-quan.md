# Gộp phân khu vào `tong_quan` + dọn payload Qdrant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bỏ `doc_type = "phan_khu"`; phân khu trở thành một point riêng bên trong doc `tong_quan` của dự án cha, và payload Qdrant `<tenant>_documents` bỏ 3 khoá thừa.

**Architecture:** `EntitySpec` mọc thêm `child_block: ChildBlockSpec | None`. Khi spec anchor khai nó, `reader.read_record()` đọc thêm hàng con và `resolve.build_text()` nối một khối `## <section>` › `### <subsection>` + bullet vào cuối text. Khối nằm ở **độ sâu đường dẫn 2 cấp** nên `chunker` luôn tách nó thành point riêng, độc lập với `min_chars`. Việc nạp của `zones` được chuyển hướng sang dự án cha tại **một** chỗ duy nhất (`kb/ops/enqueue.py::dat_viec_nap`) — chỗ mà cả đường UI lẫn đường API ingest đều đi qua.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg · Qdrant · pytest · uv · ruff

**Spec:** [docs/superpowers/specs/2026-08-19-gop-phan-khu-vao-tong-quan-design.md](../specs/2026-08-19-gop-phan-khu-vao-tong-quan-design.md)

## Global Constraints

- **Định danh tiếng Anh.** Tên hàm/biến/hằng/tham số/file mới: tiếng Anh. Tiếng Việt chỉ ở comment, docstring, tên hàm test. Tên cũ trong repo giữ nguyên, không đổi hàng loạt.
- **Comment ít.** ~7% dòng comment so với dòng code. Docstring module 1 dòng (tối đa 3 nếu có cảnh báo ngăn bug thật), docstring hàm 1–2 dòng. Một dòng `#` cho một quyết định. Lý do dài → `docs/superpowers/specs/`.
- **Mọi câu SQL chạm `tenant_data` phải mang `_CACH_LY`** (`tenant_id = portal.current_tenant()`) và chạy trong `tenant_conn()`.
- **Luật 3 — biên module.** `portal.modules.<a>` chỉ import `portal.core.*` và `portal.modules.<b>.contracts`. Cưỡng chế bằng `tests/test_module_boundaries.py` (đọc AST).
- **`make lint` là HAI lệnh:** `ruff check` **và** `ruff format --check`. Chạy cả hai.
- Chạy test bằng `uv run pytest`. Không tự chạy `git commit` — plan in ra lệnh, người dùng tự chạy.
- Không sửa `CLAUDE.md` (nhiều người cùng sửa, dễ conflict) — báo lại nội dung cần thêm ở Task 8.

---

### Task 1: Từ điển nhãn loại hình ở mặt tiền `realestate`

**Files:**
- Modify: `src/portal/modules/realestate/contracts.py`
- Test: `tests/modules/realestate/test_project_type_labels.py` (create)

**Interfaces:**
- Consumes: —
- Produces: `portal.modules.realestate.contracts.PROJECT_TYPE_LABELS: dict[str, str]` — 6 cặp `mã → nhãn tiếng Việt` cho `zones.category` / `projects.category`.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/realestate/test_project_type_labels.py`:

```python
"""Cổng chống lệch giữa từ điển nhãn và enum thật."""

from typing import get_args

from portal.modules.realestate import router
from portal.modules.realestate.contracts import PROJECT_TYPE_LABELS


def test_nhan_phu_dung_tap_gia_tri_cua_enum():
    """Thêm giá trị vào `_LoaiHinhDuAn` mà quên nhãn ⇒ mã thô lọt vào vector nhúng."""
    assert set(PROJECT_TYPE_LABELS) == set(get_args(router._LoaiHinhDuAn))


def test_moi_nhan_deu_co_chu_va_khac_ma():
    for ma, nhan in PROJECT_TYPE_LABELS.items():
        assert nhan.strip()
        assert nhan != ma
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/realestate/test_project_type_labels.py -v`
Expected: FAIL — `ImportError: cannot import name 'PROJECT_TYPE_LABELS'`

- [ ] **Step 3: Write minimal implementation**

Trong `src/portal/modules/realestate/contracts.py`, thêm ngay sau khối `__all__` (và thêm chuỗi `"PROJECT_TYPE_LABELS"` vào `__all__`, giữ thứ tự bảng chữ cái của list đó):

```python
# `zones.category` / `projects.category` — bản chép thứ hai của FE `enums.ts::LOAI_HINH`.
PROJECT_TYPE_LABELS: dict[str, str] = {
    "chung_cu": "Chung cư",
    "biet_thu": "Biệt thự",
    "lien_ke": "Liền kề",
    "shophouse": "Shophouse",
    "dat_nen": "Đất nền",
    "van_phong": "Văn phòng",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/modules/realestate/test_project_type_labels.py -v`
Expected: PASS 2 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/portal/modules/realestate/contracts.py tests/modules/realestate/test_project_type_labels.py && uv run ruff format --check src/portal/modules/realestate/contracts.py tests/modules/realestate/test_project_type_labels.py`
Expected: `All checks passed!` và `2 files already formatted`

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/realestate/contracts.py tests/modules/realestate/test_project_type_labels.py
git commit -m "feat(re): PROJECT_TYPE_LABELS ở mặt tiền, có cổng chống lệch enum"
```

---

### Task 2: `ChildBlockSpec` + `build_text` dựng khối con

**Files:**
- Modify: `src/portal/modules/kb/contracts.py`
- Modify: `src/portal/modules/kb/directive/resolve.py`
- Test: `tests/modules/kb/test_child_block.py` (create)

**Interfaces:**
- Consumes: —
- Produces:
  - `portal.modules.kb.contracts.ChildBlockSpec(table, name_col, section, subsection, fields, field_labels, value_labels={}, anchor_col="project_code")` — frozen dataclass, slots.
  - `portal.modules.kb.contracts.EntitySpec.child_block: ChildBlockSpec | None = None`
  - `portal.modules.kb.directive.resolve.child_block_text(rows: list[dict], block: ChildBlockSpec) -> str` — trả `""` khi không có hàng nào dùng được.
  - `build_text(row, spec)` giữ nguyên chữ ký; đọc hàng con từ `row["children"]`.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/kb/test_child_block.py`:

```python
"""Khối con trong doc anchor — hàm thuần, không DB."""

from portal.modules.kb.contracts import ChildBlockSpec, ChunkSpec, EntitySpec
from portal.modules.kb.directive.resolve import build_text, child_block_text
from portal.modules.kb.index import chunker

BLOCK = ChildBlockSpec(
    table="zones",
    name_col="name",
    section="Cơ cấu sản phẩm",
    subsection="Phân khu",
    fields=("category", "product_scale", "overview"),
    field_labels={"category": "Loại hình", "product_scale": "Quy mô"},
    value_labels={"category": {"biet_thu": "Biệt thự", "lien_ke": "Liền kề"}},
)

ANCHOR = EntitySpec(
    table="projects",
    doc_type="tong_quan",
    is_anchor=True,
    fields=("region", "investor"),
    field_labels={"region": "Khu vực", "investor": "Chủ đầu tư"},
    child_block=BLOCK,
)

# Sáu phân khu THẬT của aina_2/CE9F4363 — chỉ có tên, trùng ba cặp.
ZONES_THAT = [
    {"name": n, "category": None, "product_scale": "", "overview": ""}
    for n in [
        "Vịnh Bình Minh 2",
        "Vịnh Bình Minh 1",
        "Vịnh Bình Minh 2",
        "Thiên Đường Nhiệt Đới 1",
        "Vịnh Bình Minh 1",
        "Thiên Đường Nhiệt Đới 1",
    ]
]


def test_khong_co_hang_con_thi_khong_sinh_section_rong():
    assert child_block_text([], BLOCK) == ""


def test_phan_khu_chi_co_ten_van_vao_text():
    """Ca SẢN XUẤT. Nếu tên đi vào tiêu đề `###` thay vì nội dung, chunker bỏ hẳn nó."""
    ra = child_block_text([{"name": "A", "category": None, "product_scale": "", "overview": ""}], BLOCK)
    assert ra == "## Cơ cấu sản phẩm\n### Phân khu\n- **A**"


def test_gop_phan_khu_trung():
    ra = child_block_text(ZONES_THAT, BLOCK)
    assert ra.count("- **") == 3
    assert ra.count("Vịnh Bình Minh 2") == 1


def test_trung_ten_khac_field_thi_giu_ca_hai():
    rows = [
        {"name": "A", "category": "biet_thu", "product_scale": "", "overview": ""},
        {"name": "A", "category": "lien_ke", "product_scale": "", "overview": ""},
    ]
    assert child_block_text(rows, BLOCK).count("- **A**") == 2


def test_category_ra_nhan_tieng_viet_khong_phai_ma_tho():
    rows = [{"name": "A", "category": "biet_thu", "product_scale": "", "overview": ""}]
    ra = child_block_text(rows, BLOCK)
    assert "Loại hình: Biệt thự" in ra
    assert "biet_thu" not in ra


def test_field_khong_co_nhan_thi_xuong_dong_thut():
    rows = [{"name": "A", "category": None, "product_scale": "", "overview": "Ven sông."}]
    assert child_block_text(rows, BLOCK) == "## Cơ cấu sản phẩm\n### Phân khu\n- **A**\n  Ven sông."


def test_build_text_noi_khoi_con_vao_cuoi():
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": ZONES_THAT}
    text = build_text(row, ANCHOR)
    assert text.index("## Khu vực") < text.index("## Cơ cấu sản phẩm")
    assert text.endswith("- **Thiên Đường Nhiệt Đới 1**")


def test_build_text_khong_co_children_thi_nhu_cu():
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes"}
    assert build_text(row, ANCHOR) == "## Khu vực\nQuảng Ninh\n\n## Chủ đầu tư\nVinhomes"


def test_khoi_con_luon_thanh_point_rieng():
    """Ranh giới đến từ ĐỘ SÂU đường dẫn, không từ cỡ chunk — nên đúng ở mọi `min_chars`."""
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": ZONES_THAT}
    text = build_text(row, ANCHOR)
    for min_chars in (0, 300, 600):
        chunks = chunker.split(text, ChunkSpec(1000, 100, min_chars))
        rieng = [c for c in chunks if c.section_path[:1] == ("Cơ cấu sản phẩm",)]
        chung = [c for c in chunks if c.section_path[:1] != ("Cơ cấu sản phẩm",)]
        assert len(rieng) == 1, min_chars
        assert len(chung) == 1, min_chars
        assert not any("Phân khu" in c.text for c in chung), min_chars
        assert rieng[0].section_path == ("Cơ cấu sản phẩm", "Phân khu")


def test_nhieu_phan_khu_van_khong_lan_sang_point_tong_quan():
    rows = [
        {
            "name": f"Phân khu số {i}",
            "category": "biet_thu",
            "product_scale": f"{i * 10} căn",
            "overview": f"Phân khu thứ {i} nằm ở phía đông dự án, tiếp giáp trục cảnh quan chính.",
        }
        for i in range(1, 41)
    ]
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": rows}
    chunks = chunker.split(build_text(row, ANCHOR), ChunkSpec(1000, 100, 300))
    chung = [c for c in chunks if c.section_path[:1] != ("Cơ cấu sản phẩm",)]
    assert len(chung) == 1
    assert not any("Phân khu" in c.text for c in chung)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_child_block.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChildBlockSpec' from 'portal.modules.kb.contracts'`

- [ ] **Step 3: Add `ChildBlockSpec` to `kb/contracts.py`**

Thêm ngay **trước** `class EntitySpec`:

```python
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
```

Trong `class EntitySpec`, thêm dòng cuối:

```python
    child_block: ChildBlockSpec | None = None
```

- [ ] **Step 4: Implement `child_block_text` + nối vào `build_text`**

Trong `src/portal/modules/kb/directive/resolve.py`, đổi import đầu file thành:

```python
from portal.modules.kb.contracts import ChildBlockSpec, ChunkSpec, EntitySpec, TextDirective, VerticalSpec
```

Thêm hàm mới **trước** `build_text`:

```python
def child_block_text(rows: list[dict], block: ChildBlockSpec) -> str:
    """Bảng con → `## <section>` › `### <subsection>` + bullet. Rỗng ⇒ `""`.

    Tên hàng là NỘI DUNG chứ không phải tiêu đề: `chunker._tach_khoi()` bỏ hẳn một
    `###` không có thân, mà phân khu thật thường chỉ có mỗi tên.
    """
    items: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get(block.name_col) or "").strip()
        if not name:
            continue
        facts: list[str] = []
        for col in block.fields:
            if col not in block.field_labels:
                continue
            value = row.get(col)
            if value is None or not str(value).strip():
                continue
            shown = block.value_labels.get(col, {}).get(str(value), str(value))
            facts.append(f"{block.field_labels[col]}: {shown}")
        head = f"- **{name}**" + (f" — {' · '.join(facts)}" if facts else "")
        tail = [
            f"  {str(row[col]).strip()}"
            for col in block.fields
            if col not in block.field_labels and str(row.get(col) or "").strip()
        ]
        item = "\n".join([head, *tail])
        if item in seen:
            continue
        seen.add(item)
        items.append(item)
    if not items:
        return ""
    return "\n".join([f"## {block.section}", f"### {block.subsection}", *items])
```

Trong `build_text`, đổi dòng `return "\n\n".join(phan)` thành:

```python
    if spec.child_block is not None:
        khoi = child_block_text(list(row.get("children") or []), spec.child_block)
        if khoi:
            phan.append(khoi)
    return "\n\n".join(phan)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/test_child_block.py -v`
Expected: PASS 10 passed

- [ ] **Step 6: Run the whole kb suite for regressions**

Run: `uv run pytest tests/modules/kb -q`
Expected: PASS, không bài nào mới đỏ

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/portal/modules/kb tests/modules/kb && uv run ruff format --check src/portal/modules/kb tests/modules/kb`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/kb/contracts.py src/portal/modules/kb/directive/resolve.py tests/modules/kb/test_child_block.py
git commit -m "feat(kb): ChildBlockSpec — bảng con thành một khối trong doc anchor"
```

---

### Task 3: SQL + reader đọc hàng con

**Files:**
- Modify: `src/portal/modules/kb/source/query.py`
- Modify: `src/portal/modules/kb/source/reader.py`
- Test: `tests/modules/kb/test_source_query.py` (modify — thêm bài mới vào cuối)

**Interfaces:**
- Consumes: `ChildBlockSpec` (Task 2)
- Produces:
  - `portal.modules.kb.source.query.read_child_rows_sql(block: ChildBlockSpec) -> str` — `$1` = mã anchor.
  - `portal.modules.kb.source.reader.read_child_rows(conn, *, block, anchor_code) -> list[dict]`
  - `reader.read_record()` gắn `row["children"]` khi `spec.child_block is not None`.

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/modules/kb/test_source_query.py`:

```python
def test_sql_hang_con_mang_vi_tu_cach_ly_va_thu_tu_on_dinh():
    from portal.modules.kb.contracts import ChildBlockSpec

    block = ChildBlockSpec(
        table="zones",
        name_col="name",
        section="Cơ cấu sản phẩm",
        subsection="Phân khu",
        fields=("category", "overview"),
        field_labels={"category": "Loại hình"},
    )
    sql = query.read_child_rows_sql(block)
    assert "tenant_id = portal.current_tenant()" in sql
    assert "tenant_data.zones" in sql
    assert "project_code = $1" in sql
    assert "ORDER BY id" in sql
    # Cột đọc đúng tập khai báo, không thừa không thiếu.
    assert "SELECT name, category, overview" in sql
    # KHÔNG lọc status — spec §D4.
    assert "status" not in sql


def test_sql_hang_con_tu_choi_ten_bang_khong_hop_le():
    from portal.modules.kb.contracts import ChildBlockSpec

    block = ChildBlockSpec(
        table="zones; DROP TABLE x",
        name_col="name",
        section="s",
        subsection="ss",
        fields=(),
        field_labels={},
    )
    with pytest.raises(ValueError, match="không hợp lệ"):
        query.read_child_rows_sql(block)
```

Nếu `pytest` chưa được import trong file đó, thêm `import pytest` vào khối import đầu file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_source_query.py -k hang_con -v`
Expected: FAIL — `AttributeError: module 'portal.modules.kb.source.query' has no attribute 'read_child_rows_sql'`

- [ ] **Step 3: Implement `read_child_rows_sql`**

Trong `src/portal/modules/kb/source/query.py`, đổi import contracts thành:

```python
from portal.modules.kb.contracts import ChildBlockSpec, EntitySpec, VerticalSpec
```

Thêm hàm sau `read_record_sql`:

```python
def read_child_rows_sql(block: ChildBlockSpec) -> str:
    """Hàng con của MỘT anchor, $1 = mã anchor. Không lọc `status` (spec §D4)."""
    table = _safe_ident(block.table)
    anchor_col = _safe_ident(block.anchor_col)
    cols = ", ".join([_safe_ident(block.name_col), *(_safe_ident(f) for f in block.fields)])
    return (
        f"SELECT {cols} FROM {settings.SCHEMA}.{table}\n"
        f" WHERE {_CACH_LY} AND {anchor_col} = $1 ORDER BY id"
    )
```

- [ ] **Step 4: Implement reader**

Trong `src/portal/modules/kb/source/reader.py`, đổi import contracts thành:

```python
from portal.modules.kb.contracts import ChildBlockSpec, EntitySpec, VerticalSpec
```

Thêm hàm mới sau `read_record`:

```python
async def read_child_rows(
    conn: asyncpg.Connection, *, block: ChildBlockSpec, anchor_code: str
) -> list[dict]:
    rows = await conn.fetch(query.read_child_rows_sql(block), anchor_code)
    return [dict(r) for r in rows]
```

Trong `read_record`, chèn ngay **trước** `return row`:

```python
    if spec.child_block is not None:
        row["children"] = await read_child_rows(
            conn, block=spec.child_block, anchor_code=str(row[spec.anchor_col])
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/test_source_query.py -v`
Expected: PASS, gồm 2 bài mới

- [ ] **Step 6: Cổng cách ly**

Run: `uv run pytest tests/isolation -q`
Expected: số dòng đỏ **không tăng** so với lúc bắt đầu task. Nếu tăng, câu SQL mới thiếu `_CACH_LY` hoặc giấu schema sau một biến — sửa CODE, tuyệt đối không allowlist/xfail.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check src/portal/modules/kb tests/modules/kb && uv run ruff format --check src/portal/modules/kb tests/modules/kb
git add src/portal/modules/kb/source/query.py src/portal/modules/kb/source/reader.py tests/modules/kb/test_source_query.py
git commit -m "feat(kb): đọc hàng con của anchor cho ChildBlockSpec"
```

---

### Task 4: Chuyển hướng việc nạp `zones` → dự án cha

**Files:**
- Modify: `src/portal/modules/kb/ops/enqueue.py`
- Modify: `src/portal/modules/realestate/router.py:373-378` (`_enqueue_purge_zone`)
- Modify: `src/portal/modules/realestate/router.py:1258-1274` (route `xoa_phan_khu`)
- Modify: `src/portal/modules/ingest/chieu.py:205-241` (`_xep_purge`)
- Test: `tests/modules/kb/test_enqueue_redirect_zones.py` (create)

**Interfaces:**
- Consumes: —
- Produces: `dat_viec_nap(conn, *, tenant_id, actor, entity, record_id, project_code, vertical="real_estate")` — chữ ký **không đổi**; hành vi mới là `entity == "zones"` ra job `entity="projects"` của dự án cha.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/kb/test_enqueue_redirect_zones.py`:

```python
"""`zones` không còn là doc riêng ⇒ sửa phân khu = nạp lại dự án cha.

Chuyển hướng đặt ở `dat_viec_nap` — chỗ DUY NHẤT cả đường UI lẫn đường API ingest đi qua,
nên hai đường giống nhau theo cấu trúc chứ không nhờ chép đúng hai lần.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.ops.enqueue import dat_viec_nap


async def _payloads(conn, kind: str) -> list[dict]:
    import json

    rows = await conn.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = portal.current_tenant() AND kind = $1 ORDER BY id",
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


@pytest.mark.asyncio
async def test_zones_ra_job_cua_du_an_cha(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="zones",
            record_id=zone_id,
            project_code=project_code,
        )
        jobs = await _payloads(conn, "kb_index")
    assert len(jobs) == 1
    assert jobs[0]["entity"] == "projects"
    assert jobs[0]["record_id"] == project_id
    assert jobs[0]["project_code"] == project_code


@pytest.mark.asyncio
async def test_hai_phan_khu_cung_du_an_gop_thanh_mot_viec(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        for rid in (zone_id, zone_id + 1):
            await dat_viec_nap(
                conn,
                tenant_id=tenant_id,
                actor="test",
                entity="zones",
                record_id=rid,
                project_code=project_code,
            )
        jobs = await _payloads(conn, "kb_index")
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_khong_tim_thay_du_an_cha_thi_khong_xep_gi(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, _project_code, _project_id, zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        ra = await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="zones",
            record_id=zone_id,
            project_code="KHONG_TON_TAI",
        )
        jobs = await _payloads(conn, "kb_index")
    assert ra is None
    assert jobs == []


@pytest.mark.asyncio
async def test_entity_khac_khong_bi_doi(pool, tenant_co_du_an_va_phan_khu):
    tenant_id, project_code, _project_id, _zone_id = tenant_co_du_an_va_phan_khu
    async with tenant_conn(pool, tenant_id) as conn:
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="test",
            entity="documents",
            record_id=99,
            project_code=project_code,
        )
        jobs = await _payloads(conn, "kb_index")
    assert jobs[0]["entity"] == "documents"
    assert jobs[0]["record_id"] == 99
```

Thêm fixture vào `tests/modules/kb/conftest.py`:

```python
@pytest.fixture
async def tenant_co_du_an_va_phan_khu(pool):
    """Một tenant với 1 dự án + 2 phân khu. Trả `(tenant_id, project_code, project_id, zone_id)`."""
    import uuid

    from portal.core.db.session import tenant_conn

    tenant_id = f"cb_{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.tenants (id, name, vertical) VALUES ($1, $1, 'real_estate')",
            tenant_id,
        )
    async with tenant_conn(pool, tenant_id) as conn:
        project_id = await conn.fetchval(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Dự án 1', 'published') RETURNING id"
        )
        zone_id = await conn.fetchval(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Z1', 'Phân khu 1', 'published') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Z2', 'Phân khu 2', 'published')"
        )
    yield tenant_id, "P1", project_id, zone_id
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM tenant_data.zones WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", tenant_id)
```

Nếu `tests/modules/kb/conftest.py` chưa `import pytest`, thêm vào đầu file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_enqueue_redirect_zones.py -v`
Expected: FAIL ở `test_zones_ra_job_cua_du_an_cha` — `assert 'zones' == 'projects'`

- [ ] **Step 3: Implement chuyển hướng trong `dat_viec_nap`**

Trong `src/portal/modules/kb/ops/enqueue.py`, thêm hằng + hàm phụ ngay dưới `_CAU_DA_CHO`:

```python
# Bảng đã thôi làm doc riêng: việc nạp của nó chuyển sang anchor cha.
_REDIRECT_TO_ANCHOR = {"zones"}

_ANCHOR_ID_SQL = """SELECT id FROM tenant_data.projects
                     WHERE tenant_id = portal.current_tenant() AND project_code = $1"""
```

Ở đầu thân `dat_viec_nap`, **trước** câu dò gộp việc:

```python
    if entity in _REDIRECT_TO_ANCHOR:
        anchor_id = await conn.fetchval(_ANCHOR_ID_SQL, project_code)
        if anchor_id is None:
            log.warning("bỏ qua: %s#%s không có dự án %r", entity, record_id, project_code)
            return None
        entity, record_id = "projects", int(anchor_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/test_enqueue_redirect_zones.py -v`
Expected: PASS 4 passed

- [ ] **Step 5: Đổi đường purge phía UI**

Trong `src/portal/modules/realestate/router.py`, thay nguyên hàm `_enqueue_purge_zone`:

```python
async def _enqueue_purge_zone(
    conn: asyncpg.Connection, p: Principal, *, project_code: str, media_ids: list[int]
) -> None:
    """Phân khu không còn point riêng — xoá nó là NẠP LẠI dự án. Media neo vào nó vẫn phải
    purge từng cái: worker chỉ cascade theo `anchor_code`, không theo zone."""
    await _enqueue_index(conn, p, entity="zones", record_id=0, project_code=project_code)
    for mid in media_ids:
        await _enqueue_purge_record(conn, p, entity="media", record_id=mid)
```

`entity="zones"` + `record_id=0` là cố ý: `dat_viec_nap` (Step 3) tra id dự án từ
`project_code` rồi thay cả hai, nên `record_id` truyền vào không được đọc. Gọi thẳng
`entity="projects"` thì route phải tự tra id — một bản sao thứ hai của phép tra đó.

Đổi lời gọi trong route `xoa_phan_khu` (`src/portal/modules/realestate/router.py:1273`) cho
khớp chữ ký mới:

```python
        await _enqueue_purge_zone(conn, p, project_code=project_code, media_ids=media_ids)
```

Phần còn lại của route giữ nguyên — kể cả dòng đọc `media_ids` TRƯỚC khi xoá.

- [ ] **Step 6: Đổi đường purge phía ingest API**

Trong `src/portal/modules/ingest/chieu.py`, trong `_xep_purge`, thay khối:

```python
    if entity == "project":
        payload: dict = {"vertical": "real_estate", "anchor_code": project_code}
    else:
        payload = {"vertical": "real_estate", "entity": _BANG[entity], "record_id": record_id}
    await enqueue(conn, tenant_id=tenant_id, kind=KIND_DELETE_INDEX, actor="ingest", payload=payload)
```

bằng:

```python
    if entity == "zone":
        # Phân khu không còn point riêng — rời published là NẠP LẠI dự án cha.
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="ingest",
            entity="zones",
            record_id=record_id,
            project_code=project_code,
        )
    else:
        if entity == "project":
            payload: dict = {"vertical": "real_estate", "anchor_code": project_code}
        else:
            payload = {"vertical": "real_estate", "entity": _BANG[entity], "record_id": record_id}
        await enqueue(conn, tenant_id=tenant_id, kind=KIND_DELETE_INDEX, actor="ingest", payload=payload)
```

Vế cascade media của zone ngay bên dưới **giữ nguyên**. Nếu `dat_viec_nap` chưa được import trong file, thêm vào khối import: `from portal.modules.kb.ops.enqueue import dat_viec_nap`.

- [ ] **Step 7: Run affected suites**

Run: `uv run pytest tests/modules/kb tests/modules/realestate tests/modules/ingest -q`
Expected: PASS. Bài nào kỳ vọng job `kb_delete` cho `zones` sẽ đỏ — sửa **bài test** cho khớp hành vi mới (job `kb_index` của `projects`), không nới code.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/portal/modules/kb/ops/enqueue.py src/portal/modules/realestate/router.py src/portal/modules/ingest/chieu.py tests/modules/kb/
git commit -m "feat(kb): việc nạp của zones chuyển sang dự án cha, một chỗ cho cả UI và API"
```

---

### Task 5: Lật vertical — bỏ `phan_khu`, gắn `child_block`

**Files:**
- Modify: `src/portal/modules/kb/directive/verticals/real_estate.py`
- Modify: `src/portal/modules/kb/jobs.py:164-207` (`handle_index`)
- Modify: `tests/modules/kb/test_directive.py:12-24`
- Modify: `tests/modules/kb/test_doc_type_roi_nhau.py`
- Test: `tests/modules/kb/test_vertical_khong_con_phan_khu.py` (create)

**Interfaces:**
- Consumes: `ChildBlockSpec` (Task 2), `read_child_rows` (Task 3), `PROJECT_TYPE_LABELS` (Task 1)
- Produces: `REAL_ESTATE.embed_sources` còn 2 phần tử (`projects`, `documents`); `REAL_ESTATE.embed_sources[0].child_block` là `ChildBlockSpec` của `zones`.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/kb/test_vertical_khong_con_phan_khu.py`:

```python
"""`zones` thôi làm nguồn embed riêng — nó là khối con của doc dự án."""

import pytest

from portal.modules.kb.directive import resolve
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_chi_con_hai_nguon_embed():
    assert [s.table for s in REAL_ESTATE.embed_sources] == ["projects", "documents"]
    assert "phan_khu" not in {s.doc_type for s in REAL_ESTATE.embed_sources}


def test_zones_khong_con_tra_duoc_spec():
    with pytest.raises(ValueError, match="không phải nguồn embed"):
        resolve.source_for(REAL_ESTATE, "zones")


def test_projects_khai_khoi_con_zones():
    block = REAL_ESTATE.embed_sources[0].child_block
    assert block is not None
    assert block.table == "zones"
    assert block.section == "Cơ cấu sản phẩm"
    assert block.subsection == "Phân khu"


def test_nhan_loai_hinh_lay_tu_so_realestate_khong_chep_tay():
    from portal.modules.realestate.contracts import PROJECT_TYPE_LABELS

    block = REAL_ESTATE.embed_sources[0].child_block
    assert block.value_labels["category"] is PROJECT_TYPE_LABELS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_vertical_khong_con_phan_khu.py -v`
Expected: FAIL — `assert ['projects', 'zones', 'documents'] == ['projects', 'documents']`

- [ ] **Step 3: Sửa vertical**

Trong `src/portal/modules/kb/directive/verticals/real_estate.py`:

Đổi import thành:

```python
from portal.modules.kb.contracts import (
    MEDIA_VISUAL_REAL_ESTATE,
    ChildBlockSpec,
    EntitySpec,
    VerticalSpec,
    doc_type_of,
)
from portal.modules.realestate.contracts import PROJECT_TYPE_LABELS
```

Xoá nguyên khối `EntitySpec(table="zones", doc_type="phan_khu", …)`.

Trong `EntitySpec(table="projects", …)`, thêm ngay sau `field_labels={…}`:

```python
            child_block=ChildBlockSpec(
                table="zones",
                name_col="name",
                section="Cơ cấu sản phẩm",
                subsection="Phân khu",
                fields=("category", "product_scale", "overview"),
                field_labels={"category": "Loại hình", "product_scale": "Quy mô"},
                value_labels={"category": PROJECT_TYPE_LABELS},
            ),
```

Đổi docstring module (giữ 3 dòng, xoá dòng nói `projects` chỉ còn một spec nếu đã thừa):

```python
"""Khai báo real_estate — nguyên văn `rag_config["real_estate"]` (§15.1).

Thêm/bớt field embed, đổi nhãn, đổi caption profile → sửa ở đây. `units` không embed.
`zones` là khối con của doc dự án, không phải doc riêng — spec 2026-08-19.
"""
```

- [ ] **Step 4: Chặn job cũ của entity đã thôi làm nguồn embed**

Trong `src/portal/modules/kb/jobs.py::handle_index`, chèn ngay sau dòng `slug = workspace_slug(tenant_id)`:

```python
    if entity != "media" and entity not in {s.table for s in vertical.embed_sources}:
        return JobResult(count=0, message=f"{entity}#{record_id}: không còn là nguồn embed, bỏ qua")
```

Việc này để job `entity="zones"` còn nằm trong hàng đợi lúc deploy không nổ `ValueError`.

- [ ] **Step 5: Sửa hai bài test đã lỗi thời**

Trong `tests/modules/kb/test_directive.py`, thay nguyên hàm `test_ba_nguon_embed_va_projects_chi_xuat_hien_mot_lan` bằng:

```python
def test_hai_nguon_embed_va_projects_chi_xuat_hien_mot_lan():
    """`zones` thôi làm nguồn riêng (spec 2026-08-19); `thong_tin` đã gộp từ trước."""
    assert len(REAL_ESTATE.embed_sources) == 2
    assert [s.table for s in REAL_ESTATE.embed_sources].count("projects") == 1
    assert {s.doc_type for s in REAL_ESTATE.embed_sources} == {"tong_quan", "tai_lieu"}
    assert "units" not in {s.table for s in REAL_ESTATE.embed_sources}
```

Trong `tests/modules/kb/test_doc_type_roi_nhau.py`, bỏ `"phan_khu"` khỏi mọi tập giá trị kỳ vọng và khỏi mọi tham số hoá. Chạy `uv run pytest tests/modules/kb/test_doc_type_roi_nhau.py -v` để thấy chính xác chỗ nào cần sửa.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/modules/kb tests/modules/realestate tests/modules/ingest -q`
Expected: PASS. Bài nào còn kỳ vọng `phan_khu` thì sửa **bài test**.

- [ ] **Step 7: Kiểm biên module**

Run: `uv run pytest tests/test_module_boundaries.py -v`
Expected: PASS — `kb` import `realestate.contracts` là mặt tiền, hợp Luật 3.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/portal/modules/kb tests/modules/kb
git commit -m "feat(kb): bỏ doc_type phan_khu, zones thành khối con của doc dự án"
```

---

### Task 6: Dọn payload — bỏ `section`, `section_path`, `page`

**Files:**
- Modify: `src/portal/modules/kb/clients/rag.py:110-133`
- Modify: `src/portal/modules/kb/index/store.py` (`doi_ten_trong_text`)
- Test: `tests/modules/kb/test_payload_khoa.py` (create)

**Interfaces:**
- Consumes: —
- Produces: payload `<tenant>_documents` đúng 11 khoá.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/kb/test_payload_khoa.py`:

```python
"""Payload documents — 11 khoá. `section`/`section_path`/`page` đã bỏ (spec §D3).

Bằng chứng: quét 136 point thật trên 4 collection, 136/136 có `text` mở đầu đúng bằng
`"<project_name> — <section_path[-1]>"`. Ba khoá nói cùng một chuyện.
"""

KHOA_MONG_DOI = {
    "project_id",
    "project_name",
    "record_id",
    "doc_type",
    "text",
    "content_hash",
    "updated_at",
    "status",
    "file_public_url",
    "file_name",
    "thumb_url",
}


class _StoreGia:
    def __init__(self) -> None:
        self.points: list = []

    async def delete_by_record(self, name, *, record_id, doc_type=""):
        return 0

    async def upsert(self, name, points):
        self.points.extend(points)
        return len(points)


class _EmbedGia:
    async def dense(self, texts):
        return [[0.0] * 4 for _ in texts]

    async def sparse(self, texts):
        return [{"indices": [1], "values": [1.0]} for _ in texts]


async def _index(text: str):
    from portal.modules.kb.clients.rag import RagClient
    from portal.modules.kb.contracts import ChunkSpec, TextDirective

    store = _StoreGia()
    client = RagClient(embed=_EmbedGia(), store=store)
    await client.index(
        TextDirective(
            workspace_slug="ws",
            record_id=426,
            doc_type="tong_quan",
            anchor_code="P1",
            anchor_name="Dự án 1",
            section="bỏ đi",
            text=text,
            chunk=ChunkSpec(1000, 100, 300),
            status="published",
            anchor_status="published",
            entity="projects",
        )
    )
    return store.points


async def test_payload_dung_11_khoa():
    points = await _index("## Khu vực\nQuảng Ninh")
    assert set(points[0].payload) == KHOA_MONG_DOI


async def test_khong_con_ba_khoa_da_bo():
    points = await _index("## Khu vực\nQuảng Ninh")
    for khoa in ("section", "section_path", "page"):
        assert khoa not in points[0].payload


async def test_nhan_muc_van_con_trong_text():
    """Bỏ khoá được vì `_tien_to()` đã gắn nhãn vào đầu MỌI chunk."""
    points = await _index("## Cơ cấu sản phẩm\n### Phân khu\n- **A**")
    assert points[0].payload["text"].startswith("Dự án 1 — Phân khu\n\n")
```

Nếu bộ test dùng `anyio`/`pytest-asyncio` với marker tường minh, thêm `@pytest.mark.asyncio` lên ba hàm và `import pytest`; xem `tests/modules/kb/test_content_hash_of.py` để theo đúng nếp file cùng thư mục.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_payload_khoa.py -v`
Expected: FAIL — payload còn `section`, `section_path`, `page`

- [ ] **Step 3: Bỏ 3 khoá khỏi `rag.py`**

Trong `src/portal/modules/kb/clients/rag.py`, xoá 3 dòng khỏi dict `payload`:

```python
                    "section_path": list(chunks[i].section_path),
                    "section": chunks[i].section_path[-1] if chunks[i].section_path else directive.section,
                    "page": 0,
```

Không đụng gì khác — `_tien_to()`, `_hash_of()`, `_chunks()` giữ nguyên.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/modules/kb/test_payload_khoa.py -v`
Expected: PASS 3 passed

- [ ] **Step 5: Write the failing test cho `doi_ten_trong_text`**

Thêm vào cuối `tests/modules/kb/test_store_qdrant.py`:

```python
def test_doi_ten_doc_tien_to_tu_text_khong_can_section_path():
    """Payload không còn `section_path` ⇒ tiền tố cũ phải suy từ chính dòng đầu của `text`."""
    from portal.modules.kb.index.store import tach_tien_to

    assert tach_tien_to("Dự án 1 — Phân khu\n\nnội dung", "Dự án 1") == ("Dự án 1 — Phân khu", "nội dung")
    assert tach_tien_to("Dự án 1\n\nnội dung", "Dự án 1") == ("Dự án 1", "nội dung")
    # Tên khác ⇒ không đụng.
    assert tach_tien_to("Dự án 2 — Phân khu\n\nnội dung", "Dự án 1") is None
    # Tên là TIỀN TỐ của tên khác, không có dấu phân cách ⇒ không đụng.
    assert tach_tien_to("Dự án 12 — Phân khu\n\nnội dung", "Dự án 1") is None
    # Không có dòng trống ngăn cách ⇒ không đụng.
    assert tach_tien_to("Dự án 1 — Phân khu", "Dự án 1") is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/test_store_qdrant.py -k tach_tien_to -v`
Expected: FAIL — `ImportError: cannot import name 'tach_tien_to'`

- [ ] **Step 7: Implement `tach_tien_to` + dùng nó trong `doi_ten_trong_text`**

Trong `src/portal/modules/kb/index/store.py`, thêm hàm thuần ở mức module (trước `class QdrantStore`):

```python
def tach_tien_to(text: str, old_name: str) -> tuple[str, str] | None:
    """`("<old_name> — <mục>", "phần còn lại")`, hoặc `None` nếu dòng đầu không phải tiền tố."""
    head, sep, body = text.partition("\n\n")
    if not sep or not (head == old_name or head.startswith(f"{old_name} — ")):
        return None
    return head, body
```

Thay thân vòng lặp của `doi_ten_trong_text` — bỏ hai dòng đọc `section_path` và dựng `cu`/`moi`:

```python
        for diem, pl in await self._scroll_payload(name, anchor_code):
            tach = tach_tien_to(str(pl.get("text") or ""), ten_cu)
            if tach is None:
                truot += 1
                continue
            dong_dau, than = tach
            moi = f"{ten_moi}{dong_dau[len(ten_cu) :]}"
            await self._c.set_payload(name, payload={"text": f"{moi}\n\n{than}"}, points=[diem], wait=True)
            n += 1
```

Cập nhật docstring hàm còn 2 dòng: nó không còn dựng lại tiền tố từ `section_path` mà so thẳng vào chuỗi sắp ghi đè.

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/modules/kb -q`
Expected: PASS. Bài nào ghim `section`/`section_path`/`page` trong payload thì sửa **bài test**.

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/portal/modules/kb tests/modules/kb
git commit -m "feat(kb): payload documents bỏ section, section_path, page"
```

---

### Task 7: CLI dọn point `phan_khu` cũ

**Files:**
- Create: `src/portal/cli/drop_zone_points.py`
- Test: `tests/unit/test_drop_zone_points.py` (create)

**Interfaces:**
- Consumes: —
- Produces: `python -m portal.cli.drop_zone_points [--ghi]`; hàm thuần `plan_lines(rows: list[tuple[str, int, int]]) -> list[str]` để test không cần Qdrant.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_drop_zone_points.py`:

```python
"""Phần thuần của lệnh dọn — không Qdrant, không DB."""

from portal.cli.drop_zone_points import plan_lines


def test_bao_cao_tung_tenant_va_tong():
    dong = plan_lines([("aina_2", 21, 12), ("hanoi", 0, 6)])
    assert dong[0] == "aina_2: 21 point phan_khu · 12 dự án xếp lại"
    assert dong[1] == "hanoi: 0 point phan_khu · 6 dự án xếp lại"
    assert dong[-1] == "TỔNG: 21 point phan_khu · 18 dự án xếp lại · 2 tenant"


def test_khong_co_tenant_nao():
    assert plan_lines([]) == ["TỔNG: 0 point phan_khu · 0 dự án xếp lại · 0 tenant"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_drop_zone_points.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.cli.drop_zone_points'`

- [ ] **Step 3: Write the CLI**

Create `src/portal/cli/drop_zone_points.py`:

```python
"""Dọn point `phan_khu` cũ sau khi zones thôi làm doc riêng — chạy MỘT LẦN.

    python -m portal.cli.drop_zone_points          # thử khô
    python -m portal.cli.drop_zone_points --ghi    # ghi thật

Deploy code TRƯỚC, chạy lệnh này SAU: bản cũ đang chạy vẫn ghi point `phan_khu`.
"""

import asyncio
import sys

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.modules.kb.ops.enqueue import dat_viec_nap

_DOC_TYPE_CU = "phan_khu"


def plan_lines(rows: list[tuple[str, int, int]]) -> list[str]:
    dong = [f"{t}: {p} point phan_khu · {d} dự án xếp lại" for t, p, d in rows]
    dong.append(
        f"TỔNG: {sum(p for _, p, _ in rows)} point phan_khu · "
        f"{sum(d for _, _, d in rows)} dự án xếp lại · {len(rows)} tenant"
    )
    return dong


async def main_async(ghi: bool) -> int:
    from portal.modules.kb.jobs import open_dependencies, workspace_slug

    pool = await create_pool()
    rows: list[tuple[str, int, int]] = []
    try:
        async with pool.acquire() as conn:
            tenants = [r["id"] for r in await conn.fetch("SELECT id FROM control.tenants ORDER BY id")]
        async with open_dependencies() as (rag, _media, _store):
            for tenant_id in tenants:
                slug = workspace_slug(tenant_id)
                async with tenant_conn(pool, tenant_id) as conn:
                    projects = await conn.fetch(
                        "SELECT id, project_code FROM tenant_data.projects "
                        "WHERE tenant_id = portal.current_tenant() ORDER BY id"
                    )
                    diem = await rag.count_by_doc_type(workspace_slug=slug, doc_type=_DOC_TYPE_CU)
                    if not ghi:
                        rows.append((tenant_id, diem, len(projects)))
                        continue
                    await rag.delete_by_doc_type(workspace_slug=slug, doc_type=_DOC_TYPE_CU)
                    await conn.execute(
                        "DELETE FROM tenant_data.kb_index_state "
                        "WHERE tenant_id = portal.current_tenant() AND entity = 'zones'"
                    )
                    for p in projects:
                        await dat_viec_nap(
                            conn,
                            tenant_id=tenant_id,
                            actor="drop_zone_points",
                            entity="projects",
                            record_id=int(p["id"]),
                            project_code=str(p["project_code"]),
                        )
                    rows.append((tenant_id, diem, len(projects)))
    finally:
        await pool.close()

    for line in plan_lines(rows):
        print(line)
    if not ghi:
        print("\nTHỬ KHÔ — thêm --ghi để chạy thật.")
    return 0


def main() -> int:
    return asyncio.run(main_async("--ghi" in sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Thêm hai phương thức đếm/xoá theo `doc_type`**

Trong `src/portal/modules/kb/index/store.py`, thêm vào `class QdrantStore`:

```python
    async def count_by_doc_type(self, name: str, *, doc_type: str) -> int:
        if not await self._c.collection_exists(name):
            return 0
        loc = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])
        return (await self._c.count(name, count_filter=loc, exact=True)).count

    async def delete_by_doc_type(self, name: str, *, doc_type: str) -> int:
        dem = await self.count_by_doc_type(name, doc_type=doc_type)
        if dem:
            loc = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])
            await self._c.delete(name, points_selector=loc, wait=True)
        return dem
```

Trong `src/portal/modules/kb/clients/base.py`, thêm vào `class LocalIndexClient`:

```python
    async def count_by_doc_type(self, *, workspace_slug: str, doc_type: str) -> int:
        fn = getattr(self._store, "count_by_doc_type", None)
        return 0 if fn is None else await fn(self.collection(workspace_slug), doc_type=doc_type)

    async def delete_by_doc_type(self, *, workspace_slug: str, doc_type: str) -> int:
        fn = getattr(self._store, "delete_by_doc_type", None)
        return 0 if fn is None else await fn(self.collection(workspace_slug), doc_type=doc_type)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_drop_zone_points.py -v`
Expected: PASS 2 passed

- [ ] **Step 6: Smoke thử khô**

Run: `uv run python -m portal.cli.drop_zone_points`
Expected: in một dòng mỗi tenant + dòng `TỔNG:` + `THỬ KHÔ — thêm --ghi để chạy thật.`, **không** ghi gì.

Kiểm chứng không ghi: `uv run pytest tests/modules/kb -q` vẫn xanh, và không có job mới trong `control.jobs`.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/portal/cli/drop_zone_points.py src/portal/modules/kb/index/store.py src/portal/modules/kb/clients/base.py tests/unit/test_drop_zone_points.py
git commit -m "feat(kb): CLI dọn point phan_khu cũ và xếp lại toàn bộ dự án"
```

---

### Task 8: Cập nhật hợp đồng payload

**Files:**
- Modify: `docs/contracts/payload-qdrant.md`
- Test: `uv run pytest tests/api -q` (cổng hợp đồng hiện có)

**Interfaces:**
- Consumes: —
- Produces: bản hợp đồng khớp code, để copy tay sang `odyssey-agent/docs/contracts/payload-qdrant.md`.

- [ ] **Step 1: Sửa §1** — dòng `<tenant_id>_documents`: đổi mô tả `(dự án · phân khu · tài liệu · CSBH · pháp lý)` thành `(dự án · tài liệu · CSBH · pháp lý)`.

- [ ] **Step 2: Sửa §3** — đổi tiêu đề `## 3. <tenant>_documents — 12 khoá` thành `— 11 khoá`; xoá 3 hàng `section_path`, `page`, và mọi hàng `section` còn sót; sửa mô tả `doc_type` bỏ `phan_khu` khỏi danh sách giá trị:

```
`doc_type` | text | `"csbh"` | `tong_quan` (dự án, gồm cả khối phân khu) · `csbh` · `phap_ly` · `huong_dan` · `khac`. Nằm trong id point. **Cũng là thứ suy ra bảng nguồn** — xem §6. | Portal |
```

- [ ] **Step 3: Sửa §6** — ba hàng, thay hàng `section` cũ:

```
`section` | documents | Trùng **phần tử cuối** của `section_path`. **ĐÃ BỎ HẲN 2026-08-19** (pha 3). |
`section_path` | documents | Trùng nội dung `text`: `_tien_to()` gắn `"<project_name> — <mục>"` vào đầu **mọi** chunk trước khi nhúng. Đo trên 136 point thật ở 4 collection: **136/136** khớp. Agent thoái hoá êm — `_section()` trả `""`, tiêu đề khối rút từ `[Dự án › Mục]` xuống `[Dự án]`, nhãn mục vẫn nằm trong `text` ngay bên dưới. |
`page` | documents | Hardcode `0` từ ngày đầu, chưa từng có giá trị khác. Agent bỏ qua khi `<= 0`. |
```

- [ ] **Step 4: Thêm §9 — phân khu**

```markdown
## 9. Phân khu nằm trong doc `tong_quan` (2026-08-19)

`doc_type = "phan_khu"` **đã bỏ**. Phân khu của một dự án gộp thành MỘT khối trong doc
`tong_quan` của dự án đó, và khối ấy luôn là **point riêng**:

    Vinhomes Global Gate Hạ Long — Phân khu

    ## Cơ cấu sản phẩm
    ### Phân khu
    - **Vịnh Bình Minh 1**
    - **Vịnh Bình Minh 2**

Point khối phân khu mang `doc_type = "tong_quan"` và **cùng `record_id`** với point quick-fact
của dự án (id hàng `projects`) — chúng khác nhau ở `idx` trong id point.

⚠ **`status` của point là của DỰ ÁN.** Phân khu `draft` vẫn vào text; không mệnh đề lọc nào
tách được nó ra. Đánh đổi có chủ ý — xem spec §7.
```

- [ ] **Step 5: Chạy cổng hợp đồng**

Run: `uv run pytest tests/api -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/contracts/payload-qdrant.md
git commit -m "docs(contracts): payload documents còn 11 khoá, bỏ doc_type phan_khu"
```

- [ ] **Step 7: Việc TAY sau khi merge — báo cho người dùng, không tự làm**

1. Copy `docs/contracts/payload-qdrant.md` sang `odyssey-agent/docs/contracts/payload-qdrant.md` (không có job CI nào so hai bên).
2. Dọn `odyssey-agent/src/noble_agent/agent/rag/kb_service_adapter.py::_section()` — không gấp, thoái hoá êm.
3. Thêm vào Change Log `CLAUDE.md` (người dùng tự sửa, tôi không đụng file đó).
4. Chạy `python -m portal.cli.drop_zone_points --ghi` trên môi trường deploy **sau** khi code đã lên.

---

## Thứ tự chạy và kiểm cuối

Sau Task 8:

- [ ] `make check` — lint + toàn bộ test
- [ ] `uv run pytest tests/isolation -q` — số dòng đỏ **không tăng** so với baseline trước đợt này
- [ ] `uv run pytest tests/unit/test_alembic_mot_head.py -v` — plan này không thêm migration nào, bài này phải xanh
