# KB doc_type — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gộp `doc_type` `thong_tin` vào `tong_quan`, và cho `documents` mang `doc_type` thật (`csbh`/`phap_ly`/`huong_dan`/`khac`) suy từ tiền tố `title` — không đụng schema Postgres.

**Architecture:** `EntitySpec` nhận thêm `doc_type_from: Callable[[dict], str] | None`; khi có, `resolve_text()` gọi nó trên row thay vì dùng hằng `spec.doc_type`. Bảng tiền tố và ba hàm thuần (`split_title` · `join_title` · `doc_type_of`) sống ở `modules/kb/contracts.py` vì đó là mặt tiền duy nhất `modules/realestate` được import. Router `realestate` ghép/tách tiền tố ở biên HTTP nên frontend không bao giờ thấy nó.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg · Pydantic v2 · pytest-asyncio · uv

## Global Constraints

- **Không migration, không đổi schema Postgres.** Head alembic `0916_conversations_source` phải giữ nguyên.
- **Luật 3 (`tests/test_module_boundaries.py`, đọc AST):** module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. `modules/realestate` **không** được import `portal.modules.kb.directive.*` hay `portal.modules.kb.service`.
- **Tập giá trị `doc_type` của `documents`:** `csbh` · `phap_ly` · `huong_dan` · `khac`. Không được trùng `tong_quan` · `phan_khu` (point-id là `uuid5(doc_type:record_id:idx)`, không chứa tên bảng).
- **Ngăn cách tiền tố:** `" — "` (em-dash U+2014, một khoảng trắng mỗi bên).
- **Định danh tiếng Anh**, comment và tên test tiếng Việt — nếp sẵn của repo.
- **Comment thưa.** Chỉ viết khi giải thích *vì sao*, không mô tả *cái gì*.
- Chạy test: `uv run pytest`. Cổng trước MR: `make check`.

**Spec:** `docs/superpowers/specs/2026-08-10-tab-kien-thuc-bds-design.md`

---

### Task 1: Gộp hai `EntitySpec` của `projects`

Spec §4.1. Sau task này `REAL_ESTATE.embed_sources` còn ba phần tử và `doc_type` `thong_tin` biến mất.

**Files:**
- Modify: `src/portal/modules/kb/directive/verticals/real_estate.py:18-44`
- Modify: `src/portal/modules/kb/state/repo.py:68`
- Test: `tests/modules/kb/test_directive.py`
- Test: `tests/modules/kb/test_source_query.py:15`

**Interfaces:**
- Consumes: —
- Produces: `REAL_ESTATE.embed_sources` có đúng 3 phần tử; `resolve.source_for(REAL_ESTATE, "projects")` trả spec duy nhất mà không cần tham số `doc_type`.

- [ ] **Step 1: Sửa test hiện có để nó đỏ**

Trong `tests/modules/kb/test_directive.py`, thay hàm ở dòng 10-21:

```python
def test_ba_nguon_embed_va_projects_chi_xuat_hien_mot_lan():
    """Gộp thong_tin vào tong_quan (spec §4.1). doc_type vẫn trong khoá kb_index_state
    vì `documents` sinh nhiều doc_type theo tiền tố title."""
    assert len(REAL_ESTATE.embed_sources) == 3
    assert [s.table for s in REAL_ESTATE.embed_sources].count("projects") == 1
    assert {s.doc_type for s in REAL_ESTATE.embed_sources} == {
        "tong_quan",
        "phan_khu",
        "tai_lieu",
    }
    # units KHÔNG embed — nó chỉ ở Postgres, agent lọc bằng SQL.
    assert "units" not in {s.table for s in REAL_ESTATE.embed_sources}
```

Trong cùng file, bỏ tham số `"thong_tin"` ở dòng 38 và 46:

```python
def test_ghep_text_giu_dung_thu_tu_khai_bao():
    """Thứ tự field = thứ tự trong embed_sources, KHÔNG phải thứ tự trong dict row."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "investor": "Noble", "region": "Long Biên"}
    text = resolve.build_text(row, spec)
    assert text.index("region:") < text.index("investor:")


def test_ghep_text_bo_field_rong_nhung_giu_so_khong():
    """`build_density_pct = 0` là dữ liệu thật, không phải "chưa nhập"."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "region": "  ", "build_density_pct": 0}
    text = resolve.build_text(row, spec)
    assert "region" not in text
    assert "build_density_pct: 0" in text
```

Bỏ tham số `"tong_quan"` ở dòng 64, và thêm assert rằng `overview` với `amenities` nay cùng một spec:

```python
def test_breadcrumb_cua_anchor_chi_la_ten_no():
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "overview": "Đại đô thị ven sông"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.section == "Noble Palace"


def test_quick_fact_va_van_xuoi_nam_chung_mot_spec_chunk_facts():
    """Gộp xong thì overview/amenities cũng mang nhãn cột — chọn markdown sẽ làm
    9 quick-fact thành chuỗi số trần, không tra được (spec §4.1)."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    assert spec.chunk == "facts"
    assert spec.fields.index("overview") > spec.fields.index("total_investment_vnd")
    row = {"id": 1, spec.anchor_col: "nplb", "region": "Long Biên", "overview": "Đại đô thị"}
    text = resolve.build_text(row, spec)
    assert "region: Long Biên" in text
    assert "overview: Đại đô thị" in text
```

Thay hàm ở dòng 70-72 — `source_for` không còn raise cho `projects`, nhưng cổng vẫn phải còn cho vertical sau này:

