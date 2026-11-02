# Nạp kiến thức cho agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Người dùng bấm một nút để nạp dữ liệu dự án lên Qdrant (hai lựa chọn: chỉ phần đã đổi / toàn bộ), thấy badge trạng thái từng dự án, và thấy mô tả tự động hiện lên ngay để sửa.

**Architecture:** Hai chặng tách rời giữ nguyên như hiện tại — `kb_enrich` (tự động, ghi Aurora) và `kb_index` (người bấm, ghi Qdrant). Đợt này thêm: phép thoát sớm theo `content_hash` cho chế độ delta, cột `project_code` trên `kb_index_state` để cascade và badge đọc được sau khi row nguồn đã bị `ON DELETE CASCADE` xoá, một endpoint trạng thái toàn tenant, và UI ở hai chỗ (danh sách dự án + header trang chi tiết).

**Tech Stack:** Python 3.13 · asyncpg thô · alembic · pytest + testcontainers · React + TanStack Query + TanStack Router · vitest + MSW

Spec: [docs/superpowers/specs/2026-08-11-nap-kien-thuc-cho-agent-design.md](../specs/2026-08-11-nap-kien-thuc-cho-agent-design.md)

## Global Constraints

- **Bốn luật của repo.** (1) Mọi truy vấn `tenant_data` đi qua `tenant_conn()` trong một giao dịch **và** tự mang vị từ `tenant_id = portal.current_tenant()`. (2) Bảng mới gọi `control.enforce_tenant_isolation()` — đợt này không tạo bảng nào. (3) Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. (4) Mọi endpoint khai `action` qua `require(action)`.
- **Bất đồng bộ toàn tuyến.** Endpoint chỉ `INSERT` vào `control.jobs` rồi trả `202`; không endpoint nào chờ Qdrant/model. Worker dùng `AsyncQdrantClient` và `httpx.AsyncClient`. CPU nặng qua `asyncio.to_thread`. FE: `useMutation` + poll **có điều kiện dừng tường minh**, không timer chạy nền vô hạn.
- **Định danh tiếng Anh cho code Python mới** (`project_status`, `saved_hash`, `mark_skipped`, `indexed_of_project`, `media_ids_of_zone`). Tiếng Việt chỉ ở comment và tên test. **Component React giữ nếp repo FE là tiếng Việt** (`TheKienThuc`, `NutNapKienThuc`) — cả 30+ component hiện có đều vậy, lệch một cái gây lộn xộn hơn là nhất quán.
- **Comment thưa.** Chỉ viết comment ở chỗ lý do KHÔNG hiển nhiên từ code (vì sao chọn cách này, cái gì sẽ vỡ nếu làm khác). Không docstring cho hàm mà tên đã nói hết.
- **Không dùng từ kỹ thuật trong chuỗi người dùng đọc được**: không "index", "kho vector", "đồng bộ", "Qdrant", "embed". Dùng bộ nhãn ở Task 11.
- **Không đổi hình dạng collection Qdrant** và không đổi tên khoá payload nào — hợp đồng với repo agent.
- **Không đổi `core/auth/actions.py`** — dùng lại `CATALOG_READ`/`CATALOG_WRITE`/`CATALOG_DELETE`, nên không phải chạy `make contracts`.
- **Không sửa `CLAUDE.md`.** Nếu đợt này làm thay đổi luật/kiến trúc cần ghi vào đó, **báo lại cho người dùng** thay vì tự sửa — nhiều người cùng chỉnh file đó.
- **KHÔNG tự chạy `git commit`/`git push`.** Mỗi bước commit chỉ **in lệnh ra** cho người dùng chạy.
- Chạy test BE: `make test-module M=kb` · `uv run pytest <path> -v` · trước khi mở MR: `make check`.
- Chạy test FE (ở `/home/thanhhai/Desktop/odyssey-portal-frontend`): `npm run test -- <path>`.

---

## Cấu trúc tệp

### Backend

| Tệp | Trách nhiệm |
|---|---|
`migrations/versions/<mới>_kb_state_skipped_va_project_code.py` | 🆕 `CHECK` thêm `'skipped'` · cột `project_code` · index · backfill 4 câu |
`kb/contracts.py` | ✏️ `IndexState` thêm `'skipped'` · `IndexResult.skipped` · `MODE_DELTA`/`MODE_FULL` |
`kb/state/repo.py` | ✏️ `saved_hash()` · `mark_skipped()` · `project_status()` · `indexed_of_project()` · `save_state(project_code=…)` |
`kb/clients/rag.py` · `media.py` | ✏️ `content_hash_of()` — dựng nội dung + hash, không I/O |
`kb/fake.py` | ✏️ `FakeIndexClient.content_hash_of()` + đếm số lần `index()` |
`kb/service.py` | ✏️ `index_text`/`index_media` nhận `mode`; `delete_cascade` đọc sổ thay vì `fanout` |
`kb/jobs.py` | ✏️ `handle_index` đọc `mode`; `handle_sync_project` truyền `mode`; `handle_delete` gọi cascade mới |
`kb/ops/sync.py` · `backfill.py` | ✏️ payload job con thêm `project_code` + `mode` |
`kb/source/fanout.py` | ✏️ chỉ thêm docstring nêu giới hạn (không còn dùng ở đường cascade-khi-xoá) |
`realestate/contracts.py` | ✏️ `+ TrangThaiKbOut` |
`realestate/repo.py` | ✏️ `+ media_ids_of_zone()` |
`realestate/router.py` | ✏️ `kb-status` mới · `sync-kb` nhận `mode` · 6 route DELETE/PATCH enqueue dọn · 2 route PATCH enqueue enrich |

### Frontend

| Tệp | Trách nhiệm |
|---|---|
`realestate/api.ts` | ✏️ `TrangThaiKb` · `trangThaiKb()` · `napKienThuc()` · `taoLaiMoTa()` · `trangThaiEnrich()` |
`realestate/components/TheKienThuc.tsx` | 🆕 badge 5 trạng thái, hàm thuần, không gọi API |
`realestate/useTrangThaiKb.ts` | 🆕 hook query + poll có điều kiện |
`realestate/useTrangThaiEnrich.ts` | 🆕 hook poll enrich của một dự án |
`realestate/components/NutNapKienThuc.tsx` | 🆕 nút + menu 2 lựa chọn + hộp xác nhận |
`realestate/components/DuAnList.tsx` | ✏️ cột thứ 6 |
`realestate/components/KhungDuAn.tsx` | ✏️ badge + nút ở header |
`realestate/components/VungMedia.tsx` | ✏️ caption **sửa được** + trạng thái + nút tạo lại |
`realestate/components/OMedia.tsx` | ✏️ trạng thái + nút tạo lại; viết lại docstring |
`realestate/components/TaiLieuTab.tsx` | ✏️ trạng thái bóc chữ; viết lại docstring |
`lib/msw/handlers.ts` | ✏️ 3 handler mới |

---

# PHẦN A — BACKEND

## Task 1: Migration — `'skipped'` và `project_code`

**Files:**
- Create: `migrations/versions/<rev>_kb_state_skipped_va_project_code.py`
- Test: `tests/integration/test_migration_kb_project_code.py`

**Interfaces:**
- Consumes: bảng `tenant_data.kb_index_state` từ `0501_kb_index_state`
- Produces: cột `kb_index_state.project_code text NOT NULL DEFAULT ''`, index `kb_index_state_tenant_project_idx`, giá trị `'skipped'` hợp lệ cho cột `state`

- [ ] **Step 1: Tìm head hiện hành**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
uv run alembic heads
```

Ghi lại revision id in ra. **Phải mở file của head đó ra đọc** để lấy đúng `revision = "..."` — id khác tên file (ví dụ `0907_view_control_plane_cho_agent_dbmode.py` có `revision = "0907_view_control_plane"`).

- [ ] **Step 2: Viết test trước**

Create `tests/integration/test_migration_kb_project_code.py`:

```python
"""Migration thêm project_code — backfill phải điền đúng cho cả 4 entity."""

from portal.core.db.session import tenant_conn

TENANT = "mig_acme"


async def test_cot_project_code_ton_tai_va_state_nhan_skipped(pool):
    async with pool.acquire() as conn:
        cot = await conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'tenant_data' AND table_name = 'kb_index_state' "
            "  AND column_name = 'project_code'"
        )
        assert cot == "text"

        rang_buoc = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'kb_index_state_state_check'"
        )
        assert "skipped" in rang_buoc


async def test_ghi_duoc_state_skipped(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, org_id) VALUES ($1,$1,'noble')", TENANT)
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES ($1,'p1','Dự án 1','published')",
            TENANT,
        )
        pid = await conn.fetchval(
            "SELECT id FROM tenant_data.projects WHERE tenant_id = portal.current_tenant()"
        )
        await conn.execute(
            "INSERT INTO tenant_data.kb_index_state "
            "  (tenant_id, entity, record_id, doc_type, target, state, project_code) "
            "VALUES (portal.current_tenant(), 'projects', $1, 'tong_quan', 'documents', 'skipped', 'p1')",
            pid,
        )
        state = await conn.fetchval(
            "SELECT state FROM tenant_data.kb_index_state WHERE tenant_id = portal.current_tenant()"
        )
    assert state == "skipped"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT)
```

- [ ] **Step 3: Chạy để thấy đỏ**

Run: `uv run pytest tests/integration/test_migration_kb_project_code.py -v`
Expected: FAIL — `assert None == "text"` (chưa có cột) và `"skipped" in rang_buoc` sai.

- [ ] **Step 4: Viết migration**

Create `migrations/versions/<rev>_kb_state_skipped_va_project_code.py` (thay `<HEAD>` bằng revision đọc được ở Step 1):

```python
"""kb_index_state: state nhận 'skipped', và thêm project_code

VÌ SAO `project_code` Ở SỔ chứ không suy từ bảng nguồn: FK `projects → zones/
documents/media` là `ON DELETE CASCADE`, nên xoá một dự án làm row con biến mất
trong CÙNG giao dịch. Job cascade chạy sau ở worker mà hỏi Postgres "dự án này có
con nào" sẽ nhận về rỗng, và point của cả cây con sống mãi trong Qdrant. Sổ này
không có FK tới bảng nguồn nên dòng sổ sống sót — nó là nơi duy nhất còn biết dự
án đã từng nạp những gì.

`'skipped'` là kết quả của chế độ nạp delta: đã đọc, đã tính hash, hash trùng nên
không gọi embed. Không có giá trị này thì không phân biệt được nó với 'indexed'.

Revision ID: <rev>
Revises: <HEAD>
"""

from alembic import op

revision = "<rev>"
down_revision = "<HEAD>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.kb_index_state DROP CONSTRAINT kb_index_state_state_check")
    op.execute(
        """
        ALTER TABLE tenant_data.kb_index_state
            ADD CONSTRAINT kb_index_state_state_check
            CHECK (state IN ('queued', 'indexing', 'indexed', 'error', 'deleted', 'skipped'))
        """
    )
    op.execute("ALTER TABLE tenant_data.kb_index_state ADD COLUMN project_code text NOT NULL DEFAULT ''")
    op.execute(
        "CREATE INDEX kb_index_state_tenant_project_idx "
        "ON tenant_data.kb_index_state (tenant_id, project_code)"
    )

    # Backfill. Chạy bằng portal_migrator (superuser trong container dev, owner ở
    # môi trường thật) nên KHÔNG bị RLS — không cần set app.tenant_id.
    op.execute(
        """
        UPDATE tenant_data.kb_index_state s SET project_code = p.project_code
          FROM tenant_data.projects p
         WHERE s.entity = 'projects' AND s.record_id = p.id AND s.tenant_id = p.tenant_id
        """
    )
    for bang in ("zones", "documents", "media"):
        op.execute(
            f"""
            UPDATE tenant_data.kb_index_state s SET project_code = c.project_code
              FROM tenant_data.{bang} c
             WHERE s.entity = '{bang}' AND s.record_id = c.id AND s.tenant_id = c.tenant_id
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX tenant_data.kb_index_state_tenant_project_idx")
    op.execute("ALTER TABLE tenant_data.kb_index_state DROP COLUMN project_code")
    op.execute("ALTER TABLE tenant_data.kb_index_state DROP CONSTRAINT kb_index_state_state_check")
    op.execute(
        """
        ALTER TABLE tenant_data.kb_index_state
            ADD CONSTRAINT kb_index_state_state_check
            CHECK (state IN ('queued', 'indexing', 'indexed', 'error', 'deleted'))
        """
    )
```

- [ ] **Step 5: Áp migration và chạy test**

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_migration_kb_project_code.py -v
uv run pytest tests/unit/test_alembic_mot_head.py -v
```

Expected: cả ba PASS. Nếu `test_alembic_mot_head` đỏ thì `down_revision` trỏ sai — quay lại Step 1.

- [ ] **Step 6: In lệnh commit cho người dùng**

```bash
git add migrations/versions/ tests/integration/test_migration_kb_project_code.py
git commit -m "feat(kb): kb_index_state nhận state 'skipped' và mang project_code"
```

---

## Task 2: `contracts` và `state/repo` — nền cho phép thoát sớm

**Files:**
- Modify: `src/portal/modules/kb/contracts.py`
- Modify: `src/portal/modules/kb/state/repo.py`
- Test: `tests/modules/kb/test_state_repo_skipped.py`

**Interfaces:**
- Consumes: cột `project_code` và giá trị `'skipped'` từ Task 1
- Produces:
  - `contracts.MODE_DELTA = "delta"` · `contracts.MODE_FULL = "full"`
  - `contracts.IndexResult.skipped: bool = False`
  - `repo.saved_hash(conn, *, entity: str, record_id: int, doc_type: str) -> tuple[str, str] | None` — `(content_hash, state)`, `None` nếu chưa có dòng
  - `repo.mark_skipped(conn, *, entity: str, record_id: int, doc_type: str) -> None`
  - `repo.save_state(..., project_code: str = "")` — tham số mới, keyword-only

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_state_repo_skipped.py`:

```python
"""saved_hash / mark_skipped — nền của phép thoát sớm ở service."""

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.state import repo

from .conftest import TENANT


async def test_saved_hash_tra_none_khi_chua_co_dong(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        assert await repo.saved_hash(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh") is None


async def test_saved_hash_tra_hash_va_state(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=3, content_hash="abc123"),
            project_code="nplb",
        )
        got = await repo.saved_hash(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh")
    assert got == ("abc123", "indexed")


async def test_mark_skipped_cham_indexed_at_nhung_giu_hash_va_points(api_pool, doc_ids):
    """Chạm indexed_at là điều kiện để badge về xanh; giữ hash/points để lần sau còn so được."""
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=3, content_hash="abc123"),
            project_code="nplb",
        )
        truoc = await conn.fetchval(
            "SELECT indexed_at FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1 AND doc_type = 'csbh'",
            doc_ids["nplb"],
        )
        await repo.mark_skipped(conn, entity="documents", record_id=doc_ids["nplb"], doc_type="csbh")
        rows = await repo.read_state(conn, entity="documents", record_id=doc_ids["nplb"])

    hang = next(r for r in rows if r["doc_type"] == "csbh")
    assert hang["state"] == "skipped"
    assert hang["content_hash"] == "abc123"
    assert hang["points"] == 3
    assert hang["indexed_at"] is not None and hang["indexed_at"] >= truoc


async def test_save_state_ghi_project_code(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            project_code="nplb",
        )
        got = await conn.fetchval(
            "SELECT project_code FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            doc_ids["nplb"],
        )
    assert got == "nplb"
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_state_repo_skipped.py -v`
Expected: FAIL — `AttributeError: module 'portal.modules.kb.state.repo' has no attribute 'saved_hash'`

- [ ] **Step 3: Sửa `contracts.py`**

Trong `src/portal/modules/kb/contracts.py`, đổi dòng `IndexState`:

```python
IndexState = Literal["queued", "indexing", "indexed", "error", "deleted", "skipped"]
```

Thêm field vào `IndexResult` (sau `extracted_text`):

```python
    # Chế độ delta: đã đọc, đã tính hash, hash trùng nên không gọi embed. Khác
    # points_upserted == 0, thứ cũng xảy ra khi nội dung bị xoá trắng.
    skipped: bool = False
```

Thêm hai hằng cạnh `KIND_SYNC_PROJECT`:

```python
MODE_DELTA = "delta"
MODE_FULL = "full"
```

- [ ] **Step 4: Sửa `state/repo.py`**

Trong `_UPSERT`, thêm `project_code` vào cột và `VALUES`, và vào nhánh `DO UPDATE`:

```python
_UPSERT = """
INSERT INTO tenant_data.kb_index_state
       (tenant_id, entity, record_id, doc_type, target, state,
        content_hash, points, error, attempts, project_code, indexed_at, updated_at)
VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
        CASE WHEN $5 = 'indexed' THEN now() ELSE NULL END, now())
