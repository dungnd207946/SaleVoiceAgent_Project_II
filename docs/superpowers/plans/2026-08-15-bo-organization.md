# Bỏ tầng organization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xoá tầng `control.organizations` khỏi cả ba repo, chuyển phân quyền từ hai trục (`users.org_role` + `memberships.role_id`) xuống một trục duy nhất (`memberships.role_id`), và mở đường tự đăng ký → tự tạo workspace → người tạo là "Quản trị".

**Architecture:** Hai migration nối tiếp (A: gỡ `roles` khỏi org; B: xoá org khỏi `tenants`/`users`/`audit_log` rồi `DROP TABLE organizations`). Bảng `roles`/`role_actions`/`actions` cùng CRUD **giữ nguyên**, chỉ mất cột `org_id`. Hai khối endpoint mất chủ (`/users*`, ghi `/roles*`) đóng bằng cờ cấu hình, không xoá. Phiên không workspace trở thành trạng thái hợp lệ để người vừa đăng ký đi tiếp được.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · Alembic · Pydantic v2 · pytest/testcontainers · React + TanStack Router + React Query + MSW/vitest (FE) · Python/pytest (agent)

**Spec:** `odyssey-portal-backend/docs/superpowers/specs/2026-08-15-bo-organization-design.md`

## Global Constraints

- **Ba repo tách rời, ba git riêng.** `odyssey-portal-backend` · `odyssey-portal-frontend` · `odyssey-agent`. Mỗi task commit trong repo của nó.
- **Luật 4 của backend:** mọi endpoint phải khai action qua `require(action)`, route công khai dùng `require(None, ly_do="...")`. Cổng: `tests/unit/test_moi_route_khai_action.py`.
- **Luật 3:** module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. Cổng: `tests/test_module_boundaries.py`.
- **Luật 1:** mọi truy vấn `tenant_data` đi qua `tenant_conn()` trong một giao dịch. Kế hoạch này **không chạm `tenant_data`** — chỉ `control`.
- **Alembic một head.** A và B nối tiếp; B lấy A làm `down_revision`. Cổng: `tests/unit/test_alembic_mot_head.py`. Lấy head hiện tại bằng `alembic heads`, **không đoán**.
- **`revision` id khác tên file** theo quy ước repo — luôn mở file cha ra đọc.
- **Sửa migration đã áp lên DB dev** ⇒ phải `alembic downgrade -1 && alembic upgrade head`.
- **4 vai trò cố định, đúng tên có dấu:** `Quản trị` (13 action) · `CSKH` (8) · `Biên tập` (7) · `Người xem` (5).
- **13 action** khai ở `src/portal/core/auth/actions.py` — **không đổi** trong kế hoạch này, nên **không cần `make contracts`**.
- **`make test-isolation` đang có sẵn 1 dòng đỏ** (`modules/realestate/router.py:760`, báo nhầm docstring). Không phải do kế hoạch này gây ra; đừng "sửa" bằng allowlist.
- **Chạy test:** backend `make check`; một file: `uv run pytest tests/... -v`. Frontend: `npm test`. Agent: `uv run pytest tests/unit/tenant -v`.

---

## Phase 1 — Backend (`odyssey-portal-backend`)

### Task 1: Migration A — gỡ `roles` khỏi organization

**Files:**
- Create: `migrations/versions/<rev>_roles_thoat_org.py`
- Test: `tests/integration/test_migration_bo_org_a.py`

**Interfaces:**
- Consumes: schema hiện tại ở head.
- Produces: `control.roles(id, name, description, created_at)` với `UNIQUE (name)`; `memberships.role_id → roles(id)` FK đơn; `invites.user_id → users(id)` FK đơn; không còn trigger `organizations_seed_vai_tro` và hàm `control.seed_vai_tro_mau(text)`.

- [ ] **Step 1: Lấy head hiện tại**

```bash
cd odyssey-portal-backend && uv run alembic heads
```

Ghi lại giá trị (ví dụ `0921_bang_agent_feedback`) — nó là `down_revision` của A. Đặt tên file `migrations/versions/0105_roles_thoat_org.py` và `revision = "0105_roles_thoat_org"`.

- [ ] **Step 2: Viết test thất bại**

```python
# tests/integration/test_migration_bo_org_a.py
"""Migration A: roles thoát org. Chạy trên DB thật (testcontainers)."""

import pytest


@pytest.mark.asyncio
async def test_roles_khong_con_cot_org_id(pool):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'roles' AND column_name = 'org_id'"""
    )
    assert n == 0


@pytest.mark.asyncio
async def test_roles_unique_theo_name(pool):
    ten = await pool.fetchval(
        """SELECT c.conname FROM pg_constraint c
             JOIN pg_class t ON t.oid = c.conrelid
             JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'control' AND t.relname = 'roles' AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (name)'"""
    )
    assert ten is not None


@pytest.mark.asyncio
async def test_bon_vai_tro_mau_con_dung_mot_ban(pool):
    hang = await pool.fetch("SELECT name, count(*) AS n FROM control.roles GROUP BY name")
    assert {r["name"] for r in hang} == {"Quản trị", "CSKH", "Biên tập", "Người xem"}
    assert all(r["n"] == 1 for r in hang), "dedup chưa chạy: còn vai trò trùng tên"


@pytest.mark.asyncio
async def test_memberships_fk_don_cot(pool):
    dinh_nghia = await pool.fetchval(
        """SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c
             JOIN pg_class t ON t.oid = c.conrelid
             JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'control' AND t.relname = 'memberships'
              AND c.contype = 'f' AND pg_get_constraintdef(c.oid) LIKE '%roles%'"""
    )
    assert dinh_nghia == "FOREIGN KEY (role_id) REFERENCES control.roles(id)"


@pytest.mark.asyncio
async def test_trigger_seed_theo_org_da_bien_mat(pool):
    assert await pool.fetchval("SELECT to_regproc('control.seed_vai_tro_mau(text)')") is None


@pytest.mark.asyncio
async def test_moi_membership_van_tro_toi_mot_vai_tro_that(pool):
    mo_coi = await pool.fetchval(
        """SELECT count(*) FROM control.memberships m
            WHERE NOT EXISTS (SELECT 1 FROM control.roles r WHERE r.id = m.role_id)"""
    )
    assert mo_coi == 0
```

- [ ] **Step 3: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/integration/test_migration_bo_org_a.py -v`
Expected: FAIL — `roles` còn cột `org_id`, chưa có `UNIQUE (name)`.

- [ ] **Step 4: Viết migration A**

```python
# migrations/versions/0105_roles_thoat_org.py
"""control.roles thoát khỏi organization — bước A của việc bỏ tầng tổ chức

Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3, §9

VÌ SAO DEDUP LÀ BẮT BUỘC, KHÔNG PHẢI PHÒNG THỦ: production chỉ có org `noble`
(4 hàng roles), nhưng `scripts/dev_seed.py` dựng HAI tổ chức — trên mọi máy dev
là 8 hàng, 4 cặp trùng tên. Bỏ `org_id` mà không dedup thì `UNIQUE (name)` nổ
ngay ở `make migrate`.

DEDUP GIỮ MA TRẬN ACTION CỦA HÀNG ĐƯỢC GIỮ VÀ VỨT CỦA HÀNG BỊ LOẠI. Hai org có
thể đã sửa vai trò cùng tên theo hai hướng khác nhau; ở dev cả hai là bản seed y
hệt nên không mất gì. RAISE NOTICE số hàng đã gộp để việc này hiện ra trong log,
không đi im lặng.

⚠ DOWNGRADE KHÔNG PHẢI ĐƯỜNG LÙI CHO PRODUCTION: hàng `roles` bị dedup không
dựng lại được. `downgrade()` ở đây chỉ dùng được ngay sau `upgrade` trên máy dev.
"""

from alembic import op

revision = "0105_roles_thoat_org"
down_revision = "<HEAD ĐỌC ĐƯỢC Ở STEP 1>"
branch_labels = None
depends_on = None

_ORG_MAC_DINH = "noble"


