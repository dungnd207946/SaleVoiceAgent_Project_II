# Cảnh báo mâu thuẫn dữ liệu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (người dùng không muốn giao subagent). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dò mâu thuẫn trong dữ liệu một dự án (tài liệu với tài liệu, tài liệu với trường đã điền), lưu thành cảnh báo, và báo người dùng bằng popup.

**Architecture:** Job `kb_conflict_check` chạy sau job nạp: lấy đoạn của bản ghi vừa đổi từ Qdrant, lọc đoạn có dữ kiện, tìm ứng viên tương đồng cùng dự án, bỏ cặp đã phán, gộp nhóm gửi LLM (qwen flash qua `WebLlm`), kiểm trích dẫn rồi ghi vào một bảng `tenant_data.data_conflicts`. API nằm trong router `kb`. Frontend có một popup dùng chung, mở từ icon ở màn Kiến thức, icon ở màn dự án, và tự bật sau khi lưu.

**Tech Stack:** Python 3.13, asyncpg, alembic, qdrant-client (AsyncQdrantClient), httpx, FastAPI, pytest + testcontainers; React 19, TanStack Query/Router, Vitest + MSW, Lucide.

**Spec:** [`specs/2026-10-14-canh-bao-mau-thuan-du-lieu-design.md`](../specs/2026-10-14-canh-bao-mau-thuan-du-lieu-design.md)

## Global Constraints

- Nhánh duy nhất: `feat/data-conflicts`, worktree `~/Desktop/data-conflicts/odyssey-portal-backend` và `~/Desktop/data-conflicts/odyssey-portal-frontend`. Không tạo nhánh khác.
- Tự commit sau mỗi task, message tiếng Anh một dòng, không credit Claude. Không push, không mở MR.
- Định danh trong code tiếng Anh; tiếng Việt chỉ ở comment, docstring và tên test. Comment ít.
- Không sửa `CLAUDE.md`; dòng Change Log đề xuất ghi vào báo cáo cuối.
- Tham số: top-k `3`, ngưỡng tương đồng `0.75`, nhóm `8` đoạn, trường văn xuôi cắt ở `3000` ký tự.
- Job kind `kb_conflict_check`, `purpose = 'conflict_check'` (tính tiền khách).
- Trạng thái cảnh báo: `open`, `dismissed`, `resolved`, `none`.
- Quyền: đọc `catalog.read`, quét và bỏ qua `catalog.write`.
- Frontend: icon `mauThuan` = Lucide `TriangleAlert`, cao bằng nút cùng hàng; nhóm dự án trong popup mặc định thu gọn; không thêm route hay mục menu; sửa ít nhất có thể vào `KhungDuAn.tsx` (cây frontend gốc đang sửa dở file này).
- Lệnh test backend: `uv run pytest <path> -q` (cần Docker). Frontend: `npx vitest run <file>`, `npm run build`.
- Baseline đo ngày 2026-10-14 trên `develop`: frontend build xanh, `vitest` xanh (lần chạy riêng). Backend: xem Task 0.

---

## Phase 0 — Chuẩn bị (đã làm)

### Task 0: Worktree và baseline

- [x] Fetch cả ba repo; agent không cần sửa.
- [x] Tạo worktree hai repo trên `feat/data-conflicts` từ `origin/develop` (backend `ba61b9e`, frontend `743b73a`), bỏ upstream.
- [x] Chép `.env`; `uv sync`; `node_modules` hardlink từ cây gốc (lockfile giống hệt).
- [x] Commit spec (`1e245cb`).
- [x] Baseline frontend: build xanh, vitest xanh.
- [ ] Baseline backend: `uv run pytest tests/unit tests/isolation tests/modules/kb tests/api -q`; ghi số vào báo cáo cuối.

---

## Phase 1 — Backend

### Task 1: Migration bảng `data_conflicts` và nhãn billing

**Files:**
- Create: `migrations/versions/0981_data_conflicts.py` (`revision = "0981_data_conflicts"`, `down_revision = "0980_hop_nhat_hai_head"`)
- Modify: `tests/isolation/test_isolation_catalog.py` chỉ khi cổng đòi khai bảng mới (bảng `tenant_data` có `enforce_tenant_isolation` thì không cần)
- Test: `tests/modules/kb/conflicts/test_schema.py`

**Interfaces:**
- Produces: bảng `tenant_data.data_conflicts` với các cột ở spec §5; hàng `billing.purpose('conflict_check', true, …)`.

- [ ] **Step 1: Test thất bại**