```python
def test_source_for_bo_qua_doc_type_khi_bang_chi_co_mot_spec():
    """Caller cũ truyền "thong_tin" vẫn chạy và KHÔNG báo gì — đó là lý do phải
    sửa caller tường minh, đừng đợi test đỏ hộ."""
    assert resolve.source_for(REAL_ESTATE, "projects", "thong_tin").doc_type == "tong_quan"
    assert resolve.source_for(REAL_ESTATE, "projects").doc_type == "tong_quan"
```

Trong `tests/modules/kb/test_source_query.py`, sửa dòng 15:

```python
    spec = resolve.source_for(REAL_ESTATE, "projects")
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_directive.py tests/modules/kb/test_source_query.py -v`
Expected: FAIL — `assert 4 == 3` ở `test_ba_nguon_embed_va_projects_chi_xuat_hien_mot_lan`, và `ValueError: 'projects' có 2 nguồn — phải nói rõ doc_type` ở các test gọi `source_for(REAL_ESTATE, "projects")`.

- [ ] **Step 3: Gộp hai spec**

Trong `src/portal/modules/kb/directive/verticals/real_estate.py`, thay hai `EntitySpec` đầu (dòng 19-44) bằng một:

```python
        EntitySpec(
            table="projects",
            doc_type="tong_quan",
            chunk="facts",
            is_anchor=True,
            anchor_col=ANCHOR_CODE_COL,
            # overview/amenities đứng CUỐI: thứ tự này quyết định content_hash, đặt
            # cuối giữ nguyên thứ tự tương đối của 9 quick-fact nên diff đọc được.
            fields=(
                "region",
                "investor",
                "total_land_area_m2",
                "floor_area_m2",
                "build_density_pct",
                "product_scale",
                "ownership_form",
                "handover_standard",
                "total_investment_vnd",
                "overview",
                "amenities",
            ),
        ),
```

Sửa docstring đầu file (dòng 1-5), câu thứ hai:

```python
"""Khai báo real_estate — nguyên văn `rag_config["real_estate"]` (§15.1).

Thêm/bớt field embed, đổi chunk strategy, đổi caption profile → sửa ở đây.
`units` không embed: agent lọc căn bằng SQL trên cột thật.

`projects` chỉ còn MỘT spec (`tong_quan`) — `thong_tin` đã gộp vào, xem
docs/superpowers/specs/2026-08-10-tab-kien-thuc-bds-design.md §4.1.
"""
```

- [ ] **Step 4: Sửa docstring của `read_state`**

Trong `src/portal/modules/kb/state/repo.py:68`:

```python
async def read_state(conn: asyncpg.Connection, *, entity: str, record_id: int) -> list[asyncpg.Record]:
    """`documents` sinh nhiều dòng (mỗi doc_type một dòng) nên trả list."""
```

- [ ] **Step 5: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/kb/test_directive.py tests/modules/kb/test_source_query.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/directive/verticals/real_estate.py \
        src/portal/modules/kb/state/repo.py \
        tests/modules/kb/test_directive.py \
        tests/modules/kb/test_source_query.py
git commit -m "refactor(kb): gộp doc_type thong_tin vào tong_quan"
```

---

### Task 2: `doc_type_from` — cho `EntitySpec` đọc doc_type từ row

Spec §4.2. Task này chỉ mở cơ chế; chưa vertical nào dùng.

**Files:**
- Modify: `src/portal/modules/kb/contracts.py:102-118`
- Modify: `src/portal/modules/kb/directive/resolve.py:29-52`
- Test: `tests/modules/kb/test_directive.py`

**Interfaces:**
- Consumes: —
- Produces: `EntitySpec.doc_type_from: Callable[[dict], str] | None = None`. `resolve.resolve_text()` trả `TextDirective.doc_type = spec.doc_type_from(row)` khi trường đó khác `None`, ngược lại `spec.doc_type`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `tests/modules/kb/test_directive.py`:

```python
def test_doc_type_from_lay_gia_tri_tu_row_thay_vi_hang():
    """Cơ chế của spec §4.2 — spec khai hàm thì directive lấy doc_type theo từng row."""
    from portal.modules.kb.contracts import EntitySpec

    spec = EntitySpec(
        table="documents",
        doc_type="tai_lieu",
        chunk="structured_md",
        fields=("title",),
        doc_type_from=lambda row: "csbh" if row["title"].startswith("CSBH") else "khac",
    )
    d = resolve.resolve_text(
        workspace_slug="acme",
        row={"id": 1, "project_code": "nplb", "title": "CSBH — Bảng giá"},
        anchor_name="NP",
        spec=spec,
    )
    assert d.doc_type == "csbh"


def test_khong_khai_doc_type_from_thi_van_dung_hang():
    spec = resolve.source_for(REAL_ESTATE, "zones")
    d = resolve.resolve_text(
        workspace_slug="acme",
        row={"id": 1, "project_code": "nplb", "name": "Phân khu A", "overview": "x"},
        anchor_name="NP",
        spec=spec,
    )
    assert d.doc_type == "phan_khu"
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_directive.py::test_doc_type_from_lay_gia_tri_tu_row_thay_vi_hang -v`
Expected: FAIL với `TypeError: EntitySpec.__init__() got an unexpected keyword argument 'doc_type_from'`.

- [ ] **Step 3: Thêm trường vào `EntitySpec`**

Trong `src/portal/modules/kb/contracts.py`, thêm import ở đầu file:

```python
from collections.abc import Callable
```

Thêm trường vào cuối `EntitySpec` (sau `section_col`):

```python
    # Cột làm đuôi breadcrumb (zones.name, documents.title).
    section_col: str | None = None
    # Khai hàm này khi doc_type thay đổi theo TỪNG ROW, không phải theo bảng.
    # `doc_type` bên trên vẫn phải khai — backfill và source_for dùng nó để định danh spec.
    doc_type_from: Callable[[dict], str] | None = None
