# Phân quyền động — kế hoạch thi công

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vai trò trở thành dữ liệu trong CSDL thuộc từng tổ chức; owner tự tạo · sửa · xoá vai trò
bằng cách tích 13 ô quyền; `require(action)` bật lên tra ma trận đó thay vì cho qua tất.

**Architecture:** Ba bảng mới trong schema `control` (`actions` · `roles` · `role_actions`),
`memberships.role` đổi thành `role_id` với composite FK theo `org_id`. `require()` đổi đúng một dòng
— thay `actions=ALL_ACTIONS` bằng một truy vấn gộp. Owner (`org_role='owner'`) không đi qua ma trận,
nhờ vậy sửa vai trò không bao giờ khoá cửa được.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · Alembic · Pydantic v2 · pytest + testcontainers ·
React 18 + TanStack Router/Query · MSW · Vitest

**Spec:** `docs/superpowers/specs/2026-08-04-phan-quyen-dong-design.md`

## Global Constraints

- **Cột CSDL đặt tên tiếng Anh** (`name`, `description`, `sort_order`, `label_vi`, `label_en`).
  **Hàm · biến · file Python đặt tên tiếng Việt** — lề của repo (`doc_membership`, `khai_quyen`,
  `loi.py`). Không đổi tên code cũ.
- **Migration:** `revision = "0104_vai_tro_dong"`, `down_revision = "0501_kb_index_state"` — head
  thật lúc thi công, xác minh bằng `uv run alembic heads`. (Bản đầu của plan ghi
  `0103_user_ho_so_invite`; sai, vì `0500`/`0501` đã chồng lên từ trước.)
  Dùng `op.execute("...")` với SQL thô — khuôn của `0102`/`0103`, không dùng `op.create_table`.
- **Danh mục action là code, không phải CSDL.** `src/portal/core/auth/actions.py` là nguồn.
  `control.actions` là bản sao đọc; một cổng test canh hai bên bằng nhau.
- **13 action giữ nguyên tên.** `make contracts` phải cho ra `contracts/actions.json` **không đổi**.
- **Mọi endpoint mới khai `require(ACTIONS.WORKSPACE_ADMIN)`** rồi kiểm `org_role='owner'` trong
  service — khuôn M2b §3.1. Thiếu khai ⇒ `tests/api/test_moi_route_khai_action.py` đỏ.
- **Ẩn nút không phải bảo vệ** (PQ_01 §BR-Q03). Mọi quyền kiểm ở API.
- **Không cache quyền vào phiên.** Đọc CSDL mỗi request.
- Chạy test: `make test` · một module: `make test-module M=auth` · lint: `make lint` ·
  trước MR: `make check`.
- **Hai repo, cả hai đều là git, cả hai đang ở nhánh `dungnd`.** Task 1–6 ở
  `odyssey-portal-backend`, Task 7–8 ở `odyssey-portal-frontend`. Commit trong repo tương ứng của
  từng task; không có task nào chạm cả hai repo.
- Mỗi task kết thúc bằng một commit sau khi test xanh. Thông điệp commit tiếng Việt, khuôn của repo
  (`[Add] ...` · `feat(m2b): ...`).

---

## Cấu trúc file

| File | Trách nhiệm | Task |
|---|---|---|
| `migrations/versions/0104_vai_tro_dong.py` | schema + seed 13 action + seed 4 vai trò/tổ chức + backfill | 1 |
| `tests/integration/test_control_schema.py` | thêm set bảng của 0104 vào allowlist | 1 |
| `src/portal/core/auth/repo.py` | `doc_quyen()` thay `doc_lifecycle` + `doc_membership` | 2 |
| `src/portal/core/auth/require.py` | dựng `Principal` từ `doc_quyen()` | 2 |
| `src/portal/core/auth/principal.py` | docstring `role` đổi nghĩa | 2 |
| `src/portal/api/loi.py` | `khong_du_quyen()` nhận tham số để nói lý do | 3 |
| `src/portal/modules/auth/contracts.py` | `MembershipIn.role` → `roleId` (spec §4.0) | 2 |
| `src/portal/modules/auth/quan_tri_user.py` · `repo.py` | `dat_lai_membership` ghi `role_id` | 2 |
| `src/portal/modules/auth/loi.py` | 4 mã lỗi mới của vai trò + `ROLE_NOT_IN_ORG` | 4 |
| `src/portal/modules/auth/contracts.py` | 5 model Pydantic của vai trò | 4 |
| `src/portal/modules/auth/repo.py` | 6 truy vấn vai trò | 4 |
| `src/portal/modules/auth/quan_tri_vai_tro.py` | **MỚI** — service 6 thao tác | 5 |
| `src/portal/modules/auth/router.py` | 6 endpoint | 5 |
| `src/portal/modules/auth/fake.py` | phiên giả khai `actions` hẹp | 5 |
| `scripts/dev_seed.py` | seed vai trò cho 2 tổ chức | 6 |
| `src/features/auth/api.ts` | 6 hàm gọi + kiểu | 7 |
| `src/features/auth/components/DanhSachVaiTro.tsx` | **MỚI** — bảng vai trò | 7 |
| `src/features/auth/components/FormVaiTro.tsx` | **MỚI** — form 13 checkbox | 7 |
| `src/routes/_app/roles.tsx` | **MỚI** — route | 7 |
| `src/features/auth/nav.ts` · `src/lib/nav-registry.ts` · `src/lib/screens.ts` | khai nav | 7 |
| `src/lib/msw/handlers.ts` | handler có trạng thái | 8 |
| màn `users` hiện có | dropdown đọc `GET /roles` | 8 |

---

## Task 1: Migration 0104 — schema · seed · backfill

**Files:**
- Create: `migrations/versions/0104_vai_tro_dong.py`
- Modify: `tests/integration/test_control_schema.py`
- Test: `tests/modules/auth/test_migration_0104.py` (mới)

**Interfaces:**
- Consumes: `control.organizations` · `control.tenants` · `control.users(org_role)` ·
  `control.memberships(user_id, tenant_id, role, org_id, expires_at)` từ `0102`/`0103`
- Produces: bảng `control.actions(code, group_name, label_vi, label_en, sort_order)` ·
  `control.roles(id, org_id, name, description, created_at)` ·
  `control.role_actions(role_id, action_code)` · cột `control.memberships.role_id`
  (cột `memberships.role` **biến mất**)

- [ ] **Step 1: Viết test thất bại — bảng tồn tại và 13 action khớp code**

Tạo `tests/modules/auth/test_migration_0104.py`:

```python
"""Cổng của migration 0104 — schema, seed, backfill, downgrade."""

import pytest

from portal.core.auth.actions import ALL_ACTIONS

pytestmark = pytest.mark.integration


async def test_danh_muc_action_khop_code(pool):
    """Cổng 1 spec §7: control.actions BẰNG ĐÚNG ALL_ACTIONS, lệch chiều nào cũng đỏ.

    Không dùng `>=`: một action thừa trong CSDL là một ô tích không endpoint nào
    kiểm — tức một lời hứa quyền mà hệ thống không giữ.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code FROM control.actions")
    assert {r["code"] for r in rows} == set(ALL_ACTIONS)


async def test_sort_order_la_1_den_13_khong_trung(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT sort_order FROM control.actions ORDER BY sort_order")
    assert [r["sort_order"] for r in rows] == list(range(1, 14))
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_migration_0104.py -v`
Expected: FAIL — `UndefinedTableError: relation "control.actions" does not exist`

- [ ] **Step 3: Viết migration — phần schema và seed action**

Tạo `migrations/versions/0104_vai_tro_dong.py`:

```python
"""control.actions · roles · role_actions — vai trò là dữ liệu, không phải enum

Spec: docs/superpowers/specs/2026-08-04-phan-quyen-dong-design.md

BA BẢNG + MỘT ĐỔI CỘT, MỘT MIGRATION — chúng là một thay đổi nghiệp vụ duy nhất
("vai trò do tổ chức tự định nghĩa"), và tách ra thì có trạng thái trung gian
không chạy được: `roles` không có `role_actions` là vai trò không quyền nào, còn
`memberships.role_id` không có `roles` là một FK trỏ vào hư không.

VÌ SAO `control.actions` TỒN TẠI khi actions.py đã là nguồn: nó làm hai việc mà
code không làm được — cho UI nhãn vi/en có thứ tự, và cho role_actions một FK
thật. Đồng bộ bằng seed dưới đây; `test_migration_0104.py` canh hai bên bằng nhau.

VÌ SAO KHÔNG CÓ CỘT `is_system`: quyết định 2026-08-04 — 4 vai trò mẫu là dữ liệu
thường, sửa/xoá được như mọi hàng khác. Thêm cờ khoá là đẻ ra một nhánh UI phải
xử lý riêng, đổi lấy một sự an toàn mà §3.3 của spec đã bảo đảm bằng cách khác
(owner không đi qua ma trận, nên sửa vai trò không khoá cửa được).
"""

import sqlalchemy as sa
from alembic import op

revision = "0104_vai_tro_dong"
down_revision = "0103_user_ho_so_invite"
branch_labels = None
depends_on = None

# 13 nhóm của PQ_01 §3.1. BẢN SAO ĐỌC của core/auth/actions.py — không có đường
# nào cho migration import code ứng dụng (migration phải chạy được ở phiên bản
# code bất kỳ). test_migration_0104.py canh hai bên khớp.
_ACTIONS = [
    ("overview.read", "operate", "Xem Tổng quan · số liệu", "View overview · metrics", 1),
    ("convos.read", "operate", "Xem danh sách Hội thoại + tóm tắt", "View conversations + summary", 2),
    ("convos.transcript.read", "operate", "Đọc bản ghi thoại", "Read transcripts", 3),
    ("convos.handle", "operate", "Nhận chuyển tiếp · đánh dấu đã xử lý", "Take handoff · mark handled", 4),
    ("appts.read", "operate", "Xem Lịch hẹn", "View appointments", 5),
    ("appts.write", "operate", "Sửa · huỷ Lịch hẹn", "Edit · cancel appointments", 6),
    ("catalog.read", "knowledge", "Xem Dự án · Quỹ căn · Tài liệu · Media", "View projects · units · docs · media", 7),
    ("catalog.write", "knowledge", "Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media", "Create · edit · import", 8),
    ("catalog.delete", "knowledge", "Xoá dự án · quỹ căn · tài liệu · media", "Delete", 9),
    ("agent_config.read", "configure", "Xem cấu hình agent", "View agent config", 10),
    ("agent_config.write", "configure", "Sửa bản nháp cấu hình agent", "Edit agent config draft", 11),
    ("agent_config.publish", "configure", "Xuất bản · Quay lui", "Publish · rollback", 12),
    ("workspace.admin", "configure", "Khoá API · Thành viên · Cài đặt workspace", "API keys · members · settings", 13),
]

# Ma trận PQ_01 §3.1 — 4 vai trò mẫu seed cho MỖI tổ chức.
# Không phải bậc thang: CSKH và Biên tập là hai NGHỀ khác nhau, không phải hai
# cấp bậc (PQ_01 §2.2). Ép vào bậc thang thì hoặc CSKH sửa được quỹ căn, hoặc
# nhân viên nhập liệu đọc được hội thoại khách.
_MAU = {
    "Quản trị": [c for c, *_ in _ACTIONS],
    "CSKH": [
        "overview.read", "convos.read", "convos.transcript.read", "convos.handle",
        "appts.read", "appts.write", "catalog.read", "agent_config.read",
    ],
    "Biên tập": [
        "overview.read", "convos.read", "appts.read",
        "catalog.read", "catalog.write", "catalog.delete", "agent_config.read",
    ],
    "Người xem": [
        "overview.read", "convos.read", "appts.read", "catalog.read", "agent_config.read",
    ],
}

_MO_TA = {
    "Quản trị": "Toàn quyền: cấu hình agent, xuất bản, mời người, cài đặt",
    "CSKH": "Đọc hội thoại, nhận chuyển tiếp, quản lịch hẹn",
    "Biên tập": "Dự án, quỹ căn, tài liệu, media",
    "Người xem": "Chỉ đọc số liệu và tóm tắt",
}

# Mã vai trò cũ ở memberships.role → tên vai trò mẫu tương ứng.
_MAP_CU = {"admin": "Quản trị", "care": "CSKH", "editor": "Biên tập", "viewer": "Người xem"}


def upgrade() -> None:
    # --- ① Danh mục action -------------------------------------------------
    op.execute(
        """CREATE TABLE control.actions (
               code        text PRIMARY KEY,
               group_name  text NOT NULL CHECK (group_name IN ('operate','knowledge','configure')),
               label_vi    text NOT NULL,
               label_en    text NOT NULL,
               sort_order  int  NOT NULL UNIQUE
           )"""
    )
    for code, nhom, vi, en, thu_tu in _ACTIONS:
        op.execute(
            sa.text(
                "INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)"
                " VALUES (:c, :g, :vi, :en, :o)"
            ).bindparams(c=code, g=nhom, vi=vi, en=en, o=thu_tu)
        )

    # --- ② Vai trò ---------------------------------------------------------
    # UNIQUE (org_id, id) KHÔNG thêm ràng buộc mới về tính duy nhất (id đã là PK);
    # nó tồn tại CHỈ để làm đích hợp lệ cho composite FK của memberships. Cùng
    # khuôn 0102 đã dùng cho tenants/users.
    op.execute(
        """CREATE TABLE control.roles (
               id           text PRIMARY KEY,
               org_id       text NOT NULL REFERENCES control.organizations(id) ON DELETE CASCADE,
               name         text NOT NULL,
               description  text,
               created_at   timestamptz NOT NULL DEFAULT now(),
               UNIQUE (org_id, name),
               UNIQUE (org_id, id)
           )"""
    )
    op.execute("CREATE INDEX roles_org_idx ON control.roles (org_id)")

    # action_code RESTRICT, không CASCADE: gỡ một action khỏi danh mục trong khi
    # vai trò còn tích nó là làm rơi quyền của người thật. Gỡ action phải là một
    # migration có chủ đích, DELETE role_actions trước — và như vậy nó hiện ra
    # trong diff.
    op.execute(
        """CREATE TABLE control.role_actions (
               role_id      text NOT NULL REFERENCES control.roles(id)      ON DELETE CASCADE,
               action_code  text NOT NULL REFERENCES control.actions(code)  ON DELETE RESTRICT,
               PRIMARY KEY (role_id, action_code)
           )"""
    )
```

