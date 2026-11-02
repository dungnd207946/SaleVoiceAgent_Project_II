# Usage & Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng module `billing` cho Portal: đọc `billing.usage_events` do agent ghi, quy trách nhiệm theo `agent_key_id`, định giá theo bảng giá có version, và ba màn hình quản lý usage + một màn admin bảng giá.

**Architecture:** Ba tầng bất biến — sự kiện (`usage_events`, agent ghi, không sửa) → bảng giá (`price_version`/`price_item`, versioned theo tenant) → đã định giá (`rated_usage`, snapshot giá + attribution, idempotent, tính lại được). Attribution lấy qua `LEFT JOIN tenant_data.conversations` trên `(tenant_id, session_id)` — an toàn vì cặp đó UNIQUE. Định giá bằng một hàm SQL `billing.rate_usage(from, to)`, không phải Python, để job và test dùng cùng một đường.

**Tech Stack:** FastAPI · asyncpg · Pydantic v2 · Alembic · Postgres 16 · pytest

**Spec:** `docs/build_module_usage&billing/THIET-KE-CHOT.md` (bản chốt) · `docs/build_module_usage&billing/pricing-schema.sql` (DDL đã kiểm chứng) · `docs/build_module_usage&billing/pricing-seed.sql` (khung điền giá) · `docs/build_module_usage&billing/portal-billing-pricing-guide-handoff-from-agent.md` (hướng dẫn công thức từ bên agent)

## Global Constraints

- **Luật 1:** mọi truy vấn bảng có RLS đi qua `tenant_conn()`, TRONG một giao dịch. Đọc ngoài giao dịch trả **0 hàng và im lặng** — không phải lỗi. Áp dụng cho `billing.rated_usage`, `billing.tenant_price_version`, `billing.usage_events`, `tenant_data.conversations`.
- **Luật 2:** bảng mới trong `tenant_data` phải gọi `control.enforce_tenant_isolation()`. Module này KHÔNG thêm bảng `tenant_data` nào.
- **Luật 3:** module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. Import ruột module khác ⇒ `tests/test_module_boundaries.py` đỏ (đọc AST). Dạng import phải là `from portal.modules.x.contracts import Y`, KHÔNG `from portal.modules.x import contracts as z`.
- **Luật 4:** mọi endpoint khai `action` qua `require(action)`.
- **Module = `modules/<ten>/router.py` khai biến tên đúng `ROUTER`.** Tên khác ⇒ endpoint không lên và không có lỗi nào.
- **Hằng vị từ cách ly phải có tên chứa `_CACH_LY`.** Cổng `tests/isolation/test_loc_tenant_o_tang_app.py` regex trên CHÍNH TÊN BIẾN, không expand giá trị runtime. Đặt tên khác (vd `_LOC`) làm cổng mù trước mọi SQL của file.
- **Định danh DB tiếng Anh** (`pricing_basis`, `purpose_unclassified`, `price_item_stt_single_basis`). Docstring/comment tiếng Việt theo nếp repo.
- **Alembic:** `revision` id khác tên file. Head hiện tại là `0942_billing_usage_events`. Một head duy nhất — cổng `tests/unit/test_alembic_mot_head.py`.
- **Hai DSN:** `DATABASE_URL` → `portal_api` (API/worker). `MIGRATOR_URL` → `portal_migrator` (chỉ alembic).
- **Cổng phải xanh trước MR:** `make check` (LÀ HAI LỆNH: `ruff check` + `ruff format --check`), `make test-isolation`.
- **Baseline test đã đỏ sẵn, KHÔNG phải hồi quy:** `tests/modules/test_heartbeat.py` (2 bài, RLS thiếu trên `control.agent_heartbeats`). Đừng cố sửa.
- **Đơn vị tiền VND.** STT thu theo **giây**. `memory`/`warm_cache`/`addressee_gate`/`semcache` **không** tính khách.
- **Không làm tròn ở `rated_usage`** (`numeric(20,10)`). Làm tròn một lần ở tầng hoá đơn.

---

## Phát hiện đã đo, quyết định thiết kế phụ thuộc vào nó

Đọc trước khi làm Task 1 — ba điều này đã kiểm chứng trên DB dev, không phải giả định.

1. **`portal_api` LÀ thành viên của nhóm `agent_all`.** Đo được: `SELECT rolname FROM pg_auth_members … WHERE member = 'portal_api'` → `agent_all`. Hệ quả: `portal_api` đọc được `billing.usage_events` hôm nay (kế thừa GRANT của `agent_all`) và **bị policy `agent_read` chi phối** (`tenant_id = portal.current_tenant()`). Docstring của `0942` viết *"`portal_api` … KHÔNG"* đọc được — **sai với bảng** (đúng với hai view). Đừng tin dòng đó.

2. **Đọc ngoài `tenant_conn()` trả 0 hàng, không báo lỗi.** Đo được: `portal_api` chạy `SELECT count(*) FROM billing.usage_events` ngoài giao dịch → `0` (không phải `permission denied`), vì `current_tenant()` rơi về `current_setting('app.tenant_id')` chưa đặt. Đây là chế độ hỏng im lặng — mọi test đọc usage phải dùng `tenant_conn()`, và phải có một bài canh khẳng định đọc-ngoài-giao-dịch ra 0.

3. **Hai view `usage_by_session`/`usage_by_tenant_month` KHÔNG có GRANT nào.** Đo được: `portal_api` → `ERROR: permission denied for view usage_by_session`. Task 1 phải cấp quyền, hoặc module tự query bảng gốc. **Quyết định: query bảng gốc, không dùng hai view đó** — chúng thiếu `wall_ms` và `channel` (bên agent tự ghi ở §"VIEW có sẵn"), mà `wall_ms` là cơ sở tính tiền của `(stt,'stream')` và `channel` cần cho việc tách hoá đơn. Cấp GRANT SELECT cho chúng vẫn làm (rẻ, để đối soát tay) nhưng code không đọc.

4. **Cổng cách ly KHÔNG quét schema `billing`.** Đo được: `tests/isolation/test_isolation_catalog.py` chỉ quét `nspname = 'tenant_data'` và `nspname = 'control'`. Nghĩa là bảng mới trong `billing` mang `tenant_id` **không có cổng nào canh**. Task 2 mở rộng cổng — nếu bỏ qua thì `rated_usage` (chứa tiền của từng tenant) có thể ship mà không RLS và không gì báo.

---

## File Structure

| File | Trách nhiệm |
|---|---|
| `migrations/versions/0943_billing_pricing.py` | 7 bảng giá/định giá + 2 function + 5 view + GRANT + RLS |
| `migrations/versions/0944_billing_action.py` | Action `billing.read` vào `control.actions` + `role_actions` |
| `migrations/versions/0945_conversations_agent_key_fk.py` | Siết attribution: composite FK + `ON DELETE RESTRICT` |
| `src/portal/modules/billing/contracts.py` | Pydantic Out/In + hằng dùng chung. Mặt tiền cho module khác. |
| `src/portal/modules/billing/repo.py` | SQL thuần, trả `asyncpg.Record`. Không biết HTTP/Pydantic. |
| `src/portal/modules/billing/service.py` | Gọi `billing.rate_usage`, quy tắc bảng giá, ghi audit |
| `src/portal/modules/billing/router.py` | `ROUTER` — 5 endpoint tenant + 4 endpoint admin |
| `src/portal/cli/dinh_gia_usage.py` | Lệnh cho cron: định giá + cửa sổ re-run 48h |
| `tests/modules/billing/conftest.py` | Fixture 2 tenant + key + conversation + usage_events |
| `tests/modules/billing/test_doi_chieu_cong_thuc_agent.py` | **Cổng vàng** — engine phải ra cùng số với query §4 của bên agent |
| `tests/modules/billing/test_rate_usage.py` | Idempotency · khớp giá theo độ cụ thể · cờ billable · STT chọn một |
| `tests/modules/billing/test_repo.py` | Rollup theo key/owner/session + cách ly tenant |
| `tests/modules/billing/test_router.py` | Tầng HTTP: action, phân trang, nhóm "chưa phân loại" |
| `tests/modules/billing/test_cong_canh_bao.py` | 3 view cổng phải rỗng khi bảng giá đủ, và kêu khi thiếu |
| `tests/isolation/test_isolation_catalog.py` | **Sửa:** mở rộng quét sang schema `billing` |

Không sửa `api/registry.py`, không sửa `api/app.py` — registry tự quét `modules/*/router.py`.

---

### Task 1: Migration 0943 — schema bảng giá + định giá

DDL đã được kiểm chứng chạy được trên DB dev (áp trong transaction rồi ROLLBACK, engine ra đúng số đã tính từ fixture). Task này bọc nó vào alembic + thêm GRANT và RLS mà file SQL chưa có.

**Files:**
- Create: `migrations/versions/0943_billing_pricing.py`
- Đọc (nguồn DDL, copy nguyên văn): `docs/build_module_usage&billing/pricing-schema.sql`
- Test: `tests/modules/billing/test_schema_billing.py`

**Interfaces:**
- Consumes: `billing.usage_events` (0942), `control.tenants`, `portal.current_tenant()` (0001)
- Produces: bảng `billing.metric` · `billing.pricing_basis` · `billing.purpose` · `billing.price_version` · `billing.price_item` · `billing.tenant_price_version` · `billing.rated_usage` · `billing.invoice` · `billing.invoice_line`; function `billing.rate_usage(timestamptz, timestamptz) → bigint` · `billing.resolve_price_version(text, timestamptz) → bigint` · `billing.price_item_specificity(text,text,text) → int` · `billing.chan_sua_gia_da_dung() → trigger`; trigger `price_item_bat_bien` trên `billing.price_item`; view `billing.price_coverage_gap` · `billing.purpose_unclassified` · `billing.unbillable_event` · `billing.cost_by_key_day` · `billing.cost_by_component_day`

- [ ] **Step 1: Viết test cổng schema (sẽ đỏ)**

```python
# tests/modules/billing/test_schema_billing.py
"""Cổng: 0943 dựng đủ bảng/function/view và cấp quyền ĐÚNG cho từng role.

Bài quan trọng nhất là test_agent_khong_doc_duoc_bang_gia: `portal_api` LÀ thành
viên nhóm `agent_all`, nên rất dễ cấp quyền cho `agent_all` "cho tiện" và mở luôn
bảng giá cho mọi pod agent. Chiều cấp quyền đúng là cấp cho `portal_api`, không
bao giờ cho `agent_all`.
"""

import asyncpg
import pytest

BANG_MOI = [
    "metric", "pricing_basis", "purpose", "price_version", "price_item",
    "tenant_price_version", "rated_usage", "invoice", "invoice_line",
]
VIEW_MOI = [
    "price_coverage_gap", "purpose_unclassified", "unbillable_event",
    "cost_by_key_day", "cost_by_component_day",
]


async def test_bang_va_view_ton_tai(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for ten in BANG_MOI:
            assert await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", f"billing.{ten}"
            ), f"thiếu bảng billing.{ten}"
        for ten in VIEW_MOI:
            assert await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", f"billing.{ten}"
            ), f"thiếu view billing.{ten}"


async def test_so_dong_hat_giong(pool: asyncpg.Pool) -> None:
    """Ba bảng danh mục phải có dữ liệu hạt giống, không rỗng."""
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM billing.metric") == 8
        assert await conn.fetchval("SELECT count(*) FROM billing.pricing_basis") == 11
        assert await conn.fetchval("SELECT count(*) FROM billing.purpose") == 10
        assert await conn.fetchval(
            "SELECT count(*) FROM billing.purpose WHERE NOT billable"
        ) == 4


async def test_portal_api_doc_duoc(api_dsn: str) -> None:
    """Không có GRANT thì mọi màn hình usage trả 500."""
    conn = await asyncpg.connect(api_dsn)
    try:
        for ten in BANG_MOI + VIEW_MOI:
            await conn.fetchval(f"SELECT count(*) FROM billing.{ten}")
    finally:
        await conn.close()


async def test_agent_khong_doc_duoc_bang_gia(pool: asyncpg.Pool) -> None:
    """`agent_all` KHÔNG được thấy giá. Cấp cho nhóm này là mở cho mọi pod."""
    async with pool.acquire() as conn:
        for ten in ("price_version", "price_item", "rated_usage", "invoice"):
            co = await conn.fetchval(
                "SELECT has_table_privilege('agent_all', $1, 'SELECT')", f"billing.{ten}"
            )
            assert co is False, f"agent_all đọc được billing.{ten}"


async def test_rls_tren_bang_mang_tenant_id(pool: asyncpg.Pool) -> None:
    """Bảng billing mang tenant_id phải có RLS + policy, giống usage_events."""
    async with pool.acquire() as conn:
        for ten in ("rated_usage", "tenant_price_version", "invoice"):
            rls = await conn.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid = $1::regclass",
                f"billing.{ten}",
            )
            assert rls is True, f"billing.{ten} thiếu RLS"
            so_policy = await conn.fetchval(
                "SELECT count(*) FROM pg_policy WHERE polrelid = $1::regclass",
                f"billing.{ten}",
            )
            assert so_policy > 0, f"billing.{ten} có RLS nhưng KHÔNG policy nào"


async def test_status_chi_hai_gia_tri(pool: asyncpg.Pool) -> None:
    """`status` chỉ còn active|inactive, default inactive.

    Bộ giá mới PHẢI ra đời ở trạng thái không áp cho ai — mặc định 'active' nghĩa
    là vừa tạo xong đã tính tiền khách bằng một bộ giá chưa ai nhập đủ ô.
    """
    async with pool.acquire() as conn:
        ck = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'billing.price_version'::regclass AND contype = 'c' "
            "AND pg_get_constraintdef(oid) LIKE '%status%'"
        )
        assert "'active'" in ck and "'inactive'" in ck
        assert "draft" not in ck and "archived" not in ck
        mac_dinh = await conn.fetchval(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'billing' AND table_name = 'price_version' "
            "AND column_name = 'status'"
        )
        assert "inactive" in mac_dinh


async def test_gia_da_sinh_ra_tien_thi_bat_bien(pool: asyncpg.Pool) -> None:
    """Sửa được giá của bộ đang dùng là VIẾT LẠI hoá đơn các kỳ đã chốt.

    Cùng lệ với `control.config_versions` (0200 REVOKE UPDATE, DELETE). Khác ở chỗ
    điều kiện ở đây là ĐỘNG ("đã sinh ra tiền chưa") nên dùng trigger thay vì REVOKE.
    """
    async with pool.acquire() as conn, conn.transaction():
        pv = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency) "
            "VALUES ('pv_t_frozen', 't', 'VND') RETURNING id"
        )
        it = await conn.fetchval(
            "INSERT INTO billing.price_item (price_version_id, component, metric, "
            "unit_price, per_units) VALUES ($1, 'tts', 'units', 2, 1) RETURNING id", pv,
        )
        # chưa sinh ra tiền ⇒ sửa được
        await conn.execute("UPDATE billing.price_item SET unit_price = 3 WHERE id = $1", it)

        ev = await conn.fetchval(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, units)
               VALUES ('t_frozen', 's', 'chat', 0, 'tts', 'conversation', 10)
               RETURNING event_id"""
        )
        await conn.execute(
            """INSERT INTO billing.rated_usage
               (event_id, metric, tenant_id, occurred_at, component, purpose,
                provider, model, price_version_id, quantity, unit_price, per_units,
                amount, currency)
               VALUES ($1, 'units', 't_frozen', now(), 'tts', 'conversation',
                       '', '', $2, 10, 3, 1, 30, 'VND')""", ev, pv,
        )
        with pytest.raises(asyncpg.PostgresError, match="da sinh ra tien"):
            await conn.execute(
                "UPDATE billing.price_item SET unit_price = 9999 WHERE id = $1", it)


async def test_stt_chi_mot_co_so_tinh_tien(pool: asyncpg.Pool) -> None:
    """Đặt giá cả hai cơ sở STT là tính tiền STT hai lần. DB phải chặn."""
    async with pool.acquire() as conn, conn.transaction():
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status) "
            "VALUES ('pv_t_stt', 't', 'VND', 'inactive') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO billing.price_item "
            "(price_version_id, component, purpose, metric, unit_price, per_units) "
            "VALUES ($1, 'stt', 'conversation', 'audio_sec', 10, 1)", pb,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO billing.price_item "
                "(price_version_id, component, purpose, metric, unit_price, per_units) "
                "VALUES ($1, 'stt', 'stream', 'wall_ms', 99, 60000)", pb,
            )
        raise asyncpg.PostgresError  # không để lại rác — xem Step 2 nếu cần đổi cách dọn
```