```

- [ ] **Step 4: Dùng nó trong `resolve_text`**

Trong `src/portal/modules/kb/directive/resolve.py`, sửa dòng `doc_type=spec.doc_type,` trong `resolve_text()`:

```python
        doc_type=spec.doc_type_from(row) if spec.doc_type_from else spec.doc_type,
```

- [ ] **Step 5: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/kb/test_directive.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/contracts.py \
        src/portal/modules/kb/directive/resolve.py \
        tests/modules/kb/test_directive.py
git commit -m "feat(kb): EntitySpec nhận doc_type_from để lấy doc_type theo row"
```

---

### Task 3: Bảng tiền tố + ba hàm thuần, gắn vào spec `documents`

Spec §4.2 và §4.3. Đặt ở `contracts.py` vì `modules/realestate` sẽ import (Task 6) và luật 3 chỉ cho nó chạm file này.

**Files:**
- Modify: `src/portal/modules/kb/contracts.py`
- Modify: `src/portal/modules/kb/directive/verticals/real_estate.py:52-59`
- Create: `tests/unit/test_doc_type_khong_dung.py`
- Test: `tests/modules/kb/test_directive.py`

**Interfaces:**
- Consumes: `EntitySpec.doc_type_from` (Task 2)
- Produces, tất cả trong `portal.modules.kb.contracts`:
  - `TITLE_SEPARATOR: str` = `" — "`
  - `TITLE_PREFIXES: dict[str, str]` — nhãn tiền tố → mã loại
  - `DEFAULT_DOC_TYPE: str` = `"khac"`
  - `split_title(title: str) -> tuple[str, str]` — trả `(loai, tieu_de_duoi)`
  - `join_title(loai: str, title: str) -> str`
  - `doc_type_of(row: dict) -> str`

- [ ] **Step 1: Viết test đỏ cho ba hàm thuần**

Thêm vào cuối `tests/modules/kb/test_directive.py`:

```python
def test_split_title_nhan_dung_bon_loai():
    from portal.modules.kb import contracts as c

    assert c.split_title("CSBH — Bảng giá đợt 3") == ("csbh", "Bảng giá đợt 3")
    assert c.split_title("Pháp lý — Hợp đồng mẫu") == ("phap_ly", "Hợp đồng mẫu")
    assert c.split_title("Hướng dẫn — Sổ tay bàn giao") == ("huong_dan", "Sổ tay bàn giao")


def test_split_title_khong_co_ngan_cach_thi_giu_nguyen():
    from portal.modules.kb import contracts as c

    assert c.split_title("Brochure công ty") == ("khac", "Brochure công ty")


def test_split_title_co_ngan_cach_nhung_tien_to_la_thi_GIU_NGUYEN_CA_CAU():
    """Bẫy chính: cắt phần đầu của một tiêu đề tự do là âm thầm đổi tên tài liệu."""
    from portal.modules.kb import contracts as c

    assert c.split_title("Quy trình — bước 2") == ("khac", "Quy trình — bước 2")


def test_split_title_phan_biet_hoa_thuong():
    """`csbh —` không phải tiền tố hợp lệ: khoan dung ở đây nghĩa là hai tiêu đề
    khác nhau sinh cùng một doc_type, và không ai nhìn ra lúc đọc dữ liệu."""
    from portal.modules.kb import contracts as c

    assert c.split_title("csbh — Bảng giá") == ("khac", "csbh — Bảng giá")


def test_join_title_la_nghich_dao_cua_tach():
    from portal.modules.kb import contracts as c

    assert c.join_title("csbh", "Bảng giá đợt 3") == "CSBH — Bảng giá đợt 3"
    assert c.join_title("khac", "Brochure công ty") == "Brochure công ty"
    assert c.split_title(c.join_title("phap_ly", "Sổ đỏ")) == ("phap_ly", "Sổ đỏ")


def test_loai_tai_lieu_doc_tu_cot_title_cua_row():
    from portal.modules.kb import contracts as c

    assert c.doc_type_of({"title": "CSBH — Bảng giá"}) == "csbh"
    assert c.doc_type_of({"title": "Brochure"}) == "khac"


def test_spec_documents_khai_doc_type_from_nen_directive_mang_loai_that():
    spec = resolve.source_for(REAL_ESTATE, "documents")
    row = {"id": 9, "project_code": "nplb", "title": "CSBH — Bảng giá đợt 3", "body": "x"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.doc_type == "csbh"
    # Breadcrumb tự mang loại vì section_col="title" — không cần chèn cấp nào.
    assert d.section == "Noble Palace > CSBH — Bảng giá đợt 3"
```

Sửa `test_breadcrumb_cua_documents_gom_ten_du_an_va_tieu_de` (dòng 53-60) — tiêu đề seed không có tiền tố nên loại là `khac`:

```python
def test_breadcrumb_cua_documents_gom_ten_du_an_va_tieu_de():
    spec = resolve.source_for(REAL_ESTATE, "documents")
    row = {"id": 9, "project_code": "nplb", "title": "Chính sách bán hàng Q3", "body": "x"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.section == "Noble Palace > Chính sách bán hàng Q3"
    assert d.doc_type == "khac", "không có tiền tố thì rơi về khac, không phải tai_lieu"
    assert d.chunk.strategy == "structured_md"
    assert (d.chunk.max_chars, d.chunk.overlap) == (800, 150)
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_directive.py -v -k "tieu_de or loai_tai_lieu"`
Expected: FAIL với `AttributeError: module 'portal.modules.kb.contracts' has no attribute 'split_title'`.

