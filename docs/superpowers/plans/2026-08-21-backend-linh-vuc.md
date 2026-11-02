# Backend `/api/v1/linh-vuc` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng 2 endpoint `GET/PATCH /api/v1/linh-vuc` cho màn «Quản lý lĩnh vực» (`/domains`) — hợp đồng FE đã định sẵn, backend chưa từng có.

**Architecture:** Module mới `modules/linh_vuc/` (registry tự quét `ROUTER`). Trạng thái bật/tắt = SỰ HIỆN DIỆN của hàng trong `control.tenant_verticals` (bảng có sẵn từ `0002`). Một migration backfill `0944` cho tenant tạo trước 2026-08-15. Sổ lĩnh vực là hằng trong module (2 dòng: `bds↔realestate`, `taichinh↔finance`).

**Tech Stack:** FastAPI + asyncpg + alembic + pytest (khuôn y hệt module `kb`/`config`).

**Spec:** `docs/superpowers/specs/2026-08-21-backend-linh-vuc-design.md` — plan này lập luận từ spec đó, executor đọc CẢ HAI.

## Global Constraints

- Nhánh `feat/linh-vuc-backend`, base `a97f055` (develop). KHÔNG rebase/merge giữa chừng.
- Commit message `<type>: <subject>`, KHÔNG footer attribution. Stage theo ĐƯỜNG DẪN tường minh — cấm `git add -A`/`git add .`/`commit -a`.
- Hợp đồng FE đóng băng: field ĐÚNG tên `ma/ten/bat/soKyNang/coDuLieu`; GET trả MẢNG TRẦN (không envelope); PATCH body `{"bat": bool}`.
- `tenant_id` LUÔN lấy từ `Principal`, KHÔNG từ path/body (luật đầu `config/router.py`).
- SQL chạm `tenant_data` phải qua `tenant_conn()` và mang vị từ LITERAL `tenant_id = portal.current_tenant()` trong chuỗi (cổng cách ly đọc TĨNH f-string). SQL `control.*` viết schema `control.` THẲNG trong literal.
- Migration: literal đóng băng (`'realestate'` viết thẳng), KHÔNG import `portal.*`; `down_revision = "0943_hop_nhat_hai_head"` (head duy nhất, đã kiểm `alembic heads`).
- KHÔNG chạm `contracts/` (actions.py/tools.py không đổi ⇒ không cần `make contracts`).
- KHÔNG chạm route/module khác ngoài 2 file ghi ở Task 5 (docstring `workspace/repo.py`, `CLAUDE.md`).
- Test chạy bằng `uv run pytest …` (KHÔNG pytest trần). Test module cần Docker đang chạy (container `pg_dsn` scope session dựng từ `alembic upgrade head` — migration hỏng sẽ làm ĐỎ cả thư mục test, đó là chủ ý).
- Python: type annotation đủ trên chữ ký; docstring giải thích VÌ SAO theo nếp repo.

---

### Task 1: Sổ lĩnh vực + contracts của module (`so.py`, `contracts.py`)

**Files:**
- Create: `src/portal/modules/linh_vuc/__init__.py` (rỗng)
- Create: `src/portal/modules/linh_vuc/so.py`
- Create: `src/portal/modules/linh_vuc/contracts.py`
- Test: `tests/modules/linh_vuc/test_so.py`

**Interfaces:**
- Consumes: `portal.modules.config.contracts.TEN_KY_NANG` (frozenset 12 tên kỹ năng — import chéo qua mặt tiền, hợp lệ luật 3; `ops/router.py` đã đi đường này).
- Produces (Task 3, 4 dùng): `so.LinhVuc(ma, ten, vertical)` NamedTuple · `so.SO_LINH_VUC: tuple[LinhVuc, ...]` (thứ tự bds, taichinh) · `so.KY_NANG_CHUNG: frozenset[str]` · `so.theo_ma(ma) -> LinhVuc | None` · `so.so_ky_nang(lv) -> int` · `contracts.LinhVucOut` (5 field: ma/ten/bat/soKyNang/coDuLieu) · `contracts.DatLinhVucIn` (`bat: bool`, `extra="forbid"`).

- [ ] **Step 1: Viết test (sẽ fail vì module chưa có)**