```python
# tests/modules/kb/conflicts/test_schema.py
import asyncpg
import pytest
from portal.core.db.session import tenant_conn

async def test_bang_ton_tai_va_bat_rls(pool):
    async with pool.acquire() as c:
        r = await c.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'tenant_data.data_conflicts'::regclass"
        )
    assert r["relrowsecurity"] and r["relforcerowsecurity"]

async def test_mot_cap_mot_hang(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        sql = ("INSERT INTO tenant_data.data_conflicts (tenant_id, project_code, left_hash, right_hash, status)"
               " VALUES (portal.current_tenant(), 'p1', 'a', 'b', 'none')")
        await c.execute(sql)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(sql)

async def test_status_ngoai_danh_sach_bi_chan(pool, seed_conflict_tenant):
    async with tenant_conn(pool, seed_conflict_tenant) as c:
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(
                "INSERT INTO tenant_data.data_conflicts (tenant_id, project_code, left_hash, right_hash, status)"
                " VALUES (portal.current_tenant(), 'p1', 'a', 'c', 'xxx')"
            )

async def test_nhan_billing_tinh_tien(pool):
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT billable FROM billing.purpose WHERE code = 'conflict_check'") is True
```

Fixture `seed_conflict_tenant` (trong `tests/modules/kb/conflicts/conftest.py`): tạo `control.tenants` id `cf_conflict`, xoá khi xong.

- [ ] **Step 2: Chạy, thấy đỏ** — `uv run pytest tests/modules/kb/conflicts/test_schema.py -q` → bảng không tồn tại.