- [ ] **Step 3: Cài ba hàm thuần**

Thêm vào cuối `src/portal/modules/kb/contracts.py`:

```python
# ─── Phân loại tài liệu bằng tiền tố `title` ────────────────────────────────
# Ở ĐÂY, KHÔNG Ở `verticals/real_estate.py`: `modules/realestate` phải ghép và
# tách tiền tố ở biên HTTP, mà luật 3 chỉ cho nó import `modules.kb.contracts`.
# Để bảng này ở vertical nghĩa là repo có hai bản sao và không cổng nào so chúng.
#
# `documents` KHÔNG có cột phân loại (0400 cố ý) và spec 2026-08-10 §2 cấm thêm,
# nên `title` mang hai nghĩa. Miền giá trị ĐÓNG là thứ giữ an toàn cho point-id:
# `uuid5(doc_type:record_id:idx)` không chứa tên bảng, nên một giá trị trùng
# `tong_quan`/`phan_khu` sẽ ghi đè point của projects/zones — xem §4.3.
TITLE_SEPARATOR = " — "
TITLE_PREFIXES: dict[str, str] = {"CSBH": "csbh", "Pháp lý": "phap_ly", "Hướng dẫn": "huong_dan"}
DEFAULT_DOC_TYPE = "khac"

_PREFIX_BY_TYPE = {ma: nhan for nhan, ma in TITLE_PREFIXES.items()}


def split_title(title: str) -> tuple[str, str]:
    """`"CSBH — Bảng giá"` → `("csbh", "Bảng giá")`.

    Tiền tố lạ thì trả NGUYÊN VĂN cả câu: `"Quy trình — bước 2"` có dấu ngăn cách
    nhưng không phải tiêu đề đã phân loại, cắt nó đi là đổi tên tài liệu của user.
    """
    dau, sep, duoi = title.partition(TITLE_SEPARATOR)
    if sep and dau in TITLE_PREFIXES:
        return TITLE_PREFIXES[dau], duoi
    return DEFAULT_DOC_TYPE, title


def join_title(loai: str, title: str) -> str:
    tien_to = _PREFIX_BY_TYPE.get(loai)
    return f"{tien_to}{TITLE_SEPARATOR}{title}" if tien_to else title


def doc_type_of(row: dict) -> str:
    """Chữ ký khớp `EntitySpec.doc_type_from`."""
    return split_title(str(row["title"]))[0]
```

- [ ] **Step 4: Gắn vào spec `documents`**

Trong `src/portal/modules/kb/directive/verticals/real_estate.py`, sửa import ở đầu file:

```python
from portal.modules.kb.contracts import EntitySpec, VerticalSpec, doc_type_of
```

Sửa `EntitySpec` của `documents`:

```python
        EntitySpec(
            table="documents",
            doc_type="tai_lieu",
            chunk="structured_md",
            fields=("title", "body"),
            extra_cols=("file_url",),
            section_col="title",
            # doc_type thật lấy từ tiền tố title; `doc_type="tai_lieu"` bên trên chỉ
            # còn là tên định danh spec cho backfill và source_for.
            doc_type_from=doc_type_of,
        ),
```

- [ ] **Step 5: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/kb/test_directive.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Viết cổng canh point-id**

Tạo `tests/unit/test_doc_type_khong_dung.py`:

```python
"""Cổng canh bất biến point-id — spec 2026-08-10 §4.3.

⚠️ KHI TEST NÀY ĐỎ, ĐỪNG SỬA `values` CHO XANH. Nó đỏ nghĩa là một tiền tố mới
trong TITLE_PREFIXES sinh ra doc_type đã thuộc về nguồn khác. Point id là
`uuid5(doc_type:record_id:idx)` và KHÔNG chứa tên bảng, nên `projects` id 12 và
`documents` id 12 cùng doc_type sẽ ghi đè nhau — không lỗi, không log, một trong
hai biến mất khỏi kho vector. Sửa bằng cách đổi tên mã loại mới.
"""

from portal.modules.kb.contracts import DEFAULT_DOC_TYPE, TITLE_PREFIXES
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_loai_tai_lieu_khong_dung_doc_type_cua_nguon_khac():
    values = set(TITLE_PREFIXES.values()) | {DEFAULT_DOC_TYPE}
    khac = {s.doc_type for s in REAL_ESTATE.embed_sources if s.doc_type_from is None}
    assert values & khac == set()


def test_moi_tien_to_sinh_mot_ma_rieng():
    """Hai tiền tố cùng mã nghĩa là join_title() mất tính nghịch đảo."""
    assert len(set(TITLE_PREFIXES.values())) == len(TITLE_PREFIXES)
```

- [ ] **Step 7: Chạy cổng canh**

Run: `uv run pytest tests/unit/test_doc_type_khong_dung.py -v`
Expected: PASS (2 test).

- [ ] **Step 8: Chạy cổng ranh giới module**

Run: `uv run pytest tests/test_module_boundaries.py -v`
Expected: PASS — `real_estate.py` import `contracts` cùng module nên không vi phạm.

- [ ] **Step 9: Commit**

```bash
git add src/portal/modules/kb/contracts.py \
        src/portal/modules/kb/directive/verticals/real_estate.py \
        tests/modules/kb/test_directive.py \
        tests/unit/test_doc_type_khong_dung.py
git commit -m "feat(kb): phân loại tài liệu bằng tiền tố title, doc_type mang loại thật"
```

---

### Task 4: `kb_index_state` ghi doc_type thật