```python
# tests/modules/linh_vuc/test_so.py
"""Sổ lĩnh vực — mọi bài ở đây thuần, không cần Docker.

Sổ là bảng ánh xạ giữa BA hệ tên: `ma` FE (`NavSegment.linhVuc`), `vertical`
DB (CHECK của 0002), và sổ kỹ năng backend. Test đối chiếu từng cạnh — lệch
cạnh nào là màn /domains sai theo kiểu của cạnh đó.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import TEN_KY_NANG
from portal.modules.linh_vuc import so
from portal.modules.linh_vuc.contracts import DatLinhVucIn
from portal.modules.realestate.contracts import SENTINEL_TENANT


def test_ky_nang_chung_nam_trong_so_that():
    """3 kỹ năng chung phải là tên THẬT trong sổ 12 — gõ sai một tên là
    so_ky_nang() đếm sai mà không lỗi nào phát ra."""
    assert so.KY_NANG_CHUNG <= TEN_KY_NANG
    assert len(so.KY_NANG_CHUNG) == 3


def test_vertical_khop_check_cua_0002():
    """CHECK (vertical IN ('realestate','finance')) — literal chép từ 0002.
    Thêm lĩnh vực vào sổ mà quên nới CHECK thì INSERT nổ lúc chạy; bài này
    làm nó nổ lúc test."""
    assert {lv.vertical for lv in so.SO_LINH_VUC} <= {"realestate", "finance"}


def test_ma_khong_trung_va_dung_thu_tu():
    """Thứ tự cố định bds → taichinh: FE render theo thứ tự mảng."""
    assert [lv.ma for lv in so.SO_LINH_VUC] == ["bds", "taichinh"]


def test_so_ky_nang_hom_nay():
    """bds = 12 − 3 = 9 (mọi kỹ năng không-chung đều là BĐS hôm nay — xem
    cảnh báo tương lai trong docstring so_ky_nang)."""
    bds, taichinh = so.SO_LINH_VUC
    assert so.so_ky_nang(bds) == len(TEN_KY_NANG) - len(so.KY_NANG_CHUNG) == 9
    assert so.so_ky_nang(taichinh) == 0


def test_theo_ma():
    assert so.theo_ma("bds") is not None
    assert so.theo_ma("realestate") is None  # vertical KHÔNG phải ma


def test_sentinel_khop_literal_trong_sql():
    """repo.co_du_lieu_bds (Task 3) viết literal '__ALL__' trong SQL (cổng
    cách ly đọc tĩnh, không expand biến) — bài này neo literal đó vào hằng
    thật của realestate."""
    assert SENTINEL_TENANT == "__ALL__"


def test_dat_linh_vuc_in_chan_khoa_la():
    with pytest.raises(ValidationError):
        DatLinhVucIn(bat=True, la="x")
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `uv run pytest tests/modules/linh_vuc/test_so.py -q`
Expected: FAIL/ERROR `ModuleNotFoundError: No module named 'portal.modules.linh_vuc'`

- [ ] **Step 3: Viết `__init__.py` (rỗng), `so.py`, `contracts.py`**

```python
# src/portal/modules/linh_vuc/so.py
"""Sổ lĩnh vực — hằng của sản phẩm, KHÔNG cho tenant tự thêm/xoá.

Khớp quyết định phía FE (docstring `QuanLyLinhVuc.tsx`): sổ hôm nay là hai
hằng số (vertical #1 đã có, #2 chưa), một nút «Thêm lĩnh vực» sẽ hứa rằng
thêm xong agent biết làm gì đó, trong khi kỹ năng và dữ liệu của một vertical
mới là việc của backend.

VÌ SAO CÓ ÁNH XẠ ma ↔ vertical: FE nav dùng `bds`/`taichinh`
(`NavSegment.linhVuc`, hợp đồng đã đóng băng 2026-08-08), còn CHECK của
`control.tenant_verticals` (0002) chỉ nhận `'realestate'`/`'finance'`. Đổi
phía nào cũng đắt hơn bảng ánh xạ hai dòng này.
"""

from typing import NamedTuple

from portal.modules.config.contracts import TEN_KY_NANG


class LinhVuc(NamedTuple):
    ma: str
    """Khoá FE — khớp `NavSegment.linhVuc` bên repo frontend. Đổi là vỡ hợp đồng."""
    ten: str
    vertical: str
    """Giá trị cột `control.tenant_verticals.vertical` — phải nằm trong CHECK của 0002."""


SO_LINH_VUC: tuple[LinhVuc, ...] = (
    LinhVuc("bds", "Bất động sản", "realestate"),
    LinhVuc("taichinh", "Tài chính", "finance"),
)
"""Thứ tự CỐ ĐỊNH — GET trả đúng thứ tự này, FE render theo mảng."""

KY_NANG_CHUNG: frozenset[str] = frozenset({"kb_search", "update_customer", "escalate"})
"""3 kỹ năng không thuộc lĩnh vực nào — tra tài liệu, cập nhật khách, chuyển
người thật là việc agent làm bất kể đang nói về gì. FE khai Y HỆT ở
`features/agent/kyNang.ts` (`KY_NANG_CHUNG`); backend chưa có khái niệm này
nên khai ở đây, test đối chiếu ⊆ TEN_KY_NANG."""


def theo_ma(ma: str) -> LinhVuc | None:
    """`None` = ma lạ — router trả 404, không đoán."""
    return next((lv for lv in SO_LINH_VUC if lv.ma == ma), None)