def upgrade() -> None:
    # --- ① Dedup roles theo name ------------------------------------------
    # created_at đồng hạng (cùng một lượt seed, bằng nhau tới micro giây) thì
    # phân giải bằng id — nếu không, `DISTINCT ON` chọn tuỳ hứng và hai lần chạy
    # trên hai máy cho ra hai kết quả khác nhau.
    op.execute(
        """
        CREATE TEMP TABLE _giu AS
             SELECT DISTINCT ON (name) name, id
               FROM control.roles
              ORDER BY name, created_at, id
        """
    )
    op.execute(
        """
        UPDATE control.memberships m
           SET role_id = g.id
          FROM control.roles r
          JOIN _giu g ON g.name = r.name
         WHERE m.role_id = r.id AND m.role_id <> g.id
        """
    )
    op.execute(
        """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n
            FROM control.roles r
           WHERE r.id NOT IN (SELECT id FROM _giu);
          IF n > 0 THEN
            RAISE NOTICE '0105: gộp % hàng roles trùng tên (dedup theo name)', n;
          END IF;
        END $$
        """
    )
    # role_actions rụng theo ON DELETE CASCADE của FK role_actions.role_id.
    op.execute("DELETE FROM control.roles WHERE id NOT IN (SELECT id FROM _giu)")
    op.execute("DROP TABLE _giu")

    # --- ② FK ghép -> FK đơn ----------------------------------------------
    # ⚠ `memberships` có BA FK ghép, không phải một (đo bằng pg_constraint trên DB
    # thật 2026-08-15). Bỏ sót hai cái kia thì `DROP COLUMN org_id` ở migration B
    # nổ, và nổ ở một file khác file gây ra lỗi.
    #
    # `memberships_role_cung_to_chuc_fkey` là ON DELETE **RESTRICT** (không phải
    # CASCADE): xoá một vai trò đang có người giữ bị chặn ở tầng DB. FK thay thế
    # PHẢI giữ RESTRICT — đổi sang mặc định NO ACTION thì hành vi gần giống nhưng
    # `quan_tri_vai_tro.xoa()` đang dựa vào việc DB chặn làm lưới thứ hai sau
    # `dem_nguoi_dung_vai_tro()`.
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_role_cung_to_chuc_fkey")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_role_id_fkey
             FOREIGN KEY (role_id) REFERENCES control.roles (id) ON DELETE RESTRICT"""
    )
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_tenant_fkey")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_tenant_id_fkey
             FOREIGN KEY (tenant_id) REFERENCES control.tenants (id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_org_user_fkey")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_user_id_fkey
             FOREIGN KEY (user_id) REFERENCES control.users (id) ON DELETE CASCADE"""
    )

    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_org_user_fkey")
    op.execute(
        """ALTER TABLE control.invites
             ADD CONSTRAINT invites_user_id_fkey
             FOREIGN KEY (user_id) REFERENCES control.users (id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.invites DROP COLUMN org_id")

    # --- ③ roles bỏ org_id -------------------------------------------------
    op.execute("DROP INDEX control.roles_org_idx")
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_org_id_name_key")
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_org_id_id_key")
    op.execute("ALTER TABLE control.roles DROP COLUMN org_id")  # kéo theo roles_org_id_fkey
    op.execute("ALTER TABLE control.roles ADD CONSTRAINT roles_name_key UNIQUE (name)")

    # --- ④ Trigger seed theo org -------------------------------------------
    # Bốn vai trò đã tồn tại (backfill của 0104 + dedup ở ①); không seed lại.
    op.execute("DROP TRIGGER organizations_seed_vai_tro ON control.organizations")
    op.execute("DROP FUNCTION control.seed_vai_tro_mau(text)")


def downgrade() -> None:
    op.execute("ALTER TABLE control.roles DROP CONSTRAINT roles_name_key")
    op.execute(f"ALTER TABLE control.roles ADD COLUMN org_id text DEFAULT '{_ORG_MAC_DINH}'")
    op.execute("ALTER TABLE control.roles ALTER COLUMN org_id SET NOT NULL")
    op.execute("ALTER TABLE control.roles ALTER COLUMN org_id DROP DEFAULT")
    op.execute(
        """ALTER TABLE control.roles ADD CONSTRAINT roles_org_id_name_key UNIQUE (org_id, name)"""
    )
    op.execute("""ALTER TABLE control.roles ADD CONSTRAINT roles_org_id_id_key UNIQUE (org_id, id)""")
    op.execute("CREATE INDEX roles_org_idx ON control.roles (org_id)")

    op.execute("ALTER TABLE control.invites DROP CONSTRAINT invites_user_id_fkey")
    op.execute(f"ALTER TABLE control.invites ADD COLUMN org_id text NOT NULL DEFAULT '{_ORG_MAC_DINH}'")
    op.execute("ALTER TABLE control.invites ALTER COLUMN org_id DROP DEFAULT")
    op.execute(
        """ALTER TABLE control.invites
             ADD CONSTRAINT invites_org_user_fkey
             FOREIGN KEY (org_id, user_id) REFERENCES control.users (org_id, id) ON DELETE CASCADE"""
    )

    for cu, moi, dich, hanh_dong in (
        ("memberships_role_id_fkey", "memberships_role_cung_to_chuc_fkey", "roles (org_id, id)", "RESTRICT"),
        ("memberships_tenant_id_fkey", "memberships_org_tenant_fkey", "tenants (org_id, id)", "CASCADE"),
        ("memberships_user_id_fkey", "memberships_org_user_fkey", "users (org_id, id)", "CASCADE"),
    ):
        cot = "role_id" if "role" in cu else ("tenant_id" if "tenant" in cu else "user_id")
        op.execute(f"ALTER TABLE control.memberships DROP CONSTRAINT {cu}")
        op.execute(
            f"""ALTER TABLE control.memberships ADD CONSTRAINT {moi}
                  FOREIGN KEY (org_id, {cot}) REFERENCES control.{dich}
                  ON DELETE {hanh_dong}"""
        )
    # Hàm + trigger seed KHÔNG dựng lại: thân hàm sinh từ dict `_MAU` của 0104 và
    # sao chép nó vào đây là tạo bản thứ hai của ma trận PQ_01 §3.1. Downgrade
    # chỉ để quay lại ngay trên máy dev, nơi 4 vai trò đã có sẵn.
```

- [ ] **Step 5: Áp migration và chạy test**

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_migration_bo_org_a.py -v
```
Expected: PASS (6 test).

- [ ] **Step 6: Kiểm một head**

Run: `uv run pytest tests/unit/test_alembic_mot_head.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/0105_roles_thoat_org.py tests/integration/test_migration_bo_org_a.py
git commit -m "feat(db): roles thoát khỏi organization (migration A)"
```

---

### Task 2: Migration B — xoá `control.organizations`

**Files:**
- Create: `migrations/versions/0106_bo_organizations.py`
- Test: `tests/integration/test_migration_bo_org_b.py`

**Interfaces:**
- Consumes: Task 1 (`revision = "0105_roles_thoat_org"` làm `down_revision`).
- Produces: `tenants(id, name, created_by, lifecycle, created_at, …)` với `UNIQUE (created_by, lower(btrim(name)))`; `users` không còn `org_id`/`org_role`; `audit_log` không còn `org_id`; bảng `control.organizations` không tồn tại.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/integration/test_migration_bo_org_b.py
import pytest


@pytest.mark.asyncio
async def test_bang_organizations_da_bien_mat(pool):
    assert await pool.fetchval("SELECT to_regclass('control.organizations')") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bang", "cot"),
    [("tenants", "org_id"), ("users", "org_id"), ("users", "org_role"), ("audit_log", "org_id")],
)
async def test_cot_org_da_bien_mat(pool, bang, cot):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = $1 AND column_name = $2""",
        bang,
        cot,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_tenants_co_created_by_not_null(pool):
    r = await pool.fetchrow(
        """SELECT is_nullable FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'tenants' AND column_name = 'created_by'"""
    )
    assert r is not None and r["is_nullable"] == "NO"


@pytest.mark.asyncio
async def test_moi_tenant_deu_co_nguoi_tao_that(pool):
    mo_coi = await pool.fetchval(
        """SELECT count(*) FROM control.tenants t
            WHERE NOT EXISTS (SELECT 1 FROM control.users u WHERE u.id = t.created_by)"""
    )
    assert mo_coi == 0


@pytest.mark.asyncio
async def test_trung_ten_trong_cung_nguoi_tao_bi_chan(pool):
    uid = await pool.fetchval("SELECT id FROM control.users LIMIT 1")
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_a', 'Kiểm Tra', $1)", uid
    )
    with pytest.raises(Exception, match="duplicate key|unique"):
        await pool.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_b', ' kiểm tra ', $1)", uid
        )
    await pool.execute("DELETE FROM control.tenants WHERE id = 'kt_a'")


@pytest.mark.asyncio
async def test_hai_nguoi_khac_nhau_dat_trung_ten_van_duoc(pool):
    hai = await pool.fetch("SELECT id FROM control.users LIMIT 2")
    if len(hai) < 2:
        pytest.skip("cần ít nhất 2 user")
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_c', 'Trùng Tên', $1)",
        hai[0]["id"],
    )
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_d', 'Trùng Tên', $1)",
        hai[1]["id"],
    )
    await pool.execute("DELETE FROM control.tenants WHERE id IN ('kt_c', 'kt_d')")
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/integration/test_migration_bo_org_b.py -v`
Expected: FAIL — bảng `organizations` còn đó.

- [ ] **Step 3: Viết migration B**

```python
# migrations/versions/0106_bo_organizations.py
"""Xoá control.organizations — bước B của việc bỏ tầng tổ chức

Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3, §9

`created_by` VỪA THAY `org_id` LÀM PHẠM VI CHO RÀNG BUỘC TÊN, VỪA TRẢ LỜI "AI MỞ
WORKSPACE NÀY" — câu mà `org_id` trước đây trả lời mơ hồ. Tên duy nhất theo NGƯỜI
TẠO chứ không toàn cục: sau khi mở tự đăng ký, hai người lạ đặt tên "Test" là
chuyện bình thường, và duy nhất toàn cục sẽ 409 vào mặt người thứ hai.

BACKFILL NỔ NẾU KHÔNG CÓ OWNER: dữ liệu ở trạng thái đó không có câu trả lời
đúng, và im lặng gán bừa là tạo ra một chủ sở hữu sai mà không ai phát hiện.

⚠ DOWNGRADE KHÔNG PHẢI ĐƯỜNG LÙI CHO PRODUCTION: nó gom MỌI workspace về một tổ
chức `noble`, và `UNIQUE (org_id, lower(name))` cũ có thể nổ vì hai người đã đặt
trùng tên hợp lệ sau khi upgrade. Chỉ dùng được ngay sau `upgrade` trên máy dev.
"""

from alembic import op

revision = "0106_bo_organizations"
down_revision = "0105_roles_thoat_org"
branch_labels = None
depends_on = None

_ORG_MAC_DINH = "noble"


