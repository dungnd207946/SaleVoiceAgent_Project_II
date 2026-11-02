# M7 — Màn Hội thoại: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng màn `convos` — danh sách khách nhóm theo số điện thoại, bấm vào một khách ra các phiên của người đó và transcript từng phiên. Chỉ xem.

**Architecture:** Module backend mới `portal.modules.ops` phơi 3 endpoint GET đọc `tenant_data.conversations` (phiên) + `tenant_data.conversation_messages` (lượt nói, migration `0915`). Frontend thêm `features/ops` với hai route drill-down (`/convos` → `/convos/$phone`), dữ liệu qua React Query, fake qua MSW.

**Tech Stack:** FastAPI + asyncpg + Pydantic (BE, repo `odyssey-portal-backend`) · React 18 + TanStack Router/Query + Tailwind 4 + MSW + Vitest (FE, repo `odyssey-portal-frontend`).

**Spec:** `docs/superpowers/specs/2026-08-06-m7-man-hoi-thoai-design.md` — đọc §2.1, §3.1, §3.2 trước Task 1.

## Global Constraints

- **Hai repo.** Task 1–3 ở `odyssey-portal-backend`. Task 4–7 ở `odyssey-portal-frontend`. Mỗi task ghi rõ repo ở đầu.
- **Mọi truy vấn `tenant_data` đi qua `tenant_conn(pool, p.tenant_id)`, trong một giao dịch, VÀ mang `WHERE tenant_id = portal.current_tenant()`.** RLS đã bị dỡ (`0909`) rồi bật lại (`0913`) trong cùng một ngày — đừng dựa vào nó là lớp duy nhất.
- **`tenant_id` KHÔNG BAO GIỜ đến từ path/query/body.** Chỉ từ `Principal.tenant_id`.
- **Mọi endpoint khai `require(ACTIONS.CONVOS_READ)`.** Không endpoint nào dùng `CONVOS_TRANSCRIPT_READ` — quyết định 06/08, xem spec §3.1.
- **Module chỉ import `portal.core.*`.** Import ruột module khác ⇒ `tests/test_module_boundaries.py` đỏ.
- **Không POST/PATCH/DELETE.** Màn này chỉ xem.
- **Ruff line-length 120.** `make check` (lint + test) phải xanh trước mỗi commit BE.
- **FE typecheck bằng `npm run build`**, KHÔNG phải `tsc --noEmit` (tsconfig solution-style, `--noEmit` pass rỗng).
- **Đặt tên tiếng Việt không dấu** cho hàm/biến nội bộ (`liet_ke_khach`, `doc_luot`), **camelCase tiếng Việt không dấu** cho field DTO (`soPhien`, `ganNhat`) — khớp `realestate`.
- **DTO là hợp đồng chép tay hai bên.** Đổi tên field ở `contracts.py` thì phải đổi ở `features/ops/api.ts` cùng commit.

---

## File Structure

**Backend** (`odyssey-portal-backend`)

| Tệp | Trách nhiệm |
|---|---|
| `src/portal/modules/ops/__init__.py` | Rỗng — đánh dấu package |
| `src/portal/modules/ops/contracts.py` | Hằng số phân trang + 5 DTO. Không có logic |
| `src/portal/modules/ops/repo.py` | 4 hàm SQL thuần. Không biết HTTP, không biết Pydantic |
| `src/portal/modules/ops/router.py` | 3 endpoint. Ánh xạ `Record` → DTO, không có SQL |
| `tests/modules/ops/conftest.py` | Workspace + user + client đã đăng nhập |
| `tests/modules/ops/test_repo.py` | Cổng cho SQL: nhóm, sắp xếp, lọc, đếm |
| `tests/modules/ops/test_api.py` | Cổng cho HTTP: quyền, 404, cách ly tenant |

**Frontend** (`odyssey-portal-frontend`)

| Tệp | Trách nhiệm |
|---|---|
| `src/features/ops/api.ts` | 3 hàm gọi + kiểu. Không JSX |
| `src/features/ops/thoiGian.ts` | Hàm thuần định dạng thời gian. Không React |
| `src/features/ops/msw.ts` | Handler giả cho 3 endpoint |
| `src/features/ops/components/KhachRow.tsx` | Một hàng khách |
| `src/features/ops/components/KhachList.tsx` | Thanh lọc + danh sách + rỗng/lỗi/tải |
| `src/features/ops/components/Transcript.tsx` | Các lượt nói + dòng công cụ |
| `src/features/ops/components/PhienKhach.tsx` | Header khách + cột phiên + `<Transcript/>` |
| `src/routes/_app/convos.tsx` | Route `/convos` |
| `src/routes/_app/convos.$phone.tsx` | Route `/convos/$phone` |
| `tests/convos-list.test.tsx` · `tests/convos-phien.test.tsx` · `tests/convos-thoigian.test.ts` | Cổng FE |

---

## Task 1: Contracts + repo — nhóm khách theo số điện thoại

**Repo:** `odyssey-portal-backend`

**Files:**
- Create: `src/portal/modules/ops/__init__.py`
- Create: `src/portal/modules/ops/contracts.py`
- Create: `src/portal/modules/ops/repo.py`
- Create: `tests/modules/ops/__init__.py`
- Create: `tests/modules/ops/conftest.py`
- Create: `tests/modules/ops/test_repo.py`

**Interfaces:**
- Consumes: `portal.core.db.session.tenant_conn`
- Produces:
  - `contracts.TRANG_MAC_DINH: int = 50` · `contracts.GIOI_HAN_TRANG: int = 200` · `contracts.PHONE_TRONG: str = "_"`
  - `contracts.KhachOut` · `contracts.TrangKhach` (Task 3 dùng)
  - `repo.liet_ke_khach(conn, *, tim: str = "", tu_ngay: str = "30", da_chuyen: bool = False, limit: int = 50, offset: int = 0) -> list[asyncpg.Record]`
  - `repo.dem_tong(conn, *, tim: str = "", tu_ngay: str = "30", da_chuyen: bool = False) -> tuple[int, int]` → `(tổng khách, tổng phiên)`

- [ ] **Step 1: Tạo package rỗng và conftest**

`src/portal/modules/ops/__init__.py` — tệp rỗng.
`tests/modules/ops/__init__.py` — tệp rỗng.

`tests/modules/ops/conftest.py`:

```python
"""Fixture của M7 — cùng nếp tests/modules/realestate/conftest.py.

Không mock `tenant_conn()`: nó là seam của cách ly, mock nó thì test xanh cho cả
một truy vấn quên `WHERE tenant_id`.
"""

from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"
TENANT = "opsw"
TENANT_KHAC = "opsx"


@pytest.fixture
async def workspace_ops(pool: asyncpg.Pool):
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for t, ten in ((TENANT, "Ops Workspace"), (TENANT_KHAC, "Ops Khac")):
            await conn.execute("INSERT INTO control.tenants (id, name, org_id) VALUES ($1, $2, 'noble')", t, ten)
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash, org_id) VALUES ($1,$2,$3,$4,'noble')",
            "u_ops",
            "Đăng",
            "dang@ops.vn",
            bam(MAT_KHAU),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE org_id = 'noble' AND name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id, org_id) VALUES ('u_ops',$1,$2,'noble')",
            TENANT,
            r_admin,
        )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = 'u_ops'")


@pytest.fixture
async def conn_ops(pool: asyncpg.Pool, workspace_ops: str):
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, workspace_ops) as conn:
        yield conn


def luc(ngay: int, gio: int = 10) -> datetime:
    """Mốc thời gian tất định — KHÔNG dùng now() trong test.

    now() làm ca «7 ngày qua» đỏ vào đúng ngày thứ 8 sau khi ai đó viết test, và
    người sửa sẽ nghĩ mình vừa làm hỏng bộ lọc.
    """
    return datetime(2026, 7, ngay, gio, 0, tzinfo=UTC)


def cach_day(so_ngay: float) -> datetime:
    """Mốc TƯƠNG ĐỐI so với `now()` — chỉ dùng cho test bộ lọc thời gian.

    Bộ lọc so với `now()` của Postgres, nên một mốc cố định như `luc(27)` sẽ đổi
    nghĩa mỗi ngày trôi qua: hôm nay nó nằm trong «30 ngày», tháng sau thì không.
    Test viết bằng `luc()` cho bộ lọc thời gian là test tự hỏng theo lịch.
    """
    return datetime.now(UTC) - timedelta(days=so_ngay)


async def them_phien(
    conn: asyncpg.Connection,
    session_id: str,
    *,
    tenant: str = TENANT,
    phone: str | None = "0912448111",
    ten: str | None = "Minh Anh",
    summary: str | None = "Hỏi căn 3PN",
    du_an: str | None = "Ocean Park 2",
    chuyen: bool = False,
    bat_dau: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.conversations
            (tenant_id, session_id, phone, customer_name, summary, project,
             transferred_to_sales, started_at, created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8, COALESCE($8, now()))
        """,
        tenant,
        session_id,
        phone,
        ten,
        summary,
        du_an,
        chuyen,
        bat_dau or luc(27),
    )


async def them_luot(
    conn: asyncpg.Connection,
    session_id: str,
    seq: int,
    *,
    tenant: str = TENANT,
    role: str = "user",
    content: str = "xin chào",
    tao_luc: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.conversation_messages
            (tenant_id, session_id, seq, role, content, created_at)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        tenant,
        session_id,
        seq,
        role,
        content,
        tao_luc or luc(27),
    )
```

- [ ] **Step 2: Viết test đỏ cho `liet_ke_khach`**

`tests/modules/ops/test_repo.py`:

```python
"""Cổng cho SQL của M7. Mỗi test neo một lỗi im lặng cụ thể, không phải "kiểm tra hàm chạy"."""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT, TENANT_KHAC, cach_day, luc, them_luot, them_phien

pytestmark = pytest.mark.asyncio


async def test_ba_phien_cung_so_gop_thanh_mot_hang(conn_ops):
    for i in range(3):
        await them_phien(conn_ops, f"s{i}", phone="0912448111", bat_dau=luc(20 + i))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert len(hang) == 1
    assert hang[0]["phone"] == "0912448111"
    assert hang[0]["so_phien"] == 3


async def test_ten_lay_cua_phien_moi_nhat_khong_phai_max(conn_ops):
    """Ca chốt: `max(customer_name)` trả 'Zũng' vì Z > A. Đúng phải là 'An' — phiên mới hơn."""
    await them_phien(conn_ops, "cu", ten="Zũng", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", ten="An", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["ten"] == "An"


async def test_phien_khong_co_ten_khong_xoa_ten_da_biet(conn_ops):
    await them_phien(conn_ops, "co_ten", ten="An", bat_dau=luc(14))
    await them_phien(conn_ops, "khong_ten", ten=None, bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["ten"] == "An"


async def test_phone_null_gop_thanh_nhom_khoa_rong(conn_ops):
    await them_phien(conn_ops, "an1", phone=None)
    await them_phien(conn_ops, "an2", phone=None)
    await them_phien(conn_ops, "co_so", phone="0912448111")

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")
    theo_phone = {r["phone"]: r for r in hang}

    assert theo_phone[""]["so_phien"] == 2
    assert theo_phone["0912448111"]["so_phien"] == 1


async def test_da_chuyen_dung_bool_or_khong_phai_phien_cuoi(conn_ops):
    await them_phien(conn_ops, "cu", chuyen=True, bat_dau=luc(14))
    await them_phien(conn_ops, "moi", chuyen=False, bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["da_chuyen"] is True


async def test_q_chua_phan_tram_khong_khop_toan_bo(conn_ops):
    await them_phien(conn_ops, "s1", phone="0912448111")

    hang = await repo.liet_ke_khach(conn_ops, tim="%", tu_ngay="all")

    assert hang == []


async def test_q_chua_gach_duoi_khong_khop_moi_ky_tu_don(conn_ops):
    await them_phien(conn_ops, "s1", phone="0912448111", ten="An")

    hang = await repo.liet_ke_khach(conn_ops, tim="_", tu_ngay="all")

    assert hang == []


async def test_sap_theo_phien_gan_nhat_giam_dan(conn_ops):
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", phone="0900000002", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert [r["phone"] for r in hang] == ["0900000002", "0900000001"]


async def test_khong_thay_hang_cua_tenant_khac(conn_ops):
    await them_phien(conn_ops, "cua_toi", tenant=TENANT, phone="0900000001")
    await them_phien(conn_ops, "cua_ho", tenant=TENANT_KHAC, phone="0900000002")

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert [r["phone"] for r in hang] == ["0900000001"]


async def test_dem_tong_tra_ca_so_khach_va_so_phien(conn_ops):
    await them_phien(conn_ops, "a1", phone="0900000001")
    await them_phien(conn_ops, "a2", phone="0900000001")
    await them_phien(conn_ops, "b1", phone="0900000002")

    so_khach, so_phien = await repo.dem_tong(conn_ops, tu_ngay="all")

    assert (so_khach, so_phien) == (2, 3)


# ─── Bộ lọc chạy ở mức NHÓM, không mức hàng ────────────────────────────────
# Bốn test dưới đây canh đúng một lớp lỗi: lọc trước khi gom thì con số trả về
# vẫn "hợp lý" nên không ai nhìn ra. Xem docstring `_dieu_kien_thoi_gian`.


async def test_loc_7_ngay_van_dem_du_phien_cu_cua_khach(conn_ops):
    """Khách vừa nhắn 2 hôm trước, còn một phiên 40 ngày trước ⇒ «2 phiên».

    Lọc ở WHERE thì ra «1 phiên» — đúng kiểu con số sai mà trông hợp lý.
    """
    await them_phien(conn_ops, "moi", phone="0900000001", bat_dau=cach_day(2))
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=cach_day(40))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="7")

    assert len(hang) == 1
    assert hang[0]["so_phien"] == 2


async def test_loc_7_ngay_bo_khach_lau_khong_nhan(conn_ops):
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=cach_day(40))

    assert await repo.liet_ke_khach(conn_ops, tu_ngay="7") == []


async def test_mac_dinh_30_ngay_bo_khach_cu_hon(conn_ops):
    """Nhánh mặc định `"30"` — không truyền `tu_ngay` thì phải là 30 ngày."""
    await them_phien(conn_ops, "trong_han", phone="0900000001", bat_dau=cach_day(10))
    await them_phien(conn_ops, "qua_han", phone="0900000002", bat_dau=cach_day(40))

    hang = await repo.liet_ke_khach(conn_ops)

    assert [r["phone"] for r in hang] == ["0900000001"]


async def test_tim_ten_cu_van_hien_du_ca_nhom(conn_ops):
    """Gõ tên CŨ vẫn ra hồ sơ đầy đủ: tên mới nhất, đủ số phiên.

    Quyết định của chủ sản phẩm 06/08: trúng một phiên là hiện cả người.
    """
    await them_phien(conn_ops, "cu", phone="0900000001", ten="Zũng", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", phone="0900000001", ten="An", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tim="Zũng", tu_ngay="all")

    assert len(hang) == 1
    assert hang[0]["ten"] == "An"
    assert hang[0]["so_phien"] == 2


async def test_dem_tong_dem_tren_tap_da_loc(conn_ops):
    """Bỏ `WHERE`/`HAVING` khỏi câu đếm thì test cũ vẫn xanh — test này thì không."""
    await them_phien(conn_ops, "a1", phone="0900000001", ten="An")
    await them_phien(conn_ops, "a2", phone="0900000001", ten="An")
    await them_phien(conn_ops, "b1", phone="0900000002", ten="Bảo")

    assert await repo.dem_tong(conn_ops, tim="An", tu_ngay="all") == (1, 2)
    assert await repo.dem_tong(conn_ops, tu_ngay="all") == (2, 3)
```