- [ ] **Step 3: Migration**

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_data.data_conflicts (
          id bigserial PRIMARY KEY,
          tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
          project_code text NOT NULL,
          left_hash text NOT NULL,
          right_hash text NOT NULL,
          status text NOT NULL CHECK (status IN ('open','dismissed','resolved','none')),
          summary text NOT NULL DEFAULT '',
          left_entity text, left_record_id bigint, left_field text, left_label text, left_quote text,
          right_entity text, right_record_id bigint, right_field text, right_label text, right_quote text,
          created_at timestamptz NOT NULL DEFAULT now(),
          resolved_at timestamptz, dismissed_at timestamptz, dismissed_by text,
          UNIQUE (tenant_id, left_hash, right_hash)
        )""")
    op.execute("CREATE INDEX data_conflicts_project_status ON tenant_data.data_conflicts (tenant_id, project_code, status)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data', 'data_conflicts')")
    op.execute("""INSERT INTO billing.purpose (code, billable, note) VALUES
      ('conflict_check', true, 'dò mâu thuẫn dữ liệu dự án — tính năng khách dùng')
      ON CONFLICT (code) DO NOTHING""")

def downgrade() -> None:
    op.execute("DELETE FROM billing.purpose WHERE code = 'conflict_check'")
    op.execute("DROP TABLE tenant_data.data_conflicts")
```

Kiểm chữ ký thật của `control.enforce_tenant_isolation` trong migration `0913` trước khi gọi; dùng đúng chữ ký đó.

- [ ] **Step 4: Xanh** — test trên, cộng `uv run pytest tests/isolation tests/unit/test_alembic_mot_head.py -q`.
- [ ] **Step 5: Commit** — `feat(kb): add data_conflicts table and conflict_check billing purpose`

### Task 2: Hàm thuần — dữ kiện, dấu tay, trích dẫn

**Files:**
- Create: `src/portal/modules/kb/conflicts/__init__.py`, `src/portal/modules/kb/conflicts/facts.py`
- Test: `tests/unit/test_conflict_facts.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str` — gộp khoảng trắng, hạ chữ thường, bỏ `*`/`_` markdown.
  - `has_checkable_fact(text: str) -> bool`
  - `chunk_hash(text: str) -> str` — `"c:" + sha256(normalize(text))[:32]`
  - `field_hash(entity: str, record_id: int, field: str, value: str) -> str` — `"f:" + sha256(f"{entity}.{record_id}.{field}={normalize(value)}")[:32]`
  - `block_hash(hashes: Iterable[str]) -> str` — `"b:" + sha256("|".join(sorted(hashes)))[:32]`
  - `ordered(a: str, b: str) -> tuple[str, str]`
  - `quote_found(quote: str, source: str) -> bool` — `normalize(quote)` khác rỗng, dài ≥ 4 và nằm trong `normalize(source)`.

- [ ] **Step 1: Test thất bại**

```python
from portal.modules.kb.conflicts.facts import (
    block_hash, chunk_hash, field_hash, has_checkable_fact, ordered, quote_found)

def test_doan_co_so_lieu_thi_kiem_duoc():
    assert has_checkable_fact("Chiết khấu 2% khi thanh toán đúng hạn")
    assert has_checkable_fact("Hiệu lực đến hết 30/11/2026")
    assert has_checkable_fact("Chủ đầu tư: Công ty Cổ phần Kinh doanh Bất động sản Noble")
    assert has_checkable_fact("Quyết định số 1499/QĐ-UBND")

def test_van_quang_cao_khong_kiem():
    assert not has_checkable_fact("Không gian sống đẳng cấp, hài hoà cùng thiên nhiên.")

def test_dau_tay_khong_doi_theo_khoang_trang_va_chu_hoa():
    assert chunk_hash("Chiết  khấu 2%") == chunk_hash("chiết khấu 2%")
    assert chunk_hash("a").startswith("c:")

def test_dau_tay_truong_gan_dung_truong():
    assert field_hash("projects", 1, "investor", "Noble") != field_hash("projects", 1, "region", "Noble")

def test_dau_tay_khoi_khong_phu_thuoc_thu_tu():
    assert block_hash(["f:1", "f:2"]) == block_hash(["f:2", "f:1"])

def test_cap_xep_thu_tu():
    assert ordered("c:b", "c:a") == ("c:a", "c:b")

def test_trich_dan_phai_co_that():
    src = "Hiệu lực: từ 17/07/2026 đến hết **30/11/2026**"
    assert quote_found("đến hết 30/11/2026", src)
    assert not quote_found("đến hết 31/12/2026", src)
    assert not quote_found("  ", src)
```

- [ ] **Step 2: Đỏ** — `uv run pytest tests/unit/test_conflict_facts.py -q`.
- [ ] **Step 3: Cài đặt** — regex dữ kiện: chữ số (`\d`), `%`, đơn vị tiền/diện tích (`tỷ|triệu|đồng|vnd|m²|m2|ha`), tên tổ chức (`công ty|tập đoàn|ctcp|tnhh`), số văn bản (`\bsố\s*\d|/qđ|/tb|/ubnd`). Không phân biệt hoa thường, chạy trên `normalize`.
- [ ] **Step 4: Xanh.**
- [ ] **Step 5: Commit** — `feat(kb): add pure helpers for conflict detection`

### Task 3: Khối trường của dự án

**Files:**
- Create: `src/portal/modules/kb/conflicts/fields.py`
- Test: `tests/modules/kb/conflicts/test_fields.py`

**Interfaces:**
- Consumes: `facts.field_hash`, `facts.block_hash`; `REAL_ESTATE` (`directive/verticals/real_estate.py`).
- Produces:
  - `@dataclass(frozen=True) FieldValue(entity: str, record_id: int, field: str, label: str, value: str, hash: str)`; `ref` = `f"field:{entity}.{record_id}.{field}"`.
  - `async def load_fields(conn, project_code: str) -> list[FieldValue]` — đọc `projects` (một hàng), `zones`, `buildings` của dự án; chỉ các cột khai trong `fields` của spec tương ứng (projects: `EntitySpec.fields`; zones: `child_block.fields`; buildings: `BUILDINGS.fields`); bỏ giá trị rỗng/NULL; nhãn từ `field_labels`, thiếu nhãn thì `overview` → «Tổng quan», còn lại dùng tên cột; với zone/building thêm tiền tố tên («Phân khu Riviera · Quy mô»); `value_labels` áp như khi dựng văn bản cho agent; giá trị cắt ở 3000 ký tự; jsonb (`handover_standard`) qua đúng formatter của spec.
  - `def render_block(fields: list[FieldValue]) -> str` — mỗi dòng `[{ref}] {label}: {value}`.
  - `def fields_block_hash(fields) -> str` = `block_hash(f.hash for f in fields)`.

- [ ] **Step 1: Test thất bại** — seed một dự án (`investor='Noble'`, `product_scale='172 sản phẩm · 4,3 ha'`, `overview` dài 5000 ký tự), một phân khu (`product_scale='98 sản phẩm'`), một toà (`num_floors=25`). Khẳng định: có `FieldValue` `projects.<id>.investor` nhãn «Chủ đầu tư»; overview dài đúng 3000; phân khu có nhãn bắt đầu bằng tên phân khu; trường NULL không xuất hiện; `render_block` chứa `[field:projects.<id>.investor] Chủ đầu tư: Noble`; đổi `investor` thì `fields_block_hash` đổi.
- [ ] **Step 2: Đỏ.**
- [ ] **Step 3: Cài đặt** (SQL qua `tenant_conn` của caller, mọi câu có `tenant_id = portal.current_tenant()`).
- [ ] **Step 4: Xanh** — kèm `uv run pytest tests/isolation -q` (cổng đọc literal SQL).
- [ ] **Step 5: Commit** — `feat(kb): build the filled-in field block for conflict checks`

### Task 4: Qdrant — lấy đoạn kèm vector và tìm đoạn tương đồng

**Files:**
- Modify: `src/portal/modules/kb/index/store.py`
- Test: `tests/modules/kb/test_store_qdrant.py` (thêm bài)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) VectorPoint(point_id: str, record_id: int, doc_type: str, text: str, project_name: str, vector: list[float] | None, score: float = 0.0)`
  - `QdrantStore.points_with_vectors(name, *, anchor_code: str, record_id: int | None = None, doc_types: Collection[str] = ()) -> list[VectorPoint]` — scroll lọc `project_id`, tuỳ chọn `record_id`, `doc_type` (MatchAny); `with_vectors=["dense"]`. Collection không tồn tại → `[]`.
  - `QdrantStore.similar(name, *, vector, anchor_code, exclude_record_id: int | None, doc_types: Collection[str], limit: int, min_score: float) -> list[VectorPoint]` — `query_points(using="dense", query=vector, query_filter=..., limit=..., score_threshold=min_score, with_payload=True)`; lọc `must_not record_id` khi có.

- [ ] **Step 1: Test thất bại** — upsert 3 point cùng `project_id='p'` (hai `csbh` record 1 và 2, một `tong_quan` record 9) và 1 point `project_id='q'`, vector gần nhau cho point record 1/2; khẳng định `points_with_vectors(..., record_id=1)` trả đúng 1 point có vector dài 1024; `similar(vector của record 1, exclude_record_id=1, doc_types={'csbh','tong_quan'})` không trả record 1, không trả point dự án `q`, sắp theo điểm giảm dần; ngưỡng cao hơn điểm thật thì rỗng.
- [ ] **Step 2: Đỏ.**
- [ ] **Step 3: Cài đặt.** `text` lấy từ payload rồi bóc tiền tố bằng `tach_tien_to(text, project_name)` (giữ phần thân nếu bóc được).
- [ ] **Step 4: Xanh** — `uv run pytest tests/modules/kb/test_store_qdrant.py -q`.
- [ ] **Step 5: Commit** — `feat(kb): read vectors and search similar chunks within a project`

### Task 5: Prompt và đọc kết quả LLM

**Files:**
- Modify: `src/portal/modules/kb/prompts.yaml` (profile `conflict_check`, `model: qwen3.7-flash`, `max_tokens: 1500`, `temperature: 0`)
- Create: `src/portal/modules/kb/conflicts/llm.py`
- Test: `tests/unit/test_conflict_llm.py`

**Interfaces:**
- Produces:
  - `PROFILE = "conflict_check"`
  - `@dataclass(frozen=True) Item(ref: str, label: str, text: str)` (ref `D1…`, `C1…`)
  - `@dataclass(frozen=True) Finding(summary: str, left_ref: str, left_quote: str, right_ref: str, right_quote: str)`
  - `def build_user_text(block: str, items: list[Item], candidates: list[Item]) -> str` — thứ tự cố định: khối trường trước (`## Trường đã điền`), rồi `## Đoạn cần kiểm` (D), rồi `## Đoạn đối chiếu` (C); mỗi đoạn `[D1] <nhãn>\n<chữ>`.
  - `def parse_findings(raw: dict, *, valid_refs: set[str]) -> list[Finding]` — bỏ mục thiếu khoá, ref lạ, hai phía cùng ref, hoặc không có phía nào là `D…`; chuẩn hoá để phía trái luôn là `D…`.

Prompt hệ thống (tiếng Việt), yêu cầu đúng bốn điều ở spec §4.4 và định dạng `{"conflicts":[{"summary","left":{"ref","quote"},"right":{"ref","quote"}}]}`; không có mâu thuẫn thì `{"conflicts": []}`.

- [ ] **Step 1: Test thất bại** — `build_user_text` đặt khối trường trước đoạn D; `parse_findings` giữ mục hợp lệ, bỏ mục `ref` lạ, đảo phía khi trái là `C2` phải là `D1`, bỏ mục `C1` với `C2`; `raw` không có `conflicts` → `[]`.
- [ ] **Step 2: Đỏ.** **Step 3: Cài đặt.** **Step 4: Xanh** (`tests/unit/test_conflict_llm.py`, `tests/modules/kb/test_prompts.py`).
- [ ] **Step 5: Commit** — `feat(kb): add the conflict-check prompt and result parser`

### Task 6: Repo cảnh báo

**Files:**
- Create: `src/portal/modules/kb/conflicts/repo.py`
- Test: `tests/modules/kb/conflicts/test_repo.py`

**Interfaces:**
- Produces (mọi câu SQL mang `tenant_id = portal.current_tenant()`):
  - `@dataclass(frozen=True) Side(entity: str | None, record_id: int | None, field: str | None, label: str, quote: str)`
  - `@dataclass(frozen=True) Row(project_code: str, left_hash: str, right_hash: str, status: str, summary: str = "", left: Side | None = None, right: Side | None = None)`
  - `async def judged_pairs(conn, pairs: Collection[tuple[str, str]]) -> set[tuple[str, str]]`
  - `async def insert_rows(conn, rows: list[Row]) -> int` — `ON CONFLICT DO NOTHING`, trả số hàng `open` ghi được.
  - `async def resolve_stale(conn, project_code: str, current: set[str]) -> int` — `open` có `left_hash` hoặc `right_hash` ∉ `current` → `resolved`, `resolved_at = now()`.
  - `async def drop_stale_none(conn, project_code: str, current: set[str]) -> int`
  - `async def list_open(conn, project_code: str, since: datetime | None = None) -> list[asyncpg.Record]` — sắp `created_at DESC`.
  - `async def summary(conn) -> list[asyncpg.Record]` — `project_code, name, open, checking, failed` (join `projects` lấy tên; `checking` = có job `kb_conflict_check` `queued|running` của dự án; `failed` = job `kb_conflict_check` mới nhất của dự án ở `failed`); chỉ dự án `open > 0` hoặc `checking`.
  - `async def check_status(conn, project_code: str) -> tuple[bool, bool]` — `(checking, failed)`; `checking` xét job `queued|running` thuộc `kb_index|kb_thumb|kb_enrich|kb_caption|kb_conflict_check` có `payload->>'project_code' = $1`.
  - `async def dismiss(conn, conflict_id: int, user_id: str) -> asyncpg.Record | None` — chỉ từ `open`.

- [ ] **Step 1: Test thất bại** — chèn hai hàng trùng cặp chỉ ghi một; `judged_pairs` trả đúng cặp đã có, kể cả `dismissed`; `resolve_stale` đóng hàng có hash ngoài tập hiện tại và không đụng `dismissed`; `dismiss` không mở lại được bằng `insert_rows` cùng cặp; `summary` không đếm `none`, `resolved`; tenant khác không thấy hàng (`tenant_conn` hai tenant).
- [ ] **Step 2: Đỏ.** **Step 3: Cài đặt.** **Step 4: Xanh** + `uv run pytest tests/isolation -q`.
- [ ] **Step 5: Commit** — `feat(kb): add the data_conflicts repository`

### Task 7: Lượt dò

**Files:**
- Create: `src/portal/modules/kb/conflicts/service.py`, `src/portal/modules/kb/conflicts/settings.py`
- Test: `tests/modules/kb/conflicts/test_service.py`

**Interfaces:**
- Consumes: Task 2–6.
- Produces:
  - `settings.TOP_K = 3`, `MIN_SCORE = 0.75`, `BATCH = 8`, `DOC_TYPES = frozenset({"csbh", "phap_ly", "huong_dan", "khac"})` (suy từ `TITLE_PREFIXES` + `DEFAULT_DOC_TYPE`), `FIELD_ANCHOR = "tong_quan"`.
  - `class Asker(Protocol): async def ask(self, profile: str, user_text: str) -> dict`
  - `@dataclass CheckResult(sent: int, opened: int, resolved: int)`
  - `async def check_record(conn, *, store: QdrantStore, llm: Asker, collection: str, project_code: str, entity: str, record_id: int) -> CheckResult` — `entity` là `documents` hoặc `projects`.
  - `async def check_project(conn, *, store, llm, collection, project_code) -> CheckResult` — mọi tài liệu của dự án rồi phía trường; cuối cùng `drop_stale_none`.

Thuật toán đúng spec §4.3:
1. `current` = dấu tay mọi đoạn `DOC_TYPES` của dự án + dấu tay từng trường + dấu tay khối; `resolve_stale`.
2. `documents`: đoạn của bản ghi; `projects`: với mỗi point `tong_quan` của dự án, `similar` trong `DOC_TYPES` → các đoạn tài liệu (khử trùng).
3. Lọc `has_checkable_fact`.
4. Với đoạn tài liệu của chính bản ghi: `similar(..., exclude_record_id=record_id, doc_types=DOC_TYPES | {FIELD_ANCHOR})`; hit tài liệu → cặp đoạn–đoạn; có hit `tong_quan` → cặp đoạn–khối. Với nhánh `projects`: mỗi đoạn chỉ có cặp đoạn–khối.
5. `judged_pairs` → bỏ cặp đã phán; đoạn không còn cặp nào thì bỏ.
6. Gộp `BATCH` đoạn; ứng viên trùng gửi một lần; khối trường luôn kèm. `parse_findings`; lỗi JSON (`ValueError`, `TruncatedLlmError`) → chia đôi nhóm thử lại một lần, vẫn lỗi thì ném.
7. Kiểm trích dẫn: phía `D`/`C` so với chữ đoạn; phía `field:` so với giá trị trường. Sai thì bỏ, đếm vào log.
8. Ghi: cặp đoạn–đoạn đã gửi → `open` (có finding hợp lệ) hoặc `none`; cặp đoạn–khối → `none` cho `(đoạn, khối)` + `open` cho `(đoạn, field_hash)` mỗi trường có finding. Nhãn phía tài liệu = tiêu đề tài liệu (`documents.title`), phía trường = `FieldValue.label`.

- [ ] **Step 1: Test thất bại** (Qdrant thật, LLM giả ghi lại các lần gọi và trả kết quả soạn sẵn; vector soạn tay để hai đoạn CSBH gần nhau):
  - hai CSBH lệch ngày → một cảnh báo `open` đúng hai đoạn trích, `summary` từ LLM;
  - chạy lại không gọi LLM lần nào;
  - finding có trích dẫn bịa → không có cảnh báo, cặp vẫn ghi `none`;
  - đoạn văn quảng cáo không chữ số → không gửi LLM;
  - finding với `field:projects.<id>.investor` → cảnh báo phía phải mang `right_field='investor'`, nhãn «Chủ đầu tư»;
  - đoạn lệch hai trường → hai cảnh báo;
  - sửa trường `investor` rồi `check_record(entity='projects')` → cảnh báo cũ `resolved`;
  - `dismissed` giữ nguyên sau `check_project`;
  - LLM trả JSON hỏng hai lần → ném, không có hàng nào được ghi (giao dịch của test rollback).
- [ ] **Step 2: Đỏ.** **Step 3: Cài đặt.** **Step 4: Xanh** + `uv run pytest tests/isolation -q`.
- [ ] **Step 5: Commit** — `feat(kb): detect data conflicts for a record or a whole project`

### Task 8: Job, kích hoạt sau khi nạp, đếm chi phí

**Files:**
- Modify: `src/portal/modules/kb/web/usage.py` — `flush(..., purpose: str = PURPOSE, channel: str = CHANNEL)`; `metered(handler=None, *, purpose=PURPOSE, channel=CHANNEL, session_prefix=JOB_SESSION_PREFIX)` dùng được cả dạng `@metered` cũ lẫn `metered(purpose=...)`.
- Create: `src/portal/modules/kb/conflicts/jobs.py`, `src/portal/modules/kb/conflicts/enqueue.py`
- Modify: `src/portal/modules/kb/jobs.py` (`handle_index` xếp job dò), `src/portal/worker/__main__.py` (`load_handlers` import `portal.modules.kb.conflicts.jobs`)
- Test: `tests/modules/kb/conflicts/test_jobs.py`, `tests/modules/kb/web/test_usage*.py` hiện có phải xanh

**Interfaces:**
- Produces:
  - `KIND_CONFLICT_CHECK = "kb_conflict_check"` (trong `conflicts/enqueue.py`)
  - `async def queue_check(conn, *, tenant_id, actor, project_code, entity: str | None = None, record_id: int | None = None) -> int | None` — gộp khi đã có job `queued` cùng `project_code` + `entity` + `record_id`; job phạm vi dự án (entity None) gộp mọi job bản ghi đang chờ của dự án đó.
  - Handler `handle_conflict_check(conn, payload) -> JobResult`, đăng ký `register(KIND_CONFLICT_CHECK, metered(handle_conflict_check, purpose="conflict_check", channel="kb_conflict", session_prefix="kbconflict-job:"), retries=RETRY_VIEC_KB, max_concurrency=2)`.
  - Handler dựng `WebLlm(base_url=env.vlm_base_url, api_key=env.vlm_api_key, concurrency=2)` và `QdrantStore` từ cấu hình, đóng cả hai trong `finally`.

- [ ] **Step 1: Test thất bại**
  - `handle_index` nạp tài liệu có ghi point → có hàng `control.jobs` `kb_conflict_check` đúng `entity/record_id/project_code`;
  - nạp báo «nội dung không đổi» → không có;
  - nạp media → không có;
  - `queue_check` hai lần liên tiếp → một job;
  - handler với LLM giả ghi `billing.usage_events` có `purpose='conflict_check'` (kiểm `channel` có ràng buộc CHECK nào không trước khi chọn `kb_conflict`; có thì thêm giá trị vào migration Task 1 hoặc dùng giá trị được phép).
- [ ] **Step 2: Đỏ.** **Step 3: Cài đặt.** **Step 4: Xanh** — `tests/modules/kb`, `tests/modules/test_worker.py`.
- [ ] **Step 5: Commit** — `feat(kb): run conflict checks after indexing and meter their cost`

### Task 9: API

**Files:**
- Create: `src/portal/modules/kb/conflicts/contracts.py`, `src/portal/modules/kb/conflicts/router.py`
- Modify: `src/portal/modules/kb/router.py` (`ROUTER.include_router(CONFLICTS_ROUTER)`), `src/portal/core/nhat_ky_ma.py` (thêm `conflict.scan`, `conflict.dismiss`), `contracts/audit-actions.json` (qua `make contracts`)
- Test: `tests/modules/kb/conflicts/test_router.py`

**Interfaces:**
- Produces (camelCase, khớp spec §6):
  - `ConflictSideOut(entity, recordId, field, label, quote)`, `ConflictOut(id, summary, createdAt, left, right)`
  - `ConflictSummaryOut(projectCode, name, open, checking, failed)`
  - `ConflictCheckOut(checking, failed, conflicts: list[ConflictOut])`
  - `GET /conflicts/summary` → `list[ConflictSummaryOut]`
  - `GET /projects/{code}/conflicts` → `list[ConflictOut]`
  - `GET /projects/{code}/conflicts/check?since=<ISO>` → `ConflictCheckOut`
  - `POST /projects/{code}/conflicts/scan` → 202 `{"jobId": int | null}`
  - `POST /conflicts/scan` → 202 `{"queued": int}` (mọi dự án trừ `__ALL__`)
  - `POST /conflicts/{id}/dismiss` → 204; không phải `open` hoặc không thuộc tenant → 404

- [ ] **Step 1: Test thất bại** (dùng `client_cfg`): hình dạng từng endpoint; `summary` chỉ có dự án có `open`; `dismiss` xong biến khỏi danh sách và `summary`; `scan` ghi nhật ký `conflict.scan`; `dismiss` ghi `conflict.dismiss`; user chỉ có `catalog.read` gọi `scan` → 403 (theo khuôn test quyền sẵn có của `realestate`).
- [ ] **Step 2: Đỏ.** **Step 3: Cài đặt** + `make contracts`.
- [ ] **Step 4: Xanh** — `tests/modules/kb/conflicts`, `tests/api`, `tests/unit/test_nhat_ky_ma.py`, cổng «mọi route khai action».
- [ ] **Step 5: Commit** — `feat(kb): expose data conflict endpoints`

### Task 10: Kiểm toàn backend

- [ ] `uv run ruff check src tests && uv run ruff format --check src tests`
- [ ] `uv run pytest tests/unit tests/isolation tests/modules/kb tests/api tests/modules/test_worker.py -q`; so với baseline Task 0.
- [ ] Sửa lỗi nếu có, commit riêng.

---

## Phase 2 — Frontend

### Task 11: API client, kiểu dữ liệu, icon

**Files:**
- Create: `src/features/conflicts/api.ts`
- Modify: `src/components/icons.tsx` (khoá `mauThuan` → Lucide `TriangleAlert`, đúng quy ước độ dày nét của tệp), `src/lib/audit-actions` hoặc tệp tương ứng nhận `contracts/audit-actions.json` mới (chép từ backend) + `so-hanh-dong.ts` thêm nhãn `conflict.scan` «Kiểm tra mâu thuẫn», `conflict.dismiss` «Bỏ qua mâu thuẫn»
- Test: `tests/conflicts-api.test.ts`, `tests/audit-actions-parity.test.ts` phải xanh

**Interfaces:**
- Produces: kiểu `Conflict`, `ConflictSide`, `ConflictSummary`, `ConflictCheck`; hàm `conflictSummary()`, `projectConflicts(code)`, `checkConflicts(code, since: string)`, `scanProject(code)`, `scanAll()`, `dismissConflict(id)` — đều qua `goi` của `@/lib/http`, đường dẫn `/kb/...` theo tiền tố router `kb` (kiểm tiền tố thật trước khi viết).

- [ ] Test (MSW) gọi đúng đường dẫn và phương thức → đỏ → cài đặt → xanh → commit `feat(conflicts): add API client and warning icon`.

### Task 12: Popup dùng chung

**Files:**
- Create: `src/features/conflicts/ConflictItem.tsx`, `src/features/conflicts/ConflictDialog.tsx`
- Test: `tests/conflicts-dialog.test.tsx`

**Interfaces:**
- Produces: `ConflictDialog` props `{ mode: { kind: 'workspace' } | { kind: 'project'; code: string; name: string } | { kind: 'afterSave'; code: string; conflicts: Conflict[] }; onClose: () => void }`.

Hành vi (mockup bản 7):
- `workspace`: tiêu đề «Mâu thuẫn dữ liệu» + tổng; nút «Kiểm tra tất cả dự án» qua `XacNhan` («Kiểm tra N dự án? Lần đầu có thể mất vài phút»); mỗi dự án một hàng thu gọn mặc định (mũi tên, tên, «N mâu thuẫn», link «Kiểm tra» hoặc «Đang kiểm tra…»); mở hàng thì gọi `projectConflicts`.
- `project`: tiêu đề «Mâu thuẫn · <tên>» + số; nút «Kiểm tra» ở đầu; `failed` → dòng «Lần kiểm tra gần nhất bị lỗi».
- `afterSave`: tiêu đề «Bản ghi vừa lưu có N mâu thuẫn»; nút «Để sau».
- Mục: tóm tắt; hai dòng nguồn (chỗ lấy, «Mở», trích dẫn); «Không phải mâu thuẫn» gọi `dismissConflict` rồi bỏ mục khỏi danh sách và làm mới `summary`.
- «Mở» đóng popup, điều hướng `/pform?code=<code>&tab=<tab>` với `documents → tai-lieu`, `projects → tong-quan`, `zones → phan-khu`, `buildings → toa`. Mở đúng tài liệu hoặc trỏ đúng ô trường để lần sau (spec §7 ghi rõ).

- [ ] Test: nhóm mặc định thu gọn, bấm thì hiện mục; «Kiểm tra tất cả dự án» hỏi xác nhận rồi gọi `scanAll`; «Không phải mâu thuẫn» gọi đúng id và mục biến mất; «Mở» điều hướng đúng tab → đỏ → cài đặt → xanh → commit `feat(conflicts): add the shared conflict dialog`.

### Task 13: Icon ở hai màn và tự bật sau khi lưu

**Files:**
- Create: `src/features/conflicts/ConflictButton.tsx` (nút icon + số + chấm đang kiểm tra), `src/features/conflicts/useConflictWatch.ts`
- Modify: `src/features/realestate/components/DuAnList.tsx` (nút ở thanh công cụ trước «Nạp qua API»; chữ «N mâu thuẫn» cạnh tên dòng), `src/features/realestate/components/KhungDuAn.tsx` (một dòng: nút trong cụm góc phải trên, trước `StatusChip`)
- Test: `tests/conflicts-watch.test.tsx`

**Interfaces:**
- Produces: `useConflictWatch(code: string)` — hỏi `checkConflicts(code, since)` định kỳ khi màn dự án mở (3 giây khi `checking`, 15 giây khi rảnh); có cảnh báo mới → `fresh` để mở `ConflictDialog` dạng `afterSave`, mốc dời lên cảnh báo mới nhất. Trả `{ checking, failed, fresh, clear }`. (Đổi lúc thi công: các tab tự lưu không qua `useMutation`, xem spec §7.)

- [ ] Test (fake timers + MSW): mutation thành công → gọi `check`; `checking=false` không cảnh báo → dừng, không popup; có cảnh báo → popup; quá 3 phút → dừng; nút màn Kiến thức hiện tổng từ `summary`; nút màn dự án có chấm khi `checking` → đỏ → cài đặt → xanh → commit `feat(conflicts): show conflict icons and open the dialog after saving`.

### Task 14: Kiểm toàn frontend

- [ ] `npm run build`
- [ ] `npx vitest run` (chạy riêng, không song song với test backend); so với baseline.
- [ ] Sửa lỗi nếu có, commit riêng.

---

## Phase 3 — Kết thúc

### Task 15: Báo cáo

- [ ] `git log --oneline origin/develop..HEAD` cho cả hai worktree.
- [ ] Báo cáo: số test trước/sau, giới hạn còn lại («Mở» chỉ tới tab), dòng Change Log đề xuất cho `CLAUDE.md` backend (không tự sửa), việc người dùng cần làm: push hai nhánh, mở MR, chạy migration `0981` trên môi trường đích.