def upgrade() -> None:
    # --- ① tenants.created_by ---------------------------------------------
    op.execute("ALTER TABLE control.tenants ADD COLUMN created_by text REFERENCES control.users(id)")
    op.execute(
        """
        UPDATE control.tenants t
           SET created_by = (
                 SELECT u.id FROM control.users u
                  WHERE u.org_id = t.org_id AND u.org_role = 'owner'
                  ORDER BY u.created_at, u.id
                  LIMIT 1)
        """
    )
    op.execute(
        """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n FROM control.tenants WHERE created_by IS NULL;
          IF n > 0 THEN
            RAISE EXCEPTION '0106: % workspace không suy được người tạo (org không có owner nào). '
                            'Gán tay control.tenants.created_by rồi chạy lại.', n;
          END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE control.tenants ALTER COLUMN created_by SET NOT NULL")
    op.execute(
        """CREATE UNIQUE INDEX tenants_nguoi_tao_ten_key
             ON control.tenants (created_by, lower(btrim(name)))"""
    )

    # --- ② Gỡ org khỏi ba bảng --------------------------------------------
    op.execute("DROP INDEX control.tenants_org_idx")
    op.execute("ALTER TABLE control.tenants DROP CONSTRAINT tenants_org_id_key")
    op.execute("ALTER TABLE control.tenants DROP COLUMN org_id")

    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_org_id_key")
    op.execute("ALTER TABLE control.users DROP COLUMN org_id")
    op.execute("ALTER TABLE control.users DROP COLUMN org_role")  # kéo theo users_org_role_check

    # ⚠ `audit_log_co_pham_vi_check` = CHECK (tenant_id IS NOT NULL OR org_id IS
    # NOT NULL) — "mỗi dòng nhật ký phải có ít nhất một phạm vi". Bỏ `org_id` mà
    # giữ CHECK thì nó rút thành `tenant_id IS NOT NULL`, và MỌI dòng cũ có phạm
    # vi tổ chức (tenant_id NULL, org_id có) lập tức vi phạm.
    #
    # Chọn DROP CHECK chứ không backfill `tenant_id`: những dòng đó ghi lại hành
    # động cấp hệ thống (tạo user, sửa vai trò) vốn KHÔNG thuộc workspace nào, và
    # gán bừa chúng vào một workspace là làm hỏng nhật ký để chiều một ràng buộc.
    # `tenant_id IS NULL` từ nay đọc là "hành động không thuộc workspace nào".
    op.execute("ALTER TABLE control.audit_log DROP CONSTRAINT audit_log_co_pham_vi_check")
    op.execute("ALTER TABLE control.audit_log DROP COLUMN org_id")

    op.execute("ALTER TABLE control.memberships DROP COLUMN org_id")

    # --- ③ ------------------------------------------------------------------
    op.execute("DROP TABLE control.organizations")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.organizations (
            id         text PRIMARY KEY,
            name       text NOT NULL,
            lifecycle  text NOT NULL DEFAULT 'active'
                       CONSTRAINT organizations_lifecycle_check
                       CHECK (lifecycle IN ('active', 'suspended', 'closed')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"INSERT INTO control.organizations (id, name) VALUES ('{_ORG_MAC_DINH}', 'NobleX')")

    for bang in ("tenants", "users", "memberships"):
        op.execute(
            f"""ALTER TABLE control.{bang} ADD COLUMN org_id text
                  DEFAULT '{_ORG_MAC_DINH}'
                  REFERENCES control.organizations(id) ON DELETE CASCADE"""
        )
        op.execute(f"ALTER TABLE control.{bang} ALTER COLUMN org_id SET NOT NULL")
        op.execute(f"ALTER TABLE control.{bang} ALTER COLUMN org_id DROP DEFAULT")

    op.execute(
        f"""ALTER TABLE control.audit_log ADD COLUMN org_id text
              DEFAULT '{_ORG_MAC_DINH}' REFERENCES control.organizations(id) ON DELETE CASCADE"""
    )
    op.execute("ALTER TABLE control.audit_log ALTER COLUMN org_id DROP DEFAULT")

    op.execute("ALTER TABLE control.tenants ADD CONSTRAINT tenants_org_id_key UNIQUE (org_id, id)")
    op.execute("CREATE INDEX tenants_org_idx ON control.tenants (org_id)")
    op.execute("ALTER TABLE control.users ADD CONSTRAINT users_org_id_key UNIQUE (org_id, id)")
    op.execute(
        """ALTER TABLE control.users ADD COLUMN org_role text NOT NULL DEFAULT 'member'
             CONSTRAINT users_org_role_check CHECK (org_role IN ('owner', 'member'))"""
    )
    op.execute(
        """ALTER TABLE control.audit_log ADD CONSTRAINT audit_log_co_pham_vi_check
             CHECK (tenant_id IS NOT NULL OR org_id IS NOT NULL)"""
    )

    op.execute("DROP INDEX control.tenants_nguoi_tao_ten_key")
    op.execute("ALTER TABLE control.tenants DROP COLUMN created_by")
```

- [ ] **Step 4: Áp migration và chạy test**

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_migration_bo_org_b.py -v
```
Expected: PASS (8 test, kể cả parametrize).

- [ ] **Step 5: Kiểm downgrade đi về được**

```bash
uv run alembic downgrade -2 && uv run alembic upgrade head
```
Expected: cả hai lệnh thoát 0.

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/0106_bo_organizations.py tests/integration/test_migration_bo_org_b.py
git commit -m "feat(db): xoá control.organizations, thêm tenants.created_by (migration B)"
```

---

### Task 3: `doc_quyen()` bỏ nhánh owner

**Files:**
- Modify: `src/portal/core/auth/repo.py`
- Test: `tests/api/test_core_auth_repo.py`

**Interfaces:**
- Consumes: schema sau Task 2.
- Produces: `HangQuyen(lifecycle: str, role_name: str | None, actions: frozenset[str], co_membership: bool)` — **bỏ field `org_role`**. `doc_quyen(conn, user_id, tenant_id) -> HangQuyen | None` giữ nguyên chữ ký.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/api/test_core_auth_repo.py  (thêm vào cuối)
@pytest.mark.asyncio
async def test_khong_co_membership_thi_khong_co_action_nao(pool, user_khong_membership, tenant_bat_ky):
    """Trước đây owner nhận đủ 13 action ở mọi workspace cùng org dù không có
    hàng memberships. Nhánh đó đã bỏ — giờ không membership là không quyền."""
    q = await repo.doc_quyen(pool, user_khong_membership, tenant_bat_ky)
    assert q is not None
    assert q.actions == frozenset()
    assert q.co_membership is False
    assert q.role_name is None


@pytest.mark.asyncio
async def test_hang_quyen_khong_con_org_role(pool, user_co_membership, tenant_cua_ho):
    q = await repo.doc_quyen(pool, user_co_membership, tenant_cua_ho)
    assert not hasattr(q, "org_role")
```

Hai fixture cần thêm vào `tests/api/conftest.py` (hoặc file test, nếu repo đặt fixture cục bộ):

```python
@pytest.fixture
async def user_khong_membership(pool):
    await pool.execute(
        """INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                VALUES ('u_le_loi', 'leloi@x.vn', 'Lê Lợi', 'x', 'active')
             ON CONFLICT (id) DO NOTHING"""
    )
    yield "u_le_loi"
    await pool.execute("DELETE FROM control.users WHERE id = 'u_le_loi'")
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/api/test_core_auth_repo.py -v`
Expected: FAIL — `HangQuyen` còn `org_role`, và nhánh owner vẫn trả `ALL_ACTIONS`.

- [ ] **Step 3: Sửa `doc_quyen`**

```python
# src/portal/core/auth/repo.py
@dataclass(frozen=True, slots=True)
class HangQuyen:
    lifecycle: str
    """'active' | 'suspended'."""
    role_name: str | None
    """Tên vai trò trong workspace đang xét. None = không có membership."""
    actions: frozenset[str]
    co_membership: bool


async def doc_quyen(conn: asyncpg.Connection, user_id: str, tenant_id: str) -> HangQuyen | None:
    """Lifecycle + vai trò + tập action hiệu lực, MỘT truy vấn.

    KHÔNG CÒN NHÁNH OWNER. Trước 2026-08-15, `org_role='owner'` + tenant cùng tổ
    chức ⇒ đủ 13 action ở MỌI workspace, không cần hàng memberships. Tầng tổ chức
    đã bị bỏ (spec 2026-08-15-bo-organization-design §4), nên quyền giờ CHỈ đến từ
    `memberships`: không có hàng thì không có action nào. Đó cũng là lý do
    `workspace.service.tao()` buộc phải ghi membership 'Quản trị' cho người tạo.

    ⚠ VỊ TỪ `expires_at` NẰM TRONG `ON`, KHÔNG PHẢI `WHERE`. Ở `WHERE` nó biến
    LEFT JOIN thành INNER JOIN âm thầm: user không có membership sẽ mất luôn hàng
    và hàm trả None — không phân biệt được với "user không tồn tại".

    `expires_at IS NULL OR expires_at > now()` là chỗ BR-Q08 được cài: vé hỗ trợ
    của NobleX tự hết hiệu lực, không ai phải nhớ thu hồi.
    """
    r = await conn.fetchrow(
        """SELECT u.lifecycle,
                  r.name AS role_name,
                  bool_or(m.user_id IS NOT NULL) AS co_membership,
                  coalesce(
                    array_agg(ra.action_code) FILTER (WHERE ra.action_code IS NOT NULL),
                    '{}'
                  ) AS actions
             FROM control.users u
             LEFT JOIN control.memberships m
                    ON m.user_id = u.id
                   AND m.tenant_id = $2
                   AND (m.expires_at IS NULL OR m.expires_at > now())
             LEFT JOIN control.roles r         ON r.id = m.role_id
             LEFT JOIN control.role_actions ra ON ra.role_id = m.role_id
            WHERE u.id = $1
            GROUP BY u.lifecycle, r.name""",
        user_id,
        tenant_id,
    )
    if r is None:
        return None
    return HangQuyen(r["lifecycle"], r["role_name"], frozenset(r["actions"]), r["co_membership"])
```

Xoá import `ALL_ACTIONS` nếu không còn ai dùng trong file.

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/api/test_core_auth_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/portal/core/auth/repo.py tests/api/test_core_auth_repo.py tests/api/conftest.py
git commit -m "feat(auth): doc_quyen bỏ nhánh owner — quyền chỉ đến từ memberships"
```

---

### Task 4: `require()` chịu được phiên không workspace + dọn comment lỗi thời

**Files:**
- Modify: `src/portal/core/auth/require.py`
- Modify: `src/portal/core/auth/session.py`
- Modify: `src/portal/modules/auth/router.py:191-193` (comment)
- Modify: `src/portal/modules/auth/quan_tri_user.py:10-17` (comment)
- Test: `tests/modules/auth/test_require_khong_workspace.py`

**Interfaces:**
- Consumes: Task 3 (`HangQuyen` không còn `org_role`).
- Produces: `ss.BanGhiPhien(user_id: str, tenant_id: str | None)`; `ss.tao(r, *, user_id: str, tenant_id: str | None) -> str`. `require(action)` trả 403 `thieu_quyen` khi phiên chưa có workspace, 401 khi user bị đình chỉ.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/auth/test_require_khong_workspace.py
"""Phiên không workspace là trạng thái HỢP LỆ sau khi mở tự đăng ký.

Trước 2026-08-15 nó là 409 NO_WORKSPACE — đúng khi user chỉ ra đời qua lời mời
(được mời VÀO một workspace). Với tự đăng ký, người vừa đăng ký có 0 workspace,
nên 409 là ngõ cụt: không có đường nào tới màn tạo workspace đầu tiên.
"""

import pytest


@pytest.mark.asyncio
async def test_phien_khong_workspace_goi_endpoint_co_action_thi_403(app_client, user_moi_dang_ky):
    r = await app_client.get("/api/v1/members")
    assert r.status_code == 403
    assert r.json()["code"] == "THIEU_QUYEN"


@pytest.mark.asyncio
async def test_phien_khong_workspace_goi_me_thi_200_va_rong(app_client, user_moi_dang_ky):
    r = await app_client.get("/api/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["workspaces"] == []
    assert body["currentWorkspaceId"] is None
    assert body["actions"] == []


@pytest.mark.asyncio
async def test_user_dinh_chi_khong_workspace_bi_day_ve_login(app_client, user_dinh_chi_khong_ws):
    r = await app_client.get("/api/v1/members")
    assert r.status_code == 401, "đình chỉ là chuyện danh tính — phải 401, không phải 403"
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_require_khong_workspace.py -v`
Expected: FAIL — `BanGhiPhien.tenant_id` không nhận `None`.

- [ ] **Step 3: Nới `session.py`**

```python
# src/portal/core/auth/session.py
@dataclass(frozen=True, slots=True)
class BanGhiPhien:
    user_id: str
    tenant_id: str | None
    """None = user chưa thuộc workspace nào (vừa tự đăng ký).

    Trạng thái HỢP LỆ từ 2026-08-15 (spec bo-organization §5.0). Trước đó mọi user
    đều ra đời qua lời mời VÀO một workspace, nên None là không thể xảy ra.
    """


async def tao(r: Redis, *, user_id: str, tenant_id: str | None) -> str:
    ...  # thân hàm không đổi; json.dumps xử lý None thành null
```

- [ ] **Step 4: Sửa `require()`**

```python
# src/portal/core/auth/require.py — trong thân `_kiem`
            sid = request.cookies.get(ss.TEN_COOKIE, "")
            ban_ghi = await ss.doc(r, sid)
            if ban_ghi is None:
                raise loi.khong_co_phien()

            async with pool.acquire() as conn, conn.transaction():
                if ban_ghi.tenant_id is None:
                    # Phiên chưa có workspace (vừa tự đăng ký). Không có gì để tra
                    # ma trận, nhưng VẪN phải kiểm lifecycle: một tài khoản bị đình
                    # chỉ mà chưa có workspace vẫn phải bị đẩy về /login, không phải
                    # nhận 403 rồi ngồi nhìn một màn "không đủ quyền".
                    lc = await conn.fetchval(
                        "SELECT lifecycle FROM control.users WHERE id = $1", ban_ghi.user_id
                    )
                    if lc != "active":
                        await ss.xoa(r, sid)
                        raise loi.khong_co_phien()
                    raise loi.thieu_quyen(action, None)

                q = await repo.doc_quyen(conn, ban_ghi.user_id, ban_ghi.tenant_id)

                if q is None or q.lifecycle != "active":
                    await ss.xoa(r, sid)
                    raise loi.khong_co_phien()

            if action not in q.actions:
                raise loi.thieu_quyen(action, q.role_name)

            return Principal(
                user_id=ban_ghi.user_id,
                tenant_id=ban_ghi.tenant_id,
                role=q.role_name,
                actions=q.actions,
            )
```

`Principal.role` bỏ giá trị rơi `"Chủ tổ chức"` — nó chỉ tồn tại cho nhánh owner đã xoá ở Task 3. Đổi kiểu trong `src/portal/core/auth/principal.py` thành `role: str | None`.

- [ ] **Step 5: Dọn ba comment lỗi thời**

`src/portal/core/auth/require.py` — docstring đầu file, thay đoạn "Ở M2a thân hàm chỉ kiểm... M2b đổi ĐÚNG một chỗ" bằng:

```python
"""require(action) — CỔNG QUYỀN DUY NHẤT.

Ma trận vai trò ĐÃ BẬT: thân hàm tra `doc_quyen()` mỗi request và so `action` với
tập action hiệu lực. Ba comment cũ trong repo (file này, modules/auth/router.py,
modules/auth/quan_tri_user.py) từng nói "M2a chỉ kiểm thành viên, M2b sẽ bật ma
trận sau" — đã lỗi thời và đã gỡ 2026-08-15.

VÌ SAO ĐỌC MEMBERSHIP MỖI REQUEST (PQ_01 §BR-Q04 · YC03): CMS cũ nhét vai trò vào
phiếu đăng nhập hạn 15 phút, nên "sa thải một người xong, 15 phút nữa họ vẫn sửa
được dữ liệu". Ràng buộc cách ly đã buộc mọi request nằm trong một giao dịch, nên
đọc thêm một hàng đi cùng chuyến.
"""
```

`src/portal/modules/auth/router.py` — xoá khối comment ở dòng 191-193 và 203-205 (khối "CỬA THẬT là `org_role = 'owner'`"), thay bằng một dòng:

```python
# Cổng thật là `require(ACTIONS.WORKSPACE_ADMIN)`. Không còn cửa thứ hai:
# `org_role` đã bị bỏ 2026-08-15 (spec bo-organization §2).
```

`src/portal/modules/auth/quan_tri_user.py` — xoá khối docstring dòng 10-17 nói về `org_role = 'owner'`, thay bằng:

```python
"""Quản trị user toàn hệ thống.

⚠ KHỐI NÀY MẤT CHỦ SAU KHI BỎ `org_role` (2026-08-15). Nó được giữ nguyên nhưng
ĐÓNG bằng cờ `USERS_ADMIN_ENABLED` (mặc định False) — xem `_cong_users_admin()`.
Bật lại cần một mô hình admin hệ thống mà hiện chưa có.
"""
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/auth/test_require_khong_workspace.py tests/api -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/portal/core/auth/ src/portal/modules/auth/router.py src/portal/modules/auth/quan_tri_user.py tests/modules/auth/test_require_khong_workspace.py
git commit -m "feat(auth): phiên không workspace là hợp lệ; dọn comment M2a lỗi thời"
```

---

### Task 5: `SessionOut` bỏ `organization`/`orgRole`, `currentWorkspaceId` nhận null

**Files:**
- Modify: `src/portal/modules/auth/contracts.py`
- Modify: `src/portal/modules/auth/service.py`
- Modify: `src/portal/modules/auth/repo.py` (xoá `doc_to_chuc`, `HangUser.org_id`/`org_role`)
- Modify: `src/portal/modules/auth/fake.py`
- Test: `tests/modules/auth/test_login.py`, `tests/modules/auth/test_schema.py`

**Interfaces:**
- Consumes: Task 4 (`BanGhiPhien.tenant_id: str | None`).
- Produces: `SessionOut(user, workspaces: list[WorkspaceOut], currentWorkspaceId: str | None, actions: list[str])`. `OrganizationOut` bị xoá khỏi module. `service._dung_session_out(u, ws, tenant_id, actions)` — bỏ tham số `tc`.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/auth/test_login.py  (thêm)
@pytest.mark.asyncio
async def test_session_out_khong_con_truong_to_chuc(app_client, tai_khoan_that):
    r = await app_client.post("/api/v1/auth/login", json=tai_khoan_that)
    assert r.status_code == 200
    body = r.json()
    assert "organization" not in body
    assert "orgRole" not in body
    assert set(body) == {"user", "workspaces", "currentWorkspaceId", "actions"}
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_login.py -v`
Expected: FAIL — body còn `organization`.

- [ ] **Step 3: Sửa contracts**

```python
# src/portal/modules/auth/contracts.py
# XOÁ class OrganizationOut (dòng 76-83) và mọi import của nó.
# XOÁ `OrgRole = Literal["owner", "member"]` (dòng 16) và trường `orgRole` ở
# TaoUserIn/SuaUserIn (dòng 242, 257) cùng validator dùng nó.


class SessionOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]
    currentWorkspaceId: str | None
    """None = user chưa thuộc workspace nào (vừa tự đăng ký).

    FE dùng đúng điều kiện này để đưa tới màn "Tạo workspace đầu tiên" thay vì
    dashboard rỗng. Xem spec bo-organization §5.0/§5.4.
    """
    actions: list[str]
    """Quyền của user TRONG workspace hiện tại. Rỗng khi chưa có workspace.

    Phải khớp CHÍNH XÁC cái `require()` thực thi ở request kế tiếp — nếu không FE
    sẽ ẩn một mục mà API cho, hoặc hiện một mục mà API chặn.
    """
```

- [ ] **Step 4: Sửa service**

```python
# src/portal/modules/auth/service.py
def _dung_session_out(
    u: repo.HangUser, ws: list, tenant_id: str | None, actions: frozenset[str]
) -> SessionOut:
    """Một chỗ dựng payload, hai đường gọi (login và /me).

    `actions` PHẢI đến từ `doc_quyen` của người gọi — không tự tính lại ở đây.
    """
    return SessionOut(
        user=UserOut(id=u.id, name=u.name, email=u.email, initials=suy_initials(u.name)),
        workspaces=ws,
        currentWorkspaceId=tenant_id,
        actions=sorted(actions),
    )


async def dung_session_out(conn: asyncpg.Connection, ban_ghi: ss.BanGhiPhien) -> SessionOut:
    u = await repo.tim_user_theo_id(conn, ban_ghi.user_id)
    if u is None:
        raise loi.khong_co_phien()
    ws = await repo.liet_ke_workspace(conn, ban_ghi.user_id)
    # KHÔNG raise khi ws rỗng: từ 2026-08-15 phiên không workspace là hợp lệ
    # (spec bo-organization §5.0). Người vừa tự đăng ký đi qua đúng nhánh này.
    q = (
        await core_repo.doc_quyen(conn, ban_ghi.user_id, ban_ghi.tenant_id)
        if ban_ghi.tenant_id is not None
        else None
    )
    return _dung_session_out(u, ws, ban_ghi.tenant_id, q.actions if q else frozenset())
```

Và trong `dang_nhap`, thay khối raise:

```python
    ws = await repo.liet_ke_workspace(conn, u.id)
    # 0 workspace KHÔNG còn là lỗi — xem dung_session_out.
    tenant_id = ws[0].id if ws else None
    session_id = await ss.tao(r, user_id=u.id, tenant_id=tenant_id)
    q = await core_repo.doc_quyen(conn, u.id, tenant_id) if tenant_id else None
    return session_id, _dung_session_out(u, ws, tenant_id, q.actions if q else frozenset())
```

Xoá import `OrganizationOut`.

- [ ] **Step 5: Sửa repo + fake**

Trong `src/portal/modules/auth/repo.py`: xoá hàm `doc_to_chuc`, bỏ `org_id`/`org_role` khỏi `HangUser` và khỏi các câu `SELECT` dựng nó.

Trong `src/portal/modules/auth/fake.py`: xoá `organization=OrganizationOut(...)` và `orgRole=...` khỏi mẫu; xoá docstring nhắc migration 0102.

Trong `src/portal/api/loi.py`, viết lại docstring `khong_co_workspace()`:

```python
def khong_co_workspace() -> LoiPortal:
    """Đổi workspace sang một workspace user không thuộc.

    KHÔNG còn dùng cho đăng nhập/`/me`: phiên không workspace là trạng thái HỢP
    LỆ từ 2026-08-15 (spec bo-organization §5.0), đảo ngược PQ_01 Q01.
    """
    return LoiPortal("NO_WORKSPACE", 409, "Bạn không thuộc workspace này")
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/auth -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/auth/ src/portal/api/loi.py tests/modules/auth/
git commit -m "feat(api): SessionOut bỏ organization/orgRole, currentWorkspaceId nhận null"
```

---

### Task 6: `POST /api/v1/auth/register`

**Files:**
- Modify: `src/portal/modules/auth/contracts.py` (thêm `VaoDangKy`)
- Modify: `src/portal/modules/auth/service.py` (thêm `dang_ky`)
- Modify: `src/portal/modules/auth/repo.py` (thêm `tao_user_tu_dang_ky`)
- Modify: `src/portal/modules/auth/router.py`
- Test: `tests/modules/auth/test_dang_ky.py`

**Interfaces:**
- Consumes: Task 5 (`_dung_session_out` chữ ký mới).
- Produces: `service.dang_ky(conn, r, *, email, name, mat_khau) -> tuple[str, SessionOut]`; `repo.tao_user_tu_dang_ky(conn, *, user_id, email, name, password_hash) -> HangUser`.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/auth/test_dang_ky.py
import pytest

_MOI = {"email": "Nguoi.Moi@X.VN", "name": "Người Mới", "password": "matkhau-du-dai"}


@pytest.mark.asyncio
async def test_dang_ky_tra_phien_khong_workspace(app_client):
    r = await app_client.post("/api/v1/auth/register", json=_MOI)
    assert r.status_code == 201
    body = r.json()
    assert body["workspaces"] == []
    assert body["currentWorkspaceId"] is None
    assert body["actions"] == []
    assert body["user"]["email"] == "nguoi.moi@x.vn", "email phải chuẩn hoá về chữ thường"


@pytest.mark.asyncio
async def test_dang_ky_dat_cookie_phien(app_client):
    r = await app_client.post("/api/v1/auth/register", json=_MOI)
    assert "sid" in r.cookies or any(c.startswith("sid=") for c in r.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_dang_ky_trung_email_tra_409(app_client):
    await app_client.post("/api/v1/auth/register", json=_MOI)
    r = await app_client.post("/api/v1/auth/register", json=_MOI)
    assert r.status_code == 409
    assert r.json()["code"] == "EMAIL_DA_DUNG"


@pytest.mark.asyncio
async def test_mat_khau_qua_ngan_tra_422(app_client):
    r = await app_client.post("/api/v1/auth/register", json={**_MOI, "password": "ngan"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dang_ky_xong_dang_nhap_duoc_ngay(app_client):
    await app_client.post("/api/v1/auth/register", json=_MOI)
    r = await app_client.post(
        "/api/v1/auth/login", json={"email": _MOI["email"], "password": _MOI["password"]}
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_dang_ky.py -v`
Expected: FAIL — 404, route chưa tồn tại.

- [ ] **Step 3: Contract**

```python
# src/portal/modules/auth/contracts.py
class VaoDangKy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    """8 là sàn, không phải chính sách mật khẩu. Chính sách thật (độ phức tạp,
    danh sách rò rỉ) chưa có và không được giả vờ là đã có bằng một regex."""
```

- [ ] **Step 4: Repo**

```python
# src/portal/modules/auth/repo.py
async def tao_user_tu_dang_ky(
    conn: asyncpg.Connection, *, user_id: str, email: str, name: str, password_hash: str
) -> HangUser:
    """Tự đăng ký: user ra đời KHÔNG thuộc workspace nào và không có ai bảo lãnh.

    Khác `tao_user()` (đường quản trị, kèm memberships và người mời) — tách hàm
    chứ không thêm tham số tuỳ chọn, vì hai đường có hai bất biến khác nhau và gộp
    lại thì mỗi lần đọc phải suy ngược xem nhánh nào đang chạy.
    """
    r = await conn.fetchrow(
        """INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                VALUES ($1, $2, $3, $4, 'active')
             RETURNING id, email, name, password_hash, lifecycle""",
        user_id,
        email,
        name,
        password_hash,
    )
    return HangUser(r["id"], r["email"], r["name"], r["password_hash"], r["lifecycle"])
```

- [ ] **Step 5: Service**

```python
# src/portal/modules/auth/service.py
import uuid


async def dang_ky(
    conn: asyncpg.Connection, r: Redis, *, email: str, name: str, mat_khau: str
) -> tuple[str, SessionOut]:
    """Tự đăng ký. Trả (session_id, SessionOut) — đăng ký xong là đã đăng nhập.

    KHÔNG tạo workspace ở đây. Người dùng đăng ký xong rơi vào phiên không
    workspace (hợp lệ, xem §5.0) và FE đưa họ tới màn tạo workspace đầu tiên.
    Gộp hai việc lại buộc phải hỏi tên workspace ngay ở form đăng ký, và người
    chưa biết sản phẩm là gì thì chưa có tên để đặt.

    KHÔNG xác thực email ở đợt này — ghi rõ ở spec §12 là ngoài phạm vi, để người
    sau không tưởng đây là sơ suất.
    """
    email = chuan_hoa_email(email)
    if await repo.email_da_dung(conn, email):
        raise loi.email_da_dung(email)

    user_id = f"u_{uuid.uuid4().hex[:16]}"
    u = await repo.tao_user_tu_dang_ky(
        conn, user_id=user_id, email=email, name=name.strip(), password_hash=pw.bam(mat_khau)
    )
    session_id = await ss.tao(r, user_id=u.id, tenant_id=None)
    return session_id, _dung_session_out(u, [], None, frozenset())
```

Nếu `portal.core.auth.password` chưa có hàm băm tên `bam`, dùng tên thật của nó (đọc `src/portal/core/auth/password.py`); chữ ký còn lại không đổi.

Nếu `loi.email_da_dung` chưa tồn tại, thêm vào `src/portal/api/loi.py`:

```python
def email_da_dung(email: str) -> LoiPortal:
    return LoiPortal("EMAIL_DA_DUNG", 409, f"Email {email} đã có tài khoản")
```

- [ ] **Step 6: Router**

```python
# src/portal/modules/auth/router.py
@ROUTER.post("/auth/register", response_model=SessionOut, status_code=201)
async def dang_ky(
    vao: VaoDangKy,
    res: Response,
    _: None = require(None, ly_do="chính đường này tạo ra tài khoản đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> SessionOut:
    async with pool.acquire() as conn, conn.transaction():
        session_id, ra = await service.dang_ky(
            conn, r, email=vao.email, name=vao.name, mat_khau=vao.password
        )
    _dat_cookie(res, session_id)
    return ra
```

- [ ] **Step 7: Chạy test**

```bash
uv run pytest tests/modules/auth/test_dang_ky.py tests/unit/test_moi_route_khai_action.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/auth/ src/portal/api/loi.py tests/modules/auth/test_dang_ky.py
git commit -m "feat(auth): POST /auth/register — tự đăng ký, phiên không workspace"
```

---

### Task 7: `workspace.service.tao()` — mở cổng, ghi membership 'Quản trị'

**Files:**
- Modify: `src/portal/modules/workspace/service.py`
- Modify: `src/portal/modules/workspace/repo.py`
- Modify: `src/portal/modules/workspace/contracts.py`
- Modify: `src/portal/modules/workspace/loi.py`
- Test: `tests/modules/workspace/test_tao.py`

**Interfaces:**
- Consumes: Task 2 (`tenants.created_by`), Task 3 (`doc_quyen` không nhánh owner).
- Produces: `repo.HangActor(id: str)`; `repo.ten_da_dung(conn, created_by, ten) -> bool`; `repo.them_tenant(conn, tenant_id, ten, created_by) -> HangTenant`; `repo.id_vai_tro_quan_tri(conn) -> str`; `repo.them_membership(conn, user_id, tenant_id, role_id) -> None`. `WorkspaceTaoRaOut` không còn `orgId`.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/workspace/test_tao.py  (thêm)
@pytest.mark.asyncio
async def test_ai_co_phien_cung_tao_duoc_workspace(app_client, user_moi_dang_ky, pool):
    r = await app_client.post("/api/v1/workspaces", json={"name": "Sàn Mới"})
    assert r.status_code == 201, "cổng org_role='owner' đã bỏ — chỉ cần có phiên"


@pytest.mark.asyncio
async def test_nguoi_tao_thanh_quan_tri_cua_workspace_do(app_client, user_moi_dang_ky, pool):
    r = await app_client.post("/api/v1/workspaces", json={"name": "Sàn Mới"})
    tid = r.json()["id"]
    ten_vai_tro = await pool.fetchval(
        """SELECT ro.name FROM control.memberships m
             JOIN control.roles ro ON ro.id = m.role_id
            WHERE m.user_id = $1 AND m.tenant_id = $2""",
        user_moi_dang_ky,
        tid,
    )
    assert ten_vai_tro == "Quản trị"


@pytest.mark.asyncio
async def test_tao_xong_vao_duoc_chinh_no(app_client, user_moi_dang_ky):
    r = await app_client.post("/api/v1/workspaces", json={"name": "Sàn Mới"})
    tid = r.json()["id"]
    doi = await app_client.post("/api/v1/me/workspace", json={"workspaceId": tid})
    assert doi.status_code == 200
    assert len(doi.json()["actions"]) == 13


@pytest.mark.asyncio
async def test_ghi_created_by(app_client, user_moi_dang_ky, pool):
    r = await app_client.post("/api/v1/workspaces", json={"name": "Sàn Mới"})
    nguoi_tao = await pool.fetchval(
        "SELECT created_by FROM control.tenants WHERE id = $1", r.json()["id"]
    )
    assert nguoi_tao == user_moi_dang_ky


@pytest.mark.asyncio
async def test_hai_nguoi_dat_trung_ten_deu_thanh_cong(app_client, hai_phien_khac_nhau):
    a, b = hai_phien_khac_nhau
    assert (await a.post("/api/v1/workspaces", json={"name": "Test"})).status_code == 201
    assert (await b.post("/api/v1/workspaces", json={"name": "Test"})).status_code == 201


@pytest.mark.asyncio
async def test_cung_nguoi_dat_trung_ten_bi_409(app_client, user_moi_dang_ky):
    await app_client.post("/api/v1/workspaces", json={"name": "Test"})
    r = await app_client.post("/api/v1/workspaces", json={"name": " test "})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_response_khong_con_org_id(app_client, user_moi_dang_ky):
    r = await app_client.post("/api/v1/workspaces", json={"name": "Sàn Mới"})
    assert "orgId" not in r.json()
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/workspace/test_tao.py -v`
Expected: FAIL — 403 (cổng `org_role`).

- [ ] **Step 3: Sửa repo**

```python
# src/portal/modules/workspace/repo.py
@dataclass(frozen=True, slots=True)
class HangActor:
    """Chỉ còn id: `org_id`/`org_role` đã bị bỏ 2026-08-15. Giữ dataclass thay vì
    trả `str` để chỗ gọi không phải đổi hình dạng khi cần thêm cột."""

    id: str


@dataclass(frozen=True, slots=True)
class HangTenant:
    id: str
    name: str
    lifecycle: str
    created_at: datetime


async def tim_actor(conn: asyncpg.Connection, user_id: str) -> HangActor | None:
    r = await conn.fetchrow("SELECT id FROM control.users WHERE id = $1", user_id)
    return None if r is None else HangActor(r["id"])


async def ten_da_dung(conn: asyncpg.Connection, created_by: str, ten: str) -> bool:
    """Trùng tên trong phạm vi MỘT NGƯỜI TẠO, so sánh đã chuẩn hoá.

    Phạm vi đổi từ tổ chức sang người tạo cùng lúc với việc bỏ tầng tổ chức: ai
    cũng tạo được workspace, nên hai người lạ đặt tên "Test" là chuyện bình thường.

    Từ migration 0106 có UNIQUE INDEX `tenants_nguoi_tao_ten_key` trên đúng biểu
    thức này, nên cửa sổ đua của phép kiểm ở tầng app đã ĐÓNG — hàm này giờ chỉ
    để trả 409 có thông điệp đẹp thay vì để INSERT nổ ra 500.
    """
    return await conn.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM control.tenants
              WHERE created_by = $1 AND lower(btrim(name)) = lower(btrim($2))
           )""",
        created_by,
        ten,
    )