def so_ky_nang(lv: LinhVuc) -> int:
    """Số kỹ năng thuộc lĩnh vực — SUY từ sổ thật, không hằng chép tay
    (bài học overview 2026-08-14: mẫu số viết cứng sai ngay ngày sổ đổi).

    ⚠️ Công thức bds = «mọi kỹ năng không-chung» chỉ đúng khi cả sổ ngoài
    phần chung đều là BĐS — hôm nay đúng (9/9), và FE đang suy Y HỆT
    (`KY_NANG_TAB_BDS = MUOI_HAI_KY_NANG − chung`). Ngày sổ kỹ năng mọc kỹ
    năng finance, công thức này gán nhầm nó cho bds — lúc đó phải chuyển sổ
    sang gắn nhãn lĩnh vực từng kỹ năng (cả đây lẫn FE).
    """
    if lv.ma == "bds":
        return len(TEN_KY_NANG) - len(KY_NANG_CHUNG)
    return 0
```

```python
# src/portal/modules/linh_vuc/contracts.py
"""Mặt tiền của module linh_vuc — module khác chỉ được import file này.

`LinhVucOut` chép ĐÚNG hình dạng FE khai ở `features/agent/linhVuc.ts`
(hợp đồng FE định trước 2026-08-08, đóng băng): tên field camelCase y nguyên,
GET trả mảng TRẦN các object này, PATCH trả MỘT object.
"""

from pydantic import BaseModel, ConfigDict


class LinhVucOut(BaseModel):
    ma: str
    ten: str
    bat: bool
    soKyNang: int
    """Để màn quản lý nói rõ tắt đi là mất gì."""
    coDuLieu: bool
    """`False` ⇒ bật lên agent cũng chưa trả lời được — FE hiện «chưa có dữ
    liệu để agent tra»."""


class DatLinhVucIn(BaseModel):
    """Body của PATCH. `extra="forbid"` — khoá lạ là 422 ngay, cùng nếp
    `DatTrangThaiKhoaIn` của enrollment."""

    model_config = ConfigDict(extra="forbid")

    bat: bool
```

- [ ] **Step 4: Chạy test pass**

Run: `uv run pytest tests/modules/linh_vuc/test_so.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/linh_vuc/__init__.py src/portal/modules/linh_vuc/so.py src/portal/modules/linh_vuc/contracts.py tests/modules/linh_vuc/test_so.py
git commit -m "feat: so linh vuc + contracts cua module linh_vuc"
```

---

### Task 2: Migration `0944` backfill `tenant_verticals`

**Files:**
- Create: `migrations/versions/0944_backfill_tenant_verticals.py`

**Interfaces:**
- Consumes: bảng `control.tenant_verticals` (0002) + `control.tenants`.
- Produces: mọi tenant hiện hữu có hàng `(tenant_id, 'realestate')` — Task 3/4 giả định «trạng thái sau backfill» khi seed test.

- [ ] **Step 1: Viết migration**

```python
# migrations/versions/0944_backfill_tenant_verticals.py
"""Backfill `control.tenant_verticals` — bật `realestate` cho tenant tạo trước 2026-08-15

VÌ SAO BẮT BUỘC, KHÔNG PHẢI PHÒNG HỜ: `workspace/repo.them_vertical` mới chạy
từ 2026-08-15 (đường tạo workspace); tenant tạo trước đó (anphu, sunrise…)
KHÔNG có hàng nào. Module `linh_vuc` (cùng đợt commit này) đọc «bật = có
hàng» — thiếu backfill thì ship xong, `GET /linh-vuc` trả `bat=false` cho bds
và khối Bất động sản BIẾN KHỎI NAV của mọi workspace cũ ngay lập tức (FE
`useNavGroups` lọc khối theo công tắc).

Bật mặc định `realestate` đúng với hành vi mọi tenant đang thấy: tất cả đều
là tenant BĐS (`VERTICAL_MAC_DINH = 'realestate'` ở workspace/service,
`ConfigPayload.pham_vi.linh_vuc = Literal["realestate"]`), và fake MSW của FE
cũng seed `bds.bat = true`.

Literal `'realestate'` viết THẲNG — migration đóng băng theo thời điểm,
KHÔNG import `portal.*` (đọc sổ hiện hành nghĩa là migration cũ đổi nghĩa
mỗi lần sổ đổi).

Idempotent (`ON CONFLICT DO NOTHING`): chạy lại trên DB đã backfill hoặc
tenant đã có hàng từ `them_vertical` đều là no-op.
"""

from alembic import op

revision = "0944_backfill_tenant_verticals"
down_revision = "0943_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO control.tenant_verticals (tenant_id, vertical)
        SELECT id, 'realestate' FROM control.tenants
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # No-op CÓ CHỦ Ý: không phân biệt được hàng backfill với hàng
    # `them_vertical` ghi thật lúc tạo workspace — xoá là tắt nhầm lĩnh vực
    # người ta đang bật. Chiều xuống chấp nhận giữ hàng.
    pass