ON CONFLICT (tenant_id, entity, record_id, doc_type) DO UPDATE
   SET target = EXCLUDED.target,
       state = EXCLUDED.state,
       content_hash = EXCLUDED.content_hash,
       points = EXCLUDED.points,
       error = EXCLUDED.error,
       attempts = EXCLUDED.attempts,
       -- COALESCE: caller cũ không truyền project_code, và ghi '' lên giá trị đã
       -- có sẽ làm cascade và badge mất dấu record đó.
       project_code = COALESCE(NULLIF(EXCLUDED.project_code, ''), kb_index_state.project_code),
       indexed_at = EXCLUDED.indexed_at,
       updated_at = now()
RETURNING id
"""
```

Thêm tham số vào `save_state` (giữ nguyên phần còn lại của hàm, chỉ thêm `project_code` vào chữ ký và vào lời gọi `fetchval`):

```python
async def save_state(
    conn: asyncpg.Connection,
    *,
    entity: str,
    record_id: int,
    doc_type: str,
    target: Target,
    state: IndexState,
    result: IndexResult | None = None,
    error: str = "",
    attempts: int = 0,
    project_code: str = "",
) -> int:
    r = result or IndexResult()
    return await conn.fetchval(
        _UPSERT,
        entity,
        record_id,
        doc_type,
        target,
        state,
        r.content_hash,
        r.points_upserted,
        error,
        attempts,
        project_code,
    )
```

Thêm hai hàm mới (đặt ngay sau `read_state`):

```python
async def saved_hash(
    conn: asyncpg.Connection, *, entity: str, record_id: int, doc_type: str
) -> tuple[str, str] | None:
    row = await conn.fetchrow(
        "SELECT content_hash, state FROM tenant_data.kb_index_state "
        "WHERE tenant_id = portal.current_tenant() AND entity = $1 AND record_id = $2 AND doc_type = $3",
        entity,
        record_id,
        doc_type,
    )
    return (str(row["content_hash"]), str(row["state"])) if row else None


async def mark_skipped(conn: asyncpg.Connection, *, entity: str, record_id: int, doc_type: str) -> None:
    """KHÔNG chạm content_hash/points — lần nạp sau vẫn phải so được với hash cũ.

    Chạm `indexed_at` là bắt buộc: badge so `updated_at` của record với `indexed_at`,
    nên bỏ nó ra là badge báo "chưa nạp" mãi và người dùng bấm lại vô ích.
    """
    await conn.execute(
        "UPDATE tenant_data.kb_index_state SET state = 'skipped', indexed_at = now(), updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND entity = $1 AND record_id = $2 AND doc_type = $3",
        entity,
        record_id,
        doc_type,
    )
```

- [ ] **Step 5: Chạy test**

```bash
uv run pytest tests/modules/kb/test_state_repo_skipped.py -v
make test-module M=kb
```

Expected: test mới PASS, và **toàn bộ test kb cũ vẫn PASS** (`project_code` có default nên caller cũ không vỡ).

- [ ] **Step 6: In lệnh commit**

```bash
git add src/portal/modules/kb/contracts.py src/portal/modules/kb/state/repo.py tests/modules/kb/test_state_repo_skipped.py
git commit -m "feat(kb): saved_hash/mark_skipped và project_code trong sổ index"
```

---

## Task 3: `content_hash_of()` — tính hash mà không embed

**Files:**
- Modify: `src/portal/modules/kb/clients/rag.py`
- Modify: `src/portal/modules/kb/clients/media.py`
- Modify: `src/portal/modules/kb/fake.py`
- Test: `tests/modules/kb/test_content_hash_of.py`

**Interfaces:**
- Consumes: `TextDirective`/`MediaDirective` từ `contracts.py`
- Produces:
  - `RagClient.content_hash_of(directive: TextDirective) -> str`
  - `MediaClient.content_hash_of(directive: MediaDirective) -> str`
  - `FakeIndexClient.content_hash_of(directive) -> str` và `FakeIndexClient.hash_calls: int`
  - Cả ba là **đồng bộ** (thuần CPU, không I/O) — gọi không cần `await`

Ghi chú thiết kế: hash được tính **hai lần** cho record thật sự đổi (một lần ở `content_hash_of`, một lần trong `index()`). Đó là đánh đổi có ý thức — chunk là hàm thuần và `sha256` trên vài KB rẻ hơn nhiều so với việc tách `index()` thành hai nửa và phải giữ hai nửa đó khớp nhau về sau.

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_content_hash_of.py`:

```python
"""content_hash_of phải khớp TỪNG BIT với hash mà index() ghi ra.

Lệch một bit là chế độ delta bỏ qua record thật sự đã đổi (hoặc nạp lại record
không đổi) — cả hai đều im lặng.
"""

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.rag import RagClient
from portal.modules.kb.contracts import ChunkSpec, MediaDirective, TextDirective


class _EmbedGia:
    """dense/sparse trả đúng số phần tử — index() kiểm độ dài tường minh."""

    async def dense(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]

    async def sparse(self, texts: list[str]) -> list[dict]:
        return [{"indices": [1], "values": [0.5]} for _ in texts]

    async def visual_image(self, urls: list[str]) -> list[list[float]]:
        return [[0.2] * 4 for _ in urls]


class _StoreGia:
    def __init__(self) -> None:
        self.upserted: list = []

    async def delete_by_record(self, name, *, record_id, doc_type="", entity="") -> int:
        return 1

    async def upsert(self, name, points) -> int:
        self.upserted.extend(points)
        return len(points)


def _chi_thi_text(text: str = "Nội dung dài vừa phải", anchor_name: str = "Dự án A") -> TextDirective:
    return TextDirective(
        workspace_slug="acme",
        record_id=7,
        doc_type="phan_khu",
        anchor_code="pa",
        anchor_name=anchor_name,
        section=f"{anchor_name} > Khu B",
        text=text,
        chunk=ChunkSpec(strategy="markdown", max_chars=800, overlap=150),
        entity="zones",
    )


async def test_hash_text_khop_voi_hash_ma_index_ghi_ra():
    store = _StoreGia()
    client = RagClient(embed=_EmbedGia(), store=store)
    chi_thi = _chi_thi_text()

    truoc = client.content_hash_of(chi_thi)
    ket_qua = await client.index(chi_thi)

    assert truoc == ket_qua.content_hash != ""


async def test_doi_ten_du_an_lam_doi_hash():
    """Breadcrumb nằm TRONG nội dung chunk, nên đổi tên dự án phải đổi hash — nếu
    không, mọi phân khu và tài liệu giữ tên cũ trong kho vector vĩnh viễn."""
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    a = client.content_hash_of(_chi_thi_text(anchor_name="Dự án A"))
    b = client.content_hash_of(_chi_thi_text(anchor_name="Dự án B ĐÃ ĐỔI TÊN"))
    assert a != b


async def test_noi_dung_rong_tra_hash_rong():
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    assert client.content_hash_of(_chi_thi_text(text="   ")) == ""


async def test_hash_media_khop_voi_index():
    store = _StoreGia()
    client = MediaClient(embed=_EmbedGia(), store=store)
    chi_thi = MediaDirective(
        workspace_slug="acme",
        record_id=11,
        anchor_code="pa",
        content_type="image",
        category="tong_quan",
        media_url="tenants/acme/img/a.jpg",
        caption="Toàn cảnh khu căn hộ",
    )

    truoc = client.content_hash_of(chi_thi)
    ket_qua = await client.index(chi_thi)

    assert truoc == ket_qua.content_hash != ""
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_content_hash_of.py -v`
Expected: FAIL — `AttributeError: 'RagClient' object has no attribute 'content_hash_of'`

- [ ] **Step 3: Sửa `clients/rag.py`**

Rút hai helper module-level (đặt ngay dưới `collection_name`) và cho `index()` dùng chúng:

```python
def _noi_dung_chunk(directive: TextDirective) -> list[str]:
    dau = f"{directive.anchor_name} — {directive.section}".strip(" —")
    chunks = chunker.split(directive.text, directive.chunk)
    return [f"{dau}\n\n{c}" if dau else c for c in chunks]


def _hash_cua(noi_dung: list[str]) -> str:
    return hashlib.sha256("␟".join(noi_dung).encode()).hexdigest() if noi_dung else ""
```

Viết lại `RagClient.index()` để dùng helper, và thêm `content_hash_of`:

```python
    def content_hash_of(self, directive: TextDirective) -> str:
        return _hash_cua(_noi_dung_chunk(directive))

    async def index(self, directive: TextDirective) -> IndexResult:
        ten = self.collection(directive.workspace_slug)
        noi_dung = _noi_dung_chunk(directive)

        # Xoá TRƯỚC khi kiểm rỗng: biên tập viên xoá trắng nội dung thì split trả
        # [], và thoát sớm ở đây để lại point cũ sống vĩnh viễn trong khi sổ ghi
        # points=0 — agent tiếp tục trả lời bằng nội dung đã bị xoá.
        await self._store.delete_by_record(
            ten, record_id=directive.record_id, doc_type=directive.doc_type, entity=directive.entity
        )
        if not noi_dung:
            return IndexResult(points_upserted=0, content_hash="")

        content_hash = _hash_cua(noi_dung)
        dense = await self._embed.dense(noi_dung)
        sparse = await self._embed.sparse(noi_dung)
        if len(dense) != len(noi_dung) or len(sparse) != len(noi_dung):
            raise ValueError(f"embed trả thiếu: {len(noi_dung)} chunk nhưng {len(dense)} dense / {len(sparse)} sparse")

        points = [
            PointIn(
                point_id=point_id_of(directive.doc_type, directive.record_id, i),
                vectors={"dense": dense[i], "bm25": {"indices": s["indices"], "values": s["values"]}},
                payload={
                    "project_id": directive.anchor_code,
                    "anchor_code": directive.anchor_code,
                    "doc_type": directive.doc_type,
                    "entity": directive.entity,
                    "content_type": "text",
                    "section": directive.section,
                    "text": noi_dung[i],
                    "chunk_index": i,
                    "record_id": directive.record_id,
                    "content_hash": content_hash,
                },
            )
            for i, s in enumerate(sparse)
        ]
        n = await self._store.upsert(ten, points)
        return IndexResult(points_upserted=n, content_hash=content_hash)
```

- [ ] **Step 4: Sửa `clients/media.py`**

Rút helper và thêm method:

```python
def _mo_ta_va_hash(directive: MediaDirective) -> tuple[str, str]:
    caption = directive.caption or ""
    mo_ta = f"{directive.category} {caption}".strip()
    content_hash = hashlib.sha256(f"{directive.media_url}␟{caption}".encode()).hexdigest()
    return mo_ta, content_hash
```

Trong `MediaClient`:

```python
    def content_hash_of(self, directive: MediaDirective) -> str:
        return _mo_ta_va_hash(directive)[1]
```

Và trong `index()`, thay ba dòng đầu (`caption = …`, `mo_ta = …`, `content_hash = …`) bằng:

```python
        mo_ta, content_hash = _mo_ta_va_hash(directive)
        caption = directive.caption or ""
```

- [ ] **Step 5: Sửa `fake.py`**

Trong `FakeIndexClient.__init__`, thêm hai thuộc tính:

```python
        self.hash_calls = 0
        self.index_calls = 0
```

Thêm method (dùng đúng công thức mà `index()` của fake dùng, để test service khớp):

```python
    def content_hash_of(self, directive: TextDirective | MediaDirective) -> str:
        self.hash_calls += 1
        return self._hash_cua(directive)

    @staticmethod
    def _hash_cua(directive: TextDirective | MediaDirective) -> str:
        is_media = isinstance(directive, MediaDirective)
        payload = f"{directive.caption}|{directive.media_url}" if is_media else directive.text
        return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()
```

Và viết lại `index()` để dùng chung helper + đếm lời gọi:

```python
    async def index(self, directive: TextDirective | MediaDirective) -> IndexResult:
        self.indexed.append(directive)
        self.index_calls += 1
        is_media = isinstance(directive, MediaDirective)
        return IndexResult(
            points_upserted=1,
            content_hash=self._hash_cua(directive),
            caption=self.generated_caption if is_media and directive.caption is None else None,
            extracted_text=self.extracted_text if not is_media else None,
        )
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/kb/test_content_hash_of.py -v
make test-module M=kb
```

Expected: PASS hết. Nếu `test_index_client_that.py` đỏ, đọc kỹ — nó canh hình dạng point thật và hash **không được đổi giá trị** so với trước đợt này.

- [ ] **Step 7: In lệnh commit**

```bash
git add src/portal/modules/kb/clients/rag.py src/portal/modules/kb/clients/media.py src/portal/modules/kb/fake.py tests/modules/kb/test_content_hash_of.py
git commit -m "feat(kb): content_hash_of — tính hash không cần gọi embed"
```

---

## Task 4: Phép thoát sớm ở `service`

**Files:**
- Modify: `src/portal/modules/kb/service.py`
- Test: `tests/modules/kb/test_delta_thoat_som.py`

**Interfaces:**
- Consumes: `repo.saved_hash`/`mark_skipped` (Task 2), `client.content_hash_of` (Task 3), `MODE_DELTA`/`MODE_FULL` (Task 2)
- Produces:
  - `service.index_text(conn, *, tenant_id, slug, vertical, entity, doc_type, record_id, rag, store, mode: str = MODE_FULL) -> IndexResult | None`
  - `service.index_media(conn, *, tenant_id, slug, vertical, record_id, media, store, mode: str = MODE_FULL) -> IndexResult | None`
  - Khi bỏ qua: trả `IndexResult(points_upserted=0, content_hash=<hash cũ>, skipped=True)`

`mode` mặc định `MODE_FULL` để mọi caller cũ (và mọi test cũ) giữ nguyên hành vi.

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_delta_thoat_som.py`:

```python
"""Chế độ delta: hash trùng thì KHÔNG gọi embed, nhưng vẫn chạm indexed_at."""

from portal.core.db.session import tenant_conn
from portal.modules.kb import service
from portal.modules.kb.contracts import MODE_DELTA, MODE_FULL
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.fake import FakeIndexClient, FakeObjectStore
from portal.modules.kb.state import repo

from .conftest import TENANT


async def _nap(conn, rag, store, record_id: int, mode: str = MODE_FULL):
    return await service.index_text(
        conn,
        tenant_id=TENANT,
        slug=TENANT,
        vertical=REAL_ESTATE,
        entity="documents",
        doc_type="tai_lieu",
        record_id=record_id,
        rag=rag,
        store=store,
        mode=mode,
    )


async def test_lan_hai_o_che_do_delta_khong_goi_embed(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        assert rag.index_calls == 1

        lan_hai = await _nap(conn, rag, store, rid, mode=MODE_DELTA)
        rows = await repo.read_state(conn, entity="documents", record_id=rid)

    assert rag.index_calls == 1, "hash trùng mà vẫn gọi embed — phép thoát sớm không chạy"
    assert lan_hai is not None and lan_hai.skipped is True
    assert lan_hai.points_upserted == 0

    hang = rows[0]
    assert hang["state"] == "skipped"
    assert hang["points"] == 1, "points phải giữ nguyên — point cũ vẫn còn trên Qdrant"
    assert hang["indexed_at"] is not None


async def test_che_do_full_bo_qua_phep_so(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await _nap(conn, rag, store, rid, mode=MODE_FULL)
    assert rag.index_calls == 2, "nạp lại toàn bộ phải thật là toàn bộ"


async def test_noi_dung_doi_thi_van_nap_lai_o_che_do_delta(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await conn.execute(
            "UPDATE tenant_data.documents SET body = 'nội dung đã sửa' "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            rid,
        )
        ket_qua = await _nap(conn, rag, store, rid, mode=MODE_DELTA)

    assert rag.index_calls == 2
    assert ket_qua is not None and ket_qua.skipped is False


async def test_dong_so_dang_loi_thi_van_nap_lai_du_hash_trung(api_pool, doc_ids):
    """hash trùng chỉ nói nội dung không đổi — nó KHÔNG nói point đã lên Qdrant."""
    rag, store = FakeIndexClient(), FakeObjectStore()
    rid = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, rid)
        await conn.execute(
            "UPDATE tenant_data.kb_index_state SET state = 'error', error = 'embed 500' "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            rid,
        )
        await _nap(conn, rag, store, rid, mode=MODE_DELTA)

    assert rag.index_calls == 2


async def test_ghi_project_code_vao_so(api_pool, doc_ids):
    rag, store = FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        await _nap(conn, rag, store, doc_ids["nplb"])
        got = await conn.fetchval(
            "SELECT project_code FROM tenant_data.kb_index_state "
            "WHERE tenant_id = portal.current_tenant() AND record_id = $1",
            doc_ids["nplb"],
        )
    assert got == "nplb"
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_delta_thoat_som.py -v`
Expected: FAIL — `TypeError: index_text() got an unexpected keyword argument 'mode'`

- [ ] **Step 3: Sửa `service.py`**

Đổi import ở đầu file:

```python
from portal.modules.kb.contracts import (
    MODE_FULL,
    IndexClient,
    IndexResult,
    MediaDirective,
    ObjectStore,
    VerticalSpec,
)
```

Thêm helper module-level (đặt trên `index_text`):

```python
async def _bo_qua_duoc(
    conn: asyncpg.Connection,
    *,
    mode: str,
    entity: str,
    record_id: int,
    doc_type: str,
    hash_moi: str,
) -> str | None:
    """Trả hash cũ nếu được phép bỏ qua, None nếu phải nạp lại.

    Đòi `state == 'indexed'`: một record từng lỗi có hash trùng vẫn phải nạp lại —
    hash trùng nói nội dung không đổi, không nói point đã lên Qdrant.
    """
    if mode != MODE_DELTA or not hash_moi:
        return None
    da_luu = await repo.saved_hash(conn, entity=entity, record_id=record_id, doc_type=doc_type)
    if da_luu is None:
        return None
    hash_cu, state = da_luu
    return hash_cu if state == "indexed" and hash_cu == hash_moi else None
```

Thêm `MODE_DELTA` vào import cùng `MODE_FULL`.

Trong `index_text`, sau khi dựng `directive` và **trước** `repo.save_state(... 'indexing')`, chèn:

```python
    hash_cu = await _bo_qua_duoc(
        conn,
        mode=mode,
        entity=entity,
        record_id=record_id,
        doc_type=directive.doc_type,
        hash_moi=rag.content_hash_of(directive),
    )
    if hash_cu is not None:
        await repo.mark_skipped(conn, entity=entity, record_id=record_id, doc_type=directive.doc_type)
        return IndexResult(points_upserted=0, content_hash=hash_cu, skipped=True)
```

Thêm `mode: str = MODE_FULL` vào chữ ký `index_text`, và `project_code=directive.anchor_code` vào **cả hai** lời gọi `repo.save_state` trong hàm.

Trong `index_media`, sau khi dựng `directive` và trước `save_state(... 'indexing')`:

```python
    hash_cu = await _bo_qua_duoc(
        conn,
        mode=mode,
        entity="media",
        record_id=record_id,
        doc_type="",
        hash_moi=media.content_hash_of(directive),
    )
    if hash_cu is not None:
        await repo.mark_skipped(conn, entity="media", record_id=record_id, doc_type="")
        return IndexResult(points_upserted=0, content_hash=hash_cu, skipped=True)
```

Thêm `mode: str = MODE_FULL` vào chữ ký `index_media`, và `project_code=directive.anchor_code` vào cả ba lời gọi `repo.save_state` trong hàm (kể cả nhánh `should_index_media` trả `False`).

- [ ] **Step 4: Chạy test**

```bash
uv run pytest tests/modules/kb/test_delta_thoat_som.py -v
make test-module M=kb
```

Expected: PASS hết.

- [ ] **Step 5: In lệnh commit**

```bash
git add src/portal/modules/kb/service.py tests/modules/kb/test_delta_thoat_som.py
git commit -m "feat(kb): chế độ delta thoát sớm khi content_hash không đổi"
```

---

## Task 5: `mode` chạy suốt từ job cha xuống job con

**Files:**
- Modify: `src/portal/modules/kb/jobs.py`
- Modify: `src/portal/modules/kb/ops/sync.py`
- Modify: `src/portal/modules/kb/ops/backfill.py`
- Test: `tests/modules/kb/test_sync_mode.py`

**Interfaces:**
- Consumes: `service.index_*(mode=…)` (Task 4)
- Produces:
  - `sync.enqueue_project(conn, *, tenant_id, project_code, vertical, actor, mode: str = MODE_DELTA) -> int` — payload job con mang `project_code` và `mode`
  - `handle_index` đọc `payload.get("mode", MODE_FULL)`
  - `handle_sync_project` đọc `payload.get("mode", MODE_DELTA)` và truyền xuống

Mặc định khác nhau là có ý: một job `kb_index` lẻ (từ `POST /kb/{entity}/{id}/reindex`) là người dùng chủ động chỉ vào một record ⇒ `full`. Một lần bấm nút cấp dự án mặc định là `delta` ⇒ rẻ.

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_sync_mode.py`:

```python
"""mode phải đi từ job cha xuống từng job con, và payload phải mang project_code."""

import json

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.contracts import MODE_DELTA, MODE_FULL
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.fake import FakeIndexClient, FakeObjectStore
from portal.modules.kb.ops import sync

TENANT = "kb_acme"


@pytest.fixture
def fakes(monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    return rag, media, store


def _payloads(rows) -> list[dict]:
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def test_job_con_mang_project_code_va_mode(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test", mode=MODE_DELTA
        )
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )

    ps = _payloads(rows)
    assert ps, "không xếp job nào"
    assert all(p["project_code"] == "nplb" for p in ps)
    assert all(p["mode"] == MODE_DELTA for p in ps)


async def test_handle_sync_project_truyen_mode_full_xuong(pool, seed_kb, fakes):
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_sync_project(
            conn, {"vertical": "real_estate", "project_code": "nplb", "actor": "test", "mode": MODE_FULL}
        )
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )
    assert all(p["mode"] == MODE_FULL for p in _payloads(rows))


async def test_mac_dinh_cua_job_sync_la_delta(pool, seed_kb, fakes):
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_sync_project(conn, {"vertical": "real_estate", "project_code": "nplb", "actor": "t"})
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )
    assert all(p["mode"] == MODE_DELTA for p in _payloads(rows))
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_sync_mode.py -v`
Expected: FAIL — `KeyError: 'project_code'`

- [ ] **Step 3: Sửa `ops/sync.py`**

```python
"""Cascade theo một dự án. `ops/backfill.py` làm cả tenant; đây thu hẹp phạm vi.