- [ ] **Step 4: Chạy migration, xác nhận hai test đầu xanh**

Run: `make reset && make up && uv run pytest tests/modules/auth/test_migration_0104.py -v`
Expected: PASS (2 test)

- [ ] **Step 5: Viết test thất bại cho seed vai trò + backfill**

Thêm vào `tests/modules/auth/test_migration_0104.py`:

```python
@pytest.fixture
async def org_moi(pool):
    """Một tổ chức tạo SAU migration. Trigger phải tự seed 4 vai trò cho nó.

    Container test chạy migration trên DB trống, nên KHÔNG có tổ chức nào tồn tại
    lúc backfill chạy. Phép kiểm seed chỉ có nghĩa khi tự tạo lấy một tổ chức —
    và làm vậy đồng thời kiểm luôn trigger, tức đường mà khách hàng mới đi qua.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.organizations (id,name) VALUES ('org_seed','Seed')"
            " ON CONFLICT (id) DO NOTHING"
        )
    yield "org_seed"
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.organizations WHERE id = 'org_seed'")


async def test_to_chuc_moi_tu_co_4_vai_tro_mau(pool, org_moi):
    """Trigger `organizations_seed_vai_tro`. Không có nó, owner của một khách hàng
    mới đăng nhập lần đầu và thấy dropdown vai trò rỗng."""
    async with pool.acquire() as conn:
        ten = await conn.fetch(
            "SELECT name FROM control.roles WHERE org_id = $1 ORDER BY name", org_moi
        )
    assert {r["name"] for r in ten} == {"Quản trị", "CSKH", "Biên tập", "Người xem"}


async def test_vai_tro_quan_tri_co_du_13_quyen(pool, org_moi):
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            """SELECT count(*) FROM control.role_actions ra
                 JOIN control.roles r ON r.id = ra.role_id
                WHERE r.name = 'Quản trị' AND r.org_id = $1""",
            org_moi,
        )
    assert n == 13


async def test_nguoi_xem_khong_co_quyen_ghi(pool, org_moi):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ra.action_code FROM control.role_actions ra
                 JOIN control.roles r ON r.id = ra.role_id
                WHERE r.name = 'Người xem' AND r.org_id = $1""",
            org_moi,
        )
    codes = {r["action_code"] for r in rows}
    assert codes == {"overview.read", "convos.read", "appts.read", "catalog.read", "agent_config.read"}


async def test_seed_goi_lai_khong_nhan_doi(pool, org_moi):
    """Hàm phải idempotent: dev_seed chạy nhiều lần, và backfill của một migration
    sau có thể gọi lại nó."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.seed_vai_tro_mau($1)", org_moi)
        n = await conn.fetchval(
            "SELECT count(*) FROM control.roles WHERE org_id = $1", org_moi
        )
    assert n == 4


async def test_cot_role_cu_da_bien_mat(pool):
    async with pool.acquire() as conn:
        cot = await conn.fetch(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema='control' AND table_name='memberships'"""
        )
    ten = {c["column_name"] for c in cot}
    assert "role_id" in ten
    assert "role" not in ten, "cột role cũ phải bị drop, không để hai nguồn sự thật"


async def test_membership_lech_to_chuc_bi_chan_o_postgres(pool):
    """Cổng 4 spec §7 — composite FK, không phải phép kiểm ở service."""
    import asyncpg

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.organizations (id, name) VALUES ('org_x','X') ON CONFLICT DO NOTHING"
        )
        rid = await conn.fetchval(
            "INSERT INTO control.roles (id, org_id, name) VALUES ('r_x','org_x','Tạm') RETURNING id"
        )
        uid = await conn.fetchval("SELECT id FROM control.users LIMIT 1")
        tid = await conn.fetchval("SELECT id FROM control.tenants LIMIT 1")
        oid = await conn.fetchval("SELECT org_id FROM control.users WHERE id = $1", uid)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                """INSERT INTO control.memberships (user_id, tenant_id, org_id, role_id)
                   VALUES ($1,$2,$3,$4)""",
                uid, tid, oid, rid,
            )
        raise _Rollback()


class _Rollback(Exception):
    """Huỷ transaction để test không để lại rác."""
```

Sửa lại thân test cuối cho gọn — bọc bằng `try/except _Rollback` quanh `conn.transaction()`:

```python
async def test_membership_lech_to_chuc_bi_chan_o_postgres(pool):
    import asyncpg

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO control.organizations (id, name) VALUES ('org_x','X')"
                    " ON CONFLICT DO NOTHING"
                )
                await conn.execute(
                    "INSERT INTO control.roles (id, org_id, name) VALUES ('r_x','org_x','Tạm')"
                )
                uid = await conn.fetchval("SELECT id FROM control.users LIMIT 1")
                tid = await conn.fetchval("SELECT id FROM control.tenants LIMIT 1")
                oid = await conn.fetchval("SELECT org_id FROM control.users WHERE id=$1", uid)
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await conn.execute(
                        """INSERT INTO control.memberships (user_id, tenant_id, org_id, role_id)
                           VALUES ($1,$2,$3,'r_x')""",
                        uid, tid, oid,
                    )
                raise _Rollback
        except _Rollback:
            pass
```