async def them_tenant(conn: asyncpg.Connection, tenant_id: str, ten: str, created_by: str) -> HangTenant:
    r = await conn.fetchrow(
        """INSERT INTO control.tenants (id, name, created_by)
                VALUES ($1, $2, $3)
             RETURNING id, name, lifecycle, created_at""",
        tenant_id,
        ten,
        created_by,
    )
    return HangTenant(r["id"], r["name"], r["lifecycle"], r["created_at"])


async def id_vai_tro_quan_tri(conn: asyncpg.Connection) -> str:
    """Tra theo TÊN, không suy bằng md5.

    Cùng lý lẽ 0104 đã ghi: một vai trò mẫu bị xoá qua API rồi tạo lại nhận id
    `uuid4()`, không phải `md5(...)`. Tra theo tên luôn trúng hàng THẬT đang tồn
    tại, bất kể id của nó sinh ra từ đâu.

    Không tìm thấy ⇒ nổ. Tạo workspace mà không gán được vai trò cho người tạo
    thì họ không vào được chính workspace vừa tạo — một trạng thái hỏng câm.
    """
    rid = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
    if rid is None:
        raise RuntimeError(
            "không tìm thấy vai trò 'Quản trị' trong control.roles — "
            "seed vai trò đã bị xoá? Xem migration 0104/0105."
        )
    return rid