Gọi TỪ WORKER của job `kb_sync_project`, không gọi từ router — một dự án 20 phân khu +
96 media là 116 lần INSERT, và giao dịch của request không được ngồi chờ chuyện đó.
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.contracts import KIND_INDEX, MODE_DELTA, VerticalSpec
from portal.modules.kb.source import reader


async def enqueue_project(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    project_code: str,
    vertical: VerticalSpec,
    actor: str,
    mode: str = MODE_DELTA,
) -> int:
    count = 0

    async def _xep(entity: str, record_id: int, doc_type: str = "") -> None:
        nonlocal count
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_INDEX,
            actor=actor,
            payload={
                "vertical": vertical.key,
                "entity": entity,
                "doc_type": doc_type,
                "record_id": record_id,
                "project_code": project_code,
                "mode": mode,
                "op": "upsert",
            },
        )
        count += 1

    for spec in vertical.embed_sources:
        for record_id in await reader.list_published_by_anchor(
            conn, vertical=vertical, spec=spec, anchor_code=project_code
        ):
            await _xep(spec.table, record_id, spec.doc_type)

    for record_id in await reader.list_published_media_by_anchor(
        conn, vertical=vertical, anchor_code=project_code
    ):
        await _xep("media", record_id)

    return count
```

- [ ] **Step 4: Sửa `ops/backfill.py`**

Trong payload của `backfill_tenant`, thêm hai khoá (`project_code` lấy từ chính record — cần đọc thêm, nên đổi sang dùng `reader.list_published` rồi tra `project_code` bằng một câu):

```python
"""Re-index toàn bộ từ Postgres. Gọi khi đổi model/chunk/payload, hoặc migrate media_v3.

Không copy point từ media_v3 sang: nó index bằng pipeline cũ (fastembed INT8/CPU) nên
không parity với model layer mới (§11.3).
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.contracts import KIND_INDEX, MODE_FULL, VerticalSpec
from portal.modules.kb.source import reader


async def backfill_tenant(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    vertical: VerticalSpec,
    actor: str = "cli:backfill",
) -> int:
    count = 0
    for spec in vertical.embed_sources:
        for record_id in await reader.list_published(conn, vertical=vertical, spec=spec):
            # project_code đọc riêng: badge đếm tiến độ theo khoá này, và một job
            # thiếu nó là một mục biến mất khỏi con số người dùng đang nhìn.
            project_code = await conn.fetchval(
                f"SELECT {'project_code' if not spec.is_anchor else vertical.anchor_code_col} "
                f"FROM tenant_data.{spec.table} "
                "WHERE tenant_id = portal.current_tenant() AND id = $1",
                record_id,
            )
            await enqueue(
                conn,
                tenant_id=tenant_id,
                kind=KIND_INDEX,
                actor=actor,
                payload={
                    "vertical": vertical.key,
                    "entity": spec.table,
                    "doc_type": spec.doc_type,
                    "record_id": record_id,
                    "project_code": str(project_code or ""),
                    "mode": MODE_FULL,
                    "op": "upsert",
                },
            )
            count += 1
    return count
```

- [ ] **Step 5: Sửa `jobs.py`**

Trong `handle_index`, đọc `mode` và truyền xuống service:

```python
async def handle_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Record không còn đủ điều kiện thì tự chuyển sang xoá, không coi là lỗi."""
    vertical = registry.get(str(payload["vertical"]))
    entity = str(payload["entity"])
    record_id = int(payload["record_id"])
    doc_type = str(payload.get("doc_type", ""))
    mode = str(payload.get("mode", MODE_FULL))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)
    async with open_dependencies() as (rag, media, store):
        if entity == "media":
            result = await service.index_media(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                vertical=vertical,
                record_id=record_id,
                media=media,
                store=store,
                mode=mode,
            )
        else:
            result = await service.index_text(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                vertical=vertical,
                entity=entity,
                doc_type=doc_type,
                record_id=record_id,
                rag=rag,
                store=store,
                mode=mode,
            )

        if result is None:
            await service.delete_index(conn, slug=slug, entity=entity, record_id=record_id, rag=rag, media=media)
            return JobResult(count=0, message=f"{entity}#{record_id} không còn published → đã xoá point")

    if result.skipped:
        return JobResult(count=0, message=f"{entity}#{record_id}: nội dung không đổi, giữ nguyên")
    return JobResult(count=result.points_upserted, message=f"{entity}#{record_id}: +{result.points_upserted} point")
```

Trong `handle_sync_project`, truyền `mode` (giữ nguyên phần `collections.create`):

```python
    mode = str(payload.get("mode", MODE_DELTA))
    n = await sync.enqueue_project(
        conn,
        tenant_id=tenant_id,
        project_code=str(payload["project_code"]),
        vertical=vertical,
        actor=str(payload.get("actor", "sync")),
        mode=mode,
    )
    nhan = "toàn bộ" if mode == MODE_FULL else "phần đã đổi"
    return JobResult(count=n, message=f"đã xếp {n} mục để nạp ({nhan})")
```

Thêm `MODE_DELTA, MODE_FULL` vào khối import từ `contracts`.

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/kb/test_sync_mode.py -v
make test-module M=kb
uv run pytest tests/unit/test_nap_lai_kb.py -v
```

Expected: PASS hết. `test_nap_lai_kb.py` chạm `backfill` nên phải kiểm nó riêng.

- [ ] **Step 7: In lệnh commit**

```bash
git add src/portal/modules/kb/jobs.py src/portal/modules/kb/ops/ tests/modules/kb/test_sync_mode.py
git commit -m "feat(kb): mode delta/full chạy từ job cha xuống job con"
```

---

## Task 6: Endpoint trạng thái theo dự án

**Files:**
- Modify: `src/portal/modules/kb/state/repo.py`
- Modify: `src/portal/modules/realestate/contracts.py`
- Modify: `src/portal/modules/realestate/router.py:995` (thay `kb_sync_status`)
- Test: `tests/modules/kb/test_project_status.py`

**Interfaces:**
- Consumes: cột `project_code` (Task 1)
- Produces:
  - `repo.project_status(conn) -> list[asyncpg.Record]` với cột `project_code · pending · total · stale_count · error_count · last_synced_at`
  - `contracts.TrangThaiKbOut` (pydantic): `projectCode · state · pending · total · staleCount · errorCount · lastSyncedAt`
  - `GET /api/v1/projects/kb-status` → `list[TrangThaiKbOut]`
  - `state` là một trong `running · error · stale · never · synced`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_project_status.py`:

```python
"""project_status — badge đọc đúng một endpoint này cho cả trang danh sách."""

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.state import repo

from .conftest import TENANT


def _cua(rows, project_code: str):
    return next((r for r in rows if r["project_code"] == project_code), None)


async def test_du_an_chua_nap_lan_nao_co_total_0(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        rows = await repo.project_status(conn)
    hang = _cua(rows, "nplb")
    assert hang is not None
    assert hang["total"] == 0
    assert hang["stale_count"] > 0, "record published chưa có dòng sổ phải tính là lệch"


async def test_sau_khi_nap_thi_het_lech(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        for entity, rid, doc_type in [("documents", doc_ids["nplb"], "csbh")]:
            await repo.save_state(
                conn,
                entity=entity,
                record_id=rid,
                doc_type=doc_type,
                target="documents",
                state="indexed",
                result=IndexResult(points_upserted=2, content_hash="h1"),
                project_code="nplb",
            )
        # projects.nplb cũng là một mục phải nạp — nạp luôn để dự án hết lệch.
        pid = await conn.fetchval(
            "SELECT id FROM tenant_data.projects "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'nplb'"
        )
        await repo.save_state(
            conn,
            entity="projects",
            record_id=pid,
            doc_type="tong_quan",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=1, content_hash="h2"),
            project_code="nplb",
        )
        rows = await repo.project_status(conn)

    hang = _cua(rows, "nplb")
    assert hang["total"] == 2
    assert hang["error_count"] == 0
    assert hang["last_synced_at"] is not None
    assert hang["stale_count"] == 0


async def test_dong_loi_duoc_dem(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="error",
            error="embed 500",
            project_code="nplb",
        )
        rows = await repo.project_status(conn)
    assert _cua(rows, "nplb")["error_count"] == 1


async def test_job_dang_cho_duoc_dem_vao_pending(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload) "
            "VALUES (portal.current_tenant(), 'kb_index', 'test', $1::jsonb)",
            '{"project_code": "nplb", "entity": "documents", "record_id": 1}',
        )
        rows = await repo.project_status(conn)
    assert _cua(rows, "nplb")["pending"] == 1


async def test_khong_thay_du_an_cua_tenant_khac(api_pool, doc_ids):
    async with tenant_conn(api_pool, TENANT) as conn:
        rows = await repo.project_status(conn)
    assert all(r["project_code"] in {"nplb", "__ALL__", "draftpj"} for r in rows)
```

Create `tests/modules/kb/test_endpoint_kb_status.py`:

```python
"""GET /projects/kb-status — thứ tự ưu tiên trạng thái là hợp đồng với badge."""


async def test_tra_ve_danh_sach_va_co_du_khoa(client_cfg, workspace_cfg):
    r = await client_cfg.get("/api/v1/projects/kb-status")
    assert r.status_code == 200
    ds = r.json()
    assert isinstance(ds, list)
    if ds:
        m = ds[0]
        assert set(m) == {
            "projectCode",
            "state",
            "pending",
            "total",
            "staleCount",
            "errorCount",
            "lastSyncedAt",
        }
        assert m["state"] in {"running", "error", "stale", "never", "synced"}


