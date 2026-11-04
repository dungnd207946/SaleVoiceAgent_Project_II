# Màn Tổng quan (Dashboard) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng màn `/dashboard` — 5 ô khoá trong đúng một màn hình không cuộn — và endpoint `GET /api/v1/overview` cấp toàn bộ số liệu cho nó trong một lượt gọi.

**Architecture:** Backend thêm ba hàm SQL vào `modules/ops/repo.py` (module đã sở hữu M7 — màn này là màn thứ tư của M7) và một endpoint `GET /overview` gộp chúng thành một `OverviewOut`. Frontend thêm `overview()` vào `features/ops/api.ts`, bốn component trình bày thuần trong `features/ops/components/`, và một component biểu đồ SVG tự vẽ (không thư viện chart). Route `/dashboard` đã có sẵn `ScreenStub` — thay ruột, không đụng nav/screens registry vì `dashboardNav` và `SCREENS['dashboard']` đã khai từ trước.

**Tech Stack:** FastAPI + asyncpg + Pydantic (BE) · React 19 + TanStack Router/Query + Tailwind v4 + SVG tay (FE) · pytest-asyncio + testcontainers (BE) · vitest + Testing Library + MSW (FE)

**Spec:** `odyssey-portal-frontend/docs/superpowers/specs/2026-08-13-man-tong-quan-dashboard-design.md`

**Bản mẫu thị giác:** `odyssey-portal-frontend/public/demo-tong-quan.html` — bản demo đã được người dùng duyệt 2026-08-13. Đây là **nguồn hình học và số đo chính xác** cho Task 8–11 (padding biểu đồ, thang băng, gradient, cột lưới ô Kiến thức). Task 11 xoá nó.

---

## Global Constraints

Mọi task đều chịu các ràng buộc dưới đây; chúng không lặp lại trong từng task.

**Backend**
- Router khai đường **tương đối** (`/overview`), KHÔNG viết `/api/v1` — `api/app.py:TIEN_TO` gắn tiền tố.
- Mọi route phải khai một action qua `require(...)`; `tests/api/test_moi_route_khai_action.py` là cổng. Action dùng ở đây là `ACTIONS.OVERVIEW_READ` (`"overview.read"`) — **đã có sẵn** trong `core/auth/actions.py:25`, không sinh lại `contracts/`.
- Mọi truy vấn đi qua `tenant_conn(pool, p.tenant_id)` và mang `tenant_id = portal.current_tenant()` trong `WHERE`. Không mock `tenant_conn` trong test.
- Field DTO đặt **camelCase không dấu** (`theoNgay`, `chuyenSale`) — hợp đồng với FE.
- Test **không dùng `now()`** cho dữ liệu cố định: dùng `luc(ngay, gio)` từ `tests/modules/ops/conftest.py`. Chỉ test bộ lọc thời gian mới dùng `cach_day(n)`.
- Chạy test: `make test-module M=ops` (= `uv run pytest tests/modules/ops -v`). Lint: `make lint`.

**Frontend**
- **Không viết mã màu ngoài `src/styles/theme.css`.** Token mới khai trong `@theme` (Task 5), component chỉ dùng tên lớp Tailwind sinh từ token.
- Bo góc chỉ dùng thang đã có (`--radius-sm/md/lg` = 6/8/12px) + `--radius-mark` (3px, Task 5, **chỉ cho mark biểu đồ**). Không `rounded-[Npx]` tuỳ ý.
- **Không sửa `src/components/shell/*`.**
- Ranh giới module: `features/ops/*` không import ruột `features/quality/*` — dùng chung thì đặt ở `components/ui/`. `tests/module-boundaries.test.ts` là cổng.
- Typecheck là `npm run build` (chạy `tsc -b`). **`tsc --noEmit` là cổng RỖNG** ở repo này (tsconfig kiểu solution) — đừng dùng nó để xác nhận.
- `exactOptionalPropertyTypes` đang bật: không gán tường minh `undefined` vào field optional, trải object có điều kiện.
- Chạy test: `npm test` (vitest). **Node 22** — Node ≥ 24 làm vỡ bộ test; nếu buộc phải dùng Node 24 thì đặt `NODE_OPTIONS="--no-experimental-webstorage"`.

**Chung**
- Ngày giờ hiển thị theo `Asia/Ho_Chi_Minh`. Backend trả `date`/`datetime` ISO, frontend định dạng.
- Commit sau mỗi task.

---

### Task 1: Contracts của overview

**Files:**
- Modify: `odyssey-portal-backend/src/portal/modules/ops/contracts.py`
- Test: `odyssey-portal-backend/tests/modules/ops/test_contracts_overview.py` (create)

**Interfaces:**
- Produces: `MocOut`, `NgayOut`, `KenhOut`, `HoiThoaiOut`, `ChuyenSaleOut`, `DanhGiaOut`, `MucKienThucOut`, `KienThucOut`, `OverviewOut`, hằng `SO_NGAY = 7`, `KENH_CHAT = "chat"`, `KENH_VOICE = "voice"`.

**Vì sao hợp đồng khác spec §3 gốc:** spec viết trước khi chốt thiết kế. Bản duyệt cuối cần **Chat và Voice tách riêng theo từng ngày** (ô ①) và **sáu mục Kiến thức có cả `kb_files`** (ô ⑤). Hợp đồng dưới đây là bản chốt.

- [ ] **Step 1: Viết test đỏ cho hình dạng hợp đồng**

Tạo `tests/modules/ops/test_contracts_overview.py`:

```python
"""Cổng hình dạng hợp đồng overview — chạy không cần DB.

Kiểm những thứ mà một lỗi ở đó không làm test khác đỏ mà chỉ làm màn hiện
`undefined`: tên field camelCase, và bất biến "tổng = tổng các phần".
"""

from datetime import date

from portal.modules.ops.contracts import (
    SO_NGAY,
    DanhGiaOut,
    HoiThoaiOut,
    KenhOut,
    KienThucOut,
    MocOut,
    MucKienThucOut,
    NgayOut,
    OverviewOut,
)


def test_field_dto_dat_camel_case():
    """Field snake_case lọt ra JSON là màn đọc `undefined` — không nổ, không ai thấy."""
    khoa = set(OverviewOut.model_fields)
    assert khoa == {"moc", "hoiThoai", "chuyenSale", "danhGia", "kienThuc"}
    assert set(HoiThoaiOut.model_fields) == {"tong", "truoc", "theoNgay", "theoKenh"}
    assert set(MucKienThucOut.model_fields) == {"khoa", "thay", "tong"}


def test_ngay_out_tu_tinh_tong():
    """`tong` là tổng ba nhánh, KHÔNG nhận từ ngoài: hai nguồn cho một con số
    là hai chỗ để lệch, và biểu đồ vẽ theo nhánh còn nhãn đọc theo tổng.

    `computed_field` KHÔNG nằm trong `model_fields` — nó ở
    `model_computed_fields`. Kiểm cả hai chỗ để không ai "sửa" nó thành field
    nhận-từ-ngoài rồi thấy test vẫn xanh."""
    assert set(NgayOut.model_fields) == {"ngay", "chat", "voice", "khac"}
    assert set(NgayOut.model_computed_fields) == {"tong"}

    n = NgayOut(ngay=date(2026, 8, 13), chat=20, voice=13, khac=4)
    assert n.tong == 37
    # Và nó phải RA JSON — biểu đồ đọc `tong` từ đó.
    assert n.model_dump()["tong"] == 37


def test_so_ngay_la_bay():
    assert SO_NGAY == 7


def test_khoa_kien_thuc_du_sau_muc():
    kt = KienThucOut(
        muc=[
            MucKienThucOut(khoa=k, thay=1, tong=2)
            for k in ("duAn", "phanKhu", "can", "taiLieu", "tepTraCuu", "hoSoDuTruong")
        ]
    )
    assert [m.khoa for m in kt.muc] == [
        "duAn",
        "phanKhu",
        "can",
        "taiLieu",
        "tepTraCuu",
        "hoSoDuTruong",
    ]


def test_danh_gia_truoc_cho_phep_none():
    """Kỳ trước chưa có lượt đánh giá nào ⇒ `truoc = None`, KHÔNG phải 0.0.
    0.0 vẽ ra mũi tên «giảm 4,33» trên một kỳ chưa từng có số."""
    d = DanhGiaOut(trungBinh=4.33, truoc=None, tong=190, theoSao={"1": 4, "2": 8, "3": 20, "4": 48, "5": 110})
    assert d.truoc is None


def test_moc_va_kenh_giu_nguon_tho():
    m = MocOut(tuNgay=date(2026, 8, 7), tinhDen=date(2026, 8, 13))
    assert m.tuNgay < m.tinhDen
    # `kenh=None` = agent bản cũ chưa gửi `source`. Giữ None, không đổi thành "".
    assert KenhOut(kenh=None, n=8).kenh is None
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/ops/test_contracts_overview.py -v`
Expected: FAIL — `ImportError: cannot import name 'SO_NGAY' from 'portal.modules.ops.contracts'`

- [ ] **Step 3: Thêm hợp đồng vào `contracts.py`**

Nối vào cuối `src/portal/modules/ops/contracts.py` (giữ nguyên phần M7 đã có), và thêm các tên mới vào `__all__`:

```python
# ── Overview — màn /dashboard ───────────────────────────────────────────────
# Một endpoint cho cả màn, KHÔNG năm endpoint cho năm ô: màn này không có bộ
# lọc riêng cho từng ô, nên năm lượt gọi chỉ tạo ra năm khoảnh khắc màn hiện
# một nửa số liệu.

SO_NGAY = 7
"""Cửa sổ của ô Hội thoại. Nhãn trục x là 7 ngày, con số delta cũng đo trên
cửa sổ này — hai thứ lệch cửa sổ nhau là hai câu chuyện về cùng một biểu đồ."""

KENH_CHAT = "chat"
KENH_VOICE = "voice"
"""Hai giá trị `conversations.source` mà agent thật ghi (`base_session`/
`telephony` → `voice`, `text_chat` → `chat`; xem `components/ui/ChipKenh.tsx`).
Cột là `text` KHÔNG CHECK có chủ ý — kênh mới có thể tới bất cứ lúc nào — nên
mọi giá trị khác (và NULL) rơi vào `khac`, và `theoKenh` giữ nguyên văn nguồn
thô để chú thích gọi đúng tên nó."""


class MocOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    tuNgay: date
    tinhDen: date


class NgayOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    ngay: date
    chat: int
    voice: int
    #: Mọi `source` không phải chat/voice, cộng cả NULL.
    khac: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tong(self) -> int:
        """TÍNH, không nhận từ ngoài — xem test_ngay_out_tu_tinh_tong."""
        return self.chat + self.voice + self.khac


class KenhOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Nguyên văn `conversations.source`. `None` = agent bản cũ chưa gửi trường này.
    kenh: str | None
    n: int


class HoiThoaiOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    tong: int
    #: Cùng độ dài cửa sổ, lùi `SO_NGAY` ngày — mẫu số của delta.
    truoc: int
    #: ĐÚNG `SO_NGAY` phần tử, ngày cũ trước. Ngày không có phiên nào vẫn có
    #: mặt với 0 — biểu đồ vẽ theo chỉ số ô, thiếu một ngày là lệch cả trục.
    theoNgay: list[NgayOut]
    theoKenh: list[KenhOut]


class ChuyenSaleOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    chuyen: int
    tuXuLy: int


class DanhGiaOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    trungBinh: float
    #: `None` = kỳ trước chưa có lượt nào. KHÔNG dùng 0.0 thay thế.
    truoc: float | None
    tong: int
    theoSao: dict[str, int]


class MucKienThucOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Một trong sáu khoá cố định — FE ánh xạ sang nhãn và icon.
    khoa: str
    #: Phần agent ĐỌC ĐƯỢC. Đứng trước `tong` vì đây là con số đáng quan tâm.
    thay: int
    tong: int


class KienThucOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    muc: list[MucKienThucOut]


class OverviewOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    moc: MocOut
    hoiThoai: HoiThoaiOut
    chuyenSale: ChuyenSaleOut
    danhGia: DanhGiaOut
    kienThuc: KienThucOut
```