Sổ ghi đang dùng hằng `spec.doc_type`. Không sửa thì point mang `csbh` còn sổ ghi `tai_lieu`, và câu hỏi "CSBH đã index chưa" trả lời sai.

**Files:**
- Modify: `src/portal/modules/kb/service.py:58-60,65-73`
- Test: `tests/modules/kb/test_service_ingest.py`

**Interfaces:**
- Consumes: `TextDirective.doc_type` do Task 3 sinh
- Produces: hàng `kb_index_state` của một `documents` mang `doc_type` bằng loại thật của nó.

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `tests/modules/kb/test_service_ingest.py`:

```python
async def test_kb_index_state_ghi_doc_type_that_khong_phai_hang_cua_spec(api_pool, doc_ids):
    """Sổ ghi phải nói đúng point nào đang tồn tại — nếu không, "CSBH đã index chưa"
    là câu hỏi trả lời sai mà không ai biết."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET title = 'CSBH — Bảng giá đợt 3' WHERE id = $1",
            doc_ids["nplb"],
        )
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    assert [r["doc_type"] for r in rows] == ["csbh"]
    assert rows[0]["state"] == "indexed"
    d = rag.indexed[0]
    assert isinstance(d, TextDirective)
    assert d.doc_type == "csbh"
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_service_ingest.py::test_kb_index_state_ghi_doc_type_that_khong_phai_hang_cua_spec -v`
Expected: FAIL với `assert ['tai_lieu'] == ['csbh']`.

- [ ] **Step 3: Dùng `directive.doc_type` trong `index_text`**

Trong `src/portal/modules/kb/service.py`, sửa **cả hai** lời gọi `repo.save_state` trong `index_text()` — đổi `doc_type=spec.doc_type` thành `doc_type=directive.doc_type`:

```python
    await repo.save_state(
        conn, entity=entity, record_id=record_id, doc_type=directive.doc_type, target="documents", state="indexing"
    )
    result = await rag.index(directive)

    if result.extracted_text:
        await repo.cache_extracted_text(conn, record_id=record_id, text=result.extracted_text)
    await repo.save_state(
        conn,
        entity=entity,
        record_id=record_id,
        # directive, KHÔNG spec: với documents thì doc_type đến từ row, và sổ ghi
        # phải khớp point-id đã tạo — nếu không thì xoá point sẽ trượt (§4.4).
        doc_type=directive.doc_type,
        target="documents",
        state="indexed",
        result=result,
    )
```

- [ ] **Step 4: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/kb/test_service_ingest.py -v`
Expected: PASS toàn bộ, gồm cả các test cũ.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/service.py tests/modules/kb/test_service_ingest.py
git commit -m "fix(kb): kb_index_state ghi doc_type thật của directive, không phải hằng của spec"
```

---

### Task 5: `delete_index` tra sổ khi không biết doc_type

Khi row đã bị xoá hoặc rời `published`, không đọc được `title` nữa nên không suy được loại. Nguồn duy nhất còn lại là `kb_index_state`. Đây cũng vá một bug sẵn có: `delete_cascade` gọi `delete_index` **không** truyền doc_type nên đang xoá bằng `doc_type=""`, không khớp point-id của bất kỳ nguồn nào.

**Files:**
- Modify: `src/portal/modules/kb/service.py:132-145`
- Test: `tests/modules/kb/test_service_ingest.py`

**Interfaces:**
- Consumes: `repo.read_state(conn, entity=..., record_id=...) -> list[Record]` (đã có)
- Produces: `service.delete_index()` gọi `client.delete()` **một lần cho mỗi `doc_type`** đã ghi trong sổ khi caller không truyền `doc_type`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `tests/modules/kb/test_service_ingest.py`:

```python
async def test_xoa_khong_biet_doc_type_thi_tra_so_de_xoa_dung_point(api_pool, doc_ids):
    """Row đã mất thì không suy được loại từ title — sổ kb_index_state là nguồn cuối.
    Xoá bằng doc_type="" sẽ trượt vì point id là uuid5(doc_type:record_id:idx)."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET title = 'Pháp lý — Sổ đỏ' WHERE id = $1",
            doc_ids["nplb"],
        )
        await service.index_text(
            conn,
            tenant_id=TENANT,
            slug=TENANT,
            vertical=REAL_ESTATE,
            entity="documents",
            doc_type="tai_lieu",
            record_id=doc_ids["nplb"],
            rag=rag,
            store=store,
        )
        await service.delete_index(
            conn, slug=TENANT, entity="documents", record_id=doc_ids["nplb"], rag=rag, media=rag
        )

    assert rag.deleted == [(TENANT, doc_ids["nplb"], "phap_ly")]


async def test_xoa_co_doc_type_tuong_minh_thi_khong_tra_so(api_pool, doc_ids):
    """Caller biết loại cũ (đường §4.4) thì dùng đúng cái đó — sổ lúc đó đã là loại MỚI."""
    rag = FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await service.delete_index(
            conn,
            slug=TENANT,
            entity="documents",
            record_id=doc_ids["nplb"],
            rag=rag,
            media=rag,
            doc_type="csbh",
        )

    assert rag.deleted == [(TENANT, doc_ids["nplb"], "csbh")]
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_service_ingest.py::test_xoa_khong_biet_doc_type_thi_tra_so_de_xoa_dung_point -v`
Expected: FAIL với `assert [('kb_acme', N, '')] == [('kb_acme', N, 'phap_ly')]`.

- [ ] **Step 3: Cài**

Trong `src/portal/modules/kb/service.py`, thay `delete_index()`:

```python
async def delete_index(
    conn: asyncpg.Connection,
    *,
    slug: str,
    entity: str,
    record_id: int,
    rag: IndexClient,
    media: IndexClient,
    doc_type: str = "",
) -> None:
    """Xoá point của một record. Cascade cây con là việc của delete_cascade().

    `doc_type=""` nghĩa là caller KHÔNG BIẾT — row có thể đã bị xoá nên không suy
    được loại từ nội dung. Sổ `kb_index_state` là nguồn duy nhất còn lại, và một
    record có thể có nhiều dòng (documents đổi loại vài lần). Xoá bằng chuỗi rỗng
    thì point id `uuid5(doc_type:record_id:idx)` không khớp gì và point ở lại vĩnh viễn.
    """
    client = media if entity == "media" else rag
    if doc_type or entity == "media":
        loai = [doc_type]
    else:
        rows = await repo.read_state(conn, entity=entity, record_id=record_id)
        loai = [str(r["doc_type"]) for r in rows] or [""]
    for dt in loai:
        await client.delete(workspace_slug=slug, record_id=record_id, doc_type=dt)
    await repo.mark_deleted(conn, entity=entity, record_id=record_id)
```

- [ ] **Step 4: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/kb/ -v`
Expected: PASS toàn bộ module kb.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/service.py tests/modules/kb/test_service_ingest.py
git commit -m "fix(kb): delete_index tra kb_index_state khi caller không biết doc_type"
```

---

### Task 6: API `loai` cho `documents`

Spec §6. Tiền tố ghép và tách ở biên HTTP nên frontend không bao giờ thấy nó, và bảng tiền tố chỉ tồn tại một nơi.

**Files:**
- Modify: `src/portal/modules/realestate/contracts.py:270-281` — `TaiLieuOut`
- Modify: `src/portal/modules/realestate/router.py` — `_ra_tai_lieu` (dòng 415), `DocumentIn`/`DocumentPatch` (dòng 664-680), `_payload_tai_lieu` (mới, cạnh `_tach_payload` dòng 712), `tao_tai_lieu`, `sua_tai_lieu`
- Create: `tests/modules/realestate/test_tai_lieu_loai.py`

**Interfaces:**
- Consumes: `portal.modules.kb.contracts.join_title` · `split_title` (Task 3)
- Produces: `TaiLieuOut.loai: str` và `TaiLieuOut.title` là **phần đuôi**; `DocumentIn.loai` / `DocumentPatch.loai` nhận `Literal["csbh","phap_ly","huong_dan","khac"]`, mặc định `"khac"`.

- [ ] **Step 1: Viết test đỏ**

Fixture của thư mục này là `client_re` / `workspace_re` (tenant `rew`, `tests/modules/realestate/conftest.py`), và đường dẫn API có tiền tố `/api/v1` — cùng nếp `test_crud.py`.

Tạo `tests/modules/realestate/test_tai_lieu_loai.py`:

```python
"""Tiền tố loại ghép/tách ở biên HTTP — spec 2026-08-10 §4.2, §6.

Frontend KHÔNG được thấy tiền tố: nếu nó tự ghép thì bảng tiền tố có bản sao ở
repo kia, không cổng nào so hai bên, và một chữ lệch làm mọi tài liệu mới rơi về
`khac` — im lặng.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _tao_du_an(client: httpx.AsyncClient, project_code: str) -> None:
    r = await client.post(_url("/projects"), json={"projectCode": project_code, "name": f"Dự án {project_code}"})
    assert r.status_code == 201, r.text


async def test_tao_tai_lieu_ghep_tien_to_vao_title(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC1")
    r = await client_re.post(
        _url("/projects/DOC1/documents"),
        json={"title": "Bảng giá đợt 3", "loai": "csbh", "status": "published"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["loai"] == "csbh"
    assert r.json()["title"] == "Bảng giá đợt 3", "API trả phần đuôi, không trả tiền tố"


async def test_title_trong_db_mang_tien_to(client_re: httpx.AsyncClient, conn_re):
    await _tao_du_an(client_re, "DOC2")
    tao = await client_re.post(_url("/projects/DOC2/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    title = await conn_re.fetchval("SELECT title FROM tenant_data.documents WHERE id = $1", doc_id)
    assert title == "Pháp lý — Sổ đỏ", "loại phải nằm trong title vì documents không có cột phân loại"


async def test_doc_lai_thi_tach_dung_loai(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC3")
    tao = await client_re.post(_url("/projects/DOC3/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.get(_url(f"/projects/DOC3/documents/{doc_id}"))
    assert (r.json()["loai"], r.json()["title"]) == ("phap_ly", "Sổ đỏ")


async def test_khong_gui_loai_thi_la_khac_va_title_giu_nguyen(client_re: httpx.AsyncClient):
    """`Quy trình — bước 2` có dấu ngăn cách nhưng tiền tố lạ: cắt nó đi là âm thầm
    đổi tên tài liệu của người dùng."""
    await _tao_du_an(client_re, "DOC4")
    r = await client_re.post(_url("/projects/DOC4/documents"), json={"title": "Quy trình — bước 2"})
    assert r.status_code == 201, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("khac", "Quy trình — bước 2")


async def test_loai_ngoai_bon_gia_tri_bi_chan_o_bien(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC5")
    r = await client_re.post(_url("/projects/DOC5/documents"), json={"title": "x", "loai": "tong_quan"})
    assert r.status_code == 422, "tong_quan trùng doc_type của projects — phải chặn ở biên"
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/realestate/test_tai_lieu_loai.py -v`
Expected: FAIL — `KeyError: 'loai'` hoặc 422 vì `extra="forbid"` từ chối trường `loai`.