async def test_duong_dan_khong_bi_route_du_an_an_mat(client_cfg, workspace_cfg):
    """`GET /projects/{project_code}` khớp mọi chuỗi — kb-status phải đăng ký TRƯỚC nó."""
    r = await client_cfg.get("/api/v1/projects/kb-status")
    assert r.status_code == 200, "rơi vào doc_du_an nghĩa là thứ tự route sai"
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_project_status.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'project_status'`

- [ ] **Step 3: Viết `repo.project_status`**

Thêm vào cuối `src/portal/modules/kb/state/repo.py`:

```python
# `stale` phải đọc `updated_at` của bảng NGUỒN — sổ không có cột đó. Bốn nhánh
# UNION vì `kb_index_state` trỏ bốn bảng qua `(entity, record_id)`, và mỗi bảng có
# sequence riêng nên nối thẳng bằng `record_id` là trộn id của bốn bảng.
_MUC_PUBLISHED = """
    SELECT 'projects' AS entity, p.id, p.project_code, p.updated_at
      FROM tenant_data.projects p
     WHERE p.tenant_id = portal.current_tenant() AND p.status = 'published'
    UNION ALL
    SELECT 'zones', z.id, z.project_code, z.updated_at
      FROM tenant_data.zones z
      JOIN tenant_data.projects ap
           ON (ap.tenant_id, ap.project_code) = (z.tenant_id, z.project_code)
     WHERE z.tenant_id = portal.current_tenant() AND z.status = 'published' AND ap.status = 'published'
    UNION ALL
    SELECT 'documents', d.id, d.project_code, d.updated_at
      FROM tenant_data.documents d
      JOIN tenant_data.projects ad
           ON (ad.tenant_id, ad.project_code) = (d.tenant_id, d.project_code)
     WHERE d.tenant_id = portal.current_tenant() AND d.status = 'published' AND ad.status = 'published'
    UNION ALL
    SELECT 'media', m.id, m.project_code, m.updated_at
      FROM tenant_data.media m
      JOIN tenant_data.projects am
           ON (am.tenant_id, am.project_code) = (m.tenant_id, m.project_code)
     WHERE m.tenant_id = portal.current_tenant() AND m.status = 'published' AND am.status = 'published'
"""

_PROJECT_STATUS = f"""
WITH muc AS ({_MUC_PUBLISHED}),
so AS (
    SELECT project_code,
           count(*) FILTER (WHERE state <> 'deleted') AS total,
           count(*) FILTER (WHERE state = 'error') AS error_count,
           max(indexed_at) AS last_synced_at
      FROM tenant_data.kb_index_state
     WHERE tenant_id = portal.current_tenant() AND project_code <> ''
     GROUP BY project_code
),
lech AS (
    SELECT m.project_code, count(*) AS stale_count
      FROM muc m
      LEFT JOIN tenant_data.kb_index_state s
             ON s.tenant_id = portal.current_tenant()
            AND s.entity = m.entity
            AND s.record_id = m.id
            AND s.state <> 'deleted'
     WHERE s.id IS NULL OR s.indexed_at IS NULL OR m.updated_at > s.indexed_at
     GROUP BY m.project_code
),
cho AS (
    SELECT j.payload->>'project_code' AS project_code, count(*) AS pending
      FROM control.jobs j
     WHERE j.tenant_id = portal.current_tenant()
       AND j.kind IN ('kb_index', 'kb_sync_project')
       AND j.state IN ('queued', 'running')
       AND coalesce(j.payload->>'project_code', '') <> ''
     GROUP BY 1
)
SELECT p.project_code,
       coalesce(cho.pending, 0)::int AS pending,
       coalesce(so.total, 0)::int AS total,
       coalesce(lech.stale_count, 0)::int AS stale_count,
       coalesce(so.error_count, 0)::int AS error_count,
       so.last_synced_at
  FROM tenant_data.projects p
  LEFT JOIN so ON so.project_code = p.project_code
  LEFT JOIN lech ON lech.project_code = p.project_code
  LEFT JOIN cho ON cho.project_code = p.project_code
 WHERE p.tenant_id = portal.current_tenant()
 ORDER BY p.project_code
"""