```

- [ ] **Step 2: Kiểm một head + upgrade trên DB dev**

Run: `uv run pytest tests/unit/test_alembic_mot_head.py -q`
Expected: PASS (0944 nhận 0943 làm cha ⇒ vẫn một head)

Run: `make migrate`
Expected: chạy sạch, không lỗi.

- [ ] **Step 3: Kiểm dữ liệu thật trên DB dev**

Run (đọc DSN từ `.env`, DB dev cổng theo `PORTAL_PG_PORT`):
```bash
docker exec $(docker ps --format '{{.Names}}' | grep portal.*postgres | head -1) \
  psql -U postgres -d portal -c \
  "SELECT t.id, v.vertical FROM control.tenants t LEFT JOIN control.tenant_verticals v ON v.tenant_id = t.id ORDER BY t.id"
```
Expected: MỌI tenant có ít nhất một hàng `realestate`, không hàng nào NULL. (Tên container/DB đọc từ `docker ps` và `.env` — nếu lệnh trên không khớp máy, dùng `uv run python -c` với asyncpg và `MIGRATOR_URL`.)

Run lại `make migrate` lần nữa: no-op, không lỗi (idempotent).

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/0944_backfill_tenant_verticals.py
git commit -m "feat: migration 0944 backfill tenant_verticals cho tenant cu"
```

---

### Task 3: Repo SQL + seed test (`repo.py`, `conftest.py`)

**Files:**
- Create: `src/portal/modules/linh_vuc/repo.py`
- Create: `tests/modules/linh_vuc/conftest.py`
- Test: `tests/modules/linh_vuc/test_repo.py`

**Interfaces:**
- Consumes: `tenant_conn` (`portal.core.db.session`), bảng `control.tenant_verticals`, `tenant_data.projects`.
- Produces (Task 4 dùng): `repo.doc_verticals(conn, tenant_id) -> set[str]` · `repo.bat(conn, tenant_id, vertical) -> None` · `repo.tat(conn, tenant_id, vertical) -> None` · `repo.co_du_lieu_bds(conn) -> bool` (chạy TRONG `tenant_conn`). Fixture `seed_lv` + hằng `TENANT="lv_acme"`, `OTHER_TENANT="lv_other"`, fixture `api_pool`.

- [ ] **Step 1: Viết conftest + test (fail vì repo chưa có)**

```python
# tests/modules/linh_vuc/conftest.py
"""Seed cho test module linh_vuc — hai tenant, trạng thái NHƯ SAU backfill 0944.

Mỗi tenant có sẵn: hàng `('realestate')` trong tenant_verticals (backfill/
them_vertical đều ra thế) + dự án sentinel `__ALL__` published (provisioning
tạo cho MỌI tenant thật — thiếu nó thì bài coDuLieu xanh giả: không có gì
để loại).

Seed hai tenant, không một: bug cách ly trông y hệt chạy đúng nếu chỉ seed
tenant đang test.
"""

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

TENANT = "lv_acme"
OTHER_TENANT = "lv_other"


@pytest.fixture
async def seed_lv(pool):
    async with pool.acquire() as conn, conn.transaction():
        for tid, name in [(TENANT, "LV Acme"), (OTHER_TENANT, "LV Other")]:
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, name
            )
            await conn.execute(
                "INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, 'realestate')", tid
            )
    for tid in (TENANT, OTHER_TENANT):
        async with tenant_conn(pool, tid) as conn:
            await conn.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                "VALUES ($1, '__ALL__', 'Chung / toàn tenant', 'published')",
                tid,
            )
    yield
    # ON DELETE CASCADE dọn tenant_verticals + tenant_data + audit_log của hai
    # tenant — cascade chạy ở tầng hệ thống, không bị RLS chặn.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'lv\\_%'")


@pytest.fixture
async def api_pool(api_dsn):
    """Pool runtime (`portal_api`) — role thật của API. `pool` là migrator/
    superuser, bỏ qua RLS kể cả FORCE, chỉ dùng để seed và đọc đối chứng."""
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()
```