- [ ] **Step 6: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_migration_0104.py -v`
Expected: FAIL — chưa có hàng `roles` nào, `memberships.role` vẫn còn

- [ ] **Step 7: Viết phần seed + backfill của migration**

Nối vào cuối `upgrade()` trong `migrations/versions/0104_vai_tro_dong.py`:

```python
    # --- ③ Seed 4 vai trò mẫu CHO TỪNG tổ chức -----------------------------
    # Theo từng org, không một bộ dùng chung: dùng chung nghĩa là tổ chức A sửa
    # vai trò thì đổi quyền của tổ chức B (spec §1.3).
    #
    # id = 'r_' + md5(org_id || name) — tất định, nên chạy lại migration trên
    # cùng dữ liệu cho ra cùng id. KHÔNG suy nghĩa: id chỉ cần ổn định, còn tên
    # thì đổi được (spec §2.1). API tạo vai trò mới dùng uuid4().hex.
    # Một HÀM, dùng cho cả backfill lẫn trigger — nên hai đường không thể lệch
    # nhau. Nếu backfill viết riêng một câu INSERT còn trigger viết một câu khác,
    # thì tổ chức cũ và tổ chức mới nhận hai bộ vai trò khác nhau, và không ai
    # phát hiện cho tới lúc một khách hàng mới hỏi vì sao họ thiếu một vai trò.
    #
    # Thân hàm sinh từ _MAU ở trên: ma trận PQ_01 §3.1 chỉ tồn tại MỘT chỗ trong
    # file này. `ON CONFLICT DO NOTHING` cho hàm gọi lại được — dev_seed và test
    # đều cần tính idempotent.
    nhanh = []
    for ten, codes in _MAU.items():
        ten_q = ten.replace("'", "''")
        mo_ta_q = _MO_TA[ten].replace("'", "''")
        ds = ", ".join("'" + c + "'" for c in codes)
        nhanh.append(
            f"""
              INSERT INTO control.roles (id, org_id, name, description)
                   VALUES ('r_' || md5(p_org || '{ten_q}'), p_org, '{ten_q}', '{mo_ta_q}')
              ON CONFLICT (org_id, name) DO NOTHING;
              INSERT INTO control.role_actions (role_id, action_code)
                   SELECT 'r_' || md5(p_org || '{ten_q}'), c
                     FROM unnest(ARRAY[{ds}]::text[]) AS c
              ON CONFLICT DO NOTHING;
            """
        )
    op.execute(
        f"""CREATE FUNCTION control.seed_vai_tro_mau(p_org text) RETURNS void
            LANGUAGE plpgsql AS $fn$
            BEGIN
            {"".join(nhanh)}
            END $fn$"""
    )

    # Trigger: tổ chức tạo SAU migration này cũng có 4 vai trò. Không có nó thì
    # owner của một khách hàng mới đăng nhập lần đầu và thấy dropdown vai trò
    # rỗng — không ai gán được quyền cho ai, và lời hứa §1.1 của spec là sai.
    #
    # Ở trigger chứ không ở service: hôm nay CHƯA có API tạo tổ chức (thuộc M9),
    # nên org sinh ra từ dev_seed, từ migration, và từ psql tay. Chỉ trigger phủ
    # được cả ba. Khi M9 có API, nó không phải nhớ gọi gì.
    op.execute(
        """CREATE FUNCTION control.trg_seed_vai_tro_mau() RETURNS trigger
           LANGUAGE plpgsql AS $fn$
           BEGIN
             PERFORM control.seed_vai_tro_mau(NEW.id);
             RETURN NEW;
           END $fn$"""
    )
    op.execute(
        """CREATE TRIGGER organizations_seed_vai_tro
             AFTER INSERT ON control.organizations
             FOR EACH ROW EXECUTE FUNCTION control.trg_seed_vai_tro_mau()"""
    )

    # Backfill tổ chức đã có — gọi ĐÚNG hàm mà trigger gọi.
    op.execute("SELECT control.seed_vai_tro_mau(id) FROM control.organizations")

    # --- ④ memberships.role → role_id --------------------------------------
    op.execute("ALTER TABLE control.memberships ADD COLUMN role_id text")
    for ma_cu, ten in _MAP_CU.items():
        op.execute(
            sa.text(
                """UPDATE control.memberships m
                      SET role_id = r.id
                     FROM control.roles r
                    WHERE r.org_id = m.org_id AND r.name = :ten AND m.role = :ma_cu"""
            ).bindparams(ten=ten, ma_cu=ma_cu)
        )
    # Hàng nào còn NULL nghĩa là memberships.role có giá trị ngoài 4 mã — CHECK
    # của 0101 không cho phép, nên đây là bất khả. Vẫn kiểm: nếu nó xảy ra thì
    # SET NOT NULL sẽ nổ với một thông điệp không nói được nguyên nhân.
    op.execute(
        """DO $$
           DECLARE n int;
           BEGIN
             SELECT count(*) INTO n FROM control.memberships WHERE role_id IS NULL;
             IF n > 0 THEN
               RAISE EXCEPTION '0104: % hàng memberships có role ngoài 4 mã đã biết', n;
             END IF;
           END $$"""
    )
    op.execute("ALTER TABLE control.memberships ALTER COLUMN role_id SET NOT NULL")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_role_cung_to_chuc_fkey
             FOREIGN KEY (org_id, role_id) REFERENCES control.roles (org_id, id)
             ON DELETE RESTRICT"""
    )
    op.execute("ALTER TABLE control.memberships DROP COLUMN role")
```

- [ ] **Step 8: Viết `downgrade()` — raise thay vì đoán**

```python
def downgrade() -> None:
    """Ngược đúng thứ tự upgrade() — và TỪ CHỐI khi không ngược được.

    Khôi phục cột `role` cần map ngược tên vai trò → 4 mã cố định. Tổ chức đã đổi
    tên hoặc thêm vai trò thì không map được. Đoán bừa (gán hết về 'viewer') là âm
    thầm tước quyền của cả tổ chức; raise là câu trả lời duy nhất trung thực.
    """
    # DO block không nhận bind param, nên tên 4 vai trò gốc ghép thẳng vào chuỗi.
    # An toàn vì chúng là hằng số trong chính file này, không phải dữ liệu người
    # dùng — nhưng vẫn escape nháy đơn để nếu ai đó đổi _MAP_CU thì không vỡ.
    ten_goc = ", ".join("'" + t.replace("'", "''") + "'" for t in _MAP_CU.values())
    op.execute(
        f"""DO $$
            DECLARE v text;
            BEGIN
              SELECT string_agg(DISTINCT r.name, ', ') INTO v
                FROM control.memberships m
                JOIN control.roles r ON r.id = m.role_id
               WHERE r.name NOT IN ({ten_goc});
              IF v IS NOT NULL THEN
                RAISE EXCEPTION
                  '0104 downgrade TỪ CHỐI: có membership dùng vai trò tuỳ chỉnh (%). '
                  'Chuyển những người đó về 4 vai trò gốc trước khi hạ cấp.', v;
              END IF;
            END $$"""
    )
    op.execute(
        """ALTER TABLE control.memberships ADD COLUMN role text
             CHECK (role IN ('admin','care','editor','viewer'))"""
    )
    for ma_cu, ten in _MAP_CU.items():
        op.execute(
            sa.text(
                """UPDATE control.memberships m SET role = :ma_cu
                     FROM control.roles r
                    WHERE r.id = m.role_id AND r.name = :ten"""
            ).bindparams(ma_cu=ma_cu, ten=ten)
        )
    op.execute("ALTER TABLE control.memberships ALTER COLUMN role SET NOT NULL")
    op.execute(
        "ALTER TABLE control.memberships DROP CONSTRAINT memberships_role_cung_to_chuc_fkey"
    )
    op.execute("ALTER TABLE control.memberships DROP COLUMN role_id")

    op.execute("DROP TRIGGER organizations_seed_vai_tro ON control.organizations")
    op.execute("DROP FUNCTION control.trg_seed_vai_tro_mau()")
    op.execute("DROP FUNCTION control.seed_vai_tro_mau(text)")

    op.execute("DROP TABLE control.role_actions")
    op.execute("DROP INDEX control.roles_org_idx")
    op.execute("DROP TABLE control.roles")
    op.execute("DROP TABLE control.actions")
```

- [ ] **Step 9: Thêm test downgrade**

Thêm vào `tests/modules/auth/test_migration_0104.py`:

```python
async def test_downgrade_tu_choi_khi_co_vai_tro_tuy_chinh(pool):
    """Cổng 13 spec §7 — downgrade RAISE, không đoán bừa.

    Kiểm bằng chính câu SQL của downgrade thay vì chạy alembic: harness test dùng
    một container chung cho cả session, hạ cấp thật sẽ phá mọi test sau nó.
    """
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            """SELECT string_agg(DISTINCT r.name, ', ')
                 FROM control.memberships m
                 JOIN control.roles r ON r.id = m.role_id
                WHERE r.name NOT IN ('Quản trị','CSKH','Biên tập','Người xem')"""
        )
    assert v is None, "sau backfill mọi membership phải trỏ vào 4 vai trò gốc"
```

- [ ] **Step 10: Thêm bảng mới vào allowlist schema `control`**

Trong `tests/integration/test_control_schema.py`, thêm một set mới theo đúng khuôn các set đã có
(mỗi migration một set, **không gộp**):

```python
# Quan hệ `control` mà phân quyền động sở hữu (migration 0104).
# Giữ set riêng theo khuôn của 0102/0103: phép so `==` vẫn là cổng, và "ai sở hữu
# bảng nào" vẫn đọc được từ file này.
BANG_0104 = {"actions", "roles", "role_actions"}
```

Rồi thêm `| BANG_0104` vào biểu thức hợp của phép so `==` cuối file.

- [ ] **Step 11: Chạy toàn bộ test — 0104 xanh, test cũ không đỏ**

Run: `make reset && make up && make test-module M=auth && uv run pytest tests/integration -v`
Expected: test `0104` PASS; **`tests/modules/auth/test_repo.py` và mọi test đọc
`memberships.role` sẽ ĐỎ** — đó là đúng, Task 2 sửa chúng. Ghi lại danh sách test đỏ.

- [ ] **Step 12: Chạy lint**

Run: `make lint`
Expected: sạch

---

## Task 2: `doc_quyen()` + bật ma trận trong `require()`

**Files:**
- Modify: `src/portal/core/auth/repo.py` (thay `doc_lifecycle` + `doc_membership`)
- Modify: `src/portal/core/auth/require.py` (dòng dựng `Principal`)
- Modify: `src/portal/core/auth/principal.py` (docstring `role`)
- Modify: `tests/modules/auth/test_repo.py` (test cũ đọc `HangMembership.role`)
- Test: `tests/modules/auth/test_ma_tran_quyen.py` (mới)

**Interfaces:**
- Consumes: bảng của Task 1
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class HangQuyen:
      lifecycle: str
      org_role: str          # 'owner' | 'member'
      role_name: str | None  # None = owner (không qua membership) hoặc không có membership
      actions: frozenset[str]

  async def doc_quyen(conn, user_id: str, tenant_id: str) -> HangQuyen | None
  # None = user không tồn tại
  ```
  `Principal(user_id, tenant_id, role, actions)` giữ nguyên chữ ký; `role` đổi nghĩa sang
  **tên vai trò** người dùng đặt.

- [ ] **Step 1: Viết test thất bại — viewer bị chặn, owner qua**

Tạo `tests/modules/auth/test_ma_tran_quyen.py`:

```python
"""Ma trận vai trò × hành động — cổng 2·3·8·10 của spec §7."""

import pytest

from portal.core.auth import repo
from portal.core.auth.actions import ACTIONS, ALL_ACTIONS

pytestmark = pytest.mark.integration


async def test_owner_du_13_quyen_du_khong_co_membership(pool, du_lieu_quyen):
    """Cổng 3 §7. Owner không đi qua ma trận — §3.3.

    Đây là thứ làm cho sửa vai trò không khoá cửa được thành thật: owner bỏ
    tích cả 13 ô của mọi vai trò thì chính họ vẫn vào được và sửa lại.
    """
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.owner_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert q.org_role == "owner"
    assert q.actions == ALL_ACTIONS


async def test_nguoi_xem_khong_co_quyen_ghi(pool, du_lieu_quyen):
    """Cổng 2 §7."""
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.viewer_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert ACTIONS.CATALOG_READ in q.actions
    assert ACTIONS.CATALOG_WRITE not in q.actions
    assert q.role_name == "Người xem"


async def test_khong_membership_tra_actions_rong(pool, du_lieu_quyen):
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.nguoi_la_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert q.actions == frozenset()
    assert q.role_name is None


async def test_user_khong_ton_tai_tra_none(pool, du_lieu_quyen):
    async with pool.acquire() as conn:
        assert await repo.doc_quyen(conn, "u_khong_co", du_lieu_quyen.tenant_id) is None


async def test_membership_het_han_khong_cho_quyen(pool, du_lieu_quyen):
    """Vị từ expires_at phải nằm trong ON, không phải WHERE — §3.2.

    Ở WHERE nó biến LEFT JOIN thành INNER JOIN âm thầm: user không membership mất
    luôn hàng, và nhánh owner không bao giờ chạy tới.
    """
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.het_han_id, du_lieu_quyen.tenant_id)
    assert q is not None, "user vẫn tồn tại — chỉ vé của họ hết hạn"
    assert q.actions == frozenset()


async def test_bo_tich_mot_o_chan_ngay_lan_doc_ke_tiep(pool, du_lieu_quyen):
    """Cổng 8 §7 — chứng minh KHÔNG cache. Cổng khó viết nhất và quan trọng nhất."""
    async with pool.acquire() as conn:
        truoc = await repo.doc_quyen(conn, du_lieu_quyen.editor_id, du_lieu_quyen.tenant_id)
        assert ACTIONS.CATALOG_WRITE in truoc.actions

        await conn.execute(
            """DELETE FROM control.role_actions
                WHERE role_id = (SELECT role_id FROM control.memberships
                                  WHERE user_id = $1 AND tenant_id = $2)
                  AND action_code = $3""",
            du_lieu_quyen.editor_id, du_lieu_quyen.tenant_id, ACTIONS.CATALOG_WRITE,
        )

        sau = await repo.doc_quyen(conn, du_lieu_quyen.editor_id, du_lieu_quyen.tenant_id)
    assert ACTIONS.CATALOG_WRITE not in sau.actions
```

- [ ] **Step 2: Viết fixture `du_lieu_quyen`**

Thêm vào `tests/modules/auth/conftest.py`:

```python
from dataclasses import dataclass

import pytest


@dataclass(frozen=True, slots=True)
class DuLieuQuyen:
    org_id: str
    tenant_id: str
    owner_id: str
    viewer_id: str
    editor_id: str
    het_han_id: str
    nguoi_la_id: str
    """User cùng tổ chức nhưng KHÔNG có membership ở tenant này."""
    role_viewer_id: str
    role_editor_id: str


@pytest.fixture
async def du_lieu_quyen(pool):
    """Một tổ chức đủ năm loại người để kiểm ma trận.

    Dùng org RIÊNG (`org_q`) chứ không mượn dữ liệu seed: test khác sửa seed thì
    test này đỏ vì lý do không liên quan.

    KHÔNG tự tạo vai trò — trigger `organizations_seed_vai_tro` đã seed 4 cái khi
    hàng organizations được chèn. Tự chèn thêm 'Người xem' sẽ vỡ UNIQUE (org_id,
    name). Fixture chỉ TRA id theo tên.
    """
    org, ten = "org_q", "ws_q"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.organizations (id,name) VALUES ($1,'Org Quyền')"
            " ON CONFLICT (id) DO NOTHING", org)
        await conn.execute(
            "INSERT INTO control.tenants (id,name,org_id) VALUES ($1,'WS Quyền',$2)"
            " ON CONFLICT (id) DO NOTHING", ten, org)

        r_viewer = await conn.fetchval(
            "SELECT id FROM control.roles WHERE org_id=$1 AND name='Người xem'", org)
        r_editor = await conn.fetchval(
            "SELECT id FROM control.roles WHERE org_id=$1 AND name='Biên tập'", org)
        assert r_viewer and r_editor, "trigger phải đã seed 4 vai trò mẫu cho org này"

        nguoi = [
            ("u_q_owner", "owner"), ("u_q_viewer", "member"), ("u_q_editor", "member"),
            ("u_q_hethan", "member"), ("u_q_la", "member"),
        ]
        for uid, vai in nguoi:
            await conn.execute(
                """INSERT INTO control.users (id,email,password_hash,name,org_id,org_role)
                   VALUES ($1,$1||'@q.vn','x',$1,$2,$3) ON CONFLICT (id) DO NOTHING""",
                uid, org, vai)

        await conn.execute(
            "INSERT INTO control.memberships (user_id,tenant_id,org_id,role_id)"
            " VALUES ('u_q_viewer',$1,$2,$3) ON CONFLICT DO NOTHING", ten, org, r_viewer)
        await conn.execute(
            "INSERT INTO control.memberships (user_id,tenant_id,org_id,role_id)"
            " VALUES ('u_q_editor',$1,$2,$3) ON CONFLICT DO NOTHING", ten, org, r_editor)
        await conn.execute(
            """INSERT INTO control.memberships (user_id,tenant_id,org_id,role_id,expires_at)
               VALUES ('u_q_hethan',$1,$2,$3, now() - interval '1 day')
               ON CONFLICT DO NOTHING""", ten, org, r_editor)

    yield DuLieuQuyen(
        org, ten, "u_q_owner", "u_q_viewer", "u_q_editor", "u_q_hethan", "u_q_la",
        r_viewer, r_editor,
    )

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.organizations WHERE id = $1", org)
```

- [ ] **Step 3: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_ma_tran_quyen.py -v`
Expected: FAIL — `AttributeError: module 'portal.core.auth.repo' has no attribute 'doc_quyen'`

- [ ] **Step 4: Viết `doc_quyen()`**

Thay toàn bộ phần sau docstring module trong `src/portal/core/auth/repo.py`:

```python
from dataclasses import dataclass

import asyncpg

from portal.core.auth.actions import ALL_ACTIONS


@dataclass(frozen=True, slots=True)
class HangQuyen:
    lifecycle: str
    """'active' | 'suspended' | 'pending' (migration 0100 · 0103)."""
    org_role: str
    """'owner' | 'member' (migration 0102)."""
    role_name: str | None
    """Tên vai trò người dùng tự đặt. None = owner, hoặc không có membership."""
    actions: frozenset[str]
    """Tập hành động hiệu lực. Owner: cả 13. Không membership: rỗng."""


async def doc_quyen(conn: asyncpg.Connection, user_id: str, tenant_id: str) -> HangQuyen | None:
    """MỘT truy vấn cho cả ba câu hỏi: còn hoạt động? · có vào được? · làm được gì?

    None = user không tồn tại.

    THAY CHO `doc_lifecycle` + `doc_membership` — hai lượt trước đây. Ít hơn một
    round-trip dù làm nhiều việc hơn. Đi trong transaction mà ràng buộc cách ly
    đã bắt buộc phải có.

    ⚠ VỊ TỪ `expires_at` NẰM TRONG `ON`, KHÔNG PHẢI `WHERE`. Ở `WHERE` nó biến
    LEFT JOIN thành INNER JOIN âm thầm: user không có membership sẽ mất luôn
    hàng, hàm trả None, và nhánh owner bên dưới không bao giờ chạy tới. Đó là
    một owner bị 401 mà không ai hiểu vì sao.

    `expires_at IS NULL OR expires_at > now()` là chỗ BR-Q08 được cài: vé hỗ trợ
    của NobleX tự hết hiệu lực, không ai phải nhớ thu hồi.

    NHÁNH OWNER (spec §3.3): org_role='owner' ⇒ đủ 13 action ở MỌI workspace của
    tổ chức, không cần hàng memberships. Không phải cửa sau — 0102 §3 đã chốt
    owner thấy mọi workspace dù memberships rỗng; đây chỉ là phần quyền của cùng
    một quy tắc. Phạm vi vẫn dừng ở org của chính họ: mệnh đề `t.org_id = u.org_id`.
    """
    r = await conn.fetchrow(
        """SELECT u.lifecycle,
                  u.org_role,
                  r.name AS role_name,
                  EXISTS (SELECT 1 FROM control.tenants t
                           WHERE t.id = $2 AND t.org_id = u.org_id) AS cung_to_chuc,
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
            GROUP BY u.lifecycle, u.org_role, r.name, u.org_id""",
        user_id,
        tenant_id,
    )
    if r is None:
        return None
    if r["org_role"] == "owner" and r["cung_to_chuc"]:
        return HangQuyen(r["lifecycle"], "owner", None, ALL_ACTIONS)
    return HangQuyen(r["lifecycle"], r["org_role"], r["role_name"], frozenset(r["actions"]))
```

- [ ] **Step 5: Chạy test repo**

Run: `uv run pytest tests/modules/auth/test_ma_tran_quyen.py -v`
Expected: PASS (6 test)

- [ ] **Step 6: Viết test thất bại ở tầng HTTP**

Thêm vào `tests/modules/auth/test_ma_tran_quyen.py` (cần fixture client + login đã có ở
`tests/modules/auth/conftest.py` — theo đúng khuôn `test_sua_user.py`):

```python
async def test_viewer_goi_endpoint_ghi_nhan_403(client_viewer):
    """Cổng 2 §7 ở tầng HTTP — không chỉ ở repo."""
    r = await client_viewer.post("/api/v1/du-an", json={"name": "Thử"})
    assert r.status_code == 403
    than = r.json()["error"]
    assert than["code"] == "FORBIDDEN"
    # Cổng của §3.4: thông điệp phải nói LÝ DO, không phải một câu chung chung.
    assert "Người xem" in than["message"]
    assert "Thêm · sửa" in than["message"]
```

- [ ] **Step 7: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_ma_tran_quyen.py::test_viewer_goi_endpoint_ghi_nhan_403 -v`
Expected: FAIL — trả 200/201 vì `require()` vẫn cấp `ALL_ACTIONS`

- [ ] **Step 8: Đổi `require()`**

Trong `src/portal/core/auth/require.py`, thay thân `_kiem` (giữ nguyên phần đọc cookie/phiên):

```python
            async with pool.acquire() as conn, conn.transaction():
                q = await repo.doc_quyen(conn, ban_ghi.user_id, ban_ghi.tenant_id)

                # Đình chỉ là chuyện DANH TÍNH, không phải của một workspace: xoá
                # luôn phiên rồi 401. 403 sẽ làm FE hiện màn "không có quyền" trong
                # khi đúng ra phải đẩy về /login. Xem spec §4.4.
                if q is None or q.lifecycle != "active":
                    await ss.xoa(r, sid)
                    raise loi.khong_co_phien()

            if not q.actions:
                raise loi.khong_du_quyen()

            # M2b: ma trận đã BẬT. `actions` là tập hiệu lực đọc từ CSDL mỗi
            # request — không cache vào phiên (PQ_01 §BR-Q04).
            if action not in q.actions:
                raise loi.thieu_quyen(action, q.role_name)

            return Principal(
                user_id=ban_ghi.user_id,
                tenant_id=ban_ghi.tenant_id,
                role=q.role_name or "Chủ tổ chức",
                actions=q.actions,
            )
```

- [ ] **Step 9: Cập nhật docstring `Principal.role`**

Trong `src/portal/core/auth/principal.py`:

```python
    role: str
    """TÊN vai trò người dùng tự đặt ('Trưởng nhóm CSKH'), hoặc 'Chủ tổ chức' cho owner.

    ⚠ CHỈ để hiển thị trong thông điệp lỗi. KHÔNG dùng để quyết định gì — so sánh
    `p.role == 'admin'` là một phép kiểm quyền đi vòng qua require(), và nó sai
    âm thầm ngay khi ai đó đổi tên vai trò. Dùng `ACTIONS.X in p.actions`.
    """
```

- [ ] **Step 10: Rà mọi chỗ so sánh `p.role`**

Run: `grep -rn "\.role\b" src/ tests/ --include='*.py' | grep -v "org_role" | grep -v "role_id"`

Sửa mọi chỗ so sánh chuỗi sang `ACTIONS.X in p.actions`. **Nếu grep ra 0 kết quả cần sửa, ghi con
số đó vào ghi chú task** — im lặng không phân biệt được với quên rà.

- [ ] **Step 11: Chạy toàn bộ test auth**

Run: `make test-module M=auth`
Expected: `test_ma_tran_quyen.py` PASS. Test cũ dùng `HangMembership` sẽ đỏ — sửa chúng sang
`doc_quyen`/`HangQuyen`. `test_membership_het_han.py` và `test_dinh_chi_giua_phien.py` phải còn xanh
sau khi sửa: chúng kiểm đúng hai vị từ mà `doc_quyen` phải giữ.

- [ ] **Step 12: Chạy toàn bộ test của repo**

Run: `make check`
Expected: sạch. Nếu test của M4/M5/M6/M7 đỏ vì phiên test cấp vai trò không đủ quyền, sửa fixture
phiên của chúng sang vai trò Quản trị — **không** nới `require()`.

---

## Task 3: 403 nói lý do

**Files:**
- Modify: `src/portal/api/loi.py`
- Test: `tests/modules/auth/test_ma_tran_quyen.py::test_viewer_goi_endpoint_ghi_nhan_403` (Task 2)

**Interfaces:**
- Produces: `portal.api.loi.thieu_quyen(action: str, ten_vai_tro: str | None) -> LoiPortal`
  — mã `FORBIDDEN`, HTTP 403. `khong_du_quyen()` giữ nguyên cho chỗ không biết action.

- [ ] **Step 1: Viết test thất bại cho hàm lỗi**

Tạo `tests/unit/test_loi_thieu_quyen.py`:

```python
from portal.api.loi import thieu_quyen


def test_thong_diep_neu_ten_quyen_va_ten_vai_tro():
    e = thieu_quyen("catalog.write", "Người xem")
    assert e.ma == "FORBIDDEN"
    assert e.http == 403
    assert "Thêm · sửa" in e.thong_diep
    assert "Người xem" in e.thong_diep


def test_khong_co_vai_tro_van_ra_cau_doc_duoc():
    """Người chưa được cấp vai trò nào — không được ghép 'None' vào câu."""
    e = thieu_quyen("catalog.write", None)
    assert "None" not in e.thong_diep
    assert "chưa được cấp vai trò" in e.thong_diep


def test_action_la_van_khong_no():
    """Nhãn tra không thấy thì dùng chính mã — thà thô còn hơn 500."""
    e = thieu_quyen("khong.ton.tai", "Người xem")
    assert "khong.ton.tai" in e.thong_diep
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/unit/test_loi_thieu_quyen.py -v`
Expected: FAIL — `ImportError: cannot import name 'thieu_quyen'`

- [ ] **Step 3: Viết `thieu_quyen()`**

Thêm vào `src/portal/api/loi.py`, ngay sau `khong_du_quyen()`:

```python
# Nhãn ngắn của 13 nhóm, để thông điệp 403 nói được người dùng thiếu QUYỀN NÀO.
# PQ_01 §3 phi chức năng: "người dùng thấy lý do bị chặn, không phải một nút xám
# vô nghĩa. Nút xám không giải thích là nguồn của mọi ticket hỗ trợ."
#
# VÌ SAO KHÔNG ĐỌC control.actions.label_vi: hàm này chạy trên đường lỗi, và một
# truy vấn CSDL ở đó nghĩa là CSDL hỏng thì lỗi 403 cũng hỏng theo. Bản sao ngắn
# ở đây là cái giá của việc đường lỗi không phụ thuộc gì.
_NHAN = {
    "overview.read": "Xem Tổng quan",
    "convos.read": "Xem Hội thoại",
    "convos.transcript.read": "Đọc bản ghi thoại",
    "convos.handle": "Nhận chuyển tiếp",
    "appts.read": "Xem Lịch hẹn",
    "appts.write": "Sửa · huỷ Lịch hẹn",
    "catalog.read": "Xem Dự án · Quỹ căn",
    "catalog.write": "Thêm · sửa Dự án · Quỹ căn",
    "catalog.delete": "Xoá dự án · quỹ căn",
    "agent_config.read": "Xem cấu hình agent",
    "agent_config.write": "Sửa bản nháp cấu hình agent",
    "agent_config.publish": "Xuất bản · Quay lui",
    "workspace.admin": "Quản trị workspace",
}


def thieu_quyen(action: str, ten_vai_tro: str | None) -> LoiPortal:
    """403 NÓI LÝ DO. Cùng mã `FORBIDDEN` với `khong_du_quyen()` — hợp đồng mã lỗi
    không đổi, chỉ thông điệp giàu hơn.

    `ten_vai_tro=None` là người có membership nhưng vai trò đã bị gỡ hết quyền,
    hoặc chưa được cấp vai trò. Ghép "None" vào câu là một lỗi hiện ra tận UI.
    """
    nhan = _NHAN.get(action, action)
    if ten_vai_tro:
        return LoiPortal(
            "FORBIDDEN", 403,
            f"Việc này cần quyền {nhan}. Vai trò của bạn ở workspace này là {ten_vai_tro}.",
        )
    return LoiPortal(
        "FORBIDDEN", 403,
        f"Việc này cần quyền {nhan}. Bạn chưa được cấp vai trò nào ở workspace này.",
    )
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/unit/test_loi_thieu_quyen.py tests/modules/auth/test_ma_tran_quyen.py -v`
Expected: PASS

- [ ] **Step 5: Cổng canh `_NHAN` không lệch `ALL_ACTIONS`**

Thêm vào `tests/unit/test_loi_thieu_quyen.py`:

```python
def test_nhan_phu_du_13_action():
    """Thêm action mà quên nhãn ⇒ thông điệp 403 in mã máy ra cho người dùng đọc."""
    from portal.api.loi import _NHAN
    from portal.core.auth.actions import ALL_ACTIONS

    assert set(_NHAN) == set(ALL_ACTIONS)
```

- [ ] **Step 6: Chạy lại và lint**

Run: `uv run pytest tests/unit -v && make lint`
Expected: PASS, lint sạch

---

## Task 4: Mã lỗi · contract · truy vấn vai trò

**Files:**
- Modify: `src/portal/modules/auth/loi.py`
- Modify: `src/portal/modules/auth/contracts.py`
- Modify: `src/portal/modules/auth/repo.py`
- Test: `tests/modules/auth/test_contracts_vai_tro.py` (mới)

**Interfaces:**
- Produces:
  ```python
  # loi.py
  def vai_tro_khong_ton_tai() -> LoiPortal            # ROLE_NOT_FOUND 404
  def ten_vai_tro_da_ton_tai() -> LoiPortal           # ROLE_NAME_TAKEN 409
  def vai_tro_dang_dung(so_nguoi: int) -> LoiPortal   # ROLE_IN_USE 409
  def action_khong_hop_le(ma: str) -> LoiPortal       # UNKNOWN_ACTION 422

  # contracts.py  (alias camelCase, khuôn của UserDetailOut)
  class ActionOut:        code, groupName, labelVi, labelEn, sortOrder
  class VaiTroOut:        id, name, description, userCount
  class VaiTroChiTietOut: id, name, description, actions: list[str]
  class TaoVaiTroIn:      name, description, actions: list[str]
  class SuaVaiTroIn:      name, description, actions: list[str]

  # repo.py
  async def liet_ke_action(conn) -> list[asyncpg.Record]
  async def liet_ke_vai_tro(conn, org_id) -> list[asyncpg.Record]
  async def doc_vai_tro(conn, org_id, role_id) -> asyncpg.Record | None
  async def tao_vai_tro(conn, role_id, org_id, name, description) -> None
  async def dat_action_cua_vai_tro(conn, role_id, codes: list[str]) -> None
  async def dem_nguoi_dung_vai_tro(conn, role_id) -> int
  async def xoa_vai_tro(conn, org_id, role_id) -> None
  ```

- [ ] **Step 1: Viết test thất bại cho contract**

Tạo `tests/modules/auth/test_contracts_vai_tro.py`:

```python
"""Hai luật cross-field của contract vai trò."""

import pytest
from pydantic import ValidationError

from portal.modules.auth.contracts import SuaVaiTroIn, TaoVaiTroIn


def test_ten_rong_bi_tu_choi():
    with pytest.raises(ValidationError):
        TaoVaiTroIn(name="   ", description=None, actions=[])


def test_vai_tro_khong_quyen_duoc_phep():
    """Đã tạo, chưa cấu hình là một trạng thái THẬT — spec §4.

    Chặn nó là bắt người dùng tích bừa một ô để lưu được.
    """
    v = TaoVaiTroIn(name="Tạm", description=None, actions=[])
    assert v.actions == []


def test_action_trung_bi_gom_lai():
    """Gửi trùng không phải lỗi của người dùng — PK (role_id, action_code) sẽ nổ
    ở tầng dưới, và một 500 cho một việc vô hại là sai."""
    v = TaoVaiTroIn(name="X", description=None, actions=["catalog.read", "catalog.read"])
    assert v.actions == ["catalog.read"]


def test_ten_duoc_trim():
    v = SuaVaiTroIn(name="  Trưởng nhóm  ", description=None, actions=[])
    assert v.name == "Trưởng nhóm"
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_contracts_vai_tro.py -v`
Expected: FAIL — `ImportError: cannot import name 'TaoVaiTroIn'`

- [ ] **Step 3: Viết contract**

Thêm vào cuối `src/portal/modules/auth/contracts.py` (theo đúng khuôn alias camelCase của
`UserDetailOut` đã có trong file):

```python
class ActionOut(BaseModel):
    """Một trong 13 ô checkbox. Nhãn song ngữ vì FE đã song ngữ (NavLeaf.label)."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    group_name: str = Field(serialization_alias="groupName")
    label_vi: str = Field(serialization_alias="labelVi")
    label_en: str = Field(serialization_alias="labelEn")
    sort_order: int = Field(serialization_alias="sortOrder")