async def project_status(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(_PROJECT_STATUS)


async def indexed_of_project(conn: asyncpg.Connection, *, project_code: str) -> list[asyncpg.Record]:
    """Mục đã từng nạp của một dự án — đọc SỔ, không đọc bảng nguồn.

    Đây là đường duy nhất còn dùng được sau khi `ON DELETE CASCADE` đã xoá row con:
    sổ không có FK tới bảng nguồn nên dòng của nó sống sót.
    """
    return await conn.fetch(
        "SELECT entity, record_id, doc_type FROM tenant_data.kb_index_state "
        "WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND state <> 'deleted' "
        "ORDER BY entity, record_id",
        project_code,
    )
```

- [ ] **Step 4: Thêm DTO vào `realestate/contracts.py`**

Đặt cạnh các `*Out` khác:

```python
class TrangThaiKbOut(BaseModel):
    projectCode: str
    # running > error > stale > never > synced — thứ tự ưu tiên là hợp đồng với badge.
    state: Literal["running", "error", "stale", "never", "synced"]
    pending: int
    total: int
    staleCount: int
    errorCount: int
    lastSyncedAt: str | None
```

Nếu `Literal` chưa được import trong file đó thì thêm `from typing import Literal`.

- [ ] **Step 5: Viết lại endpoint**

Trong `src/portal/modules/realestate/router.py`, thay toàn bộ hàm `kb_sync_status` (bắt đầu ở dòng ~995) bằng:

```python
def _trang_thai_kb(r: asyncpg.Record) -> str:
    if r["pending"] > 0:
        return "running"
    if r["error_count"] > 0:
        return "error"
    if r["stale_count"] > 0:
        return "stale"
    if r["total"] == 0:
        return "never"
    return "synced"


@ROUTER.get("/projects/kb-status", response_model=list[TrangThaiKbOut])
async def kb_status(
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[TrangThaiKbOut]:
    """Mức DỰ ÁN. `running` che `stale` vì con số lệch đang giảm dần, và hiện
    "chưa nạp" lúc đó làm người dùng bấm lại; `error` che `stale` vì lỗi phải xử
    lý trước.

    PHẢI đứng TRƯỚC `doc_du_an` (`GET /projects/{project_code}`): Starlette khớp
    route theo thứ tự đăng ký và `{project_code}` nhận mọi chuỗi.
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await kb_repo.project_status(conn)
    return [
        TrangThaiKbOut(
            projectCode=r["project_code"],
            state=_trang_thai_kb(r),
            pending=r["pending"],
            total=r["total"],
            staleCount=r["stale_count"],
            errorCount=r["error_count"],
            lastSyncedAt=r["last_synced_at"].isoformat() if r["last_synced_at"] else None,
        )
        for r in rows
    ]
```

Import cần thêm ở đầu `router.py`:

```python
from portal.modules.kb.state import repo as kb_repo
```

⚠ **Luật 3 nói module chỉ import `portal.modules.<khác>.contracts`.** `kb.state.repo` **không** phải `contracts`, nên import trên **sẽ làm `tests/test_module_boundaries.py` đỏ**. Cách đúng: **không** import `kb_repo` ở `realestate`. Thay vào đó viết câu SQL trạng thái ngay trong `realestate/repo.py` (nó sở hữu 4 bảng nguồn và đọc `kb_index_state` là đọc một bảng `tenant_data` bình thường). Chuyển khối `_MUC_PUBLISHED`/`_PROJECT_STATUS`/`project_status()` từ Step 3 sang `src/portal/modules/realestate/repo.py` và gọi `repo.project_status(conn)`. Giữ `indexed_of_project()` ở `kb/state/repo.py` — nó do `kb/service.py` gọi, cùng module nên không vi phạm.

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/kb/test_project_status.py tests/modules/kb/test_endpoint_kb_status.py -v
uv run pytest tests/test_module_boundaries.py -v
uv run pytest tests/isolation/test_loc_tenant_o_tang_app.py -v
```

Expected: cả ba PASS. Nếu `test_module_boundaries` đỏ thì Step 5 chưa chuyển SQL sang `realestate/repo.py`. Nếu `test_loc_tenant_o_tang_app` đỏ thì một câu SQL mới thiếu `tenant_id = portal.current_tenant()`.

Chú ý: test ở `tests/modules/kb/test_project_status.py` gọi `repo.project_status` — sau Step 5 nó nằm ở `realestate/repo.py`, nên **đổi import trong test** thành `from portal.modules.realestate import repo as re_repo` và gọi `re_repo.project_status(conn)`. Đổi luôn tên file test sang `tests/modules/realestate/test_project_status.py` cho đúng chỗ.

- [ ] **Step 7: In lệnh commit**

```bash
git add src/portal/modules/kb/state/repo.py src/portal/modules/realestate/ tests/modules/
git commit -m "feat(re): GET /projects/kb-status — trạng thái nạp kiến thức từng dự án"
```

---

## Task 7: Cascade đọc sổ thay vì đọc bảng nguồn

**Files:**
- Modify: `src/portal/modules/kb/service.py` (`delete_cascade`)
- Modify: `src/portal/modules/kb/jobs.py` (`handle_delete`)
- Modify: `src/portal/modules/kb/source/fanout.py` (chỉ docstring)
- Test: `tests/modules/kb/test_cascade_sau_khi_xoa.py`

**Interfaces:**
- Consumes: `repo.indexed_of_project` (Task 6)
- Produces: `service.delete_cascade(conn, *, slug: str, anchor_code: str, rag: IndexClient, media: IndexClient) -> int` — **bỏ tham số `vertical`**

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_cascade_sau_khi_xoa.py`:

```python
"""Cascade phải chạy ĐƯỢC sau khi row nguồn đã bị ON DELETE CASCADE xoá.

Đây là lỗi mà cột project_code sửa: worker chạy sau request vài giây, và lúc đó
Postgres không còn con nào để liệt kê.
"""

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs, service
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.fake import FakeIndexClient, FakeObjectStore
from portal.modules.kb.state import repo

from .conftest import TENANT


async def test_xoa_du_an_roi_van_xoa_du_point(api_pool, doc_ids, pool):
    rag, media = FakeIndexClient(), FakeIndexClient()
    rid = doc_ids["nplb"]

    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=rid,
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=2, content_hash="h"),
            project_code="nplb",
        )

    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "DELETE FROM tenant_data.projects "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'nplb'"
        )
        con_lai = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.documents "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            rid,
        )
    assert con_lai == 0, "seed sai — FK phải là ON DELETE CASCADE"

    async with tenant_conn(api_pool, TENANT) as conn:
        n = await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert n == 1
    assert rag.deleted == [(TENANT, rid, "csbh")]


async def test_handle_delete_nhanh_anchor_goi_cascade(api_pool, doc_ids, monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    rid = doc_ids["nplb"]

    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=rid,
            doc_type="csbh",
            target="documents",
            state="indexed",
            result=IndexResult(points_upserted=1, content_hash="h"),
            project_code="nplb",
        )
        ket_qua = await jobs.handle_delete(conn, {"vertical": "real_estate", "anchor_code": "nplb"})
        rows = await repo.read_state(conn, entity="documents", record_id=rid)

    assert ket_qua.count == 1
    assert rows[0]["state"] == "deleted"


async def test_cascade_khong_cham_du_an_khac(api_pool, doc_ids):
    rag, media = FakeIndexClient(), FakeIndexClient()
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["nplb"],
            doc_type="csbh",
            target="documents",
            state="indexed",
            project_code="nplb",
        )
        await repo.save_state(
            conn,
            entity="documents",
            record_id=doc_ids["__ALL__"],
            doc_type="khac",
            target="documents",
            state="indexed",
            project_code="__ALL__",
        )
        await service.delete_cascade(conn, slug=TENANT, anchor_code="nplb", rag=rag, media=media)

    assert [d[1] for d in rag.deleted] == [doc_ids["nplb"]]
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_cascade_sau_khi_xoa.py -v`
Expected: FAIL — `TypeError: delete_cascade() got an unexpected keyword argument 'anchor_code'` (hàm cũ đòi `vertical`) hoặc `missing 1 required keyword-only argument: 'vertical'`.

- [ ] **Step 3: Viết lại `service.delete_cascade`**

Thay toàn bộ hàm:

```python
async def delete_cascade(
    conn: asyncpg.Connection,
    *,
    slug: str,
    anchor_code: str,
    rag: IndexClient,
    media: IndexClient,
) -> int:
    """Anchor rời published (hoặc bị xoá hẳn) → xoá point của toàn bộ cây con.

    Đọc SỔ `kb_index_state`, KHÔNG đọc bảng nguồn: FK `projects → con` là
    `ON DELETE CASCADE`, nên khi worker chạy tới đây thì row con đã biến mất và
    một câu liệt kê con sẽ trả rỗng — point sống mãi mà không log nào đỏ.
    """
    muc = await repo.indexed_of_project(conn, project_code=anchor_code)
    for r in muc:
        entity, record_id, doc_type = str(r["entity"]), int(r["record_id"]), str(r["doc_type"])
        client = media if entity == "media" else rag
        await client.delete(workspace_slug=slug, record_id=record_id, doc_type=doc_type, entity=entity)
        await repo.mark_deleted(conn, entity=entity, record_id=record_id, doc_types=[doc_type])
    log.info("cascade %s: xoá %d mục", anchor_code, len(muc))
    return len(muc)
```

Bỏ import `fanout` khỏi `service.py` nếu không còn ai dùng.

- [ ] **Step 4: Sửa `handle_delete`**

```python
        anchor_code = payload.get("anchor_code")
        if anchor_code:
            count = await service.delete_cascade(
                conn, slug=slug, anchor_code=str(anchor_code), rag=rag, media=media
            )
            return JobResult(count=count, message=f"cascade {anchor_code}: xoá {count} mục")
```

Bỏ dòng `vertical = registry.get(...)` nếu nhánh còn lại không dùng (`handle_delete` không cần vertical nữa) — nhưng **giữ** việc đọc `payload["vertical"]` nếu test cũ truyền nó, và không truy cập `registry` vô ích.

- [ ] **Step 5: Ghi giới hạn vào `fanout.py`**

Thêm vào docstring của `children_of_anchor`:

```python
    """Trả [(bảng, id)] của mọi con, kể cả con đang published.

    ⚠ CHỈ DÙNG ĐƯỢC KHI ROW ANCHOR CÒN TỒN TẠI. FK `projects → zones/documents/
    media` là `ON DELETE CASCADE`, nên sau một `DELETE` dự án thì hàm này trả rỗng.
    Đường cascade-khi-xoá đã chuyển sang đọc `kb_index_state` (xem
    `service.delete_cascade`); hàm này còn lại cho reconcile, nơi row vẫn còn.
    """
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/kb/test_cascade_sau_khi_xoa.py -v
make test-module M=kb
```

Expected: PASS. Test cũ `test_sync_job.py` có case cascade — nếu nó gọi `delete_cascade(vertical=…)` thì sửa lời gọi trong test đó, **không** thêm lại tham số vào hàm.

- [ ] **Step 7: In lệnh commit**

```bash
git add src/portal/modules/kb/ tests/modules/kb/test_cascade_sau_khi_xoa.py tests/modules/kb/test_sync_job.py
git commit -m "fix(kb): cascade đọc sổ index nên chạy đúng sau khi row nguồn bị cascade xoá"
```

---

## Task 8: `realestate` enqueue dọn khi xoá — dự án, tài liệu, media

**Files:**
- Modify: `src/portal/modules/realestate/router.py` (`sua_du_an`, `xoa_du_an`, `xoa_tai_lieu`, `xoa_media`, `sua_tai_lieu`)
- Test: `tests/modules/realestate/test_enqueue_don_khi_xoa.py`

**Interfaces:**
- Consumes: `KIND_DELETE_INDEX` (đã có trong `kb.contracts`), `handle_delete` nhánh `anchor_code` (Task 7)
- Produces: không có API mới — chỉ thêm `enqueue` vào 5 handler

- [ ] **Step 1: Viết test trước**

Create `tests/modules/realestate/test_enqueue_don_khi_xoa.py`:

```python
"""Mọi đường xoá/ẩn phải xếp job dọn point. Thiếu một đường là point mồ côi im lặng."""

import json


def _jobs(rows) -> list[dict]:
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _payload_jobs(pool, tenant_id: str, kind: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id",
            tenant_id,
            kind,
        )
    return _jobs(rows)


async def test_xoa_du_an_xep_job_cascade(client_cfg, workspace_cfg, pool):
    r = await client_cfg.post(
        "/api/v1/projects",
        json={"projectCode": "xoa1", "name": "Dự án sẽ xoá", "status": "draft"},
    )
    assert r.status_code == 201

    r = await client_cfg.delete("/api/v1/projects/xoa1")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("anchor_code") == "xoa1" for j in js), "xoá dự án không xếp job cascade"


async def test_unpublish_du_an_xep_job_cascade(client_cfg, workspace_cfg, pool):
    await client_cfg.post(
        "/api/v1/projects", json={"projectCode": "an1", "name": "Dự án sẽ ẩn", "status": "draft"}
    )
    r = await client_cfg.patch("/api/v1/projects/an1", json={"status": "draft"})
    assert r.status_code == 200

    js = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("anchor_code") == "an1" for j in js)


async def test_xoa_media_xep_job_theo_record(client_cfg, workspace_cfg, pool):
    await client_cfg.post(
        "/api/v1/projects", json={"projectCode": "md1", "name": "Dự án media", "status": "draft"}
    )
    r = await client_cfg.post(
        "/api/v1/projects/md1/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "md1/a.jpg", "status": "published"},
    )
    assert r.status_code == 201
    mid = r.json()["id"]

    r = await client_cfg.delete(f"/api/v1/projects/md1/media/{mid}")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("entity") == "media" and j.get("record_id") == mid for j in js)


async def test_xoa_tai_lieu_xep_job_theo_record(client_cfg, workspace_cfg, pool):
    await client_cfg.post(
        "/api/v1/projects", json={"projectCode": "tl1", "name": "Dự án tài liệu", "status": "draft"}
    )
    r = await client_cfg.post(
        "/api/v1/projects/tl1/documents",
        json={"title": "Bảng giá", "loai": "csbh", "body": "nội dung", "status": "published"},
    )
    assert r.status_code == 201
    did = r.json()["id"]

    r = await client_cfg.delete(f"/api/v1/projects/tl1/documents/{did}")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("entity") == "documents" and j.get("record_id") == did for j in js)


async def test_doi_loai_tai_lieu_chi_xep_job_xoa_khong_xep_job_nap(client_cfg, workspace_cfg, pool):
    """Nạp lại là việc người dùng bấm — không còn đường tự lan nào."""
    await client_cfg.post(
        "/api/v1/projects", json={"projectCode": "dl1", "name": "Dự án đổi loại", "status": "draft"}
    )
    r = await client_cfg.post(
        "/api/v1/projects/dl1/documents",
        json={"title": "Bảng giá", "loai": "csbh", "body": "x", "status": "published"},
    )
    did = r.json()["id"]

    truoc = await _payload_jobs(pool, workspace_cfg, "kb_index")
    r = await client_cfg.patch(f"/api/v1/projects/dl1/documents/{did}", json={"loai": "phap_ly"})
    assert r.status_code == 200
    sau = await _payload_jobs(pool, workspace_cfg, "kb_index")

    assert len(sau) == len(truoc), "PATCH đổi loại vẫn tự xếp job nạp — nửa auto phải bỏ"

    xoa = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("record_id") == did and j.get("doc_type") == "csbh" for j in xoa)
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/realestate/test_enqueue_don_khi_xoa.py -v`
Expected: FAIL ở `test_xoa_du_an_xep_job_cascade` — không có job `kb_delete` nào.

- [ ] **Step 3: Sửa `xoa_du_an`**

Thêm `enqueue` trước `_nhat_ky` (trong cùng giao dịch):

```python
        await repo.xoa_du_an(conn, hang["id"])
        # Cascade đọc SỔ `kb_index_state`, nên xếp job SAU khi row đã xoá vẫn đúng —
        # xem `service.delete_cascade`.
        await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_DELETE_INDEX,
            actor=p.user_id,
            payload={"vertical": "real_estate", "anchor_code": project_code},
        )
        await _nhat_ky(conn, p, "realestate.project.delete", {"project_code": project_code})
```

- [ ] **Step 4: Sửa `sua_du_an` — chỉ khi rời `published`**

Sau `sua = await repo.sua_du_an(...)`:

```python
        if payload.get("status") and payload["status"] != "published" and hang["status"] == "published":
            # Anchor rời published thì point của CẢ cây con phải biến mất — xoá
            # riêng hàng dự án mà bỏ con là agent vẫn gửi tài liệu/ảnh của dự án đã ẩn.
            await enqueue(
                conn,
                tenant_id=p.tenant_id,
                kind=KIND_DELETE_INDEX,
                actor=p.user_id,
                payload={"vertical": "real_estate", "anchor_code": project_code},
            )
```

- [ ] **Step 5: Sửa `xoa_tai_lieu` và `xoa_media`**

Trong `xoa_tai_lieu`, trước `_nhat_ky`:

```python
        await repo.xoa_tai_lieu(conn, doc_id)
        # doc_type bỏ trống: row đã xoá nên không suy được loại từ nội dung; worker
        # tra sổ và xoá đúng những loại đang tồn tại.
        await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_DELETE_INDEX,
            actor=p.user_id,
            payload={"vertical": "real_estate", "entity": "documents", "record_id": doc_id},
        )
```

Trong `xoa_media`, cùng cách với `"entity": "media", "record_id": media_id`.

- [ ] **Step 6: Bỏ nửa index lại ở `sua_tai_lieu`**

Trong nhánh `if loai_moi != loai_cu:`, **xoá** lời gọi `enqueue(... kind=KIND_INDEX ...)` và comment của nó, giữ lại job `KIND_DELETE_INDEX`. Thay comment bằng:

```python
            # KHÔNG xếp job nạp lại: nạp là việc người dùng bấm (D1). Badge sẽ báo
            # dự án này lệch cho tới lúc đó.
```

Nếu `KIND_INDEX` không còn được dùng ở `router.py` thì bỏ khỏi khối import.

- [ ] **Step 7: Chạy test**

```bash
uv run pytest tests/modules/realestate/test_enqueue_don_khi_xoa.py -v
uv run pytest tests/modules/realestate -v
```

Expected: PASS. Nếu một test cũ canh "PATCH đổi loại xếp 2 job" thì sửa test đó theo hành vi mới.

- [ ] **Step 8: In lệnh commit**

```bash
git add src/portal/modules/realestate/router.py tests/modules/realestate/
git commit -m "feat(re): xoá/ẩn dự án · xoá tài liệu · xoá media đều xếp job dọn point"
```

---

## Task 9: Phân khu, enrich khi thay tệp, và `mode` ở `sync-kb`

**Files:**
- Modify: `src/portal/modules/realestate/repo.py` (`+ media_ids_of_zone`)
- Modify: `src/portal/modules/realestate/router.py` (`xoa_phan_khu`, `sua_phan_khu`, `sua_media`, `sua_tai_lieu`, `sync_knowledge_base`)
- Test: `tests/modules/realestate/test_enqueue_phan_khu_va_enrich.py`

**Interfaces:**
- Consumes: `KIND_DELETE_INDEX`, `KIND_ENRICH`, `KIND_SYNC_PROJECT`, `MODE_DELTA`, `MODE_FULL`
- Produces:
  - `repo.media_ids_of_zone(conn, *, project_code: str, zone_code: str) -> list[int]`
  - `POST /projects/{code}/sync-kb?mode=delta|full`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/realestate/test_enqueue_phan_khu_va_enrich.py`:

```python
"""Phân khu (§3.1) và enrich khi thay tệp (D6)."""

import json


async def _payload_jobs(pool, tenant_id: str, kind: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id",
            tenant_id,
            kind,
        )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _du_an(client, code: str) -> None:
    r = await client.post("/api/v1/projects", json={"projectCode": code, "name": f"DA {code}", "status": "draft"})
    assert r.status_code == 201


async def test_xoa_phan_khu_xep_job_cho_zone_va_cho_media_cua_zone(client_cfg, workspace_cfg, pool):
    await _du_an(client_cfg, "pk1")
    r = await client_cfg.post(
        "/api/v1/projects/pk1/zones", json={"zoneCode": "z1", "name": "Khu A", "status": "published"}
    )
    assert r.status_code == 201
    zid = r.json()["id"]

    r = await client_cfg.post(
        "/api/v1/projects/pk1/media",
        json={
            "contentType": "image",
            "category": "tong_quan",
            "mediaUrl": "pk1/z1.jpg",
            "zoneCode": "z1",
            "status": "published",
        },
    )
    mid = r.json()["id"]

    r = await client_cfg.post(
        "/api/v1/projects/pk1/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "pk1/khac.jpg", "status": "published"},
    )
    mid_ngoai_zone = r.json()["id"]

    r = await client_cfg.delete("/api/v1/projects/pk1/zones/z1")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_cfg, "kb_delete")
    assert any(j.get("entity") == "zones" and j.get("record_id") == zid for j in js)
    assert any(j.get("entity") == "media" and j.get("record_id") == mid for j in js)
    assert not any(
        j.get("entity") == "media" and j.get("record_id") == mid_ngoai_zone for j in js
    ), "media không thuộc phân khu bị kéo theo"


async def test_thay_anh_thi_tao_lai_mo_ta_voi_force(client_cfg, workspace_cfg, pool):
    await _du_an(client_cfg, "ta1")
    r = await client_cfg.post(
        "/api/v1/projects/ta1/media",
        json={
            "contentType": "image",
            "category": "tong_quan",
            "mediaUrl": "ta1/cu.jpg",
            "caption": "mô tả của ảnh cũ",
            "status": "published",
        },
    )
    mid = r.json()["id"]

    r = await client_cfg.patch(f"/api/v1/projects/ta1/media/{mid}", json={"mediaUrl": "ta1/moi.jpg"})
    assert r.status_code == 200

    js = await _payload_jobs(pool, workspace_cfg, "kb_enrich")
    khop = [j for j in js if j.get("record_id") == mid and j.get("force") is True]
    assert khop, "thay ảnh mà không tạo lại mô tả — mô tả cũ mô tả sai ảnh mới"


async def test_sua_rieng_caption_khong_xep_job_nao(client_cfg, workspace_cfg, pool):
    await _du_an(client_cfg, "ca1")
    r = await client_cfg.post(
        "/api/v1/projects/ca1/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "ca1/a.jpg", "status": "published"},
    )
    mid = r.json()["id"]
    truoc = await _payload_jobs(pool, workspace_cfg, "kb_enrich")

    r = await client_cfg.patch(f"/api/v1/projects/ca1/media/{mid}", json={"caption": "tôi tự viết"})
    assert r.status_code == 200

    sau = await _payload_jobs(pool, workspace_cfg, "kb_enrich")
    assert len(sau) == len(truoc), "sửa chú thích tay không được kích hoạt VLM"


async def test_sync_kb_nhan_mode(client_cfg, workspace_cfg, pool):
    await _du_an(client_cfg, "sy1")
    r = await client_cfg.post("/api/v1/projects/sy1/sync-kb?mode=full")
    assert r.status_code == 202

    js = await _payload_jobs(pool, workspace_cfg, "kb_sync_project")
    assert js[-1]["mode"] == "full"


async def test_sync_kb_mac_dinh_delta(client_cfg, workspace_cfg, pool):
    await _du_an(client_cfg, "sy2")
    r = await client_cfg.post("/api/v1/projects/sy2/sync-kb")
    assert r.status_code == 202

    js = await _payload_jobs(pool, workspace_cfg, "kb_sync_project")
    assert js[-1]["mode"] == "delta"


async def test_mode_la_khong_hop_le_thi_422(client_cfg, workspace_cfg):
    await _du_an(client_cfg, "sy3")
    r = await client_cfg.post("/api/v1/projects/sy3/sync-kb?mode=xyz")
    assert r.status_code == 422
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/realestate/test_enqueue_phan_khu_va_enrich.py -v`
Expected: FAIL ở test đầu — không có job `kb_delete` nào cho phân khu.

- [ ] **Step 3: Thêm `media_ids_of_zone` vào `realestate/repo.py`**

```python
async def media_ids_of_zone(conn: asyncpg.Connection, *, project_code: str, zone_code: str) -> list[int]:
    """Gọi TRƯỚC khi xoá/ẩn phân khu: FK `zones → media` là ON DELETE CASCADE, nên
    sau DELETE thì không còn gì để liệt kê. Sổ `kb_index_state` không mang
    `zone_code` nên nó không cứu được trường hợp này."""
    rows = await conn.fetch(
        "SELECT id FROM tenant_data.media "
        "WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND zone_code = $2 "
        "ORDER BY id",
        project_code,
        zone_code,
    )
    return [int(r["id"]) for r in rows]
```

- [ ] **Step 4: Sửa `xoa_phan_khu`**

```python
@ROUTER.delete("/projects/{project_code}/zones/{zone_code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_phan_khu(
    project_code: str,
    zone_code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_phan_khu(conn, project_code, zone_code)
        if hang is None:
            raise _phan_khu_khong_thay()
        media_ids = await repo.media_ids_of_zone(conn, project_code=project_code, zone_code=zone_code)
        await repo.xoa_phan_khu(conn, hang["id"])
        await _xep_don_phan_khu(conn, p, zone_id=hang["id"], media_ids=media_ids)
        await _nhat_ky(conn, p, "realestate.zone.delete", {"project_code": project_code, "zone_code": zone_code})
```

Thêm helper (đặt cạnh `_nhat_ky`):

```python
async def _xep_don_phan_khu(
    conn: asyncpg.Connection, p: Principal, *, zone_id: int, media_ids: list[int]
) -> None:
    """Một job cho phân khu + một job cho mỗi media của nó.

    Không dùng nhánh `anchor_code`: nhánh đó xoá point của CẢ dự án. Sổ không mang
    `zone_code` nên danh sách media phải chụp trước khi row biến mất (§3.1).
    """
    for entity, record_id in [("zones", zone_id), *(("media", m) for m in media_ids)]:
        await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_DELETE_INDEX,
            actor=p.user_id,
            payload={"vertical": "real_estate", "entity": entity, "record_id": record_id},
        )
```

- [ ] **Step 5: Sửa `sua_phan_khu` — chỉ khi rời `published`**

Sau `sua = await repo.sua_phan_khu(...)`:

```python
        if payload.get("status") and payload["status"] != "published" and hang["status"] == "published":
            media_ids = await repo.media_ids_of_zone(conn, project_code=project_code, zone_code=zone_code)
            await _xep_don_phan_khu(conn, p, zone_id=hang["id"], media_ids=media_ids)
```

Chú ý: `media_ids_of_zone` phải gọi **trước** khi row media đổi gì — ở đây row còn nguyên nên thứ tự không quan trọng, nhưng giữ cùng nếp với nhánh xoá cho dễ đọc.

- [ ] **Step 6: Sửa `sua_media` — enrich khi đổi `mediaUrl`**

```python
        sua = await repo.sua_media(conn, media_id, payload)
        assert sua is not None
        if "media_url" in payload and payload["media_url"] != hang["media_url"]:
            # Ảnh đã khác thì mô tả cũ mô tả SAI ảnh — force=True để đè, kể cả khi
            # đó là chữ người dùng tự viết cho ảnh trước.
            await enqueue(
                conn,
                tenant_id=p.tenant_id,
                kind=KIND_ENRICH,
                actor=p.user_id,
                payload={
                    "vertical": "real_estate",
                    "entity": "media",
                    "record_id": media_id,
                    "force": True,
                },
            )
```

⚠ Kiểm tên khoá thật trong `payload` do `_tach_payload` sinh — nếu nó giữ camelCase (`mediaUrl`) thì dùng đúng tên đó. Đọc `_tach_payload` và `contracts._KHOA_*` trước khi viết dòng `if`.

- [ ] **Step 7: Sửa `sua_tai_lieu` — enrich khi đổi `fileUrl`**

Trong `sua_tai_lieu`, sau khi có `sua`:

```python
        if "file_url" in payload and payload["file_url"] and payload["file_url"] != hang["file_url"]:
            await enqueue(
                conn,
                tenant_id=p.tenant_id,
                kind=KIND_ENRICH,
                actor=p.user_id,
                payload={
                    "vertical": "real_estate",
                    "entity": "documents",
                    "record_id": doc_id,
                    "force": True,
                },
            )
```

(Cùng cảnh báo về tên khoá như Step 6.)

- [ ] **Step 8: Sửa `sync_knowledge_base` — nhận `mode`**

```python
_ModeNap = Literal["delta", "full"]


@ROUTER.post("/projects/{project_code}/sync-kb", status_code=status.HTTP_202_ACCEPTED)
async def sync_knowledge_base(
    project_code: str,
    mode: _ModeNap = "delta",
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int | str]:
    """`mode='full'` nạp lại mọi mục kể cả mục không đổi — tốn tiền embed, nên FE
    phải hỏi xác nhận trước khi gọi."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_SYNC_PROJECT,
            actor=p.user_id,
            payload={
                "vertical": "real_estate",
                "project_code": project_code,
                "actor": p.user_id,
                "mode": mode,
            },
        )
        await _nhat_ky(
            conn, p, "realestate.knowledge.sync", {"project_code": project_code, "job_id": job_id, "mode": mode}
        )
    return {"jobId": job_id, "state": "queued"}
```

`Literal` đã được dùng ở file này cho `_LocMediaCategory`; theo đúng nếp đó.

- [ ] **Step 9: Chạy test**

```bash
uv run pytest tests/modules/realestate/test_enqueue_phan_khu_va_enrich.py -v
uv run pytest tests/modules/realestate tests/modules/kb -v
uv run pytest tests/isolation -v
```

Expected: PASS. `tests/isolation/test_loc_tenant_o_tang_app.py` phải xanh — câu SQL mới ở `media_ids_of_zone` có vị từ tenant tường minh.

- [ ] **Step 10: In lệnh commit**

```bash
git add src/portal/modules/realestate/ tests/modules/realestate/
git commit -m "feat(re): dọn point khi xoá phân khu, tạo lại mô tả khi thay ảnh/tệp, sync-kb nhận mode"
```

---

## Task 10: Chốt phần backend — chạy full check

**Files:** không sửa gì mới

- [ ] **Step 1: Chạy toàn bộ cổng**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
make check
make test-isolation
uv run pytest tests/unit/test_alembic_mot_head.py tests/test_module_boundaries.py -v
```

Expected: `make check` xanh. **Hai vấn đề đã biết từ trước đợt này** vẫn có thể đỏ và **không** thuộc phạm vi sửa ở đây: `tests/modules/test_heartbeat.py` (RLS thiếu trên `control.agent_heartbeats`) và 2 câu SQL thiếu vị từ tenant ở `modules/ops/repo.py:76,110`. Nếu thấy đỏ **chỗ khác**, đó là do đợt này — sửa trước khi đi tiếp.

- [ ] **Step 2: Ghi lại những gì cần vào CLAUDE.md — KHÔNG tự sửa**

Viết ra một đoạn 3-5 dòng mô tả: cột `project_code` + `'skipped'` trên `kb_index_state`, `GET /projects/kb-status` thay `kb-sync-status`, `sync-kb?mode=`, và việc mọi đường xoá/ẩn giờ đều xếp job dọn. **Đưa đoạn đó cho người dùng** để họ tự dán vào `CLAUDE.md` (nhiều người cùng sửa file đó).

---

# PHẦN B — FRONTEND

Làm ở `/home/thanhhai/Desktop/odyssey-portal-frontend`.

## Task 11: API client và MSW handler

**Files:**
- Modify: `src/features/realestate/api.ts`
- Modify: `src/lib/msw/handlers.ts`
- Test: `tests/` — không có test riêng cho task này; các task sau dùng nó

**Interfaces:**
- Produces:
  ```ts
  export type TrangThaiKbState = 'running' | 'error' | 'stale' | 'never' | 'synced'
  export interface TrangThaiKb {
    readonly projectCode: string
    readonly state: TrangThaiKbState
    readonly pending: number
    readonly total: number
    readonly staleCount: number
    readonly errorCount: number
    readonly lastSyncedAt: string | null
  }
  export type CheDoNap = 'delta' | 'full'
  export interface MucEnrich {
    readonly entity: 'media' | 'documents'
    readonly recordId: number
    readonly state: 'queued' | 'running' | 'success' | 'failed'
    readonly message: string
  }
  export function trangThaiKb(): Promise<TrangThaiKb[]>
  export function napKienThuc(projectCode: string, mode: CheDoNap): Promise<{ jobId: number; state: string }>
  export function trangThaiEnrich(projectCode: string): Promise<MucEnrich[]>
  export function taoLaiMoTa(mediaId: number): Promise<{ jobId: number; state: string }>
  ```

- [ ] **Step 1: Thêm kiểu và hàm vào `api.ts`**

Đặt cuối file, sau khối Media:

```ts
// ─── Nạp kiến thức cho agent ────────────────────────────────────────────────

export type TrangThaiKbState = 'running' | 'error' | 'stale' | 'never' | 'synced'

export interface TrangThaiKb {
  readonly projectCode: string
  readonly state: TrangThaiKbState
  readonly pending: number
  readonly total: number
  readonly staleCount: number
  readonly errorCount: number
  readonly lastSyncedAt: string | null
}

export type CheDoNap = 'delta' | 'full'

export interface MucEnrich {
  readonly entity: 'media' | 'documents'
  readonly recordId: number
  readonly state: 'queued' | 'running' | 'success' | 'failed'
  readonly message: string
}

export function trangThaiKb(): Promise<TrangThaiKb[]> {
  return goi('/projects/kb-status')
}

export function napKienThuc(
  projectCode: string,
  mode: CheDoNap,
): Promise<{ jobId: number; state: string }> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/sync-kb?mode=${mode}`, { method: 'POST' })
}