async def them_membership(
    conn: asyncpg.Connection, user_id: str, tenant_id: str, role_id: str
) -> None:
    await conn.execute(
        """INSERT INTO control.memberships (user_id, tenant_id, role_id)
                VALUES ($1, $2, $3)""",
        user_id,
        tenant_id,
        role_id,
    )
```

- [ ] **Step 4: Sửa service**

```python
# src/portal/modules/workspace/service.py
async def tao(conn: asyncpg.Connection, actor_id: str, vao: TaoWorkspaceIn) -> WorkspaceTaoRaOut:
    """Người dùng tự tạo một workspace và trở thành "Quản trị" của nó.

    GHI `control.memberships` — ĐẢO NGƯỢC CÓ CHỦ Ý quyết định cũ. Bản trước ghi
    "KHÔNG ghi memberships" vì `org_role='owner'` đã cho đủ 13 action ở mọi
    workspace cùng tổ chức. Nhánh owner đó bị bỏ 2026-08-15, nên nếu không ghi
    membership thì người vừa tạo workspace KHÔNG vào được chính nó.

    KHÔNG cấp phát hạ tầng. `CREATE ROLE` và khoá kho tệp không nằm trong giao
    dịch này — gộp vào là tạo trạng thái nửa vời mà rollback không dọn được.
    `derive_tenant_status()` trả `provisioning` cho workspace chưa có nhịp tim và
    coi đó là BÌNH THƯỜNG; cấp phát là hành động riêng ở `/agent/*`.
    """
    ten = vao.name.strip()

    actor = await repo.tim_actor(conn, actor_id)
    if actor is None:
        # Phiên đã xác thực tới được đây thì user luôn tồn tại, nên None chỉ có thể
        # là một cuộc đua với xoá user — câu trả lời đúng cho nó cũng là "không được".
        raise loi_chung.khong_du_quyen()

    if await repo.ten_da_dung(conn, actor.id, ten):
        raise loi.ten_workspace_da_dung(ten)

    tenant_id = await sinh_tenant_id(conn, ten)
    hang = await repo.them_tenant(conn, tenant_id, ten, actor.id)
    await repo.them_vertical(conn, tenant_id, VERTICAL_MAC_DINH)
    await repo.them_membership(conn, actor.id, tenant_id, await repo.id_vai_tro_quan_tri(conn))

    await nhat_ky.ghi(
        conn,
        tenant_id,
        "workspace.tao",
        actor_id,
        {"name": ten, "vertical": VERTICAL_MAC_DINH},
    )

    return WorkspaceTaoRaOut(
        id=hang.id,
        name=hang.name,
        lifecycle=hang.lifecycle,
        status=derive_tenant_status(
            lifecycle=hang.lifecycle,
            last_seen_at=None,
            running_version=None,
            live_version=None,
            now=hang.created_at,
        ),
        created_at=hang.created_at,
    )