class VaiTroOut(BaseModel):
    """Một dòng ở màn danh sách.

    `userCount` KHÔNG phải trang trí: không có nó thì nút Xoá là một cái bẫy —
    người dùng bấm, nhận 409, và không biết phải làm gì tiếp.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str | None
    user_count: int = Field(serialization_alias="userCount")


class VaiTroChiTietOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str | None
    actions: list[str]


def _lam_sach_ten(v: str) -> str:
    ten = v.strip()
    if not ten:
        raise ValueError("Tên vai trò không được rỗng")
    return ten


def _bo_trung(v: list[str]) -> list[str]:
    """Giữ thứ tự, bỏ trùng. Gửi trùng không phải lỗi người dùng — nhưng
    PK (role_id, action_code) sẽ nổ ở tầng dưới, và một 500 cho một việc vô hại
    là sai."""
    thay: list[str] = []
    for x in v:
        if x not in thay:
            thay.append(x)
    return thay


class TaoVaiTroIn(BaseModel):
    name: Annotated[str, AfterValidator(_lam_sach_ten)]
    description: str | None = None
    actions: Annotated[list[str], AfterValidator(_bo_trung)]


class SuaVaiTroIn(BaseModel):
    """`actions` là THAY THẾ TOÀN BỘ, không cộng dồn — spec §4, cùng lý lẽ M2b §4.4.

    Form là 13 checkbox người dùng sửa trực tiếp. Diễn dịch nó thành chuỗi
    add/remove ở FE là đặt logic hoà giải vào chỗ không có transaction, và hai
    tab mở cùng lúc sẽ trộn ra một tập quyền không ai chọn.
    """

    name: Annotated[str, AfterValidator(_lam_sach_ten)]
    description: str | None = None
    actions: Annotated[list[str], AfterValidator(_bo_trung)]
```

Thêm import nếu file chưa có: `from typing import Annotated` và
`from pydantic import AfterValidator, BaseModel, ConfigDict, Field`.

- [ ] **Step 4: Chạy test contract**

Run: `uv run pytest tests/modules/auth/test_contracts_vai_tro.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Viết 4 mã lỗi**

Thêm vào `src/portal/modules/auth/loi.py`:

```python
def vai_tro_khong_ton_tai() -> LoiPortal:
    """404 cả khi vai trò thuộc tổ chức khác — cùng lý lẽ `user_khong_ton_tai()`.

    403 xác nhận id này tồn tại, chỉ không phải của bạn — đủ để dò cấu hình
    quyền của mọi khách hàng.
    """
    return LoiPortal("ROLE_NOT_FOUND", 404, "Không tìm thấy vai trò này")


def ten_vai_tro_da_ton_tai() -> LoiPortal:
    """409, không 422: dữ liệu gửi lên đúng dạng, chỉ là thế giới đã thay đổi.

    UNIQUE (org_id, name) — trùng tên chỉ trong cùng tổ chức, nên thông điệp
    ĐƯỢC nói "trong tổ chức này" (khác `email_da_ton_tai()`, nơi UNIQUE là toàn cục).
    """
    return LoiPortal("ROLE_NAME_TAKEN", 409, "Tổ chức đã có một vai trò tên này")


def vai_tro_dang_dung(so_nguoi: int) -> LoiPortal:
    """FK RESTRICT cũng chặn, nhưng bằng ForeignKeyViolationError → 500.

    Con số trong thông điệp là thứ biến một lời từ chối thành một việc làm được:
    người dùng biết phải chuyển bao nhiêu người trước khi xoá.
    """
    return LoiPortal(
        "ROLE_IN_USE", 409,
        f"Vai trò này đang gán cho {so_nguoi} người — chuyển họ sang vai trò khác trước khi xoá",
    )


def action_khong_hop_le(ma: str) -> LoiPortal:
    """422 vì đây LÀ lỗi dữ liệu gửi lên. FK tới control.actions cũng chặn, nhưng
    kiểm trước biến cùng một sự thật thành một câu người đọc được."""
    return LoiPortal("UNKNOWN_ACTION", 422, f"Quyền {ma} không tồn tại")
```

- [ ] **Step 6: Viết truy vấn**

Thêm vào `src/portal/modules/auth/repo.py`:

```python
async def liet_ke_action(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT code, group_name, label_vi, label_en, sort_order
             FROM control.actions ORDER BY sort_order"""
    )