export function trangThaiEnrich(projectCode: string): Promise<MucEnrich[]> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/enrich-status`)
}

export function taoLaiMoTa(mediaId: number): Promise<{ jobId: number; state: string }> {
  return goi(`/media/${mediaId}/recaption`, { method: 'POST' })
}
```

- [ ] **Step 2: Thêm handler vào `src/lib/msw/handlers.ts`**

Cạnh các handler `/api/v1/projects/...` hiện có. ⚠ Đặt handler `kb-status` **trước** handler `'/api/v1/projects/:code'`:

```ts
  http.get('/api/v1/projects/kb-status', () =>
    HttpResponse.json([
      {
        projectCode: 'NPLB',
        state: 'stale',
        pending: 0,
        total: 12,
        staleCount: 3,
        errorCount: 0,
        lastSyncedAt: '2026-08-11T10:32:00Z',
      },
    ]),
  ),
  http.post('/api/v1/projects/:code/sync-kb', () =>
    HttpResponse.json({ jobId: 1, state: 'queued' }, { status: 202 }),
  ),
  http.get('/api/v1/projects/:code/enrich-status', () => HttpResponse.json([])),
  http.post('/api/v1/media/:id/recaption', () =>
    HttpResponse.json({ jobId: 2, state: 'queued' }, { status: 202 }),
  ),
```

- [ ] **Step 3: Kiểm biên dịch**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-frontend
npx tsc --noEmit
npm run lint
```

Expected: không lỗi.

- [ ] **Step 4: In lệnh commit**

```bash
git add src/features/realestate/api.ts src/lib/msw/handlers.ts
git commit -m "feat(re): client cho kb-status, sync-kb, enrich-status, recaption"
```

---

## Task 12: `TheKienThuc` — badge 5 trạng thái

**Files:**
- Create: `src/features/realestate/components/TheKienThuc.tsx`
- Test: `src/features/realestate/components/TheKienThuc.test.tsx`

**Interfaces:**
- Consumes: `TrangThaiKb` (Task 11)
- Produces: `export function TheKienThuc({ tt }: { tt: TrangThaiKb | undefined }): JSX.Element | null` — trả `null` khi `tt` là `undefined` (chưa tải xong)

Bộ nhãn (D7 — không dùng từ kỹ thuật):

| `state` | Nhãn |
|---|---|
`synced` | `● Agent đã có bản mới nhất` |
`running` | `◐ Đang nạp — <total - pending>/<total>` (khi `total` là 0: `◐ Đang nạp…`) |
`stale` | `△ <staleCount> mục chưa nạp` |
`never` | `○ Chưa nạp lần nào` |
`error` | `✕ <errorCount> mục lỗi` |

- [ ] **Step 1: Viết test trước**

Create `src/features/realestate/components/TheKienThuc.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { TrangThaiKb } from '../api'
import { TheKienThuc } from './TheKienThuc'

const CO_SO: TrangThaiKb = {
  projectCode: 'NPLB',
  state: 'synced',
  pending: 0,
  total: 10,
  staleCount: 0,
  errorCount: 0,
  lastSyncedAt: '2026-08-11T10:32:00Z',
}