Đổi dòng cuối thành dọn tường minh nếu `raise` làm test đỏ:

```python
        await conn.execute("DELETE FROM billing.price_version WHERE code = 'pv_t_stt'")
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `uv run pytest tests/modules/billing/test_schema_billing.py -q`
Expected: FAIL — `thiếu bảng billing.metric` (0943 chưa tồn tại).

- [ ] **Step 3: Viết migration 0943**

Copy DDL từ `docs/build_module_usage&billing/pricing-schema.sql` **nguyên văn** vào `op.execute()`, rồi thêm khối GRANT + RLS ở cuối. Cấu trúc:

```python
"""bảng giá + định giá cho module billing — 7 bảng, 3 function, 5 view

VÌ SAO KHÔNG DÙNG `control.enforce_tenant_isolation()`: hàm đó bật RLS **FORCE**,
và FORCE khoá luôn chủ bảng `portal_migrator` — mất đường đối soát tay và mất luôn
khả năng chạy `billing.rate_usage()` bằng migrator. Theo đúng khuôn `0942` đã chọn
cho `usage_events`: RLS ENABLE + policy keyed `portal.current_tenant()`.

GRANT CHỈ CHO `portal_api`, KHÔNG BAO GIỜ CHO `agent_all`. Đo được trên DB dev:
`portal_api` LÀ thành viên của nhóm `agent_all`, nên quyền chảy từ nhóm xuống
portal_api chứ không ngược lại. Cấp cho `agent_all` "cho gọn" là mở toàn bộ bảng
giá và số tiền của MỌI tenant cho mọi pod agent.

`rated_usage.event_id` FK về `billing.usage_events` CÓ cascade — khác `usage_events`
vốn cố ý không FK về `control.tenants`. Lý do khác nhau: xoá workspace không được
xoá lịch sử usage (nên không cascade ở đó), nhưng một dòng tiền trỏ tới event không
còn tồn tại là rác thuần (nên cascade ở đây).

Revision ID: 0943_billing_pricing
Revises: 0942_billing_usage_events
"""

from alembic import op

revision = "0943_billing_pricing"
down_revision = "0942_billing_usage_events"
branch_labels = None
depends_on = None

_DDL = r"""
-- ... copy nguyên văn pricing-schema.sql từ dòng `CREATE EXTENSION` tới hết ...
"""

_QUYEN = r"""
-- Danh mục giá: portal_api cần DML để màn admin CRUD được.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  billing.metric, billing.pricing_basis, billing.purpose,
  billing.price_version, billing.price_item, billing.tenant_price_version,
  billing.invoice, billing.invoice_line
TO portal_api;

-- rated_usage: portal_api CHỈ ĐỌC. Đường ghi duy nhất là billing.rate_usage(),
-- chạy bằng SECURITY DEFINER dưới quyền chủ bảng.
GRANT SELECT ON billing.rated_usage TO portal_api;

GRANT SELECT ON
  billing.price_coverage_gap, billing.purpose_unclassified,
  billing.unbillable_event, billing.cost_by_key_day,
  billing.cost_by_component_day
TO portal_api;

-- Hai view của 0942 chưa từng có GRANT nào. Cấp để còn đường đối soát tay;
-- code module KHÔNG đọc chúng (thiếu wall_ms và channel).
GRANT SELECT ON billing.usage_by_session, billing.usage_by_tenant_month TO portal_api;

GRANT USAGE ON SCHEMA billing TO portal_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA billing TO portal_api;

-- RLS cho ba bảng mang tenant_id.
ALTER TABLE billing.rated_usage        ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.tenant_price_version  ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing.invoice            ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_read ON billing.rated_usage;
CREATE POLICY tenant_read ON billing.rated_usage FOR SELECT TO portal_api
  USING (tenant_id = portal.current_tenant());

DROP POLICY IF EXISTS tenant_all ON billing.tenant_price_version;
CREATE POLICY tenant_all ON billing.tenant_price_version TO portal_api
  USING (tenant_id = portal.current_tenant())
  WITH CHECK (tenant_id = portal.current_tenant());

DROP POLICY IF EXISTS tenant_all ON billing.invoice;
CREATE POLICY tenant_all ON billing.invoice TO portal_api
  USING (tenant_id = portal.current_tenant())
  WITH CHECK (tenant_id = portal.current_tenant());

-- invoice_line không mang tenant_id: nó đi theo invoice_id. Cách ly kế thừa qua
-- FK + RLS của invoice ở tầng app (mọi truy vấn luôn JOIN invoice).
"""