- [ ] **Step 3: Thêm `loai` vào DTO**

Trong `src/portal/modules/realestate/router.py`, thêm import:

```python
from portal.modules.kb.contracts import join_title, split_title
```

Thêm alias enum cạnh các `Literal` khác (khu vực dòng ~495):

```python
# Trùng miền giá trị với `TITLE_PREFIXES` + mặc định — cổng canh ở
# tests/unit/test_doc_type_khong_dung.py giữ nó không đụng doc_type nguồn khác.
_LoaiTaiLieu = Literal["csbh", "phap_ly", "huong_dan", "khac"]
```

Thêm trường vào `DocumentIn` và `DocumentPatch`:

```python
class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(alias="title", min_length=1)
    loai: _LoaiTaiLieu = Field(default="khac", alias="loai")
    body: str = Field(default="", alias="body")
    file_url: str | None = Field(default=None, alias="fileUrl")  # nullable thật ở DB
    status: _Status = Field(default="draft", alias="status")


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", alias="title", min_length=1)
    loai: _LoaiTaiLieu = Field(default="khac", alias="loai")
    body: str = Field(default="", alias="body")
    file_url: str | None = Field(default=None, alias="fileUrl")
    status: _Status = Field(default="draft", alias="status")
```

Thêm `loai` vào `TaiLieuOut` trong `src/portal/modules/realestate/contracts.py:270`:

```python
class TaiLieuOut(BaseModel):
    id: int
    projectCode: str
    """`== "__ALL__"` (`SENTINEL_TENANT`) ⇒ tài liệu dùng chung toàn tenant (`02a §4b`)."""
    loai: str
    """Suy từ tiền tố `title`; `documents` không có cột phân loại (0400, spec 2026-08-10 §4.2)."""
    title: str
    body: str
    fileUrl: str | None
    status: str
    createdAt: datetime
    updatedAt: datetime
```

- [ ] **Step 4: Ghép và tách ở hai đầu**

Sửa `_ra_tai_lieu` (dòng ~415):

```python
def _ra_tai_lieu(r: asyncpg.Record) -> TaiLieuOut:
    # `documents.title` mang HAI nghĩa (tiêu đề + loại). Tách ở đây là chỗ duy nhất
    # frontend thấy chúng rời nhau — xem kb.contracts.split_title.
    loai, tieu_de = split_title(r["title"])
    return TaiLieuOut(
        id=r["id"],
        projectCode=r["project_code"],
        loai=loai,
        title=tieu_de,
        body=r["body"],
        fileUrl=r["file_url"],
        status=r["status"],
        createdAt=r["created_at"],
        updatedAt=r["updated_at"],
    )
```

Thêm hàm dựng payload ngay dưới `_tach_payload` (dòng ~717):

```python
def _payload_tai_lieu(body: DocumentIn | DocumentPatch) -> dict:
    """`loai` KHÔNG phải cột — nó nhập vào `title` thành tiền tố trước khi xuống DB."""
    payload = _tach_payload(body)
    loai = payload.pop("loai", None)
    if "title" in payload:
        payload["title"] = join_title(loai or "khac", payload["title"])
    return payload
```

Trong `tao_tai_lieu`, đổi `payload = _tach_payload(body)` thành:

```python
    payload = _payload_tai_lieu(body)
```

Trong `sua_tai_lieu`, đổi tương tự.

- [ ] **Step 5: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/realestate/test_tai_lieu_loai.py -v`
Expected: PASS (5 test).

- [ ] **Step 6: Chạy cổng ranh giới module**

Run: `uv run pytest tests/test_module_boundaries.py -v`
Expected: PASS — `modules/realestate` chỉ import `modules.kb.contracts`, đúng luật 3.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/realestate/router.py tests/modules/realestate/
git commit -m "feat(realestate): API documents nhận loai, ghép/tách tiền tố title ở biên HTTP"
```

---

### Task 7: PATCH đổi loại thì xoá point loại cũ

Spec §4.4. Router `realestate` chưa enqueue job index nào, nên việc cần làm ở đây là enqueue `kb_delete` cho loại cũ — không phải "trước khi enqueue index" như spec viết.

**Files:**
- Modify: `src/portal/modules/kb/contracts.py` — thêm hằng `KIND_DELETE_INDEX`
- Modify: `src/portal/modules/kb/jobs.py:15`
- Modify: `src/portal/modules/realestate/router.py` — `sua_tai_lieu`
- Test: `tests/modules/realestate/test_tai_lieu_loai.py`