describe('TheKienThuc', () => {
  it('không render gì khi chưa có dữ liệu', () => {
    const { container } = render(<TheKienThuc tt={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('đã nạp xong thì nói agent đã có bản mới nhất', () => {
    render(<TheKienThuc tt={CO_SO} />)
    expect(screen.getByText(/Agent đã có bản mới nhất/)).toBeInTheDocument()
  })

  it('đang nạp thì hiện tiến độ đã xong trên tổng', () => {
    render(<TheKienThuc tt={{ ...CO_SO, state: 'running', pending: 4, total: 10 }} />)
    expect(screen.getByText(/6\/10/)).toBeInTheDocument()
  })

  it('đang nạp mà chưa biết tổng thì không hiện phân số', () => {
    render(<TheKienThuc tt={{ ...CO_SO, state: 'running', pending: 1, total: 0 }} />)
    expect(screen.getByText(/Đang nạp/)).toBeInTheDocument()
    expect(screen.queryByText('/')).not.toBeInTheDocument()
  })

  it('lệch thì đếm số mục chưa nạp', () => {
    render(<TheKienThuc tt={{ ...CO_SO, state: 'stale', staleCount: 8 }} />)
    expect(screen.getByText(/8 mục chưa nạp/)).toBeInTheDocument()
  })

  it('chưa nạp lần nào', () => {
    render(<TheKienThuc tt={{ ...CO_SO, state: 'never', total: 0, staleCount: 5 }} />)
    expect(screen.getByText(/Chưa nạp lần nào/)).toBeInTheDocument()
  })

  it('lỗi thì đếm số mục lỗi', () => {
    render(<TheKienThuc tt={{ ...CO_SO, state: 'error', errorCount: 3 }} />)
    expect(screen.getByText(/3 mục lỗi/)).toBeInTheDocument()
  })

  it('không dùng từ kỹ thuật nào', () => {
    for (const s of ['synced', 'running', 'stale', 'never', 'error'] as const) {
      const { container, unmount } = render(<TheKienThuc tt={{ ...CO_SO, state: s }} />)
      const chu = container.textContent ?? ''
      for (const tu of ['index', 'vector', 'Qdrant', 'embed', 'đồng bộ']) {
        expect(chu.toLowerCase()).not.toContain(tu.toLowerCase())
      }
      unmount()
    }
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/components/TheKienThuc.test.tsx`
Expected: FAIL — không resolve được `./TheKienThuc`.

- [ ] **Step 3: Viết component**

Create `src/features/realestate/components/TheKienThuc.tsx`:

```tsx
/**
 * Badge "dữ liệu dự án này đã tới agent chưa".
 *
 * KHÔNG tự gọi API: badge hiện ở hai chỗ (danh sách dự án và header trang chi
 * tiết) và hai chỗ đó dùng chung MỘT query — mỗi badge tự tra là một request cho
 * mỗi hàng của bảng.
 *
 * Chữ trên badge cố ý không có "index"/"kho vector"/"đồng bộ": người đọc nó là
 * biên tập viên nội dung, và họ cần biết dữ liệu của mình đã tới agent chưa.
 */
import type { TrangThaiKb } from '../api'

const NEN: Record<TrangThaiKb['state'], string> = {
  synced: 'text-badge-ok-fg',
  running: 'text-ac',
  stale: 'text-badge-warn-fg',
  never: 'text-muted',
  error: 'text-badge-err-fg',
}

function chu(tt: TrangThaiKb): string {
  switch (tt.state) {
    case 'synced':
      return '● Agent đã có bản mới nhất'
    case 'running':
      return tt.total > 0
        ? `◐ Đang nạp — ${Math.max(tt.total - tt.pending, 0)}/${tt.total}`
        : '◐ Đang nạp…'
    case 'stale':
      return `△ ${tt.staleCount} mục chưa nạp`
    case 'never':
      return '○ Chưa nạp lần nào'
    case 'error':
      return `✕ ${tt.errorCount} mục lỗi`
  }
}

export function TheKienThuc({ tt }: { tt: TrangThaiKb | undefined }) {
  if (!tt) return null
  return (
    <span className={`whitespace-nowrap text-[12px] ${NEN[tt.state]}`} title={nhanChiTiet(tt)}>
      {chu(tt)}
    </span>
  )
}

function nhanChiTiet(tt: TrangThaiKb): string {
  if (!tt.lastSyncedAt) return 'Chưa nạp lần nào'
  return `Lần nạp cuối: ${new Date(tt.lastSyncedAt).toLocaleString('vi-VN')}`
}
```

⚠ Ba lớp màu `text-badge-ok-fg`/`text-badge-warn-fg`/`text-badge-err-fg` phải tồn tại trong theme. `text-badge-warn-fg` đã dùng ở `DuAnList.tsx`. **Kiểm hai lớp còn lại** bằng `rg "badge-ok-fg|badge-err-fg" src` — nếu không có, dùng lớp tương đương đang có trong repo thay vì thêm token mới.

- [ ] **Step 4: Chạy test**

Run: `npm run test -- src/features/realestate/components/TheKienThuc.test.tsx`
Expected: PASS 8/8.

- [ ] **Step 5: In lệnh commit**

```bash
git add src/features/realestate/components/TheKienThuc.tsx src/features/realestate/components/TheKienThuc.test.tsx
git commit -m "feat(re): badge trạng thái nạp kiến thức"
```

---

## Task 13: `useTrangThaiKb` — query có poll dừng được

**Files:**
- Create: `src/features/realestate/useTrangThaiKb.ts`
- Test: `src/features/realestate/useTrangThaiKb.test.tsx`

**Interfaces:**
- Consumes: `trangThaiKb()` (Task 11)
- Produces:
  ```ts
  export function useTrangThaiKb(): {
    theoMa: Record<string, TrangThaiKb>
    dangTai: boolean
  }
  ```
  `queryKey` là `['re', 'kb-status']`.

- [ ] **Step 1: Viết test trước**

Create `src/features/realestate/useTrangThaiKb.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from './api'
import { useTrangThaiKb } from './useTrangThaiKb'

function boc() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const MOT: api.TrangThaiKb = {
  projectCode: 'NPLB',
  state: 'synced',
  pending: 0,
  total: 5,
  staleCount: 0,
  errorCount: 0,
  lastSyncedAt: null,
}

describe('useTrangThaiKb', () => {
  it('tra được theo mã dự án', async () => {
    vi.spyOn(api, 'trangThaiKb').mockResolvedValue([MOT])
    const { result } = renderHook(() => useTrangThaiKb(), { wrapper: boc() })
    await waitFor(() => expect(result.current.theoMa.NPLB?.state).toBe('synced'))
  })

  it('KHÔNG poll khi không có dự án nào đang nạp', async () => {
    const goi = vi.spyOn(api, 'trangThaiKb').mockResolvedValue([MOT])
    vi.useFakeTimers()
    renderHook(() => useTrangThaiKb(), { wrapper: boc() })
    await vi.advanceTimersByTimeAsync(30_000)
    vi.useRealTimers()
    expect(goi).toHaveBeenCalledTimes(1)
  })

  it('poll khi có dự án đang nạp', async () => {
    const goi = vi
      .spyOn(api, 'trangThaiKb')
      .mockResolvedValue([{ ...MOT, state: 'running', pending: 2 }])
    vi.useFakeTimers()
    renderHook(() => useTrangThaiKb(), { wrapper: boc() })
    await vi.advanceTimersByTimeAsync(10_000)
    vi.useRealTimers()
    expect(goi.mock.calls.length).toBeGreaterThan(1)
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/useTrangThaiKb.test.tsx`
Expected: FAIL — không resolve `./useTrangThaiKb`.

- [ ] **Step 3: Viết hook**

Create `src/features/realestate/useTrangThaiKb.ts`:

```ts
/**
 * MỘT query cho cả màn: badge xuất hiện ở mọi hàng của bảng dự án, nên mỗi badge
 * tự tra là N request cho một trang.
 *
 * `refetchInterval` là HÀM chứ không phải số: nó phải TẮT khi không còn dự án nào
 * đang nạp. Một interval cố định là một request mỗi 3 giây suốt thời gian người
 * dùng mở tab, kể cả khi không có gì thay đổi.
 */
import { useQuery } from '@tanstack/react-query'

import { trangThaiKb, type TrangThaiKb } from './api'

const NHIP_MS = 3_000

export function useTrangThaiKb() {
  const q = useQuery({
    queryKey: ['re', 'kb-status'],
    queryFn: trangThaiKb,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((t) => t.state === 'running') ? NHIP_MS : false,
  })

  const theoMa: Record<string, TrangThaiKb> = {}
  for (const t of q.data ?? []) theoMa[t.projectCode] = t

  return { theoMa, dangTai: q.isPending }
}
```

- [ ] **Step 4: Chạy test**

Run: `npm run test -- src/features/realestate/useTrangThaiKb.test.tsx`
Expected: PASS 3/3.

- [ ] **Step 5: In lệnh commit**

```bash
git add src/features/realestate/useTrangThaiKb.ts src/features/realestate/useTrangThaiKb.test.tsx
git commit -m "feat(re): hook trạng thái nạp kiến thức, poll tự dừng"
```

---

## Task 14: `NutNapKienThuc` — nút, menu, hộp xác nhận

**Files:**
- Create: `src/features/realestate/components/NutNapKienThuc.tsx`
- Test: `src/features/realestate/components/NutNapKienThuc.test.tsx`

**Interfaces:**
- Consumes: `napKienThuc()` (Task 11), `TrangThaiKb` (Task 11)
- Produces: `export function NutNapKienThuc({ projectCode, tt }: { projectCode: string; tt: TrangThaiKb | undefined }): JSX.Element`
- Hành vi: menu 2 mục; mục "Nạp lại toàn bộ" mở hộp xác nhận nêu `total` mục; nút vô hiệu hoá khi `tt.state === 'running'`; sau khi gọi thành công thì `invalidateQueries(['re','kb-status'])`.

- [ ] **Step 1: Viết test trước**

Create `src/features/realestate/components/NutNapKienThuc.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import { NutNapKienThuc } from './NutNapKienThuc'

function boc({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const TT: api.TrangThaiKb = {
  projectCode: 'NPLB',
  state: 'stale',
  pending: 0,
  total: 12,
  staleCount: 3,
  errorCount: 0,
  lastSyncedAt: null,
}

describe('NutNapKienThuc', () => {
  it('nạp phần đã đổi gọi mode delta, không hỏi xác nhận', async () => {
    const goi = vi.spyOn(api, 'napKienThuc').mockResolvedValue({ jobId: 1, state: 'queued' })
    render(<NutNapKienThuc projectCode="NPLB" tt={TT} />, { wrapper: boc })

    await userEvent.click(screen.getByRole('button', { name: /Nạp kiến thức cho agent/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Chỉ phần mới thay đổi/ }))

    await waitFor(() => expect(goi).toHaveBeenCalledWith('NPLB', 'delta'))
  })

  it('nạp lại toàn bộ PHẢI qua hộp xác nhận', async () => {
    const goi = vi.spyOn(api, 'napKienThuc').mockResolvedValue({ jobId: 1, state: 'queued' })
    render(<NutNapKienThuc projectCode="NPLB" tt={TT} />, { wrapper: boc })

    await userEvent.click(screen.getByRole('button', { name: /Nạp kiến thức cho agent/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Nạp lại toàn bộ/ }))

    expect(goi).not.toHaveBeenCalled()
    expect(screen.getByText(/12 mục/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Nạp lại toàn bộ$/ }))
    await waitFor(() => expect(goi).toHaveBeenCalledWith('NPLB', 'full'))
  })

  it('huỷ hộp xác nhận thì không gọi gì', async () => {
    const goi = vi.spyOn(api, 'napKienThuc').mockResolvedValue({ jobId: 1, state: 'queued' })
    render(<NutNapKienThuc projectCode="NPLB" tt={TT} />, { wrapper: boc })

    await userEvent.click(screen.getByRole('button', { name: /Nạp kiến thức cho agent/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Nạp lại toàn bộ/ }))
    await userEvent.click(screen.getByRole('button', { name: /Huỷ/ }))

    expect(goi).not.toHaveBeenCalled()
  })

  it('đang nạp thì nút bị vô hiệu hoá', () => {
    render(<NutNapKienThuc projectCode="NPLB" tt={{ ...TT, state: 'running', pending: 5 }} />, {
      wrapper: boc,
    })
    expect(screen.getByRole('button', { name: /Đang nạp/ })).toBeDisabled()
  })

  it('menu nói rõ số mục sẽ nạp ở lựa chọn delta', async () => {
    render(<NutNapKienThuc projectCode="NPLB" tt={TT} />, { wrapper: boc })
    await userEvent.click(screen.getByRole('button', { name: /Nạp kiến thức cho agent/ }))
    expect(screen.getByRole('menuitem', { name: /3 mục/ })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/components/NutNapKienThuc.test.tsx`
Expected: FAIL — không resolve `./NutNapKienThuc`.

- [ ] **Step 3: Viết component**

Create `src/features/realestate/components/NutNapKienThuc.tsx`:

```tsx
/**
 * Nút nạp dữ liệu dự án cho agent. Hai lựa chọn, và lựa chọn tốn tiền phải qua
 * xác nhận: "nạp lại toàn bộ" gọi embed cho MỌI mục kể cả mục không đổi.
 *
 * Cập nhật lạc quan sang "Đang nạp" ngay khi bấm: job chạy ở worker nên response
 * 202 về trước khi có gì thay đổi, và một nút không phản hồi sẽ bị bấm lại.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { napKienThuc, type CheDoNap, type TrangThaiKb } from '../api'

const NUT =
  'rounded-md border border-border-strong px-2.5 py-1 text-[13px] hover:border-ac hover:text-acd disabled:opacity-50'
const MUC = 'block w-full px-3 py-2 text-left text-[13px] hover:bg-acs'

export function NutNapKienThuc({
  projectCode,
  tt,
}: {
  projectCode: string
  tt: TrangThaiKb | undefined
}) {
  const qc = useQueryClient()
  const [moMenu, setMoMenu] = useState(false)
  const [hoiToanBo, setHoiToanBo] = useState(false)

  const m = useMutation({
    mutationFn: (mode: CheDoNap) => napKienThuc(projectCode, mode),
    onSuccess: () => {
      setMoMenu(false)
      setHoiToanBo(false)
      void qc.invalidateQueries({ queryKey: ['re', 'kb-status'] })
    },
  })

  const dangNap = tt?.state === 'running' || m.isPending
  const soLech = tt?.staleCount ?? 0
  const soTong = tt?.total ?? 0

  return (
    <div className="relative inline-block">
      <button
        type="button"
        className={NUT}
        disabled={dangNap}
        aria-haspopup="menu"
        aria-expanded={moMenu}
        onClick={() => setMoMenu((v) => !v)}
      >
        {dangNap ? 'Đang nạp…' : 'Nạp kiến thức cho agent ▾'}
      </button>

      {moMenu && !hoiToanBo && (
        <div
          role="menu"
          className="absolute right-0 z-10 mt-1 w-64 rounded-md border border-border bg-surface shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            className={MUC}
            onClick={() => m.mutate('delta')}
          >
            Chỉ phần mới thay đổi{soLech > 0 ? ` (${soLech} mục)` : ''}
          </button>
          <button
            type="button"
            role="menuitem"
            className={MUC}
            onClick={() => setHoiToanBo(true)}
          >
            Nạp lại toàn bộ dự án
          </button>
        </div>
      )}

      {hoiToanBo && (
        <div className="absolute right-0 z-10 mt-1 w-80 rounded-md border border-border bg-surface p-3 shadow-lg">
          <p className="text-[13px]">
            Nạp lại toàn bộ {soTong > 0 ? `${soTong} mục` : 'dự án'} — kể cả mục không thay đổi.
            Việc này mất nhiều thời gian hơn và tốn chi phí xử lý.
          </p>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              className={NUT}
              onClick={() => {
                setHoiToanBo(false)
                setMoMenu(false)
              }}
            >
              Huỷ
            </button>
            <button type="button" className={NUT} onClick={() => m.mutate('full')}>
              Nạp lại toàn bộ
            </button>
          </div>
        </div>
      )}

      {m.error && (
        <p className="mt-1 text-[12px] text-badge-err-fg">Không gửi được yêu cầu. Thử lại.</p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Chạy test**

Run: `npm run test -- src/features/realestate/components/NutNapKienThuc.test.tsx`
Expected: PASS 5/5.

- [ ] **Step 5: In lệnh commit**

```bash
git add src/features/realestate/components/NutNapKienThuc.tsx src/features/realestate/components/NutNapKienThuc.test.tsx
git commit -m "feat(re): nút nạp kiến thức với hai lựa chọn và hộp xác nhận"
```

---

## Task 15: Gắn badge và nút vào hai màn

**Files:**
- Modify: `src/features/realestate/components/DuAnList.tsx`
- Modify: `src/features/realestate/components/KhungDuAn.tsx`
- Test: `src/features/realestate/components/DuAnList.kb.test.tsx`

**Interfaces:**
- Consumes: `useTrangThaiKb()` (Task 13), `TheKienThuc` (Task 12), `NutNapKienThuc` (Task 14)
- Produces: không export gì mới

- [ ] **Step 1: Viết test trước**

Create `src/features/realestate/components/DuAnList.kb.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import { DuAnList } from './DuAnList'

function boc({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('DuAnList — cột kiến thức agent', () => {
  it('mỗi hàng hiện badge trạng thái của đúng dự án đó', async () => {
    vi.spyOn(api, 'danhSachDuAn').mockResolvedValue({
      items: [
        {
          id: 1,
          projectCode: 'NPLB',
          name: 'Noble Palace',
          category: [],
          region: '',
          address: '',
          investor: '',
          developer: '',
        },
      ] as unknown as api.DuAn[],
      nextCursor: null,
      total: 1,
    })
    vi.spyOn(api, 'trangThaiKb').mockResolvedValue([
      {
        projectCode: 'NPLB',
        state: 'stale',
        pending: 0,
        total: 9,
        staleCount: 4,
        errorCount: 0,
        lastSyncedAt: null,
      },
    ])

    render(<DuAnList />, { wrapper: boc })

    await waitFor(() => expect(screen.getByText(/4 mục chưa nạp/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Nạp kiến thức cho agent/ })).toBeInTheDocument()
  })
})
```

⚠ `DuAnList` dùng `useNavigate` của TanStack Router. Nếu test đỏ vì thiếu router context, bọc thêm bằng đúng helper mà các test hiện có của repo dùng — tìm bằng `rg "createRouter|RouterProvider" src --glob '*.test.tsx'` và theo nếp đó. **Không** viết helper thứ hai.

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/components/DuAnList.kb.test.tsx`
Expected: FAIL — không tìm thấy chữ "4 mục chưa nạp".

- [ ] **Step 3: Sửa `DuAnList.tsx`**

Thêm import:

```tsx
import { useTrangThaiKb } from '../useTrangThaiKb'
import { NutNapKienThuc } from './NutNapKienThuc'
import { TheKienThuc } from './TheKienThuc'
```

Thêm cột vào `COT` (trước cột hành động rỗng):

```tsx
const COT: readonly Cot[] = [
  { nhan: 'Dự án' },
  { nhan: 'Loại hình' },
  { nhan: 'Vị trí' },
  { nhan: 'Kinh doanh' },
  { nhan: 'Kiến thức agent' },
  { nhan: '', phai: true },
]
```

Trong `BangDuAn`, gọi hook:

```tsx
  const kb = useTrangThaiKb()
```

Thêm `<td>` mới ngay trước `<td>` chứa nút xoá:

```tsx
                      <td className={`${TD_PHU} whitespace-nowrap`}>
                        <div className="flex flex-col items-start gap-1">
                          <TheKienThuc tt={kb.theoMa[d.projectCode]} />
                          <NutNapKienThuc projectCode={d.projectCode} tt={kb.theoMa[d.projectCode]} />
                        </div>
                      </td>
```

⚠ `Hang` có `mo={() => nav(...)}` trên cả hàng — bấm nút trong ô này sẽ **lan lên** và mở form dự án. Chặn bằng `onClick={(e) => e.stopPropagation()}` trên `<div>` bọc, hoặc theo đúng cách mà ô nút xoá hiện tại đã dùng (đọc `NutIcon` xem nó có `stopPropagation` sẵn không — nếu có, làm giống).

- [ ] **Step 4: Sửa `KhungDuAn.tsx`**

Thêm import như trên, rồi đổi khối `<DuongDan>` để badge và nút đứng cạnh `<h2>`:

```tsx
      <DuongDan>
        <Link to="/projects" className={DUONG_VE}>
          Kiến thức
        </Link>
        <h2 className="text-[17px] font-semibold text-fg">
          {code ? (
            <>
              <span className="font-mono">{code}</span>
              {ten ? ` · ${ten}` : ''}
            </>
          ) : (
            'Dự án mới'
          )}
        </h2>
        {code && (
          <div className="ml-auto flex items-center gap-2">
            <TheKienThuc tt={kb.theoMa[code]} />
            <NutNapKienThuc projectCode={code} tt={kb.theoMa[code]} />
          </div>
        )}
      </DuongDan>
```

Và gọi `const kb = useTrangThaiKb()` trong thân component. ⚠ `DuongDan` phải là flex container để `ml-auto` có tác dụng — đọc nó và nếu chưa phải thì đặt badge+nút **ngoài** `DuongDan`, trong một hàng flex riêng ngay dưới, thay vì sửa `DuongDan` (nó dùng ở nhiều form khác).

- [ ] **Step 5: Chạy test**

```bash
npm run test -- src/features/realestate
npx tsc --noEmit
npm run lint
```

Expected: PASS.

- [ ] **Step 6: In lệnh commit**

```bash
git add src/features/realestate/components/
git commit -m "feat(re): badge + nút nạp kiến thức ở danh sách dự án và header dự án"
```

---

## Task 16: Mô tả tự động hiện lên và sửa được — kho media

**Files:**
- Create: `src/features/realestate/useTrangThaiEnrich.ts`
- Modify: `src/features/realestate/components/VungMedia.tsx`
- Test: `src/features/realestate/useTrangThaiEnrich.test.tsx`
- Test: `src/features/realestate/components/VungMedia.caption.test.tsx`

**Interfaces:**
- Consumes: `trangThaiEnrich()`, `taoLaiMoTa()`, `suaMedia()` (Task 11 + api có sẵn)
- Produces:
  ```ts
  export function useTrangThaiEnrich(projectCode: string): {
    dangChay: Set<number>
    lamMoi: () => void
  }
  ```

Đây là task **quan trọng nhất của phần B**: trước đợt này caption trong kho media **chỉ đọc**, nên mô tả tự động hiện ra mà người dùng không sửa được.

- [ ] **Step 1: Viết test cho hook**

Create `src/features/realestate/useTrangThaiEnrich.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from './api'
import { useTrangThaiEnrich } from './useTrangThaiEnrich'

function boc() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

describe('useTrangThaiEnrich', () => {
  it('gom recordId của các job đang chạy', async () => {
    vi.spyOn(api, 'trangThaiEnrich').mockResolvedValue([
      { entity: 'media', recordId: 7, state: 'running', message: '' },
      { entity: 'media', recordId: 8, state: 'success', message: 'xong' },
    ])
    const { result } = renderHook(() => useTrangThaiEnrich('NPLB'), { wrapper: boc() })
    await waitFor(() => expect(result.current.dangChay.has(7)).toBe(true))
    expect(result.current.dangChay.has(8)).toBe(false)
  })

  it('KHÔNG poll khi mọi job đã xong', async () => {
    const goi = vi
      .spyOn(api, 'trangThaiEnrich')
      .mockResolvedValue([{ entity: 'media', recordId: 8, state: 'success', message: '' }])
    vi.useFakeTimers()
    renderHook(() => useTrangThaiEnrich('NPLB'), { wrapper: boc() })
    await vi.advanceTimersByTimeAsync(30_000)
    vi.useRealTimers()
    expect(goi).toHaveBeenCalledTimes(1)
  })

  it('poll khi còn job chờ', async () => {
    const goi = vi
      .spyOn(api, 'trangThaiEnrich')
      .mockResolvedValue([{ entity: 'media', recordId: 7, state: 'queued', message: '' }])
    vi.useFakeTimers()
    renderHook(() => useTrangThaiEnrich('NPLB'), { wrapper: boc() })
    await vi.advanceTimersByTimeAsync(10_000)
    vi.useRealTimers()
    expect(goi.mock.calls.length).toBeGreaterThan(1)
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/useTrangThaiEnrich.test.tsx`
Expected: FAIL — không resolve `./useTrangThaiEnrich`.

- [ ] **Step 3: Viết hook**

Create `src/features/realestate/useTrangThaiEnrich.ts`:

```ts
/**
 * Job tạo mô tả chạy ở worker nên mất vài giây đến vài phút. Hook này poll trong
 * lúc còn job, dừng ngay khi hết, và làm mới danh sách media để chữ vừa sinh
 * hiện vào ô mà không cần tải lại trang.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { trangThaiEnrich } from './api'

const NHIP_MS = 3_000
const CHUA_XONG = new Set(['queued', 'running'])

export function useTrangThaiEnrich(projectCode: string) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['re', projectCode, 'enrich-status'],
    queryFn: () => trangThaiEnrich(projectCode),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((m) => CHUA_XONG.has(m.state)) ? NHIP_MS : false,
  })

  const soChuaXong = (q.data ?? []).filter((m) => CHUA_XONG.has(m.state)).length
  const truoc = useRef(soChuaXong)
  useEffect(() => {
    // Job vừa xong ⇒ chữ đã nằm trong Aurora, phải tải lại danh sách để ô có nội dung.
    if (truoc.current > 0 && soChuaXong === 0) {
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'documents'] })
    }
    truoc.current = soChuaXong
  }, [soChuaXong, projectCode, qc])

  return {
    dangChay: new Set((q.data ?? []).filter((m) => CHUA_XONG.has(m.state)).map((m) => m.recordId)),
    lamMoi: () => void q.refetch(),
  }
}
```

- [ ] **Step 4: Chạy test hook**

Run: `npm run test -- src/features/realestate/useTrangThaiEnrich.test.tsx`
Expected: PASS 3/3.

- [ ] **Step 5: Viết test cho ô caption sửa được**

Create `src/features/realestate/components/VungMedia.caption.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import { VungMedia } from './VungMedia'

function boc({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const ANH = {
  id: 7,
  projectCode: 'NPLB',
  contentType: 'image',
  category: 'tong_quan',
  mediaUrl: 'NPLB/a.jpg',
  caption: 'Mô tả do máy tạo',
  thumbUrl: null,
  zoneCode: null,
  unitCode: null,
} as unknown as api.Media

describe('VungMedia — mô tả sửa được', () => {
  it('mô tả hiện trong một ô nhập, không phải chữ chỉ đọc', () => {
    render(
      <VungMedia projectCode="NPLB" category="tong_quan" nhan="Tổng quan" anh={[ANH]} lamMoi={() => {}} />,
      { wrapper: boc },
    )
    const o = screen.getByDisplayValue('Mô tả do máy tạo')
    expect(o).toBeEnabled()
  })

  it('sửa rồi rời ô thì lưu', async () => {
    const goi = vi.spyOn(api, 'suaMedia').mockResolvedValue(ANH)
    render(
      <VungMedia projectCode="NPLB" category="tong_quan" nhan="Tổng quan" anh={[ANH]} lamMoi={() => {}} />,
      { wrapper: boc },
    )
    const o = screen.getByDisplayValue('Mô tả do máy tạo')
    await userEvent.clear(o)
    await userEvent.type(o, 'Tôi sửa lại')
    await userEvent.tab()

    await waitFor(() =>
      expect(goi).toHaveBeenCalledWith('NPLB', 7, expect.objectContaining({ caption: 'Tôi sửa lại' })),
    )
  })

  it('không gọi lưu khi chữ không đổi', async () => {
    const goi = vi.spyOn(api, 'suaMedia').mockResolvedValue(ANH)
    render(
      <VungMedia projectCode="NPLB" category="tong_quan" nhan="Tổng quan" anh={[ANH]} lamMoi={() => {}} />,
      { wrapper: boc },
    )
    await userEvent.click(screen.getByDisplayValue('Mô tả do máy tạo'))
    await userEvent.tab()
    expect(goi).not.toHaveBeenCalled()
  })

  it('có nút tạo lại mô tả', async () => {
    const goi = vi.spyOn(api, 'taoLaiMoTa').mockResolvedValue({ jobId: 1, state: 'queued' })
    render(
      <VungMedia projectCode="NPLB" category="tong_quan" nhan="Tổng quan" anh={[ANH]} lamMoi={() => {}} />,
      { wrapper: boc },
    )
    await userEvent.click(screen.getByRole('button', { name: /Tạo lại mô tả/ }))
    await waitFor(() => expect(goi).toHaveBeenCalledWith(7))
  })
})
```

- [ ] **Step 6: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/components/VungMedia.caption.test.tsx`
Expected: FAIL — `getByDisplayValue` không thấy gì (caption đang là `<p>`).

- [ ] **Step 7: Sửa `VungMedia.tsx`**

Thêm import:

```tsx
import { suaMedia, taoLaiMoTa } from '../api'
import { useTrangThaiEnrich } from '../useTrangThaiEnrich'
```

Thêm component con trong cùng file (nó chỉ dùng ở đây):

```tsx
/** Ô mô tả của một ảnh: sửa được, tự lưu khi rời ô, và nói rõ khi máy đang viết. */
function OMoTa({
  projectCode,
  m,
  dangTao,
  lamMoi,
}: {
  projectCode: string
  m: Media
  dangTao: boolean
  lamMoi: () => void
}) {
  const [nhap, setNhap] = useState(m.caption ?? '')

  const mLuu = useMutation({
    mutationFn: (caption: string) => suaMedia(projectCode, m.id, { caption }),
    onSuccess: lamMoi,
  })
  const mTao = useMutation({
    mutationFn: () => taoLaiMoTa(m.id),
    onSuccess: lamMoi,
  })

  // Job vừa ghi mô tả mới vào Aurora ⇒ prop đổi, ô phải theo. Không đồng bộ lại
  // là người dùng nhìn ô rỗng trong khi dữ liệu đã có.
  useEffect(() => setNhap(m.caption ?? ''), [m.caption])

  if (dangTao) {
    return <p className="mt-1 text-[12px] text-ac">◐ Đang tạo mô tả…</p>
  }

  return (
    <div className="mt-1 space-y-1">
      <input
        type="text"
        aria-label={`Mô tả ảnh ${m.id}`}
        placeholder="Mô tả (agent dùng câu này khi gửi ảnh cho khách)"
        value={nhap}
        onChange={(e) => setNhap(e.target.value)}
        onBlur={() => {
          if (nhap !== (m.caption ?? '')) mLuu.mutate(nhap)
        }}
        className="w-full rounded border border-border-field px-2 py-1 text-[12px]"
      />
      <button
        type="button"
        className="text-[12px] text-muted hover:text-acd"
        onClick={() => mTao.mutate()}
        disabled={mTao.isPending}
      >
        ↻ Tạo lại mô tả
      </button>
    </div>
  )
}
```

Trong `VungMedia`, gọi hook và thay chỗ hiện caption chỉ đọc:

```tsx
  const enrich = useTrangThaiEnrich(projectCode)
```

Thay dòng `<p className="mt-1 truncate text-[12px] text-muted" title={m.caption}>{m.caption || '(chưa có chú thích)'}</p>` bằng:

```tsx
              <OMoTa
                projectCode={projectCode}
                m={m}
                dangTao={enrich.dangChay.has(m.id)}
                lamMoi={lamMoi}
              />
```

Và thay dòng `<p className="text-[13px] text-muted">{anhChinh.caption || '(chưa có chú thích)'}</p>` (khối ảnh chính) bằng cùng component đó với `m={anhChinh}`.

Thêm `useEffect`, `useState`, `useMutation` vào import nếu chưa có.

- [ ] **Step 8: Chạy test**

```bash
npm run test -- src/features/realestate
npx tsc --noEmit
npm run lint
```

Expected: PASS.

- [ ] **Step 9: In lệnh commit**

```bash
git add src/features/realestate/useTrangThaiEnrich.ts src/features/realestate/useTrangThaiEnrich.test.tsx src/features/realestate/components/VungMedia.tsx src/features/realestate/components/VungMedia.caption.test.tsx
git commit -m "feat(re): mô tả ảnh sửa được ngay trong kho media, có trạng thái đang tạo"
```

---

## Task 17: Trạng thái mô tả ở ô cover/map và ở tab Tài liệu

**Files:**
- Modify: `src/features/realestate/components/OMedia.tsx`
- Modify: `src/features/realestate/components/TaiLieuTab.tsx`
- Test: `src/features/realestate/components/TaiLieuTab.enrich.test.tsx`

**Interfaces:**
- Consumes: `useTrangThaiEnrich()` (Task 16)
- Produces: không export gì mới

- [ ] **Step 1: Viết test trước**

Create `src/features/realestate/components/TaiLieuTab.enrich.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import { TaiLieuTab } from './TaiLieuTab'

function boc({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const TL = {
  id: 5,
  projectCode: 'NPLB',
  title: 'Bảng giá Q3',
  loai: 'csbh',
  body: '',
  fileUrl: 'NPLB/bang-gia.pdf',
  status: 'published',
} as unknown as api.TaiLieu

describe('TaiLieuTab — trạng thái bóc nội dung', () => {
  it('đang bóc thì nói rõ, không hiện "0 ký tự"', async () => {
    vi.spyOn(api, 'danhSachTaiLieu').mockResolvedValue({
      items: [TL],
      nextCursor: null,
      total: 1,
    } as unknown as api.Trang<api.TaiLieu>)
    vi.spyOn(api, 'trangThaiEnrich').mockResolvedValue([
      { entity: 'documents', recordId: 5, state: 'running', message: '' },
    ])

    render(<TaiLieuTab projectCode="NPLB" />, { wrapper: boc })

    await waitFor(() => expect(screen.getByText(/Đang bóc nội dung tệp/)).toBeInTheDocument())
  })
})
```

⚠ Đọc chữ ký thật của `TaiLieuTab` (`rg "export function TaiLieuTab" -A 5`) và sửa prop trong test cho khớp trước khi chạy.

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npm run test -- src/features/realestate/components/TaiLieuTab.enrich.test.tsx`
Expected: FAIL — không thấy chữ "Đang bóc nội dung tệp".

- [ ] **Step 3: Sửa `TaiLieuTab.tsx`**

Gọi hook trong component:

```tsx
  const enrich = useTrangThaiEnrich(projectCode)
```

Ở chỗ hiện `{t.body ? ... : ...}` trong bảng (dòng ~339, chỗ in `{t.body.length} ký tự`), bọc thêm nhánh đang chạy:

```tsx
                        {enrich.dangChay.has(t.id) ? (
                          <span className="text-[12px] text-ac">◐ Đang bóc nội dung tệp…</span>
                        ) : t.body ? (
                          <span className="text-[12px] text-muted">{t.body.length} ký tự</span>
                        ) : (
                          <span className="text-[12px] text-muted">(chưa có nội dung)</span>
                        )}
```

Giữ nguyên cấu trúc và class của nhánh `t.body` hiện có — chỉ thêm nhánh đầu.

Viết lại docstring đầu file: bỏ `⚠ body NHẬP TAY`, thay bằng một câu nói `body` do job `kb_enrich` bóc từ tệp và người dùng sửa được, và luật "chỉ ghi khi ô đang rỗng, trừ khi thay tệp".

- [ ] **Step 4: Sửa `OMedia.tsx`**

Ô caption ở đây đã sửa được, chỉ cần thêm trạng thái và nút tạo lại. `OMedia` **không** biết `projectCode` — kiểm chữ ký của nó trước; nếu thiếu, **không** thêm prop chỉ để gọi hook: thay vào đó chỉ thêm nút "↻ Tạo lại mô tả" (dùng `taoLaiMoTa(giaTri.id)`, chỉ hiện khi `giaTri.id` tồn tại) và bỏ qua phần trạng thái. Trạng thái đầy đủ đã có ở kho media (Task 16), nơi người dùng làm việc với ảnh nhiều nhất.

Viết lại docstring: bỏ `⚠ caption NHẬP TAY`, nói rõ mô tả có thể do job tạo và người dùng sửa được.

- [ ] **Step 5: Chạy test**

```bash
npm run test -- src/features/realestate
npx tsc --noEmit
npm run lint
```

Expected: PASS.

- [ ] **Step 6: In lệnh commit**

```bash
git add src/features/realestate/components/
git commit -m "feat(re): trạng thái bóc nội dung tệp và nút tạo lại mô tả"
```

---

## Task 18: Chốt — chạy hai repo và soát bằng mắt

**Files:** không sửa gì mới

- [ ] **Step 1: Chạy cổng hai bên**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend && make check
cd /home/thanhhai/Desktop/odyssey-portal-frontend && npm run lint && npx tsc --noEmit && npm run test
```

- [ ] **Step 2: Soát bằng mắt trên app thật**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
make up          # nếu chưa chạy
make api         # cổng 8100
make worker      # hàng đợi control.jobs — BẮT BUỘC, không có nó thì job nằm mãi ở 'queued'
```

Frontend: `npm run dev` (cổng 5273). Đăng nhập `dang@anphuland.vn` / `odyssey-dev`.

Kiểm bảy điều:

1. `/projects` — cột "Kiến thức agent" có badge ở mọi hàng.
2. Bấm "Nạp kiến thức cho agent" → "Chỉ phần mới thay đổi" → badge đổi sang "◐ Đang nạp", con số giảm dần, rồi về "● Agent đã có bản mới nhất". Poll **dừng** sau đó (mở DevTools › Network, không còn request `kb-status` mới).
3. Bấm lại "Chỉ phần mới thay đổi" ngay lần nữa → worker log nói "nội dung không đổi, giữ nguyên", **không** gọi embed.
4. "Nạp lại toàn bộ dự án" → có hộp xác nhận nêu số mục; Huỷ thì không có job nào sinh ra.
5. Tab Media → thêm một ảnh → ô mô tả hiện "◐ Đang tạo mô tả…" rồi tự có chữ; sửa chữ đó rồi rời ô → tải lại trang thấy chữ đã lưu.
6. Xoá một ảnh đã nạp → bảng `control.jobs` có job `kb_delete` mang đúng `record_id`.
7. Đổi `status` một dự án đã nạp sang `draft` → có job `kb_delete` mang `anchor_code`.

- [ ] **Step 3: Đưa đoạn cập nhật `CLAUDE.md` cho người dùng**

Gộp đoạn đã viết ở Task 10 Step 2 với phần frontend, đưa cho người dùng tự dán. **Không tự sửa file đó.**

---

## Self-review

**Spec coverage:**

| Mục spec | Task |
|---|---|
D1 nút hai lựa chọn | 9 (backend `mode`), 14 (nút + xác nhận) |
D2 delta so `content_hash` | 3, 4 |
D3 xoá/unpublish vẫn tự động | 8, 9 |
D4 badge từ `updated_at` vs `indexed_at` | 6 |
D5 `skipped` chạm `indexed_at` | 1, 2, 4 |
D6 thay ảnh/tệp ⇒ đè mô tả | 9 |
D7 từ ngữ "nạp kiến thức cho agent" | 12 (kèm test cấm từ kỹ thuật), 14 |
D8 badge + nút ở hai chỗ | 15 |
D9 `reconcile` ngoài scope | không có task — đúng ý |
D10 cột `project_code` | 1, 6, 7 |
§3.1 xoá phân khu | 9 |
§4.2 hash sau breadcrumb | 3 (`test_doi_ten_du_an_lam_doi_hash`) |
§4.4 thứ tự route | 6 (`test_duong_dan_khong_bi_route_du_an_an_mat`) |
§5.1 `VungMedia` caption sửa được | 16 |
§6 bất đồng bộ | Global Constraints; test poll-tự-dừng ở 13, 16 |
§7 xử lý lỗi | 4 (`state='error'` vẫn nạp lại), 14 (nút disabled khi đang chạy) |
§8 bảng test | rải khắp; mọi dòng có task tương ứng |

**Sai lệch so với spec, có ý:**
- Spec §4.3 đặt `project_status()` ở `kb/state/repo.py`. Plan chuyển sang `realestate/repo.py` (Task 6 Step 5) vì luật 3 cấm `realestate` import `kb.state.repo`. `indexed_of_project()` vẫn ở `kb/state/repo.py` — nó do `kb/service.py` gọi.
- Spec §5.1 nêu `OMedia` là nơi hiện trạng thái enrich. Plan hạ xuống: `OMedia` chỉ thêm nút tạo lại, vì nó không nhận `projectCode` và thêm prop chỉ để gọi hook là kéo một phụ thuộc vào component dùng ở nhiều chỗ. Trạng thái đầy đủ ở `VungMedia` (Task 16).

**Chỗ người thực thi phải tự đọc code trước khi viết** (đã ghi ⚠ tại chỗ): tên khoá trong `_tach_payload` (Task 9 Step 6-7) · lớp màu badge có trong theme hay không (Task 12 Step 3) · helper router context của test FE (Task 15 Step 1) · `stopPropagation` trên hàng bảng (Task 15 Step 3) · `DuongDan` có phải flex (Task 15 Step 4) · chữ ký `TaiLieuTab`/`OMedia` (Task 17).