def upgrade() -> None:
    op.execute(_DDL)
    op.execute("ALTER FUNCTION billing.rate_usage(timestamptz, timestamptz) SECURITY DEFINER")
    op.execute(_QUYEN)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS billing.cost_by_component_day;
        DROP VIEW IF EXISTS billing.cost_by_key_day;
        DROP VIEW IF EXISTS billing.unbillable_event;
        DROP VIEW IF EXISTS billing.purpose_unclassified;
        DROP VIEW IF EXISTS billing.price_coverage_gap;
        DROP FUNCTION IF EXISTS billing.rate_usage(timestamptz, timestamptz);
        DROP FUNCTION IF EXISTS billing.resolve_price_version(text, timestamptz);
        DROP FUNCTION IF EXISTS billing.price_item_specificity(text, text, text);
        DROP TABLE IF EXISTS billing.invoice_line;
        DROP TABLE IF EXISTS billing.invoice;
        DROP TABLE IF EXISTS billing.rated_usage;
        DROP TABLE IF EXISTS billing.tenant_price_version;
        DROP TABLE IF EXISTS billing.price_item;
        DROP TABLE IF EXISTS billing.price_version;
        DROP TABLE IF EXISTS billing.purpose;
        DROP TABLE IF EXISTS billing.pricing_basis;
        DROP TABLE IF EXISTS billing.metric;
    """)
```

⚠️ `rate_usage` phải là `SECURITY DEFINER` vì `portal_api` không có INSERT trên `rated_usage`. Nhưng SECURITY DEFINER bỏ qua RLS — nên hàm PHẢI tự giới hạn tenant. Sửa thân hàm trong `_DDL`: thêm tham số `p_tenant text DEFAULT NULL` và điều kiện `AND (p_tenant IS NULL OR e.tenant_id = p_tenant)`. Đường gọi từ API luôn truyền tenant; đường gọi từ cron truyền `NULL` để chạy mọi tenant.

- [ ] **Step 4: Áp migration và chạy test**

```bash
make migrate
uv run pytest tests/modules/billing/test_schema_billing.py -q
```
Expected: PASS 6/6.

- [ ] **Step 5: Kiểm round-trip downgrade**

```bash
uv run alembic downgrade -1 && uv run alembic upgrade head
uv run pytest tests/unit/test_alembic_mot_head.py -q
```
Expected: không lỗi, một head duy nhất. `billing.usage_events` còn nguyên dữ liệu (downgrade không đụng bảng của 0942).

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/0943_billing_pricing.py tests/modules/billing/
git commit -m "feat(billing): migration 0943 — bảng giá, định giá, GRANT cho portal_api"
```

---

### Task 2: Mở rộng cổng cách ly sang schema `billing`

Không có task này thì bảng billing mang `tenant_id` ship mà không cổng nào canh — và `rated_usage` chứa tiền của từng tenant.

**Files:**
- Modify: `tests/isolation/test_isolation_catalog.py` (thêm hằng + 1 test)

**Interfaces:**
- Consumes: Task 1 (`billing.rated_usage`, `tenant_price_version`, `invoice`)
- Produces: hằng `BILLING_TABLES_CO_RLS`, `BILLING_TABLES_KHONG_TENANT_ID`

- [ ] **Step 1: Viết test mới (sẽ đỏ nếu ai bỏ RLS)**

```python
# thêm vào cuối tests/isolation/test_isolation_catalog.py

# BẢNG `billing` — schema thứ ba mang dữ liệu phạm vi-tenant.
# `usage_events` (0942) và `rated_usage` (0943) đều có cột `tenant_id`, và cổng RLS
# ở trên chỉ quét `tenant_data` nên KHÔNG với tới đây. Danh sách đóng dưới đây buộc
# người thêm bảng billing mới phải chọn tường minh một trong hai chỗ.
BILLING_TABLES_CO_RLS: frozenset[str] = frozenset({
    "usage_events",       # 0942 — sổ ghi usage, agent INSERT, policy agent_read/agent_insert
    "rated_usage",        # 0943 — tiền từng event; policy tenant_read
    "tenant_price_version",  # 0943 — tenant nào dùng bảng giá nào; policy tenant_all
    "invoice",            # 0943 — hoá đơn theo kỳ; policy tenant_all
})

# Bảng billing KHÔNG mang tenant_id — danh mục giá cấp nền tảng, dùng chung mọi tenant.
BILLING_TABLES_KHONG_TENANT_ID: frozenset[str] = frozenset({
    "metric", "pricing_basis", "purpose", "price_version", "price_item", "invoice_line",
})


async def test_bang_billing_mang_tenant_id_phai_co_rls(pool) -> None:
    """Bảng `billing` có cột tenant_id thì phải có RLS + ít nhất một policy.

    Chế độ hỏng nếu thiếu: `portal_api` đọc được tiền của MỌI tenant, và không
    query nào báo lỗi — chỉ trả nhiều hàng hơn mức được phép.
    """
    async with pool.acquire() as conn:
        hang = await conn.fetch(
            """SELECT c.relname,
                      c.relrowsecurity,
                      (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS so_policy,
                      EXISTS (SELECT 1 FROM information_schema.columns col
                               WHERE col.table_schema = 'billing'
                                 AND col.table_name = c.relname
                                 AND col.column_name = 'tenant_id') AS co_tenant_id
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'billing' AND c.relkind IN ('r', 'p')
                ORDER BY c.relname"""
        )
        assert hang, "không thấy bảng nào trong schema billing — 0943 chưa áp?"
        thieu = [
            r["relname"] for r in hang
            if r["co_tenant_id"] and not (r["relrowsecurity"] and r["so_policy"] > 0)
        ]
        assert not thieu, f"bảng billing mang tenant_id nhưng thiếu RLS/policy: {thieu}"

        chua_khai = {
            r["relname"] for r in hang
            if r["relname"] not in BILLING_TABLES_CO_RLS
            and r["relname"] not in BILLING_TABLES_KHONG_TENANT_ID
        }
        assert not chua_khai, (
            f"bảng billing mới chưa khai vào catalog: {chua_khai}. "
            "Thêm vào BILLING_TABLES_CO_RLS (nếu mang tenant_id) hoặc "
            "BILLING_TABLES_KHONG_TENANT_ID (kèm lý do vì sao an toàn)."
        )
```

- [ ] **Step 2: Chạy cổng, xác nhận xanh**

Run: `uv run pytest tests/isolation/test_isolation_catalog.py -q`
Expected: PASS. Nếu đỏ ở `thieu` ⇒ Task 1 thiếu RLS, quay lại sửa migration.

- [ ] **Step 3: Kiểm ngược — cổng có thật sự bắt được không**

```bash
uv run psql "$MIGRATOR_URL" -c "ALTER TABLE billing.rated_usage DISABLE ROW LEVEL SECURITY"
uv run pytest tests/isolation/test_isolation_catalog.py -q   # PHẢI đỏ
uv run psql "$MIGRATOR_URL" -c "ALTER TABLE billing.rated_usage ENABLE ROW LEVEL SECURITY"
uv run pytest tests/isolation/test_isolation_catalog.py -q   # xanh lại
```
Một cổng chưa bao giờ thấy đỏ là một cổng chưa biết có hoạt động không.

- [ ] **Step 4: Chạy toàn bộ cổng cách ly**

Run: `make test-isolation`
Expected: 52/52 (51 baseline + 1 mới).

- [ ] **Step 5: Commit**

```bash
git add tests/isolation/test_isolation_catalog.py
git commit -m "test(isolation): cổng cách ly quét cả schema billing"
```

---

### Task 3: Fixture + CỔNG VÀNG đối chiếu công thức bên agent

Task quan trọng nhất của cả plan. Nó neo engine bảng giá vào công thức bên agent bàn giao. Nếu ai đó sửa thứ tự ưu tiên khớp giá, đổi `per_units`, hay bỏ một metric — bài này đỏ ngay với một con số cụ thể.

**Files:**
- Create: `tests/modules/billing/conftest.py`
- Create: `tests/modules/billing/test_doi_chieu_cong_thuc_agent.py`
- Create: `tests/modules/billing/__init__.py` (rỗng)

**Interfaces:**
- Consumes: Task 1 (`billing.rate_usage`, bảng giá)
- Produces: fixture `workspace_billing` (2 tenant, 2 key, conversation có `agent_key_id`), fixture `bang_gia_vi_du` (bảng giá VND đúng §4 của bên agent), hằng `TENANT`, `TENANT_KHAC`, `KEY_LABEL`

- [ ] **Step 1: Viết conftest**

```python
# tests/modules/billing/conftest.py
"""Fixture module billing — cùng nếp tests/modules/ops/conftest.py.

KHÔNG mock `tenant_conn()`: nó là seam của cách ly, mock nó thì test xanh cho cả
một truy vấn quên vị từ tenant.

Dữ liệu usage được chèn TRỰC TIẾP vào `billing.usage_events` bằng `pool`
(`portal_migrator`) chứ không qua đường agent — Portal không có đường ghi vào bảng
đó, và dựng một agent giả chỉ để chèn 8 hàng là đắt mà không kiểm thêm được gì.
"""

from datetime import UTC, datetime

import asyncpg
import pytest

TENANT = "bilw"
TENANT_KHAC = "bilx"
USER_ID = "u_bil"
MAT_KHAU = "MatKhauDaiVaManh!1"
KEY_LABEL = "khoá dev"
SESSION = "bil-sess-voice-1"
MOC = datetime(2026, 8, 19, 9, 52, tzinfo=UTC)


@pytest.fixture
async def workspace_billing(pool: asyncpg.Pool):
    """Hai tenant · một key mỗi tenant · một phiên voice có usage đầy đủ.

    Trả dict có `key_id` và `key_id_khac` để test cách ly dùng.
    """
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for t, ten in ((TENANT, "Billing WS"), (TENANT_KHAC, "Billing Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) "
                "VALUES ($1, $2, $3)", t, ten, USER_ID,
            )
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) "
            "VALUES ($1, 'Dũng', 'bil@noblex.vn', $2)", USER_ID, bam(MAT_KHAU),
        )
        for t in (TENANT, TENANT_KHAC):
            await conn.execute(
                "INSERT INTO control.memberships (user_id, tenant_id, role_id) "
                "VALUES ($1, $2, 'owner')", USER_ID, t,
            )
        key_id = await conn.fetchval(
            "INSERT INTO control.agent_keys "
            "(tenant_id, key_sha256, key_prefix, label, created_by) "
            "VALUES ($1, 'sha_bil_a', 'ody_ag_aaa', $2, $3) RETURNING id",
            TENANT, KEY_LABEL, USER_ID,
        )
        key_khac = await conn.fetchval(
            "INSERT INTO control.agent_keys "
            "(tenant_id, key_sha256, key_prefix, label, created_by) "
            "VALUES ($1, 'sha_bil_b', 'ody_ag_bbb', 'khoá tenant khác', $2) RETURNING id",
            TENANT_KHAC, USER_ID,
        )
        await conn.execute(
            "INSERT INTO tenant_data.conversations "
            "(tenant_id, session_id, source, agent_key_id, started_at) "
            "VALUES ($1, $2, 'voice', $3, $4)", TENANT, SESSION, key_id, MOC,
        )
        await _chen_usage(conn, TENANT, SESSION)

    yield {"key_id": key_id, "key_id_khac": key_khac, "session": SESSION}

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM billing.usage_events WHERE tenant_id = ANY($1::text[])",
            [TENANT, TENANT_KHAC],
        )
        # rated_usage đi theo event_id (cascade), price_version dọn riêng ở fixture giá.
        await conn.execute("DELETE FROM control.audit_log WHERE tenant_id = ANY($1::text[])",
                           [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])",
                           [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = $1", USER_ID)


async def _chen_usage(conn: asyncpg.Connection, tenant: str, session: str) -> None:
    """Một phiên voice thật, số liệu chép từ DB dev 2026-08-19.

    Tổng tiền với bảng giá ví dụ §4 của bên agent = 4025,2625 đ (đã đo thật:
    23 dòng rated_usage). Đừng đổi số ở đây mà không đổi hằng TIEN_MONG_DOI.

    ⚠️ FIXTURE PHẢI TỰ CHÈN DỮ LIỆU CỦA NÓ, không đọc dữ liệu có sẵn trong
    billing.usage_events. Agent vẫn đang ghi vào bảng đó — trong lúc viết plan này
    nó đi từ 20 → 34 → 43 event, và tổng tiền đi theo. Một cổng neo vào dữ liệu
    sống là một cổng đỏ ngẫu nhiên vào hôm sau.
    """
    hang = [
        # component, purpose, provider, model, in, out, cw, cr, audio_sec, wall_ms, units, exact
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 11663, 42, 0, 0, 0.0, 2800.0, 2, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12856, 76, 0, 10878, 0.0, 2900.0, 2, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 37443, 196, 0, 0, 0.0, 3000.0, 2, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 25224, 71, 0, 12335, 0.0, 2600.0, 2, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12891, 34, 0, 12335, 0.0, 2500.0, 2, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12694, 42, 0, 0, 0.0, 2900.0, 1, True),
        ("llm", "summary", "gemini", "gemini-2.5-flash", 903, 86, 0, 0, 0.0, 1400.0, 1, True),
        ("stt", "conversation", "", "", 0, 0, 0, 0, 10.21, 0.0, 0, True),
        ("stt", "stream", "", "", 0, 0, 0, 0, 0.0, 142776.8, 1, True),
        ("tts", "conversation", "", "", 0, 0, 0, 0, 81.72, 9900.0, 1115, True),
        ("vad", "conversation", "", "", 0, 0, 0, 0, 141.44, 7700.0, 0, True),
        ("speaker_verify", "conversation", "", "", 0, 0, 0, 0, 10.57, 200.0, 7, True),
        ("call", "session", "", "", 0, 0, 0, 0, 142.44, 0.0, 1, True),
    ]
    for seq, r in enumerate(hang):
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, turn_idx, component, purpose,
                provider, model, input_tokens, output_tokens, cache_write_tokens,
                cache_read_tokens, audio_sec, wall_ms, units, exact, occurred_at)
               VALUES ($1,$2,'voice',$3,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
            tenant, session, seq, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
            r[8], r[9], r[10], r[11], MOC,
        )


@pytest.fixture
async def bang_gia_vi_du(pool: asyncpg.Pool):
    """Bảng giá VND đúng theo ví dụ §4 của bên agent. STT thu theo GIÂY."""
    async with pool.acquire() as conn, conn.transaction():
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
            "VALUES ('pv_vd_test', 'ví dụ §4', 'VND', 'active', false) RETURNING id"
        )
        llm = [("input_tokens", 2500), ("output_tokens", 10000),
               ("cache_write_tokens", 0), ("cache_read_tokens", 625)]
        for metric, gia in llm:
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, provider, "
                "model, metric, unit_price, per_units) "
                "VALUES ($1, 'llm', 'gemini', 'gemini-2.5-flash', $2, $3, 1000000)",
                pb, metric, gia,
            )
        audio = [
            ("stt", "conversation", "audio_sec", 10, 1),
            ("stt", "stream", "wall_ms", 0, 60000),
            ("tts", "", "units", 2, 1),
            ("vad", "", "audio_sec", 1, 1),
            ("speaker_verify", "", "audio_sec", 5, 1),
            ("call", "", "audio_sec", 500, 60),
        ]
        for comp, purpose, metric, gia, per in audio:
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, purpose, "
                "metric, unit_price, per_units) VALUES ($1, $2, $3, $4, $5, $6)",
                pb, comp, purpose, metric, gia, per,
            )
        await conn.execute(
            "INSERT INTO billing.tenant_price_version "
            "(tenant_id, price_version_id, effective_from) "
            "VALUES ($1, $2, '2000-01-01'::timestamptz)", TENANT, pb,
        )
    yield pb
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM billing.price_version WHERE id = $1", pb)
```

- [ ] **Step 2: Viết cổng vàng**

```python
# tests/modules/billing/test_doi_chieu_cong_thuc_agent.py
"""CỔNG VÀNG — engine bảng giá phải ra CÙNG SỐ với công thức bên agent bàn giao.

Nguồn công thức: docs/build_module_usage&billing/portal-billing-pricing-guide-handoff-from-agent.md §4
Query dưới đây chép từ §4 đó, chỉ bỏ GROUP BY để lấy một tổng.

VÌ SAO BÀI NÀY TỒN TẠI: Portal không tính tiền bằng khối CASE của họ, mà bằng bảng
giá + độ ưu tiên khớp. Hai cách hoàn toàn khác nhau về cấu trúc, nên "trông có vẻ
đúng" là không đủ — cần một phép so số học trên cùng dữ liệu. Bài này đã chạy thật
và ra CÙNG một số ở cả hai bên trước khi được viết vào plan.

Hai phép so, khác vai:
· `cua_portal == cua_agent` — phép so CHÍNH, tự kiểm, đúng bất kể fixture đổi.
· `cua_portal == TIEN_MONG_DOI` — cổng chống fixture trôi. Nếu ai sửa số trong
  `_chen_usage` mà quên sửa hằng thì bài này đỏ, đúng như mong muốn.

Nó đỏ nếu ai: đổi thứ tự ưu tiên khớp giá · bỏ metric wall_ms · đổi nghĩa per_units ·
bật billable cho một nhãn giá vốn · vô tình cộng audio_sec chéo component.
"""

from decimal import Decimal

import asyncpg

from tests.modules.billing.conftest import TENANT

TIEN_MONG_DOI = Decimal("4025.26")

_QUERY_BEN_AGENT = """
WITH gia_audio AS (
  SELECT 10::numeric stt_per_sec, 0::numeric stt_per_stream_min, 2::numeric tts_per_char,
         1::numeric vad_per_sec, 5::numeric sv_per_sec, 500::numeric call_per_min),
gia_llm(provider, model, in_1m, out_1m, cw_1m, cr_1m) AS (
  VALUES ('gemini', 'gemini-2.5-flash', 2500::numeric, 10000::numeric, 0::numeric, 625::numeric)),
nhan_tinh(purpose) AS (
  VALUES ('conversation'), ('summary'), ('suggestions'), ('embed'), ('stream'), ('session'))
SELECT round(sum(CASE u.component
    WHEN 'llm' THEN (u.input_tokens * l.in_1m + u.output_tokens * l.out_1m
                   + u.cache_write_tokens * l.cw_1m + u.cache_read_tokens * l.cr_1m) / 1e6
    WHEN 'stt' THEN CASE u.purpose
                        WHEN 'conversation' THEN u.audio_sec * a.stt_per_sec
                        WHEN 'stream'       THEN u.wall_ms / 60000.0 * a.stt_per_stream_min
                    END
    WHEN 'tts'            THEN u.units * a.tts_per_char
    WHEN 'vad'            THEN u.audio_sec * a.vad_per_sec
    WHEN 'speaker_verify' THEN u.audio_sec * a.sv_per_sec
    WHEN 'call'           THEN u.audio_sec / 60.0 * a.call_per_min
  END)::numeric, 2)
FROM billing.usage_events u
CROSS JOIN gia_audio a
LEFT JOIN gia_llm l ON u.component = 'llm' AND l.provider = u.provider AND l.model = u.model
WHERE u.tenant_id = $1 AND u.purpose IN (SELECT purpose FROM nhan_tinh)
"""


async def test_engine_khop_cong_thuc_ben_agent(
    pool: asyncpg.Pool, workspace_billing, bang_gia_vi_du
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )
        cua_portal = await conn.fetchval(
            "SELECT round(sum(amount), 2) FROM billing.rated_usage WHERE tenant_id = $1",
            TENANT,
        )
        cua_agent = await conn.fetchval(_QUERY_BEN_AGENT, TENANT)

    assert cua_portal == cua_agent, (
        f"engine Portal ra {cua_portal}, công thức bên agent ra {cua_agent}"
    )
    assert cua_portal == TIEN_MONG_DOI, (
        f"ra {cua_portal}, mong đợi {TIEN_MONG_DOI} — dữ liệu fixture đã đổi?"
    )


async def test_khong_cong_audio_sec_cheo_component(
    pool: asyncpg.Pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Bẫy §5.1 của bên agent: vad/call/stt đo những quãng audio CHỒNG LẤN.

    Cấu trúc rated_usage làm việc cộng gộp đó bất khả thi — mỗi dòng gắn một
    component. Bài này neo bất biến đó: tổng audio_sec của call KHÔNG được bằng
    tổng audio_sec toàn bảng.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )
        theo_component = await conn.fetch(
            "SELECT component, sum(quantity) q FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND metric = 'audio_sec' GROUP BY 1", TENANT,
        )
    d = {r["component"]: r["q"] for r in theo_component}
    assert d["call"] < d["vad"] + d["stt"] + d["speaker_verify"], (
        "call phải NHỎ HƠN tổng các đồng hồ con — nếu không, giả định chồng lấn đã sai"
    )
```

- [ ] **Step 3: Chạy — cổng vàng phải xanh ngay**

Run: `uv run pytest tests/modules/billing/test_doi_chieu_cong_thuc_agent.py -q`
Expected: PASS 2/2. Nếu `cua_portal != cua_agent` ⇒ `_DDL` ở Task 1 bị chép sai, so lại với `pricing-schema.sql`.

- [ ] **Step 4: Kiểm ngược cổng — bỏ metric wall_ms phải làm nó đỏ**

```bash
uv run psql "$MIGRATOR_URL" -c "DELETE FROM billing.pricing_basis WHERE metric='wall_ms'"
uv run pytest tests/modules/billing/test_doi_chieu_cong_thuc_agent.py -q  # vẫn xanh (giá stream=0)
uv run psql "$MIGRATOR_URL" -c "UPDATE billing.purpose SET billable=false WHERE code='summary'"
uv run pytest tests/modules/billing/test_doi_chieu_cong_thuc_agent.py -q  # PHẢI đỏ
uv run psql "$MIGRATOR_URL" -c "UPDATE billing.purpose SET billable=true WHERE code='summary'"
uv run psql "$MIGRATOR_URL" -c "INSERT INTO billing.pricing_basis (component,purpose,metric,note) VALUES ('stt','stream','wall_ms','')"
```

- [ ] **Step 5: Commit**

```bash
git add tests/modules/billing/
git commit -m "test(billing): cổng vàng đối chiếu công thức bên agent"
```

---

### Task 4: `billing.rate_usage` — bài canh hành vi định giá

Task 3 kiểm TỔNG. Task này kiểm từng quy tắc riêng, để khi tổng lệch thì biết lệch ở đâu.

**Files:**
- Create: `tests/modules/billing/test_rate_usage.py`
- Modify: `migrations/versions/0943_billing_pricing.py` (chỉ nếu có bài đỏ)

**Interfaces:**
- Consumes: Task 1, Task 3 (fixture)
- Produces: không có API mới

- [ ] **Step 1: Viết 5 bài canh**

```python
# tests/modules/billing/test_rate_usage.py
"""Từng quy tắc định giá một. Task 3 kiểm tổng; đây kiểm cơ chế."""

from decimal import Decimal

import asyncpg

from tests.modules.billing.conftest import TENANT, TENANT_KHAC


async def _rate(conn: asyncpg.Connection, tenant: str = TENANT) -> int:
    return await conn.fetchval(
        "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
        "'2100-01-01'::timestamptz, $1)", tenant,
    )


async def test_chay_lai_khong_nhan_ban(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Cron chạy trùng, hoặc re-run cửa sổ 48h, không được nhân đôi hoá đơn."""
    async with pool.acquire() as conn, conn.transaction():
        lan1 = await _rate(conn)
        tong1 = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        lan2 = await _rate(conn)
        tong2 = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        so_dong = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
    assert lan1 == lan2, "số dòng xử lý phải như nhau"
    assert tong1 == tong2, f"chạy lại làm tiền đổi: {tong1} → {tong2}"
    assert so_dong == lan1


async def test_nhan_gia_von_khong_tinh_tien(pool, workspace_billing, bang_gia_vi_du) -> None:
    """warm_cache là tối ưu nội bộ — khách không yêu cầu, không trả tiền.

    Cờ billable lọc TRƯỚC khi khớp giá. Đây là lý do không thể thay nó bằng
    'dòng giá = 0': dòng giá cụ-thể-theo-model (điểm 6) thắng dòng
    cụ-thể-theo-purpose (điểm 1), nên nhãn giá vốn vẫn bị tính đủ tiền.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, output_tokens, occurred_at)
               VALUES ($1, 'bil-sess-voice-1', 'voice', 99, 'llm', 'warm_cache',
                       'gemini', 'gemini-2.5-flash', 50000, 100, '2026-08-19T09:52Z')""",
            TENANT,
        )
        await _rate(conn)
        tien_warm = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND purpose = 'warm_cache'", TENANT,
        )
    assert tien_warm == 0, "warm_cache bị tính tiền — cờ billable không có tác dụng"