```python
# tests/modules/linh_vuc/test_repo.py
"""Repo SQL của linh_vuc — chạy trên container Postgres thật (fixture pg_dsn)."""

from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import repo

from .conftest import OTHER_TENANT, TENANT


async def test_doc_bat_tat_vong_tron(api_pool, seed_lv):
    async with api_pool.acquire() as conn:
        assert await repo.doc_verticals(conn, TENANT) == {"realestate"}

        await repo.tat(conn, TENANT, "realestate")
        assert await repo.doc_verticals(conn, TENANT) == set()

        await repo.bat(conn, TENANT, "finance")
        await repo.bat(conn, TENANT, "finance")  # idempotent — ON CONFLICT
        assert await repo.doc_verticals(conn, TENANT) == {"finance"}

        await repo.tat(conn, TENANT, "finance")
        await repo.tat(conn, TENANT, "finance")  # DELETE hụt cũng im lặng
        assert await repo.doc_verticals(conn, TENANT) == set()


async def test_tat_khong_lan_sang_tenant_khac(api_pool, seed_lv):
    """control.* KHÔNG có RLS — cách ly ở đây chỉ nhờ vị từ tenant_id trong
    SQL. Bài này là bằng chứng vị từ đó tồn tại."""
    async with api_pool.acquire() as conn:
        await repo.tat(conn, TENANT, "realestate")
        assert await repo.doc_verticals(conn, OTHER_TENANT) == {"realestate"}


async def test_co_du_lieu_bo_qua_sentinel(api_pool, seed_lv):
    """Chỉ có `__ALL__` (row hệ thống, LUÔN published ở mọi tenant) thì CHƯA
    tính là có dữ liệu — không loại nó thì trường này là hằng true."""
    async with tenant_conn(api_pool, TENANT) as conn:
        assert await repo.co_du_lieu_bds(conn) is False


async def test_co_du_lieu_dem_du_an_published(api_pool, seed_lv):
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'nplb', 'Noble Palace', 'draft')"
        )
        assert await repo.co_du_lieu_bds(conn) is False  # draft chưa tính

        await conn.execute(
            "UPDATE tenant_data.projects SET status = 'published' "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'nplb'"
        )
        assert await repo.co_du_lieu_bds(conn) is True

    # tenant kia không lây
    async with tenant_conn(api_pool, OTHER_TENANT) as conn:
        assert await repo.co_du_lieu_bds(conn) is False
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `uv run pytest tests/modules/linh_vuc/test_repo.py -q`
Expected: ERROR `cannot import name 'repo'` (hoặc AttributeError)

- [ ] **Step 3: Viết `repo.py`**

```python
# src/portal/modules/linh_vuc/repo.py
"""SQL của module linh_vuc. CALLER quyết định giao dịch — khuôn `repo.py` chung.

HAI HẠNG KẾT NỐI, đừng trộn:
- `doc_verticals`/`bat`/`tat` chạm `control.tenant_verticals` — schema
  `control` KHÔNG có RLS (cố ý, 0908), cách ly CHỈ nhờ vị từ `tenant_id = $1`
  với tenant lấy từ Principal. Nhận `conn` từ `pool.acquire()` thường.
- `co_du_lieu_bds` chạm `tenant_data.projects` — PHẢI gọi trong
  `tenant_conn()` (RLS FORCE), và vị từ `tenant_id = portal.current_tenant()`
  viết LITERAL trong chuỗi vì cổng cách ly đọc TĨNH f-string.

Bảng `tenant_verticals` có người ghi thứ nhất là `workspace/repo.them_vertical`
(lúc tạo workspace) — module này là người ghi thứ hai (công tắc màn /domains).
"""

import asyncpg


async def doc_verticals(conn: asyncpg.Connection, tenant_id: str) -> set[str]:
    """Tập vertical đang BẬT của workspace — bật = có hàng (nghĩa gốc của 0002)."""
    rows = await conn.fetch(
        "SELECT vertical FROM control.tenant_verticals WHERE tenant_id = $1", tenant_id
    )
    return {r["vertical"] for r in rows}


async def bat(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> None:
    """Idempotent — bật thứ đang bật là no-op, không có lỗi «đã bật rồi»."""
    await conn.execute(
        "INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        tenant_id,
        vertical,
    )


async def tat(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> None:
    """Idempotent — DELETE hụt im lặng. `enabled_at` mất theo hàng; bật lại
    là mốc mới — chấp nhận, không ai đọc mốc đó."""
    await conn.execute(
        "DELETE FROM control.tenant_verticals WHERE tenant_id = $1 AND vertical = $2",
        tenant_id,
        vertical,
    )


async def co_du_lieu_bds(conn: asyncpg.Connection) -> bool:
    """Agent đã có gì để tra chưa — gọi TRONG `tenant_conn()`.

    LOẠI SENTINEL `'__ALL__'` (literal — khớp `SENTINEL_TENANT` của
    realestate, có test neo): row hệ thống đó LUÔN published ở mọi tenant
    (provisioning tạo, `SENTINEL_PROTECTED` chặn xoá) — không loại thì mọi
    tenant đều «đã có dữ liệu» và trường này thành hằng.

    Chỉ xét `projects`: nó neo cả cây (units/zones/documents FK về nó) —
    «có dự án published» là điều kiện cần và đủ để agent tra được gì đó.
    """
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tenant_data.projects"
            " WHERE tenant_id = portal.current_tenant()"
            " AND status = 'published' AND project_code <> '__ALL__')"
        )
    )
```

- [ ] **Step 4: Chạy test pass**

Run: `uv run pytest tests/modules/linh_vuc -q`
Expected: test_repo 4 passed + test_so 7 passed

- [ ] **Step 5: Cổng cách ly**

Run: `make test-isolation`
Expected: XANH như baseline (51/51) — `co_du_lieu_bds` mang vị từ literal nên cổng nhận.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/linh_vuc/repo.py tests/modules/linh_vuc/conftest.py tests/modules/linh_vuc/test_repo.py
git commit -m "feat: repo linh_vuc - doc/bat/tat vertical + co_du_lieu_bds"
```