Sửa dòng import đầu file cho đủ: `from datetime import date, datetime` và `from pydantic import BaseModel, ConfigDict, computed_field`.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/ops/test_contracts_overview.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/ops/contracts.py tests/modules/ops/test_contracts_overview.py
git commit -m "feat(ops): hop dong OverviewOut cho man Tong quan"
```

---

### Task 2: SQL — hội thoại theo ngày và theo kênh

**Files:**
- Modify: `odyssey-portal-backend/src/portal/modules/ops/repo.py`
- Test: `odyssey-portal-backend/tests/modules/ops/test_repo_overview.py` (create)

**Interfaces:**
- Consumes: `SO_NGAY`, `KENH_CHAT`, `KENH_VOICE` (Task 1)
- Produces:
  - `async def hoi_thoai_theo_ngay(conn, *, tinh_den: date, so_ngay: int = SO_NGAY) -> list[asyncpg.Record]` — cột `ngay, chat, voice, khac`
  - `async def hoi_thoai_theo_kenh(conn, *, tu_ngay: date, tinh_den: date) -> list[asyncpg.Record]` — cột `kenh, n`
  - `async def dem_hoi_thoai(conn, *, tu_ngay: date, tinh_den: date) -> int`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/ops/test_repo_overview.py`:

```python
"""Cổng SQL của màn Tổng quan. Mỗi test neo một lỗi im lặng cụ thể."""

from datetime import date

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, luc, them_phien

pytestmark = pytest.mark.asyncio

TINH_DEN = date(2026, 7, 27)


async def test_ngay_khong_co_phien_van_co_mat_voi_0(conn_ops):
    """Ca chốt: `GROUP BY ngay` bỏ hẳn ngày rỗng. Biểu đồ vẽ theo CHỈ SỐ ô, nên
    thiếu một ngày làm mọi ngày sau nó trượt sang trái một cột — trục nói sai
    ngày mà không có dấu hiệu nào."""
    await them_phien(conn_ops, "a", bat_dau=luc(27), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert len(hang) == 7
    assert [r["ngay"] for r in hang] == [date(2026, 7, d) for d in range(21, 28)]
    assert hang[-1]["chat"] == 1
    assert hang[0]["chat"] == 0


async def test_source_la_roi_vao_khac_khong_bi_bo(conn_ops):
    """`zalo` chưa có trong ChipKenh nhưng vẫn là một phiên có thật. Bỏ nó khỏi
    `khac` làm tổng của ô nhỏ hơn số phiên thật mà không ai đối chiếu được."""
    await them_phien(conn_ops, "z", bat_dau=luc(27), source="zalo_oa")
    await them_phien(conn_ops, "n", bat_dau=luc(27), source=None)

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert hang[-1]["khac"] == 2
    assert hang[-1]["chat"] == 0
    assert hang[-1]["voice"] == 0


async def test_chat_voice_tach_dung_theo_source(conn_ops):
    await them_phien(conn_ops, "c1", bat_dau=luc(26), source="chat")
    await them_phien(conn_ops, "c2", bat_dau=luc(26), source="chat")
    await them_phien(conn_ops, "v1", bat_dau=luc(26), source="voice")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)
    ngay26 = next(r for r in hang if r["ngay"] == date(2026, 7, 26))

    assert (ngay26["chat"], ngay26["voice"]) == (2, 1)


async def test_phien_tenant_khac_khong_lot_vao(conn_ops):
    await them_phien(conn_ops, "ta", bat_dau=luc(27), source="chat")
    await them_phien(conn_ops, "tb", tenant=TENANT_KHAC, bat_dau=luc(27), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert hang[-1]["chat"] == 1


async def test_phien_ngoai_cua_so_khong_dem(conn_ops):
    """Ngày 20/7 nằm ngoài cửa sổ 21→27."""
    await them_phien(conn_ops, "cu", bat_dau=luc(20), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert sum(r["chat"] for r in hang) == 0


async def test_theo_kenh_cong_lai_bang_tong(conn_ops):
    """Bất biến của ô: dòng chú thích cộng lại phải ra đúng con số lớn ở trên.
    Hai truy vấn khác nhau cho hai số của cùng một tập là chỗ chúng lệch nhau."""
    for i, s in enumerate(["chat", "chat", "voice", "zalo_oa", None]):
        await them_phien(conn_ops, f"k{i}", bat_dau=luc(25), source=s)

    kenh = await repo.hoi_thoai_theo_kenh(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)
    tong = await repo.dem_hoi_thoai(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert sum(r["n"] for r in kenh) == tong == 5
    theo = {r["kenh"]: r["n"] for r in kenh}
    assert theo["chat"] == 2
    assert theo[None] == 1
```

Thêm tham số `source` vào helper `them_phien` trong `tests/modules/ops/conftest.py` — thêm `source: str | None = None` vào chữ ký, `source` vào danh sách cột INSERT, `$9` vào VALUES, và truyền biến vào cuối lời gọi `conn.execute`.

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/ops/test_repo_overview.py -v`
Expected: FAIL — `AttributeError: module 'portal.modules.ops.repo' has no attribute 'hoi_thoai_theo_ngay'`

- [ ] **Step 3: Viết SQL**

Nối vào `src/portal/modules/ops/repo.py`:

```python
# ── Overview ────────────────────────────────────────────────────────────────

_NGAY = "(COALESCE(started_at, created_at) AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"
"""Gom theo ngày Ở MÚI GIỜ NGƯỜI DÙNG, không phải UTC. Một phiên lúc 23h30
giờ VN nằm ở ngày hôm sau theo UTC — gom sai thì cột cuối biểu đồ (hôm nay)
luôn hụt mấy phiên muộn nhất, đúng những phiên người xem để ý nhất."""


async def hoi_thoai_theo_ngay(
    conn: asyncpg.Connection,
    *,
    tinh_den: date,
    so_ngay: int = SO_NGAY,
) -> list[asyncpg.Record]:
    """Một hàng một NGÀY, đủ `so_ngay` hàng kể cả ngày không có phiên nào.

    `generate_series` LEFT JOIN với dữ liệu — không phải `GROUP BY` trần. Xem
    `test_ngay_khong_co_phien_van_co_mat_voi_0`: biểu đồ vẽ theo chỉ số ô nên
    một ngày vắng mặt làm trượt cả trục.
    """
    return await conn.fetch(
        f"""
        WITH khung AS (
            SELECT generate_series($1::date - ($2::int - 1), $1::date, '1 day')::date AS ngay
        ),
        phien AS (
            SELECT {_NGAY} AS ngay, source
            FROM tenant_data.conversations
            WHERE {_LOC}
              AND {_NGAY} BETWEEN $1::date - ($2::int - 1) AND $1::date
        )
        SELECT khung.ngay,
               count(*) FILTER (WHERE phien.source = $3) AS chat,
               count(*) FILTER (WHERE phien.source = $4) AS voice,
               count(*) FILTER (
                   WHERE phien.ngay IS NOT NULL
                     AND (phien.source IS NULL OR phien.source NOT IN ($3, $4))
               ) AS khac
        FROM khung LEFT JOIN phien ON phien.ngay = khung.ngay
        GROUP BY khung.ngay
        ORDER BY khung.ngay
        """,
        tinh_den,
        so_ngay,
        KENH_CHAT,
        KENH_VOICE,
    )


async def hoi_thoai_theo_kenh(
    conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date
) -> list[asyncpg.Record]:
    """Một hàng một `source` NGUYÊN VĂN, kể cả NULL và kênh chưa biết tên.

    Không gộp kênh lạ vào "khác" ở tầng SQL: chú thích cần gọi đúng tên nó
    («+ Zalo OA 37»), còn việc gộp là quyết định trình bày của FE.
    """
    return await conn.fetch(
        f"""
        SELECT source AS kenh, count(*) AS n
        FROM tenant_data.conversations
        WHERE {_LOC} AND {_NGAY} BETWEEN $1::date AND $2::date
        GROUP BY source
        ORDER BY n DESC, source NULLS LAST
        """,
        tu_ngay,
        tinh_den,
    )