async def test_nhan_chua_khai_van_tinh_tien(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Nhãn purpose mới agent thêm ⇒ MẶC ĐỊNH TÍNH TIỀN, và hiện ở view cảnh báo.

    Chiều ngược lại (mặc định không tính) là mất doanh thu ÂM THẦM — không ai
    phát hiện. Mặc định tính thì sai lệch sẽ có người khiếu nại.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, output_tokens, occurred_at)
               VALUES ($1, 'bil-sess-voice-1', 'voice', 98, 'llm', 'nhan_moi_la',
                       'gemini', 'gemini-2.5-flash', 1000000, 0, '2026-08-19T09:52Z')""",
            TENANT,
        )
        await _rate(conn)
        tien = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND purpose = 'nhan_moi_la'", TENANT,
        )
        canh_bao = await conn.fetchval(
            "SELECT count(*) FROM billing.purpose_unclassified WHERE purpose = 'nhan_moi_la'")
    assert tien == Decimal("2500.0000000000"), f"nhãn mới không được tính tiền: {tien}"
    assert canh_bao == 1, "nhãn mới không hiện ở purpose_unclassified"


async def test_gia_cu_the_thang_gia_wildcard(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Đặt giá chung cho mọi model rồi ghi đè riêng một model."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO billing.price_item (price_version_id, component, metric, "
            "unit_price, per_units) VALUES ($1, 'llm', 'input_tokens', 99999, 1000000)",
            bang_gia_vi_du,
        )
        await _rate(conn)
        gia_da_dung = await conn.fetchval(
            "SELECT DISTINCT unit_price FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND component = 'llm' AND metric = 'input_tokens'",
            TENANT,
        )
    assert gia_da_dung == Decimal("2500.0000000000"), (
        f"dùng giá wildcard {gia_da_dung} thay vì giá theo model"
    )


async def test_tinh_lai_ky_cu_khi_version_da_inactive(
    pool, workspace_billing, bang_gia_vi_du
) -> None:
    """BÀI CANH QUAN TRỌNG NHẤT của việc siết status còn active|inactive.

    Kịch bản: tháng 8 dùng bộ v1; sang tháng 9 chuyển v2, v1 thành 'inactive'.
    Rồi có người tính lại tháng 8 — re-run cửa sổ 48h, hay tính lại sau khi sửa
    dữ liệu.

    Nếu `resolve_price_version()` đòi `status = 'active'` thì nó KHÔNG tìm thấy v1,
    rơi về `is_default`, và tháng 8 ra MỘT SỐ TIỀN KHÁC — một kỳ đã chốt bị viết
    lại, không lỗi nào phát ra, và số mới trông hoàn toàn hợp lý.

    Nên hàm đó cố ý chỉ đọc KHOẢNG HIỆU LỰC trong tenant_price_version.
    Bài này đỏ ngay nếu ai "sửa cho hợp lý" bằng cách thêm điều kiện status.
    """
    async with pool.acquire() as conn, conn.transaction():
        truoc = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT
        ) or 0
        if truoc == 0:
            await _rate(conn)
            truoc = await conn.fetchval(
                "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)

        # dựng một bộ giá khác làm default, rồi cho bộ đang dùng về inactive
        pv2 = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
            "VALUES ('pv_t_khac', 'khac', 'VND', 'active', true) RETURNING id"
        )
        await conn.execute(
            "INSERT INTO billing.price_item (price_version_id, component, provider, "
            "model, metric, unit_price, per_units) VALUES "
            "($1, 'llm', 'gemini', 'gemini-2.5-flash', 'input_tokens', 99999, 1000000)",
            pv2,
        )
        await conn.execute(
            "UPDATE billing.price_version SET status = 'inactive', is_default = false "
            "WHERE id = $1", bang_gia_vi_du,
        )
        await conn.execute(
            "DELETE FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        await _rate(conn)
        sau = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)

    assert sau == truoc, (
        f"tính lại kỳ cũ ra {sau} thay vì {truoc} — resolve_price_version() đang đọc "
        "`status`, và điều đó viết lại hoá đơn của một kỳ đã chốt"
    )


async def test_khong_dinh_gia_cheo_tenant(pool, workspace_billing, bang_gia_vi_du) -> None:
    """rate_usage là SECURITY DEFINER (bỏ qua RLS) nên tham số tenant PHẢI chặn.

    Không có vế này thì một lời gọi cho tenant A định giá luôn usage của B bằng
    bảng giá của A — sai tiền của cả hai, không lỗi nào phát ra.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, 'sess-khac', 'chat', 0, 'llm', 'conversation', 'gemini',
                       'gemini-2.5-flash', 500000, '2026-08-19T09:52Z')""",
            TENANT_KHAC,
        )
        await _rate(conn, TENANT)
        ro_ri = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1", TENANT_KHAC)
    assert ro_ri == 0, "định giá cho tenant A đã chạm usage của tenant B"
```

- [ ] **Step 2: Chạy, sửa migration nếu đỏ**

Run: `uv run pytest tests/modules/billing/test_rate_usage.py -q`
Expected: PASS 5/5. Bài `test_khong_dinh_gia_cheo_tenant` sẽ đỏ nếu Step 3 của Task 1 chưa thêm tham số `p_tenant` — sửa `_DDL` rồi `alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 3: Commit**

```bash
git add tests/modules/billing/test_rate_usage.py migrations/versions/0943_billing_pricing.py
git commit -m "test(billing): canh từng quy tắc định giá — idempotency, billable, độ cụ thể, cách ly"
```

---

### Task 5: `contracts.py` + `repo.py` — đường đọc

**Files:**
- Create: `src/portal/modules/billing/__init__.py` (rỗng)
- Create: `src/portal/modules/billing/contracts.py`
- Create: `src/portal/modules/billing/repo.py`
- Create: `tests/modules/billing/test_repo.py`

**Interfaces:**
- Consumes: Task 1 (view `cost_by_key_day`, bảng `rated_usage`, `usage_events`)
- Produces:
  - `contracts.TongQuanOut`, `contracts.DongKeyOut`, `contracts.DanhSachKeyOut`, `contracts.DongOwnerOut`, `contracts.PhienUsageOut`, `contracts.DanhSachPhienOut`, `contracts.EventOut`, `contracts.ChiTietPhienOut`, `contracts.CanhBaoOut`
  - `repo.tong_quan(conn, tu_ngay, den_ngay) -> asyncpg.Record`
  - `repo.theo_key(conn, tu_ngay, den_ngay) -> list[asyncpg.Record]`
  - `repo.theo_owner(conn, tu_ngay, den_ngay) -> list[asyncpg.Record]`
  - `repo.liet_ke_phien(conn, tu_ngay, den_ngay, limit, offset) -> list[asyncpg.Record]`
  - `repo.event_cua_phien(conn, session_id) -> list[asyncpg.Record]`
  - `repo.canh_bao(conn) -> asyncpg.Record`

- [ ] **Step 1: Viết test repo (sẽ đỏ)**

```python
# tests/modules/billing/test_repo.py
"""SQL của module billing. Đọc qua tenant_conn() — đó là seam cách ly."""

from decimal import Decimal

import asyncpg
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.billing import repo
from tests.modules.billing.conftest import KEY_LABEL, SESSION, TENANT, TENANT_KHAC

TU = "2026-08-01"
DEN = "2026-09-01"


async def _da_dinh_gia(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )


async def test_doc_ngoai_giao_dich_tra_0_hang(api_dsn: str, workspace_billing) -> None:
    """Chế độ hỏng IM LẶNG của Luật 1 — neo lại để không ai "sửa" bằng cách bỏ tenant_conn.

    Đo được trên DB dev: portal_api đọc billing.usage_events ngoài giao dịch trả 0,
    KHÔNG phải permission denied. Một repo quên tenant_conn() sẽ trả bảng rỗng và
    màn hình hiện "chưa có dữ liệu" — trông hoàn toàn hợp lý.
    """
    conn = await asyncpg.connect(api_dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM billing.usage_events") == 0
    finally:
        await conn.close()


async def test_tong_quan(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        r = await repo.tong_quan(conn, TU, DEN)
    assert r["so_phien"] == 1
    assert r["input_tokens"] == 113674
    assert r["voice_sec"] == pytest.approx(386.38, abs=0.01)
    assert r["chi_phi"] == Decimal("4025.2625000000")
    assert r["so_key"] == 1


async def test_theo_key_co_dong_chua_phan_loai(
    api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Phiên không có agent_key_id phải hiện thành nhóm riêng, KHÔNG bị ẩn.

    Ẩn nó là làm tổng theo key lệch tổng hoá đơn — lỗi phổ biến nhất của dashboard
    usage, và nó lệch theo hướng THIẾU nên không ai thấy.
    """
    async with api_pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id, source) "
            "VALUES ($1, 'sess-khong-key', 'chat')", TENANT,
        )
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, 'sess-khong-key', 'chat', 0, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 400000, '2026-08-19T09:52Z')""",
            TENANT,
        )
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
    theo_id = {r["agent_key_id"]: r for r in hang}
    assert None in theo_id, "thiếu nhóm 'chưa phân loại'"
    assert theo_id[None]["chi_phi"] == Decimal("1000.0000000000")
    co_key = [r for r in hang if r["agent_key_id"] is not None][0]
    assert co_key["label"] == KEY_LABEL
    assert co_key["so_phien"] == 1


async def test_cach_ly_tenant(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT_KHAC) as conn:
        assert await repo.theo_key(conn, TU, DEN) == []
        r = await repo.tong_quan(conn, TU, DEN)
    assert (r["chi_phi"] or 0) == 0


async def test_event_cua_phien_co_tien_tung_dong(
    api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        ev = await repo.event_cua_phien(conn, SESSION)
    assert len(ev) == 13
    call = [e for e in ev if e["component"] == "call"][0]
    assert call["chi_phi"] == Decimal("1187.0000000000")
```

Thêm fixture `api_pool` vào `tests/modules/billing/conftest.py` (pool nối bằng `portal_api`, không phải `portal_migrator` — dùng `pool` là chạy test bằng superuser và mọi cổng RLS thành cổng không bao giờ đỏ):

```python
@pytest.fixture
async def api_pool(api_dsn: str):
    p = await asyncpg.create_pool(api_dsn, min_size=1, max_size=3)
    yield p
    await p.close()
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/billing/test_repo.py -q`
Expected: FAIL — `ModuleNotFoundError: portal.modules.billing`.

- [ ] **Step 3: Viết `contracts.py`**

```python
"""Mặt tiền module billing. Module khác chỉ được import từ file này (Luật 3)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

TRANG_MAC_DINH: Final = 50
TRANG_TOI_DA: Final = 200

NHAN_CHUA_PHAN_LOAI: Final = "Chưa phân loại (không có khoá)"
"""Nhãn cho nhóm agent_key_id IS NULL. Nhóm này KHÔNG được ẩn khỏi UI: ẩn nó là
làm tổng theo khoá lệch tổng hoá đơn, và lệch theo hướng thiếu nên không ai thấy."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanhBaoOut(_Base):
    """Ba con số vận hành. Khác 0 là có việc phải làm, không phải thông tin nền."""

    thieu_gia: int = Field(description="cặp (component, metric) có usage mà chưa có giá")
    nhan_chua_phan_loai: int = Field(description="purpose agent gửi mà chưa ai phân loại")
    event_khong_so_do: int = Field(description="event không có số đo nào ⇒ không tính được tiền")
    llm_khong_chinh_xac: int = Field(description="event llm có exact=false ⇒ đo THIẾU token")


class TongQuanOut(_Base):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    voice_sec: float = Field(description="tổng audio_sec — KHÔNG cộng chéo component")
    so_phien: int
    so_key: int
    chi_phi: Decimal
    currency: str
    canh_bao: CanhBaoOut


class DongKeyOut(_Base):
    agent_key_id: int | None = Field(description="None = nhóm chưa phân loại")
    label: str
    key_prefix: str
    nguoi_tao: str
    nguoi_tao_ten: str | None
    da_thu_hoi: bool
    so_phien: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    voice_sec: float
    so_event: int
    chi_phi: Decimal


class DanhSachKeyOut(_Base):
    items: list[DongKeyOut]
    total: int
    chi_phi_tong: Decimal
    currency: str


class DongOwnerOut(_Base):
    user_id: str | None
    ten: str | None
    email: str | None
    so_key: int
    so_phien: int
    chi_phi: Decimal


class PhienUsageOut(_Base):
    session_id: str
    agent_key_id: int | None
    key_label: str | None
    customer_name: str | None
    phone: str | None
    channel: str
    bat_dau: datetime | None
    so_turn: int
    input_tokens: int
    output_tokens: int
    voice_sec: float
    chi_phi: Decimal
    exact: bool


class DanhSachPhienOut(_Base):
    items: list[PhienUsageOut]
    total: int


class EventOut(_Base):
    event_id: int
    seq: int
    turn_idx: int | None
    component: str
    purpose: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    audio_sec: float
    units: int
    exact: bool
    chi_phi: Decimal
    occurred_at: datetime


class ChiTietPhienOut(_Base):
    phien: PhienUsageOut
    events: list[EventOut]
    ghi_chu_turn: str = Field(
        default=(
            "turn_idx của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). "
            "Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để đối chiếu tiền."
        )
    )
```

- [ ] **Step 4: Viết `repo.py`**

```python
"""SQL của module billing. Trả `asyncpg.Record` thô — không biết HTTP, không Pydantic.

MỌI câu ở đây mang vị từ tenant qua RLS (`portal.current_tenant()`), và PHẢI được
gọi trong `tenant_conn()`. Đọc ngoài giao dịch trả 0 hàng, KHÔNG báo lỗi.