---

### Task 4: Router — 2 route `/linh-vuc`

**Files:**
- Create: `src/portal/modules/linh_vuc/router.py`
- Test: `tests/modules/linh_vuc/test_router.py`

**Interfaces:**
- Consumes: mọi thứ Task 1 + Task 3 produce; `require`/`lay_pool` (`portal.core.auth.require`), `nhat_ky.ghi(conn, tenant_id, hanh_dong, actor, chi_tiet)`.
- Produces: `ROUTER` prefix `/linh-vuc` — registry tự quét, KHÔNG sửa `api/registry.py`. Handler `liet_ke(p, pool)` và `dat(ma, body, p, pool)` (test gọi thẳng).

- [ ] **Step 1: Viết test (fail vì router chưa có)**

```python
# tests/modules/linh_vuc/test_router.py
"""2 route /linh-vuc — khuôn module kb: gọi thẳng handler, Principal dựng sẵn.

`actions=frozenset()` vì require() là dependency của FastAPI, không chạy khi
gọi thẳng — phép kiểm «route nào khai action nào» thuộc cổng
tests/api/test_moi_route_khai_action.py, tự quét mọi APIRoute.
"""

import pytest

from portal.api.loi import LoiPortal
from portal.core.auth.principal import Principal
from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import router
from portal.modules.linh_vuc.contracts import DatLinhVucIn

from .conftest import OTHER_TENANT, TENANT

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())
_P_KHAC = Principal(user_id="u_seed_test", tenant_id=OTHER_TENANT, role="Quản trị", actions=frozenset())


async def test_get_sau_backfill(api_pool, seed_lv):
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert [(o.ma, o.bat) for o in ds] == [("bds", True), ("taichinh", False)]
    assert (ds[0].soKyNang, ds[1].soKyNang) == (9, 0)
    assert (ds[0].ten, ds[1].ten) == ("Bất động sản", "Tài chính")
    # tenant mới chỉ có sentinel — chưa tính là có dữ liệu
    assert (ds[0].coDuLieu, ds[1].coDuLieu) == (False, False)


async def test_patch_tat_roi_bat_lai(api_pool, seed_lv):
    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    assert o.bat is False and o.ma == "bds"

    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert ds[0].bat is False  # GET đọc lại đúng trạng thái vừa ghi

    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)  # idempotent
    assert o.bat is True


async def test_patch_ma_la_404(api_pool, seed_lv):
    with pytest.raises(LoiPortal) as e:
        await router.dat(ma="chungkhoan", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    assert e.value.ma == "LINH_VUC_KHONG_TON_TAI" and e.value.http == 404


async def test_patch_khong_lan_sang_tenant_khac(api_pool, seed_lv):
    await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    ds = await router.liet_ke(p=_P_KHAC, pool=api_pool)
    assert ds[0].bat is True


async def test_patch_ghi_nhat_ky(api_pool, pool, seed_lv):
    await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    async with pool.acquire() as conn:
        hd = [
            r["hanh_dong"]
            for r in await conn.fetch(
                "SELECT hanh_dong FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong LIKE 'linh_vuc.%' ORDER BY id",
                TENANT,
            )
        ]
    assert hd == ["linh_vuc.tat", "linh_vuc.bat"]


async def test_co_du_lieu_doi_theo_du_an(api_pool, seed_lv):
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'nplb', 'Noble Palace', 'published')"
        )
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert ds[0].coDuLieu is True
    assert ds[1].coDuLieu is False  # taichinh là hằng False, không query


async def test_route_len_app(api_pool):
    """Registry quét được ROUTER — thiếu biến/đặt sai tên là 404 không lỗi nào."""
    from portal.api.registry import gom_router

    routers = dict(gom_router())
    assert "linh_vuc" in routers
    paths = {r.path for r in routers["linh_vuc"].routes}
    assert paths == {"/linh-vuc", "/linh-vuc/{ma}"}
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `uv run pytest tests/modules/linh_vuc/test_router.py -q`
Expected: ERROR `cannot import name 'router'`

- [ ] **Step 3: Viết `router.py`**

```python
# src/portal/modules/linh_vuc/router.py
"""Endpoint màn «Quản lý lĩnh vực» (/domains của FE) — 2 route.

HỢP ĐỒNG DO FE ĐỊNH TRƯỚC (2026-08-08, `features/agent/linhVuc.ts`, fake MSW
chạy từ đó tới nay): GET trả MẢNG TRẦN đúng thứ tự sổ; PATCH trả MỘT object.
Đổi hình dạng ở đây là vỡ màn đang chạy — sửa FE trước rồi mới tới đây.

`tenant_id` LUÔN lấy từ `Principal` (đã xác thực qua membership), KHÔNG từ
path/body — `control.tenant_verticals` không có RLS đỡ phía sau, lấy sai chỗ
là bật/tắt lĩnh vực của workspace khác không lỗi nào.

Quyền: GET `AGENT_CONFIG_READ` (khớp `requiredActions` nav FE), PATCH
`AGENT_CONFIG_WRITE` — bật/tắt lĩnh vực là sửa hành vi agent, cùng hạng sửa
bản nháp cấu hình. KHÔNG side effect sang agent: gating kỹ năng vẫn ở FE lúc
«Lưu và áp dụng» (`locKyNangTheoLinhVuc`), backend chỉ là sổ trạng thái.
Cổng nạp (ingest) cũng KHÔNG đọc bảng này — tắt lĩnh vực không chặn nạp dữ
liệu, cố ý (xem spec §7).
"""