- [ ] **Step 3: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.ops.repo'`

- [ ] **Step 4: Viết `contracts.py`**

```python
"""Hợp đồng của M7 — hằng số phân trang và DTO. Không logic, không SQL.

Field DTO đặt camelCase không dấu vì chúng là hợp đồng với FE (`features/ops/api.ts`
chép tay theo tệp này). Đổi tên ở đây mà không đổi bên kia thì màn hiện `undefined`
chứ không nổ — nên đổi thì đổi cùng commit.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "GIOI_HAN_TRANG",
    "PHONE_TRONG",
    "TRANG_MAC_DINH",
    "ChiTietPhienOut",
    "KhachOut",
    "LuotOut",
    "PhienOut",
    "TrangKhach",
]

TRANG_MAC_DINH = 50
GIOI_HAN_TRANG = 200

# Nhóm «Chưa có số» đi trên đường dẫn bằng ký tự này. KHÔNG dùng chuỗi rỗng: nó
# không đi qua được path param của Starlette (`/convos//phien` là một đường khác).
# `_` không thể là số điện thoại thật nên không đụng nhóm nào.
PHONE_TRONG = "_"


class KhachOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: `""` = nhóm «Chưa có số». KHÔNG phải null — nó là khoá nhóm, luôn có mặt.
    phone: str
    ten: str | None
    soPhien: int
    ganNhat: datetime
    dauTien: datetime
    daChuyen: bool
    summaryCuoi: str | None
    duAn: str | None