async def dem_hoi_thoai(conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date) -> int:
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM tenant_data.conversations
        WHERE {_LOC} AND {_NGAY} BETWEEN $1::date AND $2::date
        """,
        tu_ngay,
        tinh_den,
    )
```

Thêm vào đầu file: `from datetime import date` và mở rộng import contracts thành `from portal.modules.ops.contracts import KENH_CHAT, KENH_VOICE, SO_NGAY, TRANG_MAC_DINH`.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/ops/test_repo_overview.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/ops/repo.py tests/modules/ops/
git commit -m "feat(ops): SQL hoi thoai theo ngay va theo kenh cho overview"
```

---

### Task 3: SQL — chuyển sale, đánh giá, kiến thức

**Files:**
- Modify: `odyssey-portal-backend/src/portal/modules/ops/repo.py`
- Modify: `odyssey-portal-backend/tests/modules/ops/test_repo_overview.py`

**Interfaces:**
- Produces:
  - `async def dem_chuyen_sale(conn, *, tu_ngay: date, tinh_den: date) -> asyncpg.Record` — cột `chuyen, tong`
  - `async def danh_gia(conn, *, tu_ngay: date, tinh_den: date) -> asyncpg.Record` — cột `tong, trung_binh, sao1..sao5`
  - `async def kien_thuc(conn) -> asyncpg.Record` — 12 cột `<muc>_thay` / `<muc>_tong` cho sáu mục

- [ ] **Step 1: Viết test đỏ**

Nối vào `tests/modules/ops/test_repo_overview.py`:

```python
async def test_chuyen_sale_dem_tren_cung_cua_so_voi_tong(conn_ops):
    """`chuyen` và `tong` phải ra từ MỘT truy vấn: hai lượt đếm trên hai cửa sổ
    lệch nhau cho ra tỉ lệ > 100% mà không chỗ nào báo lỗi."""
    await them_phien(conn_ops, "p1", bat_dau=luc(25), chuyen=True)
    await them_phien(conn_ops, "p2", bat_dau=luc(25), chuyen=False)
    await them_phien(conn_ops, "p3", bat_dau=luc(25), chuyen=False)
    await them_phien(conn_ops, "cu", bat_dau=luc(10), chuyen=True)

    r = await repo.dem_chuyen_sale(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert (r["chuyen"], r["tong"]) == (1, 3)


async def test_danh_gia_trung_binh_va_phan_bo_tu_MOT_truy_van(conn_ops, pool):
    """Điểm trung bình phải tính TỪ chính phân bố đang vẽ. Hai nguồn rời nhau
    làm ngôi sao tô một đằng, con số in một nẻo."""
    async with pool.acquire() as c, c.transaction():
        for i, sao in enumerate([5, 5, 4, 3, 1]):
            await c.execute(
                "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, created_at)"
                " VALUES ($1,$2,$3,$4)",
                "opsw",
                f"fb{i}",
                sao,
                luc(25),
            )

    r = await repo.danh_gia(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["tong"] == 5
    assert float(r["trung_binh"]) == pytest.approx(18 / 5)
    assert (r["sao5"], r["sao4"], r["sao3"], r["sao2"], r["sao1"]) == (2, 1, 1, 0, 1)


async def test_danh_gia_khong_co_luot_nao_tra_tong_0_khong_no(conn_ops):
    """Workspace mới toanh. `avg()` trên tập rỗng trả NULL — nếu router ép float
    thẳng thì màn 500 ngay lần mở đầu tiên, đúng lúc không ai gỡ được."""
    r = await repo.danh_gia(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["tong"] == 0
    assert r["trung_binh"] is None


async def test_kien_thuc_thay_dem_published_tong_dem_tat_ca(conn_ops, pool):
    """Ca chốt của cả ô: agent KHÔNG đọc được bản nháp (`status <> 'published'`).
    Đếm `thay` bằng tổng là con số làm người xem yên tâm sai."""
    async with pool.acquire() as c, c.transaction():
        for ma, st in (("P1", "published"), ("P2", "published"), ("P3", "draft")):
            await c.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)"
                " VALUES ('opsw',$1,$2,$3)",
                ma,
                f"Dự án {ma}",
                st,
            )

    r = await repo.kien_thuc(conn_ops)

    assert (r["du_an_thay"], r["du_an_tong"]) == (2, 3)


async def test_kien_thuc_tep_tra_cuu_dem_theo_state_san_sang(conn_ops, pool):
    """`kb_files` không có cột `status` — nó dùng `state`, và giá trị agent đọc
    được là `san_sang` (đã bóc chữ → chia đoạn → nhúng vector xong)."""
    async with pool.acquire() as c, c.transaction():
        for i, st in enumerate(["san_sang", "san_sang", "dang_xu_ly", "loi"]):
            await c.execute(
                "INSERT INTO tenant_data.kb_files (tenant_id, ten_file, s3_key, kich_thuoc, loai, state)"
                " VALUES ('opsw',$1,$2,100,'pdf',$3)",
                f"f{i}.pdf",
                f"k/{i}",
                st,
            )

    r = await repo.kien_thuc(conn_ops)

    assert (r["tep_tra_cuu_thay"], r["tep_tra_cuu_tong"]) == (2, 4)


async def test_kien_thuc_ho_so_du_truong_theo_luat_completeness(conn_ops, pool):
    """`BAT_BUOC['project'] = (name, region, overview)` — `completeness.py`.
    Thiếu = NULL HOẶC chuỗi rỗng, một phép kiểm chứ không hai nhánh."""
    async with pool.acquire() as c, c.transaction():
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, region, overview, status)"
            " VALUES ('opsw','D1','Đủ','Hà Nội','Mô tả','published')"
        )
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, region, overview, status)"
            " VALUES ('opsw','D2','Thiếu vùng','','Mô tả','published')"
        )

    r = await repo.kien_thuc(conn_ops)

    assert (r["ho_so_du_truong_thay"], r["ho_so_du_truong_tong"]) == (1, 2)
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/ops/test_repo_overview.py -v -k "chuyen or danh_gia or kien_thuc"`
Expected: FAIL — `AttributeError: ... has no attribute 'dem_chuyen_sale'`

- [ ] **Step 3: Viết SQL**

Nối vào `repo.py`:

```python
async def dem_chuyen_sale(
    conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date
) -> asyncpg.Record:
    """MỘT truy vấn cho cả tử số và mẫu số — xem test cùng tên."""
    return await conn.fetchrow(
        f"""
        SELECT count(*) FILTER (WHERE transferred_to_sales) AS chuyen,
               count(*) AS tong
        FROM tenant_data.conversations
        WHERE {_LOC} AND {_NGAY} BETWEEN $1::date AND $2::date
        """,
        tu_ngay,
        tinh_den,
    )


_NGAY_FB = "(created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"


async def danh_gia(conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date) -> asyncpg.Record:
    """Điểm trung bình VÀ phân bố từ cùng một tập — xem test cùng tên.

    `trung_binh` trả NULL khi chưa có lượt nào; router quyết định hiển thị,
    KHÔNG ép 0.0 ở đây (0,00/5 là một điểm số, «chưa có» thì không).
    """
    return await conn.fetchrow(
        f"""
        SELECT count(*) AS tong,
               avg(rating)::float8 AS trung_binh,
               count(*) FILTER (WHERE rating = 1) AS sao1,
               count(*) FILTER (WHERE rating = 2) AS sao2,
               count(*) FILTER (WHERE rating = 3) AS sao3,
               count(*) FILTER (WHERE rating = 4) AS sao4,
               count(*) FILTER (WHERE rating = 5) AS sao5
        FROM tenant_data.agent_feedback
        WHERE {_LOC} AND {_NGAY_FB} BETWEEN $1::date AND $2::date
        """,
        tu_ngay,
        tinh_den,
    )


# Luật completeness của `project` — chép từ `realestate/completeness.py:BAT_BUOC`.
# KHÔNG import hàm `thieu_truong()`: nó là hàm thuần trên MỘT bản ghi, dùng nó ở
# đây buộc phải kéo cả 12xx dự án về Python để đếm. Ba tên cột này là hợp đồng
# giữa hai chỗ — đổi `BAT_BUOC['project']` thì đổi cả dòng dưới.
_DU_TRUONG = "COALESCE(name,'') <> '' AND COALESCE(region,'') <> '' AND COALESCE(overview,'') <> ''"


async def kien_thuc(conn: asyncpg.Connection) -> asyncpg.Record:
    """Sáu cặp (agent đọc được / tổng trong kho). KHÔNG có cửa sổ thời gian:
    kho kiến thức là trạng thái HIỆN TẠI, không phải lưu lượng trong 7 ngày."""
    return await conn.fetchrow(
        f"""
        SELECT
          (SELECT count(*) FILTER (WHERE status = 'published') FROM tenant_data.projects WHERE {_LOC})   AS du_an_thay,
          (SELECT count(*) FROM tenant_data.projects WHERE {_LOC})                                       AS du_an_tong,
          (SELECT count(*) FILTER (WHERE status = 'published') FROM tenant_data.zones WHERE {_LOC})      AS phan_khu_thay,
          (SELECT count(*) FROM tenant_data.zones WHERE {_LOC})                                          AS phan_khu_tong,
          (SELECT count(*) FILTER (WHERE status = 'published') FROM tenant_data.units WHERE {_LOC})      AS can_thay,
          (SELECT count(*) FROM tenant_data.units WHERE {_LOC})                                          AS can_tong,
          (SELECT count(*) FILTER (WHERE status = 'published') FROM tenant_data.documents WHERE {_LOC})  AS tai_lieu_thay,
          (SELECT count(*) FROM tenant_data.documents WHERE {_LOC})                                      AS tai_lieu_tong,
          (SELECT count(*) FILTER (WHERE state = 'san_sang') FROM tenant_data.kb_files WHERE {_LOC})     AS tep_tra_cuu_thay,
          (SELECT count(*) FROM tenant_data.kb_files WHERE {_LOC})                                       AS tep_tra_cuu_tong,
          (SELECT count(*) FILTER (WHERE {_DU_TRUONG}) FROM tenant_data.projects WHERE {_LOC})           AS ho_so_du_truong_thay,
          (SELECT count(*) FROM tenant_data.projects WHERE {_LOC})                                       AS ho_so_du_truong_tong
        """
    )
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/ops/test_repo_overview.py -v`
Expected: PASS (12 test)

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/ops/repo.py tests/modules/ops/test_repo_overview.py
git commit -m "feat(ops): SQL chuyen sale, danh gia, kien thuc cho overview"
```

---

### Task 4: Endpoint `GET /overview`

**Files:**
- Modify: `odyssey-portal-backend/src/portal/modules/ops/router.py`
- Test: `odyssey-portal-backend/tests/modules/ops/test_api_overview.py` (create)

**Interfaces:**
- Consumes: mọi thứ Task 1–3 sinh ra
- Produces: `GET /api/v1/overview` → `OverviewOut`, gác bởi `ACTIONS.OVERVIEW_READ`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/ops/test_api_overview.py`:

```python
"""Cổng HTTP của màn Tổng quan — quyền, hình dạng, bất biến, cách ly tenant."""

import asyncpg
import httpx
import pytest

from .conftest import TENANT_KHAC, cach_day, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "h1", bat_dau=cach_day(1), source="chat", chuyen=True)
        await them_phien(conn, "h2", bat_dau=cach_day(1), source="voice")
        await them_phien(conn, "h3", bat_dau=cach_day(2), source="zalo_oa")
        await them_phien(conn, "ngoai", tenant=TENANT_KHAC, bat_dau=cach_day(1), source="chat")
        await conn.execute(
            "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating) VALUES ('opsw','h1',5)"
        )
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, region, overview, status)"
            " VALUES ('opsw','P1','Ocean Park','Hà Nội','Mô tả','published')"
        )


async def test_khong_dang_nhap_thi_401(app_client: httpx.AsyncClient):
    r = await app_client.get("/api/v1/overview")
    assert r.status_code == 401


async def test_tra_du_nam_khoi(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/overview")

    assert r.status_code == 200
    assert set(r.json()) == {"moc", "hoiThoai", "chuyenSale", "danhGia", "kienThuc"}


async def test_theo_ngay_luon_du_bay_phan_tu(client_ops: httpx.AsyncClient, du_lieu):
    body = (await client_ops.get("/api/v1/overview")).json()

    assert len(body["hoiThoai"]["theoNgay"]) == 7
    assert body["hoiThoai"]["theoNgay"][-1]["ngay"] == body["moc"]["tinhDen"]
    # `tong` là computed_field — phải có mặt trong JSON, biểu đồ đọc nó.
    assert "tong" in body["hoiThoai"]["theoNgay"][0]


async def test_theo_kenh_cong_lai_dung_bang_tong(client_ops: httpx.AsyncClient, du_lieu):
    """Bất biến người dùng ĐỌC ĐƯỢC trên màn: dòng chú thích cộng lại phải ra
    con số lớn ngay trên nó."""
    ht = (await client_ops.get("/api/v1/overview")).json()["hoiThoai"]

    assert sum(k["n"] for k in ht["theoKenh"]) == ht["tong"]
    assert sum(n["tong"] for n in ht["theoNgay"]) == ht["tong"]


async def test_chuyen_sale_cong_lai_bang_tong_hoi_thoai(client_ops: httpx.AsyncClient, du_lieu):
    body = (await client_ops.get("/api/v1/overview")).json()
    cs = body["chuyenSale"]

    assert cs["chuyen"] + cs["tuXuLy"] == body["hoiThoai"]["tong"]


async def test_khong_lay_du_lieu_tenant_khac(client_ops: httpx.AsyncClient, du_lieu):
    """`ngoai` thuộc TENANT_KHAC — 3 phiên, không phải 4."""
    body = (await client_ops.get("/api/v1/overview")).json()

    assert body["hoiThoai"]["tong"] == 3


async def test_workspace_rong_tra_200_khong_500(client_ops: httpx.AsyncClient, workspace_ops):
    """Không fixture `du_lieu` — workspace mới toanh. `avg()` trên tập rỗng trả
    NULL; ép float thẳng là 500 ngay lần mở màn đầu tiên."""
    r = await client_ops.get("/api/v1/overview")

    assert r.status_code == 200
    body = r.json()
    assert body["danhGia"]["tong"] == 0
    assert body["danhGia"]["trungBinh"] == 0.0
    assert body["danhGia"]["truoc"] is None
    assert len(body["hoiThoai"]["theoNgay"]) == 7
    assert [m["khoa"] for m in body["kienThuc"]["muc"]] == [
        "duAn",
        "phanKhu",
        "can",
        "taiLieu",
        "tepTraCuu",
        "hoSoDuTruong",
    ]
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/ops/test_api_overview.py -v`
Expected: FAIL — `assert 404 == 200`

- [ ] **Step 3: Viết endpoint**

Nối vào `src/portal/modules/ops/router.py` (và mở rộng import contracts cho đủ các lớp Task 1 + `SO_NGAY`, thêm `from datetime import datetime, timedelta`, `from zoneinfo import ZoneInfo`):

```python
_MUI_GIO = ZoneInfo("Asia/Ho_Chi_Minh")

_KIEN_THUC = (
    ("duAn", "du_an"),
    ("phanKhu", "phan_khu"),
    ("can", "can"),
    ("taiLieu", "tai_lieu"),
    ("tepTraCuu", "tep_tra_cuu"),
    ("hoSoDuTruong", "ho_so_du_truong"),
)
"""Thứ tự SÁU MỤC là hợp đồng trình bày — FE vẽ theo đúng thứ tự nhận được,
không tự sắp lại. Đi từ thô tới tinh: dự án → phân khu → căn, rồi tài liệu →
tệp tra cứu, cuối cùng là chất lượng hồ sơ."""


@ROUTER.get("/overview", response_model=OverviewOut)
async def doc_overview(
    p: Principal = require(ACTIONS.OVERVIEW_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> OverviewOut:
    """MỘT endpoint cho cả màn — xem docstring khối Overview ở `contracts.py`.

    Mốc thời gian tính Ở ĐÂY, không ở SQL: sáu truy vấn dùng chung một cặp
    (tuNgay, tinhDen), và `now()` gọi sáu lần có thể rơi qua nửa đêm giữa
    chừng — khi đó ô Hội thoại và ô Đánh giá nói về hai cửa sổ khác nhau.
    """
    tinh_den = datetime.now(_MUI_GIO).date()
    tu_ngay = tinh_den - timedelta(days=SO_NGAY - 1)
    tu_ngay_truoc = tu_ngay - timedelta(days=SO_NGAY)
    tinh_den_truoc = tu_ngay - timedelta(days=1)

    async with tenant_conn(pool, p.tenant_id) as conn:
        ngay = await repo.hoi_thoai_theo_ngay(conn, tinh_den=tinh_den)
        kenh = await repo.hoi_thoai_theo_kenh(conn, tu_ngay=tu_ngay, tinh_den=tinh_den)
        truoc = await repo.dem_hoi_thoai(conn, tu_ngay=tu_ngay_truoc, tinh_den=tinh_den_truoc)
        cs = await repo.dem_chuyen_sale(conn, tu_ngay=tu_ngay, tinh_den=tinh_den)
        dg = await repo.danh_gia(conn, tu_ngay=tu_ngay, tinh_den=tinh_den)
        dg_truoc = await repo.danh_gia(conn, tu_ngay=tu_ngay_truoc, tinh_den=tinh_den_truoc)
        kt = await repo.kien_thuc(conn)

    theo_ngay = [
        NgayOut(ngay=r["ngay"], chat=r["chat"], voice=r["voice"], khac=r["khac"]) for r in ngay
    ]
    return OverviewOut(
        moc=MocOut(tuNgay=tu_ngay, tinhDen=tinh_den),
        hoiThoai=HoiThoaiOut(
            # Tổng lấy TỪ chuỗi ngày, không đếm lại bằng một truy vấn thứ tám:
            # hai phép đếm cùng một tập là hai chỗ để lệch nhau.
            tong=sum(n.tong for n in theo_ngay),
            truoc=truoc,
            theoNgay=theo_ngay,
            theoKenh=[KenhOut(kenh=r["kenh"], n=r["n"]) for r in kenh],
        ),
        chuyenSale=ChuyenSaleOut(chuyen=cs["chuyen"], tuXuLy=cs["tong"] - cs["chuyen"]),
        danhGia=DanhGiaOut(
            # `or 0.0` cho MÀN: một ô rỗng vẫn phải vẽ được thang 0→5.
            trungBinh=round(dg["trung_binh"] or 0.0, 2),
            # `truoc` thì KHÔNG — `None` ở đây làm FE ẩn hẳn mũi tên delta thay
            # vì vẽ «giảm 4,33» so với một kỳ chưa từng có số.
            truoc=round(dg_truoc["trung_binh"], 2) if dg_truoc["trung_binh"] is not None else None,
            tong=dg["tong"],
            theoSao={str(n): dg[f"sao{n}"] for n in range(1, 6)},
        ),
        kienThuc=KienThucOut(
            muc=[
                MucKienThucOut(khoa=khoa, thay=kt[f"{cot}_thay"], tong=kt[f"{cot}_tong"])
                for khoa, cot in _KIEN_THUC
            ]
        ),
    )
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/ops -v && uv run pytest tests/api/test_moi_route_khai_action.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/portal/modules/ops/router.py tests/modules/ops/test_api_overview.py
git commit -m "feat(ops): GET /api/v1/overview cho man Tong quan"
```

---

### Task 5: Token màu chuỗi dữ liệu

**Files:**
- Modify: `odyssey-portal-frontend/src/styles/theme.css`
- Test: `odyssey-portal-frontend/tests/token-chuoi-du-lieu.test.ts` (create)

**Interfaces:**
- Produces: token `--color-ds1..ds4`, `--color-ds-khac`, `--color-ds1-mo`, `--color-acs-manh`, `--radius-mark` (dùng qua lớp Tailwind `text-ds1`, `bg-ds1-mo`, `bg-acs-manh`, …)

**Vì sao bộ màu này:** đã chạy validator của skill `dataviz` trên đúng nền `surface` (`#fffefc`). Cặp kề xấu nhất ΔE 12.0 deutan — bộ đầu tiên không còn cảnh báo nào. Cặp `ds1`+`ds2` (hai đường Chat/Voice, và gauge Chuyển sale) đo riêng ở chế độ all-pairs: ΔE 24.4 protan · 35.2 mắt thường. **Ba bộ đã bỏ, đừng thử lại** — chi tiết trong khối comment sẽ viết ở Step 3.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/token-chuoi-du-lieu.test.ts`:

```ts
/**
 * Cổng token của biểu đồ. Đọc thẳng `theme.css` — không render, không jsdom
 * (jsdom không tính được `var()` lồng nhau nên một test render sẽ xanh cả khi
 * token không tồn tại).
 *
 * Bảo vệ hai điều: token có mặt, và KHÔNG ai chép mã màu ra ngoài file này.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const CSS = readFileSync(new URL('../src/styles/theme.css', import.meta.url), 'utf8')

const CAN_CO = [
  '--color-ds1',
  '--color-ds2',
  '--color-ds3',
  '--color-ds4',
  '--color-ds-khac',
  '--color-ds1-mo',
  '--color-acs-manh',
  '--radius-mark',
] as const

describe('token chuỗi dữ liệu', () => {
  it.each(CAN_CO)('%s được khai trong @theme', (ten) => {
    expect(CSS).toContain(`${ten}:`)
  })

  it('ds1 và ds2 là hai mã khác nhau', () => {
    const doc = (ten: string) => CSS.match(new RegExp(`${ten}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
    expect(doc('--color-ds1')).toBeDefined()
    expect(doc('--color-ds1')).not.toBe(doc('--color-ds2'))
  })

  it('radius-mark là 3px — KHÔNG phải bậc thứ tư của thang UI', () => {
    expect(CSS).toMatch(/--radius-mark:\s*3px/)
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `cd odyssey-portal-frontend && npm test -- tests/token-chuoi-du-lieu.test.ts`
Expected: FAIL — 8 test `toContain` không thấy token

- [ ] **Step 3: Thêm token vào `@theme`**

Chèn vào trong khối `@theme { … }` của `src/styles/theme.css` (khối bắt đầu ở dòng 44):

```css
  /* ── Màu CHUỖI DỮ LIỆU (biểu đồ) ─────────────────────────────────────────
     Đã chạy validator của skill `dataviz` trên đúng nền `surface` #fffefc.
     Bộ ĐẦU TIÊN không còn cảnh báo: cặp kề xấu nhất ΔE 12.0 deutan (mọi vòng
     trước đều rơi vào dải cảnh báo 6–8). Cặp ds1+ds2 — hai đường Chat/Voice và
     gauge Chuyển sale — đo riêng ở chế độ all-pairs: ΔE 24.4 protan · 35.2 mắt
     thường.

     ⚠ BA BỘ ĐÃ BỎ, đừng quay lại:
       ① Neo vào ChipKenh (chat #1f5aa8 + voice #5b45a8) — ΔE 0.6 deutan, gần
          như một màu. Chip kênh tối ưu cho việc đứng cạnh CHỮ, không phải cho
          hai đường cắt nhau trên cùng một lưới.
       ② #1f5aa8 lam + #a05a00 hổ phách — #a05a00 chroma sát sàn, trên nền giấy
          ấm ra nâu bùn chứ không phải một sắc.
       ③ #3a5fa8 chàm + #c2593f đất nung — đạt cổng nhưng trầm và bão hoà thấp,
          đọc ra cũ.
     Đổi bộ này thì chạy lại validator, đừng ước lượng bằng mắt. */
  --color-ds1: #4361ee; /* indigo  — Chat */
  --color-ds2: #ef4d5a; /* san hô  — Voice · Chuyển sale */
  --color-ds3: #0ea5a4; /* teal    — Zalo OA */
  --color-ds4: #8b5cf6; /* tím oải — slot 4 */
  --color-ds-khac: var(--color-n6);
  /* Dải crosshair — ds1 pha rất nhạt, chỉ để phân nền, không mang dữ liệu. */
  --color-ds1-mo: #eef1fd;

  /* `acs` đậm hơn một nấc — nền hàng lúc rê chuột. Cần bậc riêng vì `acs` đang
     là nền mục nav đang mở: dùng lại đúng nó cho hover thì hàng rê vào trông y
     hệt hàng đang được chọn. */
  --color-acs-manh: #dcece6;

  /* Bo góc của MARK biểu đồ — KHÔNG phải bậc thứ tư của thang UI. Thang 6/8/12
     đo cho nút · ô nhập · thẻ; một nấc thước cao 16px rộng 3px bo 6px thì thành
     viên thuốc. Khai có tên để không ai rải `rounded-[3px]` trong component. */
  --radius-mark: 3px;
```

- [ ] **Step 4: Chạy test + build, xác nhận xanh**

Run: `npm test -- tests/token-chuoi-du-lieu.test.ts && npm run build`
Expected: PASS 10 test (8 từ `it.each` + 2); build không lỗi

- [ ] **Step 5: Commit**

```bash
git add src/styles/theme.css tests/token-chuoi-du-lieu.test.ts
git commit -m "feat(theme): token mau chuoi du lieu cho bieu do Tong quan"
```

---

### Task 6: Client `overview()` trong `features/ops/api.ts`

**Files:**
- Modify: `odyssey-portal-frontend/src/features/ops/api.ts`
- Test: `odyssey-portal-frontend/tests/overview-api.test.ts` (create)

**Interfaces:**
- Produces: `interface Overview`, `interface NgayHoiThoai`, `interface MucKienThuc`, `async function overview(): Promise<Overview>`, `const KHOA_OVERVIEW = ['overview'] as const`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/overview-api.test.ts`:

```ts
/**
 * Cổng client overview. Kiểm KHIÊN trước hết — backend cũ/chưa deploy bỏ hẳn
 * một khoá khỏi JSON, và `undefined` lọt mọi guard `!== null` ở component.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { overview } from '@/features/ops/api'

const DAY_DU = {
  moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
  hoiThoai: {
    tong: 3,
    truoc: 2,
    theoNgay: [
      { ngay: '2026-08-13', chat: 2, voice: 1, khac: 0, tong: 3 },
    ],
    theoKenh: [{ kenh: 'chat', n: 2 }, { kenh: null, n: 1 }],
  },
  chuyenSale: { chuyen: 1, tuXuLy: 2 },
  danhGia: { trungBinh: 4.33, truoc: null, tong: 190, theoSao: { '1': 4, '2': 8, '3': 20, '4': 48, '5': 110 } },
  kienThuc: { muc: [{ khoa: 'duAn', thay: 8, tong: 12 }] },
}

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('overview()', () => {
  it('đọc đủ năm khối', async () => {
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(DAY_DU)))

    const o = await overview()

    expect(o.hoiThoai.tong).toBe(3)
    expect(o.hoiThoai.theoNgay[0]?.chat).toBe(2)
    expect(o.chuyenSale.chuyen).toBe(1)
    expect(o.danhGia.theoSao['5']).toBe(110)
    expect(o.kienThuc.muc[0]?.khoa).toBe('duAn')
  })

  it('backend thiếu khoá `theoKenh` ⇒ mảng rỗng, KHÔNG undefined', async () => {
    const thieu = { ...DAY_DU, hoiThoai: { ...DAY_DU.hoiThoai, theoKenh: undefined } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.hoiThoai.theoKenh).toEqual([])
  })

  it('`theoSao` thiếu một bậc ⇒ bậc đó là 0, không phải undefined', async () => {
    const thieu = { ...DAY_DU, danhGia: { ...DAY_DU.danhGia, theoSao: { '5': 110 } } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.danhGia.theoSao['1']).toBe(0)
    expect(o.danhGia.theoSao['5']).toBe(110)
  })

  it('lỗi HTTP ném LoiApi mang code của backend', async () => {
    server.use(
      http.get('/api/v1/overview', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'Không có quyền' } }, { status: 403 }),
      ),
    )

    await expect(overview()).rejects.toMatchObject({ code: 'FORBIDDEN' })
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `npm test -- tests/overview-api.test.ts`
Expected: FAIL — `overview` không được export từ `@/features/ops/api`

- [ ] **Step 3: Viết client**

Nối vào `src/features/ops/api.ts` (dùng lại `goi()` và `LoiApi` đã có trong file):

```ts
// ── Overview — màn /dashboard ───────────────────────────────────────────────

export const KHOA_OVERVIEW = ['overview'] as const

export interface NgayHoiThoai {
  /** ISO `YYYY-MM-DD`. */
  readonly ngay: string
  readonly chat: number
  readonly voice: number
  readonly khac: number
  readonly tong: number
}

export interface KenhHoiThoai {
  /** Nguyên văn `conversations.source`. `null` = agent bản cũ chưa gửi. */
  readonly kenh: string | null
  readonly n: number
}

export type SaoKey = '1' | '2' | '3' | '4' | '5'

export interface MucKienThuc {
  readonly khoa: string
  readonly thay: number
  readonly tong: number
}

export interface Overview {
  readonly moc: { readonly tuNgay: string; readonly tinhDen: string }
  readonly hoiThoai: {
    readonly tong: number
    readonly truoc: number
    readonly theoNgay: readonly NgayHoiThoai[]
    readonly theoKenh: readonly KenhHoiThoai[]
  }
  readonly chuyenSale: { readonly chuyen: number; readonly tuXuLy: number }
  readonly danhGia: {
    readonly trungBinh: number
    /** `null` = kỳ trước chưa có lượt nào ⇒ KHÔNG vẽ mũi tên delta. */
    readonly truoc: number | null
    readonly tong: number
    readonly theoSao: Readonly<Record<SaoKey, number>>
  }
  readonly kienThuc: { readonly muc: readonly MucKienThuc[] }
}

/**
 * MỘT lượt gọi cho cả màn.
 *
 * Mọi mảng/bậc đều qua khiên `?? []` / `?? 0` — cùng lý lẽ `chuanHoaFeedback`
 * ở `features/quality/api.ts`: backend chưa deploy bản mới bỏ HẲN khoá khỏi
 * JSON, và `undefined` lọt mọi guard `!== null` ở component. Ở đây nó còn nặng
 * hơn: `theoNgay` là thứ biểu đồ `.map()` thẳng.
 */
export async function overview(): Promise<Overview> {
  const t = await goi<Overview>('/overview')
  const sao = (t.danhGia?.theoSao ?? {}) as Partial<Record<SaoKey, number>>
  return {
    moc: t.moc,
    hoiThoai: {
      tong: t.hoiThoai?.tong ?? 0,
      truoc: t.hoiThoai?.truoc ?? 0,
      theoNgay: t.hoiThoai?.theoNgay ?? [],
      theoKenh: t.hoiThoai?.theoKenh ?? [],
    },
    chuyenSale: t.chuyenSale,
    danhGia: {
      trungBinh: t.danhGia?.trungBinh ?? 0,
      truoc: t.danhGia?.truoc ?? null,
      tong: t.danhGia?.tong ?? 0,
      theoSao: {
        '1': sao['1'] ?? 0,
        '2': sao['2'] ?? 0,
        '3': sao['3'] ?? 0,
        '4': sao['4'] ?? 0,
        '5': sao['5'] ?? 0,
      },
    },
    kienThuc: { muc: t.kienThuc?.muc ?? [] },
  }
}
```

ℹ️ `features/ops/api.ts:8` khai `const GOC = '/api/v1'` (khác `features/quality/api.ts` dùng `/api/v1/agent`), nên `goi('/overview')` ra đúng `/api/v1/overview`. Đừng viết tiền tố lần nữa trong chuỗi đường.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `npm test -- tests/overview-api.test.ts && npm run build`
Expected: PASS 4 test

- [ ] **Step 5: Commit**

```bash
git add src/features/ops/api.ts tests/overview-api.test.ts
git commit -m "feat(ops): client overview() cho man Tong quan"
```

---

### Task 7: MSW handler cho `/overview`

**Files:**
- Modify: `odyssey-portal-frontend/src/features/ops/msw.ts`

**Interfaces:**
- Consumes: `Overview` (Task 6)
- Produces: handler `GET /api/v1/overview` nằm trong mảng `opsHandlers` đã export

- [ ] **Step 1: Viết dữ liệu giả và handler**

Nối vào `src/features/ops/msw.ts`, rồi thêm handler vào mảng `opsHandlers` đã có ở cuối file:

```ts
/**
 * Overview giả. Ca biên cố ý có mặt, vì màn thật vỡ ở đúng chỗ fake không đi
 * tới: một ngày 0 phiên (cuối tuần), một `kenh: null` (agent bản cũ), một mục
 * kiến thức ĐẦY (100% — nhánh nhãn "Agent đọc đủ" chỉ chạy ở đây), và
 * `danhGia.truoc = null` (kỳ trước chưa có lượt nào ⇒ ẩn mũi tên delta).
 *
 * Ngày CỐ ĐỊNH, không sinh từ `new Date()`: fake trôi theo hôm nay làm ảnh
 * chụp màn hình của hai hôm khác nhau không so được, và một test canh nhãn
 * trục sẽ đỏ vào một ngày ngẫu nhiên trong tương lai.
 */
const OVERVIEW_GIA: Overview = {
  moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
  hoiThoai: {
    tong: 338,
    truoc: 298,
    theoNgay: [
      { ngay: '2026-08-07', chat: 26, voice: 17, khac: 5, tong: 48 },
      { ngay: '2026-08-08', chat: 15, voice: 22, khac: 3, tong: 40 },
      { ngay: '2026-08-09', chat: 13, voice: 21, khac: 2, tong: 36 },
      { ngay: '2026-08-10', chat: 28, voice: 17, khac: 6, tong: 51 },
      { ngay: '2026-08-11', chat: 30, voice: 17, khac: 7, tong: 54 },
      { ngay: '2026-08-12', chat: 27, voice: 16, khac: 6, tong: 49 },
      { ngay: '2026-08-13', chat: 27, voice: 17, khac: 16, tong: 60 },
    ],
    theoKenh: [
      { kenh: 'chat', n: 166 },
      { kenh: 'voice', n: 127 },
      { kenh: 'zalo_oa', n: 37 },
      { kenh: null, n: 8 },
    ],
  },
  chuyenSale: { chuyen: 73, tuXuLy: 265 },
  danhGia: {
    trungBinh: 4.33,
    truoc: null,
    tong: 190,
    theoSao: { '1': 4, '2': 8, '3': 20, '4': 48, '5': 110 },
  },
  kienThuc: {
    muc: [
      { khoa: 'duAn', thay: 8, tong: 12 },
      { khoa: 'phanKhu', thay: 31, tong: 47 },
      { khoa: 'can', thay: 964, tong: 1203 },
      { khoa: 'taiLieu', thay: 189, tong: 214 },
      { khoa: 'tepTraCuu', thay: 38, tong: 38 },
      { khoa: 'hoSoDuTruong', thay: 10, tong: 12 },
    ],
  },
}

// Thêm dòng này vào mảng `opsHandlers`:
//   http.get('/api/v1/overview', () => HttpResponse.json(OVERVIEW_GIA)),
```

Thêm `Overview` vào dòng `import type { ... } from '@/features/ops/api'` ở đầu file.

- [ ] **Step 2: Kiểm tổng của fake khớp nhau**

Chạy trong `node`:

```bash
node -e "
const d=[[26,17,5],[15,22,3],[13,21,2],[28,17,6],[30,17,7],[27,16,6],[27,17,16]];
const tong=d.reduce((a,[c,v,k])=>a+c+v+k,0);
const kenh=166+127+37+8;
const cs=73+265;
console.log({tong,kenh,cs});
if(tong!==338||kenh!==338||cs!==338) { console.error('LỆCH'); process.exit(1) }
console.log('OK — ba con số cùng nói 338')
"
```

Expected: `OK — ba con số cùng nói 338`

*Vì sao bước này tồn tại: bản demo từng in tổng `1.160` trong khi bốn kênh cộng lại ra `1.284`. Không ai đối chiếu bằng mắt hai con số cách nhau 40px.*

- [ ] **Step 3: Chạy toàn bộ test, xác nhận không vỡ gì**

Run: `npm test && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/features/ops/msw.ts
git commit -m "feat(ops): MSW fake cho GET /overview"
```

---

### Task 8: Biểu đồ hai đường `BieuDoNgay.tsx`

**Files:**
- Create: `odyssey-portal-frontend/src/features/ops/components/BieuDoNgay.tsx`
- Test: `odyssey-portal-frontend/tests/overview-bieu-do.test.tsx` (create)

**Interfaces:**
- Consumes: `NgayHoiThoai` (Task 6), token `ds1`/`ds2`/`ds1-mo` (Task 5)
- Produces: `export function BieuDoNgay({ chuoi, dangXem, doiDangXem }: { chuoi: readonly NgayHoiThoai[]; dangXem: number; doiDangXem: (i: number) => void })`

**Hình học — THANG BĂNG, không phải thang mép-tới-mép.** Đây là quyết định gốc, và ba lỗi thị giác đã sửa ở demo đều bắt nguồn từ việc làm sai nó. Port nguyên các hằng và công thức dưới đây từ `public/demo-tong-quan.html` § `ve()`:

```
PT = 14, PR = 16, PB = 8, PL = 30      // padding vùng vẽ
iw = W - PL - PR ; ih = H - PT - PB
buoc = iw / 7                           // 7 Ô, không phải 6 khoảng
X[i] = PL + (i + 0.5) * buoc            // TÂM ô — KHÔNG phải mép
dinh = max(20, ceil(max(chat,voice) * 1.12 / 20) * 20)   // trần bội của 20
Y(v) = PT + ih - (v / dinh) * ih
```

Hệ quả — tất cả tự khớp, không còn con số magic nào:
- dải ngày đang xem = **trọn một ô** (`x = PL + dangXem*buoc`, `width = buoc`), luôn nằm trong lưới, **không cần phép kẹp**
- dải và đường dọc cao đúng `PT → PT + ih`, khít đường nền
- vạch lưới dọc vẽ tại tâm ô ⇒ **đi xuyên đúng điểm dữ liệu**
- hàng nhãn ngày chỉ cần **cùng lề trái/phải** với vùng vẽ (`padding: 0 {PR}px 0 {PL}px`) rồi chia 7 ô đều — tâm tự trùng `X[i]`
- bám chuột dùng **`Math.floor` theo ô**, không `Math.round` theo điểm

**Gradient — ba chỗ, mỗi chỗ một lý do:** vùng dưới đường (dọc, màu → trong suốt, `.22→0` chat / `.17→0` voice) cho khối lượng; **nét đường (ngang, `.45→1`)** mã hoá chiều đọc — quá khứ nhạt, hôm nay đậm nhất, không phải trang trí; dải ngày đang xem (dọc, `.16→.02`) vì vùng chọn không được nặng bằng dữ liệu nó phủ lên. Thêm quầng sáng `r=9, opacity .15` sau điểm đang xem.

⚠️ **`stop-color` phải đặt qua thuộc tính `style`**, không qua presentation attribute — `var()` không được phân giải ở đó và im lặng rơi về mặc định. Cùng lớp bẫy với `rx="var(--…)"`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/overview-bieu-do.test.tsx`:

```tsx
/**
 * Cổng HÌNH HỌC của biểu đồ. Kiểm những bất biến mà mắt đọc thành "lệch" —
 * ba lỗi này đã xảy ra thật ở bản demo và không lỗi nào làm test cũ đỏ.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BieuDoNgay } from '@/features/ops/components/BieuDoNgay'
import type { NgayHoiThoai } from '@/features/ops/api'

const CHUOI: NgayHoiThoai[] = Array.from({ length: 7 }, (_, i) => ({
  ngay: `2026-08-${String(7 + i).padStart(2, '0')}`,
  chat: 10 + i,
  voice: 5 + i,
  khac: 0,
  tong: 15 + 2 * i,
}))

function veRoi(dangXem = 6) {
  render(<BieuDoNgay chuoi={CHUOI} dangXem={dangXem} doiDangXem={vi.fn()} />)
  return screen.getByRole('img')
}

describe('BieuDoNgay — hình học', () => {
  it('vẽ đúng 7 nhãn ngày, ngày cuối là hôm nay', () => {
    veRoi()
    expect(screen.getAllByTestId(/^nhan-ngay-/)).toHaveLength(7)
    expect(screen.getByTestId('nhan-ngay-6')).toHaveTextContent('13/8')
  })

  it('dải ngày đang xem rộng ĐÚNG một ô và nằm trọn trong lưới', () => {
    const svg = veRoi(0)
    const dai = svg.querySelector('[data-vai="dai"]') as SVGRectElement
    const luoi = svg.querySelector('[data-vai="nen-luoi"]') as SVGRectElement

    const x = Number(dai.getAttribute('x'))
    const w = Number(dai.getAttribute('width'))
    const lx = Number(luoi.getAttribute('x'))
    const lw = Number(luoi.getAttribute('width'))

    // Ca chốt: ở cột ĐẦU TIÊN, thang mép-tới-mép đẩy nửa dải ra ngoài lưới.
    expect(x).toBeGreaterThanOrEqual(lx)
    expect(x + w).toBeLessThanOrEqual(lx + lw + 0.01)
    expect(w).toBeCloseTo(lw / 7, 5)
  })

  it('dải cao đúng bằng lưới — không thừa ra phía dưới', () => {
    const svg = veRoi(3)
    const dai = svg.querySelector('[data-vai="dai"]') as SVGRectElement
    const luoi = svg.querySelector('[data-vai="nen-luoi"]') as SVGRectElement

    expect(Number(dai.getAttribute('y'))).toBeCloseTo(Number(luoi.getAttribute('y')), 5)
    expect(Number(dai.getAttribute('height'))).toBeCloseTo(Number(luoi.getAttribute('height')), 5)
  })

  it('vạch lưới dọc đi XUYÊN điểm dữ liệu — cùng toạ độ x', () => {
    const svg = veRoi()
    const vach = Array.from(svg.querySelectorAll('[data-vai="vach-doc"]'))
    const diem = Array.from(svg.querySelectorAll('[data-vai="diem-chat"]'))

    expect(vach).toHaveLength(7)
    expect(diem).toHaveLength(7)
    for (let i = 0; i < 7; i++) {
      expect(Number(diem[i]!.getAttribute('cx'))).toBeCloseTo(
        Number(vach[i]!.getAttribute('x1')),
        5,
      )
    }
  })

  it('trục y có 5 mốc, mốc trên cùng là bội của 20', () => {
    const svg = veRoi()
    const moc = Array.from(svg.querySelectorAll('[data-vai="moc-y"]'))

    expect(moc).toHaveLength(5)
    const dinh = Number(moc[moc.length - 1]!.textContent!.replace(/\D/g, ''))
    expect(dinh % 20).toBe(0)
  })

  it('gradient dùng thuộc tính `style` cho stop-color, không phải attribute', () => {
    /* `var()` KHÔNG phân giải trong presentation attribute — nó im lặng rơi về
       mặc định và gradient ra màu đen. */
    const svg = veRoi()
    for (const s of Array.from(svg.querySelectorAll('stop'))) {
      expect(s.getAttribute('stop-color')).toBeNull()
      expect(s.getAttribute('style')).toContain('stop-color')
    }
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `npm test -- tests/overview-bieu-do.test.tsx`
Expected: FAIL — không tìm thấy module `@/features/ops/components/BieuDoNgay`

- [ ] **Step 3: Viết component**

Tạo `src/features/ops/components/BieuDoNgay.tsx`. Yêu cầu bắt buộc, kiểm bởi test trên:

1. Đo khung bằng `ResizeObserver` trên một `<div>` bọc, lưu `{W, H}` vào state; không vẽ khi `W` hoặc `H` bằng 0.
2. Render **JSX SVG** (không `document.createElementNS`, không `replaceChildren`) với `viewBox={\`0 0 ${W} ${H}\`}`, `role="img"`, `aria-label="Số phiên Chat và Voice mỗi ngày trong 7 ngày gần nhất"`.
3. Dùng đúng các hằng và công thức ở khối "Hình học" trên.
4. Gắn `data-vai` cho: `nen-luoi` (một `<rect>` trong suốt phủ đúng `PL,PT,iw,ih` — nó là mốc đối chiếu của test, không vẽ gì), `dai`, `vach-doc` (7 cái), `moc-y` (5 `<text>`), `diem-chat`, `diem-voice`.
5. `<stop>` đặt màu qua `style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0.22 }}` — **không** `stopColor=` như attribute.
6. Hàng nhãn ngày là `<div>` **ngoài** SVG, `style={{ padding: \`0 ${PR}px 0 ${PL}px\` }}`, bên trong là grid 7 cột đều nhau; mỗi nhãn có `data-testid={\`nhan-ngay-${i}\`}` và `white-space: nowrap`.
7. `onMouseMove` trên div bọc: `doiDangXem(clamp(Math.floor((e.clientX - rect.left - PL) / buoc), 0, 6))`. `onMouseLeave`: `doiDangXem(6)`.
8. Màu qua token: đường/điểm Chat dùng `var(--color-ds1)`, Voice dùng `var(--color-ds2)`. Không viết hex.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `npm test -- tests/overview-bieu-do.test.tsx && npm run build`
Expected: PASS 6 test

- [ ] **Step 5: Commit**

```bash
git add src/features/ops/components/BieuDoNgay.tsx tests/overview-bieu-do.test.tsx
git commit -m "feat(ops): bieu do hai duong Chat/Voice theo thang bang"
```

---

### Task 9: Ô Kiến thức — `TheKienThuc.tsx`

**Files:**
- Create: `odyssey-portal-frontend/src/features/ops/components/TheKienThuc.tsx`
- Test: `odyssey-portal-frontend/tests/overview-kien-thuc.test.tsx` (create)

**Interfaces:**
- Consumes: `MucKienThuc` (Task 6)
- Produces: `export function TheKienThuc({ muc }: { muc: readonly MucKienThuc[] })`

**Vì sao là HÀNG + THƯỚC KHẮC VẠCH, không phải sáu ô có thanh bo tròn:** ô ③ Khách đánh giá đã dùng thanh bo tròn đặc cho phân bố sao, và hai ô nằm cùng một màn. Cùng một hình thì mắt đọc ra *cùng một loại số*, trong khi một bên là phân bố phiếu còn bên kia là độ phủ kho. Nấc rời còn đọc được giá trị thô ("11 trên 14 vạch") khi in đen trắng.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/overview-kien-thuc.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TheKienThuc } from '@/features/ops/components/TheKienThuc'
import type { MucKienThuc } from '@/features/ops/api'

const MUC: MucKienThuc[] = [
  { khoa: 'duAn', thay: 8, tong: 12 },
  { khoa: 'phanKhu', thay: 31, tong: 47 },
  { khoa: 'can', thay: 964, tong: 1203 },
  { khoa: 'taiLieu', thay: 189, tong: 214 },
  { khoa: 'tepTraCuu', thay: 38, tong: 38 },
  { khoa: 'hoSoDuTruong', thay: 10, tong: 12 },
]

describe('TheKienThuc', () => {
  it('vẽ đủ sáu hàng theo đúng thứ tự backend trả về', () => {
    render(<TheKienThuc muc={MUC} />)
    const hang = screen.getAllByTestId(/^kt-hang-/)
    expect(hang.map((h) => h.dataset.khoa)).toEqual([
      'duAn', 'phanKhu', 'can', 'taiLieu', 'tepTraCuu', 'hoSoDuTruong',
    ])
  })

  it('mục ĐẦY hiện nhãn "đọc đủ", mục hụt hiện phần thiếu thành lời', () => {
    render(<TheKienThuc muc={MUC} />)
    expect(within(screen.getByTestId('kt-hang-tepTraCuu')).getByText(/đọc đủ/i)).toBeInTheDocument()
    expect(within(screen.getByTestId('kt-hang-duAn')).getByText(/4/)).toBeInTheDocument()
  })

  it('thước chỉ tô đủ 14 nấc khi thật sự 100%', () => {
    render(<TheKienThuc muc={MUC} />)
    const day = within(screen.getByTestId('kt-hang-tepTraCuu')).getAllByTestId('kt-nac-day')
    // 189/214 = 88,3% → làm tròn lên là 12,4 ⇒ 12; nhưng ca nguy hiểm là 13,6/14.
    const gan = within(screen.getByTestId('kt-hang-taiLieu')).getAllByTestId('kt-nac-day')

    expect(day).toHaveLength(14)
    expect(gan.length).toBeLessThanOrEqual(13)
  })

  it('không tô đủ nấc cho 99% — thước đầy cho kho còn thiếu là nói dối', () => {
    render(<TheKienThuc muc={[{ khoa: 'can', thay: 99, tong: 100 }]} />)
    expect(within(screen.getByTestId('kt-hang-can')).getAllByTestId('kt-nac-day')).toHaveLength(13)
  })

  it('cộng gộp theo MỤC, không lấy trung bình sáu tỉ lệ', () => {
    render(<TheKienThuc muc={MUC} />)
    // 8+31+964+189+38+10 = 1240 ; 12+47+1203+214+38+12 = 1526 ; 81%
    const tong = screen.getByTestId('kt-tong')
    expect(tong).toHaveTextContent('1.240')
    expect(tong).toHaveTextContent('1.526')
    expect(tong).toHaveTextContent('81%')
  })

  it('mục lạ backend thêm sau vẫn vẽ được, không vỡ màn', () => {
    render(<TheKienThuc muc={[{ khoa: 'khoaMoiChuaBiet', thay: 1, tong: 2 }]} />)
    expect(screen.getByTestId('kt-hang-khoaMoiChuaBiet')).toBeInTheDocument()
  })

  it('tong = 0 không sinh NaN%', () => {
    render(<TheKienThuc muc={[{ khoa: 'duAn', thay: 0, tong: 0 }]} />)
    expect(screen.getByTestId('kt-tong')).not.toHaveTextContent('NaN')
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `npm test -- tests/overview-kien-thuc.test.tsx`
Expected: FAIL — không tìm thấy module

- [ ] **Step 3: Viết component**

Tạo `src/features/ops/components/TheKienThuc.tsx`. Yêu cầu bắt buộc:

1. Bảng nhãn tra theo `khoa` (nhãn · điều kiện · icon · danh từ đếm phần hụt):

```ts
const NHAN: Readonly<Record<string, { ten: string; dk: string; icon: IconName }>> = {
  duAn:         { ten: 'Dự án',           dk: 'đã phát hành',    icon: 'projects' },
  phanKhu:      { ten: 'Phân khu',        dk: 'đã phát hành',    icon: 'gaps' },
  can:          { ten: 'Căn / sản phẩm',  dk: 'đã phát hành',    icon: 'appts' },
  taiLieu:      { ten: 'Tài liệu dự án',  dk: 'đính kèm dự án',  icon: 'kb' },
  tepTraCuu:    { ten: 'Tệp tra cứu',     dk: 'đã nhúng vector', icon: 'audit' },
  hoSoDuTruong: { ten: 'Hồ sơ đủ trường', dk: 'đủ mọi trường',   icon: 'quality' },
}
```

⚠️ **Ba dòng đầu ghi «đã phát hành» giống hệt nhau là ĐÚNG, đừng "làm cho phong phú".** Bản demo ghi «còn mở bán» cho `can` — đọc hay hơn, nhưng SQL ở Task 3 đếm `status = 'published'` chứ không phải `sale_status = 'available'`, nên câu chữ đó nói một điều kiện lọc không tồn tại. Cột này tồn tại để nói ĐÚNG cái lọc đang chạy; ba dòng trùng nhau chính là thông tin («ba mục này cùng một luật»). Muốn `can` thật sự lọc theo mở bán thì sửa SQL trước, sửa nhãn sau.

`IconName` chỉ nhận tên đã khai trong `src/components/icons.tsx` — sáu tên trên đều có sẵn. **Không thêm icon mới cho task này**; `tsc -b` là cổng nếu gõ sai tên.

Khoá lạ ⇒ dùng chính `khoa` làm tên và `dk: ''` — **không bỏ hàng**: backend thêm mục mới mà FE nuốt im lặng là giấu đúng thứ cần thấy.

2. Mỗi hàng: `data-testid={\`kt-hang-${m.khoa}\`}` và `data-khoa={m.khoa}`. Lưới 7 cột: `[30px] [tên 1fr] [điều kiện 1.15fr] [78px `thay / tong`] [thước] [46px %] [148px nhãn]`, gap 12px, nền `fill`, viền `border`, bo `radius-md`, hover `bg-acs-manh`.
3. Thước 14 nấc: mỗi nấc `<i>` rộng 3px cao 16px bo `--radius-mark`. Nấc đã đạt mang `data-testid="kt-nac-day"`, nền `var(--color-ac)` với `opacity = 0.4 + 0.6 * i/(n-1)`. Số nấc:

```ts
const NAC = 14
const day = thay === tong && tong > 0 ? NAC : Math.min(NAC - 1, Math.round((thay / tong) * NAC))
```

4. Nhãn phải: `thay === tong && tong > 0` ⇒ viên nhãn `acs`/`acd` chữ "Agent đọc đủ"; ngược lại viên nhãn `badge-warn-*` chữ `` `${tong - thay} chưa đọc được` ``. Mỗi viên có một chấm tròn 6px cùng màu chữ — **trạng thái không bao giờ chỉ có màu**.
5. Dòng cộng gộp `data-testid="kt-tong"`: `` `${dinhDang(a)} / ${dinhDang(b)} mục · ${b > 0 ? Math.round((a/b)*100) : 0}% agent đọc được` `` với `a = sum(thay)`, `b = sum(tong)`. **Cộng theo mục, không trung bình sáu tỉ lệ** — trung bình cho «dự án» (12 mục) cùng trọng số với «căn» (1.203 mục).
6. Số định dạng `vi-VN` (dấu chấm ngăn nghìn).

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `npm test -- tests/overview-kien-thuc.test.tsx && npm run build`
Expected: PASS 7 test

- [ ] **Step 5: Commit**

```bash
git add src/features/ops/components/TheKienThuc.tsx tests/overview-kien-thuc.test.tsx
git commit -m "feat(ops): o Kien thuc dang hang + thuoc khac vach"
```

---

### Task 10: Ô Chuyển sale và ô Khách đánh giá

**Files:**
- Create: `odyssey-portal-frontend/src/features/ops/components/GaugeNuaCung.tsx`
- Create: `odyssey-portal-frontend/src/features/ops/components/TheDanhGia.tsx`
- Test: `odyssey-portal-frontend/tests/overview-gauge-danh-gia.test.tsx` (create)

**Interfaces:**
- Consumes: `Overview['chuyenSale']`, `Overview['danhGia']` (Task 6); `Sao` từ `@/components/ui/Sao`
- Produces: `export function GaugeNuaCung({ chuyen, tuXuLy })`, `export function TheDanhGia({ danhGia })`

**Hai quyết định đã chốt ở spec, đừng đảo:**
- **Nửa cung, không donut.** Vòng tròn kín nói "đây là cơ cấu chia phần" — hai mảng ngang hàng. Ô này hỏi *một tỉ lệ trên thang 0→100*, mà nửa cung có điểm đầu và điểm cuối. Thêm nữa lỗ donut là chỗ đặt số, nên số luôn phải nhỏ đi để lọt vào.
- **Một sắc + một máng trung tính.** «Agent tự xử lý» không phải chuỗi đối lập cần màu riêng — nó là phần *chưa tới* của cùng một thang. Tô nó thành màu thứ hai là bịa ra một sự đối đầu.
- **`Sao` IMPORT, KHÔNG chép lại.** Component đã dùng ở `/quality` và `PhienKhach.tsx`; bản thứ ba là ba chỗ phải sửa mỗi lần đổi hình ngôi sao.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/overview-gauge-danh-gia.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GaugeNuaCung } from '@/features/ops/components/GaugeNuaCung'
import { TheDanhGia } from '@/features/ops/components/TheDanhGia'

describe('GaugeNuaCung', () => {
  it('in tỉ lệ theo vi-VN (dấu phẩy thập phân)', () => {
    render(<GaugeNuaCung chuyen={73} tuXuLy={265} />)
    expect(screen.getByText('21,6%')).toBeInTheDocument()
  })

  it('tổng = 0 không sinh NaN', () => {
    render(<GaugeNuaCung chuyen={0} tuXuLy={0} />)
    expect(screen.getByTestId('gauge-so')).toHaveTextContent('0%')
    expect(screen.getByTestId('gauge-so')).not.toHaveTextContent('NaN')
  })

  it('tỉ lệ rất nhỏ vẫn vẽ ra một vệt nhìn thấy được', () => {
    /* 1/5000 = 0,02% ⇒ cung dài 0,1px là không vẽ gì. Sàn 1,2% giữ nó hiện
       diện; con số bên cạnh vẫn nói sự thật. */
    render(<GaugeNuaCung chuyen={1} tuXuLy={4999} />)
    const cung = screen.getByTestId('gauge-cung')
    expect(Number(cung.getAttribute('stroke-dasharray')!.split(' ')[0])).toBeGreaterThan(2)
  })
})

describe('TheDanhGia', () => {
  const DG = {
    trungBinh: 4.33,
    truoc: 4.41,
    tong: 190,
    theoSao: { '1': 4, '2': 8, '3': 20, '4': 48, '5': 110 },
  } as const

  it('hiện điểm, tổng lượt và đủ 5 dòng phân bố', () => {
    render(<TheDanhGia danhGia={DG} />)
    expect(screen.getByText('4,33')).toBeInTheDocument()
    expect(screen.getByText(/190/)).toBeInTheDocument()
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByTestId(`dg-sao-${n}`)).toBeInTheDocument()
    }
  })

  it('KHÔNG làm tròn khi vẽ sao — 4,33 phải tô MỘT PHẦN ngôi thứ năm', () => {
    /* `Sao` không có aria-label; móc test của nó là `data-sao` / `data-phan`
       (xem `tests/sao.test.tsx`). Làm tròn 4,33 → 4 cho ra 4 ngôi «on» + 1
       «off» và KHÔNG có ngôi nào «phan» — đó chính là ca cần bắt. */
    const { container } = render(<TheDanhGia danhGia={DG} />)

    expect(container.querySelectorAll('[data-sao="on"]')).toHaveLength(4)
    const le = container.querySelectorAll('[data-sao="phan"]')
    expect(le).toHaveLength(1)
    expect(le[0]!.getAttribute('data-phan')).toBe('33')
  })

  it('`truoc = null` ⇒ KHÔNG vẽ mũi tên delta', () => {
    render(<TheDanhGia danhGia={{ ...DG, truoc: null }} />)
    expect(screen.queryByTestId('dg-delta')).not.toBeInTheDocument()
  })

  it('tong = 0 ⇒ thanh phân bố rộng 0%, không NaN%', () => {
    render(
      <TheDanhGia
        danhGia={{ trungBinh: 0, truoc: null, tong: 0, theoSao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 } }}
      />,
    )
    const thanh = screen.getByTestId('dg-sao-5').querySelector('[data-vai="thanh"]') as HTMLElement
    expect(thanh.style.width).toBe('0%')
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `npm test -- tests/overview-gauge-danh-gia.test.tsx`
Expected: FAIL — không tìm thấy hai module

- [ ] **Step 3: Viết hai component**

`GaugeNuaCung.tsx` — nửa cung SVG `R=84, dày=11, rộng=208`, máng `fill-strong`, cung `var(--color-ds2)`, `stroke-linecap="round"`:

```ts
const ti = chuyen + tuXuLy > 0 ? chuyen / (chuyen + tuXuLy) : 0
const DAI = Math.PI * R                       // độ dài nửa cung
// Sàn 1,2%: một tỉ lệ nhỏ xíu vẫn phải để lại vệt — xem test.
const ve = ti > 0 ? Math.max(DAI * 0.012, DAI * ti) : 0
// strokeDasharray = `${ve} ${DAI - ve}`, data-testid="gauge-cung"
```

Số ở miệng cung: `data-testid="gauge-so"`, định dạng `new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(ti * 100) + '%'`. Chú thích hai dòng bên dưới: một chấm `ds2` «Chuyển sale», một chấm `fill-strong` «Agent tự xử lý».

`TheDanhGia.tsx` — cột đầu là điểm lớn + `<Sao gia={danhGia.trungBinh} kichThuoc={17} />` (**không** làm tròn) + `«N lượt đánh giá»`; `truoc !== null` thì thêm `data-testid="dg-delta"` với dấu và màu theo chiều. Bên dưới 5 dòng `data-testid={\`dg-sao-${n}\`}` từ 5★ xuống 1★, mỗi dòng có `<span data-vai="thanh" style={{ width: \`${tong > 0 ? (theoSao[k]/tong)*100 : 0}%\` }} />`.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `npm test -- tests/overview-gauge-danh-gia.test.tsx && npm run build`
Expected: PASS 7 test

- [ ] **Step 5: Commit**

```bash
git add src/features/ops/components/GaugeNuaCung.tsx src/features/ops/components/TheDanhGia.tsx tests/overview-gauge-danh-gia.test.tsx
git commit -m "feat(ops): gauge nua cung Chuyen sale + o Khach danh gia"
```

---

### Task 11: Lắp màn `/dashboard` và dọn demo

**Files:**
- Create: `odyssey-portal-frontend/src/features/ops/components/TongQuanScreen.tsx`
- Modify: `odyssey-portal-frontend/src/routes/_app/dashboard.tsx`
- Delete: `odyssey-portal-frontend/public/demo-tong-quan.html`
- Test: `odyssey-portal-frontend/tests/overview-man.test.tsx` (create)

**Interfaces:**
- Consumes: `overview`, `KHOA_OVERVIEW` (Task 6); bốn component Task 8–10
- Produces: `export function TongQuanScreen()`

**Bố cục — lưới bento 12 cột, 2 hàng, khoá trong một màn:** `height:100dvh` + `overflow:hidden` → cột flex → `grid-template-rows: 1fr 1fr` + `min-height: 0` **trên mọi ô**. `dvh` chứ không `vh`: trên di động `100vh` cao hơn chỗ thật sự nhìn thấy nên màn "không cuộn" vẫn cuộn được vài chục pixel.

Hàng 1: ① Hội thoại `span 5` · ② Chuyển sale `span 3` · ③ Khách đánh giá `span 4`
Hàng 2: ⑤ Kiến thức `span 8` · ⑥ Usage & Billing `span 4` (chỗ đã chừa, viền nét đứt, chưa có dữ liệu)

Dưới 1240px: `grid-template-rows: repeat(3, 1fr)` và mọi ô `span 6`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/overview-man.test.tsx`:

```tsx
/**
 * Render component trực tiếp, không boot router — đơn vị đang kiểm là
 * `TongQuanScreen`. Cùng lý lẽ `khoa-dau-noi.test.tsx:11`.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TongQuanScreen } from '@/features/ops/components/TongQuanScreen'
import { opsHandlers } from '@/features/ops/msw'

const server = setupServer(...opsHandlers)
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function veRoi() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TongQuanScreen />
    </QueryClientProvider>,
  )
}

describe('TongQuanScreen', () => {
  it('vẽ đủ năm ô sau khi dữ liệu về', async () => {
    veRoi()
    await waitFor(() => expect(screen.getByTestId('o-hoi-thoai')).toBeInTheDocument())
    for (const k of ['o-hoi-thoai', 'o-chuyen-sale', 'o-danh-gia', 'o-kien-thuc', 'o-usage']) {
      expect(screen.getByTestId(k)).toBeInTheDocument()
    }
  })

  it('tổng hội thoại và tổng theo kênh nói cùng một con số', async () => {
    veRoi()
    await waitFor(() => expect(screen.getByTestId('ht-tong')).toHaveTextContent('338'))
    expect(screen.getByTestId('ht-chu-thich')).toHaveTextContent('166')
    expect(screen.getByTestId('ht-chu-thich')).toHaveTextContent('127')
  })

  it('đang tải thì hiện khung chờ, KHÔNG hiện số 0', async () => {
    veRoi()
    expect(screen.getByTestId('tong-quan-dang-tai')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('tong-quan-dang-tai')).not.toBeInTheDocument())
  })

  it('API lỗi thì hiện thông báo, không trắng màn', async () => {
    server.use(
      http.get('/api/v1/overview', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'Không có quyền' } }, { status: 403 }),
      ),
    )
    veRoi()
    await waitFor(() => expect(screen.getByTestId('tong-quan-loi')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `npm test -- tests/overview-man.test.tsx`
Expected: FAIL — không tìm thấy `TongQuanScreen`

- [ ] **Step 3: Viết màn + gắn route**

`TongQuanScreen.tsx`:

```tsx
const q = useQuery({ queryKey: KHOA_OVERVIEW, queryFn: overview })
```

- `q.isPending` ⇒ `<div data-testid="tong-quan-dang-tai">` với 5 khung xám đúng vị trí 5 ô. **Không render số 0** — một màn đầy số 0 trông như workspace rỗng, không như đang tải.
- `q.error` ⇒ `<div data-testid="tong-quan-loi">` in `error.message` + nút "Thử lại" gọi `q.refetch()`.
- Có dữ liệu ⇒ lưới bento như mô tả trên. `dangXem` là state khởi tạo `chuoi.length - 1`; truyền xuống `BieuDoNgay`.
- Ô ① mang `data-testid="o-hoi-thoai"`, số lớn `data-testid="ht-tong"`, dòng chú thích `data-testid="ht-chu-thich"` in `Chat {n} · Voice {n}` cộng phần còn lại gọi đúng tên kênh từ `theoKenh`.
- Ô ⑥ `data-testid="o-usage"` — viền nét đứt, hai dòng «Lượng dùng» / «Gói cước», badge «Chưa có». Đây là **chỗ đã chừa**, để đúng chỗ ngay từ bây giờ thì ngày có dữ liệu chỉ thay tại chỗ, không xếp lại cả lưới.

`src/routes/_app/dashboard.tsx` — thay `ScreenStub`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { TongQuanScreen } from '@/features/ops/components/TongQuanScreen'

export const Route = createFileRoute('/_app/dashboard')({
  component: TongQuanScreen,
})
```

- [ ] **Step 4: Chạy toàn bộ cổng**

Run:
```bash
npm test && npm run build && npm run lint
```
Expected: PASS toàn bộ. `tests/boot.test.tsx` (vòng mount mọi màn) và `tests/nav-registry.test.ts` phải vẫn xanh — `dashboardNav` và `SCREENS['dashboard']` đã khai từ trước, task này không đụng tới chúng.

- [ ] **Step 5: Kiểm bằng mắt ở hai độ phân giải**

Chạy `npm run dev`, mở `http://localhost:5273/dashboard`, chụp ở 1920×1080 và 1440×900:

```bash
google-chrome --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --screenshot=/tmp/tq-1920.png --window-size=1920,1080 \
  --virtual-time-budget=3500 http://localhost:5273/dashboard
google-chrome --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --screenshot=/tmp/tq-1440.png --window-size=1440,900 \
  --virtual-time-budget=3500 http://localhost:5273/dashboard
```

Đối chiếu với `public/demo-tong-quan.html` trước khi xoá nó. Danh sách kiểm:
- không có thanh cuộn dọc ở cả hai kích thước
- rê chuột vào cột đầu tiên: dải xanh nằm **trọn trong lưới**, đáy khít đường nền, nhãn `T6 7/8` khớp tâm dải
- nhãn điều kiện ở ô Kiến thức không bị cắt giữa chữ ở 1440
- `964 / 1.203` không đè lên thước

*Bước này không thay được bằng test: validator kiểm màu, vitest kiểm hình học từng component — không cái nào thấy hai ô đè nhau.*

- [ ] **Step 6: Xoá demo và commit**

```bash
rm odyssey-portal-frontend/public/demo-tong-quan.html
git add -A odyssey-portal-frontend/src odyssey-portal-frontend/tests odyssey-portal-frontend/public
git commit -m "feat(ops): man Tong quan /dashboard + go file demo"
```

---

## Ghi chú cho người thực hiện

**Thứ tự bắt buộc:** Task 1 → 2 → 3 → 4 (backend, mỗi task phụ thuộc task trước). Task 5 → 6 → 7 rồi 8/9/10 (ba task này **độc lập nhau**, chạy song song được) → 11.

**Chạy backend để thử tay:** `make dev && make migrate && make api` (cổng 8100). Frontend `npm run dev` (cổng 5273) proxy `^/api/` sang đó. Không chạy backend thì MSW của Task 7 gánh — đó là lý do nó tồn tại.

**Đã CẮT khỏi phạm vi, và vì sao** (spec §6, đừng thêm lại):
- Sơ đồ tầng dữ liệu 4 tầng — ý cốt lõi của nó (*dự án còn nháp thì agent không thấy*) đã nằm gọn trong ô ⑤.
- Ô «Kỹ năng agent đã dùng» — chủ sản phẩm chốt 2026-08-13: biết agent gọi `kb_search` 103 lần không dẫn tới quyết định nào. Cột `skill_calls` vẫn còn trong DB.
- Bộ lọc khoảng thời gian ở đầu màn — nút `7 ngày / 4 tuần / Tất cả` trong demo là **trang trí**, backend chỉ nhận một cửa sổ. Ngày cần thật thì thêm query param `so_ngay` vào Task 4 và một task riêng cho state ở URL.