import asyncpg
from fastapi import APIRouter, Depends

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import repo, so
from portal.modules.linh_vuc.contracts import DatLinhVucIn, LinhVucOut

ROUTER = APIRouter(prefix="/linh-vuc", tags=["linh-vuc"])
"""KHÔNG có `/api/v1` ở đây — `create_app()` thêm tiền tố lúc include_router."""


def _khong_ton_tai(ma: str) -> loi.LoiPortal:
    return loi.LoiPortal("LINH_VUC_KHONG_TON_TAI", 404, f"Không có lĩnh vực {ma!r}")


async def _dung_out(pool: asyncpg.Pool, tenant_id: str, lv: so.LinhVuc, dang_bat: set[str]) -> LinhVucOut:
    """Một chỗ dựng LinhVucOut — GET và PATCH trả cùng hình dạng từ cùng phép tính."""
    if lv.ma == "bds":
        async with tenant_conn(pool, tenant_id) as conn:
            co_du_lieu = await repo.co_du_lieu_bds(conn)
    else:
        # taichinh chưa có bảng dữ liệu nào — hằng False, không mở giao dịch vô ích
        co_du_lieu = False
    return LinhVucOut(
        ma=lv.ma,
        ten=lv.ten,
        bat=lv.vertical in dang_bat,
        soKyNang=so.so_ky_nang(lv),
        coDuLieu=co_du_lieu,
    )