```

- [ ] **Step 5: Sửa contracts + loi + router**

`src/portal/modules/workspace/contracts.py`: xoá `org_id: str = Field(serialization_alias="orgId")` khỏi `WorkspaceTaoRaOut`; sửa docstring `TaoWorkspaceIn` (bỏ câu "suy từ `org_id` của actor").

`src/portal/modules/workspace/loi.py`: sửa docstring — phạm vi trùng tên giờ là "workspace của chính bạn", không phải "tổ chức".

`src/portal/modules/workspace/router.py`: đổi `require(ACTIONS.WORKSPACE_ADMIN)` ở route tạo workspace thành `require(None, ly_do="tạo workspace mới — chưa có workspace nào để xét quyền trong đó")`, và sửa khối comment đầu file nói về "cửa thật là org_role".

⚠ Route này giờ chỉ cần phiên, nên nó phải tự đọc `user_id` từ phiên qua `lay_ban_ghi_phien` thay vì nhận `Principal`.

```python
@ROUTER.post("/workspaces", response_model=WorkspaceTaoRaOut, status_code=201)
async def tao_workspace(
    vao: TaoWorkspaceIn,
    _: None = require(None, ly_do="tạo workspace mới — chưa có workspace nào để xét quyền trong đó"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> WorkspaceTaoRaOut:
    _, ban_ghi = phien
    async with pool.acquire() as conn, conn.transaction():
        return await service.tao(conn, ban_ghi.user_id, vao)
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/workspace tests/unit/test_moi_route_khai_action.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/workspace/ tests/modules/workspace/
git commit -m "feat(workspace): ai có phiên cũng tạo được workspace, người tạo là Quản trị"
```

---

### Task 8: Gỡ `org_id` khỏi `modules/auth` repo + service vai trò

**Files:**
- Modify: `src/portal/modules/auth/repo.py`
- Modify: `src/portal/modules/auth/quan_tri_vai_tro.py`
- Modify: `src/portal/modules/auth/quan_tri_user.py`
- Modify: `src/portal/modules/auth/loi.py`
- Modify: `src/portal/core/nhat_ky.py`
- Test: `tests/modules/auth/test_vai_tro.py`

**Interfaces:**
- Consumes: Task 2 (schema không còn `org_id`).
- Produces: `repo.liet_ke_vai_tro(conn)` · `repo.doc_vai_tro(conn, role_id)` · `repo.tao_vai_tro(conn, role_id, name, description)` · `repo.doi_ten_vai_tro(conn, role_id, name, description)` · `repo.dat_action_cua_vai_tro(conn, role_id, codes)` · `repo.xoa_vai_tro(conn, role_id)` · `repo.liet_ke_user(conn)` · `repo.doc_chi_tiet_user(conn, user_id)` · `repo.liet_ke_membership(conn, user_id)` — tất cả **bỏ tham số `org_id`**. `nhat_ky.ghi(conn, tenant_id, hanh_dong, actor, chi_tiet)` bỏ `org_id`.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/auth/test_vai_tro.py  (thêm)
@pytest.mark.asyncio
async def test_moi_role_id_ton_tai_deu_hop_le(app_client, quan_tri_client, pool):
    """422 ROLE_NOT_IN_ORG đã bỏ: vai trò giờ toàn cục, không thuộc tổ chức nào."""
    rid = await pool.fetchval("SELECT id FROM control.roles WHERE name = 'CSKH'")
    r = await quan_tri_client.post(
        "/api/v1/members", json={"emails": ["ai.do@x.vn"], "roleId": rid}
    )
    assert r.status_code in (200, 201)


@pytest.mark.asyncio
async def test_role_id_khong_ton_tai_tra_role_not_found(quan_tri_client):
    r = await quan_tri_client.post(
        "/api/v1/members", json={"emails": ["ai.do@x.vn"], "roleId": "khong_co_that"}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "ROLE_NOT_FOUND"
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_vai_tro.py -v`
Expected: FAIL — mã lỗi còn là `ROLE_NOT_IN_ORG`.

- [ ] **Step 3: Gỡ `org_id` khỏi 9 hàm repo**

Trong `src/portal/modules/auth/repo.py`, với mỗi hàm liệt kê ở **Interfaces**: bỏ tham số `org_id`, bỏ mệnh đề `WHERE org_id = $n` / `AND org_id = $n`, và đánh số lại placeholder `$1..$n`. Xoá hẳn `loc_workspace_ngoai_to_chuc`, `loc_role_ngoai_to_chuc`, `dem_owner` — cả ba chỉ tồn tại để canh biên tổ chức.

Đổi `loc_role_ngoai_to_chuc` thành:

```python
async def loc_role_khong_ton_tai(conn: asyncpg.Connection, role_ids: list[str]) -> list[str]:
    """Trả các role_id KHÔNG có trong `control.roles`.

    Thay `loc_role_ngoai_to_chuc`: vai trò đã toàn cục nên "ngoài tổ chức" không
    còn nghĩa; câu hỏi duy nhất còn lại là "có tồn tại không".
    """
    co = await conn.fetch("SELECT id FROM control.roles WHERE id = ANY($1::text[])", role_ids)
    thay = {r["id"] for r in co}
    return [rid for rid in role_ids if rid not in thay]
```

- [ ] **Step 4: Đổi mã lỗi**

`src/portal/modules/auth/loi.py`:

```python
def vai_tro_khong_ton_tai_trong_yeu_cau(role_ids: list[str]) -> LoiPortal:
    """Thay `ROLE_NOT_IN_ORG` (422). Vai trò toàn cục từ 2026-08-15 nên câu hỏi
    "có thuộc tổ chức của bạn không" không còn nghĩa."""
    return LoiPortal("ROLE_NOT_FOUND", 422, f"Vai trò không tồn tại: {', '.join(role_ids)}")
```

Xoá `_kiem_role_thuoc_to_chuc` trong `quan_tri_user.py`, thay bằng lời gọi `loc_role_khong_ton_tai`.

- [ ] **Step 5: `nhat_ky.py`**

```python
# src/portal/core/nhat_ky.py — bỏ tham số org_id ở cả hai hàm ghi
    await conn.execute(
        "INSERT INTO control.audit_log (hanh_dong, actor, chi_tiet) VALUES ($1, $2, $3::jsonb)",
        hanh_dong,
        actor,
        chi_tiet,
    )
```

Hai hàm vẫn là **hai hàm** — lý lẽ tách chúng không liên quan tới org.

- [ ] **Step 6: Chạy test**

```bash
uv run pytest tests/modules/auth tests/test_module_boundaries.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/auth/ src/portal/core/nhat_ky.py tests/modules/auth/
git commit -m "refactor(auth): gỡ org_id khỏi repo/service vai trò, ROLE_NOT_IN_ORG -> ROLE_NOT_FOUND"
```

---

### Task 9: Hai cờ đóng khối endpoint mất chủ

**Files:**
- Modify: `src/portal/core/config.py`
- Modify: `src/portal/modules/auth/quan_tri_user.py`
- Modify: `src/portal/modules/auth/quan_tri_vai_tro.py`
- Modify: `src/portal/api/loi.py`
- Test: `tests/modules/auth/test_co_dong_cong.py`

**Interfaces:**
- Consumes: Task 8.
- Produces: `Settings.roles_crud_enabled: bool = False`, `Settings.users_admin_enabled: bool = False`; `loi.tinh_nang_dang_tat(ten: str) -> LoiPortal` (403, code `FEATURE_DISABLED`).

- [ ] **Step 1: Viết test thất bại**

```python
# tests/modules/auth/test_co_dong_cong.py
"""Hai khối endpoint mất chủ sau khi bỏ org_role.

Vai trò giờ TOÀN CỤC (một bộ 4 dùng chung cho mọi workspace), nên nếu để ghi
`/roles` mở cho WORKSPACE_ADMIN thì Quản trị của một workspace bất kỳ sửa được
quyền của TẤT CẢ workspace khác. Trước đây `org_role='owner'` giới hạn phạm vi đó.
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "duong"),
    [("post", "/api/v1/roles"), ("patch", "/api/v1/roles/r_x"), ("delete", "/api/v1/roles/r_x")],
)
async def test_ghi_vai_tro_bi_tat_mac_dinh(quan_tri_client, method, duong):
    r = await getattr(quan_tri_client, method)(duong, json={"name": "X", "actions": []})
    assert r.status_code == 403
    assert r.json()["code"] == "FEATURE_DISABLED"


@pytest.mark.asyncio
async def test_doc_vai_tro_van_mo(quan_tri_client):
    """FE cần GET /roles để render dropdown chọn vai trò khi mời thành viên."""
    r = await quan_tri_client.get("/api/v1/roles")
    assert r.status_code == 200
    assert {v["name"] for v in r.json()} == {"Quản trị", "CSKH", "Biên tập", "Người xem"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "duong"),
    [("get", "/api/v1/users"), ("post", "/api/v1/users"), ("delete", "/api/v1/users/u_x")],
)
async def test_quan_tri_user_bi_tat_mac_dinh(quan_tri_client, method, duong):
    r = await getattr(quan_tri_client, method)(duong, json={})
    assert r.status_code == 403
    assert r.json()["code"] == "FEATURE_DISABLED"


@pytest.mark.asyncio
async def test_mac_dinh_trong_code_la_tat(monkeypatch):
    """Settings(_env_file=None): đo giá trị mặc định trong CODE, không phải .env
    của lập trình viên — xem Gotchas ở CLAUDE.md."""
    from portal.core.config import Settings

    s = Settings(_env_file=None)
    assert s.roles_crud_enabled is False
    assert s.users_admin_enabled is False
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_co_dong_cong.py -v`
Expected: FAIL — chưa có cờ.

- [ ] **Step 3: Thêm cờ**

```python
# src/portal/core/config.py
    roles_crud_enabled: bool = False
    """Ghi `control.roles` qua API (POST/PATCH/DELETE /roles).

    TẮT mặc định từ 2026-08-15: bỏ `org_role` làm khối này mất cửa thật, và vai
    trò đã toàn cục nên một Quản trị workspace bất kỳ sẽ sửa được quyền của MỌI
    workspace. Code + bảng giữ nguyên để bật lại khi có mô hình quyền động.
    """

    users_admin_enabled: bool = False
    """Quản trị user toàn hệ thống (6 đường /users*).

    TẮT mặc định từ 2026-08-15 vì cùng lý do: không còn admin hệ thống nào để
    làm chủ khối này. Tạo tài khoản giờ đi qua `POST /auth/register`.
    """
```

- [ ] **Step 4: Cổng ở tầng service**

```python
# src/portal/api/loi.py
def tinh_nang_dang_tat(ten: str) -> LoiPortal:
    """403 chứ không 404: endpoint CÓ tồn tại và sẽ bật lại — trả 404 làm client
    kết luận sai rằng nó đã bị gỡ và đi tìm đường thay thế."""
    return LoiPortal("FEATURE_DISABLED", 403, f"Tính năng '{ten}' đang tắt")
```

```python
# src/portal/modules/auth/quan_tri_vai_tro.py — đầu mỗi hàm GHI (tao/sua/xoa)
def _cong_ghi_vai_tro() -> None:
    if not get_settings().roles_crud_enabled:
        raise loi_chung.tinh_nang_dang_tat("quản trị vai trò")
```

```python
# src/portal/modules/auth/quan_tri_user.py — thay _lay_owner() ở cả 6 đường
def _cong_users_admin() -> None:
    if not get_settings().users_admin_enabled:
        raise loi_chung.tinh_nang_dang_tat("quản trị người dùng")
```

Xoá hàm `_lay_owner()` — nó đọc `org_role` đã không còn.

Kiểm cờ nằm ở **tầng service**, không ở router — cùng khuôn với `_lay_owner()` mà nó thay thế, và giữ router chỉ còn khai action.

- [ ] **Step 5: Chạy test**

```bash
uv run pytest tests/modules/auth -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/config.py src/portal/api/loi.py src/portal/modules/auth/ tests/modules/auth/test_co_dong_cong.py
git commit -m "feat(auth): đóng /users* và ghi /roles* bằng cờ, giữ nguyên code"
```

---

### Task 10: Script seed + `dev_seed` viết lại

**Files:**
- Modify: `scripts/dev_seed.py`
- Modify: `scripts/nap_du_lieu_tu_odyssey.py`
- Modify: `scripts/seed_kho_tep.py`
- Modify: `src/portal/cli/seed_owner.py`
- Test: `tests/integration/test_seed_owner.py`

**Interfaces:**
- Consumes: Task 2, Task 7.
- Produces: `make dev-seed` dựng 3 user · 3 workspace · 0 tổ chức, giữ nguyên ba tài khoản và mật khẩu cũ.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/integration/test_seed_owner.py  (viết lại phần org)
@pytest.mark.asyncio
async def test_dev_seed_khong_tao_to_chuc_nao(pool):
    assert await pool.fetchval("SELECT to_regclass('control.organizations')") is None


@pytest.mark.asyncio
async def test_haven_khong_thay_workspace_cua_dang(pool):
    """Bất biến THAY THẾ cho "haven thuộc org khác".

    Cách ly giờ do memberships canh: haven không có hàng memberships nào ở
    anphu/sunrise nên không thấy hai workspace đó.
    """
    ws = await pool.fetch(
        """SELECT t.id FROM control.memberships m
             JOIN control.tenants t ON t.id = m.tenant_id
             JOIN control.users u ON u.id = m.user_id
            WHERE u.email = 'haven@haven.vn'"""
    )
    assert {r["id"] for r in ws}.isdisjoint({"anphu", "sunrise"})


@pytest.mark.asyncio
async def test_dang_van_thay_hai_workspace(pool):
    ws = await pool.fetch(
        """SELECT t.id FROM control.memberships m
             JOIN control.tenants t ON t.id = m.tenant_id
             JOIN control.users u ON u.id = m.user_id
            WHERE u.email = 'dang@anphuland.vn'"""
    )
    assert {r["id"] for r in ws} >= {"anphu", "sunrise"}
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/integration/test_seed_owner.py -v`
Expected: FAIL — `dev_seed` còn chèn org.

- [ ] **Step 3: Viết lại `dev_seed.py`**

Bỏ mọi `INSERT INTO control.organizations` và cột `org_id`/`org_role`. Với mỗi workspace thêm `created_by`. Với `dang@anphuland.vn`, thay `org_role='owner'` bằng **hai hàng `memberships`** vai trò `Quản trị` ở `anphu` và `sunrise`. `bientap@anphuland.vn` giữ `Biên tập` ở `anphu`. `haven@haven.vn` nhận `Quản trị` ở workspace `havengroup` và **không có hàng nào** ở `anphu`/`sunrise`.

- [ ] **Step 4: Chạy lại từ đầu**

```bash
make reset && make up
uv run pytest tests/integration/test_seed_owner.py -v
```
Expected: PASS, và cuối `make up` vẫn in ba tài khoản như cũ.

- [ ] **Step 5: Commit**

```bash
git add scripts/ src/portal/cli/seed_owner.py tests/integration/test_seed_owner.py
git commit -m "feat(seed): dev_seed bỏ tổ chức, cách ly do memberships canh"
```

---

### Task 11: Tài liệu backend

**Files:**
- Modify: `CLAUDE.md`
- Modify: `SPEC-DB-HIEN-TAI.md`, `PHAN-TICH-THIET-KE-DB.md`, `docs/architecture/*`
- Modify: `docs/superpowers/specs/2026-08-03-organization-level-above-tenant-design.md` (banner)

- [ ] **Step 1: `CLAUDE.md`**

Sửa dòng `make dev-seed` (`3 user · 3 workspace · 2 tổ chức` → `3 user · 3 workspace`), sửa mô tả tài khoản seed (`haven@haven.vn` — bỏ "org khác", thay bằng "không có membership ở anphu/sunrise"), sửa bảng schema `control` (bỏ `organizations`), và thêm một dòng Change Log:

```markdown
| 2026-08-15 | **Bỏ tầng `control.organizations`** (`0105_roles_thoat_org` + `0106_bo_organizations`). Phân quyền từ hai trục (`users.org_role` + `memberships.role_id`) xuống MỘT trục — không có membership là không có quyền, nhánh owner trong `doc_quyen()` đã gỡ. `tenants` thêm `created_by`, tên workspace duy nhất theo NGƯỜI TẠO (`tenants_nguoi_tao_ten_key`), không toàn cục — ai cũng tạo được workspace nên hai người lạ đặt tên "Test" là bình thường. Vai trò TOÀN CỤC (một bộ 4 dùng chung): kéo theo ghi `/roles*` và toàn bộ `/users*` mất cửa thật, đóng bằng `ROLES_CRUD_ENABLED`/`USERS_ADMIN_ENABLED` (mặc định `false`), **giữ nguyên code + bảng** để bật lại khi có quyền động. Mới: `POST /auth/register` (tự đăng ký) và **phiên không workspace là trạng thái HỢP LỆ** — đảo ngược PQ_01 Q01, vì người vừa đăng ký có 0 workspace và 409 cũ là ngõ cụt. Ba comment "M2a chưa bật ma trận, M2b sẽ bật" đã **lỗi thời từ lâu** (`require()` cưỡng chế action thật từ trước) — đã gỡ. `odyssey-agent`: xoá dead code org (`org_of`/`new_tenant_id`/`_prefix`) — nó chưa bao giờ nằm trên đường serving, `tenant_id` thật do Portal sinh không mang tiền tố org. Spec: `docs/superpowers/specs/2026-08-15-bo-organization-design.md`. |
```

- [ ] **Step 2: Banner lên spec cũ**

Thêm vào đầu `2026-08-03-organization-level-above-tenant-design.md`:

```markdown
> ⚠ **ĐÃ BỊ THAY THẾ 2026-08-15** bởi
> `2026-08-15-bo-organization-design.md`. Tầng tổ chức mô tả ở đây đã bị gỡ khỏi
> hệ thống. Giữ lại làm hồ sơ vì sao nó từng tồn tại — đừng thi công theo.
```

- [ ] **Step 3: `make check`**

Run: `make check`
Expected: lint + test xanh (trừ 1 dòng đỏ có sẵn ở `tests/isolation`, không liên quan).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md SPEC-DB-HIEN-TAI.md PHAN-TICH-THIET-KE-DB.md docs/
git commit -m "docs: cập nhật tài liệu sau khi bỏ tầng organization"
```

---

## Phase 2 — Frontend (`odyssey-portal-frontend`)

### Task 12: Gỡ organization khỏi type, UI và MSW

**Files:**
- Modify: `src/lib/session.tsx:55,70`
- Modify: `src/components/shell/UserMenu.tsx:118`
- Modify: `src/features/auth/components/NhanLoiMoi.tsx:70,79,84,118`
- Modify: `src/features/auth/api.ts:152`
- Modify: `src/features/workspace/api.ts:47,61`
- Modify: `src/components/ui/Truong.tsx:180` (comment)
- Modify: `src/lib/msw/handlers.ts:26,303,1098`
- Test: `tests/dang-xuat.test.tsx`, `tests/shell.test.tsx`, `tests/nhan-loi-moi.test.tsx`, `tests/tao-workspace.test.tsx`, `tests/thanh-vien-seam.test.ts`

**Interfaces:**
- Consumes: Task 5, 7, 8 (contract backend mới).
- Produces: `Session { user, workspaces, currentWorkspaceId: string | null, actions }` — không còn `organization`. `TaoWorkspaceKetQua` không còn `orgId`.

- [ ] **Step 1: Sửa test trước (chúng là đặc tả)**

```typescript
// tests/shell.test.tsx — thay assertion cũ ở dòng 325
expect(within(menu).queryByText('NobleX')).not.toBeInTheDocument()
expect(within(menu).getByText(FAKE_SESSION.user.name)).toBeInTheDocument()
```

```typescript
// tests/dang-xuat.test.tsx — dòng 133: bỏ assertion tên tổ chức;
// dòng 146: bỏ override `organization: { id: 'havengroup', ... }` khỏi mock
```

```typescript
// tests/nhan-loi-moi.test.tsx — dòng 48, 86: bỏ `organizationName` khỏi payload giả
```

```typescript
// tests/tao-workspace.test.tsx — dòng 30: bỏ `orgId: 'org_noble'` khỏi mock
```

```typescript
// tests/thanh-vien-seam.test.ts — dòng 101
await expect(moiThanhVien(['a@x.vn'], 'khong_co_that')).rejects.toMatchObject({
  code: 'ROLE_NOT_FOUND',
})
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `npm test`
Expected: FAIL — type `Session` còn `organization`.

- [ ] **Step 3: Sửa type + UI**

```typescript
// src/lib/session.tsx — xoá `export interface Organization` và trường
// `readonly organization: Organization`; đổi:
readonly currentWorkspaceId: string | null
```

```tsx
// src/components/shell/UserMenu.tsx — xoá dòng 118 hiện `session.organization.name`.
// Dòng đó là chỗ DUY NHẤT người dùng từng thấy tên tổ chức.
```

```tsx
// src/features/auth/components/NhanLoiMoi.tsx — bỏ prop `toChuc`, đổi câu mời:
<p>Bạn được mời tham gia.</p>
// KHÔNG thay bằng tên workspace: lời mời được nhận TRƯỚC khi có phiên, người
// nhận chưa có ngữ cảnh workspace nào.
```

```typescript
// src/features/auth/api.ts — bỏ `readonly organizationName: string` khỏi LoiMoi
// src/features/workspace/api.ts — bỏ `readonly orgId: string`, sửa comment dòng 61
```

- [ ] **Step 4: Sửa MSW**

`src/lib/msw/handlers.ts`: bỏ `organization` khỏi `FAKE_SESSION` (dòng 26), bỏ `organizationName` (dòng 1098), sửa comment dòng 303 (`ROLE_NOT_IN_ORG` → `ROLE_NOT_FOUND`) và mã lỗi mà handler trả.

- [ ] **Step 5: Chạy test + typecheck**

```bash
npm test && npm run build
```
Expected: PASS. (⚠ `tsc --noEmit` pass rỗng ở repo này — solution-style tsconfig. Dùng `npm run build`.)

- [ ] **Step 6: Commit**

```bash
git add src/ tests/
git commit -m "feat: gỡ organization khỏi session, UI và MSW"
```

---

### Task 13: Trang đăng ký

**Files:**
- Create: `src/routes/dang-ky.tsx`
- Modify: `src/features/auth/api.ts` (thêm `dangKy`)
- Modify: `src/routes/login.tsx` (thêm link)
- Modify: `src/lib/msw/handlers.ts` (handler `POST /api/v1/auth/register`)
- Test: `tests/dang-ky.test.tsx`

**Interfaces:**
- Consumes: Task 6 (`POST /api/v1/auth/register` → 201 `SessionOut`).
- Produces: `dangKy(email: string, name: string, password: string): Promise<Session>`.

- [ ] **Step 1: Viết test thất bại**

```tsx
// tests/dang-ky.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

describe('Trang đăng ký', () => {
  it('đăng ký thành công thì đưa tới màn tạo workspace đầu tiên', async () => {
    renderTrangDangKy()
    await userEvent.type(screen.getByLabelText('Email'), 'moi@x.vn')
    await userEvent.type(screen.getByLabelText('Họ tên'), 'Người Mới')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'matkhau-du-dai')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng ký' }))
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /workspace đầu tiên/i })).toBeInTheDocument(),
    )
  })

  it('email đã có tài khoản thì hiện lỗi, không điều hướng', async () => {
    renderTrangDangKy()
    await userEvent.type(screen.getByLabelText('Email'), 'da.ton.tai@x.vn')
    await userEvent.type(screen.getByLabelText('Họ tên'), 'A')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'matkhau-du-dai')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng ký' }))
    expect(await screen.findByText(/đã có tài khoản/i)).toBeInTheDocument()
  })

  it('mật khẩu ngắn hơn 8 ký tự thì nút bị khoá', async () => {
    renderTrangDangKy()
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'ngan')
    expect(screen.getByRole('button', { name: 'Đăng ký' })).toBeDisabled()
  })
})
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `npm test tests/dang-ky.test.tsx`
Expected: FAIL — route chưa tồn tại.

- [ ] **Step 3: API client**

```typescript
// src/features/auth/api.ts
export function dangKy(email: string, name: string, password: string): Promise<Session> {
  return goi<Session>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, name, password }),
  })
}
```

- [ ] **Step 4: Trang**

Dựng theo đúng khuôn `src/routes/login.tsx` (cùng layout, cùng component `Truong`, cùng cách hiện `LoiApi`). Ba trường: Email · Họ tên · Mật khẩu (`minLength=8`). Nút khoá khi bất kỳ trường nào rỗng hoặc mật khẩu < 8 ký tự. Thành công ⇒ ghi session vào React Query cache rồi `navigate({ to: '/tao-workspace-dau-tien' })`.

Thêm link ở cuối `login.tsx`: `Chưa có tài khoản? <Link to="/dang-ky">Đăng ký</Link>`.

- [ ] **Step 5: MSW handler**

```typescript
// src/lib/msw/handlers.ts
http.post('/api/v1/auth/register', async ({ request }) => {
  const body = (await request.json()) as { email: string; name: string }
  if (body.email === 'da.ton.tai@x.vn') {
    return HttpResponse.json(
      { code: 'EMAIL_DA_DUNG', message: 'Email đã có tài khoản' },
      { status: 409 },
    )
  }
  return HttpResponse.json(
    {
      user: { id: 'u_moi', name: body.name, email: body.email, initials: 'NM' },
      workspaces: [],
      currentWorkspaceId: null,
      actions: [],
    },
    { status: 201 },
  )
}),
```

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/routes/dang-ky.tsx src/features/auth/api.ts src/routes/login.tsx src/lib/msw/handlers.ts tests/dang-ky.test.tsx
git commit -m "feat: trang đăng ký tài khoản"
```

---

### Task 14: Màn tạo workspace đầu tiên + ẩn `/users`

**Files:**
- Create: `src/routes/tao-workspace-dau-tien.tsx`
- Modify: `src/routes/_app/route.tsx` (guard `currentWorkspaceId === null`)
- Modify: `src/lib/nav-registry.ts` (ẩn `users`)
- Test: `tests/tao-workspace-dau-tien.test.tsx`

**Interfaces:**
- Consumes: Task 12 (`currentWorkspaceId: string | null`), Task 13.
- Produces: route `/tao-workspace-dau-tien`.

- [ ] **Step 1: Viết test thất bại**

```tsx
// tests/tao-workspace-dau-tien.test.tsx
describe('Màn tạo workspace đầu tiên', () => {
  it('phiên không workspace bị đưa khỏi dashboard', async () => {
    renderApp({ session: { ...FAKE_SESSION, workspaces: [], currentWorkspaceId: null } })
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /workspace đầu tiên/i })).toBeInTheDocument(),
    )
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('tạo xong thì vào thẳng workspace vừa tạo', async () => {
    renderApp({ session: { ...FAKE_SESSION, workspaces: [], currentWorkspaceId: null } })
    await userEvent.type(screen.getByLabelText('Tên workspace'), 'Sàn Của Tôi')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo workspace' }))
    await waitFor(() => expect(screen.getByRole('navigation')).toBeInTheDocument())
  })

  it('phiên CÓ workspace không thấy màn này', async () => {
    renderApp({ session: FAKE_SESSION })
    expect(screen.queryByRole('heading', { name: /workspace đầu tiên/i })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `npm test tests/tao-workspace-dau-tien.test.tsx`
Expected: FAIL — route chưa tồn tại.

- [ ] **Step 3: Guard trong layout `_app`**

```tsx
// src/routes/_app/route.tsx — trong beforeLoad hoặc component gác
if (session.currentWorkspaceId === null) {
  throw redirect({ to: '/tao-workspace-dau-tien' })
}
```

Không render sidebar/nav ở màn này: người chưa có workspace không có gì để điều hướng tới, và một sidebar toàn mục xám là lời mời bấm vào chỗ chắc chắn hỏng.

- [ ] **Step 4: Màn hình**

Một trường `Tên workspace` + nút `Tạo workspace`, gọi `taoWorkspace(name)` đã có sẵn ở `src/features/workspace/api.ts`. Thành công ⇒ invalidate query session rồi `navigate({ to: '/dashboard' })`. 409 ⇒ hiện "Bạn đã có workspace tên này".

- [ ] **Step 5: Ẩn `/users` khỏi nav**

```typescript
// src/lib/nav-registry.ts — bỏ mục `users` khỏi danh sách.
// Route file `src/routes/_app/users.tsx` GIỮ NGUYÊN: backend chỉ đóng bằng cờ
// USERS_ADMIN_ENABLED, và xoá file ở đây làm việc bật lại sau này tốn hơn.
```

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/routes/ src/lib/nav-registry.ts tests/tao-workspace-dau-tien.test.tsx
git commit -m "feat: màn tạo workspace đầu tiên, ẩn /users khỏi nav"
```

---

## Phase 3 — Agent (`odyssey-agent`)

### Task 15: Xoá dead code organization

**Files:**
- Modify: `src/noble_agent/tenant/identity.py`
- Modify: `src/noble_agent/tenant/store.py:251-253,522-558`
- Modify: `src/noble_agent/tenant/provisioning.py:46-73,187-194`
- Modify: `src/noble_agent/tenant/current.py:56`
- Modify: `src/noble_agent/tenant/cli.py:217-232`
- Delete: `tests/unit/tenant/test_provisioning_org.py`, `tests/unit/tenant/test_org_isolation.py`
- Modify: `tests/unit/tenant/test_identity.py`, `tests/unit/tenant/test_loader.py`

**Interfaces:**
- Consumes: không gì (độc lập với Phase 1/2).
- Produces: `identity.py` không còn `ORG_RE`/`is_valid_org_id`/`new_org_id`/`org_of`/`new_tenant_id`. `store._prefix(tenant_id) -> str` trả thẳng `tenant_id`. `provisioning.list_tenants(store)` bỏ tham số `org_id`; `provisioning.list_orgs` bị xoá.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/unit/tenant/test_identity.py — thay toàn bộ test org bằng:
def test_khong_con_khai_niem_org():
    """tenant_id THẬT do Portal sinh (`slug(tên)` + hậu tố `_2`..`_50`), KHÔNG
    mang tiền tố org. Scheme `<org_id>_<slug>` ở đây chưa bao giờ nằm trên đường
    serving: TENANT_RE không khớp id thật, loader né nhánh store với id không
    org-format, và tenant_store_enabled mặc định False."""
    import noble_agent.tenant.identity as idy

    for ten in ("ORG_RE", "is_valid_org_id", "new_org_id", "org_of", "new_tenant_id"):
        assert not hasattr(idy, ten), f"{ten} còn sót"


def test_prefix_la_chinh_tenant_id():
    from noble_agent.tenant.store import MinioTenantStore

    assert MinioTenantStore._prefix(object(), "bao-ngoc") == "bao-ngoc"
```

- [ ] **Step 2: Chạy test để xác nhận đỏ**

Run: `uv run pytest tests/unit/tenant/test_identity.py -v`
Expected: FAIL — `org_of` còn tồn tại.

- [ ] **Step 3: Gỡ code**

```python
# src/noble_agent/tenant/identity.py — giữ lại đúng slugify + is_valid_tenant_id
"""Định dạng tenant id — thuần, không I/O.

`tenant_id` do Portal sinh: `slug(tên)`, trùng thì hậu tố `_2`..`_50`. KHÔNG mang
tiền tố tổ chức — tầng đó đã bị bỏ 2026-08-15, và kể cả trước đó scheme
`<org_id>_<slug>` ở file này chưa bao giờ nằm trên đường serving.
"""

import re

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def is_valid_tenant_id(s: str) -> bool:
    return bool(TENANT_RE.match(s or ""))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s[:40].rstrip("-") or "t"
```

```python
# src/noble_agent/tenant/store.py
    def _prefix(self, tenant_id: str) -> str:
        """Object-key prefix. Trước 2026-08-15 là `<org>/<tenant>` với org tách từ
        chính tenant_id — nhưng nhánh đó chỉ chạy khi `tenant_store_enabled` bật
        VÀ id đúng định dạng org, tức chưa từng có tenant thật nào đi qua."""
        return tenant_id
```

Xoá `list_orgs` và `migrate_legacy_layout` khỏi `store.py`; xoá `list_orgs` khỏi `provisioning.py`; bỏ tham số `org_id` khỏi `provision_tenant` và `list_tenants`; xoá nhánh `org_of(...)` ở `current.py:56`; xoá lệnh `tenant new-org` và cờ `--org` ở `cli.py`.

- [ ] **Step 4: Xoá hai file test đã hết nghĩa**

```bash
git rm tests/unit/tenant/test_provisioning_org.py tests/unit/tenant/test_org_isolation.py
```

Sửa `tests/unit/tenant/test_loader.py:39` — comment nhắc `org_of("noble") would raise` không còn đúng; nhánh store giờ vào được với mọi id hợp lệ.

- [ ] **Step 5: Chạy test**

```bash
uv run pytest tests/unit/tenant -v
```
Expected: PASS.

⚠ Nếu bất kỳ test nào cho thấy `_prefix` đổi làm lệch object key của một tenant đang sống, **dừng lại**: giữ nguyên `store.py` và chỉ gỡ phần định danh. Ràng buộc "đường legacy byte-identical" của plan retire-minio vẫn còn hiệu lực.

- [ ] **Step 6: Commit**

```bash
git add -A src/noble_agent/tenant tests/unit/tenant
git commit -m "refactor(tenant): xoá dead code organization"
```

---

## Self-Review

**Spec coverage** — mọi mục của spec có task:

| Spec | Task |
|---|---|
| §3.1 xoá bảng/cột | 1, 2 |
| §3.2 đổi FK, seed | 1 |
| §3.3 `created_by`, dedup, backfill | 1, 2 |
| §4 `doc_quyen` bỏ nhánh owner | 3 |
| §5.0 phiên không workspace | 4, 5 |
| §5.1 đăng ký | 6, 13 |
| §5.2 tạo workspace + membership | 7 |
| §5.3 mời người, `ROLE_NOT_FOUND` | 8 |
| §5.4 màn đầu tiên | 14 |
| §6.1 bỏ trường contract | 5, 7, 12 |
| §6.2 hai cờ, ẩn `users.tsx` | 9, 14 |
| §7 agent | 15 |
| §8 dọn comment lỗi thời | 4 |
| §9 migration | 1, 2 |
| §10 test | rải trong mọi task |
| §11 script + tài liệu | 10, 11 |

**Chưa chốt được ở thời điểm viết plan, phải xác định lúc thi công:**
- `down_revision` của Task 1 = `alembic heads` (Step 1 của chính task đó).
- Tên thật của hàm băm mật khẩu trong `core/auth/password.py` (plan gọi tạm `pw.bam`).
- Tên chính xác của các constraint bị drop ở Task 1/2 (`invites_org_user_fkey`, `roles_org_id_name_key`, `users_org_id_id_key`, …) — lấy bằng `\d+ control.<bảng>` trong psql trước khi chạy; Postgres đặt tên theo quy tắc nhưng migration cũ có thể đã đặt tên tường minh khác.