KHÔNG dùng hai view `billing.usage_by_session`/`usage_by_tenant_month` của 0942:
chúng thiếu `wall_ms` (cơ sở tính tiền của `(stt,'stream')`) và `channel`.
"""

from datetime import date

import asyncpg

_CACH_LY = "tenant_id = portal.current_tenant()"
"""Tên biến PHẢI chứa `_CACH_LY` — cổng tests/isolation/test_loc_tenant_o_tang_app.py
regex trên CHÍNH TÊN BIẾN, không expand giá trị runtime. Đặt tên khác làm cổng mù
trước mọi câu SQL của file này."""


async def tong_quan(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> asyncpg.Record:
    return await conn.fetchrow(
        f"""
        WITH ev AS (
            SELECT * FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1 AND occurred_at < $2
        ), tien AS (
            SELECT sum(amount) AS chi_phi, min(currency) AS currency
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1 AND occurred_at < $2
        )
        SELECT COALESCE(sum(ev.input_tokens), 0)::bigint      AS input_tokens,
               COALESCE(sum(ev.output_tokens), 0)::bigint     AS output_tokens,
               COALESCE(sum(ev.cache_read_tokens), 0)::bigint AS cache_read_tokens,
               COALESCE(sum(ev.audio_sec), 0)::float          AS voice_sec,
               count(DISTINCT ev.session_id)::int             AS so_phien,
               (SELECT count(DISTINCT c.agent_key_id) FROM tenant_data.conversations c
                 WHERE c.{_CACH_LY} AND c.agent_key_id IS NOT NULL
                   AND c.session_id IN (SELECT session_id FROM ev))::int AS so_key,
               COALESCE((SELECT chi_phi FROM tien), 0)        AS chi_phi,
               COALESCE((SELECT currency FROM tien), 'VND')   AS currency
          FROM ev
        """,
        tu_ngay, den_ngay,
    )


async def canh_bao(conn: asyncpg.Connection) -> asyncpg.Record:
    """Bốn con số vận hành. `price_coverage_gap` khác rỗng = đang mất doanh thu."""
    return await conn.fetchrow(
        f"""
        SELECT (SELECT count(*) FROM billing.price_coverage_gap
                 WHERE {_CACH_LY})::int                        AS thieu_gia,
               (SELECT count(*) FROM billing.purpose_unclassified)::int
                                                               AS nhan_chua_phan_loai,
               (SELECT count(*) FROM billing.unbillable_event
                 WHERE {_CACH_LY})::int                        AS event_khong_so_do,
               (SELECT count(*) FROM billing.usage_events
                 WHERE {_CACH_LY} AND component = 'llm' AND NOT exact)::int
                                                               AS llm_khong_chinh_xac
        """
    )


async def theo_key(
    conn: asyncpg.Connection, tu_ngay: date, den_ngay: date
) -> list[asyncpg.Record]:
    """LEFT JOIN conversations — nhóm `agent_key_id IS NULL` phải còn lại trong kết quả.

    INNER JOIN ở đây sẽ âm thầm làm mất usage của phiên chưa có hàng conversations
    (agent ghi usage trước khi tạo phiên). Tổng sẽ nhỏ hơn hoá đơn mà không lỗi nào.
    """
    return await conn.fetch(
        f"""
        WITH ev AS (
            SELECT e.session_id, c.agent_key_id,
                   e.input_tokens, e.output_tokens, e.cache_read_tokens,
                   e.audio_sec, e.event_id
              FROM billing.usage_events e
              LEFT JOIN tenant_data.conversations c
                     ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
             WHERE e.{_CACH_LY} AND e.occurred_at >= $1 AND e.occurred_at < $2
        ), tien AS (
            SELECT agent_key_id, sum(amount) AS chi_phi
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1 AND occurred_at < $2
             GROUP BY 1
        )
        SELECT ev.agent_key_id,
               COALESCE(k.label, '')      AS label,
               COALESCE(k.key_prefix, '') AS key_prefix,
               COALESCE(k.created_by, '') AS nguoi_tao,
               u.name                     AS nguoi_tao_ten,
               (k.revoked_at IS NOT NULL) AS da_thu_hoi,
               count(DISTINCT ev.session_id)::int              AS so_phien,
               COALESCE(sum(ev.input_tokens), 0)::bigint       AS input_tokens,
               COALESCE(sum(ev.output_tokens), 0)::bigint      AS output_tokens,
               COALESCE(sum(ev.cache_read_tokens), 0)::bigint  AS cache_read_tokens,
               COALESCE(sum(ev.audio_sec), 0)::float           AS voice_sec,
               count(*)::int                                   AS so_event,
               COALESCE(t.chi_phi, 0)                          AS chi_phi
          FROM ev
          LEFT JOIN control.agent_keys k ON k.id = ev.agent_key_id
          LEFT JOIN control.users u      ON u.id = k.created_by
          LEFT JOIN tien t               ON t.agent_key_id IS NOT DISTINCT FROM ev.agent_key_id
         GROUP BY ev.agent_key_id, k.label, k.key_prefix, k.created_by, u.name,
                  k.revoked_at, t.chi_phi
         ORDER BY chi_phi DESC, ev.agent_key_id NULLS LAST
        """,
        tu_ngay, den_ngay,
    )


async def theo_owner(
    conn: asyncpg.Connection, tu_ngay: date, den_ngay: date
) -> list[asyncpg.Record]:
    """Gộp theo `agent_keys.created_by` — trả lời "user nào dùng bao nhiêu"."""
    return await conn.fetch(
        f"""
        SELECT k.created_by AS user_id, u.name AS ten, u.email,
               count(DISTINCT k.id)::int                AS so_key,
               count(DISTINCT r.metric || r.occurred_at::text) * 0 +
               count(DISTINCT c.session_id)::int        AS so_phien,
               COALESCE(sum(r.amount), 0)               AS chi_phi
          FROM billing.rated_usage r
          JOIN control.agent_keys k ON k.id = r.agent_key_id
          LEFT JOIN control.users u ON u.id = k.created_by
          LEFT JOIN tenant_data.conversations c
                 ON c.agent_key_id = k.id AND c.tenant_id = r.tenant_id
         WHERE r.{_CACH_LY} AND r.occurred_at >= $1 AND r.occurred_at < $2
         GROUP BY k.created_by, u.name, u.email
         ORDER BY chi_phi DESC
        """,
        tu_ngay, den_ngay,
    )


async def liet_ke_phien(
    conn: asyncpg.Connection, tu_ngay: date, den_ngay: date, limit: int, offset: int
) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        WITH ev AS (
            SELECT session_id,
                   min(occurred_at)                       AS bat_dau,
                   max(channel)                           AS channel,
                   count(DISTINCT turn_idx)::int          AS so_turn,
                   sum(input_tokens)::bigint              AS input_tokens,
                   sum(output_tokens)::bigint             AS output_tokens,
                   sum(audio_sec)::float                  AS voice_sec,
                   bool_and(exact)                        AS exact
              FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1 AND occurred_at < $2
             GROUP BY session_id
        ), tien AS (
            SELECT e.session_id, sum(r.amount) AS chi_phi
              FROM billing.rated_usage r
              JOIN billing.usage_events e ON e.event_id = r.event_id
             WHERE r.{_CACH_LY} AND r.occurred_at >= $1 AND r.occurred_at < $2
             GROUP BY 1
        )
        SELECT ev.session_id, c.agent_key_id, k.label AS key_label,
               c.customer_name, c.phone, ev.channel, ev.bat_dau, ev.so_turn,
               ev.input_tokens, ev.output_tokens, ev.voice_sec, ev.exact,
               COALESCE(t.chi_phi, 0) AS chi_phi,
               count(*) OVER ()::int  AS total
          FROM ev
          LEFT JOIN tenant_data.conversations c
                 ON c.tenant_id = portal.current_tenant() AND c.session_id = ev.session_id
          LEFT JOIN control.agent_keys k ON k.id = c.agent_key_id
          LEFT JOIN tien t ON t.session_id = ev.session_id
         ORDER BY ev.bat_dau DESC
         LIMIT $3 OFFSET $4
        """,
        tu_ngay, den_ngay, limit, offset,
    )


async def event_cua_phien(
    conn: asyncpg.Connection, session_id: str
) -> list[asyncpg.Record]:
    """Timeline theo `seq`. Tiền từng event = tổng mọi metric của event đó."""
    return await conn.fetch(
        f"""
        SELECT e.event_id, e.seq, e.turn_idx, e.component, e.purpose, e.provider,
               e.model, e.input_tokens, e.output_tokens, e.cache_read_tokens,
               e.audio_sec::float AS audio_sec, e.units, e.exact, e.occurred_at,
               COALESCE((SELECT sum(r.amount) FROM billing.rated_usage r
                          WHERE r.event_id = e.event_id), 0) AS chi_phi
          FROM billing.usage_events e
         WHERE e.{_CACH_LY} AND e.session_id = $1
         ORDER BY e.seq, e.component
        """,
        session_id,
    )
```

- [ ] **Step 5: Chạy test repo**

Run: `uv run pytest tests/modules/billing/test_repo.py -q`
Expected: PASS 5/5. Nếu `test_tong_quan` lệch số token, in ra `sum(input_tokens)` từ fixture rồi sửa hằng trong test — đừng sửa SQL để khớp một con số đoán.

- [ ] **Step 6: Cổng cách ly phải còn xanh**

Run: `make test-isolation`
Expected: 52/52. Đỏ ở `test_loc_tenant_o_tang_app.py` ⇒ tên hằng `_CACH_LY` bị đổi hoặc có câu SQL thiếu vị từ.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/billing/ tests/modules/billing/test_repo.py
git commit -m "feat(billing): contracts + repo — rollup theo key/owner/phiên"
```

---

### Task 6: Action `billing.read` + migration 0944

**Files:**
- Modify: `src/portal/core/auth/actions.py`
- Create: `migrations/versions/0944_billing_action.py`
- Test: `tests/modules/billing/test_action.py`

**Interfaces:**
- Consumes: `control.actions`, `control.role_actions` (0104)
- Produces: `ACTIONS.BILLING_READ = "billing.read"`

- [ ] **Step 1: Viết test**

```python
# tests/modules/billing/test_action.py
"""Action mới phải có mặt ở CẢ code LẪN bảng control.actions.

Thiếu ở code: endpoint không khai được. Thiếu ở DB: `require()` trả 403 cho mọi
người vì `action not in q.actions`, và thông điệp nói về VAI TRÒ nên người dùng đi
xin thêm quyền cho một action không tồn tại.
"""

import asyncpg

from portal.core.auth.actions import ACTIONS, ALL_ACTIONS, NHAN_HANH_DONG


def test_action_co_trong_code() -> None:
    assert ACTIONS.BILLING_READ == "billing.read"
    assert ACTIONS.BILLING_READ in ALL_ACTIONS
    assert ACTIONS.BILLING_READ in NHAN_HANH_DONG


async def test_action_co_trong_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM control.actions WHERE code = 'billing.read'"
        ) == 1
        vai_tro = await conn.fetch(
            "SELECT role_id FROM control.role_actions WHERE action_code = 'billing.read'"
        )
    assert {r["role_id"] for r in vai_tro} >= {"owner"}, (
        "owner phải có billing.read — không thì không ai xem được hoá đơn"
    )
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/billing/test_action.py -q`
Expected: FAIL — `AttributeError: BILLING_READ`.

- [ ] **Step 3: Thêm action vào code**

Trong `src/portal/core/auth/actions.py`, cạnh `WORKSPACE_ADMIN`:

```python
    BILLING_READ: Final = "billing.read"
    """Xem Usage & Billing. TÁCH khỏi WORKSPACE_ADMIN có chủ ý: kế toán cần xem
    hoá đơn mà không cần quyền mời/gỡ thành viên."""
```

Và vào `NHAN_HANH_DONG`:

```python
    ACTIONS.BILLING_READ: "Xem Usage & Billing · chi phí",
```

- [ ] **Step 4: Viết migration 0944**

```python
"""action `billing.read` vào control.actions + role_actions

Vai trò là DỮ LIỆU (0104), không phải enum — nên thêm action là một migration, và
danh sách vai trò được cấp phải khai TRONG file này chứ không import từ portal.*
(migration cũ đổi nghĩa mỗi lần sổ đổi).

Revision ID: 0944_billing_action
Revises: 0943_billing_pricing
"""

from alembic import op

revision = "0944_billing_action"
down_revision = "0943_billing_pricing"
branch_labels = None
depends_on = None

_VAI_TRO_DUOC_CAP = ("owner", "admin")
"""Đóng băng theo thời điểm 2026-08-19. Biên tập KHÔNG có — họ soạn nội dung,
không xem chi phí."""


def upgrade() -> None:
    op.execute(
        """INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
           VALUES ('billing.read', 'billing', 'Xem Usage & Billing · chi phí',
                   'View usage & billing', 900)
           ON CONFLICT (code) DO NOTHING"""
    )
    for vai_tro in _VAI_TRO_DUOC_CAP:
        op.execute(
            f"""INSERT INTO control.role_actions (role_id, action_code)
                SELECT '{vai_tro}', 'billing.read'
                 WHERE EXISTS (SELECT 1 FROM control.roles WHERE id = '{vai_tro}')
                ON CONFLICT DO NOTHING"""
        )


def downgrade() -> None:
    op.execute("DELETE FROM control.role_actions WHERE action_code = 'billing.read'")
    op.execute("DELETE FROM control.actions WHERE code = 'billing.read'")
```

- [ ] **Step 5: Áp, sinh contract, chạy test**

```bash
make migrate
make contracts
uv run pytest tests/modules/billing/test_action.py tests/api/test_contracts.py -q
```
Expected: PASS. `make contracts` cập nhật `contracts/actions.json` — **copy tay sang repo `odyssey-portal-frontend`**, không có job CI nào so hai bên.

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/auth/actions.py migrations/versions/0944_billing_action.py \
        contracts/actions.json tests/modules/billing/test_action.py
git commit -m "feat(billing): action billing.read + migration 0944"
```

---

### Task 7: `router.py` — 5 endpoint tenant

**Files:**
- Create: `src/portal/modules/billing/router.py`
- Create: `tests/modules/billing/test_router.py`

**Interfaces:**
- Consumes: Task 5 (`repo.*`, `contracts.*`), Task 6 (`ACTIONS.BILLING_READ`)
- Produces: `ROUTER` với `GET /billing/summary` · `/billing/by-key` · `/billing/by-owner` · `/billing/sessions` · `/billing/sessions/{session_id}`

- [ ] **Step 1: Viết test router**

```python
# tests/modules/billing/test_router.py
"""Tầng HTTP. Bài quan trọng nhất là test_khong_co_action_thi_403 — endpoint quên
require() vẫn chạy và không lỗi nào phát ra, chỉ là ai cũng xem được hoá đơn.
"""

import httpx
import pytest

from tests.modules.billing.conftest import MAT_KHAU, SESSION, TENANT

BASE = "/api/v1/billing"