class TrangKhach(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[KhachOut]
    #: Hai số ở góc phải thanh lọc — tính TRÊN tập đã lọc, không phải tổng toàn bảng.
    tongKhach: int
    tongPhien: int


class PhienOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    sessionId: str
    #: `customer_name` của CHÍNH phiên này — header màn chi tiết lấy của phiên mới nhất.
    ten: str | None
    batDau: datetime | None
    ketThuc: datetime | None
    #: Số hàng `conversation_messages`. `0` là hợp lệ — phiên chưa có lượt nào.
    soLuot: int
    summary: str | None
    duAn: str | None
    daChuyen: bool
    runningVersion: int | None


class LuotOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    #: KHÔNG phải enum. `0915` cố ý không có CHECK — giá trị lạ vẫn phải đi qua đây.
    role: str
    content: str
    taoLuc: datetime
    meta: dict


class ChiTietPhienOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    phien: PhienOut
    luot: list[LuotOut]
    #: `conversations.skill_calls` — NGUỒN DỰ PHÒNG (spec §2.1). FE chỉ dùng khi
    #: không lượt nào mang `meta.tool_calls`. Chỉ có ở endpoint chi tiết, KHÔNG có
    #: ở danh sách phiên: nó là dữ liệu của một phiên đang mở, không phải của 6 phiên.
    skillCalls: list
```

- [ ] **Step 5: Viết `repo.py` (phần khách)**

```python
"""SQL của M7. Không biết HTTP, không biết Pydantic — trả `asyncpg.Record` thô.

MỌI câu ở đây mang `tenant_id = portal.current_tenant()`. RLS đã bị dỡ (`0909`) rồi
bật lại (`0913`) trong đúng một ngày; một lớp là một điểm chết.
"""

import asyncpg

# Bộ lọc thời gian — ánh xạ ĐÓNG. Không nhận số tuỳ ý từ query để tránh một
# `tu_ngay` lạ lọt thẳng vào chuỗi SQL.
_KHOANG = {"7": "7 days", "30": "30 days", "all": None}


def _dieu_kien_thoi_gian(tu_ngay: str) -> str:
    """Điều kiện cho HAVING, KHÔNG cho WHERE.

    Spec §3.3: bộ lọc thời gian đi theo `gan_nhat` — mốc gần nhất của cả NHÓM.
    Đặt nó ở WHERE thì nó lọc từng HÀNG trước khi gom, và một khách có phiên mới
    3 hôm trước cộng hai phiên tháng trước sẽ hiện «1 phiên» thay vì «3 phiên».
    Con số sai đó trông hoàn toàn hợp lý, nên không ai phát hiện.
    """
    khoang = _KHOANG.get(tu_ngay, _KHOANG["30"])
    if khoang is None:
        return "TRUE"
    return f"max(COALESCE(started_at, created_at)) >= now() - interval '{khoang}'"


def _escape_like(s: str) -> str:
    """`%` và `_` người dùng gõ phải là ký tự thường, không phải ký tự đại diện.

    Không có hàm này thì gõ `%` khớp toàn bộ dữ liệu và gõ `_` khớp mọi ký tự đơn —
    người dùng chỉ thấy "bộ lọc hỏng", không thấy vì sao.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# WHERE chỉ còn đúng một việc: cách ly tenant. MỌI bộ lọc của người dùng nằm ở
# HAVING, vì cả ba đều là câu hỏi về một KHÁCH, không phải về một phiên:
#   «khách này có phiên nào trong 7 ngày qua chưa»
#   «khách này có phiên nào đã chuyển sales chưa»
#   «khách này có phiên nào mang từ khoá đang tìm chưa»
# Trả lời chúng ở WHERE là trả lời một câu hỏi khác — câu về từng phiên — rồi gom
# kết quả lại và gọi đó là hồ sơ của khách.
_LOC = "tenant_id = portal.current_tenant()"

_HAVING = """
    ({thoi_gian})
AND (NOT $3 OR bool_or(transferred_to_sales))
AND ($1 = '' OR bool_or(phone ILIKE '%' || $2 || '%' ESCAPE '\\'
                     OR customer_name ILIKE '%' || $2 || '%' ESCAPE '\\'))
"""

_MOI_NHAT = "ORDER BY COALESCE(started_at, created_at) DESC"


async def liet_ke_khach(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Một hàng một khách, sắp theo phiên gần nhất.

    `array_agg(... ORDER BY ...)[1]` chứ KHÔNG `max()`: cần giá trị của phiên MỚI
    NHẤT, không phải giá trị lớn nhất theo thứ tự chữ cái. `max(customer_name)`
    chạy được, không báo lỗi, và trả tên sai.

    `FILTER (WHERE ... IS NOT NULL)` để một phiên bỏ trống trường không đẩy NULL lên
    đầu mảng và xoá mất giá trị đã biết từ phiên trước.
    """
    sql = f"""
        SELECT COALESCE(phone, '')                                  AS phone,
               count(*)                                             AS so_phien,
               max(COALESCE(started_at, created_at))                AS gan_nhat,
               min(COALESCE(started_at, created_at))                AS dau_tien,
               bool_or(transferred_to_sales)                        AS da_chuyen,
               (array_agg(customer_name {_MOI_NHAT})
                  FILTER (WHERE customer_name IS NOT NULL))[1]      AS ten,
               (array_agg(summary {_MOI_NHAT})
                  FILTER (WHERE summary IS NOT NULL AND summary <> ''))[1] AS summary_cuoi,
               (array_agg(project {_MOI_NHAT})
                  FILTER (WHERE project IS NOT NULL))[1]            AS du_an
          FROM tenant_data.conversations
         WHERE {_LOC}
         GROUP BY 1
        HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
         ORDER BY gan_nhat DESC
         LIMIT $4 OFFSET $5
    """
    return list(await conn.fetch(sql, tim, _escape_like(tim), da_chuyen, limit, offset))


async def dem_tong(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
) -> tuple[int, int]:
    """`(số khách, số phiên)` TRÊN TẬP ĐÃ LỌC — không phải tổng toàn bảng.

    Hai con số này hiện cạnh thanh lọc; nếu đếm toàn bảng thì lọc xong con số không
    đổi và người dùng tưởng bộ lọc không chạy.
    """
    sql = f"""
        SELECT count(*) AS so_khach, COALESCE(sum(n), 0) AS so_phien
          FROM (
            SELECT count(*) AS n
              FROM tenant_data.conversations
             WHERE {_LOC}
             GROUP BY COALESCE(phone, '')
            HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
          ) t
    """
    r = await conn.fetchrow(sql, tim, _escape_like(tim), da_chuyen)
    return int(r["so_khach"]), int(r["so_phien"])
```

- [ ] **Step 6: Chạy test — phải XANH**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_repo.py -v`
Expected: PASS — 15 test.

- [ ] **Step 7: Lint và commit**

```bash
cd odyssey-portal-backend
uv run ruff format . && uv run ruff check .
git add src/portal/modules/ops tests/modules/ops
git commit -m "M7: contracts + repo nhóm khách theo số điện thoại"
```

---

## Task 2: Repo — phiên của một khách và transcript

**Repo:** `odyssey-portal-backend`

**Files:**
- Modify: `src/portal/modules/ops/repo.py` (thêm 3 hàm vào cuối)
- Modify: `tests/modules/ops/test_repo.py` (thêm test vào cuối)

**Interfaces:**
- Consumes: `repo._LOC` từ Task 1 (không dùng lại — ba hàm này lọc theo `session_id`/`phone`)
- Produces:
  - `repo.liet_ke_phien(conn, *, phone: str | None) -> list[asyncpg.Record]` — `phone=None` ⇒ nhóm «Chưa có số»
  - `repo.doc_phien(conn, session_id: str) -> asyncpg.Record | None`
  - `repo.doc_luot(conn, session_id: str) -> list[asyncpg.Record]`

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `tests/modules/ops/test_repo.py`:

```python
async def test_phien_khong_co_luot_nao_van_hien_voi_so_luot_0(conn_ops):
    """Cổng cho LEFT JOIN. `JOIN` trần làm phiên rỗng biến mất và không ai biết là mất."""
    await them_phien(conn_ops, "rong", phone="0912448111")

    hang = await repo.liet_ke_phien(conn_ops, phone="0912448111")

    assert len(hang) == 1
    assert hang[0]["so_luot"] == 0


async def test_dem_luot_dung_so_luong(conn_ops):
    """Đếm đúng số lượt của một phiên CÓ lượt.

    Lưu ý: test này KHÔNG phân biệt `count(*)` với `count(m.seq)` — `seq` là
    NOT NULL nên với phiên có ≥1 lượt hai cách đếm cho cùng kết quả. Cổng cho
    `count(m.seq)` là `test_phien_khong_co_luot_nao_van_hien_voi_so_luot_0`
    ở trên, nơi LEFT JOIN sinh ra một hàng NULL.
    """
    await them_phien(conn_ops, "co_luot", phone="0912448111")
    for i in range(3):
        await them_luot(conn_ops, "co_luot", i)

    hang = await repo.liet_ke_phien(conn_ops, phone="0912448111")

    assert hang[0]["so_luot"] == 3


async def test_liet_ke_phien_cua_nhom_chua_co_so(conn_ops):
    await them_phien(conn_ops, "an", phone=None)
    await them_phien(conn_ops, "co_so", phone="0912448111")

    hang = await repo.liet_ke_phien(conn_ops, phone=None)

    assert [r["session_id"] for r in hang] == ["an"]


async def test_doc_luot_sap_theo_seq_khong_phai_created_at(conn_ops):
    """Ca chốt: `created_at` ĐẢO NGƯỢC so với `seq`.

    seq 0 mang giờ MUỘN hơn seq 1. Sắp theo `seq` ⇒ ["lượt trước", "lượt sau"];
    sắp theo `created_at` ⇒ thứ tự ngược lại. Đây là điều kiện DUY NHẤT làm test
    này đỏ được khi ai đó đổi `ORDER BY seq` thành `ORDER BY created_at`.

    ⚠️ ĐỪNG đổi hai mốc giờ này thành BẰNG NHAU cho "giống đời thật". Đã đo trên
    chính schema này: PK `(tenant_id, session_id, seq)` làm Postgres index-scan
    theo `seq`, nên khi `created_at` bằng nhau thì `ORDER BY created_at` vẫn trả
    đúng thứ tự `seq` — test xanh cho cả code sai, và cái gate này thành đồ trang
    trí. Giờ đảo ngược là thứ duy nhất phân biệt được hai câu ORDER BY.
    """
    await them_phien(conn_ops, "s1")
    await them_luot(conn_ops, "s1", 1, content="lượt sau", tao_luc=luc(27, 14))
    await them_luot(conn_ops, "s1", 0, content="lượt trước", tao_luc=luc(27, 15))

    luot = await repo.doc_luot(conn_ops, "s1")

    assert [r["content"] for r in luot] == ["lượt trước", "lượt sau"]


async def test_doc_phien_tra_du_cot_man_can(conn_ops):
    """`customer_name` phải đi qua `_COT_PHIEN` — Task 3 dựng `PhienOut.ten` từ nó.

    Không có test này thì việc nó có mặt chỉ được bảo đảm bằng mắt người đọc code.
    """
    await them_phien(conn_ops, "s1", ten="Minh Anh", du_an="Ocean Park 2", chuyen=True)
    await them_luot(conn_ops, "s1", 0)

    r = await repo.doc_phien(conn_ops, "s1")

    assert r is not None
    assert r["customer_name"] == "Minh Anh"
    assert r["project"] == "Ocean Park 2"
    assert r["transferred_to_sales"] is True
    assert r["so_luot"] == 1


async def test_doc_luot_khong_thay_luot_cua_tenant_khac(conn_ops):
    await them_phien(conn_ops, "trung_ten", tenant=TENANT)
    await them_phien(conn_ops, "trung_ten", tenant=TENANT_KHAC)
    await them_luot(conn_ops, "trung_ten", 0, tenant=TENANT, content="của tôi")
    await them_luot(conn_ops, "trung_ten", 0, tenant=TENANT_KHAC, content="của họ")

    luot = await repo.doc_luot(conn_ops, "trung_ten")

    assert [r["content"] for r in luot] == ["của tôi"]


async def test_doc_phien_tra_none_khi_session_khong_thuoc_tenant(conn_ops):
    await them_phien(conn_ops, "cua_ho", tenant=TENANT_KHAC)

    assert await repo.doc_phien(conn_ops, "cua_ho") is None
```

- [ ] **Step 2: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_repo.py -k "luot or phien_khong or nhom_chua" -v`
Expected: FAIL — `AttributeError: module 'portal.modules.ops.repo' has no attribute 'liet_ke_phien'`

- [ ] **Step 3: Thêm ba hàm vào `repo.py`**

```python
_COT_PHIEN = """
    c.session_id, c.customer_name, c.started_at, c.ended_at, c.summary, c.project,
    c.transferred_to_sales, c.running_version
"""


async def liet_ke_phien(conn: asyncpg.Connection, *, phone: str | None) -> list[asyncpg.Record]:
    """Phiên của một khách, mới nhất trên đầu. `phone=None` ⇒ nhóm «Chưa có số».

    LEFT JOIN, KHÔNG `JOIN`: một phiên chưa có lượt nào vẫn phải hiện với
    `so_luot = 0`. `JOIN` trần làm nó biến mất khỏi cột phiên và không có triệu
    chứng nào.

    `count(m.seq)`, KHÔNG `count(*)`: `count(*)` đếm cả hàng NULL mà LEFT JOIN sinh
    ra cho phiên rỗng, và trả `1`.
    """
    return list(
        await conn.fetch(
            f"""
            SELECT {_COT_PHIEN}, count(m.seq) AS so_luot
              FROM tenant_data.conversations c
              LEFT JOIN tenant_data.conversation_messages m
                     ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
             WHERE c.tenant_id = portal.current_tenant()
               AND c.phone IS NOT DISTINCT FROM $1
             GROUP BY {_COT_PHIEN}, c.created_at
             ORDER BY COALESCE(c.started_at, c.created_at) DESC
            """,
            phone,
        )
    )


async def doc_phien(conn: asyncpg.Connection, session_id: str) -> asyncpg.Record | None:
    """Meta của một phiên. `None` ⇒ không thuộc tenant hiệu lực (router đổi thành 404)."""
    return await conn.fetchrow(
        f"""
        SELECT {_COT_PHIEN}, c.phone, c.skill_calls, count(m.seq) AS so_luot
          FROM tenant_data.conversations c
          LEFT JOIN tenant_data.conversation_messages m
                 ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
         WHERE c.tenant_id = portal.current_tenant() AND c.session_id = $1
         GROUP BY {_COT_PHIEN}, c.phone, c.skill_calls, c.created_at
        """,
        session_id,
    )


async def doc_luot(conn: asyncpg.Connection, session_id: str) -> list[asyncpg.Record]:
    """Transcript một phiên, ORDER BY `seq`.

    KHÔNG `ORDER BY created_at`: hai lượt trong cùng một giây có thứ tự xác định
    theo `seq` nhưng KHÔNG theo `created_at`, và transcript sẽ đảo lượt ngẫu nhiên
    giữa hai lần tải. `created_at` chỉ để hiển thị.
    """
    return list(
        await conn.fetch(
            """
            SELECT seq, role, content, created_at, meta
              FROM tenant_data.conversation_messages
             WHERE tenant_id = portal.current_tenant() AND session_id = $1
             ORDER BY seq
            """,
            session_id,
        )
    )
```

`IS NOT DISTINCT FROM` chứ không `=`: với `phone=None` thì `c.phone = NULL` trả NULL (không hàng nào), còn `IS NOT DISTINCT FROM NULL` khớp đúng các hàng NULL. Đây là toàn bộ nhóm «Chưa có số».

- [ ] **Step 4: Chạy toàn bộ test repo — phải XANH**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_repo.py -v`
Expected: PASS — 22 test.

- [ ] **Step 5: Lint và commit**

```bash
cd odyssey-portal-backend
uv run ruff format . && uv run ruff check .
git add src/portal/modules/ops/repo.py tests/modules/ops/test_repo.py
git commit -m "M7 repo: phiên của một khách + transcript theo seq"
```

---

## Task 3: Router — ba endpoint GET

**Repo:** `odyssey-portal-backend`

**Files:**
- Create: `src/portal/modules/ops/router.py`
- Create: `tests/modules/ops/test_api.py`
- Modify: `tests/modules/ops/conftest.py` (thêm fixture `client_ops`)

**Interfaces:**
- Consumes: `contracts.*` và `repo.*` từ Task 1–2 · `portal.core.auth.require.require` · `portal.core.auth.require.lay_pool` · `portal.core.db.session.tenant_conn` · `portal.api.loi`
- Produces: `ROUTER: APIRouter` — `api/registry.py` tự quét, KHÔNG sửa `registry.py` hay `app.py`
- Endpoint: `GET /api/v1/convos/khach` · `GET /api/v1/convos/khach/{phone}/phien` · `GET /api/v1/convos/phien/{session_id}`

- [ ] **Step 1: Thêm fixture client vào `conftest.py`**

```python
@pytest.fixture
async def client_ops(app_client: httpx.AsyncClient, workspace_ops) -> httpx.AsyncClient:
    """Client đã đăng nhập vào workspace `opsw`."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@ops.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r = await app_client.post("/api/v1/me/workspace", json={"tenantId": TENANT})
    assert r.status_code == 200, r.text
    return app_client
```

- [ ] **Step 2: Viết test đỏ**

`tests/modules/ops/test_api.py`:

```python
"""Cổng HTTP của M7 — quyền, hình dạng trả về, 404, cách ly tenant."""

import asyncpg
import httpx
import pytest

from .conftest import TENANT, TENANT_KHAC, them_luot, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-anh", phone="0912448111", ten="Minh Anh", chuyen=True)
        await them_phien(conn, "s-an", phone=None, ten=None)
        await them_phien(conn, "s-ho", tenant=TENANT_KHAC, phone="0999999999")
        await them_luot(conn, "s-anh", 0, role="user", content="Còn căn 3PN nào không em?")
        await them_luot(conn, "s-anh", 1, role="assistant", content="Dạ còn 4 căn ạ.")


async def test_danh_sach_khach_nhom_theo_so(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})

    assert r.status_code == 200
    body = r.json()
    assert body["tongKhach"] == 2
    assert body["tongPhien"] == 2
    phones = {k["phone"] for k in body["items"]}
    assert phones == {"0912448111", ""}


async def test_khach_mang_du_truong_man_can(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})
    anh = next(k for k in r.json()["items"] if k["phone"] == "0912448111")

    assert anh["ten"] == "Minh Anh"
    assert anh["soPhien"] == 1
    assert anh["daChuyen"] is True
    assert anh["duAn"] == "Ocean Park 2"
    assert anh["summaryCuoi"] == "Hỏi căn 3PN"


async def test_phien_cua_khach_khong_mang_noi_dung_luot(client_ops: httpx.AsyncClient, du_lieu):
    """`content` là phần nặng nhất. Endpoint này KHÔNG được kéo nó về."""
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")

    assert r.status_code == 200
    assert r.json()[0]["soLuot"] == 2
    assert "content" not in r.text


async def test_nhom_chua_co_so_di_bang_gach_duoi(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/_/phien")

    assert r.status_code == 200
    assert [p["sessionId"] for p in r.json()] == ["s-an"]


async def test_nhom_chua_co_so_khong_mang_ten_du_phien_co_ghi(
    client_ops: httpx.AsyncClient, pool: asyncpg.Pool, workspace_ops
):
    """Nhóm «Chưa có số» gộp NHIỀU người ẩn danh — gán một cái tên cho nó là nói sai.

    Ca chốt phải có `customer_name` KHÁC NULL trên một phiên `phone IS NULL`. Nếu
    fixture để `ten=None` thì `r["ten"]` vốn đã là None, và xoá hẳn mặt nạ
    `ten=None if r["phone"] == ""` cũng không test nào đỏ — cổng thành đồ trang trí.
    """
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-an-co-ten", phone=None, ten="Ai Đó")

    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})

    nhom_an = next(k for k in r.json()["items"] if k["phone"] == "")
    assert nhom_an["ten"] is None


async def test_so_khong_co_phien_tra_mang_rong_khong_phai_404(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/0900000000/phien")

    assert r.status_code == 200
    assert r.json() == []


async def test_chi_tiet_phien_tra_luot_theo_thu_tu(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-anh")

    assert r.status_code == 200
    body = r.json()
    assert body["phien"]["sessionId"] == "s-anh"
    assert [l["seq"] for l in body["luot"]] == [0, 1]
    assert [l["role"] for l in body["luot"]] == ["user", "assistant"]


async def test_phien_cua_tenant_khac_tra_404(client_ops: httpx.AsyncClient, du_lieu):
    """404 chứ KHÔNG 403: 403 nói cho người ngoài biết session ấy có tồn tại ở đâu đó."""
    r = await client_ops.get("/api/v1/convos/phien/s-ho")

    assert r.status_code == 404


async def test_chua_dang_nhap_bi_chan(app_client: httpx.AsyncClient, workspace_ops):
    r = await app_client.get("/api/v1/convos/khach")

    assert r.status_code == 401


async def test_khong_co_endpoint_ghi_nao(client_ops: httpx.AsyncClient, du_lieu):
    """Màn này chỉ xem. Cổng canh để không ai thêm đường ghi mà không sửa spec.

    Assert đúng `405`, KHÔNG phải `in (404, 405)`: cả hai đường dưới đây đã có route
    GET đăng ký, nên Starlette luôn trả 405 cho sai method. Nhận cả 404 là để ngỏ
    cửa cho ca "route không tồn tại" — tức test vẫn xanh cả khi router chưa lên,
    và nó chứng minh được ít hơn nhiều so với vẻ ngoài.
    """
    for goi in (
        client_ops.post("/api/v1/convos/khach", json={}),
        client_ops.delete("/api/v1/convos/phien/s-anh"),
    ):
        assert (await goi).status_code == 405


async def test_phien_chua_co_luot_nao_tra_mang_rong_khong_404(client_ops: httpx.AsyncClient, du_lieu):
    """Phiên có thật nhưng chưa có lượt nào ⇒ 200 + `luot: []`. Nó chưa có nội dung,
    không phải nó không tồn tại."""
    r = await client_ops.get("/api/v1/convos/phien/s-an")

    assert r.status_code == 200
    assert r.json()["luot"] == []
    assert r.json()["phien"]["soLuot"] == 0
```

- [ ] **Step 3: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_api.py -v`
Expected: FAIL — mọi request trả 404 vì chưa có `router.py`.

- [ ] **Step 4: Viết `router.py`**

```python
"""Endpoint của M7 — màn Hội thoại. Nguồn: docs/superpowers/specs/2026-08-06-m7-man-hoi-thoai-design.md

CHỈ GET. Màn này chỉ xem: không tiếp quản hội thoại, không nhắn cho khách, không
đặt lịch. Ba việc đó thuộc `convos.handle` — một action có trong catalog quyền
nhưng chưa có đường ghi nào phía sau. Dựng endpoint cho chúng bây giờ là hứa một
thứ không bấm được.

CẢ BA ENDPOINT DÙNG `CONVOS_READ`, kể cả endpoint transcript. `CONVOS_TRANSCRIPT_READ`
có trong catalog (migration 0104) nhưng cố ý không gắn vào đâu — quyết định của chủ
sản phẩm 06/08: ai xem được hội thoại thì xem được cả nội dung. Ghi ở đây để lần
sau ai thấy action lơ lửng thì biết là chủ ý.
"""

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.ops import repo
from portal.modules.ops.contracts import (
    GIOI_HAN_TRANG,
    PHONE_TRONG,
    TRANG_MAC_DINH,
    ChiTietPhienOut,
    KhachOut,
    LuotOut,
    PhienOut,
    TrangKhach,
)

ROUTER = APIRouter(tags=["ops"])
"""KHÔNG có prefix chung — `api/app.py` gắn `/api/v1`."""


def _ra_khach(r: asyncpg.Record) -> KhachOut:
    return KhachOut(
        phone=r["phone"],
        # Nhóm «Chưa có số» KHÔNG mang tên dù có phiên nào ghi `customer_name`:
        # nó gộp nhiều người ẩn danh, gán một cái tên cho nó là nói sai.
        ten=None if r["phone"] == "" else r["ten"],
        soPhien=r["so_phien"],
        ganNhat=r["gan_nhat"],
        dauTien=r["dau_tien"],
        daChuyen=r["da_chuyen"],
        summaryCuoi=r["summary_cuoi"],
        duAn=r["du_an"],
    )


def _ra_phien(r: asyncpg.Record) -> PhienOut:
    return PhienOut(
        sessionId=r["session_id"],
        ten=r["customer_name"],
        batDau=r["started_at"],
        ketThuc=r["ended_at"],
        soLuot=r["so_luot"],
        summary=r["summary"],
        duAn=r["project"],
        daChuyen=r["transferred_to_sales"],
        runningVersion=r["running_version"],
    )


def _json(gia_tri: object, khi_hong: object) -> object:
    """`jsonb` do hệ khác ghi. asyncpg trả chuỗi JSON nếu chưa đăng ký codec, nên
    parse ở đây; parse hỏng thì trả `khi_hong` — một `meta` méo của MỘT lượt không
    được làm 500 cả phiên."""
    import json

    if isinstance(gia_tri, str):
        try:
            gia_tri = json.loads(gia_tri)
        except ValueError:
            return khi_hong
    return gia_tri if type(gia_tri) is type(khi_hong) else khi_hong


def _ra_luot(r: asyncpg.Record) -> LuotOut:
    meta = _json(r["meta"], {})
    return LuotOut(
        seq=r["seq"],
        role=r["role"],
        content=r["content"],
        taoLuc=r["created_at"],
        meta=meta,
    )


@ROUTER.get("/convos/khach", response_model=TrangKhach)
async def liet_ke_khach(
    q: str = "",
    tu_ngay: str = Query("30", pattern="^(7|30|all)$"),
    da_chuyen: bool = False,
    limit: int = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG),
    offset: int = Query(0, ge=0),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangKhach:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_khach(conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen, limit=limit, offset=offset)
        so_khach, so_phien = await repo.dem_tong(conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen)
    return TrangKhach(items=[_ra_khach(r) for r in hang], tongKhach=so_khach, tongPhien=so_phien)


@ROUTER.get("/convos/khach/{phone}/phien", response_model=list[PhienOut])
async def liet_ke_phien(
    phone: str,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[PhienOut]:
    """Số không có phiên nào trả MẢNG RỖNG, không 404 — một URL đã gửi cho đồng
    nghiệp vẫn phải mở được."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_phien(conn, phone=None if phone == PHONE_TRONG else phone)
    return [_ra_phien(r) for r in hang]


@ROUTER.get("/convos/phien/{session_id}", response_model=ChiTietPhienOut)
async def doc_phien(
    session_id: str,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChiTietPhienOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        phien = await repo.doc_phien(conn, session_id)
        if phien is None:
            # 404 chứ KHÔNG 403: phân biệt hai mã cho người ngoài biết session ấy
            # có tồn tại ở tenant khác hay không.
            raise loi.khong_thay("Không tìm thấy phiên hội thoại này")
        luot = await repo.doc_luot(conn, session_id)
    # Phiên có thật nhưng chưa có lượt nào ⇒ `luot: []`, KHÔNG 404.
    return ChiTietPhienOut(
        phien=_ra_phien(phien),
        luot=[_ra_luot(r) for r in luot],
        skillCalls=_json(phien["skill_calls"], []),
    )
```

⚠️ Kiểm tên hàm dựng lỗi 404 trong `src/portal/api/loi.py` trước khi chạy — nếu không có `khong_thay`, dùng đúng hàm 404 mà module `realestate` đang gọi và sửa import cho khớp.

- [ ] **Step 5: Chạy test — phải XANH**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops -v`
Expected: PASS — 33 test.

- [ ] **Step 6: Chạy cổng toàn repo**

Run: `cd odyssey-portal-backend && make check`
Expected: lint xanh; test xanh trừ `tests/isolation` đã đỏ sẵn trên `develop` từ `0908`/`0909` (xem CLAUDE.md). Nếu có test nào NGOÀI `tests/isolation` chuyển đỏ, đó là do task này — sửa trước khi commit.

- [ ] **Step 7: Commit**

```bash
cd odyssey-portal-backend
git add src/portal/modules/ops/router.py tests/modules/ops
git commit -m "M7 router: 3 endpoint GET cho màn Hội thoại"
```

---

## Task 4: FE — client HTTP, hàm thời gian, fake MSW

**Repo:** `odyssey-portal-frontend`

**Files:**
- Create: `src/features/ops/api.ts`
- Create: `src/features/ops/thoiGian.ts`
- Create: `src/features/ops/msw.ts`
- Create: `tests/convos-thoigian.test.ts`
- Modify: `src/lib/msw/handlers.ts` (cắm handler mới vào `HANDLERS`)

**Interfaces:**
- Consumes: DTO của Task 1 (`KhachOut` · `TrangKhach` · `PhienOut` · `LuotOut` · `ChiTietPhienOut`)
- Produces:
  - `api.ts`: `interface Khach` · `TrangKhach` · `Phien` · `Luot` · `ChiTietPhien` · `LocKhach`
  - `api.ts`: `danhSachKhach(loc: LocKhach): Promise<TrangKhach>` · `phienCuaKhach(phone: string): Promise<Phien[]>` · `chiTietPhien(sessionId: string): Promise<ChiTietPhien>`
  - `thoiGian.ts`: `gioNgan(iso: string, bayGio?: Date): string` · `thoiLuong(batDau: string | null, ketThuc: string | null): string | null` · `mocNgay(iso: string, bayGio?: Date): MocNgay`
  - `msw.ts`: `opsHandlers: RequestHandler[]`

- [ ] **Step 1: Viết test đỏ cho `thoiGian.ts`**

`tests/convos-thoigian.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { gioNgan, mocNgay, thoiLuong } from '@/features/ops/thoiGian'

/**
 * Mốc dựng theo giờ ĐỊA PHƯƠNG của máy chạy test — KHÔNG viết chuỗi ISO có hậu tố
 * `+07:00`.
 *
 * VÌ SAO: `thoiGian.ts` chia ngày bằng `getFullYear()/getMonth()/getDate()`, mà ba
 * hàm đó đọc theo múi giờ của TIẾN TRÌNH, không theo hậu tố trong chuỗi ISO. Một ca
 * `'2026-07-26T23:50:00+07:00'` là 16:50 ngày 26 dưới `TZ=UTC` — tức nó rơi sang một
 * ngày khác, và test ĐỎ trên code ĐÚNG. Máy dev ở đây chạy Asia/Bangkok nên chuyện
 * đó không lộ ra; container CI thường là UTC. Đã đo: dưới `TZ=UTC`, bốn ca dùng
 * chuỗi `+07:00` đỏ hết dù `thoiGian.ts` không sai một dòng nào.
 *
 * Dựng mốc theo giờ địa phương làm test độc lập múi giờ, VÀ kiểm đúng hợp đồng thật:
 * "hôm nay" là hôm nay theo lịch của người đang xem màn hình.
 *
 * `thang` ở đây đếm từ 1 — `new Date()` đếm tháng từ 0, và đó là một trong những
 * chỗ dễ lệch nhất khi đọc code test.
 */
function luc(nam: number, thang: number, ngay: number, gio: number, phut = 0): Date {
  return new Date(nam, thang - 1, ngay, gio, phut)
}

const iso = (d: Date) => d.toISOString()

const BAY_GIO = luc(2026, 7, 27, 18)

describe('gioNgan', () => {
  it('hôm nay thì chỉ hiện giờ', () => {
    expect(gioNgan(iso(luc(2026, 7, 27, 14, 22)), BAY_GIO)).toBe('14:22')
  })

  it('hôm qua thì nói «hôm qua», không phải một con số ngày', () => {
    expect(gioNgan(iso(luc(2026, 7, 26, 9, 10)), BAY_GIO)).toBe('hôm qua')
  })

  it('trong tuần thì đếm số ngày', () => {
    expect(gioNgan(iso(luc(2026, 7, 24, 9, 10)), BAY_GIO)).toBe('3 ngày trước')
  })

  it('cũ hơn một tuần thì hiện ngày đầy đủ', () => {
    expect(gioNgan(iso(luc(2026, 7, 14, 16, 40)), BAY_GIO)).toBe('14/07/2026')
  })

  // Hai ca dưới đây ĐỨNG SÁT NỬA ĐÊM, và đó là toàn bộ lý do chúng tồn tại.
  // Mọi ca ở trên đều cách nửa đêm vài giờ, nên chúng xanh cho CẢ hai cách tính:
  // đếm theo lịch (đúng) và đếm số giờ trôi qua rồi chia 24 (sai). Không có hai ca
  // này thì `soNgayCach` có thể bị viết lại thành phép chia trần mà không ai đỏ.

  it('qua nửa đêm là «hôm qua», dù mới cách 20 phút', () => {
    // Giết biến thể `Math.floor(elapsed / 86_400_000)`: 20 phút ⇒ 0 ngày ⇒ «hôm nay».
    const rangSang = luc(2026, 7, 27, 0, 10)
    const truoc = iso(luc(2026, 7, 26, 23, 50))
    expect(gioNgan(truoc, rangSang)).toBe('hôm qua')
    expect(mocNgay(truoc, rangSang)).toBe('hom-qua')
  })

  it('cùng ngày lịch nhưng cách gần 24 tiếng vẫn là hôm nay', () => {
    // Giết biến thể `Math.round(elapsed / 86_400_000)`: 23h40 ⇒ 1 ngày ⇒ «hôm qua».
    const toiMuon = luc(2026, 7, 27, 23, 50)
    const sang = iso(luc(2026, 7, 27, 0, 10))
    expect(gioNgan(sang, toiMuon)).toBe('00:10')
    expect(mocNgay(sang, toiMuon)).toBe('hom-nay')
  })
})

describe('thoiLuong', () => {
  it('tính hiệu hai mốc thành m:ss', () => {
    expect(thoiLuong('2026-07-27T14:22:00Z', '2026-07-27T14:23:48Z')).toBe('1:48')
  })

  it('ketThuc null ⇒ null, KHÔNG phải «0:00»', () => {
    // «0:00» là một con số SAI: nó nói cuộc hội thoại dài 0 giây, chứ không nói
    // «chưa biết nó dài bao lâu».
    expect(thoiLuong('2026-07-27T14:22:00Z', null)).toBeNull()
  })

  it('batDau null ⇒ null', () => {
    expect(thoiLuong(null, '2026-07-27T14:23:48Z')).toBeNull()
  })
})

describe('mocNgay', () => {
  it('phân nhóm để danh sách có nhịp', () => {
    expect(mocNgay(iso(luc(2026, 7, 27, 14, 22)), BAY_GIO)).toBe('hom-nay')
    expect(mocNgay(iso(luc(2026, 7, 26, 9, 10)), BAY_GIO)).toBe('hom-qua')
    expect(mocNgay(iso(luc(2026, 7, 23, 9, 10)), BAY_GIO)).toBe('tuan-truoc')
    expect(mocNgay(iso(luc(2026, 6, 1, 9, 10)), BAY_GIO)).toBe('cu-hon')
  })
})
```

- [ ] **Step 2: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-thoigian.test.ts`
Expected: FAIL — không resolve được `@/features/ops/thoiGian`.

- [ ] **Step 3: Viết `thoiGian.ts`**

```ts
/**
 * Định dạng thời gian cho màn Hội thoại. Hàm THUẦN — không React, không `new Date()`
 * ngầm: mọi hàm nhận `bayGio` để test được tất định. Một hàm gọi `Date.now()` bên
 * trong sẽ đỏ vào đúng ngày thứ 8 sau khi ai đó viết test, và người sửa nghĩ mình
 * vừa làm hỏng bộ lọc.
 */

export type MocNgay = 'hom-nay' | 'hom-qua' | 'tuan-truoc' | 'cu-hon'

function dauNgay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function soNgayCach(iso: string, bayGio: Date): number {
  const MOT_NGAY = 86_400_000
  return Math.round((dauNgay(bayGio) - dauNgay(new Date(iso))) / MOT_NGAY)
}

export function gioNgan(iso: string, bayGio: Date = new Date()): string {
  const n = soNgayCach(iso, bayGio)
  if (n <= 0) {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  if (n === 1) return 'hôm qua'
  if (n < 7) return `${n} ngày trước`
  const d = new Date(iso)
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`
}

export function thoiLuong(batDau: string | null, ketThuc: string | null): string | null {
  // Thiếu một trong hai đầu ⇒ KHÔNG có thời lượng. Trả '0:00' ở đây là in ra một
  // con số sai chứ không phải một ô trống trung thực.
  if (!batDau || !ketThuc) return null
  const giay = Math.max(0, Math.round((new Date(ketThuc).getTime() - new Date(batDau).getTime()) / 1000))
  return `${Math.floor(giay / 60)}:${String(giay % 60).padStart(2, '0')}`
}

export function mocNgay(iso: string, bayGio: Date = new Date()): MocNgay {
  const n = soNgayCach(iso, bayGio)
  if (n <= 0) return 'hom-nay'
  if (n === 1) return 'hom-qua'
  if (n < 14) return 'tuan-truoc'
  return 'cu-hon'
}

export const NHAN_MOC: Record<MocNgay, string> = {
  'hom-nay': 'Hôm nay',
  'hom-qua': 'Hôm qua',
  'tuan-truoc': 'Tuần trước',
  'cu-hon': 'Cũ hơn',
}
```

- [ ] **Step 4: Chạy test — phải XANH**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-thoigian.test.ts`
Expected: PASS — 10 test.

- [ ] **Step 5: Viết `api.ts`**

```ts
/**
 * Client HTTP của M7 — màn Hội thoại.
 *
 * Kiểu ở đây là bản chép tay của `modules/ops/contracts.py`. Nguồn là bên Python.
 * Lệch tên field thì màn hiện `undefined` chứ không nổ — nên đổi thì đổi cùng commit.
 */

const GOC = '/api/v1'

export class LoiApi extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function goi<T>(duong: string): Promise<T> {
  const res = await fetch(`${GOC}${duong}`)
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null
    throw new LoiApi(body?.error?.code ?? 'UNKNOWN', body?.error?.message ?? `${duong} → ${res.status}`)
  }
  return (await res.json()) as T
}

/** `''` = nhóm «Chưa có số». Trên đường dẫn nó đi bằng `'_'` — xem `duongDanKhach`. */
export interface Khach {
  readonly phone: string
  readonly ten: string | null
  readonly soPhien: number
  readonly ganNhat: string
  readonly dauTien: string
  readonly daChuyen: boolean
  readonly summaryCuoi: string | null
  readonly duAn: string | null
}

export interface TrangKhach {
  readonly items: readonly Khach[]
  readonly tongKhach: number
  readonly tongPhien: number
}

export interface Phien {
  readonly sessionId: string
  /** `customer_name` của CHÍNH phiên này — header lấy của phiên mới nhất. */
  readonly ten: string | null
  readonly batDau: string | null
  readonly ketThuc: string | null
  readonly soLuot: number
  readonly summary: string | null
  readonly duAn: string | null
  readonly daChuyen: boolean
  readonly runningVersion: number | null
}

/** `role` KHÔNG phải union: `0915` cố ý không có CHECK, giá trị lạ vẫn tới được đây. */
export interface Luot {
  readonly seq: number
  readonly role: string
  readonly content: string
  readonly taoLuc: string
  readonly meta: Record<string, unknown>
}

export interface ChiTietPhien {
  readonly phien: Phien
  readonly luot: readonly Luot[]
  /** Nguồn DỰ PHÒNG — chỉ dùng khi không lượt nào mang `meta.tool_calls`. */
  readonly skillCalls: readonly unknown[]
}

export interface LocKhach {
  readonly q?: string
  readonly tuNgay?: '7' | '30' | 'all'
  readonly daChuyen?: boolean
}

/** Sentinel của nhóm «Chưa có số» — phải khớp `contracts.PHONE_TRONG` bên Python. */
export const PHONE_TRONG = '_'

export function duongDanKhach(phone: string): string {
  return phone === '' ? PHONE_TRONG : phone
}

export async function danhSachKhach(loc: LocKhach = {}): Promise<TrangKhach> {
  const p = new URLSearchParams()
  if (loc.q) p.set('q', loc.q)
  p.set('tu_ngay', loc.tuNgay ?? '30')
  if (loc.daChuyen) p.set('da_chuyen', 'true')
  return goi<TrangKhach>(`/convos/khach?${p.toString()}`)
}

export async function phienCuaKhach(phone: string): Promise<Phien[]> {
  return goi<Phien[]>(`/convos/khach/${encodeURIComponent(phone)}/phien`)
}

export async function chiTietPhien(sessionId: string): Promise<ChiTietPhien> {
  return goi<ChiTietPhien>(`/convos/phien/${encodeURIComponent(sessionId)}`)
}
```

- [ ] **Step 6: Viết `msw.ts` và cắm vào `handlers.ts`**

```ts
/**
 * Fake của M7 — spec §4②: mỗi module ship kèm fake để module khác dev được mà
 * không cần backend chạy.
 *
 * Dữ liệu giả cố ý mang đủ ca biên mà màn phải chịu được: một khách không tên,
 * nhóm «Chưa có số», một phiên 0 lượt, một `role` lạ, và một phiên `ketThuc` NULL.
 * Fake chỉ có ca đẹp thì màn thật vỡ ở đúng những chỗ fake không đi tới.
 */
import { http, HttpResponse } from 'msw'
import type { ChiTietPhien, Phien, TrangKhach } from '@/features/ops/api'

const KHACH_GIA: TrangKhach = {
  tongKhach: 3,
  tongPhien: 5,
  items: [
    {
      phone: '0912448111',
      ten: 'Nguyễn Minh Anh',
      soPhien: 3,
      ganNhat: '2026-07-27T14:22:00+07:00',
      dauTien: '2026-07-14T16:40:00+07:00',
      daChuyen: true,
      summaryCuoi: 'Hỏi căn 3PN dưới 6 tỷ ở Ocean Park 2. Đã chốt lịch xem nhà 10:00 thứ Bảy 01/08.',
      duAn: 'Ocean Park 2',
    },
    {
      phone: '0987112222',
      ten: null,
      soPhien: 1,
      ganNhat: '2026-07-26T11:30:00+07:00',
      dauTien: '2026-07-26T11:30:00+07:00',
      daChuyen: false,
      summaryCuoi: null,
      duAn: null,
    },
    {
      phone: '',
      ten: null,
      soPhien: 1,
      ganNhat: '2026-07-26T09:14:00+07:00',
      dauTien: '2026-07-26T09:14:00+07:00',
      daChuyen: false,
      summaryCuoi: 'Khách chưa để lại số điện thoại.',
      duAn: null,
    },
  ],
}

const PHIEN_GIA: Record<string, Phien[]> = {
  '0912448111': [
    {
      sessionId: 's-anh-1',
      ten: 'Nguyễn Minh Anh',
      batDau: '2026-07-27T14:22:00+07:00',
      ketThuc: '2026-07-27T14:23:48+07:00',
      soLuot: 4,
      summary: 'Hỏi căn 3PN dưới 6 tỷ, chốt lịch xem nhà.',
      duAn: 'Ocean Park 2',
      daChuyen: true,
      runningVersion: 12,
    },
    {
      sessionId: 's-anh-2',
      ten: 'Nguyễn Minh Anh',
      batDau: '2026-07-21T09:10:00+07:00',
      ketThuc: null,
      soLuot: 0,
      summary: null,
      duAn: null,
      daChuyen: false,
      runningVersion: null,
    },
  ],
  _: [
    {
      sessionId: 's-an-1',
      ten: null,
      batDau: '2026-07-26T09:14:00+07:00',
      ketThuc: '2026-07-26T09:15:10+07:00',
      soLuot: 2,
      summary: 'Khách chưa để lại số điện thoại.',
      duAn: null,
      daChuyen: false,
      runningVersion: 12,
    },
  ],
}

const CHI_TIET_GIA: Record<string, ChiTietPhien> = {
  's-anh-1': {
    phien: PHIEN_GIA['0912448111'][0],
    luot: [
      {
        seq: 0,
        role: 'user',
        content: 'Còn căn nào 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 không em?',
        taoLuc: '2026-07-27T14:22:03+07:00',
        meta: {},
      },
      {
        seq: 1,
        role: 'assistant',
        content: 'Dạ hiện Ocean Park 2 còn 4 căn 3PN dưới 6 tỷ ạ. Gần nhất là NT2-1408, 78,4 m², 5,62 tỷ.',
        taoLuc: '2026-07-27T14:22:31+07:00',
        meta: { tool_calls: ['search_units(project=VOP2, max_price=6e9, bedrooms=3) → 4 · 128ms'] },
      },
      {
        seq: 2,
        role: 'he_thong_la',
        content: 'Một role không nằm trong ba giá trị đã biết.',
        taoLuc: '2026-07-27T14:23:00+07:00',
        meta: {},
      },
      { seq: 3, role: 'user', content: '10 giờ nhé em.', taoLuc: '2026-07-27T14:23:40+07:00', meta: {} },
    ],
    skillCalls: [],
  },
  's-anh-2': {
    phien: PHIEN_GIA['0912448111'][1],
    luot: [],
    // Phiên rỗng NHƯNG có skill_calls mức phiên — đúng ca mà nhánh dự phòng sinh ra
    // để phục vụ. Fake không có ca này thì nhánh đó không bao giờ chạy khi dev.
    skillCalls: ['create_appointment(slot=2026-08-01T10:00) → ok'],
  },
}

export const opsHandlers = [
  http.get('/api/v1/convos/khach', () => HttpResponse.json(KHACH_GIA)),
  http.get('/api/v1/convos/khach/:phone/phien', ({ params }) =>
    HttpResponse.json(PHIEN_GIA[String(params.phone)] ?? []),
  ),
  http.get('/api/v1/convos/phien/:sessionId', ({ params }) => {
    const ct = CHI_TIET_GIA[String(params.sessionId)]
    return ct
      ? HttpResponse.json(ct)
      : HttpResponse.json({ error: { code: 'NOT_FOUND', message: 'Không tìm thấy phiên' } }, { status: 404 })
  }),
]
```

Trong `src/lib/msw/handlers.ts`: thêm `import { opsHandlers } from '@/features/ops/msw'` ở đầu tệp, rồi trải `...opsHandlers,` vào mảng `HANDLERS` — một dòng, không sửa gì khác.

- [ ] **Step 7: Typecheck và commit**

```bash
cd odyssey-portal-frontend
npm run build && npx vitest run tests/convos-thoigian.test.ts
git add src/features/ops src/lib/msw/handlers.ts tests/convos-thoigian.test.ts
git commit -m "M7 FE: client HTTP, hàm thời gian, fake MSW"
```

---

## Task 5: FE — màn danh sách khách

**Repo:** `odyssey-portal-frontend`

**Files:**
- Create: `src/features/ops/components/KhachRow.tsx`
- Create: `src/features/ops/components/KhachList.tsx`
- Create: `tests/convos-list.test.tsx`
- Create: `src/routes/_app/convos.$phone.tsx` — **route giữ chỗ**, Task 6 viết ruột. Cần từ task này vì `<Link to="/convos/$phone">` không typecheck nếu route chưa đăng ký.
- Modify: `src/routes/_app/convos.tsx` (bỏ `ScreenStub`)
- Modify: `src/styles/theme.css` (thêm 4 cặp token màu avatar)
- Modify: `tests/nav-registry.test.ts` (cho phép route con có dấu chấm — xem Step 0)

**Interfaces:**
- Consumes: `api.ts` và `thoiGian.ts` của Task 4
- Produces: `<KhachList/>` (không props) · `<KhachRow khach={k} bayGio={d}/>`

- [ ] **Step 0: Token màu avatar + nới cổng nav-registry đúng mức**

Thêm vào khối `@theme` của `src/styles/theme.css`:

```css
  /* Avatar khách của màn Hội thoại — bốn cặp nền/chữ, chọn tất định từ số điện
     thoại (M7 §5.1). Ở ĐÂY chứ không phải trong JSX: mọi mã màu của portal sống
     trong tệp này, và một bảng màu nằm rải trong component là chỗ không ai tìm ra
     vào ngày đổi nhận diện. Cặp 1 trùng giá trị với `acs`/`ac` là cố ý — chúng có
     thể tách nhau ngày mai mà không kéo theo màu nav. */
  --color-av1-bg: #e7f2ee;
  --color-av1-fg: #0d7a5f;
  --color-av2-bg: #f3ecdf;
  --color-av2-fg: #8a6a1f;
  --color-av3-bg: #e9eef3;
  --color-av3-fg: #4a6480;
  --color-av4-bg: #f2e9ee;
  --color-av4-fg: #8a4a68;
```

Trong `tests/nav-registry.test.ts`, cổng "không có tệp route mồ côi" so khớp 1:1 tên
tệp trong `src/routes/_app/` với `SCREENS`. Route con `convos.$phone.tsx` là tệp đầu
tiên có dấu chấm, nên cổng đỏ. Nới nó — nhưng **chỉ đúng mức**:

```ts
// ĐÚNG: chỉ tha tệp có tiền tố trước dấu chấm khớp một màn ĐÃ khai.
.filter(
  (p) => !p.includes('.') || !SCREENS.some((s) => p.slice(1).startsWith(`${s.path.slice(1)}.`)),
)
```

⚠️ ĐỪNG viết `.filter((p) => !p.includes('.'))`. Nó tha MỌI tệp có dấu chấm, vĩnh
viễn — một `foo.bar.tsx` lạc hay một tên gõ nhầm sẽ không bao giờ bị bắt nữa. Cổng
này sinh ra để canh tệp mồ côi; nới tới mức không còn bắt được tệp mồ côi nào thì
nó không còn là cổng.

⚠️ VÀ ĐỪNG BỎ `p.slice(1)` HAY DẤU `!` TRƯỚC `SCREENS.some`. Hai chi tiết đó không
phải tiểu tiết cú pháp, chúng là toàn bộ tác dụng của dòng này:

- `p` mang dấu `/` ở đầu (do `.map` phía trên), `s.path.slice(1)` thì không. So
  `p.startsWith(...)` thẳng luôn cho `false`, nên `SCREENS.some(...)` luôn `false`,
  và cả biểu thức tụt về đúng `!p.includes('.')` — cùng lỗi "tha vĩnh viễn", chỉ
  viết dài hơn để trông như đã sửa. Đây là lỗi có thật: bản đầu của chính đoạn này
  mắc đúng vậy và chỉ lộ ra khi có người tạo tệp mồ côi giả để thử.
- Dấu `!` đảo chiều là cố ý: tệp mồ côi phải **ở lại** danh sách để lệch với
  `SCREENS` mà làm đỏ; tệp con đã khai phải **rời** danh sách để không thành phần
  tử dư.

Cách duy nhất biết dòng này còn sống: tạo `src/routes/_app/rac.mo-coi.tsx` rỗng,
chạy `npx vitest run tests/nav-registry.test.ts`, thấy ĐỎ, rồi xoá đi.

- [ ] **Step 1: Viết test đỏ**

`tests/convos-list.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import type { LocKhach } from '@/features/ops/api'
import { KhachList } from '@/features/ops/components/KhachList'
import { server } from '../vitest.setup'

function dung() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <KhachList />
    </QueryClientProvider>,
  )
}

describe('màn danh sách khách', () => {
  it('hiện tên, số điện thoại và trích summary của từng khách', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    expect(screen.getByText(/0912448111/)).toBeInTheDocument()
    expect(screen.getByText(/chốt lịch xem nhà/i)).toBeInTheDocument()
  })

  it('khách không có tên thì hiện số làm tên, KHÔNG hiện «null»', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument()
    expect(screen.getByText('0987112222')).toBeInTheDocument()
  })

  it('nhóm phone rỗng hiện là «Chưa có số», không phải một cái tên', async () => {
    dung()
    expect(await screen.findByText('Chưa có số')).toBeInTheDocument()
  })

  it('badge «Đã chuyển» chỉ ở khách có daChuyen', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.getAllByText(/đã chuyển/i)).toHaveLength(1)
  })

  it('hiện hai con số tổng cạnh thanh lọc', async () => {
    dung()
    expect(await screen.findByText(/3 khách/)).toBeInTheDocument()
    expect(screen.getByText(/5 phiên/)).toBeInTheDocument()
  })

  it('gõ vào ô tìm thì gọi lại API kèm q — không phải chỉ đổi giá trị ô', async () => {
    // Assert trên REQUEST, không phải trên ô input. Kiểm `input.value === 'Anh'`
    // chỉ chứng minh React giữ state — nó xanh y hệt khi `datLoc` không nối đi đâu.
    const daGoi: string[] = []
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        daGoi.push(new URL(request.url).searchParams.get('q') ?? '')
        return HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 })
      }),
    )
    const loc: LocKhach = {}
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const datLoc = vi.fn()
    render(
      <QueryClientProvider client={qc}>
        <KhachList loc={loc} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await screen.findByText('Chưa có hội thoại nào')
    await userEvent.type(screen.getByPlaceholderText(/tìm tên hoặc số/i), 'Anh')

    // Component KHÔNG tự đổi `loc` — route mới là chủ. Nó phải báo lên qua `datLoc`.
    expect(datLoc).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Anh' }))

    // Và khi route đẩy `loc` mới xuống thì query phải chạy lại với `q`.
    qc.clear()
    render(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ q: 'Anh' }} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(daGoi).toContain('Anh'))
  })

  it('mỗi hàng là một link tới /convos/<phone>, nhóm rỗng đi bằng _', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    const links = screen.getAllByRole('link')
    const href = links.map((a) => a.getAttribute('href'))
    expect(href).toContain('/convos/0912448111')
    expect(href).toContain('/convos/_')
  })

  it('danh sách rỗng ⇒ màn rỗng, KHÔNG phải thông báo lỗi', async () => {
    // Kho rỗng là bình thường. Hiện câu lỗi ở đây làm người vận hành đi báo sự cố
    // cho một hệ thống đang chạy đúng.
    server.use(
      http.get('/api/v1/convos/khach', () => HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 })),
    )
    dung()
    expect(await screen.findByText('Chưa có hội thoại nào')).toBeInTheDocument()
    expect(screen.queryByText(/không tải được/i)).not.toBeInTheDocument()
  })

  it('backend chết ⇒ câu lỗi, KHÔNG phải màn rỗng', async () => {
    server.use(http.get('/api/v1/convos/khach', () => new HttpResponse(null, { status: 500 })))
    dung()
    expect(await screen.findByText(/không tải được danh sách hội thoại/i)).toBeInTheDocument()
    expect(screen.queryByText('Chưa có hội thoại nào')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-list.test.tsx`
Expected: FAIL — không resolve được `@/features/ops/components/KhachList`.

- [ ] **Step 3: Viết `KhachRow.tsx`**

```tsx
/**
 * Một hàng khách — dải ngang trọn chiều rộng, KHÔNG phải hàng bảng.
 *
 * Bốn thứ tách nó khỏi hình dạng "table list" (spec §5.1), đừng bỏ khi dọn CSS:
 * hàng cao để summary giữ 2 dòng · chip nằm DƯỚI summary · vạch accent trái khi
 * hover · mũi › sáng lên. Một hàng bấm được phải nói ra rằng nó bấm được.
 */
import { Link } from '@tanstack/react-router'
import { type Khach, duongDanKhach } from '../api'
import { gioNgan } from '../thoiGian'

/**
 * Màu avatar chọn TẤT ĐỊNH từ phone: cùng số ⇒ cùng màu qua mọi lần tải.
 *
 * Bốn cặp này là TOKEN trong `styles/theme.css`, không phải mã hex viết thẳng vào
 * đây. Một bảng màu nằm rải trong JSX là chỗ không ai tìm ra vào ngày đổi nhận diện.
 */
const MAU = [
  'bg-av1-bg text-av1-fg',
  'bg-av2-bg text-av2-fg',
  'bg-av3-bg text-av3-fg',
  'bg-av4-bg text-av4-fg',
] as const

function mauCua(phone: string): string {
  let n = 0
  for (const c of phone) n = (n + c.charCodeAt(0)) % MAU.length
  return MAU[n]
}

function chuCai(ten: string | null): string {
  if (!ten) return '?'
  const tu = ten.trim().split(/\s+/)
  return (tu.length === 1 ? tu[0].slice(0, 2) : tu[tu.length - 2][0] + tu[tu.length - 1][0]).toUpperCase()
}

export function KhachRow({ khach, bayGio }: { khach: Khach; bayGio?: Date }) {
  const an = khach.phone === ''
  // Không có tên thì DÙNG SỐ làm tên. Hiện chuỗi 'null' hay ô trống đều tệ hơn.
  const ten = an ? 'Chưa có số' : (khach.ten ?? khach.phone)

  return (
    <Link
      to="/convos/$phone"
      params={{ phone: duongDanKhach(khach.phone) }}
      className={`group relative flex items-start gap-4 overflow-hidden rounded-xl border bg-surface px-4 py-4
                  transition hover:border-border-strong hover:shadow-[0_4px_14px_rgba(20,22,26,.07)]
                  ${an ? 'border-dashed bg-transparent' : ''}`}
    >
      <span className="absolute inset-y-0 left-0 w-[3px] bg-ac opacity-0 transition-opacity group-hover:opacity-100" />
      <span
        className={`flex size-[42px] shrink-0 items-center justify-center rounded-full text-[14.5px] font-semibold
                    ${an ? 'bg-border-soft text-muted-3' : mauCua(khach.phone)}`}
      >
        {an ? '?' : chuCai(khach.ten)}
      </span>

      <span className="w-[186px] shrink-0">
        <span className={`block text-[14px] font-semibold ${an ? 'text-muted' : ''}`}>{ten}</span>
        <span className="mt-[3px] block font-mono text-[11.5px] text-muted-2">{an ? '— ẩn danh' : khach.phone}</span>
      </span>

      <span className="min-w-0 flex-1 pr-1.5">
        {khach.summaryCuoi && (
          <span className="line-clamp-2 block text-[12.5px] leading-[1.55] text-muted">{khach.summaryCuoi}</span>
        )}
        <span className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-border-soft px-2 py-[3px] text-[10.5px] font-medium text-muted">
            {khach.duAn ?? 'Chưa rõ dự án'}
          </span>
          {khach.daChuyen && (
            <span className="rounded-full bg-acs px-2 py-[3px] text-[10.5px] font-medium text-acd">
              Đã chuyển sales
            </span>
          )}
        </span>
      </span>

      <span className="w-[132px] shrink-0 pt-0.5 text-right">
        <span className="block font-mono text-[12.5px]">{gioNgan(khach.ganNhat, bayGio)}</span>
        <span className="mt-1 block font-mono text-[11px] text-muted-2">{khach.soPhien} phiên</span>
      </span>

      <span className="self-center text-[15px] text-muted-3 group-hover:text-ac">›</span>
    </Link>
  )
}
```

- [ ] **Step 4: Viết `KhachList.tsx`**

```tsx
/**
 * Màn danh sách khách (spec §5.1). Chỉ xem.
 *
 * Ba bộ lọc nằm ở state cục bộ của component NÀY và được route đẩy lên search
 * param (Task 5 step 6) — không phải hai nguồn sự thật: component nhận giá trị
 * và hàm đặt giá trị từ route.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { type LocKhach, danhSachKhach } from '../api'
import { NHAN_MOC, type MocNgay, mocNgay } from '../thoiGian'
import { KhachRow } from './KhachRow'

const KHOANG: { ma: NonNullable<LocKhach['tuNgay']>; nhan: string }[] = [
  { ma: '7', nhan: '7 ngày' },
  { ma: '30', nhan: '30 ngày' },
  { ma: 'all', nhan: 'Tất cả' },
]

const THU_TU_MOC: MocNgay[] = ['hom-nay', 'hom-qua', 'tuan-truoc', 'cu-hon']

export function KhachList({
  loc = {},
  datLoc,
  bayGio,
}: {
  loc?: LocKhach
  datLoc?: (l: LocKhach) => void
  bayGio?: Date
}) {
  const [nhap, setNhap] = useState(loc.q ?? '')
  const ds = useQuery({ queryKey: ['convos', 'khach', loc], queryFn: () => danhSachKhach(loc) })

  const doi = (p: Partial<LocKhach>) => datLoc?.({ ...loc, ...p })

  if (ds.isPending) return <p className="p-6 text-[13px] text-muted">Đang tải…</p>
  // Hai nguyên nhân, hai câu. Backend chết mà hiện "chưa có hội thoại nào" thì
  // người vận hành ngồi đợi một thứ không bao giờ tới, và không ai báo sự cố.
  if (ds.error) return <p className="p-6 text-[13px]">Không tải được danh sách hội thoại.</p>

  const nhom = new Map<MocNgay, typeof ds.data.items>()
  for (const k of ds.data.items) {
    const m = mocNgay(k.ganNhat, bayGio)
    nhom.set(m, [...(nhom.get(m) ?? []), k])
  }

  return (
    <div className="space-y-4 p-6">
      <h1 className="text-lg font-semibold">Hội thoại</h1>

      <div className="flex flex-wrap items-center gap-3">
        <input
          className="w-[250px] rounded-lg border border-border-field bg-surface px-3 py-2 text-[13px]"
          placeholder="Tìm tên hoặc số điện thoại…"
          value={nhap}
          onChange={(e) => {
            setNhap(e.target.value)
            doi({ q: e.target.value })
          }}
        />
        <div className="flex overflow-hidden rounded-lg border bg-surface text-[12.5px]">
          {KHOANG.map((k) => (
            <button
              key={k.ma}
              type="button"
              onClick={() => doi({ tuNgay: k.ma })}
              className={`border-l px-3 py-[7px] first:border-l-0 ${
                (loc.tuNgay ?? '30') === k.ma ? 'bg-acs font-semibold text-acd' : 'text-muted'
              }`}
            >
              {k.nhan}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[12.5px] text-muted">
          <input type="checkbox" checked={!!loc.daChuyen} onChange={(e) => doi({ daChuyen: e.target.checked })} />
          Chỉ khách đã chuyển sales
        </label>
        <span className="ml-auto font-mono text-[11.5px] text-muted-2">
          {ds.data.tongKhach} khách · {ds.data.tongPhien} phiên
        </span>
      </div>

      {ds.data.items.length === 0 ? (
        // Kho rỗng là BÌNH THƯỜNG — không role="alert", không màu đỏ.
        <div className="rounded-xl border border-dashed bg-surface p-10 text-center">
          <p className="text-[14px] font-semibold">Chưa có hội thoại nào</p>
          <p className="mx-auto mt-1.5 max-w-[440px] text-[12.5px] leading-relaxed text-muted">
            Khi khách bắt đầu nhắn với agent, họ sẽ hiện ở đây — nhóm theo số điện thoại, người nhắn gần nhất lên đầu.
          </p>
        </div>
      ) : (
        THU_TU_MOC.filter((m) => nhom.has(m)).map((m) => (
          <div key={m}>
            <div className="my-4 flex items-center gap-2.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-3">{NHAN_MOC[m]}</span>
              <span className="h-px flex-1 bg-border" />
            </div>
            <div className="flex flex-col gap-2.5">
              {nhom.get(m)!.map((k) => (
                <KhachRow key={k.phone} khach={k} bayGio={bayGio} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
```

- [ ] **Step 5: Chạy test — phải XANH**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-list.test.tsx`
Expected: PASS — 9 test.

- [ ] **Step 6: Nối route `/convos`**

`src/routes/_app/convos.tsx`:

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import type { LocKhach } from '@/features/ops/api'
import { KhachList } from '@/features/ops/components/KhachList'

/**
 * Bộ lọc nằm ở SEARCH PARAM, không phải `useState`: F5 hoặc gửi link cho đồng
 * nghiệp thì vẫn ra đúng danh sách đang xem.
 */
interface TimKiem {
  q?: string
  tu?: '7' | '30' | 'all'
  chuyen?: boolean
}

export const Route = createFileRoute('/_app/convos')({
  validateSearch: (s: Record<string, unknown>): TimKiem => ({
    q: typeof s.q === 'string' ? s.q : undefined,
    tu: s.tu === '7' || s.tu === 'all' ? s.tu : undefined,
    chuyen: s.chuyen === true || s.chuyen === 'true' ? true : undefined,
  }),
  component: ManConvos,
})

function ManConvos() {
  const s = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const loc: LocKhach = { q: s.q, tuNgay: s.tu ?? '30', daChuyen: s.chuyen }

  return (
    <KhachList
      loc={loc}
      datLoc={(l) =>
        void navigate({
          search: { q: l.q || undefined, tu: l.tuNgay === '30' ? undefined : l.tuNgay, chuyen: l.daChuyen || undefined },
          replace: true,
        })
      }
    />
  )
}
```

- [ ] **Step 7: Sinh lại route tree, typecheck, commit**

```bash
cd odyssey-portal-frontend
npm run routes && npm run build && npx vitest run
git add src/features/ops src/routes/_app/convos.tsx src/routeTree.gen.ts tests/convos-list.test.tsx
git commit -m "M7 FE: màn danh sách khách + route /convos"
```

---

## Task 6: FE — màn chi tiết, transcript, mốc giờ theo hover

**Repo:** `odyssey-portal-frontend`

**Files:**
- Create: `src/features/ops/components/Transcript.tsx`
- Create: `src/features/ops/components/PhienKhach.tsx`
- Create: `src/routes/_app/convos.$phone.tsx`
- Create: `tests/convos-phien.test.tsx`
- Modify: `src/styles/theme.css` (thêm `@media (hover:none)` và `prefers-reduced-motion` cho `.moc-gio`)

**Interfaces:**
- Consumes: `api.ts` · `thoiGian.ts` của Task 4
- Produces: `<PhienKhach phone={string}/>` · `<Transcript luot={readonly Luot[]} skillCallsDuPhong={readonly unknown[]}/>`

- [ ] **Step 1: Viết test đỏ**

`tests/convos-phien.test.tsx`:

```tsx
import { readFile } from 'node:fs/promises'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { PhienKhach } from '@/features/ops/components/PhienKhach'
import { server } from '../vitest.setup'

function dung(phone = '0912448111') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PhienKhach phone={phone} />
    </QueryClientProvider>,
  )
}

describe('màn chi tiết một khách', () => {
  it('liệt kê các phiên, mới nhất trên đầu', async () => {
    dung()
    expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
    expect(screen.getByText(/21\/07\/2026/)).toBeInTheDocument()
  })

  it('phiên không có summary hiện «Chưa có tóm tắt», không phải ô trống', async () => {
    dung()
    expect(await screen.findByText(/chưa có tóm tắt/i)).toBeInTheDocument()
  })

  it('ketThuc NULL thì KHÔNG in «0:00» ở đâu cả', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    expect(screen.queryByText('0:00')).not.toBeInTheDocument()
  })

  it('render lượt nói theo đúng thứ tự seq', async () => {
    dung()
    const bong = await screen.findAllByTestId('bong-bong')
    expect(bong[0]).toHaveTextContent('Còn căn nào 3 phòng ngủ')
    expect(bong[1]).toHaveTextContent('Dạ hiện Ocean Park 2 còn 4 căn')
  })

  it('role lạ vẫn HIỆN, và hiện dạng DÒNG HỆ THỐNG chứ không phải bong bóng', async () => {
    // Hai nửa của yêu cầu, phải assert cả hai. Chỉ kiểm "có chữ đó trên màn" thì
    // một regression render nó thành bong bóng chat bình thường vẫn xanh — mà đó
    // đúng là thứ yêu cầu này cấm: `role` lạ không được trông như lời của khách
    // hay của agent.
    dung()
    const dong = await screen.findByText(/một role không nằm trong ba giá trị/i)
    expect(dong).toBeInTheDocument()
    expect(dong).not.toHaveAttribute('data-testid', 'bong-bong')
    expect(dong.className).toContain('text-center')
  })

  it('lượt có meta méo vẫn hiện bong bóng, chỉ mất phần công cụ', async () => {
    // Ghi đè bằng `server.use` chứ không nhét vào fake dùng chung: đây là ca của
    // riêng test này, và fake chung đã mang đủ sáu ca biên khác.
    server.use(
      http.get('/api/v1/convos/phien/:sessionId', () =>
        HttpResponse.json({
          phien: {
            sessionId: 's-meo',
            ten: 'Méo',
            batDau: '2026-07-27T14:22:00+07:00',
            ketThuc: null,
            soLuot: 2,
            summary: null,
            duAn: null,
            daChuyen: false,
            runningVersion: null,
          },
          luot: [
            { seq: 0, role: 'user', content: 'câu hỏi bình thường', taoLuc: '2026-07-27T14:22:00+07:00', meta: 'không phải object' },
            { seq: 1, role: 'assistant', content: 'câu trả lời bình thường', taoLuc: '2026-07-27T14:23:00+07:00', meta: { tool_calls: 'không phải mảng' } },
          ],
          skillCalls: [],
        }),
      ),
    )
    dung()
    expect(await screen.findByText('câu hỏi bình thường')).toBeInTheDocument()
    expect(screen.getByText('câu trả lời bình thường')).toBeInTheDocument()
    expect(screen.queryByText(/không phải mảng/)).not.toBeInTheDocument()
  })

  it('meta.tool_calls hiện thành dòng công cụ dưới đúng lượt của nó', async () => {
    dung()
    expect(await screen.findByText(/search_units\(project=VOP2/)).toBeInTheDocument()
  })

  it('mốc giờ có mặt trong DOM nhưng ẩn bằng opacity, KHÔNG bị display:none', async () => {
    // Nếu ẩn bằng display:none thì lúc hover cả cột tin nhắn bị xô xuống 16px —
    // chuyển động mượt cỡ nào cũng không cứu được cảm giác đó (spec §5.3).
    dung()
    const gio = await screen.findAllByTestId('moc-gio')
    expect(gio[0]).toBeInTheDocument()
    expect(gio[0].className).toContain('opacity-0')
    expect(gio[0].className).not.toContain('hidden')
  })

  it('mốc giờ mở được bằng BÀN PHÍM, không chỉ bằng chuột', async () => {
    // Ràng buộc 2 của §5.3. jsdom không áp CSS thật nên không quan sát được
    // opacity đổi; thứ kiểm được — và là thứ hỏng nếu ai xoá — là hai điều:
    // lượt nhận được focus, và lớp `group-focus-within` có mặt cạnh `group-hover`.
    // Nói rõ giới hạn này ở đây để người sau không tưởng test đã chứng minh hiệu ứng.
    dung()
    const gio = await screen.findAllByTestId('moc-gio')
    expect(gio[0].className).toContain('group-focus-within/msg:opacity-100')

    const bong = screen.getAllByTestId('bong-bong')
    bong[0].focus()
    expect(document.activeElement).toBe(bong[0])
  })

  it('theme.css còn giữ hai luật cho máy không chuột và người giảm chuyển động', async () => {
    // Ràng buộc 3 và 4 của §5.3 sống trong CSS, mà jsdom không chạy CSS. Cổng
    // này là cổng NGUỒN, không phải cổng hành vi: xoá một trong hai khối media
    // query thì nó đỏ. Không hơn — nó không chứng minh trình duyệt xử lý đúng.
    const css = await readFile(new URL('../src/styles/theme.css', import.meta.url), 'utf8')
    expect(css).toMatch(/@media \(hover: none\)[\s\S]*?\.moc-gio[\s\S]*?opacity:\s*1/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.moc-gio/)
  })

  it('bấm sang phiên 0 lượt thì hiện câu giải thích, không phải màn trắng', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    await userEvent.click(screen.getByText(/21\/07\/2026/))
    expect(await screen.findByText(/chưa có bản ghi hội thoại/i)).toBeInTheDocument()
  })

  it('phiên không lượt nào có tool_calls thì dùng skill_calls mức phiên, dồn cuối', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    await userEvent.click(screen.getByText(/21\/07\/2026/))
    expect(await screen.findByText(/công cụ agent đã gọi/i)).toBeInTheDocument()
    expect(screen.getByText(/create_appointment/)).toBeInTheDocument()
  })

  it('header lấy tên của phiên mới nhất, không hiện «null»', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument()
  })

  it('nhóm ẩn danh nói rõ nó KHÔNG phải một người', async () => {
    dung('_')
    expect(await screen.findByText(/không phải một người/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test — phải ĐỎ**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-phien.test.tsx`
Expected: FAIL — không resolve được `@/features/ops/components/PhienKhach`.

- [ ] **Step 3: Viết `Transcript.tsx`**

```tsx
/**
 * Transcript một phiên (spec §5.2, §5.3).
 *
 * PHÒNG THỦ LÀ YÊU CẦU, KHÔNG PHẢI SỰ CẨN THẬN THỪA: `conversation_messages` do
 * một hệ khác ghi và `0915` cố ý KHÔNG có CHECK trên `role`. Một lượt méo chỉ
 * được làm hỏng chính nó — các lượt còn lại vẫn phải hiện.
 */
import type { Luot } from '../api'

/** `user` bên phải, `assistant` bên trái. Mọi giá trị khác ⇒ dòng hệ thống. */
function ben(role: string): 'khach' | 'agent' | 'he_thong' {
  if (role === 'user') return 'khach'
  if (role === 'assistant') return 'agent'
  return 'he_thong'
}

function toolCalls(meta: Record<string, unknown>): string[] {
  const tc = meta?.tool_calls
  if (!Array.isArray(tc)) return []
  return tc.map((x) => (typeof x === 'string' ? x : JSON.stringify(x)))
}

function gioCua(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '' // KHÔNG in 'Invalid Date' lên màn
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function Transcript({ luot, skillCallsDuPhong = [] }: { luot: readonly Luot[]; skillCallsDuPhong?: unknown[] }) {
  if (luot.length === 0) {
    return <p className="p-6 text-center text-[12.5px] text-muted">Phiên này chưa có bản ghi hội thoại.</p>
  }

  const coToolTrongLuot = luot.some((l) => toolCalls(l.meta).length > 0)

  return (
    <div className="flex flex-col gap-2.5">
      {luot.map((l) => {
        const b = ben(l.role)
        const tools = toolCalls(l.meta)
        if (b === 'he_thong') {
          return (
            <p key={l.seq} className="text-center text-[11px] italic text-muted-3">
              {l.content}
            </p>
          )
        }
        return (
          <div key={l.seq} className="group/msg flex flex-col">
            <span
              data-testid="bong-bong"
              className={`max-w-[76%] rounded-2xl px-3 py-2 text-[13px] leading-[1.55] ${
                b === 'khach' ? 'ml-auto rounded-br-sm border bg-surface' : 'rounded-bl-sm bg-acs'
              }`}
            >
              {l.content}
            </span>
            <span
              data-testid="moc-gio"
              className={`moc-gio h-4 text-[10.5px] leading-4 text-muted-3 opacity-0 transition
                          group-hover/msg:opacity-100 group-focus-within/msg:opacity-100
                          ${b === 'khach' ? 'text-right' : ''}`}
            >
              {gioCua(l.taoLuc)}
            </span>
            {tools.map((t, i) => (
              <span
                key={i}
                className="max-w-[76%] self-start rounded-md border bg-bg px-2 py-1 font-mono text-[11px] text-muted-2"
              >
                {t}
              </span>
            ))}
          </div>
        )
      })}

      {/* Dự phòng: chỉ khi KHÔNG lượt nào mang tool_calls. `conversations.skill_calls`
          ở mức PHIÊN nên không biết nó thuộc lượt nào — dồn xuống cuối là chỗ duy
          nhất không nói sai vị trí. */}
      {!coToolTrongLuot && skillCallsDuPhong.length > 0 && (
        <div className="mt-2 rounded-lg border bg-bg p-2.5">
          <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted-3">
            Công cụ agent đã gọi
          </p>
          {skillCallsDuPhong.map((s, i) => (
            <p key={i} className="font-mono text-[11px] text-muted-2">
              {typeof s === 'string' ? s : JSON.stringify(s)}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Viết `PhienKhach.tsx`**

```tsx
/** Màn chi tiết một khách: header + cột phiên + transcript (spec §5.2). Chỉ xem. */
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { PHONE_TRONG, chiTietPhien, phienCuaKhach } from '../api'
import { thoiLuong } from '../thoiGian'
import { Transcript } from './Transcript'

function ngayGio(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const hai = (n: number) => String(n).padStart(2, '0')
  return `${hai(d.getDate())}/${hai(d.getMonth() + 1)}/${d.getFullYear()} · ${hai(d.getHours())}:${hai(d.getMinutes())}`
}

export function PhienKhach({ phone }: { phone: string }) {
  const an = phone === PHONE_TRONG
  const ds = useQuery({ queryKey: ['convos', 'phien', phone], queryFn: () => phienCuaKhach(phone) })
  const [chon, setChon] = useState<string | null>(null)
  const sid = chon ?? ds.data?.[0]?.sessionId ?? null
  const ct = useQuery({
    queryKey: ['convos', 'chitiet', sid],
    queryFn: () => chiTietPhien(sid!),
    enabled: sid !== null,
  })

  if (ds.isPending) return <p className="p-6 text-[13px] text-muted">Đang tải…</p>
  if (ds.error) return <p className="p-6 text-[13px]">Không tải được các phiên của khách này.</p>

  // Tên của phiên MỚI NHẤT (danh sách đã sắp giảm dần). Không có tên ở phiên nào
  // thì dùng số làm tên — hiện chuỗi 'null' hay ô trống đều tệ hơn.
  const ten = an ? 'Chưa có số' : (ds.data.find((p) => p.ten)?.ten ?? phone)

  return (
    <div className="space-y-4 p-6">
      <Link to="/convos" className="text-[12.5px] font-medium text-ac">
        ← Tất cả khách
      </Link>

      <div className="flex items-center gap-3">
        <span className="flex size-[46px] items-center justify-center rounded-full bg-acs text-[16px] font-semibold text-ac">
          {an ? '?' : phone.slice(-2)}
        </span>
        <div>
          <p className="text-[17px] font-semibold">{ten}</p>
          <p className="font-mono text-[12px] text-muted-2">
            {an ? `${ds.data.length} phiên ẩn danh — KHÔNG phải một người` : `${phone} · ${ds.data.length} phiên`}
          </p>
        </div>
      </div>

      {ds.data.length === 0 ? (
        <p className="rounded-xl border border-dashed p-8 text-center text-[13px] text-muted">
          Khách này không còn phiên nào.
        </p>
      ) : (
        <div className="flex gap-3.5">
          <div className="w-[300px] shrink-0 overflow-hidden rounded-xl border bg-surface">
            {ds.data.map((p) => {
              const dai = thoiLuong(p.batDau, p.ketThuc)
              return (
                <button
                  key={p.sessionId}
                  type="button"
                  onClick={() => setChon(p.sessionId)}
                  className={`block w-full border-b border-border-soft px-3.5 py-3 text-left ${
                    p.sessionId === sid ? 'border-l-[3px] border-l-ac bg-acs' : ''
                  }`}
                >
                  <span className="block text-[12.5px] font-semibold">{ngayGio(p.batDau)}</span>
                  <span
                    className={`mt-0.5 line-clamp-2 block text-[11.5px] ${p.summary ? 'text-muted' : 'italic text-muted-3'}`}
                  >
                    {p.summary ?? 'Chưa có tóm tắt cho phiên này.'}
                  </span>
                  <span className="mt-1 block font-mono text-[10.5px] text-muted-2">
                    {p.soLuot} lượt{dai ? ` · ${dai}` : ''}
                    {p.duAn ? ` · ${p.duAn}` : ''}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="flex-1 overflow-hidden rounded-xl border bg-surface">
            {ct.isPending && <p className="p-6 text-[13px] text-muted">Đang tải…</p>}
            {ct.error && <p className="p-6 text-[13px]">Không tải được nội dung phiên này.</p>}
            {ct.data && (
              <>
                <div className="flex items-center gap-4 border-b border-border-soft px-4 py-2.5 text-[11.5px] text-muted-2">
                  <span className="font-mono">{ct.data.phien.sessionId}</span>
                  <span>{ngayGio(ct.data.phien.batDau)}</span>
                  {thoiLuong(ct.data.phien.batDau, ct.data.phien.ketThuc) && (
                    <span className="font-semibold text-fg">
                      {thoiLuong(ct.data.phien.batDau, ct.data.phien.ketThuc)}
                    </span>
                  )}
                  <span>{ct.data.phien.soLuot} lượt</span>
                  {ct.data.phien.runningVersion !== null && (
                    <span className="ml-auto font-mono">config v{ct.data.phien.runningVersion}</span>
                  )}
                </div>
                <div className="space-y-3 bg-[#fcfcfb] p-4">
                  {ct.data.phien.summary && (
                    <div className="rounded-lg border border-[#f0e6cf] bg-[#fdf9ef] px-3 py-2.5 text-[12.5px] leading-[1.55] text-[#6b5a34]">
                      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-[#a3893f]">
                        Tóm tắt của agent
                      </p>
                      {ct.data.phien.summary}
                    </div>
                  )}
                  <Transcript luot={ct.data.luot} skillCallsDuPhong={[...ct.data.skillCalls]} />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Thêm hai media query vào `src/styles/theme.css`**

Thêm vào cuối tệp:

```css
@layer utilities {
  /* Máy KHÔNG có chuột thì mốc giờ hiện sẵn: ở đó không tồn tại trạng thái "rê
     vào", nên ẩn đi là giấu mất dữ liệu vĩnh viễn. */
  @media (hover: none) {
    .moc-gio {
      opacity: 1;
    }
  }
  /* Ai bật «giảm chuyển động» thì bỏ hiệu ứng, giữ nguyên việc hiện/ẩn. */
  @media (prefers-reduced-motion: reduce) {
    .moc-gio {
      transition: none;
    }
  }
}
```

- [ ] **Step 6: Chạy test — phải XANH**

Run: `cd odyssey-portal-frontend && npx vitest run tests/convos-phien.test.tsx`
Expected: PASS — 14 test.

- [ ] **Step 7: Nối route `/convos/$phone`**

`src/routes/_app/convos.$phone.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { PhienKhach } from '@/features/ops/components/PhienKhach'

export const Route = createFileRoute('/_app/convos/$phone')({
  component: () => <PhienKhach phone={Route.useParams().phone} />,
})
```

- [ ] **Step 8: Sinh route tree, chạy toàn bộ cổng FE, commit**

```bash
cd odyssey-portal-frontend
npm run routes && npm run build && npx vitest run && npm run lint
git add src/features/ops src/routes/_app src/routeTree.gen.ts src/styles/theme.css tests/convos-phien.test.tsx
git commit -m "M7 FE: màn chi tiết, transcript, mốc giờ theo hover"
```

---

## Task 7: Khớp nối cuối — chạy thật, kiểm hai màn trên dữ liệu thật

**Repo:** cả hai

**Files:**
- Modify: `src/lib/screens.ts` (đổi `note` của màn `convos` nếu nó còn ghi "MVP chỉ xem" sai lệch — kiểm trước, chỉ sửa nếu sai)
- Không tạo tệp mới.

**Interfaces:**
- Consumes: mọi thứ của Task 1–6.
- Produces: không có API mới.

- [ ] **Step 1: Dựng dữ liệu thật để soi màn**

```bash
cd odyssey-portal-backend
uv run python - <<'PY'
import asyncio, sys
sys.path.insert(0, "src")
from portal.core.config import get_settings
import asyncpg
from datetime import datetime, timedelta, UTC

async def main():
    dsn = get_settings().alembic_url.replace("postgresql+psycopg","postgresql").replace("postgresql+asyncpg","postgresql")
    c = await asyncpg.connect(dsn)
    t = "anphu"
    gio = datetime.now(UTC)
    await c.execute("""
        INSERT INTO tenant_data.conversations
          (tenant_id, session_id, phone, customer_name, summary, project, transferred_to_sales,
           started_at, ended_at, running_version, created_at)
        VALUES ($1,'demo-1','0912448111','Nguyễn Minh Anh','Hỏi căn 3PN dưới 6 tỷ, chốt lịch xem nhà.',
                'Ocean Park 2', true, $2, $3, 12, $2)
        ON CONFLICT DO NOTHING
    """, t, gio - timedelta(minutes=8), gio - timedelta(minutes=6))
    for seq, (role, noi) in enumerate([
        ("user", "Còn căn nào 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 không em?"),
        ("assistant", "Dạ hiện còn 4 căn ạ. Gần nhất NT2-1408, 78,4 m², 5,62 tỷ."),
        ("user", "Cuối tuần này xem nhà được không?"),
        ("assistant", "Dạ được ạ. Em còn slot 10:00 thứ Bảy 01/08."),
    ]):
        await c.execute("""
            INSERT INTO tenant_data.conversation_messages
              (tenant_id, session_id, seq, role, content, created_at, meta)
            VALUES ($1,'demo-1',$2,$3,$4,$5,$6::jsonb) ON CONFLICT DO NOTHING
        """, t, seq, role, noi, gio - timedelta(minutes=8) + timedelta(seconds=seq*30),
        '{"tool_calls":["search_units(project=VOP2) → 4 · 128ms"]}' if seq == 1 else '{}')
    # Phiên 0 lượt + phiên ẩn danh — hai ca biên phải nhìn thấy trên màn thật.
    await c.execute("""
        INSERT INTO tenant_data.conversations (tenant_id, session_id, phone, started_at, created_at)
        VALUES ($1,'demo-rong','0912448111',$2,$2), ($1,'demo-an',NULL,$2,$2)
        ON CONFLICT DO NOTHING
    """, t, gio - timedelta(days=2))
    print("đã nạp dữ liệu demo cho tenant", t)
    await c.close()

asyncio.run(main())
PY
```

- [ ] **Step 2: Chạy API và FE, tắt MSW**

```bash
# terminal 1
cd odyssey-portal-backend && make api
# terminal 2 — MSW tắt để gọi backend thật
cd odyssey-portal-frontend && npm run dev
```

Đăng nhập `dang@anphuland.vn` / `odyssey-dev`, chọn workspace **An Phú Land**, vào **Hội thoại**.

- [ ] **Step 3: Đối chiếu tay 8 điểm**

Đánh dấu từng điểm; điểm nào sai thì sửa rồi chạy lại toàn bộ test của task tương ứng.

1. Danh sách có hàng «Nguyễn Minh Anh» với summary 2 dòng, chip `Ocean Park 2` và `Đã chuyển sales`.
2. Có hàng **«Chưa có số»** viền đứt, chữ xám, phụ đề `— ẩn danh`.
3. Rê chuột lên một hàng: vạch xanh 3px chạy dọc mép trái, mũi `›` đổi màu.
4. Mốc ngày chia nhóm (Hôm nay / Tuần trước) có mặt.
5. Bấm vào khách → URL đổi thành `/convos/0912448111`, F5 vẫn ở đúng màn đó.
6. Cột phiên: phiên `demo-rong` hiện **`0 lượt`** và **không** có chuỗi `0:00` ở đâu.
7. Transcript: khách bên phải, agent bên trái, dòng `search_units(...)` nằm dưới đúng bong bóng agent.
8. Mốc giờ **ẩn**; rê chuột vào một lượt thì giờ của **đúng lượt đó** mờ dần hiện ra, và **không lượt nào bị xô chỗ**.
9. Gõ vào ô tìm và bấm `7 ngày` → URL thành `/convos?q=…&tu=7`. **F5** → ô tìm và nút `7 ngày` vẫn giữ nguyên trạng thái. (Cổng này là kiểm tay, không phải test: nó cần router thật + reload thật, mà `vitest` dựng component ngoài router thì không tái hiện được.)

- [ ] **Step 4: Chạy toàn bộ cổng hai repo**

```bash
cd odyssey-portal-backend && make check
cd ../odyssey-portal-frontend && npm run build && npx vitest run && npm run lint
```

Expected: xanh, trừ `tests/isolation` bên BE đã đỏ sẵn từ `0908`/`0909` trên `develop`.

- [ ] **Step 5: Commit**

```bash
cd odyssey-portal-frontend
git add -A src tests
git commit -m "M7: khớp nối màn Hội thoại trên dữ liệu thật"
```

---

## Ngoài phạm vi kế hoạch này

Đã ghi ở spec §8, nhắc lại để không ai "làm nốt cho tiện":

- Tiếp quản hội thoại / nhắn cho khách (`convos.handle`) — chưa có đường ghi.
- Tạo hoặc sửa lịch hẹn từ màn này — thuộc màn `appts`.
- Phân biệt kênh chat/voice, đếm "đang chờ người thật", thời lượng cuộc gọi:
  prototype có, **dữ liệu không có**. Dựng bây giờ là bịa số.
- Badge số trên nav `convos` — cần định nghĩa "cần người xử lý", định nghĩa đó
  chưa có dữ liệu đỡ.
- Xuất transcript ra tệp.