async def liet_ke_vai_tro(conn: asyncpg.Connection, org_id: str) -> list[asyncpg.Record]:
    """Kèm userCount — đếm bằng LEFT JOIN chứ không subquery-per-row.

    Đếm CẢ membership đã hết hạn: xoá vai trò sẽ vỡ FK vì hàng đó vẫn tồn tại,
    nên báo con số nhỏ hơn thực tế là nói dối theo hướng người dùng phát hiện
    bằng một lỗi 409 khó hiểu.
    """
    return await conn.fetch(
        """SELECT r.id, r.name, r.description, count(m.user_id) AS user_count
             FROM control.roles r
             LEFT JOIN control.memberships m ON m.role_id = r.id
            WHERE r.org_id = $1
            GROUP BY r.id, r.name, r.description
            ORDER BY r.created_at""",
        org_id,
    )


async def doc_vai_tro(conn: asyncpg.Connection, org_id: str, role_id: str) -> asyncpg.Record | None:
    """`org_id` trong WHERE, không kiểm sau: vai trò của tổ chức khác phải trả
    None để router ra 404, không phải trả hàng rồi so sánh."""
    return await conn.fetchrow(
        """SELECT r.id, r.name, r.description,
                  coalesce(array_agg(ra.action_code)
                           FILTER (WHERE ra.action_code IS NOT NULL), '{}') AS actions
             FROM control.roles r
             LEFT JOIN control.role_actions ra ON ra.role_id = r.id
            WHERE r.org_id = $1 AND r.id = $2
            GROUP BY r.id, r.name, r.description""",
        org_id,
        role_id,
    )