@ROUTER.get("", response_model=list[LinhVucOut])
async def liet_ke(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[LinhVucOut]:
    async with pool.acquire() as conn:
        dang_bat = await repo.doc_verticals(conn, p.tenant_id)
    return [await _dung_out(pool, p.tenant_id, lv, dang_bat) for lv in so.SO_LINH_VUC]


@ROUTER.patch("/{ma}", response_model=LinhVucOut)
async def dat(
    ma: str,
    body: DatLinhVucIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> LinhVucOut:
    lv = so.theo_ma(ma)
    if lv is None:
        raise _khong_ton_tai(ma)
    async with pool.acquire() as conn, conn.transaction():
        if body.bat:
            await repo.bat(conn, p.tenant_id, lv.vertical)
        else:
            await repo.tat(conn, p.tenant_id, lv.vertical)
        # Nhật ký CÙNG transaction — công tắc đổi mà không có vết (hoặc ngược
        # lại) thì người đọc nhật ký tin vào cái sai.
        await nhat_ky.ghi(
            conn, p.tenant_id, "linh_vuc.bat" if body.bat else "linh_vuc.tat", p.user_id, {"ma": ma}
        )
    # Đọc lại từ DB thay vì suy từ body — rẻ, và không bao giờ lệch trạng thái thật.
    async with pool.acquire() as conn:
        dang_bat = await repo.doc_verticals(conn, p.tenant_id)
    return await _dung_out(pool, p.tenant_id, lv, dang_bat)
```

- [ ] **Step 4: Chạy test pass**

Run: `uv run pytest tests/modules/linh_vuc -q`
Expected: toàn bộ pass (7 + 4 + 7 bài)

- [ ] **Step 5: Cổng route khai action + registry**

Run: `uv run pytest tests/api/ -q`
Expected: PASS — 2 route mới đều khai `require(...)`, registry quét thấy module.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/linh_vuc/router.py tests/modules/linh_vuc/test_router.py
git commit -m "feat: 2 route /linh-vuc cho man Quan ly linh vuc"
```

---

### Task 5: Docstring workspace + CLAUDE.md + cổng toàn repo

**Files:**
- Modify: `src/portal/modules/workspace/repo.py` (docstring đầu file dòng 1-14 + docstring `them_vertical` ~dòng 144-158)
- Modify: `CLAUDE.md` (một dòng Change Log, TRÊN CÙNG bảng)

**Interfaces:** không produce code — task tài liệu + cổng.

- [ ] **Step 1: Sửa docstring `workspace/repo.py`**

Đầu file, câu «BA BẢNG MODULE NÀY GHI: `control.tenants` · `control.tenant_verticals` · `control.audit_log` (qua `core/nhat_ky.py`).» — thêm ngay sau nó một câu:

```
`tenant_verticals` có NGƯỜI GHI THỨ HAI từ 2026-08-21: `modules/linh_vuc`
(công tắc màn /domains) INSERT/DELETE hàng theo thao tác người dùng — hàng
mà `them_vertical` ghi lúc tạo workspace có thể biến mất sau đó, đừng coi
«tạo xong là luôn có hàng realestate» là bất biến.
```

Docstring `them_vertical` — thay câu cuối «từ giờ nó là câu trả lời cấp-dữ liệu cho "workspace này lĩnh vực gì" TRƯỚC khi có config draft đầu tiên.» bằng:

```
từ giờ nó là câu trả lời cấp-dữ liệu cho "workspace này lĩnh vực gì" TRƯỚC
khi có config draft đầu tiên. Từ 2026-08-21 bảng còn một người ghi nữa —
`modules/linh_vuc` (bật/tắt từ màn /domains), nên hàng này là TRẠNG THÁI
ĐẦU, không phải bất biến.
```

- [ ] **Step 2: Thêm dòng Change Log CLAUDE.md** (trên cùng bảng, ngày 2026-08-21)

```
| 2026-08-21 | **Backend màn «Quản lý lĩnh vực»** — module mới `modules/linh_vuc`, 2 route `GET/PATCH /api/v1/linh-vuc` (spec `2026-08-21-backend-linh-vuc-design.md`). Hợp đồng FE định trước 2026-08-08 (`features/agent/linhVuc.ts` — `ma`/`ten`/`bat`/`soKyNang`/`coDuLieu`, GET trả mảng TRẦN), backend chưa từng có, màn `/domains` 404 dưới `VITE_MSW=0`. Trạng thái bật/tắt = SỰ HIỆN DIỆN của hàng `control.tenant_verticals` (bảng có sẵn từ `0002`, đúng nghĩa gốc «lĩnh vực đang bật») — PATCH bật `INSERT ON CONFLICT DO NOTHING`, tắt `DELETE`; bảng này vì thế có NGƯỜI GHI THỨ HAI ngoài `workspace/repo.them_vertical`. Migration `0944` backfill `realestate` cho tenant tạo trước 2026-08-15 (`them_vertical` mới chạy từ ngày đó) — thiếu là khối BĐS biến khỏi nav workspace cũ ngay khi ship; downgrade no-op có chủ ý (không phân biệt được hàng backfill với hàng thật). Ánh xạ `ma` FE ↔ `vertical` DB (`bds↔realestate`, `taichinh↔finance`) là sổ hằng trong `so.py` — CHECK 0002 chỉ nhận hai giá trị sau, FE nav đóng băng hai giá trị trước. `soKyNang` SUY từ sổ kỹ năng (`12 − 3` chung `kb_search`/`update_customer`/`escalate` — khai ở module, test đối chiếu ⊆ `TEN_KY_NANG`; ⚠️ ngày có kỹ năng finance phải chuyển sang gắn nhãn từng kỹ năng). `coDuLieu` của bds: EXISTS dự án published LOẠI sentinel `__ALL__` (row hệ thống luôn published — không loại thì trường thành hằng true). Quyền GET `AGENT_CONFIG_READ` / PATCH `AGENT_CONFIG_WRITE`; nhật ký `linh_vuc.bat`/`linh_vuc.tat` cùng transaction. RANH GIỚI CỐ Ý: gating kỹ năng vẫn ở FE lúc «Lưu và áp dụng»; ingest KHÔNG đọc bảng này — tắt lĩnh vực không chặn cổng nạp. |
```

- [ ] **Step 3: Cổng toàn repo**

Run: `make check`
Expected: KHÔNG thêm đỏ mới so với baseline develop (đo baseline TRƯỚC bằng cách xem CLAUDE.md/ledger; nếu nghi ngờ, chạy trên `a97f055` các file đỏ để đối chứng). `tests/modules/linh_vuc` xanh toàn bộ.

Run: `make test-isolation`
Expected: XANH như baseline.

- [ ] **Step 4: Commit**

```bash
git add src/portal/modules/workspace/repo.py CLAUDE.md
git commit -m "docs: tenant_verticals co nguoi ghi thu hai + change log linh_vuc"
```

---

### Sau khi đủ 5 task (controller làm, KHÔNG phải subagent)

1. Review cuối toàn nhánh (whole-branch review) theo subagent-driven-development.
2. E2E tay trên stack thật: `make api` (restart nếu process cũ đang chạy — kiểm `ps aux | grep uvicorn`; bài học worker cũ nẫng job của đợt /kb), FE `VITE_MSW=0` tại `localhost:5273`, đăng nhập `dang@anphuland.vn`/`odyssey-dev`, mở `/domains`: danh sách hiện đúng 2 lĩnh vực, công tắc đổi và GIỮ sau reload, tắt bds → khối BĐS rời panel Agent ngay.
3. `superpowers:finishing-a-development-branch` — push + MR vào develop.
4. Cập nhật memory `kb-files-endpoint-bi-xoa-khi-merge.md` (vế «/domains chưa có backend» hết đúng) sau khi MR mở.