async def _dang_nhap(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login",
                          json={"email": "bil@noblex.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text


async def test_summary(app_client, workspace_billing, bang_gia_vi_du) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/summary", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["soPhien"] == 1
    assert d["currency"] == "VND"
    assert "canhBao" in d
    assert d["canhBao"]["thieuGia"] == 0


async def test_by_key_giu_nhom_chua_phan_loai(
    app_client, workspace_billing, bang_gia_vi_du
) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/by-key", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    tong_dong = sum(x["chiPhi"] for x in d["items"])
    assert abs(float(tong_dong) - float(d["chiPhiTong"])) < 0.01, (
        "tổng các dòng lệch tổng hoá đơn — nhóm chưa phân loại bị ẩn?"
    )


async def test_chi_tiet_phien(app_client, workspace_billing, bang_gia_vi_du) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/sessions/{SESSION}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["events"]) == 13
    assert "xấp xỉ" in d["ghiChuTurn"]


async def test_phien_khong_ton_tai_404(app_client, workspace_billing) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/sessions/khong-co-that")
    assert r.status_code == 404


async def test_khong_dang_nhap_thi_401(app_client, workspace_billing) -> None:
    r = await app_client.get(f"{BASE}/summary")
    assert r.status_code == 401


async def test_moi_route_khai_action() -> None:
    """Cổng chung đã có ở tests/api — bài này chỉ neo cho module billing."""
    from portal.core.auth.actions import ACTIONS
    from portal.modules.billing.router import ROUTER

    for route in ROUTER.routes:
        deps = getattr(route, "dependencies", [])
        assert deps or route.dependant.dependencies, (
            f"{route.path} không khai dependency nào — thiếu require()?"
        )
    assert ACTIONS.BILLING_READ  # tránh import thừa bị ruff gỡ
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/billing/test_router.py -q`
Expected: FAIL — `ModuleNotFoundError: portal.modules.billing.router`.

- [ ] **Step 3: Viết `router.py`**

```python
"""Endpoint module Usage & Billing.

CHỈ GET — không có đường ghi nào ở tầng tenant. Định giá là job (Task 8), bảng giá
là màn admin nền tảng (Task 9).

Mọi endpoint dùng `ACTIONS.BILLING_READ`. Tách khỏi `WORKSPACE_ADMIN` để kế toán
xem được hoá đơn mà không cần quyền quản trị thành viên.
"""

from datetime import date, timedelta

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.billing import repo
from portal.modules.billing.contracts import (
    TRANG_MAC_DINH,
    TRANG_TOI_DA,
    CanhBaoOut,
    ChiTietPhienOut,
    DanhSachKeyOut,
    DanhSachPhienOut,
    DongKeyOut,
    DongOwnerOut,
    EventOut,
    PhienUsageOut,
    TongQuanOut,
)

ROUTER = APIRouter(tags=["billing"])
"""KHÔNG prefix chung — `api/app.py` gắn `/api/v1`."""

_MAC_DINH_NGAY = 30


def _khoang(tu: date | None, den: date | None) -> tuple[date, date]:
    """Mặc định 30 ngày gần nhất. `den` là cận TRÊN MỞ — `< den`, không `<=`.

    Dùng `<=` thì một dòng landed lúc 00:00:00.5 ngày cuối rơi ra ngoài, và cùng
    một kỳ đếm ra hai số khác nhau tuỳ ai gọi.
    """
    den_ = den or (date.today() + timedelta(days=1))
    tu_ = tu or (den_ - timedelta(days=_MAC_DINH_NGAY))
    if tu_ >= den_:
        raise loi.LoiPortal(422, "KHOANG_KHONG_HOP_LE", "`from` phải trước `to`")
    return tu_, den_


@ROUTER.get("/billing/summary", response_model=TongQuanOut)
async def summary(
    p: Principal = Depends(require(ACTIONS.BILLING_READ)),
    pool: asyncpg.Pool = Depends(lay_pool),
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
) -> TongQuanOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        r = await repo.tong_quan(conn, tu_, den_)
        cb = await repo.canh_bao(conn)
    return TongQuanOut(
        input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"],
        cache_read_tokens=r["cache_read_tokens"],
        voice_sec=r["voice_sec"],
        so_phien=r["so_phien"],
        so_key=r["so_key"],
        chi_phi=r["chi_phi"],
        currency=r["currency"],
        canh_bao=CanhBaoOut(
            thieu_gia=cb["thieu_gia"],
            nhan_chua_phan_loai=cb["nhan_chua_phan_loai"],
            event_khong_so_do=cb["event_khong_so_do"],
            llm_khong_chinh_xac=cb["llm_khong_chinh_xac"],
        ),
    )


@ROUTER.get("/billing/by-key", response_model=DanhSachKeyOut)
async def by_key(
    p: Principal = Depends(require(ACTIONS.BILLING_READ)),
    pool: asyncpg.Pool = Depends(lay_pool),
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
) -> DanhSachKeyOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.theo_key(conn, tu_, den_)
    items = [
        DongKeyOut(
            agent_key_id=r["agent_key_id"], label=r["label"], key_prefix=r["key_prefix"],
            nguoi_tao=r["nguoi_tao"], nguoi_tao_ten=r["nguoi_tao_ten"],
            da_thu_hoi=r["da_thu_hoi"], so_phien=r["so_phien"],
            input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"], voice_sec=r["voice_sec"],
            so_event=r["so_event"], chi_phi=r["chi_phi"],
        )
        for r in hang
    ]
    return DanhSachKeyOut(
        items=items, total=len(items),
        chi_phi_tong=sum((i.chi_phi for i in items), start=items[0].chi_phi * 0)
        if items else 0,
        currency="VND",
    )


@ROUTER.get("/billing/by-owner", response_model=list[DongOwnerOut])
async def by_owner(
    p: Principal = Depends(require(ACTIONS.BILLING_READ)),
    pool: asyncpg.Pool = Depends(lay_pool),
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
) -> list[DongOwnerOut]:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.theo_owner(conn, tu_, den_)
    return [
        DongOwnerOut(user_id=r["user_id"], ten=r["ten"], email=r["email"],
                     so_key=r["so_key"], so_phien=r["so_phien"], chi_phi=r["chi_phi"])
        for r in hang
    ]


@ROUTER.get("/billing/sessions", response_model=DanhSachPhienOut)
async def sessions(
    p: Principal = Depends(require(ACTIONS.BILLING_READ)),
    pool: asyncpg.Pool = Depends(lay_pool),
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    limit: int = Query(TRANG_MAC_DINH, ge=1, le=TRANG_TOI_DA),
    offset: int = Query(0, ge=0),
) -> DanhSachPhienOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_phien(conn, tu_, den_, limit, offset)
    return DanhSachPhienOut(
        items=[_phien_out(r) for r in hang],
        total=hang[0]["total"] if hang else 0,
    )


@ROUTER.get("/billing/sessions/{session_id}", response_model=ChiTietPhienOut)
async def chi_tiet_phien(
    session_id: str,
    p: Principal = Depends(require(ACTIONS.BILLING_READ)),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChiTietPhienOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        ev = await repo.event_cua_phien(conn, session_id)
        if not ev:
            raise loi.LoiPortal(404, "PHIEN_KHONG_TON_TAI",
                                f"không có usage cho phiên `{session_id}`")
        hang = await repo.liet_ke_phien(
            conn, ev[0]["occurred_at"].date(),
            ev[-1]["occurred_at"].date() + timedelta(days=1), 1, 0,
        )
    return ChiTietPhienOut(
        phien=_phien_out(hang[0]),
        events=[
            EventOut(
                event_id=r["event_id"], seq=r["seq"], turn_idx=r["turn_idx"],
                component=r["component"], purpose=r["purpose"], provider=r["provider"],
                model=r["model"], input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"], cache_read_tokens=r["cache_read_tokens"],
                audio_sec=r["audio_sec"], units=r["units"], exact=r["exact"],
                chi_phi=r["chi_phi"], occurred_at=r["occurred_at"],
            )
            for r in ev
        ],
    )


def _phien_out(r: asyncpg.Record) -> PhienUsageOut:
    return PhienUsageOut(
        session_id=r["session_id"], agent_key_id=r["agent_key_id"],
        key_label=r["key_label"], customer_name=r["customer_name"], phone=r["phone"],
        channel=r["channel"], bat_dau=r["bat_dau"], so_turn=r["so_turn"],
        input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
        voice_sec=r["voice_sec"], chi_phi=r["chi_phi"], exact=r["exact"],
    )
```

⚠️ Kiểm tên chính xác của `loi.LoiPortal` và cách khai `require()`/`lay_pool` bằng cách đọc `src/portal/modules/ops/router.py` — chép đúng khuôn ở đó, đừng đoán.

- [ ] **Step 4: Chạy test router**

Run: `uv run pytest tests/modules/billing/test_router.py -q`
Expected: PASS 6/6.

- [ ] **Step 5: Chạy cổng khai action toàn repo**

Run: `uv run pytest tests/api tests/test_module_boundaries.py -q`
Expected: PASS. Đỏ ở `test_module_boundaries` ⇒ có import ruột module khác; sửa thành `from portal.modules.x.contracts import Y`.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/billing/router.py tests/modules/billing/test_router.py
git commit -m "feat(billing): 5 endpoint đọc usage + chi phí"
```

---

### Task 8: Job định giá + cửa sổ re-run 48h

**Files:**
- Create: `src/portal/cli/dinh_gia_usage.py`
- Create: `tests/modules/billing/test_dinh_gia_job.py`

**Interfaces:**
- Consumes: Task 1 (`billing.rate_usage`)
- Produces: `python -m portal.cli.dinh_gia_usage [--tu YYYY-MM-DD] [--den YYYY-MM-DD] [--thu-kho]`

- [ ] **Step 1: Viết test**

```python
# tests/modules/billing/test_dinh_gia_job.py
"""Job định giá. Cửa sổ re-run 48h là yêu cầu từ §5.4 của bên agent: đường ghi
là fire-and-forget có retry, lô của một phiên có thể landed muộn vài phút nhưng
vẫn mang `occurred_at` đúng lúc phát sinh. Chốt sổ ngay 00:00 ngày 1 là bỏ sót.
"""

from datetime import UTC, date, datetime, timedelta

import asyncpg

from portal.cli.dinh_gia_usage import KHOANG_RE_RUN_GIO, chay


async def test_cua_so_re_run_la_48h() -> None:
    assert KHOANG_RE_RUN_GIO == 48, (
        "đổi hằng này là đổi một quyết định nghiệp vụ — đọc §5.4 hướng dẫn bên agent"
    )


async def test_chay_dinh_gia_moi_tenant(pool, workspace_billing, bang_gia_vi_du) -> None:
    so_dong = await chay(pool, tu=date(2026, 8, 1), den=date(2026, 9, 1))
    assert so_dong > 0
    async with pool.acquire() as conn:
        tong = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage")
    assert tong > 0


async def test_thu_kho_khong_ghi_gi(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Diễn tập phải KHÔNG để lại dòng nào — nếu không thì không ai dám thử."""
    await chay(pool, tu=date(2026, 8, 1), den=date(2026, 9, 1), thu_kho=True)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM billing.rated_usage") == 0


async def test_mac_dinh_phu_cua_so_re_run(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Gọi không tham số phải phủ lùi 48h, không chỉ hôm nay."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ('bilw', 'bil-sess-voice-1', 'voice', 77, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 1000, $1)""",
            datetime.now(UTC) - timedelta(hours=30),
        )
    await chay(pool)
    async with pool.acquire() as conn:
        co = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage r JOIN billing.usage_events e "
            "ON e.event_id = r.event_id WHERE e.seq = 77"
        )
    assert co > 0, "event 30h trước không được định giá — cửa sổ re-run không hoạt động"
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/billing/test_dinh_gia_job.py -q`
Expected: FAIL — `ModuleNotFoundError: portal.cli.dinh_gia_usage`.

- [ ] **Step 3: Viết CLI**

```python
"""Định giá usage — lệnh cho cron.

    python -m portal.cli.dinh_gia_usage                    # phủ lùi 48h
    python -m portal.cli.dinh_gia_usage --tu 2026-08-01 --den 2026-09-01
    python -m portal.cli.dinh_gia_usage --thu-kho          # diễn tập, không ghi

VÌ SAO PHỦ LÙI 48H MẶC ĐỊNH: §5.4 hướng dẫn bên agent — đường ghi là
fire-and-forget có retry theo seq, nên lô của một phiên có thể landed muộn vài phút
tới vài giờ (vẫn mang `occurred_at` đúng lúc phát sinh). Định giá đúng cửa sổ hôm
nay là bỏ sót những dòng đó, và bỏ sót IM LẶNG.

`billing.rate_usage()` idempotent (`ON CONFLICT (event_id, metric) DO UPDATE`) nên
chạy trùng nhiều lần không nhân bản — đó là điều kiện để cửa sổ chồng lấn an toàn.

LỆNH RIÊNG, không gộp vào job khác: ops phải tắt được cái này mà giữ cái kia, và
mỗi lượt cần để lại số dòng đã xử lý để trả lời "đêm qua định giá bao nhiêu".
"""

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import asyncpg

from portal.core.config import get_settings

log = logging.getLogger(__name__)

KHOANG_RE_RUN_GIO = 48
"""Cửa sổ phủ lùi mặc định. Đổi số này là đổi một quyết định nghiệp vụ."""


async def chay(
    pool: asyncpg.Pool,
    tu: date | None = None,
    den: date | None = None,
    thu_kho: bool = False,
) -> int:
    """Trả số dòng `rated_usage` đã ghi/cập nhật. `tenant = NULL` ⇒ mọi tenant."""
    if tu is None or den is None:
        bay_gio = datetime.now(UTC)
        tu_ts = bay_gio - timedelta(hours=KHOANG_RE_RUN_GIO)
        den_ts = bay_gio + timedelta(minutes=1)
    else:
        tu_ts = datetime(tu.year, tu.month, tu.day, tzinfo=UTC)
        den_ts = datetime(den.year, den.month, den.day, tzinfo=UTC)

    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            n = await conn.fetchval(
                "SELECT billing.rate_usage($1, $2, NULL)", tu_ts, den_ts
            )
            if thu_kho:
                await tx.rollback()
                log.info("THỬ KHÔ: sẽ định giá %s dòng (%s → %s)", n, tu_ts, den_ts)
                return n
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise
    log.info("đã định giá %s dòng (%s → %s)", n, tu_ts, den_ts)
    return n


def _ngay(s: str) -> date:
    return date.fromisoformat(s)


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Định giá billing.usage_events")
    ap.add_argument("--tu", type=_ngay, default=None)
    ap.add_argument("--den", type=_ngay, default=None)
    ap.add_argument("--thu-kho", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    c = get_settings()
    pool = await asyncpg.create_pool(c.migrator_url, min_size=1, max_size=2)
    try:
        await chay(pool, tu=a.tu, den=a.den, thu_kho=a.thu_kho)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
```

⚠️ Dùng `migrator_url` chứ không `database_url`: `rate_usage` là SECURITY DEFINER nên `portal_api` gọi được, nhưng job này chạy cho MỌI tenant (`NULL`) — đó là thao tác cấp nền tảng, không thuộc phạm vi một request. Kiểm tên trường thật trong `core/config.py` trước khi viết.

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/billing/test_dinh_gia_job.py -q`
Expected: PASS 4/4.

- [ ] **Step 5: Chạy thử khô trên DB dev**

```bash
uv run python -m portal.cli.dinh_gia_usage --thu-kho
```
Expected: in `THỬ KHÔ: sẽ định giá N dòng`, và `SELECT count(*) FROM billing.rated_usage` vẫn 0.

- [ ] **Step 6: Commit**

```bash
git add src/portal/cli/dinh_gia_usage.py tests/modules/billing/test_dinh_gia_job.py
git commit -m "feat(billing): CLI định giá usage với cửa sổ re-run 48h"
```

---

### Task 9: Màn admin bảng giá + cổng cảnh báo

**Files:**
- Create: `src/portal/modules/billing/service.py`
- Modify: `src/portal/modules/billing/router.py` (thêm 4 endpoint `/admin/billing/*`)
- Modify: `src/portal/modules/billing/contracts.py` (thêm In/Out bảng giá)
- Create: `tests/modules/billing/test_admin_pricing.py`
- Create: `tests/modules/billing/test_cong_canh_bao.py`

**Interfaces:**
- Consumes: Task 1, `portal.core.auth.quan_tri_nen_tang` (header `X-Platform-Admin-Token`)
- Produces: `GET/POST /admin/billing/price-versions` · `POST /admin/billing/price-versions/{id}/items` · `POST /admin/billing/price-versions/{id}/activate` · `GET /admin/billing/price-versions/{id}/preview` · **`POST /admin/billing/tenants/{tenant_id}/price-version`** · `POST /admin/billing/rate`

- [ ] **Step 1: Viết test cổng cảnh báo**

```python
# tests/modules/billing/test_cong_canh_bao.py
"""Ba view cổng. Chúng là cơ chế chống MẤT DOANH THU ÂM THẦM, nên bài quan trọng
nhất không phải "view rỗng khi đủ giá" mà "view KÊU khi thiếu giá".

Một cổng chưa bao giờ thấy đỏ là một cổng chưa biết có hoạt động không.
"""

import asyncpg

from tests.modules.billing.conftest import TENANT


async def test_du_gia_thi_ba_view_rong(pool, workspace_billing, bang_gia_vi_du) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )
        assert await conn.fetchval("SELECT count(*) FROM billing.price_coverage_gap") == 0
        assert await conn.fetchval("SELECT count(*) FROM billing.purpose_unclassified") == 0
        assert await conn.fetchval("SELECT count(*) FROM billing.unbillable_event") == 0


async def test_thieu_gia_thi_view_keu(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bỏ giá cache_read — đúng cái §1.1 hướng dẫn bên agent nói "luôn 0" (SAI).

    Data thật có cache_read_tokens = 35.548 cho gemini-2.5-flash. Ai tin §1.1 rồi
    bỏ dòng giá này sẽ mất tiền, và mất IM LẶNG vì không có dòng giá nào để đối chiếu.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM billing.price_item WHERE price_version_id = $1 "
            "AND metric = 'cache_read_tokens'", bang_gia_vi_du,
        )
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )
        gap = await conn.fetch("SELECT * FROM billing.price_coverage_gap")
    assert len(gap) == 1, "thiếu giá cache_read mà price_coverage_gap không kêu"
    assert gap[0]["metric"] == "cache_read_tokens"
    assert gap[0]["quantity"] > 0


async def test_gia_0_khong_bi_coi_la_thieu(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Miễn phí TƯỜNG MINH (giá 0) khác với thiếu giá. Không phân biệt được thì
    view kêu mãi và người trực học cách bỏ qua nó."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, "
            "'2100-01-01'::timestamptz, $1)", TENANT,
        )
        # cache_write có giá 0 và có dòng giá ⇒ không được coi là gap
        gap = await conn.fetchval(
            "SELECT count(*) FROM billing.price_coverage_gap "
            "WHERE metric = 'cache_write_tokens'"
        )
    assert gap == 0
```

- [ ] **Step 2: Chạy — 3 bài này phải xanh ngay (không cần code mới)**

Run: `uv run pytest tests/modules/billing/test_cong_canh_bao.py -q`
Expected: PASS 3/3. Đỏ ⇒ view ở Task 1 sai, sửa `_DDL`.

- [ ] **Step 3: Viết test admin pricing**

```python
# tests/modules/billing/test_admin_pricing.py
"""Màn admin bảng giá. Xác thực bằng header X-Platform-Admin-Token, KHÔNG bằng
phiên — đặt giá là việc của NobleX, không của khách."""

import httpx

BASE = "/api/v1/admin/billing"
TOKEN = {"X-Platform-Admin-Token": "test-admin-token"}


async def test_khong_token_thi_403(app_client) -> None:
    r = await app_client.get(f"{BASE}/price-versions")
    assert r.status_code == 403


async def test_tao_bang_gia_va_dong_gia(app_client, monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN,
        json={"code": "pv_api", "name": "qua API", "currency": "VND"},
    )
    assert r.status_code == 201, r.text
    pb = r.json()["id"]

    r = await app_client.post(
        f"{BASE}/price-versions/{pb}/items", headers=TOKEN,
        json={"component": "llm", "provider": "gemini", "model": "gemini-2.5-flash",
              "metric": "input_tokens", "unitPrice": "2500", "perUnits": 1000000},
    )
    assert r.status_code == 201, r.text


async def test_chan_hai_co_so_stt(app_client, monkeypatch) -> None:
    """DB chặn bằng unique index; API phải dịch thành 409 có thông điệp đọc được,
    không phải 500 UniqueViolation."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN,
        json={"code": "pv_stt", "name": "stt", "currency": "VND"},
    )
    pb = r.json()["id"]
    for purpose, metric, per in (("conversation", "audio_sec", 1), ("stream", "wall_ms", 60000)):
        r = await app_client.post(
            f"{BASE}/price-versions/{pb}/items", headers=TOKEN,
            json={"component": "stt", "purpose": purpose, "metric": metric,
                  "unitPrice": "10", "perUnits": per},
        )
    assert r.status_code == 409, f"phải 409, nhận {r.status_code}: {r.text}"
    assert "STT" in r.json()["message"]


async def test_preview_khong_ghi_gi(app_client, monkeypatch, workspace_billing) -> None:
    """Preview áp bảng giá nháp lên usage 30 ngày — phải KHÔNG để lại dòng nào."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN,
        json={"code": "pv_prev", "name": "preview", "currency": "VND"},
    )
    pb = r.json()["id"]
    r = await app_client.get(f"{BASE}/price-versions/{pb}/preview",
                             headers=TOKEN, params={"tenant": "bilw"})
    assert r.status_code == 200, r.text
    assert "chiPhi" in r.json()
```

- [ ] **Step 4: Viết `service.py` + endpoint admin**

`service.py`:

```python
"""Quy tắc nghiệp vụ bảng giá. Router không chạm SQL trực tiếp ở đường admin.

`kich_hoat` là chỗ duy nhất được đặt `status='active'`, và nó KIỂM TRƯỚC KHI ĐẶT:
một bảng giá active mà thiếu dòng giá là mất doanh thu im lặng cho mọi tenant dùng nó.
"""

import asyncpg

from portal.api import loi
from portal.core.auth.quan_tri_nen_tang import ACTOR_QUAN_TRI


async def them_dong_gia(conn: asyncpg.Connection, pb: int, **truong) -> int:
    try:
        return await conn.fetchval(
            """INSERT INTO billing.price_item
               (price_version_id, component, purpose, provider, model, metric,
                unit_price, per_units, note)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
            pb, truong["component"], truong.get("purpose", ""),
            truong.get("provider", ""), truong.get("model", ""), truong["metric"],
            truong["unit_price"], truong.get("per_units", 1), truong.get("note", ""),
        )
    except asyncpg.UniqueViolationError as e:
        if "price_item_stt_single_basis" in str(e):
            raise loi.LoiPortal(
                409, "STT_HAI_CO_SO",
                "STT chỉ được tính tiền theo MỘT cơ sở. `(stt,'conversation')/audio_sec` "
                "và `(stt,'stream')/wall_ms` là hai cách đo cùng một dịch vụ — đặt giá "
                "cả hai là tính tiền STT hai lần. Đặt cơ sở không dùng về 0.",
            ) from e
        raise loi.LoiPortal(409, "DONG_GIA_TRUNG",
                            "đã có dòng giá cho cùng bộ (component, purpose, provider, "
                            "model, metric)") from e


async def kich_hoat(conn: asyncpg.Connection, pb: int) -> None:
    """Chặn kích hoạt bảng giá còn lỗ. Đây là cửa cuối trước khi tiền chạy sai."""
    thieu = await conn.fetch(
        """SELECT cs.component, cs.purpose, cs.metric
             FROM billing.pricing_basis cs
            WHERE NOT EXISTS (
                  SELECT 1 FROM billing.price_item pi
                   WHERE pi.price_version_id = $1
                     AND pi.component = cs.component
                     AND pi.metric = cs.metric
                     AND (pi.purpose = '' OR pi.purpose = cs.purpose))""",
        pb,
    )
    if thieu:
        ds = ", ".join(f"{r['component']}/{r['metric']}" for r in thieu)
        raise loi.LoiPortal(
            409, "BANG_GIA_CON_LO",
            f"chưa có dòng giá cho: {ds}. Muốn miễn phí thì tạo dòng giá 0 — "
            "để trống nghĩa là âm thầm miễn phí và không cảnh báo nào kêu.",
        )
    await conn.execute(
        "UPDATE billing.price_version SET status = 'active' WHERE id = $1", pb)
    await conn.execute(
        """INSERT INTO control.audit_log (tenant_id, actor, hanh_dong, payload)
           VALUES (NULL, $1, 'billing.price_version_kich_hoat', $2::jsonb)""",
        ACTOR_QUAN_TRI, f'{{"price_version_id": {pb}}}',
    )
```

Thêm vào `router.py` (khuôn xác thực chép từ `modules/enrollment/router.py` các route `/admin/*`):

```python
from portal.core.auth.quan_tri_nen_tang import doi_hoi_quan_tri
from portal.modules.billing import service


@ROUTER.post("/admin/billing/price-versions", status_code=201,
             dependencies=[Depends(doi_hoi_quan_tri)])
async def tao_bang_gia(
    body: PhienBanGiaIn, pool: asyncpg.Pool = Depends(lay_pool)
) -> dict[str, int]:
    async with pool.acquire() as conn:
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status, created_by) "
            "VALUES ($1, $2, $3, 'inactive', 'platform_admin') RETURNING id",
            body.code, body.name, body.currency,
        )
    return {"id": pb}


@ROUTER.post("/admin/billing/price-versions/{pb}/items", status_code=201,
             dependencies=[Depends(doi_hoi_quan_tri)])
async def tao_dong_gia(
    pb: int, body: DongGiaIn, pool: asyncpg.Pool = Depends(lay_pool)
) -> dict[str, int]:
    async with pool.acquire() as conn:
        return {"id": await service.them_dong_gia(conn, pb, **body.model_dump())}


@ROUTER.post("/admin/billing/price-versions/{pb}/activate",
             dependencies=[Depends(doi_hoi_quan_tri)])
async def kich_hoat_bang_gia(
    pb: int, pool: asyncpg.Pool = Depends(lay_pool)
) -> dict[str, str]:
    async with pool.acquire() as conn, conn.transaction():
        await service.kich_hoat(conn, pb)
    return {"status": "active"}


@ROUTER.get("/admin/billing/price-versions/{pb}/preview",
            dependencies=[Depends(doi_hoi_quan_tri)])
async def preview_bang_gia(
    pb: int, tenant: str, pool: asyncpg.Pool = Depends(lay_pool)
) -> dict[str, object]:
    """Áp bảng giá nháp lên usage 30 ngày rồi ROLLBACK — không ghi dòng nào.

    Không có màn này thì kích hoạt một bảng giá là một phép thử trên tiền thật.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                "INSERT INTO billing.tenant_price_version "
                "(tenant_id, price_version_id, effective_from) "
                "VALUES ($1, $2, now() - interval '30 days')", tenant, pb,
            )
            await conn.execute(
                "DELETE FROM billing.rated_usage WHERE tenant_id = $1 "
                "AND occurred_at >= now() - interval '30 days'", tenant,
            )
            await conn.execute(
                "SELECT billing.rate_usage(now() - interval '30 days', now(), $1)", tenant)
            r = await conn.fetchrow(
                "SELECT sum(amount) AS chi_phi, min(currency) AS currency "
                "FROM billing.rated_usage WHERE tenant_id = $1", tenant,
            )
            return {"chiPhi": str(r["chi_phi"] or 0), "currency": r["currency"] or "VND"}
        finally:
            await tx.rollback()
```

Thêm vào `contracts.py`:

```python
class PhienBanGiaIn(_Base):
    code: str = Field(min_length=1, max_length=64)
    name: str = ""
    currency: str = Field(default="VND", pattern="^[A-Z]{3}$")


class DongGiaIn(_Base):
    component: str = Field(min_length=1)
    purpose: str = ""
    provider: str = ""
    model: str = ""
    metric: str = Field(min_length=1)
    unit_price: Decimal = Field(ge=0, alias="unitPrice")
    per_units: int = Field(default=1, gt=0, alias="perUnits")
    note: str = ""
```

- [ ] **Step 5: Gán bộ giá cho tenant — bước ⑤ của luồng, KHÔNG được thiếu**

Không có endpoint này thì `activate` một bộ giá **không làm gì cả** cho bất kỳ tenant
nào (trừ đường `is_default`), và cả module chạy mãi bằng một bộ giá duy nhất.

Thêm vào `tests/modules/billing/test_admin_pricing.py`:

```python
async def test_gan_bo_gia_dong_khoang_cu_khong_ho_khong_chong(
    app_client, monkeypatch, pool, workspace_billing
) -> None:
    """Đóng khoảng cũ và mở khoảng mới ở CÙNG MỘT MỐC.

    Lệch mốc theo hai chiều đều sai và đều im lặng:
    · để hở  ⇒ usage rơi vào khe không bộ giá nào phủ ⇒ rate_usage bỏ qua ⇒ MIỄN PHÍ
    · chồng  ⇒ hai bộ cùng hiệu lực ⇒ EXCLUDE constraint ném (đây là chiều AN TOÀN,
               nó ồn ào chứ không âm thầm)
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    ids = []
    for code in ("pv_g1", "pv_g2"):
        r = await app_client.post(
            f"{BASE}/price-versions", headers=TOKEN,
            json={"code": code, "name": code, "currency": "VND"},
        )
        ids.append(r.json()["id"])

    for pv, tu in zip(ids, ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")):
        r = await app_client.post(
            f"{BASE}/tenants/bilw/price-version", headers=TOKEN,
            json={"priceVersionId": pv, "effectiveFrom": tu},
        )
        assert r.status_code == 200, r.text

    async with pool.acquire() as conn:
        hang = await conn.fetch(
            "SELECT price_version_id, effective_from, effective_to "
            "FROM billing.tenant_price_version WHERE tenant_id = 'bilw' "
            "ORDER BY effective_from"
        )
    assert len(hang) == 2
    assert hang[0]["effective_to"] == hang[1]["effective_from"], (
        "khoảng cũ không đóng đúng mốc mở của khoảng mới — có hở hoặc có chồng"
    )
    assert hang[1]["effective_to"] is None, "khoảng đang chạy phải để NULL"


async def test_gan_moc_qua_khu_bi_chan(app_client, monkeypatch) -> None:
    """Gán lùi vào một kỳ đã định giá là viết lại tiền quá khứ."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN,
        json={"code": "pv_g3", "name": "g3", "currency": "VND"},
    )
    pv = r.json()["id"]
    r = await app_client.post(
        f"{BASE}/tenants/bilw/price-version", headers=TOKEN,
        json={"priceVersionId": pv, "effectiveFrom": "2020-01-01T00:00:00Z"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "MOC_QUA_KHU_DA_DINH_GIA"
```

Thêm vào `service.py`:

```python
async def gan_cho_tenant(
    conn: asyncpg.Connection, tenant: str, pv: int, tu: datetime
) -> None:
    """Đóng khoảng đang chạy tại `tu` rồi mở khoảng mới cũng tại `tu`.

    Dùng CÙNG MỘT giá trị cho `effective_to` của dòng cũ và `effective_from` của
    dòng mới. `tstzrange` là nửa mở `[from, to)` nên hai khoảng khít nhau mà không
    chồng — EXCLUDE constraint chấp nhận, và không có giây nào không bộ giá nào phủ.

    KHÔNG cho gán lùi vào kỳ đã định giá: `rated_usage` của kỳ đó đã chốt đơn giá,
    gán lùi rồi tính lại là ra một số tiền khác cho một kỳ đã phát hành.
    """
    if await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM billing.rated_usage "
        "WHERE tenant_id = $1 AND occurred_at >= $2)", tenant, tu,
    ):
        raise loi.LoiPortal(
            409, "MOC_QUA_KHU_DA_DINH_GIA",
            f"đã có usage được định giá từ {tu:%d/%m/%Y} trở đi. Chọn một mốc sau "
            "kỳ đã chốt, hoặc xoá rated_usage của kỳ đó trước nếu thật sự muốn "
            "tính lại.",
        )
    if await conn.fetchval(
        "SELECT status FROM billing.price_version WHERE id = $1", pv
    ) != "active":
        raise loi.LoiPortal(
            409, "BO_GIA_CHUA_KICH_HOAT",
            "kích hoạt bộ giá trước khi gán — activate là cửa kiểm bộ giá còn lỗ.",
        )
    await conn.execute(
        "UPDATE billing.tenant_price_version SET effective_to = $2 "
        "WHERE tenant_id = $1 AND effective_to IS NULL", tenant, tu,
    )
    await conn.execute(
        "INSERT INTO billing.tenant_price_version "
        "(tenant_id, price_version_id, effective_from) VALUES ($1, $2, $3)",
        tenant, pv, tu,
    )
    await conn.execute(
        "UPDATE billing.price_version SET status = 'inactive' "
        "WHERE id <> $1 AND status = 'active' AND NOT is_default "
        "AND NOT EXISTS (SELECT 1 FROM billing.tenant_price_version t "
        "WHERE t.price_version_id = billing.price_version.id "
        "AND t.effective_to IS NULL)", pv,
    )
```

Thêm vào `router.py`:

```python
@ROUTER.post("/admin/billing/tenants/{tenant_id}/price-version",
             dependencies=[Depends(doi_hoi_quan_tri)])
async def gan_bo_gia(
    tenant_id: str, body: GanBoGiaIn, pool: asyncpg.Pool = Depends(lay_pool)
) -> dict[str, str]:
    async with pool.acquire() as conn, conn.transaction():
        await service.gan_cho_tenant(conn, tenant_id, body.price_version_id,
                                    body.effective_from)
    return {"status": "ok"}
```

Thêm vào `contracts.py`:

```python
class GanBoGiaIn(_Base):
    price_version_id: int = Field(alias="priceVersionId")
    effective_from: datetime = Field(alias="effectiveFrom")
```

⚠️ `effective_from` phải **tz-aware**. Pydantic nhận naive datetime nếu không chặn, và
asyncpg encode naive theo giờ HOST — cùng bài học `occurredAt` của module `ingest`
(xem Change Log 2026-08-15). Thêm validator ném 422 nếu `tzinfo is None`.

- [ ] **Step 6: Chạy test admin**

Run: `uv run pytest tests/modules/billing/test_admin_pricing.py -q`
Expected: PASS 4/4. ⚠️ Kiểm tên thật của dependency quản trị nền tảng trong `src/portal/core/auth/quan_tri_nen_tang.py` — trong file đó hàm kiểm token tên `_kiem_token`, nên tên public để `Depends()` có thể khác `doi_hoi_quan_tri`; đọc rồi dùng đúng tên.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/billing/ tests/modules/billing/
git commit -m "feat(billing): màn admin bộ giá — nhập, preview, kích hoạt, gán tenant"
```

---

### Task 10: Migration 0945 — siết attribution

Tách khỏi Task 1 vì nó đụng bảng của module khác (`tenant_data.conversations`) và có thể bị từ chối riêng.

**Files:**
- Create: `migrations/versions/0945_conversations_agent_key_fk.py`
- Create: `tests/modules/billing/test_attribution.py`

**Interfaces:**
- Consumes: `control.agent_keys`, `tenant_data.conversations`
- Produces: constraint `agent_keys_tenant_id_uk`, constraint `conversations_agent_key_fkey` (composite, RESTRICT)

- [ ] **Step 1: Viết test**

```python
# tests/modules/billing/test_attribution.py
"""Attribution phải không thể sai ở tầng DB.

Hai lỗ trước 0945:
① FK chỉ tham chiếu agent_keys(id) ⇒ gán được khoá của tenant KHÁC cho conversation
   ⇒ usage bị quy sai người, không gì chặn.
② ON DELETE SET NULL ⇒ xoá một khoá là toàn bộ usage quá khứ của nó rơi về
   "chưa phân loại" ⇒ mất lịch sử ai đã dùng. Đã có revoked_at cho việc thu hồi.
"""

import asyncpg
import pytest

from tests.modules.billing.conftest import TENANT, TENANT_KHAC


async def test_khong_gan_duoc_khoa_cua_tenant_khac(pool, workspace_billing) -> None:
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO tenant_data.conversations "
                "(tenant_id, session_id, source, agent_key_id) "
                "VALUES ($1, 'sess-lan-tenant', 'chat', $2)",
                TENANT, workspace_billing["key_id_khac"],
            )


async def test_khong_xoa_duoc_khoa_da_co_usage(pool, workspace_billing) -> None:
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "DELETE FROM control.agent_keys WHERE id = $1",
                workspace_billing["key_id"],
            )


async def test_thu_hoi_van_duoc(pool, workspace_billing) -> None:
    """Thu hồi là đường ĐÚNG — nó giữ lịch sử, khác xoá."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE control.agent_keys SET revoked_at = now() WHERE id = $1",
            workspace_billing["key_id"],
        )
        con = await conn.fetchval(
            "SELECT agent_key_id FROM tenant_data.conversations WHERE tenant_id = $1",
            TENANT,
        )
    assert con == workspace_billing["key_id"], "thu hồi không được làm mất attribution"
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/billing/test_attribution.py -q`
Expected: FAIL 2/3 — hai bài đầu đỏ (chưa có constraint), bài `test_thu_hoi_van_duoc` xanh.

- [ ] **Step 3: Viết migration 0945**

```python
"""siết attribution: composite FK + ON DELETE RESTRICT trên conversations.agent_key_id

HAI LỖ ĐANG MỞ, đo được trên DB dev 2026-08-19:

① FK hiện tại `conversations_agent_key_id_fkey` chỉ tham chiếu `agent_keys(id)`.
   Về mặt DB, gán khoá của tenant A cho conversation của tenant B là HỢP LỆ. Data
   hiện không có ca nào (đã kiểm: 0 hàng lệch tenant), nhưng không gì chặn. Từ khi
   `0940` cho `agent_keys` cột `tenant_id`, việc này chặn được bằng composite FK —
   trước đó thì không.

② `ON DELETE SET NULL` nghĩa là xoá một khoá thì TOÀN BỘ usage quá khứ của nó rơi
   về "chưa phân loại": mất thông tin ai đã dùng, mà không lỗi nào phát ra và số
   tổng vẫn đúng nên không ai thấy. Bảng đã có `revoked_at` — đường đúng là thu hồi,
   không xoá. RESTRICT biến quy ước đó thành ràng buộc.

⚠️ ĐƯỜNG XOÁ KHOÁ Ở TẦNG APP PHẢI CHUYỂN SANG `revoked_at` TRƯỚC KHI ÁP MIGRATION
NÀY. Endpoint hiện tại là `POST /agent/keys/{key_id}` với `status: active|inactive`
(xem Change Log 2026-08-12) — nó đã set `revoked_at` chứ không DELETE, nên không có
gì phải sửa. Đường admin nền tảng `DELETE /admin/keys/{key_id}` thì có DELETE thật:
kiểm `service.thu_hoi_khoa` xem nó DELETE hay UPDATE. Nếu DELETE ⇒ nó sẽ ném
ForeignKeyViolation cho khoá đã có conversation, và đó là hành vi MONG MUỐN, nhưng
phải trả 409 có thông điệp thay vì 500.

Revision ID: 0945_conversations_agent_key_fk
Revises: 0944_billing_action
"""

from alembic import op

revision = "0945_conversations_agent_key_fk"
down_revision = "0944_billing_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE control.agent_keys "
        "ADD CONSTRAINT agent_keys_tenant_id_uk UNIQUE (tenant_id, id)"
    )
    op.execute(
        "ALTER TABLE tenant_data.conversations "
        "DROP CONSTRAINT IF EXISTS conversations_agent_key_id_fkey"
    )
    op.execute(
        """ALTER TABLE tenant_data.conversations
           ADD CONSTRAINT conversations_agent_key_fkey
           FOREIGN KEY (tenant_id, agent_key_id)
           REFERENCES control.agent_keys (tenant_id, id) ON DELETE RESTRICT"""
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_data.conversations "
        "DROP CONSTRAINT IF EXISTS conversations_agent_key_fkey"
    )
    op.execute(
        """ALTER TABLE tenant_data.conversations
           ADD CONSTRAINT conversations_agent_key_id_fkey
           FOREIGN KEY (agent_key_id) REFERENCES control.agent_keys (id)
           ON DELETE SET NULL"""
    )
    op.execute(
        "ALTER TABLE control.agent_keys DROP CONSTRAINT IF EXISTS agent_keys_tenant_id_uk"
    )
```

- [ ] **Step 4: Kiểm dữ liệu dev trước khi áp**

```bash
uv run psql "$MIGRATOR_URL" -c "SELECT count(*) FROM tenant_data.conversations c JOIN control.agent_keys k ON k.id = c.agent_key_id WHERE k.tenant_id <> c.tenant_id"
```
Expected: `0`. Khác 0 ⇒ **DỪNG**, phải dọn dữ liệu lệch trước, không thì `ALTER TABLE` ném và migration nửa đường.

- [ ] **Step 5: Áp và chạy test**

```bash
make migrate
uv run pytest tests/modules/billing/test_attribution.py -q
```
Expected: PASS 3/3.

- [ ] **Step 6: Round-trip + grep các test khác dùng bảng này**

```bash
grep -rn "agent_keys" tests/ | grep -i "delete" | head
uv run alembic downgrade -1 && uv run alembic upgrade head
```
Bài học từ `0941`: bỏ/siết một constraint thì phải `grep -rn "<tên bảng>" tests/` **TRƯỚC** khi chọn vùng chạy — test dùng `DELETE FROM control.agent_keys` để dọn fixture sẽ đỏ mà grep theo tên module bỏ sót hết.

- [ ] **Step 7: Chạy full suite, so với baseline**

```bash
make check
```
Expected: danh sách đỏ **trùng khít baseline** (`tests/modules/test_heartbeat.py` 2 bài). Bất kỳ dòng đỏ mới nào là hồi quy do Task 10 — sửa hoặc revert, đừng ghi vào "đã biết".

- [ ] **Step 8: Commit**

```bash
git add migrations/versions/0945_conversations_agent_key_fk.py tests/modules/billing/test_attribution.py
git commit -m "feat(billing): 0945 — composite FK + RESTRICT, attribution không sai được ở tầng DB"
```

---

### Task 11: Cập nhật CLAUDE.md + hợp đồng

**Files:**
- Modify: `CLAUDE.md` (Change Log + bảng schema)
- Create: `docs/contracts/usage-billing.md`

- [ ] **Step 1: Viết hợp đồng cho FE**

```markdown
# Hợp đồng Usage & Billing — bàn giao FE

5 endpoint tenant (`billing.read`) + 5 endpoint admin nền tảng
(`X-Platform-Admin-Token`). Bảng trường sinh từ OpenAPI — xem `/docs`.

## Ba điều FE PHẢI làm đúng

1. **Nhóm `agentKeyId: null` KHÔNG được ẩn.** Nhãn "Chưa phân loại (không có khoá)".
   Ẩn nó là làm tổng các dòng lệch `chiPhiTong`, và lệch theo hướng THIẾU.
2. **Không cộng `voiceSec` chéo component.** `vad`/`call`/`stt` đo những quãng audio
   chồng lấn nhau; cộng gộp là tính một giây 3–4 lần. Hiện từng component riêng.
3. **`ghiChuTurn` ở màn chi tiết phiên phải hiện.** `turnIdx` của dòng audio là xấp
   xỉ; người dùng đối chiếu tiền theo từng lượt sẽ thấy lệch và kết luận hệ thống sai.

## Dải cảnh báo trên Overview
`canhBao.thieuGia > 0` là **đang mất doanh thu** — báo đỏ, không phải thông tin nền.
`canhBao.llmKhongChinhXac` là tỷ lệ token đo thiếu; hiển thị nhưng đừng "bù" bằng ước lượng.
```

- [ ] **Step 2: Thêm dòng Change Log vào CLAUDE.md**

Một dòng ở đầu bảng, ngày `2026-08-19`, nêu: module `billing` mới · 3 migration `0943`–`0945` · `portal_api` là thành viên `agent_all` (đo được, và docstring `0942` nói sai về việc portal_api không đọc được `usage_events`) · cổng cách ly nay quét cả schema `billing` · cổng vàng đối chiếu công thức bên agent · `ON DELETE SET NULL` → `RESTRICT` là đổi ngữ nghĩa (xoá khoá đã có usage nay bị chặn).

- [ ] **Step 3: Cập nhật bảng schema trong CLAUDE.md**

Thêm hàng thứ ba vào bảng "Schema Postgres, hai hạng" (nay là **ba** hạng):

| `billing` | sổ ghi usage (`usage_events`, agent INSERT) + bảng giá/định giá (Portal) | `agent_all`: SELECT+INSERT trên `usage_events` dưới policy tenant. **ZERO** trên mọi bảng giá — cấp cho nhóm đó là mở giá cho mọi pod. |

- [ ] **Step 4: Chạy `make check` lần cuối**

Run: `make check`
Expected: đỏ đúng baseline. `ruff format --check` sạch (nhớ: `make lint` là HAI lệnh).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/contracts/usage-billing.md
git commit -m "docs(billing): hợp đồng FE + Change Log"
```

---

## Self-Review

**Spec coverage** — đối chiếu từng mục `THIET-KE-CHOT.md`:

| Mục spec | Task |
|---|---|
| §0 kiểm chứng hai bên cùng số | Task 3 (cổng vàng) |
| §1.1 `wall_ms` là metric | Task 1 (`_DDL`), Task 3 (fixture có dòng `(stt,stream)`) |
| §1.2 `call` có tính tiền | Task 3 (tổng gồm 1.187đ của `call` — 29%) |
| §1.3 STT chọn một cơ sở | Task 1 (index), Task 9 (409 có thông điệp) |
| §1.4 `embed` | Task 1 (`pricing_basis` có dòng embed) — chưa có data để test, đúng phạm vi |
| §2 khác biệt với bản của agent | Task 1 (bảng giá thay biến `P_*`), Task 9 (`purpose` thay cờ) |
| §3 bảy bảng | Task 1 |
| §4 ba bất biến | Task 1 (`numeric(20,10)`), Task 9 (`kich_hoat` chặn lỗ), Task 4 (snapshot) |
| §5 bốn cạnh sắc | Task 8 (48h), Task 5 (`ghi_chu_turn`), Task 7 (`llm_khong_chinh_xac`) |
| §6 bảng giá cần nhập | `pricing-seed.sql` + Task 9 (form sinh từ `pricing_basis`) |
| §7 UI 4 màn | Task 7 (3 màn tenant), Task 9 (màn Pricing) |
| §8 thứ tự làm | Task 1→11 |
| §9 đã chốt | Task 1 (`purpose` seed 4 nhãn `false`), Task 3 (STT theo giây) |
| §10 thiếu VAT | **KHÔNG có task** — chờ bạn chốt, xem "Còn hở" dưới |
| `usage-v1-simple.md` §3 siết FK | Task 10 |
| `price-version-flow.md` §3 luồng 5 bước | Task 9 (①②③④ Step 1–4, ⑤ Step 5) |
| `price-version-flow.md` §4 resolve không đọc status | Task 4 (`test_tinh_lai_ky_cu_khi_version_da_inactive`) |
| `price-version-flow.md` §5 bộ giá đã dùng thì bất biến | Task 1 (`test_gia_da_sinh_ra_tien_thi_bat_bien`) |
| `price-version-flow.md` §4 status chỉ active/inactive | Task 1 (`test_status_chi_hai_gia_tri`) |

**Còn hở, có chủ ý:**
- **VAT chưa làm.** `billing.invoice` chưa có `vat_rate`/`total_gom_vat`. Cần bạn chốt đơn giá đã gồm VAT chưa. Thêm sau là 2 cột `ALTER TABLE`, không đụng `rated_usage`.
- **`invoice`/`invoice_line` dựng bảng nhưng không có endpoint nào.** Giai đoạn 2 theo đúng spec §3.
- **`embed` không có bài test** vì chưa có data. `pricing_basis` đã khai nên `price_coverage_gap` sẽ kêu ngay ngày đầu embed xuất hiện — đó là cơ chế phát hiện, không cần test đoán trước.

**Placeholder scan:** không có "TBD"/"tương tự Task N". Ba chỗ có ⚠️ yêu cầu **đọc file thật trước khi viết** (tên `loi.LoiPortal`, tên dependency quản trị nền tảng, tên trường `migrator_url`) — đó là chỉ dẫn có địa chỉ cụ thể, không phải placeholder.

**Type consistency:** `repo.theo_key` trả cột `agent_key_id`/`label`/`chi_phi` → `DongKeyOut` khớp tên. `chi_phi` là `Decimal` xuyên suốt (không `float`) — tiền không đi qua float. `voice_sec` là `float` (đo lường, không phải tiền). `rate_usage(from, to, tenant)` ba tham số ở mọi lời gọi: Task 3, 4, 8, 9.