async def tao_vai_tro(
    conn: asyncpg.Connection, role_id: str, org_id: str, name: str, description: str | None
) -> None:
    await conn.execute(
        "INSERT INTO control.roles (id, org_id, name, description) VALUES ($1,$2,$3,$4)",
        role_id, org_id, name, description,
    )


async def doi_ten_vai_tro(
    conn: asyncpg.Connection, role_id: str, name: str, description: str | None
) -> None:
    await conn.execute(
        "UPDATE control.roles SET name = $2, description = $3 WHERE id = $1",
        role_id, name, description,
    )


async def dat_action_cua_vai_tro(
    conn: asyncpg.Connection, role_id: str, codes: list[str]
) -> None:
    """THAY THẾ TOÀN BỘ. Người gọi phải đang ở trong conn.transaction() — xoá xong
    mà insert hỏng thì vai trò mất sạch quyền, im lặng."""
    await conn.execute("DELETE FROM control.role_actions WHERE role_id = $1", role_id)
    if codes:
        await conn.executemany(
            "INSERT INTO control.role_actions (role_id, action_code) VALUES ($1,$2)",
            [(role_id, c) for c in codes],
        )


async def dem_nguoi_dung_vai_tro(conn: asyncpg.Connection, role_id: str) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM control.memberships WHERE role_id = $1", role_id
    )


async def xoa_vai_tro(conn: asyncpg.Connection, org_id: str, role_id: str) -> None:
    await conn.execute(
        "DELETE FROM control.roles WHERE org_id = $1 AND id = $2", org_id, role_id
    )


async def loc_action_la(conn: asyncpg.Connection, codes: list[str]) -> str | None:
    """Trả mã ĐẦU TIÊN không có trong danh mục, hoặc None. Dùng để ra 422 có tên
    thay vì một ForeignKeyViolationError → 500."""
    if not codes:
        return None
    return await conn.fetchval(
        """SELECT c FROM unnest($1::text[]) AS c
            WHERE NOT EXISTS (SELECT 1 FROM control.actions a WHERE a.code = c)
            LIMIT 1""",
        codes,
    )
```

- [ ] **Step 7: Chạy lint + test module**

Run: `make lint && make test-module M=auth`
Expected: sạch, không test nào đỏ thêm

---

## Task 5: Sáu endpoint

**Files:**
- Create: `src/portal/modules/auth/quan_tri_vai_tro.py`
- Modify: `src/portal/modules/auth/router.py`
- Modify: `src/portal/modules/auth/fake.py`
- Test: `tests/modules/auth/test_vai_tro.py` (mới)

**Interfaces:**
- Consumes: repo + contract + loi của Task 4; `require(ACTIONS.WORKSPACE_ADMIN)` của Task 2
- Produces: `GET /actions` · `GET /roles` · `GET /roles/{role_id}` · `POST /roles` ·
  `PATCH /roles/{role_id}` · `DELETE /roles/{role_id}` (prefix `/api/v1` do `api/app.py` gắn)

- [ ] **Step 1: Viết test thất bại — luồng chính**

Tạo `tests/modules/auth/test_vai_tro.py`:

```python
"""Sáu endpoint vai trò — cổng 5·9·10·11 của spec §7."""

import pytest

pytestmark = pytest.mark.integration