**Interfaces:**
- Consumes: `portal.core.jobs.enqueue(conn, *, tenant_id, kind, actor, payload) -> int` (đã có), `split_title` (Task 3)
- Produces: `portal.modules.kb.contracts.KIND_DELETE_INDEX: str` = `"kb_delete"`

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/realestate/test_tai_lieu_loai.py`:

```python
async def test_doi_loai_thi_enqueue_xoa_point_loai_cu(client_re: httpx.AsyncClient, conn_re, workspace_re):
    """Point id đổi theo doc_type, mà reconcile so theo record_id nên nó KHÔNG bắt
    được point mồ côi này — phải xoá tường minh (§4.4)."""
    import json

    await _tao_du_an(client_re, "DOC6")
    tao = await client_re.post(_url("/projects/DOC6/documents"), json={"title": "Bảng giá", "loai": "csbh"})
    doc_id = tao.json()["id"]

    r = await client_re.patch(
        _url(f"/projects/DOC6/documents/{doc_id}"),
        json={"title": "Bảng giá", "loai": "phap_ly"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["loai"] == "phap_ly"

    rows = await conn_re.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC",
        workspace_re,
    )
    assert rows, "đổi loại phải để lại một job kb_delete"
    # core/jobs.enqueue lưu payload bằng json.dumps nên đọc ra là chuỗi.
    payload = json.loads(rows[0]["payload"])
    assert payload["entity"] == "documents"
    assert payload["record_id"] == doc_id
    assert payload["doc_type"] == "csbh", "phải là loại CŨ — loại mới vẫn đang cần point"


async def test_sua_duoi_tieu_de_KHONG_enqueue_xoa(client_re: httpx.AsyncClient, conn_re, workspace_re):
    """Đổi tên tài liệu mà giữ loại thì point id không đổi — xoá là mất point đang đúng."""
    await _tao_du_an(client_re, "DOC7")
    tao = await client_re.post(_url("/projects/DOC7/documents"), json={"title": "Bảng giá", "loai": "csbh"})
    doc_id = tao.json()["id"]
    truoc = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete'", workspace_re
    )

    await client_re.patch(
        _url(f"/projects/DOC7/documents/{doc_id}"),
        json={"title": "Bảng giá đợt 4", "loai": "csbh"},
    )

    sau = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete'", workspace_re
    )
    assert sau == truoc
```

`conn_re` là kết nối đã đặt `app.tenant_id` (fixture của `tests/modules/realestate/conftest.py`); `control.jobs` không bị RLS nên vẫn cần lọc `tenant_id` tường minh trong câu SQL.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/realestate/test_tai_lieu_loai.py::test_doi_loai_thi_enqueue_xoa_point_loai_cu -v`
Expected: FAIL với `assert [] , "đổi loại phải để lại một job kb_delete"`.

- [ ] **Step 3: Chuyển hằng kind vào `contracts.py`**

Thêm vào `src/portal/modules/kb/contracts.py`, ngay trên khối tiền tố:

```python
# Ở contracts chứ không ở jobs.py: `modules/realestate` phải enqueue job xoá khi
# tài liệu đổi loại, và luật 3 chỉ cho nó import file này. Hằng đi kèm chỗ nó
# được dùng qua ranh giới module.
KIND_DELETE_INDEX = "kb_delete"
```

Sửa `src/portal/modules/kb/jobs.py` để không có hai nguồn:

```python
from portal.modules.kb.contracts import IndexClient, KIND_DELETE_INDEX, ObjectStore

KIND_INDEX = "kb_index"
KIND_DELETE = KIND_DELETE_INDEX
KIND_RECONCILE = "kb_reconcile"
```

- [ ] **Step 4: Enqueue trong `sua_tai_lieu`**

Trong `src/portal/modules/realestate/router.py`, thêm import:

```python
from portal.core.jobs import enqueue
from portal.modules.kb.contracts import KIND_DELETE_INDEX, join_title, split_title
```

Dòng thứ hai thay dòng import đã thêm ở Task 6 — không thêm dòng mới.

Sửa thân `sua_tai_lieu`:

```python
    payload = _payload_tai_lieu(body)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_tai_lieu(conn, doc_id)
        if hang is None or hang["project_code"] != project_code:
            raise _tai_lieu_khong_thay()
        loai_cu, _ = split_title(hang["title"])
        sua = await repo.sua_tai_lieu(conn, doc_id, payload)
        assert sua is not None
        loai_moi, _ = split_title(sua["title"])
        if loai_moi != loai_cu:
            # point id là uuid5(doc_type:record_id:idx) nên đổi loại sinh point MỚI và
            # bỏ lại point cũ. reconcile so theo record_id nên nó không thấy — §4.4.
            await enqueue(
                conn,
                tenant_id=p.tenant_id,
                kind=KIND_DELETE_INDEX,
                actor=p.user_id,
                payload={
                    "vertical": "real_estate",
                    "entity": "documents",
                    "record_id": doc_id,
                    "doc_type": loai_cu,
                },
            )
        await _nhat_ky(conn, p, "realestate.document.update", {"id": doc_id, "truong": sorted(payload)})
    return _ra_tai_lieu(sua)
```

- [ ] **Step 5: Chạy test để chắc nó xanh**

Run: `uv run pytest tests/modules/realestate/test_tai_lieu_loai.py -v`
Expected: PASS (7 test).

- [ ] **Step 6: Chạy toàn bộ cổng**

Run: `make check`
Expected: lint sạch, test xanh. `make test-isolation` vẫn đỏ 13 test như trên `develop` — không phải do nhánh này (xem CLAUDE.md).

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/contracts.py \
        src/portal/modules/kb/jobs.py \
        src/portal/modules/realestate/router.py \
        tests/modules/realestate/test_tai_lieu_loai.py
git commit -m "feat(realestate): đổi loại tài liệu thì enqueue kb_delete cho loại cũ"
```

---

## Sau khi xong

Backend đã đủ để frontend làm việc. Kế hoạch frontend (bộ 10 tab, `VungMedia` tách file, `TaiLieuTab` chia bốn vùng) viết riêng vì nó ở repo `odyssey-portal-frontend` và chỉ bắt đầu được khi API `loai` đã có.

Hai điều spec ghi mà plan này **không** làm, đúng như §7 của spec:
- `reconcile` vẫn không bắt được point mồ côi do sửa `title` bằng SQL tay — bịt hẳn phải thêm `doc_type` vào `IndexPoint`, tức đổi hợp đồng `/admin/scroll` với repo `odyssey-agent`.
- Không có script dọn point `thong_tin`/`tai_lieu` cũ. Runbook ở §8 của spec dành cho môi trường đã index; hiện chưa có môi trường nào như vậy.