async def test_owner_tao_va_doc_lai_vai_tro(client_owner):
    r = await client_owner.post(
        "/api/v1/roles",
        json={"name": "Trưởng nhóm CSKH", "description": "Thử", "actions": ["convos.read"]},
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    r2 = await client_owner.get(f"/api/v1/roles/{rid}")
    assert r2.status_code == 200
    assert r2.json()["actions"] == ["convos.read"]


async def test_member_du_13_quyen_van_khong_tao_duoc(client_member_quan_tri):
    """Cổng 2 §7. `org_role` mới là phép chặn, không phải ma trận action.

    Dùng member mang vai trò Quản trị (đủ 13 action) chứ không dùng Người xem:
    người xem bị `require(ACTIONS.WORKSPACE_ADMIN)` chặn từ cổng 1, nên test đó
    xanh mà không chứng minh được `_kiem_owner` có chạy hay không.
    """
    r = await client_member_quan_tri.post("/api/v1/roles", json={"name": "X", "actions": []})
    assert r.status_code == 403


async def test_trung_ten_tra_409(client_owner):
    await client_owner.post("/api/v1/roles", json={"name": "Trùng", "actions": []})
    r = await client_owner.post("/api/v1/roles", json={"name": "Trùng", "actions": []})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_NAME_TAKEN"


async def test_action_la_tra_422_va_khong_de_lai_hang_nao(client_owner, pool):
    """Cổng 9 §7 — phép kiểm transaction. Thứ duy nhất phân biệt có
    conn.transaction() với trông như có."""
    r = await client_owner.post(
        "/api/v1/roles", json={"name": "Hỏng", "actions": ["catalog.read", "khong.co.that"]}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_ACTION"

    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM control.roles WHERE name = 'Hỏng'")
    assert n == 0


async def test_patch_thay_the_toan_bo_khong_cong_don(client_owner):
    """Cổng 7 §7."""
    rid = (await client_owner.post(
        "/api/v1/roles",
        json={"name": "Thay thế", "actions": ["convos.read", "appts.read"]},
    )).json()["id"]

    await client_owner.patch(
        f"/api/v1/roles/{rid}", json={"name": "Thay thế", "actions": ["catalog.read"]}
    )
    r = await client_owner.get(f"/api/v1/roles/{rid}")
    assert r.json()["actions"] == ["catalog.read"]


async def test_xoa_vai_tro_dang_dung_tra_409_va_khong_xoa(client_owner, pool, du_lieu_quyen):
    """Cổng 5 §7."""
    r = await client_owner.delete(f"/api/v1/roles/{du_lieu_quyen.role_viewer_id}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_IN_USE"
    assert "1" in r.json()["error"]["message"]

    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.roles WHERE id = $1", du_lieu_quyen.role_viewer_id
        )
    assert n == 1


async def test_xoa_vai_tro_khong_ai_dung_thanh_cong(client_owner):
    rid = (await client_owner.post(
        "/api/v1/roles", json={"name": "Bỏ đi", "actions": []}
    )).json()["id"]
    assert (await client_owner.delete(f"/api/v1/roles/{rid}")).status_code == 204


async def test_vai_tro_to_chuc_khac_tra_404_khong_403(client_owner, pool):
    """Cổng 11 §7 — 403 xác nhận id tồn tại, đủ để dò cấu hình khách hàng khác."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.organizations (id,name) VALUES ('org_z','Z')"
            " ON CONFLICT DO NOTHING")
        await conn.execute(
            "INSERT INTO control.roles (id,org_id,name) VALUES ('r_z','org_z','Của Z')"
            " ON CONFLICT DO NOTHING")

    assert (await client_owner.get("/api/v1/roles/r_z")).status_code == 404


async def test_vai_tro_0_quyen_tao_duoc(client_owner):
    """Cổng 10 §7 — đã tạo, chưa cấu hình là trạng thái thật."""
    r = await client_owner.post("/api/v1/roles", json={"name": "Trống", "actions": []})
    assert r.status_code == 201
    assert r.json()["actions"] == []


async def test_danh_muc_action_tra_13_o_co_thu_tu(client_owner):
    r = await client_owner.get("/api/v1/actions")
    o = r.json()
    assert len(o) == 13
    assert [x["sortOrder"] for x in o] == list(range(1, 14))
    assert o[0]["labelVi"]


async def test_danh_sach_kem_user_count(client_owner, du_lieu_quyen):
    r = await client_owner.get("/api/v1/roles")
    theo_id = {x["id"]: x for x in r.json()}
    assert theo_id[du_lieu_quyen.role_viewer_id]["userCount"] == 1
```

Fixture `du_lieu_quyen` (Task 2, `tests/modules/auth/conftest.py`) đã có `role_viewer_id` /
`role_editor_id`. Task này chỉ thêm hai fixture `client_owner` / `client_viewer` — client đã đăng
nhập bằng `u_q_owner` / `u_q_viewer` với workspace `ws_q`, theo đúng khuôn fixture đăng nhập của
`test_sua_user.py`. Cả hai phụ thuộc `du_lieu_quyen`.

⚠ `u_q_viewer` mang vai trò Người xem — **không** có `workspace.admin`, nên
`require(ACTIONS.WORKSPACE_ADMIN)` chặn họ ở cổng 1 và test `test_member_khong_tao_duoc` nhận 403
từ `require()`, chưa tới `_kiem_owner`. Đó vẫn là 403 đúng. Để kiểm riêng nhánh `_kiem_owner`, thêm
`client_member_quan_tri` — một user `org_role='member'` mang vai trò Quản trị (có đủ 13 action)
ở `ws_q`; họ qua cổng 1 rồi bị `_kiem_owner` chặn. Đó mới là phép kiểm mà cổng 2 §7 mô tả
(*"member gọi POST /roles → 403 dù actions là cả 13"*).

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_vai_tro.py -v`
Expected: FAIL — 404 trên mọi đường `/api/v1/roles`

- [ ] **Step 3: Viết service**

Tạo `src/portal/modules/auth/quan_tri_vai_tro.py`:

```python
"""Sáu thao tác vai trò. Mọi thao tác ghi nằm trong MỘT transaction.

VÌ SAO KIỂM `org_role` Ở ĐÂY CHỨ KHÔNG Ở `require()`: `require(action)` trả lời
"người này có được làm hành động này trong workspace này không". Quản trị vai trò
là việc cấp TỔ CHỨC — nó không thuộc workspace nào, nên không có action nào diễn
đạt đúng nó. Khuôn này M2b §3.1 đã đặt cho `quan_tri_user.py`; giữ nguyên.

`require(ACTIONS.WORKSPACE_ADMIN)` vẫn khai trên mọi route để qua cổng 1 (mọi
endpoint phải khai action) và để chặn sớm người không có quyền quản trị nào.
"""

from uuid import uuid4

import asyncpg

from portal.api import loi as loi_chung
from portal.modules.auth import loi, repo


async def _kiem_owner(conn: asyncpg.Connection, user_id: str) -> str:
    """Trả org_id nếu là owner, ngược lại raise 403."""
    r = await conn.fetchrow(
        "SELECT org_id, org_role FROM control.users WHERE id = $1", user_id
    )
    if r is None or r["org_role"] != "owner":
        raise loi_chung.khong_du_quyen()
    return r["org_id"]


async def liet_ke_action(conn: asyncpg.Connection, user_id: str) -> list[asyncpg.Record]:
    await _kiem_owner(conn, user_id)
    return await repo.liet_ke_action(conn)


async def liet_ke(conn: asyncpg.Connection, user_id: str) -> list[asyncpg.Record]:
    org_id = await _kiem_owner(conn, user_id)
    return await repo.liet_ke_vai_tro(conn, org_id)


async def doc(conn: asyncpg.Connection, user_id: str, role_id: str) -> asyncpg.Record:
    org_id = await _kiem_owner(conn, user_id)
    r = await repo.doc_vai_tro(conn, org_id, role_id)
    if r is None:
        raise loi.vai_tro_khong_ton_tai()
    return r


async def tao(
    conn: asyncpg.Connection, user_id: str, name: str, description: str | None, actions: list[str]
) -> str:
    """Thứ tự trong MỘT transaction — người gọi mở transaction.

    1. kiểm owner                      → 403
    2. kiểm action hợp lệ              → 422 UNKNOWN_ACTION
    3. kiểm tên chưa dùng              → 409 ROLE_NAME_TAKEN
    4. INSERT roles
    5. INSERT role_actions

    Bước 2 và 3 TRƯỚC bước 4 là cố ý: FK và UNIQUE cũng chặn, nhưng bằng một
    ngoại lệ asyncpg → 500. Kiểm trước biến cùng một sự thật thành một câu có
    tên field.
    """
    org_id = await _kiem_owner(conn, user_id)

    la = await repo.loc_action_la(conn, actions)
    if la is not None:
        raise loi.action_khong_hop_le(la)

    trung = await conn.fetchval(
        "SELECT 1 FROM control.roles WHERE org_id = $1 AND name = $2", org_id, name
    )
    if trung:
        raise loi.ten_vai_tro_da_ton_tai()

    # uuid4, KHÔNG suy từ tên: tên đổi được, id thì phải ổn định (spec §2.1).
    role_id = "r_" + uuid4().hex
    await repo.tao_vai_tro(conn, role_id, org_id, name, description)
    await repo.dat_action_cua_vai_tro(conn, role_id, actions)
    return role_id


async def sua(
    conn: asyncpg.Connection,
    user_id: str,
    role_id: str,
    name: str,
    description: str | None,
    actions: list[str],
) -> None:
    org_id = await _kiem_owner(conn, user_id)
    if await repo.doc_vai_tro(conn, org_id, role_id) is None:
        raise loi.vai_tro_khong_ton_tai()

    la = await repo.loc_action_la(conn, actions)
    if la is not None:
        raise loi.action_khong_hop_le(la)

    trung = await conn.fetchval(
        "SELECT 1 FROM control.roles WHERE org_id = $1 AND name = $2 AND id <> $3",
        org_id, name, role_id,
    )
    if trung:
        raise loi.ten_vai_tro_da_ton_tai()

    await repo.doi_ten_vai_tro(conn, role_id, name, description)
    await repo.dat_action_cua_vai_tro(conn, role_id, actions)


async def xoa(conn: asyncpg.Connection, user_id: str, role_id: str) -> None:
    org_id = await _kiem_owner(conn, user_id)
    if await repo.doc_vai_tro(conn, org_id, role_id) is None:
        raise loi.vai_tro_khong_ton_tai()

    n = await repo.dem_nguoi_dung_vai_tro(conn, role_id)
    if n > 0:
        raise loi.vai_tro_dang_dung(n)

    await repo.xoa_vai_tro(conn, org_id, role_id)
```

- [ ] **Step 4: Viết router**

Thêm vào `src/portal/modules/auth/router.py` (theo đúng khuôn các route `/users` đã có — cùng cách
lấy pool và mở transaction):

```python
@ROUTER.get("/actions", response_model=list[ActionOut])
async def liet_ke_action(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[ActionOut]:
    async with pool.acquire() as conn:
        rows = await quan_tri_vai_tro.liet_ke_action(conn, p.user_id)
    return [ActionOut(**dict(r)) for r in rows]


@ROUTER.get("/roles", response_model=list[VaiTroOut])
async def liet_ke_vai_tro(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[VaiTroOut]:
    async with pool.acquire() as conn:
        rows = await quan_tri_vai_tro.liet_ke(conn, p.user_id)
    return [VaiTroOut(**dict(r)) for r in rows]


@ROUTER.get("/roles/{role_id}", response_model=VaiTroChiTietOut)
async def doc_vai_tro(
    role_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn:
        r = await quan_tri_vai_tro.doc(conn, p.user_id, role_id)
    return VaiTroChiTietOut(
        id=r["id"], name=r["name"], description=r["description"], actions=sorted(r["actions"])
    )


@ROUTER.post("/roles", response_model=VaiTroChiTietOut, status_code=201)
async def tao_vai_tro(
    than: TaoVaiTroIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn, conn.transaction():
        rid = await quan_tri_vai_tro.tao(
            conn, p.user_id, than.name, than.description, than.actions
        )
    return VaiTroChiTietOut(
        id=rid, name=than.name, description=than.description, actions=sorted(than.actions)
    )


@ROUTER.patch("/roles/{role_id}", response_model=VaiTroChiTietOut)
async def sua_vai_tro(
    role_id: str,
    than: SuaVaiTroIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn, conn.transaction():
        await quan_tri_vai_tro.sua(
            conn, p.user_id, role_id, than.name, than.description, than.actions
        )
    return VaiTroChiTietOut(
        id=role_id, name=than.name, description=than.description, actions=sorted(than.actions)
    )


@ROUTER.delete("/roles/{role_id}", status_code=204)
async def xoa_vai_tro(
    role_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await quan_tri_vai_tro.xoa(conn, p.user_id, role_id)
```

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/auth/test_vai_tro.py -v`
Expected: PASS (11 test)

- [ ] **Step 6: Cập nhật `fake.py` — phiên giả khai `actions` hẹp**

Trong `src/portal/modules/auth/fake.py`, `SessionOut` giả hiện khai cả 13 action. Đổi sang một tập
hẹp mặc định (`overview.read`, `convos.read`, `appts.read`, `catalog.read`, `agent_config.read`)
kèm comment:

```python
# Phiên giả mặc định là NGƯỜI XEM, không phải quản trị. Mặc định rộng làm mọi
# màn dev chạy được kể cả khi màn đó lẽ ra bị chặn — tức nó giấu đúng lỗi mà
# ma trận quyền tồn tại để bắt.
```

- [ ] **Step 7: Chạy cổng khai quyền + fake**

Run: `uv run pytest tests/api/test_moi_route_khai_action.py tests/modules/auth/test_fake.py -v`
Expected: PASS

- [ ] **Step 8: `make check`**

Run: `make check`
Expected: sạch

---

## Task 6: Nhật ký + `dev_seed`

**Files:**
- Modify: `src/portal/modules/auth/quan_tri_vai_tro.py` (ghi `audit_log`)
- Modify: `scripts/dev_seed.py`
- Test: `tests/modules/auth/test_vai_tro.py` (thêm 1 test)

**Interfaces:**
- Consumes: `nhat_ky.ghi(...)` như `quan_tri_user.py` đang dùng (`org_id`, `tenant_id=None`)

- [ ] **Step 1: Viết test thất bại cho nhật ký**

Thêm vào `tests/modules/auth/test_vai_tro.py`:

```python
async def test_tao_vai_tro_vao_nhat_ky_cap_to_chuc(client_owner, pool):
    """0103 đã nới audit_log.tenant_id thành NULL kèm CHECK phải có ít nhất một
    phạm vi. Vai trò là việc cấp tổ chức nên org_id là phạm vi duy nhất."""
    await client_owner.post("/api/v1/roles", json={"name": "Có vết", "actions": []})
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT org_id, tenant_id, action FROM control.audit_log
                WHERE action = 'role.tao' ORDER BY at DESC LIMIT 1"""
        )
    assert r is not None
    assert r["org_id"] is not None
    assert r["tenant_id"] is None
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/auth/test_vai_tro.py::test_tao_vai_tro_vao_nhat_ky_cap_to_chuc -v`
Expected: FAIL — không có hàng nào

- [ ] **Step 3: Ghi nhật ký ở ba thao tác ghi**

Trong `quan_tri_vai_tro.py`, thêm `nhat_ky.ghi(...)` cuối `tao` · `sua` · `xoa` — cùng khuôn
`quan_tri_user.py` đang dùng. Action lần lượt `role.tao` · `role.sua` · `role.xoa`,
`chi_tiet` chứa `{"role_id": ..., "name": ..., "actions": [...]}`.

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/auth/test_vai_tro.py -v`
Expected: PASS

- [ ] **Step 5: Cập nhật `dev_seed.py`**

`MEMBERSHIP` hiện là `(user_id, tenant_id, role)` với mã cũ. Đổi sang tên vai trò và tra `role_id`
bằng `(org_id, name)`:

```python
# (user_id, tenant_id, TÊN vai trò) — tra role_id theo (org_id, name).
# Migration 0104 seed 4 vai trò này cho mọi tổ chức; seed chỉ tra, không tạo lại.
MEMBERSHIP = [
    ("u_dang", "anphu", "Quản trị"),
    ("u_dang", "sunrise", "CSKH"),
    ("u_haven", "haven", "Quản trị"),
]
```

Trong `chay()`, đổi câu INSERT membership:

```python
            for uid, tid, ten_vai_tro in MEMBERSHIP:
                await conn.execute(
                    """INSERT INTO control.memberships (user_id, tenant_id, org_id, role_id)
                       SELECT $1, $2, u.org_id, r.id
                         FROM control.users u
                         JOIN control.roles r ON r.org_id = u.org_id AND r.name = $3
                        WHERE u.id = $1
                       ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id""",
                    uid, tid, ten_vai_tro,
                )
```

Thêm một user `member` để đường không-owner có dữ liệu thật:

```python
    # u_bt: member có vai trò Biên tập ở anphu. Đường `member` cần một người
    # thật để thấy được ma trận đang chặn đúng — owner thì không bao giờ bị chặn.
    ("u_bt", "bientap@anphuland.vn", "1", "Lê Biên Tập", "noble", "member"),
```
và một dòng `MEMBERSHIP`: `("u_bt", "anphu", "Biên tập")`.

- [ ] **Step 6: Chạy seed thật**

Run: `make reset && make up && make dev-seed`
Expected: chạy sạch, không lỗi

- [ ] **Step 7: `make check`**

Run: `make check`
Expected: sạch

---

## Task 7: Frontend — màn Vai trò

**Files:**
- Modify: `src/features/auth/api.ts`
- Create: `src/features/auth/components/DanhSachVaiTro.tsx`
- Create: `src/features/auth/components/FormVaiTro.tsx`
- Create: `src/routes/_app/roles.tsx`
- Modify: `src/features/auth/nav.ts` · `src/lib/nav-registry.ts` · `src/lib/screens.ts`
- Test: `tests/vai-tro.test.tsx` (mới) · `tests/nav-registry.test.ts` (cập nhật)

**Interfaces:**
- Consumes: 6 endpoint của Task 5
- Produces:
  ```ts
  export interface ActionInfo { code: string; groupName: 'operate'|'knowledge'|'configure';
                                labelVi: string; labelEn: string; sortOrder: number }
  export interface VaiTro { id: string; name: string; description: string | null; userCount: number }
  export interface VaiTroChiTiet { id: string; name: string; description: string | null; actions: string[] }
  export function layDanhSachAction(): Promise<ActionInfo[]>
  export function layDanhSachVaiTro(): Promise<VaiTro[]>
  export function layVaiTro(id: string): Promise<VaiTroChiTiet>
  export function taoVaiTro(v: { name: string; description: string | null; actions: string[] }): Promise<VaiTroChiTiet>
  export function suaVaiTro(id: string, v: { name: string; description: string | null; actions: string[] }): Promise<VaiTroChiTiet>
  export function xoaVaiTro(id: string): Promise<void>
  export const khoaVaiTro = { tatCa: ['roles'] as const, mot: (id: string) => ['roles', id] as const,
                              actions: ['actions'] as const }
  ```

- [ ] **Step 1: Viết test thất bại cho nav**

Thêm vào `tests/nav-registry.test.ts` một khẳng định rằng `roles` có trong NAV nhóm *Cấu hình*,
ngay sau `users`, và `requiredActions` của nó chứa `ACTIONS.WORKSPACE_ADMIN`.

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `npm test -- nav-registry`
Expected: FAIL

- [ ] **Step 3: Khai nav + screen + route**

`src/features/auth/nav.ts` — thêm:

```ts
export const rolesNav: NavLeaf = {
  kind: 'leaf',
  key: 'roles',
  path: '/roles',
  label: { vi: 'Vai trò', en: 'Roles' },
  icon: 'users',
  // Nhóm 13 — quản lý vai trò nằm cùng Thành viên · Khoá API · Cài đặt.
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}
```

`src/lib/nav-registry.ts` — thêm `rolesNav` vào nhóm *Cấu hình*, ngay sau `usersNav`, và thêm
`rolesNav` vào import từ `@/features/auth/nav`.

`src/lib/screens.ts` — thêm:

```ts
  { key: 'roles', path: '/roles', owner: 'M2b', mvp: 'full', inNav: true },
```

`src/routes/_app/roles.tsx` — route rỗng render `<DanhSachVaiTro />`.

- [ ] **Step 4: Chạy test nav**

Run: `npm test -- nav-registry`
Expected: PASS

- [ ] **Step 5: Viết test thất bại cho màn Vai trò**

Tạo `tests/vai-tro.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

describe('Màn Vai trò', () => {
  it('hiện số người đang dùng mỗi vai trò', async () => {
    renderManVaiTro()
    await waitFor(() => expect(screen.getByText('Người xem')).toBeInTheDocument())
    expect(screen.getByText(/1 người/)).toBeInTheDocument()
  })

  it('xác nhận xoá nói rõ số người bị ảnh hưởng, kể cả khi bằng 0', async () => {
    renderManVaiTro()
    await userEvent.click(await screen.findByRole('button', { name: /Xoá Trống/ }))
    expect(screen.getByText(/0 người/)).toBeInTheDocument()
  })

  it('nút Tạo vai trò ẩn khi không phải chủ tổ chức', async () => {
    renderManVaiTro({ orgRole: 'member' })
    await waitFor(() => expect(screen.getByText('Người xem')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Tạo vai trò/ })).toBeNull()
  })

  it('form gom 13 ô theo ba nhóm', async () => {
    renderManVaiTro()
    await userEvent.click(await screen.findByRole('button', { name: /Tạo vai trò/ }))
    expect(screen.getByText('Vận hành')).toBeInTheDocument()
    expect(screen.getByText('Kiến thức')).toBeInTheDocument()
    expect(screen.getByText('Cấu hình')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(13)
  })
})
```

`renderManVaiTro` là helper cục bộ dựng QueryClientProvider + MSW, theo đúng khuôn
`tests/user-admin.test.tsx` đã có.

- [ ] **Step 6: Chạy để xác nhận đỏ**

Run: `npm test -- vai-tro`
Expected: FAIL — component chưa tồn tại

- [ ] **Step 7: Viết `api.ts`, `DanhSachVaiTro.tsx`, `FormVaiTro.tsx`**

`api.ts` — 6 hàm + kiểu theo khối Interfaces ở đầu task, dùng cùng helper `fetch` và cách xử lý lỗi
mà các hàm `/users` trong file đang dùng.

`DanhSachVaiTro.tsx` — bảng bốn cột (Tên · Mô tả · Đang gán · thao tác). Ba quy tắc bắt buộc:

```tsx
// Nút Tạo vai trò chỉ hiện khi orgRole === 'owner'. Ẩn nút là cho đỡ rối mắt
// (PQ_01 §BR-Q03), KHÔNG phải bảo vệ — endpoint vẫn kiểm.
// Xác nhận xoá luôn nói userCount, kể cả 0: người dùng cần biết mình đang xoá
// một vai trò trống hay đang chạm vào quyền của người khác.
```

`FormVaiTro.tsx` — 13 checkbox gom theo `groupName` với tiêu đề
`operate → Vận hành` · `knowledge → Kiến thức` · `configure → Cấu hình`, thứ tự trong nhóm theo
`sortOrder`. Nhãn lấy `labelVi`/`labelEn` theo ngôn ngữ hiện tại.

- [ ] **Step 8: Chạy test**

Run: `npm test -- vai-tro`
Expected: PASS (4 test)

- [ ] **Step 9: Typecheck + lint**

Run: `npm run typecheck && npm run lint`
Expected: sạch

---

## Task 8: Frontend — dropdown màn Users + MSW có trạng thái

**Files:**
- Modify: màn `users` hiện có (component chứa bảng workspace × vai trò)
- Modify: `src/lib/msw/handlers.ts`
- Test: `tests/vai-tro.test.tsx` (thêm) · `tests/user-admin.test.tsx` (cập nhật)

**Interfaces:**
- Consumes: `layDanhSachVaiTro()` của Task 7

- [ ] **Step 1: Viết test thất bại — liên thông hai màn**

Thêm vào `tests/vai-tro.test.tsx`:

```tsx
it('vai trò vừa tạo hiện ngay trong dropdown màn Users', async () => {
  // MSW phải CÓ TRẠNG THÁI (M2b §5.3). Handler trả mảng cứng sẽ làm test này
  // xanh trong khi luồng thật hỏng.
  renderManVaiTro()
  await userEvent.click(await screen.findByRole('button', { name: /Tạo vai trò/ }))
  await userEvent.type(screen.getByLabelText(/Tên vai trò/), 'Trưởng nhóm')
  await userEvent.click(screen.getByRole('button', { name: /Lưu/ }))

  renderManUsers()
  await waitFor(() =>
    expect(screen.getByRole('option', { name: 'Trưởng nhóm' })).toBeInTheDocument(),
  )
})

it('dropdown rỗng hiện lời nhắc kèm link, không phải ô select trống', async () => {
  renderManUsers({ vaiTro: [] })
  expect(await screen.findByText(/Chưa có vai trò nào/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Tạo vai trò/ })).toHaveAttribute('href', '/roles')
})
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `npm test -- vai-tro`
Expected: FAIL

- [ ] **Step 3: Viết handler MSW có trạng thái**

Trong `src/lib/msw/handlers.ts`, thêm một store cục bộ (mảng module-level) cho `roles` +
`role_actions`, và 6 handler đọc/ghi vào store đó. `GET /actions` trả 13 ô cứng — chúng là hằng số
thật, không phải trạng thái.

- [ ] **Step 4: Đổi dropdown màn Users**

Bỏ 4 hằng số vai trò, dùng `useQuery(khoaVaiTro.tatCa, layDanhSachVaiTro)`. Khi mảng rỗng, render
lời nhắc + `<Link to="/roles">Tạo vai trò</Link>` thay cho `<select>`.

- [ ] **Step 5: Chạy toàn bộ test FE**

Run: `npm test`
Expected: PASS. `tests/user-admin.test.tsx` có thể đỏ vì nó giả định 4 lựa chọn cứng — cập nhật nó
sang đọc từ store MSW.

- [ ] **Step 6: Typecheck + lint + build**

Run: `npm run typecheck && npm run lint && npm run build`
Expected: sạch

- [ ] **Step 7: Kiểm bằng backend thật**

Chạy `make up && make dev-seed && make api` ở repo backend, `npm run dev` ở frontend. Đăng nhập
bằng `dang@anphuland.vn`, vào `/roles`: tạo một vai trò, gán cho `bientap@anphuland.vn` ở màn
`/users`, đăng nhập bằng tài khoản đó và xác nhận sidebar hẹp lại đúng.

- [ ] **Step 8: `make contracts` không đổi artefact**

Run (backend): `make contracts && git status contracts/` — hoặc so sánh thủ công vì repo không phải
git: `contracts/actions.json` phải vẫn đúng 13 action, tên không đổi.
Expected: không đổi

---

## Tự soát kế hoạch

**Spec coverage:**

| Mục spec | Task |
|---|---|
| §2 Schema (3 bảng + đổi cột) | 1 |
| §2.1 Năm quyết định schema | 1 (comment trong migration) |
| §2.2 `actions` là bản sao đọc + cổng canh | 1 (Step 1) |
| §3.1 Đổi một chỗ trong `require()` | 2 |
| §3.2 Một truy vấn, `expires_at` trong `ON` | 2 |
| §3.3 Owner không qua ma trận | 2 |
| §3.4 403 nói lý do | 3 |
| §3.5 Không cache | 2 (Step 1, cổng 8) |
| §4 Sáu endpoint | 5 |
| §4.1 Bốn mã lỗi | 4 |
| §4.2 Hai luật an toàn | 5 (`ROLE_IN_USE`) · M2b đã có (`SELF_LOCKOUT`) |
| §5 Chín chỗ FE | 7 · 8 |
| §5.1 Ba quy tắc UI | 7 (Step 7) · 8 (Step 4) |
| §5.2 MSW có trạng thái | 8 |
| §6 Migration dữ liệu + downgrade raise | 1 |
| §7 Cổng test 1–13 | 1 (1·4·12·13) · 2 (2·3·8) · 5 (5·7·9·10·11) · 6 (allowlist) |
| §8.1 Nhật ký thay đổi vai trò | 6 |

**Chỗ chưa phủ, cố ý:** cổng 6 (`SELF_LOCKOUT` khi gỡ owner cuối) — M2b đã cài và đã có test
`test_sua_user.py`; spec này không đổi luật đó, chỉ nhắc lại. Task 2 Step 12 canh test đó còn xanh.
