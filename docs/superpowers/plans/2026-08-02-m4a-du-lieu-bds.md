# M4a — Dữ liệu BĐS · Kế hoạch thi công

> **Cho agentic worker:** BẮT BUỘC dùng sub-skill `superpowers:subagent-driven-development`
> (khuyến nghị) hoặc `superpowers:executing-plans` để thi công từng task. Các bước dùng
> checkbox (`- [ ]`) để theo dõi.

**Goal:** Đưa `tenant_data.projects`/`units` từ *"vừa đủ chứng minh cách ly"* lên *"đủ để agent tư
vấn bằng dữ liệu thật"*, kèm đường nạp hàng loạt và cơ chế quyết định trường nào agent đọc được.

**Architecture:** Một module mới `portal.modules.realestate` theo đúng nếp `modules/kb` của M6:
ba hàm thuần (`gia.py` · `nhap_lieu.py` · `chinh_sach.py`) không chạm DB, cộng
`repo/service/router/contracts`. Hai migration trong dải `0400`–`0499`: `0400` thêm cột và bảng,
`0401` dựng lại view `agent_api`. Mọi truy vấn `tenant_data` đi qua `tenant_conn()`.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · Alembic · pydantic v2 · `openpyxl` (đã có từ M6)
· `csv` stdlib · pytest + testcontainers · ruff (line-length 120).

## Global Constraints

- **Tiền là `bigint` VND.** Không cột nào tên `*_ty`. Đổi đơn vị **chỉ** ở biên nhập, qua
  `gia.doi_don_vi_gia()`. Không chỗ nào tự nhân `1e9`.
- **Thời gian `timestamptz`**, UTC trong DB.
- **Comment và docstring bằng tiếng Việt**, giải thích *vì sao* chứ không chỉ *cái gì*.
- **Lint:** ruff, `line-length = 120`, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- **Mọi route khai `require(action)`** — thiếu là `tests/api/test_moi_route_khai_action.py` đỏ.
  M4a dùng `ACTIONS.CATALOG_READ` · `CATALOG_WRITE` · `CATALOG_DELETE`, **không thêm action mới**.
- **Mọi bảng `tenant_data` mới gọi `control.enforce_tenant_isolation()`** — thiếu là cổng 6 của
  M1 đỏ.
- **Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`** — vi phạm là
  `tests/test_module_boundaries.py` đỏ.
- **Repo function không nhận `tenant_id`** (trừ `INSERT`): RLS đã lọc. Nhận thêm tham số đó là mời
  người sau lọc bằng tay rồi tưởng thế là đủ.
- **Lỗi:** module `raise loi.LoiPortal(ma, http, thong_diep)`, không tự trả JSON.
- **Nhật ký:** `nhat_ky.ghi(conn, tenant_id, hanh_dong, actor, chi_tiet)` gọi **sau khi** việc xong.
- **Spec nguồn:** `docs/superpowers/specs/2026-08-02-m4a-du-lieu-bds-design.md`.
  Kiểm kê trường: `docs/superpowers/specs/_m4a-kiem-ke-truong.md`.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `src/portal/modules/realestate/gia.py` | Đổi đơn vị giá tỷ → VND. **Hàm thuần** |
| `src/portal/modules/realestate/nhap_lieu.py` | `bytes` → hàng → `BaoCaoChayThu`. **Hàm thuần** |
| `src/portal/modules/realestate/chinh_sach.py` | Ba cờ · lọc tên trường · suy trường thiếu. **Hàm thuần** |
| `src/portal/modules/realestate/contracts.py` | Mặt tiền: pydantic + danh sách cột hợp lệ |
| `src/portal/modules/realestate/repo.py` | SQL asyncpg thô |
| `src/portal/modules/realestate/service.py` | Ghép chạy thử với dữ liệu đang có · áp dụng |
| `src/portal/modules/realestate/router.py` | 11 endpoint |
| `migrations/versions/0400_bds_full_fields.py` | +4 cột `projects` · +22 `units` · +2 `field_policy_live` · 4 bảng mới |
| `migrations/versions/0401_agent_api_bds.py` | Dựng lại 2 view `agent_api` |
| `scripts/seed_bds.py` | 56 hàng `field_policy_live` + dữ liệu mẫu |

**Thứ tự 12 task:**

```
T1  gia.py          ─┐
T2  migration 0400   ├─> T3 migration 0401 (view)
T4  nhap_lieu.py    ─┘
T5  chinh_sach.py ──> T6 contracts + repo ──> T7  CRUD
                                          ├─> T8  field-policy · data-gaps
                                          ├─> T9  import hai bước
                                          ├─> T10 seed_bds
                                          ├─> T11 hai cổng quét động
                                          └─> T12 overview + ba bảng con
```

T1 · T2 · T4 · T5 độc lập nhau, làm song song được. T7–T12 đều sửa `router.py`
nên **phải tuần tự** — hai subagent cùng sửa file đó là hai lần merge tay.

> **Vì sao hai migration chứ không một** (spec §2.4 ghi *"migration `0400`"*): `0401` sửa view của
> M1 — một bề mặt khác hẳn, với cổng test khác hẳn. Tách ra để `git revert` được riêng phần view khi
> nó sai mà không mất 26 cột. Cả hai vẫn nằm trong dải `0400`–`0499` của M4.

---

## Task 1: `gia.py` — đổi đơn vị giá

**Files:**
- Create: `src/portal/modules/realestate/__init__.py`
- Create: `src/portal/modules/realestate/gia.py`
- Test: `tests/modules/realestate/__init__.py`, `tests/modules/realestate/test_gia.py`

**Interfaces:**
- Consumes: không gì
- Produces: `doi_don_vi_gia(nhap: str | float | int | None) -> int | None` — raise
  `LoiGiaKhongHopLe(thong_diep: str)` khi không parse được. Task 4, 7, 8, 11 đều gọi.

- [ ] **Step 1: Tạo thư mục và file rỗng**

```bash
cd odyssey-portal-backend
mkdir -p src/portal/modules/realestate tests/modules/realestate
touch src/portal/modules/realestate/__init__.py tests/modules/realestate/__init__.py
```

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/modules/realestate/test_gia.py`:

```python
"""Đổi đơn vị giá — HÀM THUẦN, không cần Postgres.

Đây là bug agent đã phải sửa một lần: giá lưu bằng tỷ, đọc ra nhân nhầm hệ số
1e9. DL_01 BR05 chốt: đổi TẠI BIÊN NHẬP, lưu VND, không bao giờ đổi ở tầng đọc.
"""

import pytest

from portal.modules.realestate.gia import LoiGiaKhongHopLe, doi_don_vi_gia


@pytest.mark.parametrize(
    ("nhap", "mong_doi"),
    [
        ("5,62", 5_620_000_000),
        ("5.62", 5_620_000_000),
        (5.62, 5_620_000_000),
        ("5", 5_000_000_000),
        (0, 0),
        ("  7,1  ", 7_100_000_000),
        ("0,085", 85_000_000),
    ],
)
def test_doi_dung_he_so(nhap, mong_doi):
    assert doi_don_vi_gia(nhap) == mong_doi


@pytest.mark.parametrize("nhap", [None, "", "   "])
def test_rong_tra_none(nhap):
    """Rỗng KHÁC 0. Ô giá bỏ trống là 'chưa biết', không phải 'miễn phí' — và
    BR03 sẽ bỏ hẳn khoá đó khỏi kết quả trả cho agent."""
    assert doi_don_vi_gia(nhap) is None


@pytest.mark.parametrize("nhap", ["abc", "5,6,2", "-1", "1e5", "12000"])
def test_khong_hop_le_thi_no(nhap):
    """`12000` (tỷ) bị chặn bằng ngưỡng trên: một căn hộ 12 nghìn tỷ là dấu hiệu
    người dùng đã nhập sẵn đơn vị VND vào ô ghi 'tỷ'. Nhận im lặng là ghi vào DB
    một con số sai hệ số một tỷ — đúng cái BR05 sinh ra để chặn."""
    with pytest.raises(LoiGiaKhongHopLe):
        doi_don_vi_gia(nhap)
```

- [ ] **Step 3: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_gia.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.realestate.gia'`

- [ ] **Step 4: Viết `gia.py`**

```python
"""Đổi đơn vị giá — HÀM THUẦN, không I/O.

BA QUYẾT ĐỊNH ĐÃ CHỐT, đừng đổi mà không đọc lý do:

1. `Decimal`, KHÔNG `float`. `5.62 * 1e9` bằng float cho ra 5619999999.999999
   trên một số nền tảng. Đây là tiền; sai một đồng là sai.

2. Cả `,` lẫn `.` đều là dấu THẬP PHÂN. Không xử lý dấu phân nhóm nghìn.
   Người Việt gõ "5,62"; người copy từ Excel tiếng Anh gõ "5.62"; cả hai đều là
   5,62 tỷ. Còn "1.200" thì hiểu là 1,2 — vì một căn hộ 1.200 tỷ không tồn tại,
   trong khi 1,2 tỷ thì rất thường. Ngưỡng trên ở dưới chặn nốt phần còn lại.

3. NGƯỠNG TRÊN 10.000 tỷ. Nó không bảo vệ khỏi người dùng cẩu thả — nó bảo vệ
   khỏi người dùng nhập sẵn VND ("5620000000") vào ô ghi 'tỷ'. Nhận im lặng là
   ghi vào DB một con số sai hệ số một tỷ, và không ai phát hiện cho tới khi
   agent đọc nó cho khách.
"""

from decimal import Decimal, InvalidOperation

MOT_TY = Decimal(1_000_000_000)

NGUONG_TREN_TY = Decimal(10_000)
"""10.000 tỷ. Xem docstring module — đây là bẫy bắt người nhập nhầm đơn vị."""


class LoiGiaKhongHopLe(ValueError):
    """Người gọi bắt nó và dịch sang ER_02 (form) hoặc một dòng lỗi (import)."""


def doi_don_vi_gia(nhap: str | float | int | None) -> int | None:
    """Nhận giá người dùng nhập bằng TỶ, trả `int` VND. Rỗng trả `None`.

    Rỗng KHÁC 0: ô bỏ trống là "chưa biết", còn 0 là một mức giá thật (căn tặng
    kèm). BR03 chỉ bỏ khoá khi giá trị là `None`.
    """
    if nhap is None:
        return None

    chuoi = str(nhap).strip()
    if not chuoi:
        return None

    chuoi = chuoi.replace(",", ".")
    if chuoi.count(".") > 1:
        raise LoiGiaKhongHopLe("Giá chỉ được có một dấu thập phân")

    try:
        ty = Decimal(chuoi)
    except InvalidOperation as e:
        raise LoiGiaKhongHopLe("Giá phải là số, ví dụ 5,62") from e

    # `Decimal("1e5")` parse được nhưng ký hiệu mũ không phải thứ người dùng gõ
    # vào một ô giá — nó đến từ Excel xuất sai định dạng. Từ chối để nó lộ ra.
    if "e" in chuoi.lower():
        raise LoiGiaKhongHopLe("Giá phải là số, ví dụ 5,62")

    if ty < 0:
        raise LoiGiaKhongHopLe("Giá không được âm")

    if ty > NGUONG_TREN_TY:
        raise LoiGiaKhongHopLe(
            f"Giá {chuoi} vượt {NGUONG_TREN_TY} tỷ — ô này nhập bằng TỶ, không phải VND"
        )

    return int(ty * MOT_TY)
```

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_gia.py -v`
Expected: PASS — 15 test

- [ ] **Step 6: Lint và commit**

```bash
uv run ruff check src/portal/modules/realestate tests/modules/realestate
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate tests/modules/realestate
git commit -m "feat(m4a): đổi đơn vị giá tỷ→VND — hàm thuần, Decimal, có ngưỡng trên (T1)"
```

---

## Task 2: Migration `0400` — cột và bảng mới

**Files:**
- Create: `migrations/versions/0400_bds_full_fields.py`
- Test: `tests/modules/realestate/test_schema.py`

**Interfaces:**
- Consumes: `control.enforce_tenant_isolation(regclass)` từ M1 (`0003_role_isolation`)
- Produces: 26 cột mới trên `tenant_data.projects`/`units`; 2 cột mới trên
  `control.field_policy_live` (`form_visible` · `required_for_agent`); 4 bảng
  `tenant_data.project_highlights` · `project_progress` · `project_documents` · `import_jobs`.
  Task 3, 6, 9, 10, 11 đều dựa vào.

- [ ] **Step 1: Xác nhận revision head hiện tại**

Run: `uv run alembic heads`
Expected: `0300_kb_files (head)` — nếu khác, sửa `down_revision` ở Step 3 cho khớp.

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/modules/realestate/test_schema.py`:

```python
"""Schema của M4a. Đây là NGOẠI LỆ đã hẹn trước của luật §4④ (spec tổng):
`0004_tenant_data_core.py` ghi thẳng trong header rằng M4 sẽ ALTER hai bảng lõi.

Bốn bảng mới ở `tenant_data` ⇒ đều phải chịu RLS + FORCE. Cổng 6 của M1 sẽ tự
bắt nếu quên, nhưng test ở đây nói rõ ràng buộc để người đọc không phải suy.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration

COT_PROJECTS_MOI = ("parent_code", "sort_order", "is_featured", "agent_enabled")

COT_UNITS_MOI = (
    "investor", "zone", "building", "bathrooms", "price_label",
    "price_tttd_vnd", "price_loan_vnd", "loan_info", "is_hot", "hot_sort",
    "delivery_standard", "floor_min", "floor_max", "axis", "front",
    "check_time", "description", "is_active", "sort_order", "sale_email",
    "lat", "lng",
)

BANG_MOI = (
    "project_highlights", "project_progress", "project_documents", "import_jobs",
)


async def _co_cot(pool: asyncpg.Pool, schema: str, bang: str, cot: str) -> bool:
    return await pool.fetchval(
        """SELECT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = $1 AND table_name = $2 AND column_name = $3)""",
        schema, bang, cot,
    )


@pytest.mark.parametrize("cot", COT_PROJECTS_MOI)
async def test_projects_co_cot_moi(pool: asyncpg.Pool, cot: str):
    assert await _co_cot(pool, "tenant_data", "projects", cot)


@pytest.mark.parametrize("cot", COT_UNITS_MOI)
async def test_units_co_cot_moi(pool: asyncpg.Pool, cot: str):
    assert await _co_cot(pool, "tenant_data", "units", cot)


@pytest.mark.parametrize("cot", ("form_visible", "required_for_agent"))
async def test_field_policy_co_hai_co_moi(pool: asyncpg.Pool, cot: str):
    """Ngoại lệ §4④: M4a sửa bảng của M1. An toàn vì `pol()` và `gated_extras()`
    chỉ đọc `agent_readable` + `is_core`, và cả hai cột mới đều có DEFAULT."""
    assert await _co_cot(pool, "control", "field_policy_live", cot)


async def test_khong_cot_nao_ten_ty(pool: asyncpg.Pool):
    """QUÉT ĐỘNG. Bắt được người thêm cột `price_ty` sáu tháng nữa — luật tiền
    của spec tổng §6.2, và là bug agent đã sửa một lần."""
    xau = await pool.fetch(
        """SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'tenant_data'
              AND (column_name LIKE '%\\_ty' OR column_name LIKE '%\\_ty\\_%')"""
    )
    assert not xau, f"cột đặt tên theo đơn vị tỷ: {[dict(r) for r in xau]}"


@pytest.mark.parametrize("bang", BANG_MOI)
async def test_bang_moi_o_tenant_data_va_co_rls(pool: asyncpg.Pool, bang: str):
    o_dau = await pool.fetchval(
        "SELECT table_schema FROM information_schema.tables WHERE table_name = $1", bang
    )
    assert o_dau == "tenant_data"

    rls = await pool.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = $1", bang
    )
    assert rls["relrowsecurity"], f"{bang} chưa bật RLS"
    assert rls["relforcerowsecurity"], f"{bang} chưa FORCE — chủ bảng sẽ bỏ qua policy"


async def test_gia_van_la_bigint(pool: asyncpg.Pool):
    for cot in ("price_vnd", "price_tts_vnd", "price_tttd_vnd", "price_loan_vnd"):
        kieu = await pool.fetchval(
            """SELECT data_type FROM information_schema.columns
                WHERE table_schema='tenant_data' AND table_name='units' AND column_name=$1""",
            cot,
        )
        assert kieu == "bigint", f"{cot} là {kieu}, phải là bigint VND"
```

- [ ] **Step 3: Viết migration**

Tạo `migrations/versions/0400_bds_full_fields.py`:

```python
"""M4a — đủ cột để agent tư vấn, cộng 4 bảng con

NGOẠI LỆ ĐÃ HẸN TRƯỚC (spec tổng §4④). `0004_tenant_data_core.py` viết thẳng
trong header: "M1 chỉ tạo cột LÕI. M4 ALTER thêm cột cho projects và units."
Đây là migration đó.

MIGRATION NÀY CÒN SỬA `control.field_policy_live` — bảng của M1. Ba điều làm nó
an toàn, và cả ba phải còn đúng nếu ai đó sửa lại:
  1. Chưa code nào đọc bảng đó ngoài portal.pol() và portal.gated_extras().
  2. Hai hàm ấy chỉ đọc `agent_readable` và `is_core` — thêm cột không đổi một
     dòng nào của 0005_agent_api.py.
  3. Cả hai cột mới có DEFAULT, nên hàng đang có không cần backfill.

VÌ SAO `parent_code` CHỨ KHÔNG `parent_id`: khoá tự nhiên của hai bảng này là
(tenant_id, code), không phải id. Tham chiếu bằng mã thì file CSV import mở bằng
Excel là đọc và sửa được; tham chiếu bằng id nội bộ thì tenant không tự soạn nổi.

VÌ SAO CÓ CỘT `building`/`floor` MÀ 0004 CẤM `tower`: 0004 cấm vì bộ LỌC theo
tầng/toà trả sai âm thầm (quyết định #17). DL_01 BR04 tách đúng chỗ — "bộ lọc
chỉ được mở khi dữ liệu thật có giá trị cho trường đó". Nên: tạo cột để tenant
NHẬP, seed field_policy_live.filterable = false. Đổi cờ đó là một quyết định về
DỮ LIỆU, không phải về schema. tests/.../test_bo_loc_co_du_lieu.py canh.

Revision ID: 0400_bds_full
Revises: 0300_kb_files
"""

from alembic import op

revision = "0400_bds_full"
down_revision = "0300_kb_files"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    # ─── projects: +4 ────────────────────────────────────────────────────────
    # `agent_enabled` KHÁC `status`. status là trạng thái BIÊN TẬP (draft/
    # published); agent_enabled là công tắc BR11 — "dự án tắt không xuất hiện
    # trong bất kỳ kết quả nào trả cho agent, kể cả khi khách gọi đích danh".
    # Gộp hai thứ là để một dự án draft vẫn được agent nhắc tới.
    op.execute(
        """
        ALTER TABLE tenant_data.projects
            ADD COLUMN parent_code   text    NOT NULL DEFAULT '',
            ADD COLUMN sort_order    integer NOT NULL DEFAULT 0,
            ADD COLUMN is_featured   boolean NOT NULL DEFAULT false,
            ADD COLUMN agent_enabled boolean NOT NULL DEFAULT true
        """
    )
    # Tự tham chiếu theo khoá tự nhiên. Cho phép '' (không có dự án mẹ) nên
    # dùng CHECK + index thay vì FK — FK không biểu diễn được "rỗng nghĩa là
    # không có" khi cột là NOT NULL DEFAULT ''.
    op.execute(
        """
        ALTER TABLE tenant_data.projects
            ADD CONSTRAINT projects_parent_khong_tu_tro CHECK (parent_code <> code)
        """
    )
    op.execute(
        "CREATE INDEX projects_tenant_parent_idx ON tenant_data.projects (tenant_id, parent_code)"
    )
    op.execute(
        "CREATE INDEX projects_tenant_agent_idx ON tenant_data.projects (tenant_id, agent_enabled)"
    )

    # ─── units: +22 ──────────────────────────────────────────────────────────
    # lat/lng LÀ CỘT MỚI: 0004 chỉ tạo chúng cho `projects`. Dễ sót khi đếm vì
    # tên trùng nhau.
    op.execute(
        """
        ALTER TABLE tenant_data.units
            ADD COLUMN investor          text    NOT NULL DEFAULT '',
            ADD COLUMN zone              text    NOT NULL DEFAULT '',
            ADD COLUMN building          text    NOT NULL DEFAULT '',
            ADD COLUMN bathrooms         smallint,
            ADD COLUMN price_label       text    NOT NULL DEFAULT '',
            ADD COLUMN price_tttd_vnd    bigint,
            ADD COLUMN price_loan_vnd    bigint,
            ADD COLUMN loan_info         text    NOT NULL DEFAULT '',
            ADD COLUMN is_hot            boolean NOT NULL DEFAULT false,
            ADD COLUMN hot_sort          integer NOT NULL DEFAULT 0,
            ADD COLUMN delivery_standard text    NOT NULL DEFAULT '',
            ADD COLUMN floor_min         smallint,
            ADD COLUMN floor_max         smallint,
            ADD COLUMN axis              text    NOT NULL DEFAULT '',
            ADD COLUMN front             text    NOT NULL DEFAULT '',
            ADD COLUMN check_time        timestamptz,
            ADD COLUMN description       text    NOT NULL DEFAULT '',
            ADD COLUMN is_active         boolean NOT NULL DEFAULT true,
            ADD COLUMN sort_order        integer NOT NULL DEFAULT 0,
            ADD COLUMN sale_email        text    NOT NULL DEFAULT '',
            ADD COLUMN lat               double precision,
            ADD COLUMN lng               double precision
        """
    )
    # Giá âm không phải dữ liệu, là lỗi nhập. CHECK ở đây rẻ hơn validate ở ba
    # đường code (form · import · seed) và không quên được.
    op.execute(
        """
        ALTER TABLE tenant_data.units
            ADD CONSTRAINT units_gia_khong_am CHECK (
                coalesce(price_vnd, 0) >= 0 AND coalesce(price_tts_vnd, 0) >= 0
                AND coalesce(price_tttd_vnd, 0) >= 0 AND coalesce(price_loan_vnd, 0) >= 0)
        """
    )
    op.execute(
        "CREATE INDEX units_tenant_hot_idx ON tenant_data.units (tenant_id, is_hot, hot_sort)"
    )

    # ─── field_policy_live: +2 (bảng của M1 — xem header) ────────────────────
    op.execute(
        """
        ALTER TABLE control.field_policy_live
            ADD COLUMN form_visible       boolean NOT NULL DEFAULT true,
            ADD COLUMN required_for_agent boolean NOT NULL DEFAULT false
        """
    )

    # ─── 4 bảng con ──────────────────────────────────────────────────────────
    # Ba bảng đầu tách ra vì lực 1-N (prototype: "5 điểm" · "9 mốc" ·
    # "6 tài liệu"), KHÔNG vì units/projects nhiều cột. Tách 1-1 thì bị loại —
    # xem spec §2.2.
    for ten, cot_rieng in (
        ("project_highlights", "noi_dung text NOT NULL CHECK (noi_dung <> '')"),
        (
            "project_progress",
            "tieu_de text NOT NULL CHECK (tieu_de <> ''), moc_ngay date, ghi_chu text NOT NULL DEFAULT ''",
        ),
        (
            "project_documents",
            "tieu_de text NOT NULL CHECK (tieu_de <> ''), link text NOT NULL CHECK (link <> '')",
        ),
    ):
        op.execute(
            f"""
            CREATE TABLE tenant_data.{ten} (
                id           bigserial PRIMARY KEY,
                tenant_id    {_TENANT_FK},
                project_code text NOT NULL CHECK (project_code <> ''),
                sort_order   integer NOT NULL DEFAULT 0,
                {cot_rieng},
                updated_at   timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        op.execute(
            f"CREATE INDEX {ten}_tenant_project_idx "
            f"ON tenant_data.{ten} (tenant_id, project_code, sort_order)"
        )
        op.execute(f"SELECT control.enforce_tenant_isolation('tenant_data.{ten}')")

    # ─── import_jobs ─────────────────────────────────────────────────────────
    # Ở `tenant_data`, không `control`: `report` chứa mã căn và giá của khách —
    # dữ liệu nghiệp vụ, phải chịu RLS. Cùng lý do kb_files ở tenant_data.
    #
    # `file_sha256` là cái NEO của luồng hai bước: bước ② gửi lại sha, lệch thì
    # 409. Không có nó thì người dùng xác nhận "xoá 3 dòng" và hệ ghi một file
    # xoá 300 dòng — DL_01 BR08 sinh ra để chặn đúng chuyện đó.
    op.execute(
        f"""
        CREATE TABLE tenant_data.import_jobs (
            id          bigserial PRIMARY KEY,
            tenant_id   {_TENANT_FK},
            entity      text NOT NULL
                        CONSTRAINT import_jobs_entity_check CHECK (entity IN ('project', 'unit')),
            mode        text NOT NULL
                        CONSTRAINT import_jobs_mode_check
                        CHECK (mode IN ('them_va_cap_nhat', 'thay_the_toan_bo')),
            state       text NOT NULL DEFAULT 'cho_xac_nhan'
                        CONSTRAINT import_jobs_state_check
                        CHECK (state IN ('cho_xac_nhan', 'da_ap_dung', 'da_huy')),
            s3_key      text NOT NULL CHECK (s3_key <> ''),
            file_sha256 text NOT NULL CHECK (length(file_sha256) = 64),
            report      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at  timestamptz NOT NULL DEFAULT now(),
            created_by  text REFERENCES control.users(id) ON DELETE SET NULL,
            expires_at  timestamptz NOT NULL,
            applied_at  timestamptz
        )
        """
    )
    op.execute(
        "CREATE INDEX import_jobs_tenant_moi_idx "
        "ON tenant_data.import_jobs (tenant_id, created_at DESC)"
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.import_jobs')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.import_jobs")
    for ten in ("project_documents", "project_progress", "project_highlights"):
        op.execute(f"DROP TABLE tenant_data.{ten}")
    op.execute(
        "ALTER TABLE control.field_policy_live "
        "DROP COLUMN required_for_agent, DROP COLUMN form_visible"
    )
    op.execute("DROP INDEX tenant_data.units_tenant_hot_idx")
    op.execute("ALTER TABLE tenant_data.units DROP CONSTRAINT units_gia_khong_am")
    op.execute(
        """
        ALTER TABLE tenant_data.units
            DROP COLUMN investor, DROP COLUMN zone, DROP COLUMN building,
            DROP COLUMN bathrooms, DROP COLUMN price_label, DROP COLUMN price_tttd_vnd,
            DROP COLUMN price_loan_vnd, DROP COLUMN loan_info, DROP COLUMN is_hot,
            DROP COLUMN hot_sort, DROP COLUMN delivery_standard, DROP COLUMN floor_min,
            DROP COLUMN floor_max, DROP COLUMN axis, DROP COLUMN front,
            DROP COLUMN check_time, DROP COLUMN description, DROP COLUMN is_active,
            DROP COLUMN sort_order, DROP COLUMN sale_email, DROP COLUMN lat, DROP COLUMN lng
        """
    )
    op.execute("DROP INDEX tenant_data.projects_tenant_agent_idx")
    op.execute("DROP INDEX tenant_data.projects_tenant_parent_idx")
    op.execute("ALTER TABLE tenant_data.projects DROP CONSTRAINT projects_parent_khong_tu_tro")
    op.execute(
        """
        ALTER TABLE tenant_data.projects
            DROP COLUMN parent_code, DROP COLUMN sort_order,
            DROP COLUMN is_featured, DROP COLUMN agent_enabled
        """
    )
```

- [ ] **Step 4: Chạy migration lên và xuống, rồi lên lại**

```bash
make dev
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: cả ba lệnh thoát mã 0. Bước `downgrade` là bắt buộc — một migration
không lùi được là một migration không thử lại được trên staging.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_schema.py -v`
Expected: PASS — 33 test

- [ ] **Step 6: Chạy cổng cách ly của M1, xác nhận không vỡ**

Run: `make test-isolation`
Expected: PASS. Cổng 6 quét `pg_class`/`pg_policies` cho **mọi** bảng
`tenant_data` — 4 bảng mới phải xanh ở đó, không chỉ ở test của M4a.

- [ ] **Step 7: Lint và commit**

```bash
uv run ruff check migrations/versions/0400_bds_full_fields.py tests/modules/realestate
uv run ruff format migrations/versions/0400_bds_full_fields.py tests/modules/realestate
git add migrations/versions/0400_bds_full_fields.py tests/modules/realestate/test_schema.py
git commit -m "feat(m4a): migration 0400 — 26 cột + 4 bảng con, ngoại lệ §4④ khai tường minh (T2)"
```

---

## Task 3: Migration `0401` — dựng lại view `agent_api`

**Files:**
- Create: `migrations/versions/0401_agent_api_bds.py`
- Test: `tests/modules/realestate/test_agent_doc_duoc.py`

**Interfaces:**
- Consumes: cột của Task 2 · `portal.pol(text, text)` · `portal.gated_extras(text, jsonb)` ·
  `portal.current_tenant()` từ M1
- Produces: `agent_api.projects` (17 cột) và `agent_api.units` (38 cột) — Task 11 seed
  `field_policy_live` phải khớp tên trường ở đây.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_agent_doc_duoc.py`:

```python
"""Cổng 2 và cổng 3 của spec §9 — đường đọc của agent.

Test này chạy bằng ROLE AGENT THẬT (`agent_<slug>`), không bằng `portal_api`.
Chạy bằng portal_api là test một đường mà agent không bao giờ đi: portal_api có
quyền trên `tenant_data`, agent thì zero — và chính chỗ chênh đó là cơ chế.
"""

import asyncpg
import pytest

from tests.conftest import dsn_as

pytestmark = pytest.mark.integration

MAT_KHAU_AGENT = "AgentM4aDev!1"


@pytest.fixture
async def hai_tenant_co_du_lieu(pool: asyncpg.Pool, api_dsn: str):
    """Hai workspace, mỗi bên một dự án và một căn. Cộng role agent cho bên A."""
    async with pool.acquire() as conn, conn.transaction():
        for t in ("m4a", "m4b"):
            await conn.execute("INSERT INTO control.tenants (id, name) VALUES ($1, $1)", t)
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", t)
            await conn.execute(
                """INSERT INTO tenant_data.projects (tenant_id, code, name, agent_enabled)
                   VALUES ($1, 'VOP2', 'Ocean Park 2', true)""",
                t,
            )
            await conn.execute(
                """INSERT INTO tenant_data.units
                       (tenant_id, code, project_code, price_vnd, commission, building, zone, floor)
                   VALUES ($1, 'NT2-1408', 'VOP2', 5620000000, 'HH 2%', 'S2.03', 'The Zurich', 14)""",
                t,
            )
        await conn.execute("SELECT control.create_agent_role('m4a', $1)", MAT_KHAU_AGENT)

    yield "m4a", "m4b"

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id IN ('m4a', 'm4b')")
    async with pool.acquire() as conn:
        await conn.execute("DROP ROLE IF EXISTS agent_m4a")


@pytest.fixture
async def conn_agent(hai_tenant_co_du_lieu, api_dsn: str):
    c = await asyncpg.connect(dsn_as(api_dsn, "agent_m4a", MAT_KHAU_AGENT))
    yield c
    await c.close()


async def test_agent_chi_thay_don_vi_cua_minh(conn_agent: asyncpg.Connection):
    """Cổng 1 — cách ly hàng. Hai tenant cùng mã căn `NT2-1408`."""
    rows = await conn_agent.fetch("SELECT code FROM agent_api.units")
    assert len(rows) == 1, "agent thấy căn của tenant khác"


async def test_cot_gated_null_khi_chua_bat_chinh_sach(conn_agent: asyncpg.Connection):
    """Cổng 2. `field_policy_live` rỗng ⇒ `pol()` trả false ⇒ NULL.

    Đây là fail-CLOSED: chưa khai chính sách thì không lộ, chứ không phải lộ
    rồi chờ ai đó nhớ ra phải khoá. BR09 gọi lộ hoa hồng là "sự cố thương mại
    thật".
    """
    assert await conn_agent.fetchval("SELECT commission FROM agent_api.units") is None


async def test_bat_chinh_sach_thi_hien(pool: asyncpg.Pool, conn_agent: asyncpg.Connection):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO control.field_policy_live
                   (tenant_id, entity, field, is_core, agent_readable)
               VALUES ('m4a', 'unit', 'commission', true, true)"""
        )
    assert await conn_agent.fetchval("SELECT commission FROM agent_api.units") == "HH 2%"


async def test_tat_du_an_thi_can_bien_mat(pool: asyncpg.Pool, conn_agent: asyncpg.Connection):
    """Cổng 3 — BR11. Đây là mệnh đề tenant THỨ HAI trong definer view, và là
    chỗ dễ quên nhất của cả M4a: thiếu nó thì không có lỗi nào, chỉ có dự án đã
    tắt vẫn được agent nhắc tới.
    """
    assert await conn_agent.fetchval("SELECT count(*) FROM agent_api.units") == 1

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', 'm4a', true)")
        await conn.execute(
            "UPDATE tenant_data.projects SET agent_enabled = false WHERE tenant_id='m4a'"
        )

    assert await conn_agent.fetchval("SELECT count(*) FROM agent_api.projects") == 0
    assert await conn_agent.fetchval("SELECT count(*) FROM agent_api.units") == 0, (
        "dự án đã tắt nhưng căn của nó vẫn lên view — thiếu mệnh đề EXISTS"
    )


async def test_is_active_false_thi_can_bien_mat(pool: asyncpg.Pool, conn_agent: asyncpg.Connection):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', 'm4a', true)")
        await conn.execute("UPDATE tenant_data.units SET is_active = false WHERE tenant_id='m4a'")
    assert await conn_agent.fetchval("SELECT count(*) FROM agent_api.units") == 0


async def test_agent_khong_cham_duoc_bang_goc(conn_agent: asyncpg.Connection):
    """Zero privilege trên `tenant_data` — "không vào được cửa" mạnh hơn "được
    vào nhưng bị lọc hàng". Xem 0005_agent_api.py, sửa lỗi C1."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn_agent.fetch("SELECT * FROM tenant_data.units")


@pytest.mark.parametrize("cot", ("zone", "building", "floor"))
async def test_ba_cot_gay_tranh_cai_van_len_view(conn_agent: asyncpg.Connection, cot: str):
    """0004 để `floor` ngoài view kèm ghi chú "M4 quyết định lại". M4a quyết
    định: lên view ở dạng ĐỌC ĐƯỢC, không lọc được. Cái sai âm thầm nằm ở LỌC
    (quyết định #17), không ở đọc — agent đọc "Toà S2.03" rồi nói lại là đúng.

    Điều kiện của quyết định này là BR03 (bỏ khoá rỗng) ở phía agent — xem
    spec §6.2 mục G-11.
    """
    assert await conn_agent.fetchval(f"SELECT {cot} FROM agent_api.units") is not None
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_agent_doc_duoc.py -v`
Expected: FAIL — `test_tat_du_an_thi_can_bien_mat` đỏ với `assert 1 == 0` (view cũ
chưa có mệnh đề `EXISTS`), và bốn test cột mới đỏ với `UndefinedColumnError`.

- [ ] **Step 3: Viết migration**

Tạo `migrations/versions/0401_agent_api_bds.py`:

```python
"""agent_api sau khi M4a đủ cột — cộng BR11

TÁCH KHỎI 0400 CÓ CHỦ Ý: 0400 thêm cột vào bảng của M1; file này dựng lại VIEW
của M1. Hai bề mặt khác nhau, hai cổng test khác nhau. Tách ra để revert được
riêng phần view khi nó sai mà không mất 26 cột.

HAI MỆNH ĐỀ TENANT TRONG MỘT VIEW — đọc kỹ chỗ này.
View ở `agent_api` là DEFINER (0005 sửa lỗi C1: security_invoker buộc phải GRANT
SELECT trên bảng gốc, mà có quyền đó là agent query thẳng bảng gốc và bỏ qua gate
cột). Definer nghĩa là RLS của owner KHÔNG áp, nên view phải TỰ lọc tenant trong
WHERE. Bản này lọc ở HAI chỗ:
    ① u.tenant_id = portal.current_tenant()          -- cách ly hàng
    ② p.tenant_id = portal.current_tenant() (EXISTS) -- BR11, dự án đã tắt
Thiếu ② thì không có lỗi nào — chỉ có dự án tenant đã tắt vẫn được agent nhắc
tới, và họ chỉ biết khi khách kể lại.

VÌ SAO KHÔNG DÙNG JOIN MÀ DÙNG EXISTS: join nhân hàng nếu có hai dự án trùng mã
(không xảy ra được vì UNIQUE(tenant_id, code), nhưng EXISTS thì đúng bất kể) và
nói rõ ý định "lọc", không phải "lấy thêm cột".

BA CỘT `zone`/`building`/`floor` LÊN VIEW, khác 0004: xem 0400 header. Đọc được,
KHÔNG lọc được. Điều kiện: BR03 ở phía agent (spec M4a §6.2 mục G-11).

`price_loan_vnd` LÊN VIEW dù DL_01 ghi nó "luôn rỗng trên nguồn hiện tại": nguồn
hiện tại là hệ cũ. Tenant của portal có ô để nhập. Rỗng thì BR03 bỏ khoá.

Revision ID: 0401_agent_api_bds
Revises: 0400_bds_full
"""

from alembic import op

revision = "0401_agent_api_bds"
down_revision = "0400_bds_full"
branch_labels = None
depends_on = None

_DU_AN_CON_BAT = """
    EXISTS (SELECT 1 FROM tenant_data.projects p
             WHERE p.tenant_id = portal.current_tenant()
               AND p.code = u.project_code
               AND p.agent_enabled)
"""


def upgrade() -> None:
    # DROP rồi CREATE, không CREATE OR REPLACE: OR REPLACE của Postgres từ chối
    # đổi kiểu hoặc thứ tự cột đang có, và bản này thêm cột vào giữa. Lỗi của nó
    # ("cannot change name of view column") đọc như lỗi cú pháp chứ không như
    # "hãy drop trước".
    op.execute("DROP VIEW agent_api.units")
    op.execute("DROP VIEW agent_api.projects")

    op.execute(
        """
        CREATE VIEW agent_api.projects AS
        SELECT p.code, p.name, p.slug, p.type, p.region, p.location, p.investor,
               p.parent_code, p.status, p.is_hot, p.is_featured, p.sort_hot,
               p.overview, p.lat, p.lng,
               portal.gated_extras('project', p.extras) AS extras,
               p.updated_at
          FROM tenant_data.projects p
         WHERE p.tenant_id = portal.current_tenant()
           AND p.agent_enabled
        """
    )

    op.execute(
        f"""
        CREATE VIEW agent_api.units AS
        SELECT u.code, u.project_code, u.unit_type, u.status, u.direction,
               u.zone, u.building, u.floor, u.floor_min, u.floor_max,
               u.bedrooms, u.bathrooms, u.investor,
               u.price_vnd, u.price_tts_vnd, u.price_tttd_vnd, u.price_loan_vnd,
               u.price_label, u.loan_info,
               u.area_m2, u.area_build_m2,
               u.fund_type, u.is_hot, u.csbh_brief, u.gift, u.legal,
               u.delivery_standard, u.axis, u.front, u.description,
               u.lat, u.lng, u.check_time,
               CASE WHEN portal.pol('unit', 'commission')   THEN u.commission   END AS commission,
               CASE WHEN portal.pol('unit', 'bank_support') THEN u.bank_support END AS bank_support,
               CASE WHEN portal.pol('unit', 'csbh_full')    THEN u.csbh_full    END AS csbh_full,
               portal.gated_extras('unit', u.extras) AS extras,
               u.updated_at
          FROM tenant_data.units u
         WHERE u.tenant_id = portal.current_tenant()
           AND u.is_active
           AND {_DU_AN_CON_BAT}
        """
    )

    # 0005 đã đặt ALTER DEFAULT PRIVILEGES cho schema agent_api, nên view mới tự
    # được cấp SELECT cho `agent_all`. Grant lại tường minh phòng trường hợp
    # default privileges bị gỡ trong một đợt hardening — rẻ, và thiếu nó thì mọi
    # pod agent nhận permission denied ngay lần bootstrap sau.
    op.execute("GRANT SELECT ON agent_api.projects, agent_api.units TO agent_all")
    op.execute("GRANT SELECT ON agent_api.projects, agent_api.units TO portal_api")


def downgrade() -> None:
    op.execute("DROP VIEW agent_api.units")
    op.execute("DROP VIEW agent_api.projects")
    op.execute(
        """
        CREATE VIEW agent_api.units AS
        SELECT u.code, u.project_code, u.unit_type, u.status, u.direction,
               u.price_vnd, u.price_tts_vnd, u.area_m2, u.area_build_m2,
               u.bedrooms, u.fund_type, u.csbh_brief, u.gift, u.legal,
               CASE WHEN portal.pol('unit', 'commission')   THEN u.commission   END AS commission,
               CASE WHEN portal.pol('unit', 'bank_support') THEN u.bank_support END AS bank_support,
               CASE WHEN portal.pol('unit', 'csbh_full')    THEN u.csbh_full    END AS csbh_full,
               portal.gated_extras('unit', u.extras) AS extras,
               u.updated_at
          FROM tenant_data.units u
         WHERE u.tenant_id = portal.current_tenant()
        """
    )
    op.execute(
        """
        CREATE VIEW agent_api.projects AS
        SELECT p.code, p.name, p.slug, p.type, p.region, p.location, p.investor,
               p.status, p.is_hot, p.sort_hot, p.overview, p.lat, p.lng,
               portal.gated_extras('project', p.extras) AS extras,
               p.updated_at
          FROM tenant_data.projects p
         WHERE p.tenant_id = portal.current_tenant()
        """
    )
    op.execute("GRANT SELECT ON agent_api.projects, agent_api.units TO agent_all")
    op.execute("GRANT SELECT ON agent_api.projects, agent_api.units TO portal_api")
```

- [ ] **Step 4: Chạy migration lên/xuống/lên**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: cả ba thoát mã 0.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_agent_doc_duoc.py -v`
Expected: PASS — 9 test

- [ ] **Step 6: Chạy lại cổng cách ly M1**

Run: `make test-isolation`
Expected: PASS. Cổng 3 và 4 của M1 kiểm view definer và `session_user` — dựng
lại view mà làm hỏng chúng thì đỏ ở đây, không ở M4a.

- [ ] **Step 7: Lint và commit**

```bash
uv run ruff check migrations/versions/0401_agent_api_bds.py tests/modules/realestate
uv run ruff format migrations/versions/0401_agent_api_bds.py tests/modules/realestate
git add migrations/versions/0401_agent_api_bds.py tests/modules/realestate/test_agent_doc_duoc.py
git commit -m "feat(m4a): agent_api đủ cột + BR11 — hai mệnh đề tenant trong definer view (T3)"
```

---

## Task 4: `nhap_lieu.py` — đọc file và chạy thử

**Files:**
- Create: `src/portal/modules/realestate/nhap_lieu.py`
- Create: `tests/modules/realestate/test_nhap_lieu.py`
- Create: `tests/fixtures/import/units_ok.csv`, `units_trung_ma.csv`, `units_thieu_cot.csv`,
  `units_ok.xlsx`

**Interfaces:**
- Consumes: `gia.doi_don_vi_gia` · `gia.LoiGiaKhongHopLe` (Task 1)
- Produces:
  - `doc_bang(noi_dung: bytes, ten_file: str) -> list[dict[str, str]]`
  - `DongLoi(dong: int, ma: str, ly_do: str)` — dataclass frozen
  - `BaoCaoChayThu(them: list[dict], sua: list[dict], xoa: list[str], loi: list[DongLoi])`
    với property `so_dong_se_xoa: int`
  - `chay_thu(hang, *, cot_bat_buoc, cot_hop_le, cot_gia, ma_dang_co, mode) -> BaoCaoChayThu`
  - `LoiFile(ValueError)` — raise khi định dạng sai hoặc thiếu cột

  Task 10 gọi cả bốn.

- [ ] **Step 1: Tạo fixture file thật**

```bash
mkdir -p tests/fixtures/import
cat > tests/fixtures/import/units_ok.csv <<'CSV'
code,project_code,unit_type,status,direction,price_ty,area_m2,bedrooms
NT2-1408,VOP2,Sky Villa 4PN,available,Đông Nam,5.62,78.4,4
NT2-0812,VOP2,Liền kề,booked,Tây Bắc,7,96.0,3
CSV
cat > tests/fixtures/import/units_trung_ma.csv <<'CSV'
code,project_code,unit_type,status,direction,price_ty,area_m2,bedrooms
NT2-1408,VOP2,Sky Villa 4PN,available,Đông Nam,5.62,78.4,4
NT2-1408,VOP2,Liền kề,booked,Tây Bắc,7,96.0,3
CSV
cat > tests/fixtures/import/units_thieu_cot.csv <<'CSV'
project_code,unit_type,price_ty
VOP2,Sky Villa 4PN,5.62
CSV
uv run python - <<'PY'
from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(["code", "project_code", "unit_type", "status", "direction", "price_ty", "area_m2", "bedrooms"])
ws.append(["NT2-1408", "VOP2", "Sky Villa 4PN", "available", "Đông Nam", 5.62, 78.4, 4])
wb.save("tests/fixtures/import/units_ok.xlsx")
PY
```

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/modules/realestate/test_nhap_lieu.py`:

```python
"""Chạy thử import — HÀM THUẦN, không cần Postgres.

Đây là phần nhiều biến thể nhất của M4a, nên nó không được chạm DB: một file
fixture vài dòng phải test được 20 biến thể hỏng trong vài trăm mili-giây. Việc
so với dữ liệu đang có do `service.py` làm (nó truyền `ma_dang_co` vào).
"""

from pathlib import Path

import pytest

from portal.modules.realestate.nhap_lieu import LoiFile, chay_thu, doc_bang

FIX = Path(__file__).parents[2] / "fixtures" / "import"

COT_BAT_BUOC = ("code", "project_code")
COT_HOP_LE = (
    "code", "project_code", "unit_type", "status", "direction",
    "price_ty", "area_m2", "bedrooms",
)
COT_GIA = {"price_ty": "price_vnd"}


def _doc(ten: str):
    return doc_bang((FIX / ten).read_bytes(), ten)


def test_doc_csv_ra_dict_theo_header():
    hang = _doc("units_ok.csv")
    assert len(hang) == 2
    assert hang[0]["code"] == "NT2-1408"
    assert hang[0]["price_ty"] == "5.62"


def test_doc_xlsx_ra_cung_hinh_dang_voi_csv():
    """Hai định dạng phải cho cùng một `list[dict[str, str]]`. Khác nhau ở đây
    nghĩa là `chay_thu` phải biết nó đang đọc file gì — và nó thì không nên."""
    assert _doc("units_ok.xlsx")[0]["code"] == "NT2-1408"


def test_dinh_dang_khong_ho_tro_thi_no():
    with pytest.raises(LoiFile):
        doc_bang(b"noi dung", "danh_sach.pdf")


def test_thieu_cot_bat_buoc_thi_no_va_noi_thieu_cot_nao():
    """ER_03 — không ghi gì, và phải liệt kê cột còn thiếu để người dùng đối
    chiếu file mẫu. Báo "file sai" mà không nói sai chỗ nào là bắt họ đoán."""
    with pytest.raises(LoiFile, match="code"):
        chay_thu(
            _doc("units_thieu_cot.csv"),
            cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
            cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
        )


def test_them_moi_khi_ma_chua_ton_tai():
    bc = chay_thu(
        _doc("units_ok.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
        cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
    )
    assert len(bc.them) == 2 and not bc.sua and not bc.loi
    assert bc.so_dong_se_xoa == 0


def test_gia_doi_sang_vnd_ngay_trong_chay_thu():
    """BR05 — đổi TẠI BIÊN NHẬP. Nếu để `service.py` đổi thì báo cáo chạy thử
    hiện một con số và DB nhận một con số khác."""
    bc = chay_thu(
        _doc("units_ok.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
        cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
    )
    assert bc.them[0]["price_vnd"] == 5_620_000_000
    assert "price_ty" not in bc.them[0], "cột đơn vị tỷ không được lọt vào payload ghi DB"


def test_ma_da_co_thi_la_sua_khong_phai_them():
    bc = chay_thu(
        _doc("units_ok.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE, cot_gia=COT_GIA,
        ma_dang_co=frozenset({"NT2-1408"}), mode="them_va_cap_nhat",
    )
    assert len(bc.them) == 1 and len(bc.sua) == 1


def test_trung_ma_trong_cung_file_thi_bao_loi_khong_tu_chon():
    """BR10 — "không tự chọn dòng nào thắng". Chọn hộ là ghi một giá mà người
    dùng không biết mình đã chọn."""
    bc = chay_thu(
        _doc("units_trung_ma.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
        cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
    )
    assert [d.ma for d in bc.loi] == ["ER_06"]
    assert bc.loi[0].dong == 3, "số dòng phải tính theo FILE (có header), không theo mảng"


def test_gia_sai_dinh_dang_thi_la_dong_loi_khong_phai_no():
    """Một dòng hỏng không được làm hỏng cả báo cáo — người dùng cần thấy TẤT CẢ
    dòng lỗi trong một lượt, không phải sửa một dòng rồi upload lại để lộ dòng
    tiếp theo."""
    hang = [{"code": "A", "project_code": "P", "price_ty": "abc"}]
    bc = chay_thu(
        hang, cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
        cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
    )
    assert bc.loi[0].ma == "ER_02" and not bc.them


def test_thay_the_toan_bo_liet_ke_ma_se_bi_xoa():
    """BR08 — số dòng sẽ XOÁ phải tính được TRƯỚC khi ghi. Đây là con số duy
    nhất trên màn import mà nếu sai thì tenant mất dữ liệu."""
    bc = chay_thu(
        _doc("units_ok.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE, cot_gia=COT_GIA,
        ma_dang_co=frozenset({"NT2-1408", "CU-01", "CU-02"}), mode="thay_the_toan_bo",
    )
    assert sorted(bc.xoa) == ["CU-01", "CU-02"]
    assert bc.so_dong_se_xoa == 2


def test_che_do_them_va_cap_nhat_khong_bao_gio_xoa():
    bc = chay_thu(
        _doc("units_ok.csv"),
        cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE, cot_gia=COT_GIA,
        ma_dang_co=frozenset({"CU-01"}), mode="them_va_cap_nhat",
    )
    assert bc.xoa == [] and bc.so_dong_se_xoa == 0


def test_cot_la_bo_qua_khong_phai_loi():
    """File của tenant thường có cột thừa (ghi chú của sales). Từ chối cả file
    vì một cột thừa là bắt họ dọn file trước khi dùng được sản phẩm."""
    hang = [{"code": "A", "project_code": "P", "ghi_chu_cua_sales": "x"}]
    bc = chay_thu(
        hang, cot_bat_buoc=COT_BAT_BUOC, cot_hop_le=COT_HOP_LE,
        cot_gia=COT_GIA, ma_dang_co=frozenset(), mode="them_va_cap_nhat",
    )
    assert not bc.loi and "ghi_chu_cua_sales" not in bc.them[0]
```

- [ ] **Step 3: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_nhap_lieu.py -v`
Expected: FAIL — `ModuleNotFoundError: ... realestate.nhap_lieu`

- [ ] **Step 4: Viết `nhap_lieu.py`**

```python
"""Đọc file import và chạy thử — HÀM THUẦN, KHÔNG chạm DB.

RANH GIỚI: file này nhận `bytes` và một tập mã ĐANG CÓ (`ma_dang_co`), trả về
báo cáo. Nó không biết Postgres tồn tại. `service.py` là chỗ đọc mã đang có và
là chỗ ghi.

Ranh giới đó là lý do test được 20 biến thể file hỏng trong vài trăm mili-giây,
và là cùng nếp với `bundle.render()` của M3 và `parse.py`/`chunk.py` của M6.

MỘT DÒNG HỎNG KHÔNG LÀM HỎNG CẢ BÁO CÁO. Người dùng cần thấy TẤT CẢ dòng lỗi
trong một lượt — sửa một dòng rồi upload lại để lộ dòng tiếp theo là cách chắc
chắn để họ bỏ cuộc ở lần thứ ba. Ngoại lệ duy nhất là thiếu cột bắt buộc: lúc đó
mọi dòng đều hỏng theo cùng một lý do, nên báo một lần (ER_03).
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Literal

from portal.modules.realestate.gia import LoiGiaKhongHopLe, doi_don_vi_gia

Mode = Literal["them_va_cap_nhat", "thay_the_toan_bo"]

DUOI_HO_TRO = ("csv", "xlsx")


class LoiFile(ValueError):
    """Hỏng ở mức FILE, không ở mức dòng: sai định dạng, hoặc thiếu cột bắt buộc.

    Người gọi dịch sang ER_03. Khác `DongLoi` ở chỗ file không đọc tiếp được —
    báo cáo chạy thử không tồn tại, chứ không phải tồn tại và có lỗi.
    """


@dataclass(frozen=True)
class DongLoi:
    dong: int
    """Số dòng TRONG FILE, tính cả header. Người dùng mở Excel và nhảy tới đúng
    dòng đó — trả chỉ số mảng là bắt họ tự cộng một."""
    ma: str
    ly_do: str


@dataclass(frozen=True)
class BaoCaoChayThu:
    them: list[dict] = field(default_factory=list)
    sua: list[dict] = field(default_factory=list)
    xoa: list[str] = field(default_factory=list)
    loi: list[DongLoi] = field(default_factory=list)

    @property
    def so_dong_se_xoa(self) -> int:
        """Con số duy nhất trên màn import mà sai thì tenant mất dữ liệu.
        Có property riêng để bước ② đối chiếu được — xem router `/apply`."""
        return len(self.xoa)

    def to_json(self) -> dict:
        return {
            "them": len(self.them),
            "sua": len(self.sua),
            "xoa": self.so_dong_se_xoa,
            "maSeXoa": self.xoa,
            "loi": [{"dong": d.dong, "ma": d.ma, "lyDo": d.ly_do} for d in self.loi],
        }


def doc_bang(noi_dung: bytes, ten_file: str) -> list[dict[str, str]]:
    """CSV hoặc XLSX → `list[dict]` khoá theo header. Giá trị luôn là `str`.

    Ép về `str` để hai định dạng cho ra cùng một hình dạng: openpyxl trả `float`
    cho ô số, csv trả `str`. Nếu không ép thì `chay_thu` phải biết nó đang đọc
    file gì — và nó thì không nên biết.
    """
    duoi = ten_file.rsplit(".", 1)[-1].lower()
    if duoi not in DUOI_HO_TRO:
        raise LoiFile("Chỉ nhận file CSV hoặc XLSX")

    if duoi == "csv":
        # utf-8-sig: Excel bản Windows ghi BOM ở đầu file, và không bỏ nó thì
        # cột đầu tiên có tên "﻿code" — file trông đúng mà báo thiếu cột.
        try:
            van_ban = noi_dung.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise LoiFile("File không phải UTF-8. Lưu lại bằng 'CSV UTF-8' trong Excel") from e
        doc_gia = csv.DictReader(io.StringIO(van_ban))
        return [{k: (v or "").strip() for k, v in h.items() if k} for h in doc_gia]

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(noi_dung), read_only=True, data_only=True)
    except Exception as e:
        raise LoiFile("Không đọc được file XLSX") from e

    ws = wb.active
    hang_lap = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(hang_lap, ())]
    ket_qua: list[dict[str, str]] = []
    for o in hang_lap:
        if all(c is None or str(c).strip() == "" for c in o):
            continue  # dòng trống giữa file — Excel sinh ra rất nhiều
        ket_qua.append(
            {h: _o_thanh_chuoi(v) for h, v in zip(header, o, strict=False) if h}
        )
    wb.close()
    return ket_qua


def _o_thanh_chuoi(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        # openpyxl trả 4.0 cho ô ghi 4. "4.0" vào cột bedrooms là một smallint
        # không parse được — và lỗi đó trông như dữ liệu bẩn chứ không như lỗi
        # thư viện.
        return str(int(v))
    return str(v).strip()


def chay_thu(
    hang: list[dict[str, str]],
    *,
    cot_bat_buoc: tuple[str, ...],
    cot_hop_le: tuple[str, ...],
    cot_gia: dict[str, str],
    ma_dang_co: frozenset[str],
    mode: Mode,
) -> BaoCaoChayThu:
    """Dựng báo cáo. `cot_gia` ánh xạ cột-nhập-bằng-tỷ → cột-lưu-VND.

    `ma_dang_co` là tập `code` đang có trong DB của tenant, do `service.py` đọc.
    Truyền vào thay vì tự đọc là điều làm hàm này thuần.
    """
    if not hang:
        raise LoiFile("File không có dòng dữ liệu nào")

    co_san = set(hang[0].keys())
    thieu = [c for c in cot_bat_buoc if c not in co_san]
    if thieu:
        raise LoiFile(f"File thiếu cột bắt buộc: {', '.join(thieu)}. Tải file mẫu để đối chiếu")

    bc_them: list[dict] = []
    bc_sua: list[dict] = []
    bc_loi: list[DongLoi] = []
    ma_trong_file: set[str] = set()

    for i, h in enumerate(hang):
        so_dong = i + 2  # +1 vì 0-based, +1 vì header
        ma = (h.get("code") or "").strip()

        if not ma:
            bc_loi.append(DongLoi(so_dong, "ER_01", "Thiếu mã (cột code)"))
            continue
        if ma in ma_trong_file:
            bc_loi.append(DongLoi(so_dong, "ER_06", f"Mã {ma} bị trùng trong cùng file"))
            continue

        try:
            payload = _dung_payload(h, cot_hop_le, cot_gia)
        except LoiGiaKhongHopLe as e:
            bc_loi.append(DongLoi(so_dong, "ER_02", str(e)))
            continue

        ma_trong_file.add(ma)
        (bc_sua if ma in ma_dang_co else bc_them).append(payload)

    # Chỉ tính XOÁ ở chế độ thay thế. Ở chế độ thêm-và-cập-nhật thì mã không có
    # trong file là mã người dùng không đụng tới, không phải mã họ muốn xoá.
    bc_xoa = sorted(ma_dang_co - ma_trong_file) if mode == "thay_the_toan_bo" else []

    return BaoCaoChayThu(them=bc_them, sua=bc_sua, xoa=bc_xoa, loi=bc_loi)


def _dung_payload(h: dict[str, str], cot_hop_le: tuple[str, ...], cot_gia: dict[str, str]) -> dict:
    """Giữ cột hợp lệ, bỏ cột thừa, đổi đơn vị giá.

    Bỏ cột thừa chứ không báo lỗi: file của tenant thường mang thêm cột ghi chú
    của sales. Từ chối cả file vì một cột thừa là bắt họ dọn file trước khi dùng
    được sản phẩm.
    """
    payload: dict = {}
    for cot in cot_hop_le:
        if cot in cot_gia:
            continue  # xử lý riêng bên dưới
        if cot in h and h[cot] != "":
            payload[cot] = h[cot]
    for cot_ty, cot_vnd in cot_gia.items():
        gia = doi_don_vi_gia(h.get(cot_ty))
        if gia is not None:
            payload[cot_vnd] = gia
    return payload
```

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_nhap_lieu.py -v`
Expected: PASS — 12 test

- [ ] **Step 6: Lint và commit**

```bash
uv run ruff check src/portal/modules/realestate tests/modules/realestate
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/nhap_lieu.py tests/modules/realestate/test_nhap_lieu.py tests/fixtures/import
git commit -m "feat(m4a): đọc CSV/XLSX + chạy thử — hàm thuần, một dòng hỏng không hỏng cả báo cáo (T4)"
```

---

## Task 5: `chinh_sach.py` — ba cờ và trường thiếu

**Files:**
- Create: `src/portal/modules/realestate/chinh_sach.py`
- Create: `tests/modules/realestate/test_chinh_sach.py`

**Interfaces:**
- Consumes: không gì (hàm thuần)
- Produces:
  - `COT_PROJECT: frozenset[str]` · `COT_UNIT: frozenset[str]` — cột thật, dùng làm danh sách trắng
  - `loc_ten_cot(ten: Iterable[str], cho_phep: frozenset[str]) -> list[str]`
  - `menh_de_thieu(truong: list[str]) -> str` — trả `""` khi rỗng
  - `LoiTruongLa(ValueError)`

  Task 6 (`contracts.py` re-export), Task 9 (`/data-gaps`), Task 10 (`cot_hop_le`) đều dùng.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_chinh_sach.py`:

```python
"""Chính sách trường — HÀM THUẦN.

Hàm quan trọng nhất ở đây là `menh_de_thieu()`: nó ghép SQL từ tên trường lấy
trong `control.field_policy_live`. Dữ liệu trong bảng đó là ĐẦU VÀO KHÔNG TIN
ĐƯỢC — admin workspace ghi được vào nó qua PATCH /field-policy. Ghép thẳng vào
SQL là một lỗ injection đi qua đường cấu hình.
"""

import pytest

from portal.modules.realestate.chinh_sach import (
    COT_PROJECT,
    COT_UNIT,
    LoiTruongLa,
    loc_ten_cot,
    menh_de_thieu,
)


def test_cot_that_gom_ca_cot_cu_lan_cot_moi():
    for c in ("code", "price_vnd", "commission", "zone", "building", "check_time"):
        assert c in COT_UNIT
    for c in ("code", "name", "agent_enabled", "parent_code"):
        assert c in COT_PROJECT


def test_extras_va_tenant_id_khong_nam_trong_danh_sach_trang():
    """`extras` là jsonb (gate bằng `gated_extras`, không bằng cột) và
    `tenant_id` là khoá cách ly — cả hai không phải trường nghiệp vụ, và cho
    chúng vào danh sách trắng là mở đường ghép chúng vào WHERE."""
    for c in ("extras", "tenant_id", "id"):
        assert c not in COT_UNIT and c not in COT_PROJECT


def test_loc_bo_ten_khong_thuoc_danh_sach_trang():
    assert loc_ten_cot(["price_vnd", "khong_ton_tai"], COT_UNIT) == ["price_vnd"]


@pytest.mark.parametrize(
    "doc_hai",
    ["price_vnd; DROP TABLE tenant_data.units", "1=1 OR code IS NOT NULL", "code--"],
)
def test_ten_doc_hai_bi_loai_im_lang(doc_hai: str):
    assert loc_ten_cot([doc_hai], COT_UNIT) == []


def test_menh_de_thieu_ghep_dung():
    assert menh_de_thieu(["price_vnd", "area_m2"]) == (
        "(price_vnd IS NULL OR area_m2 IS NULL)"
    )


def test_menh_de_thieu_rong_tra_chuoi_rong():
    """Chưa BA nào chốt N2 thì không trường nào `required_for_agent` — lúc đó
    `/data-gaps` phải trả 0, KHÔNG phải trả toàn bộ số căn. `WHERE ()` là lỗi
    cú pháp, còn `WHERE true` là đếm tất."""
    assert menh_de_thieu([]) == ""


def test_menh_de_thieu_tu_choi_ten_chua_qua_loc():
    """Hàng rào thứ hai. `loc_ten_cot` đã lọc, nhưng người gọi có thể quên —
    và một `assert` ở đây rẻ hơn một lỗ injection."""
    with pytest.raises(LoiTruongLa):
        menh_de_thieu(["price_vnd; DROP TABLE tenant_data.units"])


def test_cot_text_dung_chuoi_rong_chu_khong_phai_null():
    """`0400` khai phần lớn cột text là NOT NULL DEFAULT '' — với chúng thì
    "chưa điền" là chuỗi rỗng, không phải NULL. Kiểm sai kiểu là cảnh báo BR07
    luôn trả 0 và không ai biết vì sao."""
    assert menh_de_thieu(["direction"]) == "(direction = '')"
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_chinh_sach.py -v`
Expected: FAIL — `ModuleNotFoundError: ... realestate.chinh_sach`

- [ ] **Step 3: Viết `chinh_sach.py`**

```python
"""Chính sách trường — HÀM THUẦN, và là hàng rào chống SQL injection của M4a.

BỐN CỜ (DL_01 BR01 + BR07), lưu ở `control.field_policy_live`:
    form_visible        hiện trên form nhập liệu
    agent_readable      agent đọc được   ← Postgres cưỡng chế qua portal.pol()
    filterable          agent lọc được   ← chỉ bật khi dữ liệu thật có (BR04)
    required_for_agent  tính vào "đủ dữ liệu cho agent" (BR07)

VÌ SAO DANH SÁCH TRẮNG CỘT LÀ HẰNG SỐ Ở ĐÂY, KHÔNG ĐỌC TỪ information_schema:
đọc từ DB thì bảng nào có cột `password_hash` cũng lọt vào danh sách hợp lệ ngay
khi ai đó thêm nó. Hằng số buộc người thêm cột phải sửa hai chỗ — và chỗ thứ hai
là chỗ họ đọc được lý do.
"""

from collections.abc import Iterable

COT_PROJECT: frozenset[str] = frozenset(
    {
        # 0004
        "code", "name", "slug", "type", "region", "location", "investor",
        "status", "is_hot", "sort_hot", "lat", "lng",
        # 0400
        "parent_code", "sort_order", "is_featured", "agent_enabled",
    }
)
"""16 cột nghiệp vụ. KHÔNG gồm `id` · `tenant_id` · `extras` · `overview` ·
`updated_at` — bốn thứ đầu không phải trường người dùng, `updated_at` hệ tự đóng."""

COT_UNIT: frozenset[str] = frozenset(
    {
        # 0004
        "code", "project_code", "unit_type", "status", "direction",
        "price_vnd", "price_tts_vnd", "area_m2", "area_build_m2",
        "bedrooms", "floor", "fund_type",
        "commission", "bank_support", "csbh_full", "csbh_brief", "gift", "legal",
        # 0400
        "investor", "zone", "building", "bathrooms", "price_label",
        "price_tttd_vnd", "price_loan_vnd", "loan_info", "is_hot", "hot_sort",
        "delivery_standard", "floor_min", "floor_max", "axis", "front",
        "check_time", "description", "is_active", "sort_order", "sale_email",
        "lat", "lng",
    }
)

COT_TEXT_KHONG_NULL: frozenset[str] = frozenset(
    {
        "direction", "fund_type", "commission", "bank_support", "csbh_full",
        "csbh_brief", "gift", "legal", "investor", "zone", "building",
        "price_label", "loan_info", "delivery_standard", "axis", "front",
        "description", "sale_email", "unit_type", "project_code",
        "name", "slug", "type", "region", "location", "parent_code",
    }
)
"""`0400`/`0004` khai chúng NOT NULL DEFAULT ''. "Chưa điền" của nhóm này là
CHUỖI RỖNG, không phải NULL. Kiểm nhầm kiểu là BR07 luôn trả 0 và không ai biết
vì sao cảnh báo không bao giờ hiện."""

GATED: tuple[str, ...] = ("commission", "bank_support", "csbh_full")
"""Ba trường nhạy cảm thương mại (DL_01 BR09). Seed `agent_readable = false`.
`0005_agent_api.py` gate chúng bằng `CASE WHEN portal.pol(...)` — danh sách ở
đây phải khớp với danh sách trong view đó."""

KHONG_LOC_DUOC: tuple[str, ...] = ("floor", "building", "zone", "floor_min", "floor_max")
"""BR04 + quyết định #17. Có cột để tenant NHẬP, `filterable = false` cho tới khi
dữ liệu thật có. Đổi cờ đó là quyết định về DỮ LIỆU, không về schema.
`test_bo_loc_co_du_lieu.py` canh."""


class LoiTruongLa(ValueError):
    """Tên trường không thuộc danh sách trắng lọt tới chỗ ghép SQL."""


def loc_ten_cot(ten: Iterable[str], cho_phep: frozenset[str]) -> list[str]:
    """Giữ đúng những tên có trong danh sách trắng, giữ nguyên thứ tự, bỏ trùng.

    Bỏ IM LẶNG chứ không raise: nguồn của `ten` là `field_policy_live`, và một
    hàng rác trong bảng cấu hình không nên làm hỏng cả màn hình. Hàng rào raise
    nằm ở `menh_de_thieu()`.
    """
    thay: list[str] = []
    for t in ten:
        if t in cho_phep and t not in thay:
            thay.append(t)
    return thay


def menh_de_thieu(truong: list[str]) -> str:
    """Ghép mệnh đề `WHERE` đếm bản ghi thiếu ít nhất một trường bắt buộc (BR07).

    Rỗng trả `""` — người gọi phải hiểu đó là "không có tiêu chí", tức đếm 0.
    Trả `"true"` sẽ đếm TẤT CẢ, và cảnh báo "681 căn chưa đủ dữ liệu" ở một
    workspace chưa chốt N2 là một cảnh báo sai làm người dùng mất tin.
    """
    if not truong:
        return ""

    hop_le = COT_PROJECT | COT_UNIT
    la = [t for t in truong if t not in hop_le]
    if la:
        raise LoiTruongLa(f"tên trường không thuộc danh sách trắng: {la}")

    dieu_kien = [
        f"{t} = ''" if t in COT_TEXT_KHONG_NULL else f"{t} IS NULL" for t in truong
    ]
    return "(" + " OR ".join(dieu_kien) + ")"
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_chinh_sach.py -v`
Expected: PASS — 12 test

- [ ] **Step 5: Kiểm tréo danh sách trắng với schema thật**

Thêm vào cuối `tests/modules/realestate/test_schema.py`:

```python
async def test_danh_sach_trang_khop_schema_that(pool: asyncpg.Pool):
    """QUÉT ĐỘNG. `chinh_sach.COT_UNIT` là hằng số chép tay — nó sẽ lệch schema
    vào ngày ai đó thêm cột mà quên. Lệch theo hướng "hằng số có, schema không"
    là một mệnh đề WHERE nổ lúc chạy; theo hướng ngược lại là một trường không
    bao giờ khai được chính sách. Cả hai đều im lặng cho tới khi có người dùng.
    """
    from portal.modules.realestate.chinh_sach import COT_PROJECT, COT_UNIT

    BO_QUA = {"id", "tenant_id", "extras", "overview", "updated_at"}
    for bang, hang_so in (("projects", COT_PROJECT), ("units", COT_UNIT)):
        that = {
            r["column_name"]
            for r in await pool.fetch(
                """SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'tenant_data' AND table_name = $1""",
                bang,
            )
        } - BO_QUA
        assert hang_so == that, (
            f"{bang}: hằng số thừa {sorted(hang_so - that)}, thiếu {sorted(that - hang_so)}"
        )
```

Run: `uv run pytest tests/modules/realestate/test_schema.py -v`
Expected: PASS — 34 test

- [ ] **Step 6: Lint và commit**

```bash
uv run ruff check src/portal/modules/realestate tests/modules/realestate
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/chinh_sach.py tests/modules/realestate/test_chinh_sach.py tests/modules/realestate/test_schema.py
git commit -m "feat(m4a): chính sách trường + danh sách trắng cột — hàng rào injection qua cấu hình (T5)"
```

---

## Task 6: `contracts.py` và `repo.py`

**Files:**
- Create: `src/portal/modules/realestate/contracts.py`
- Create: `src/portal/modules/realestate/repo.py`
- Create: `tests/modules/realestate/conftest.py`
- Create: `tests/modules/realestate/test_repo.py`

**Interfaces:**
- Consumes: `chinh_sach.COT_PROJECT` · `COT_UNIT` (Task 5); bảng của Task 2
- Produces:
  - `contracts.DuAnOut` · `CanOut` · `ChinhSachTruongOut` · `BaoCaoImportOut` (pydantic, camelCase)
  - `contracts.COT_PROJECT` · `COT_UNIT` · `COT_GIA_UNIT` (re-export cho module khác)
  - `repo.liet_ke_du_an(conn, *, tim, region, type_, status) -> list[Record]`
  - `repo.doc_du_an(conn, code) -> Record | None`
  - `repo.ghi_du_an(conn, tenant_id, code, payload) -> Record` (UPSERT)
  - `repo.xoa_du_an(conn, code) -> bool`
  - `repo.liet_ke_can(conn, *, tim, project_code, fund_type, direction, status) -> list[Record]`
  - `repo.doc_can(conn, code)` · `repo.ghi_can(conn, tenant_id, code, payload)` · `repo.xoa_can(conn, code)`
  - `repo.ma_dang_co(conn, entity) -> frozenset[str]`
  - `repo.xoa_theo_ma(conn, entity, ma: list[str]) -> int`
  - `repo.dem_thieu(conn, entity, menh_de: str) -> int`
  - `repo.doc_chinh_sach(conn, entity) -> list[Record]` · `repo.ghi_chinh_sach(conn, tenant_id, entity, field, **co)`

  Task 7–11 dùng.

- [ ] **Step 1: Viết conftest cho module**

Tạo `tests/modules/realestate/conftest.py`:

```python
"""Fixture dùng chung cho test của M4a.

Cùng nếp `tests/modules/kb/conftest.py`: một workspace thật, một user thật, và
client đã đăng nhập. Không mock — `tenant_conn()` là seam của cách ly, và mock
nó thì test xanh cho cả một RLS đã tắt.
"""

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"
TENANT = "rew"


@pytest.fixture
async def workspace_re(pool: asyncpg.Pool):
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ($1, 'RE Workspace')", TENANT)
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            "u_re", "Đăng", "dang@re.vn", bam(MAT_KHAU),
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role) VALUES ('u_re', $1, 'admin')",
            TENANT,
        )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT)
        await conn.execute("DELETE FROM control.users WHERE id = 'u_re'")


@pytest.fixture
async def conn_re(pool: asyncpg.Pool, workspace_re: str):
    """Kết nối đã đặt `app.tenant_id` — RLS có hiệu lực, đúng như production.

    Dùng `tenant_conn` thật chứ không tự `set_config`: nếu `tenant_conn` đổi
    cách đặt biến thì test phải đỏ, không phải im lặng chạy đường cũ.
    """
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, workspace_re) as conn:
        yield conn


@pytest.fixture
async def client_re(app_client: httpx.AsyncClient, workspace_re, kho_tep) -> httpx.AsyncClient:
    """Client đã đăng nhập vào workspace `rew`, kho tệp rỗng.

    Nhận `kho_tep` để BUỘC THỨ TỰ: nó dọn bucket lúc setup, nên test nào upload
    trước rồi mới dựng nó sẽ mất file vừa ghi.
    """
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@re.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client
```

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/modules/realestate/test_repo.py`:

```python
"""SQL của M4a. Chạy qua `tenant_conn()` thật — RLS có hiệu lực.

Hàm repo KHÔNG nhận `tenant_id` (trừ INSERT): RLS đã lọc rồi, và nhận thêm tham
số đó là mời người viết code sau lọc bằng tay rồi tưởng thế là đủ.
"""

import asyncpg
import pytest

from portal.modules.realestate import repo

pytestmark = pytest.mark.integration


async def _du_an(conn: asyncpg.Connection, tenant: str, code: str = "VOP2", **kw):
    return await repo.ghi_du_an(conn, tenant, code, {"name": f"DA {code}", **kw})


async def test_ghi_roi_doc_lai(conn_re: asyncpg.Connection, workspace_re: str):
    await _du_an(conn_re, workspace_re)
    r = await repo.doc_du_an(conn_re, "VOP2")
    assert r is not None and r["name"] == "DA VOP2"


async def test_ghi_lan_hai_la_cap_nhat_khong_phai_trung_khoa(
    conn_re: asyncpg.Connection, workspace_re: str
):
    """UPSERT theo `(tenant_id, code)`. Import gọi hàm này cho cả dòng thêm lẫn
    dòng sửa — hai đường code riêng cho hai việc gần giống nhau là hai chỗ để
    lệch nhau."""
    await _du_an(conn_re, workspace_re)
    await repo.ghi_du_an(conn_re, workspace_re, "VOP2", {"name": "Tên mới"})
    assert (await repo.doc_du_an(conn_re, "VOP2"))["name"] == "Tên mới"
    assert len(await repo.liet_ke_du_an(conn_re)) == 1


async def test_ghi_cap_nhat_updated_at(conn_re: asyncpg.Connection, workspace_re: str):
    """BR06 — mốc cập nhật hệ TỰ đóng, không cho sửa tay. Không tự đóng thì rào
    chắn độ tươi của agent đọc một con số đứng yên."""
    r1 = await _du_an(conn_re, workspace_re)
    r2 = await repo.ghi_du_an(conn_re, workspace_re, "VOP2", {"name": "x"})
    assert r2["updated_at"] > r1["updated_at"]


async def test_ghi_tu_choi_cot_ngoai_danh_sach_trang(
    conn_re: asyncpg.Connection, workspace_re: str
):
    from portal.modules.realestate.chinh_sach import LoiTruongLa

    with pytest.raises(LoiTruongLa):
        await repo.ghi_du_an(conn_re, workspace_re, "X", {"tenant_id": "khac"})


async def test_liet_ke_loc_theo_tim_va_region(conn_re: asyncpg.Connection, workspace_re: str):
    await repo.ghi_du_an(conn_re, workspace_re, "A", {"name": "Ocean Park", "region": "Miền Bắc"})
    await repo.ghi_du_an(conn_re, workspace_re, "B", {"name": "Sola", "region": "Miền Nam"})
    assert [r["code"] for r in await repo.liet_ke_du_an(conn_re, tim="ocean")] == ["A"]
    assert [r["code"] for r in await repo.liet_ke_du_an(conn_re, region="Miền Nam")] == ["B"]


async def test_ma_dang_co_tra_tap_ma(conn_re: asyncpg.Connection, workspace_re: str):
    await repo.ghi_du_an(conn_re, workspace_re, "A", {})
    await repo.ghi_du_an(conn_re, workspace_re, "B", {})
    assert await repo.ma_dang_co(conn_re, "project") == frozenset({"A", "B"})


async def test_xoa_theo_ma_tra_so_hang_da_xoa(conn_re: asyncpg.Connection, workspace_re: str):
    for m in ("A", "B", "C"):
        await repo.ghi_du_an(conn_re, workspace_re, m, {})
    assert await repo.xoa_theo_ma(conn_re, "project", ["A", "C"]) == 2
    assert await repo.ma_dang_co(conn_re, "project") == frozenset({"B"})


async def test_xoa_theo_ma_rong_khong_xoa_gi(conn_re: asyncpg.Connection, workspace_re: str):
    """Danh sách rỗng ⇒ `WHERE code = ANY('{}')` khớp 0 hàng. Viết ra vì một
    bản cài đặt "nếu rỗng thì bỏ WHERE" sẽ xoá sạch bảng."""
    await repo.ghi_du_an(conn_re, workspace_re, "A", {})
    assert await repo.xoa_theo_ma(conn_re, "project", []) == 0
    assert await repo.ma_dang_co(conn_re, "project") == frozenset({"A"})


async def test_dem_thieu_theo_menh_de(conn_re: asyncpg.Connection, workspace_re: str):
    from portal.modules.realestate.chinh_sach import menh_de_thieu

    await repo.ghi_du_an(conn_re, workspace_re, "VOP2", {})
    await repo.ghi_can(conn_re, workspace_re, "U1", {"project_code": "VOP2", "price_vnd": 1})
    await repo.ghi_can(conn_re, workspace_re, "U2", {"project_code": "VOP2"})
    assert await repo.dem_thieu(conn_re, "unit", menh_de_thieu(["price_vnd"])) == 1


async def test_dem_thieu_menh_de_rong_tra_0(conn_re: asyncpg.Connection, workspace_re: str):
    """N2 chưa chốt ⇒ không trường nào bắt buộc ⇒ 0 căn thiếu. Trả tổng số căn
    ở đây là hiện một cảnh báo sai trên mọi workspace."""
    await repo.ghi_du_an(conn_re, workspace_re, "VOP2", {})
    await repo.ghi_can(conn_re, workspace_re, "U1", {"project_code": "VOP2"})
    assert await repo.dem_thieu(conn_re, "unit", "") == 0


async def test_hai_tenant_khong_thay_nhau(pool: asyncpg.Pool, workspace_re: str):
    """Cổng 1 của spec §9 ở mức repo. RLS lo phần này — test ở đây chứng minh
    `tenant_conn()` thật sự đặt biến, không phải chứng minh Postgres đúng."""
    from portal.core.db.session import tenant_conn

    async with pool.acquire() as c, c.transaction():
        await c.execute("INSERT INTO control.tenants (id, name) VALUES ('rew2', 'W2')")
    try:
        async with tenant_conn(pool, workspace_re) as c1:
            await repo.ghi_du_an(c1, workspace_re, "RIENG", {})
        async with tenant_conn(pool, "rew2") as c2:
            assert await repo.doc_du_an(c2, "RIENG") is None
    finally:
        async with pool.acquire() as c, c.transaction():
            await c.execute("DELETE FROM control.tenants WHERE id = 'rew2'")
```

- [ ] **Step 3: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: ... realestate.repo`

- [ ] **Step 4: Viết `contracts.py`**

```python
"""MẶT TIỀN của module realestate — file DUY NHẤT module khác được import.

Import `service.py` / `repo.py` / `router.py` từ module khác là LỖI CI
(`tests/test_module_boundaries.py` đọc AST).

Tên trường camelCase vì đây là hợp đồng HTTP — cùng lý do `modules/kb/contracts.py`.
Tên CỘT giữ snake_case: chúng là tên cột thật, và FE dùng chúng làm tên cột file
CSV (spec §8.3a). Đổi sang camelCase ở đây là để file mẫu lệch schema.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from portal.modules.realestate.chinh_sach import (
    COT_PROJECT,
    COT_UNIT,
    GATED,
    KHONG_LOC_DUOC,
)

__all__ = [
    "COT_GIA_PROJECT", "COT_GIA_UNIT", "COT_PROJECT", "COT_UNIT",
    "GATED", "KHONG_LOC_DUOC", "MODE",
    "BaoCaoImportOut", "CanOut", "ChinhSachTruongIn", "ChinhSachTruongOut",
    "DongLoiOut", "DuAnOut", "GapOut", "ImportJobOut",
]

COT_GIA_UNIT: dict[str, str] = {
    "price_ty": "price_vnd",
    "price_tts_ty": "price_tts_vnd",
    "price_tttd_ty": "price_tttd_vnd",
    "price_loan_ty": "price_loan_vnd",
}
"""Ánh xạ cột-file-nhập-bằng-TỶ → cột-DB-lưu-VND (DL_01 BR05).

Hậu tố `_ty` CHỈ tồn tại ở đây và trong header file CSV — không cột DB nào mang
nó (`test_khong_cot_nao_ten_ty` quét động). Đây là ranh giới đổi đơn vị, và nó
có đúng một chỗ."""

COT_GIA_PROJECT: dict[str, str] = {}
"""Dự án không có cột giá nào. Khai rỗng tường minh để `service.py` gọi được một
đường code cho cả hai thực thể."""

MODE = ("them_va_cap_nhat", "thay_the_toan_bo")


class DuAnOut(BaseModel):
    code: str
    name: str
    slug: str
    type: str
    region: str
    location: str
    investor: str
    parentCode: str
    status: str
    isHot: bool
    isFeatured: bool
    sortHot: int
    sortOrder: int
    agentEnabled: bool
    """BR11 — công tắc *Agent dùng*. KHÁC `status` (draft/published): status là
    trạng thái biên tập, cái này quyết định agent có được nhắc tới dự án không."""
    lat: float | None
    lng: float | None
    overview: dict
    soCan: int
    """Đếm từ `units`, không phải cột lưu — con số lưu sẽ lệch ngay lần import
    đầu tiên và không ai biết."""
    updatedAt: datetime


class CanOut(BaseModel):
    code: str
    projectCode: str
    unitType: str
    status: str
    direction: str
    zone: str
    building: str
    floor: int | None
    bedrooms: int | None
    bathrooms: int | None
    priceVnd: int | None
    priceTtsVnd: int | None
    priceTttdVnd: int | None
    priceLoanVnd: int | None
    priceLabel: str
    areaM2: float | None
    areaBuildM2: float | None
    fundType: str
    isHot: bool
    isActive: bool
    commission: str
    bankSupport: str
    csbhFull: str
    """Ba trường GATED (BR09) — API của PORTAL trả chúng cho người dùng có
    `catalog.read`; view `agent_api` mới là chỗ chặn agent. Hai đường đọc khác
    nhau, hai luật khác nhau: nhân viên workspace ĐƯỢC xem hoa hồng của chính
    họ, agent thì không."""
    csbhBrief: str
    gift: str
    legal: str
    checkTime: datetime | None
    updatedAt: datetime


class ChinhSachTruongOut(BaseModel):
    entity: str
    field: str
    labelVi: str
    type: str
    isCore: bool
    formVisible: bool
    agentReadable: bool
    filterable: bool
    matchOp: str | None
    requiredForAgent: bool


class ChinhSachTruongIn(BaseModel):
    formVisible: bool | None = None
    agentReadable: bool | None = None
    filterable: bool | None = None
    matchOp: str | None = None
    requiredForAgent: bool | None = None


class GapOut(BaseModel):
    entity: str
    soBanGhiThieu: int
    truongBatBuoc: list[str]
    """Rỗng nghĩa là BA chưa chốt N2 — FE hiện chưa đặt tiêu chí, KHÔNG hiện
    0 căn thiếu dữ liệu. Hai câu đó nói hai chuyện khác nhau."""


class DongLoiOut(BaseModel):
    dong: int
    ma: str
    lyDo: str


class BaoCaoImportOut(BaseModel):
    them: int
    sua: int
    xoa: int
    maSeXoa: list[str]
    loi: list[DongLoiOut]


class ImportJobOut(BaseModel):
    jobId: int
    entity: str
    mode: str
    state: str
    fileSha256: str
    """Bước ② gửi lại chuỗi này. Lệch ⇒ 409. Đây là cái neo của luồng hai bước:
    không có nó thì người dùng xác nhận xoá 3 dòng và hệ ghi một file xoá 300."""
    baoCao: BaoCaoImportOut
    expiresAt: datetime
```

- [ ] **Step 5: Viết `repo.py`**

```python
"""SQL của module realestate. Mọi hàm nhận `conn` từ caller.

`projects` · `units` · 4 bảng con đều ở `tenant_data` và chịu RLS, nên MỌI truy
vấn phải đi qua một kết nối đã ở trong `tenant_conn()` — điều kiện 4 của cách ly
(`SET LOCAL` trong giao dịch tường minh).

Nhờ vậy hàm ở đây KHÔNG nhận `tenant_id`, trừ `ghi_*` (INSERT cần giá trị cho
cột). Nhận thêm tham số đó ở hàm đọc là mời người viết code sau lọc bằng tay rồi
tưởng thế là đủ.

VÌ SAO GHÉP TÊN CỘT VÀO SQL: payload là `dict` động (form gửi 5 trường, import
gửi 30), nên danh sách cột không viết cứng được. An toàn nhờ `loc_ten_cot()` —
tên nào không thuộc danh sách trắng của `chinh_sach.py` thì không tới được đây.
GIÁ TRỊ thì luôn đi bằng tham số `$n`, không bao giờ ghép.
"""

from typing import Literal

import asyncpg

from portal.modules.realestate.chinh_sach import COT_PROJECT, COT_UNIT, LoiTruongLa

Entity = Literal["project", "unit"]

_BANG: dict[str, str] = {"project": "tenant_data.projects", "unit": "tenant_data.units"}
_COT_CHO_PHEP: dict[str, frozenset[str]] = {"project": COT_PROJECT, "unit": COT_UNIT}


def _kiem_payload(entity: Entity, payload: dict) -> list[str]:
    """Trả danh sách cột sẽ ghi. Raise nếu có tên lạ.

    RAISE chứ không lọc im lặng, khác `loc_ten_cot()`: nguồn ở đây là payload
    người dùng gửi lên, và im lặng bỏ một trường họ vừa nhập là mất dữ liệu mà
    họ tưởng đã lưu.
    """
    cho_phep = _COT_CHO_PHEP[entity]
    la = [k for k in payload if k not in cho_phep or k == "code"]
    if la:
        raise LoiTruongLa(f"trường không hợp lệ: {sorted(la)}")
    return sorted(payload)


# ─── Dự án ──────────────────────────────────────────────────────────────────

_COT_DU_AN = (
    "code, name, slug, type, region, location, investor, parent_code, status, "
    "is_hot, is_featured, sort_hot, sort_order, agent_enabled, lat, lng, overview, updated_at"
)


async def liet_ke_du_an(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    region: str = "",
    type_: str = "",
    status: str = "",
) -> list[asyncpg.Record]:
    """Kèm `so_can` đếm từ `units`. RLS lo phần "của workspace nào".

    LATERAL chứ không GROUP BY: dự án chưa có căn nào phải hiện với `so_can = 0`,
    không biến mất khỏi danh sách. Đó là trạng thái bình thường của dự án vừa tạo.
    """
    return await conn.fetch(
        f"""
        SELECT {", ".join("p." + c.strip() for c in _COT_DU_AN.split(","))}, c.so_can
          FROM tenant_data.projects p
          LEFT JOIN LATERAL (
                SELECT count(*)::int AS so_can FROM tenant_data.units u
                 WHERE u.tenant_id = p.tenant_id AND u.project_code = p.code
          ) c ON true
         WHERE ($1 = '' OR p.name ILIKE '%' || $1 || '%' OR p.location ILIKE '%' || $1 || '%'
                       OR p.code ILIKE '%' || $1 || '%')
           AND ($2 = '' OR p.region = $2)
           AND ($3 = '' OR p.type   = $3)
           AND ($4 = '' OR p.status = $4)
         ORDER BY p.sort_order, p.updated_at DESC, p.id DESC
        """,
        tim, region, type_, status,
    )


async def doc_du_an(conn: asyncpg.Connection, code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""SELECT {_COT_DU_AN},
                   (SELECT count(*)::int FROM tenant_data.units u
                     WHERE u.tenant_id = p.tenant_id AND u.project_code = p.code) AS so_can
              FROM tenant_data.projects p WHERE code = $1""",
        code,
    )


async def ghi_du_an(
    conn: asyncpg.Connection, tenant_id: str, code: str, payload: dict
) -> asyncpg.Record:
    return await _upsert(conn, "project", tenant_id, code, payload, _COT_DU_AN)


async def xoa_du_an(conn: asyncpg.Connection, code: str) -> bool:
    kq = await conn.execute("DELETE FROM tenant_data.projects WHERE code = $1", code)
    return kq.endswith(" 1")


# ─── Quỹ căn ────────────────────────────────────────────────────────────────

_COT_CAN = (
    "code, project_code, unit_type, status, direction, zone, building, floor, "
    "floor_min, floor_max, bedrooms, bathrooms, investor, price_vnd, price_tts_vnd, "
    "price_tttd_vnd, price_loan_vnd, price_label, loan_info, area_m2, area_build_m2, "
    "fund_type, is_hot, hot_sort, is_active, sort_order, sale_email, commission, "
    "bank_support, csbh_full, csbh_brief, gift, legal, delivery_standard, axis, front, "
    "description, lat, lng, check_time, updated_at"
)


async def liet_ke_can(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    project_code: str = "",
    fund_type: str = "",
    direction: str = "",
    status: str = "",
) -> list[asyncpg.Record]:
    """KHÔNG có bộ lọc theo `floor` hay `building` — BR04 và quyết định #17.

    Thêm chúng vào đây là mở lại đúng cái đường trả sai âm thầm: khách hỏi căn
    tầng 14, hệ trả căn tầng bất kỳ, agent đọc như thể đúng. Muốn mở thì bật
    `field_policy_live.filterable` TRƯỚC, và `test_bo_loc_co_du_lieu.py` sẽ bắt
    nếu bật mà không có dữ liệu.
    """
    return await conn.fetch(
        f"""SELECT {_COT_CAN} FROM tenant_data.units
             WHERE ($1 = '' OR code ILIKE '%' || $1 || '%' OR investor ILIKE '%' || $1 || '%')
               AND ($2 = '' OR project_code = $2)
               AND ($3 = '' OR fund_type    = $3)
               AND ($4 = '' OR direction    = $4)
               AND ($5 = '' OR status       = $5)
             ORDER BY sort_order, updated_at DESC, id DESC""",
        tim, project_code, fund_type, direction, status,
    )


async def doc_can(conn: asyncpg.Connection, code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {_COT_CAN} FROM tenant_data.units WHERE code = $1", code)


async def ghi_can(
    conn: asyncpg.Connection, tenant_id: str, code: str, payload: dict
) -> asyncpg.Record:
    return await _upsert(conn, "unit", tenant_id, code, payload, _COT_CAN)


async def xoa_can(conn: asyncpg.Connection, code: str) -> bool:
    kq = await conn.execute("DELETE FROM tenant_data.units WHERE code = $1", code)
    return kq.endswith(" 1")


# ─── Dùng chung ─────────────────────────────────────────────────────────────


async def _upsert(
    conn: asyncpg.Connection, entity: Entity, tenant_id: str, code: str, payload: dict, cot_ra: str
) -> asyncpg.Record:
    """UPSERT theo `(tenant_id, code)`. MỘT đường cho cả thêm lẫn sửa.

    Hai đường code riêng cho hai việc gần giống nhau là hai chỗ để lệch nhau —
    và chỗ lệch điển hình là `updated_at`: đường thêm đóng dấu, đường sửa quên.
    """
    cot = _kiem_payload(entity, payload)
    gia_tri = [payload[c] for c in cot]

    # $1 = tenant_id, $2 = code, còn lại là payload
    dat_cho = ", ".join(f"${i + 3}" for i in range(len(cot)))
    cap_nhat = ", ".join(f"{c} = EXCLUDED.{c}" for c in cot)
    them_cot = (", " + ", ".join(cot)) if cot else ""
    them_dat_cho = (", " + dat_cho) if cot else ""
    # `clock_timestamp()`, KHÔNG `now()`. `now()` trả giờ bắt đầu GIAO DỊCH, nên
    # một lượt import ghi 500 hàng thì cả 500 mang cùng một mốc — và hai lần ghi
    # cùng bản ghi trong một giao dịch cho ra mốc BẰNG NHAU. Với BR06 (rào chắn
    # độ tươi của agent) thì "lần sửa gần nhất" phải là giờ thật.
    #
    # Đóng dấu NGAY CẢ khi payload rỗng: "lưu mà không đổi gì" vẫn là một lần
    # người dùng xác nhận dữ liệu còn đúng — đúng thứ BR06 muốn biết.
    set_menh_de = (
        f"{cap_nhat}, updated_at = clock_timestamp()" if cot else "updated_at = clock_timestamp()"
    )

    return await conn.fetchrow(
        f"""INSERT INTO {_BANG[entity]} (tenant_id, code{them_cot})
                 VALUES ($1, $2{them_dat_cho})
            ON CONFLICT (tenant_id, code) DO UPDATE SET {set_menh_de}
              RETURNING {cot_ra}""",
        tenant_id, code, *gia_tri,
    )


async def ma_dang_co(conn: asyncpg.Connection, entity: Entity) -> frozenset[str]:
    """Tập `code` đang có. Đầu vào của `nhap_lieu.chay_thu()`."""
    rows = await conn.fetch(f"SELECT code FROM {_BANG[entity]}")
    return frozenset(r["code"] for r in rows)


async def xoa_theo_ma(conn: asyncpg.Connection, entity: Entity, ma: list[str]) -> int:
    """Trả số hàng đã xoá. Danh sách rỗng ⇒ 0, KHÔNG phải xoá tất.

    `= ANY($1)` với mảng rỗng khớp 0 hàng — đúng ý. Một bản cài đặt "nếu rỗng
    thì bỏ mệnh đề WHERE" sẽ xoá sạch bảng, nên viết thẳng thế này và có test.
    """
    kq = await conn.execute(f"DELETE FROM {_BANG[entity]} WHERE code = ANY($1::text[])", ma)
    return int(kq.rsplit(" ", 1)[-1])


async def dem_thieu(conn: asyncpg.Connection, entity: Entity, menh_de: str) -> int:
    """Đếm bản ghi thiếu ít nhất một trường bắt buộc (BR07).

    `menh_de` PHẢI đến từ `chinh_sach.menh_de_thieu()` — nó là chuỗi SQL, và đó
    là hàm duy nhất kiểm tên trường qua danh sách trắng. Rỗng ⇒ 0.
    """
    if not menh_de:
        return 0
    return await conn.fetchval(f"SELECT count(*)::int FROM {_BANG[entity]} WHERE {menh_de}")


# ─── Chính sách trường ──────────────────────────────────────────────────────

_COT_CS = (
    "entity, field, label_vi, type, enum_values, is_core, form_visible, "
    "agent_readable, filterable, match_op, required_for_agent"
)


async def doc_chinh_sach(conn: asyncpg.Connection, entity: str = "") -> list[asyncpg.Record]:
    """`control.field_policy_live` KHÔNG có RLS (nó ở `control`), nên hàm này —
    khác mọi hàm khác trong file — phải lọc `tenant_id` bằng tay.

    Nó nhận `tenant_id` qua `portal.current_tenant()` của chính kết nối đang ở
    trong `tenant_conn()`: cùng một nguồn sự thật với RLS, không phải một tham
    số người gọi truyền vào và có thể truyền sai.
    """
    return await conn.fetch(
        f"""SELECT {_COT_CS} FROM control.field_policy_live
             WHERE tenant_id = portal.current_tenant()
               AND ($1 = '' OR entity = $1)
             ORDER BY entity, field""",
        entity,
    )


async def ghi_chinh_sach(
    conn: asyncpg.Connection, tenant_id: str, entity: str, field: str, thay_doi: dict
) -> asyncpg.Record:
    """Cập nhật cờ. Chỉ ghi khoá có mặt trong `thay_doi` — PATCH, không PUT."""
    cho_phep = {
        "form_visible", "agent_readable", "filterable", "match_op", "required_for_agent",
    }
    la = set(thay_doi) - cho_phep
    if la:
        raise LoiTruongLa(f"cờ không hợp lệ: {sorted(la)}")

    cot = sorted(thay_doi)
    dat = ", ".join(f"{c} = ${i + 4}" for i, c in enumerate(cot))
    return await conn.fetchrow(
        f"""UPDATE control.field_policy_live SET {dat}
             WHERE tenant_id = $1 AND entity = $2 AND field = $3
         RETURNING {_COT_CS}""",
        tenant_id, entity, field, *[thay_doi[c] for c in cot],
    )
```

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_repo.py -v`
Expected: PASS — 11 test

- [ ] **Step 7: Chạy cổng ranh giới module**

Run: `uv run pytest tests/test_module_boundaries.py tests/api -v`
Expected: PASS. `contracts.py` chỉ import `portal.modules.realestate.chinh_sach`
(cùng module) và pydantic — không import module khác.

- [ ] **Step 8: Lint và commit**

```bash
uv run ruff check src/portal/modules/realestate tests/modules/realestate
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/contracts.py src/portal/modules/realestate/repo.py \
        tests/modules/realestate/conftest.py tests/modules/realestate/test_repo.py
git commit -m "feat(m4a): contracts + repo — UPSERT một đường, tên cột qua danh sách trắng (T6)"
```

---

## Task 7: `router.py` — CRUD Dự án và Quỹ căn

> **Gộp hai thực thể vào một task có chủ ý.** Chúng dùng chung một file router,
> chung hàm `_ra_du_an`/`_ra_can`, chung `tenant_conn()` và chung cách ghi nhật ký.
> Không có tình huống nào người review nhận CRUD dự án mà từ chối CRUD quỹ căn.
>
> **Không có `service.py` cho CRUD** — router gọi thẳng `repo`, đúng nếp
> `modules/kb/router.py`. Spec §5 liệt kê `service.py` với *"CRUD · chay_thu() ·
> ap_dung()"*; ở đây `service.py` ra đời ở Task 9 và chỉ giữ phần điều phối import.
> Một lớp service chỉ chuyển tiếp lời gọi là một chỗ để lệch nhau.

**Files:**
- Create: `src/portal/modules/realestate/router.py`
- Create: `tests/modules/realestate/test_crud.py`

**Interfaces:**
- Consumes: `repo.*` · `contracts.DuAnOut`/`CanOut` (Task 6) · `gia.doi_don_vi_gia` (Task 1)
  · `require` · `lay_pool` · `tenant_conn` · `nhat_ky.ghi` (core)
- Produces: `ROUTER: APIRouter` — Task 8 và 9 thêm route vào **chính file này**;
  `_nhat_ky(conn, p, hanh_dong, chi_tiet)` helper dùng lại.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_crud.py`:

```python
"""6 endpoint CRUD. Chạy qua HTTP thật với phiên thật — không gọi hàm trực tiếp.

Gọi service trực tiếp thì bỏ qua `require(action)`, `tenant_conn()` và handler
lỗi — ba thứ mà M4a phụ thuộc vào và không tự cài đặt.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


async def _tao_du_an(c: httpx.AsyncClient, code: str = "VOP2", **kw) -> httpx.Response:
    return await c.post(f"{API}/projects", json={"code": code, "name": f"DA {code}", **kw})


async def test_tao_va_doc_lai_du_an(client_re: httpx.AsyncClient):
    r = await _tao_du_an(client_re, region="Miền Bắc")
    assert r.status_code == 201, r.text
    assert r.json()["agentEnabled"] is True, "dự án mới mặc định BẬT cho agent"

    r = await client_re.get(f"{API}/projects/VOP2")
    assert r.status_code == 200 and r.json()["region"] == "Miền Bắc"


async def test_danh_sach_kem_so_can(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re)
    await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "VOP2"})
    ds = (await client_re.get(f"{API}/projects")).json()
    assert ds[0]["soCan"] == 1


async def test_du_an_chua_co_can_van_hien_voi_so_can_0(client_re: httpx.AsyncClient):
    """Trạng thái bình thường của dự án vừa tạo. Biến mất khỏi danh sách là lỗi
    LEFT JOIN thành INNER JOIN — im lặng, và chỉ lộ ra khi có người tạo dự án
    rồi không thấy nó đâu."""
    await _tao_du_an(client_re)
    ds = (await client_re.get(f"{API}/projects")).json()
    assert len(ds) == 1 and ds[0]["soCan"] == 0


async def test_sua_du_an_bang_patch(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re)
    r = await client_re.patch(f"{API}/projects/VOP2", json={"name": "Tên mới"})
    assert r.status_code == 200 and r.json()["name"] == "Tên mới"


async def test_patch_chi_doi_truong_gui_len(client_re: httpx.AsyncClient):
    """PATCH, không PUT. Gửi `{name}` mà xoá mất `region` là mất dữ liệu người
    dùng không hề chạm tới."""
    await _tao_du_an(client_re, region="Miền Bắc")
    await client_re.patch(f"{API}/projects/VOP2", json={"name": "x"})
    assert (await client_re.get(f"{API}/projects/VOP2")).json()["region"] == "Miền Bắc"


async def test_bat_tat_agent_enabled(client_re: httpx.AsyncClient):
    """BR11. Đây là công tắc, KHÔNG phải `status` — spec §8.4 ghi rõ prototype
    đang trộn hai thứ đó ở cột AGENT DÙNG."""
    await _tao_du_an(client_re)
    r = await client_re.patch(f"{API}/projects/VOP2", json={"agentEnabled": False})
    assert r.json()["agentEnabled"] is False


async def test_xoa_du_an(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re)
    assert (await client_re.delete(f"{API}/projects/VOP2")).status_code == 204
    assert (await client_re.get(f"{API}/projects/VOP2")).status_code == 404


async def test_doc_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.get(f"{API}/projects/KHONG-CO")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_tao_can_nhap_gia_bang_ty(client_re: httpx.AsyncClient):
    """BR05 — đổi đơn vị TẠI BIÊN NHẬP. Form gửi `priceTy`, DB lưu VND."""
    await _tao_du_an(client_re)
    r = await client_re.post(
        f"{API}/units", json={"code": "NT2-1408", "projectCode": "VOP2", "priceTy": "5,62"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["priceVnd"] == 5_620_000_000


async def test_gia_sai_dinh_dang_tra_er_02(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re)
    r = await client_re.post(
        f"{API}/units", json={"code": "U1", "projectCode": "VOP2", "priceTy": "abc"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_02"


async def test_thieu_code_tra_er_01(client_re: httpx.AsyncClient):
    r = await client_re.post(f"{API}/units", json={"projectCode": "VOP2"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_01"


async def test_trung_ma_can_tra_er_06(client_re: httpx.AsyncClient):
    """BR10 — mã căn là định danh. POST lần hai KHÔNG được âm thầm ghi đè: người
    dùng bấm Thêm căn tưởng tạo mới, mà lại mất căn cũ."""
    await _tao_du_an(client_re)
    await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "VOP2"})
    r = await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "VOP2"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_06"


async def test_loc_can_theo_du_an(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, code="A")
    await _tao_du_an(client_re, code="B")
    await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "A"})
    await client_re.post(f"{API}/units", json={"code": "U2", "projectCode": "B"})
    ds = (await client_re.get(f"{API}/units", params={"projectCode": "A"})).json()
    assert [u["code"] for u in ds] == ["U1"]


@pytest.mark.parametrize("bo_loc", ["floor", "building", "zone"])
async def test_khong_co_bo_loc_theo_tang_hay_toa(client_re: httpx.AsyncClient, bo_loc: str):
    """BR04 + quyết định #17. Tham số lạ phải bị BỎ QUA, không được lọc.

    Cái nguy hiểm không phải là 400 hay 200 — mà là một bộ lọc CÓ VẺ hoạt động:
    khách hỏi căn tầng 14, hệ trả căn tầng bất kỳ, agent đọc như thể đúng.
    """
    await _tao_du_an(client_re)
    await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "VOP2"})
    ds = (await client_re.get(f"{API}/units", params={bo_loc: "999"})).json()
    assert len(ds) == 1, f"tham số {bo_loc} đang lọc thật — phải bị bỏ qua"


async def test_moi_thao_tac_ghi_nhat_ky(client_re: httpx.AsyncClient, pool):
    """BR13. Không ghi thì lúc một căn bị xoá nhầm, không ai lần được ai làm."""
    await _tao_du_an(client_re)
    await client_re.patch(f"{API}/projects/VOP2", json={"name": "x"})
    await client_re.delete(f"{API}/projects/VOP2")
    hd = [
        r["hanh_dong"]
        for r in await pool.fetch(
            "SELECT hanh_dong FROM control.audit_log WHERE tenant_id = 'rew' ORDER BY id"
        )
    ]
    assert hd == ["realestate.project.create", "realestate.project.update", "realestate.project.delete"]
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_crud.py -v`
Expected: FAIL — 404 trên mọi route (router chưa tồn tại).

- [ ] **Step 3: Viết `router.py`**

```python
"""Endpoint của M4a. Mọi route khai `require(action)` — cổng 1 của M2a.

Ba action đã có từ M2a (`catalog.read/write/delete`) và phủ đúng "Dự án · Quỹ
căn" (PQ_01 §3.1 dòng 7·8·9). M4a KHÔNG thêm action nào — khác M10, module phải
thêm hai hằng vào `core/auth/actions.py`.

MỌI truy vấn đi qua `tenant_conn()`: `projects`/`units` ở `tenant_data` và chịu
RLS, nên đây là cửa DUY NHẤT — điều kiện 4 của cách ly (`SET LOCAL` trong giao
dịch tường minh). Đọc ngoài giao dịch là đọc không có tenant hiệu lực.

KHÔNG CÓ BỘ LỌC THEO `floor`/`building`/`zone` (BR04 · quyết định #17). Tham số
lạ trong query string bị FastAPI bỏ qua — đó là hành vi đúng ở đây, và
`test_khong_co_bo_loc_theo_tang_hay_toa` canh để nó không âm thầm thành "có lọc".
"""

import asyncpg
from fastapi import APIRouter, Depends, Query, status

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.realestate import repo
from portal.modules.realestate.chinh_sach import LoiTruongLa
from portal.modules.realestate.contracts import COT_GIA_UNIT, CanOut, DuAnOut
from portal.modules.realestate.gia import LoiGiaKhongHopLe, doi_don_vi_gia

ROUTER = APIRouter(tags=["realestate"])
"""KHÔNG có prefix chung: `/projects` · `/units` · `/imports` · `/field-policy` ·
`/data-gaps` là năm tài nguyên ngang hàng (spec §7), không phải năm nhánh của một
cái. `api/app.py` gắn `/api/v1`."""


def _thieu_ma() -> loi.LoiPortal:
    return loi.LoiPortal("ER_01", 422, "Thiếu mã (trường code)")


def _gia_sai(ly_do: str) -> loi.LoiPortal:
    return loi.LoiPortal("ER_02", 422, ly_do)


def _trung_ma(ma: str) -> loi.LoiPortal:
    return loi.LoiPortal("ER_06", 422, f"Mã {ma} đã tồn tại")


def _khong_thay(gi: str) -> loi.LoiPortal:
    return loi.LoiPortal("NOT_FOUND", 404, f"Không tìm thấy {gi}")


def _truong_la(e: LoiTruongLa) -> loi.LoiPortal:
    return loi.LoiPortal("ER_01", 422, str(e))


# ─── Đổi camelCase (HTTP) ↔ snake_case (cột) ────────────────────────────────
# Bảng ánh xạ TƯỜNG MINH thay vì `re.sub` tự động: tự động thì `priceTtsVnd` ra
# `price_tts_vnd` (đúng) nhưng `areaM2` ra `area_m2` chỉ nhờ may mắn, và
# `csbhFull` ra `csbh_full` cũng vậy. Một bảng đọc được là một bảng sửa được.

_JSON_SANG_COT_DU_AN = {
    "name": "name", "slug": "slug", "type": "type", "region": "region",
    "location": "location", "investor": "investor", "parentCode": "parent_code",
    "status": "status", "isHot": "is_hot", "isFeatured": "is_featured",
    "sortHot": "sort_hot", "sortOrder": "sort_order", "agentEnabled": "agent_enabled",
    "lat": "lat", "lng": "lng",
}

_JSON_SANG_COT_CAN = {
    "projectCode": "project_code", "unitType": "unit_type", "status": "status",
    "direction": "direction", "zone": "zone", "building": "building", "floor": "floor",
    "floorMin": "floor_min", "floorMax": "floor_max", "bedrooms": "bedrooms",
    "bathrooms": "bathrooms", "investor": "investor", "priceLabel": "price_label",
    "loanInfo": "loan_info", "areaM2": "area_m2", "areaBuildM2": "area_build_m2",
    "fundType": "fund_type", "isHot": "is_hot", "hotSort": "hot_sort",
    "isActive": "is_active", "sortOrder": "sort_order", "saleEmail": "sale_email",
    "commission": "commission", "bankSupport": "bank_support", "csbhFull": "csbh_full",
    "csbhBrief": "csbh_brief", "gift": "gift", "legal": "legal",
    "deliveryStandard": "delivery_standard", "axis": "axis", "front": "front",
    "description": "description", "lat": "lat", "lng": "lng", "checkTime": "check_time",
}

_JSON_GIA_SANG_TY = {
    "priceTy": "price_ty", "priceTtsTy": "price_tts_ty",
    "priceTttdTy": "price_tttd_ty", "priceLoanTy": "price_loan_ty",
}
"""Form gửi `priceTy`; `COT_GIA_UNIT` ánh xạ `price_ty` → `price_vnd`. Hai bước
vì file CSV dùng `price_ty` (snake_case) còn JSON dùng `priceTy`."""


def _payload(than: dict, anh_xa: dict[str, str]) -> dict:
    """Giữ khoá có mặt trong thân request. Khoá lạ bị BỎ IM LẶNG.

    Bỏ im lặng ở đây khác `repo._kiem_payload` raise: chỗ này lọc khoá HTTP mà
    FE có thể gửi thừa (ví dụ `updatedAt` đọc về rồi gửi lại nguyên cục); chỗ kia
    canh tên CỘT, và một tên cột lạ tới được đó là dấu hiệu ánh xạ hỏng.
    """
    return {cot: than[k] for k, cot in anh_xa.items() if k in than}


def _them_gia(than: dict, payload: dict) -> dict:
    """Đổi mọi ô giá nhập bằng tỷ sang VND. BR05 — tại biên nhập, một chỗ."""
    for khoa_json, khoa_ty in _JSON_GIA_SANG_TY.items():
        if khoa_json not in than:
            continue
        try:
            vnd = doi_don_vi_gia(than[khoa_json])
        except LoiGiaKhongHopLe as e:
            raise _gia_sai(str(e)) from e
        payload[COT_GIA_UNIT[khoa_ty]] = vnd
    return payload


def _ra_du_an(r: asyncpg.Record) -> DuAnOut:
    return DuAnOut(
        code=r["code"], name=r["name"], slug=r["slug"], type=r["type"],
        region=r["region"], location=r["location"], investor=r["investor"],
        parentCode=r["parent_code"], status=r["status"], isHot=r["is_hot"],
        isFeatured=r["is_featured"], sortHot=r["sort_hot"], sortOrder=r["sort_order"],
        agentEnabled=r["agent_enabled"], lat=r["lat"], lng=r["lng"],
        overview=r["overview"] or {}, soCan=r["so_can"], updatedAt=r["updated_at"],
    )


def _ra_can(r: asyncpg.Record) -> CanOut:
    return CanOut(
        code=r["code"], projectCode=r["project_code"], unitType=r["unit_type"],
        status=r["status"], direction=r["direction"], zone=r["zone"],
        building=r["building"], floor=r["floor"], bedrooms=r["bedrooms"],
        bathrooms=r["bathrooms"], priceVnd=r["price_vnd"], priceTtsVnd=r["price_tts_vnd"],
        priceTttdVnd=r["price_tttd_vnd"], priceLoanVnd=r["price_loan_vnd"],
        priceLabel=r["price_label"], areaM2=r["area_m2"], areaBuildM2=r["area_build_m2"],
        fundType=r["fund_type"], isHot=r["is_hot"], isActive=r["is_active"],
        commission=r["commission"], bankSupport=r["bank_support"], csbhFull=r["csbh_full"],
        csbhBrief=r["csbh_brief"], gift=r["gift"], legal=r["legal"],
        checkTime=r["check_time"], updatedAt=r["updated_at"],
    )


async def _nhat_ky(conn: asyncpg.Connection, p: Principal, hanh_dong: str, chi_tiet: dict) -> None:
    """BR13. Gọi SAU KHI việc đã xong — nhật ký ghi việc ĐÃ xảy ra."""
    await nhat_ky.ghi(conn, p.tenant_id, hanh_dong, p.user_id, chi_tiet)


# ─── Dự án ──────────────────────────────────────────────────────────────────


@ROUTER.get("/projects", response_model=list[DuAnOut])
async def liet_ke_du_an(
    tim: str = Query("", alias="tim"),
    region: str = Query(""),
    type_: str = Query("", alias="type"),
    status_: str = Query("", alias="status"),
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[DuAnOut]:
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.liet_ke_du_an(conn, tim=tim, region=region, type_=type_, status=status_)
    return [_ra_du_an(r) for r in rows]


@ROUTER.post("/projects", status_code=status.HTTP_201_CREATED, response_model=DuAnOut)
async def tao_du_an(
    than: dict,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    code = (than.get("code") or "").strip()
    if not code:
        raise _thieu_ma()
    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_du_an(conn, code) is not None:
            raise _trung_ma(code)
        try:
            r = await repo.ghi_du_an(conn, p.tenant_id, code, _payload(than, _JSON_SANG_COT_DU_AN))
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        await _nhat_ky(conn, p, "realestate.project.create", {"code": code})
    return _ra_du_an(r)


@ROUTER.get("/projects/{code}", response_model=DuAnOut)
async def doc_du_an(
    code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        r = await repo.doc_du_an(conn, code)
    if r is None:
        raise _khong_thay("dự án")
    return _ra_du_an(r)


@ROUTER.patch("/projects/{code}", response_model=DuAnOut)
async def sua_du_an(
    code: str,
    than: dict,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    """PATCH, không PUT: gửi `{name}` mà xoá mất `region` là mất dữ liệu người
    dùng không hề chạm tới."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_du_an(conn, code) is None:
            raise _khong_thay("dự án")
        try:
            r = await repo.ghi_du_an(conn, p.tenant_id, code, _payload(than, _JSON_SANG_COT_DU_AN))
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        await _nhat_ky(conn, p, "realestate.project.update", {"code": code, "truong": sorted(than)})
    return _ra_du_an(r)


@ROUTER.delete("/projects/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_du_an(
    code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        if not await repo.xoa_du_an(conn, code):
            raise _khong_thay("dự án")
        await _nhat_ky(conn, p, "realestate.project.delete", {"code": code})


# ─── Quỹ căn ────────────────────────────────────────────────────────────────


@ROUTER.get("/units", response_model=list[CanOut])
async def liet_ke_can(
    tim: str = Query(""),
    project_code: str = Query("", alias="projectCode"),
    fund_type: str = Query("", alias="fundType"),
    direction: str = Query(""),
    status_: str = Query("", alias="status"),
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[CanOut]:
    """Năm bộ lọc, KHÔNG có tầng và toà — BR04, quyết định #17."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.liet_ke_can(
            conn, tim=tim, project_code=project_code,
            fund_type=fund_type, direction=direction, status=status_,
        )
    return [_ra_can(r) for r in rows]


@ROUTER.post("/units", status_code=status.HTTP_201_CREATED, response_model=CanOut)
async def tao_can(
    than: dict,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    code = (than.get("code") or "").strip()
    if not code:
        raise _thieu_ma()
    payload = _them_gia(than, _payload(than, _JSON_SANG_COT_CAN))
    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_can(conn, code) is not None:
            raise _trung_ma(code)
        try:
            r = await repo.ghi_can(conn, p.tenant_id, code, payload)
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        await _nhat_ky(conn, p, "realestate.unit.create", {"code": code})
    return _ra_can(r)


@ROUTER.get("/units/{code}", response_model=CanOut)
async def doc_can(
    code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        r = await repo.doc_can(conn, code)
    if r is None:
        raise _khong_thay("căn")
    return _ra_can(r)


@ROUTER.patch("/units/{code}", response_model=CanOut)
async def sua_can(
    code: str,
    than: dict,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    payload = _them_gia(than, _payload(than, _JSON_SANG_COT_CAN))
    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_can(conn, code) is None:
            raise _khong_thay("căn")
        try:
            r = await repo.ghi_can(conn, p.tenant_id, code, payload)
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        await _nhat_ky(conn, p, "realestate.unit.update", {"code": code, "truong": sorted(than)})
    return _ra_can(r)


@ROUTER.delete("/units/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_can(
    code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        if not await repo.xoa_can(conn, code):
            raise _khong_thay("căn")
        await _nhat_ky(conn, p, "realestate.unit.delete", {"code": code})
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_crud.py -v`
Expected: PASS — 15 test

- [ ] **Step 5: Chạy cổng khai action và registry**

Run: `uv run pytest tests/api -v`
Expected: PASS. `test_moi_route_khai_action.py` quét mọi route và đòi
`KhaiQuyen` — 12 route mới đều khai. `test_actions.py` xanh vì M4a không thêm
action nào, nên `contracts/actions.json` không cần sinh lại.

- [ ] **Step 6: Lint và commit**

```bash
uv run ruff check src/portal/modules/realestate tests/modules/realestate
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/router.py tests/modules/realestate/test_crud.py
git commit -m "feat(m4a): CRUD dự án + quỹ căn — giá đổi ở biên nhập, không lọc theo tầng/toà (T7)"
```

---

## Task 8: `/field-policy` và `/data-gaps`

**Files:**
- Modify: `src/portal/modules/realestate/router.py` (thêm 3 route ở cuối)
- Create: `tests/modules/realestate/test_chinh_sach_api.py`

**Interfaces:**
- Consumes: `repo.doc_chinh_sach` · `repo.ghi_chinh_sach` · `repo.dem_thieu` (Task 6) ·
  `chinh_sach.loc_ten_cot` · `menh_de_thieu` (Task 5) · `contracts.ChinhSachTruongOut` ·
  `ChinhSachTruongIn` · `GapOut` (Task 6) · `_nhat_ky` (Task 7)
- Produces: `GET /field-policy` · `PATCH /field-policy/{entity}/{field}` · `GET /data-gaps`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_chinh_sach_api.py`:

```python
"""Chính sách trường qua HTTP + cảnh báo thiếu dữ liệu (BR07).

Cổng 9 của spec §9 nằm ở đây: đổi `requiredForAgent` bằng API thì `/data-gaps`
phải đổi theo NGAY, không deploy lại. N2 là việc của BA, và bắt BA sửa code là
bắt họ mở merge request.
"""

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
async def co_chinh_sach(pool: asyncpg.Pool, workspace_re: str):
    async with pool.acquire() as conn, conn.transaction():
        for field, core, doc, loc, op in (
            ("price_vnd", True, True, True, "lte"),
            ("commission", True, False, False, None),
            ("floor", True, True, False, None),
            ("direction", True, True, True, "eq"),
        ):
            await conn.execute(
                """INSERT INTO control.field_policy_live
                       (tenant_id, entity, field, is_core, agent_readable, filterable,
                        match_op, label_vi, type)
                   VALUES ($1, 'unit', $2, $3, $4, $5, $6, $2, 'text')""",
                workspace_re, field, core, doc, loc, op,
            )
    return workspace_re


async def test_liet_ke_chinh_sach_theo_entity(client_re: httpx.AsyncClient, co_chinh_sach):
    ds = (await client_re.get(f"{API}/field-policy", params={"entity": "unit"})).json()
    assert {r["field"] for r in ds} == {"price_vnd", "commission", "floor", "direction"}


async def test_ba_truong_thuong_mai_mac_dinh_agent_khong_doc(
    client_re: httpx.AsyncClient, co_chinh_sach
):
    """BR09 — lộ hoa hồng cho khách là sự cố thương mại thật."""
    ds = (await client_re.get(f"{API}/field-policy", params={"entity": "unit"})).json()
    cs = {r["field"]: r for r in ds}
    assert cs["commission"]["agentReadable"] is False


async def test_patch_doi_co(client_re: httpx.AsyncClient, co_chinh_sach):
    r = await client_re.patch(
        f"{API}/field-policy/unit/commission", json={"agentReadable": True}
    )
    assert r.status_code == 200 and r.json()["agentReadable"] is True


async def test_patch_truong_khong_ton_tai_tra_404(client_re: httpx.AsyncClient, co_chinh_sach):
    r = await client_re.patch(f"{API}/field-policy/unit/khong_co", json={"filterable": True})
    assert r.status_code == 404


async def test_bat_filterable_cho_truong_cam_thi_bi_tu_choi(
    client_re: httpx.AsyncClient, co_chinh_sach
):
    """BR04 + quyết định #17. `floor` có cột để tenant NHẬP, nhưng bật cờ lọc là
    mở lại đường trả sai âm thầm — và API là chỗ chặn, không phải review."""
    r = await client_re.patch(f"{API}/field-policy/unit/floor", json={"filterable": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "FILTER_KHONG_CHO_PHEP"


async def test_bat_filterable_ma_thieu_match_op_bi_tu_choi(
    client_re: httpx.AsyncClient, co_chinh_sach
):
    """`0002` có CHECK `filterable_needs_op`. Bắt trước ở tầng API để lỗi đọc
    được, thay vì để asyncpg ném `CheckViolationError` lên FE."""
    r = await client_re.patch(
        f"{API}/field-policy/unit/commission", json={"filterable": True}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_01"


async def test_data_gaps_rong_khi_chua_chot_n2(client_re: httpx.AsyncClient, co_chinh_sach):
    """Không trường nào `required_for_agent` ⇒ 0, và `truongBatBuoc` rỗng.

    FE phân biệt hai câu: chưa đặt tiêu chí khác 0 căn thiếu dữ liệu. Trả
    tổng số căn ở đây là hiện một cảnh báo sai trên mọi workspace mới.
    """
    g = (await client_re.get(f"{API}/data-gaps", params={"entity": "unit"})).json()
    assert g["soBanGhiThieu"] == 0 and g["truongBatBuoc"] == []


async def test_data_gaps_doi_theo_chinh_sach_khong_can_deploy(
    client_re: httpx.AsyncClient, co_chinh_sach
):
    """CỔNG 9. Đây là test chứng minh N2 không chặn M4a."""
    await client_re.post(f"{API}/projects", json={"code": "P", "name": "P"})
    await client_re.post(f"{API}/units", json={"code": "U1", "projectCode": "P", "priceTy": "5"})
    await client_re.post(f"{API}/units", json={"code": "U2", "projectCode": "P"})

    assert (await client_re.get(f"{API}/data-gaps", params={"entity": "unit"})).json()[
        "soBanGhiThieu"
    ] == 0

    r = await client_re.patch(f"{API}/field-policy/unit/price_vnd", json={"requiredForAgent": True})
    assert r.status_code == 200

    g = (await client_re.get(f"{API}/data-gaps", params={"entity": "unit"})).json()
    assert g["soBanGhiThieu"] == 1 and g["truongBatBuoc"] == ["price_vnd"]


async def test_data_gaps_bo_qua_ten_truong_rac_trong_bang_cau_hinh(
    pool: asyncpg.Pool, client_re: httpx.AsyncClient, co_chinh_sach
):
    """Hàng rào injection. `field_policy_live` là bảng admin workspace ghi được,
    nên tên trường trong đó là ĐẦU VÀO KHÔNG TIN ĐƯỢC. Một hàng rác không được
    làm nổ `/data-gaps`, và tuyệt đối không được ghép vào SQL."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO control.field_policy_live
                   (tenant_id, entity, field, is_core, required_for_agent)
               VALUES ($1, 'unit', 'x; DROP TABLE tenant_data.units', false, true)""",
            co_chinh_sach,
        )
    r = await client_re.get(f"{API}/data-gaps", params={"entity": "unit"})
    assert r.status_code == 200 and r.json()["truongBatBuoc"] == []
    assert await pool.fetchval(
        "SELECT to_regclass('tenant_data.units') IS NOT NULL"
    ), "bảng units đã bị xoá — lỗ injection qua bảng cấu hình"


async def test_patch_ghi_nhat_ky(client_re: httpx.AsyncClient, co_chinh_sach, pool: asyncpg.Pool):
    await client_re.patch(f"{API}/field-policy/unit/commission", json={"agentReadable": True})
    hd = await pool.fetchval(
        "SELECT hanh_dong FROM control.audit_log WHERE tenant_id = 'rew' ORDER BY id DESC LIMIT 1"
    )
    assert hd == "realestate.field_policy.update"
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_chinh_sach_api.py -v`
Expected: FAIL — 404 trên `/field-policy` và `/data-gaps`.

- [ ] **Step 3: Thêm 3 route vào cuối `router.py`**

```python
# ─── Chính sách trường ──────────────────────────────────────────────────────
# Bốn cờ (DL_01 BR01 + BR07). Hai cờ đã có từ `0002`, hai cờ do `0400` thêm.
#
# ĐÂY LÀ CHỖ N2 KHÔNG CHẶN M4a: định nghĩa "đủ dữ liệu cho agent" là DỮ LIỆU
# trong bảng này, không phải hằng số trong code. BA đổi bằng PATCH, không mở
# merge request.

from portal.modules.realestate.chinh_sach import (  # noqa: E402
    COT_PROJECT,
    COT_UNIT,
    KHONG_LOC_DUOC,
    loc_ten_cot,
    menh_de_thieu,
)
from portal.modules.realestate.contracts import (  # noqa: E402
    ChinhSachTruongIn,
    ChinhSachTruongOut,
    GapOut,
)

_CO_JSON_SANG_COT = {
    "formVisible": "form_visible",
    "agentReadable": "agent_readable",
    "filterable": "filterable",
    "matchOp": "match_op",
    "requiredForAgent": "required_for_agent",
}

_COT_THEO_ENTITY = {"project": COT_PROJECT, "unit": COT_UNIT}


def _entity_la() -> loi.LoiPortal:
    return loi.LoiPortal("ER_01", 422, "entity phải là 'project' hoặc 'unit'")


def _ra_chinh_sach(r: asyncpg.Record) -> ChinhSachTruongOut:
    return ChinhSachTruongOut(
        entity=r["entity"], field=r["field"], labelVi=r["label_vi"], type=r["type"],
        isCore=r["is_core"], formVisible=r["form_visible"],
        agentReadable=r["agent_readable"], filterable=r["filterable"],
        matchOp=r["match_op"], requiredForAgent=r["required_for_agent"],
    )


@ROUTER.get("/field-policy", response_model=list[ChinhSachTruongOut])
async def liet_ke_chinh_sach(
    entity: str = Query(""),
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[ChinhSachTruongOut]:
    if entity and entity not in _COT_THEO_ENTITY:
        raise _entity_la()
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.doc_chinh_sach(conn, entity)
    return [_ra_chinh_sach(r) for r in rows]


@ROUTER.patch("/field-policy/{entity}/{field}", response_model=ChinhSachTruongOut)
async def sua_chinh_sach(
    entity: str,
    field: str,
    than: ChinhSachTruongIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChinhSachTruongOut:
    """Bật `filterable` bị chặn ở HAI chỗ, cả hai đều cần thiết.

    (a) `KHONG_LOC_DUOC` — `floor`/`building`/`zone`/`floor_min`/`floor_max`.
        Quyết định #17: bộ lọc theo tầng/toà trả căn tầng bất kỳ và agent đọc
        như thể đúng. "Sai âm thầm tệ hơn trả rỗng."
    (b) Thiếu `match_op` — `0002` có CHECK `filterable_needs_op`. Bắt ở đây để
        người dùng nhận một câu đọc được, không phải `CheckViolationError`.
    """
    if entity not in _COT_THEO_ENTITY:
        raise _entity_la()

    thay_doi = {
        cot: getattr(than, khoa)
        for khoa, cot in _CO_JSON_SANG_COT.items()
        if getattr(than, khoa) is not None
    }
    if not thay_doi:
        raise loi.LoiPortal("ER_01", 422, "Không có cờ nào để cập nhật")

    if thay_doi.get("filterable"):
        if field in KHONG_LOC_DUOC:
            raise loi.LoiPortal(
                "FILTER_KHONG_CHO_PHEP", 422,
                f"Trường {field} chưa có dữ liệu thật nên chưa mở bộ lọc được (BR04)",
            )
        if not (thay_doi.get("match_op") or "").strip():
            raise loi.LoiPortal("ER_01", 422, "Bật bộ lọc thì phải chọn toán tử so khớp")

    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            r = await repo.ghi_chinh_sach(conn, p.tenant_id, entity, field, thay_doi)
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        if r is None:
            raise _khong_thay(f"trường {entity}.{field}")
        await _nhat_ky(
            conn, p, "realestate.field_policy.update",
            {"entity": entity, "field": field, "thay_doi": sorted(thay_doi)},
        )
    return _ra_chinh_sach(r)


@ROUTER.get("/data-gaps", response_model=GapOut)
async def canh_bao_thieu_du_lieu(
    entity: str = Query("unit"),
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> GapOut:
    """BR07 — "N căn chưa đủ dữ liệu cho agent".

    Tên trường đọc từ `field_policy_live`, và bảng đó admin workspace GHI ĐƯỢC.
    Nên nó đi qua `loc_ten_cot()` trước khi tới `menh_de_thieu()` — hai hàng rào,
    vì ghép thẳng là một lỗ injection đi qua đường cấu hình.

    Danh sách rỗng ⇒ 0, không phải "tất cả". FE hiện chưa đặt tiêu chí.
    """
    if entity not in _COT_THEO_ENTITY:
        raise _entity_la()

    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.doc_chinh_sach(conn, entity)
        bat_buoc = loc_ten_cot(
            (r["field"] for r in rows if r["required_for_agent"]), _COT_THEO_ENTITY[entity]
        )
        so = await repo.dem_thieu(conn, entity, menh_de_thieu(bat_buoc))

    return GapOut(entity=entity, soBanGhiThieu=so, truongBatBuoc=bat_buoc)
```

> **Lưu ý cho người thi công:** ba `import` ở đầu đoạn trên phải chuyển lên khối
> import đầu file (`ruff` rule `E402`). Chúng viết ở đây để đoạn code đọc được
> độc lập; `uv run ruff check --fix` sẽ **không** tự chuyển, phải làm tay.

- [ ] **Step 4: Dời import lên đầu file và lint**

```bash
uv run ruff check src/portal/modules/realestate/router.py
```

Expected: nếu còn `E402`, gộp thủ công vào khối `from portal.modules.realestate...`
đã có ở đầu file, rồi chạy lại tới khi sạch.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_chinh_sach_api.py -v`
Expected: PASS — 11 test

- [ ] **Step 6: Chạy toàn bộ test của module**

Run: `make test-module M=realestate`
Expected: PASS, không test nào đỏ. Số test cộng dồn từ T1 đến đây; con số cụ thể
không quan trọng, **có test nào đỏ mới quan trọng**.

- [ ] **Step 7: Commit**

```bash
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/router.py tests/modules/realestate/test_chinh_sach_api.py
git commit -m "feat(m4a): chính sách trường + cảnh báo thiếu dữ liệu — N2 là dữ liệu, không phải code (T8)"
```

---

## Task 9: Import hai bước

**Files:**
- Create: `src/portal/modules/realestate/service.py`
- Modify: `src/portal/modules/realestate/router.py` (thêm 3 route)
- Modify: `src/portal/modules/realestate/repo.py` (thêm 4 hàm `import_jobs`)
- Create: `tests/modules/realestate/test_import.py`

**Interfaces:**
- Consumes: `nhap_lieu.doc_bang` · `chay_thu` · `BaoCaoChayThu` · `LoiFile` (Task 4) ·
  `repo.ma_dang_co` · `ghi_du_an` · `ghi_can` · `xoa_theo_ma` (Task 6) ·
  `contracts.COT_GIA_UNIT` · `ImportJobOut` (Task 6) · `KhoTep.ghi`/`.doc` (M3)
- Produces:
  - `service.chay_thu_import(conn, kho, *, tenant_id, entity, mode, ten_file, noi_dung, user_id) -> tuple[int, BaoCaoChayThu, str]`
    trả `(job_id, bao_cao, file_sha256)`
  - `service.ap_dung_import(conn, kho, *, job_id, file_sha256, xac_nhan_xoa, so_dong_se_xoa, tenant_id) -> BaoCaoChayThu`
  - `service.LoiJobHetHan(Exception)` · `service.LoiXacNhanLech(Exception)`
  - `repo.tao_job` · `repo.doc_job` · `repo.danh_dau_da_ap_dung`
  - `GET /imports/template` · `POST /imports` · `POST /imports/{job_id}/apply`

- [ ] **Step 1: Thêm 3 hàm `import_jobs` vào `repo.py`**

Chèn vào cuối `src/portal/modules/realestate/repo.py`:

```python
# ─── import_jobs ────────────────────────────────────────────────────────────

_COT_JOB = (
    "id, entity, mode, state, s3_key, file_sha256, report, created_at, created_by, "
    "expires_at, applied_at"
)


async def tao_job(
    conn: asyncpg.Connection,
    tenant_id: str,
    *,
    entity: Entity,
    mode: str,
    s3_key: str,
    file_sha256: str,
    report: str,
    created_by: str | None,
    song_phut: int,
) -> asyncpg.Record:
    """`report` là chuỗi JSON đã serialize — asyncpg không tự đổi `dict` sang jsonb.

    `expires_at` tính bằng SQL (`now() + interval`) chứ không bằng Python: đồng
    hồ của app và của DB lệch nhau là job hết hạn sớm hoặc muộn, và cả hai đều
    trông như lỗi ngẫu nhiên.
    """
    return await conn.fetchrow(
        f"""INSERT INTO tenant_data.import_jobs
                (tenant_id, entity, mode, s3_key, file_sha256, report, created_by, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, now() + make_interval(mins => $8))
          RETURNING {_COT_JOB}""",
        tenant_id, entity, mode, s3_key, file_sha256, report, created_by, song_phut,
    )


async def doc_job(conn: asyncpg.Connection, job_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_COT_JOB} FROM tenant_data.import_jobs WHERE id = $1", job_id
    )


async def danh_dau_da_ap_dung(conn: asyncpg.Connection, job_id: int) -> bool:
    """Trả `False` nếu job không còn ở `cho_xac_nhan`.

    Điều kiện `state = 'cho_xac_nhan'` nằm trong `WHERE`, không kiểm bằng Python:
    hai request `apply` cùng lúc thì cái thứ hai phải thua ở tầng DB. Kiểm bằng
    Python rồi UPDATE là một cửa sổ đua, và giá của nó là một file import chạy
    hai lần.
    """
    kq = await conn.execute(
        """UPDATE tenant_data.import_jobs SET state = 'da_ap_dung', applied_at = now()
            WHERE id = $1 AND state = 'cho_xac_nhan' AND expires_at > now()""",
        job_id,
    )
    return kq.endswith(" 1")
```

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/modules/realestate/test_import.py`:

```python
"""Import hai bước. Cổng 5, 6, 7 của spec §9.

BR08: "không bao giờ ghi mà chưa qua bước xem trước. Báo cáo phải hiện số dòng
sẽ XOÁ. Ghi là một giao dịch cả-hoặc-không."
"""

import httpx
import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"

CSV_OK = (
    "code,project_code,unit_type,status,direction,price_ty,area_m2,bedrooms\n"
    "NT2-1408,VOP2,Sky Villa 4PN,available,Đông Nam,5.62,78.4,4\n"
    "NT2-0812,VOP2,Liền kề,booked,Tây Bắc,7,96.0,3\n"
)
CSV_MOT_DONG_HONG = (
    "code,project_code,price_ty\n"
    "U1,VOP2,5.62\n"
    "U2,VOP2,abc\n"
)
CSV_TRUNG_MA = "code,project_code,price_ty\nU1,VOP2,5.62\nU1,VOP2,7\n"


def _file(noi_dung: str, ten: str = "units.csv"):
    return {"file": (ten, noi_dung.encode("utf-8"), "text/csv")}


async def _chay_thu(c: httpx.AsyncClient, noi_dung: str, mode: str = "them_va_cap_nhat", **kw):
    return await c.post(
        f"{API}/imports",
        files=_file(noi_dung, kw.pop("ten", "units.csv")),
        data={"entity": "unit", "mode": mode},
    )


@pytest.fixture
async def co_du_an(client_re: httpx.AsyncClient):
    await client_re.post(f"{API}/projects", json={"code": "VOP2", "name": "Ocean Park 2"})
    return "VOP2"


async def test_chay_thu_khong_ghi_gi(client_re: httpx.AsyncClient, co_du_an):
    """BR08 câu đầu tiên. Đây là test quan trọng nhất của cả task."""
    r = await _chay_thu(client_re, CSV_OK)
    assert r.status_code == 200, r.text
    assert r.json()["baoCao"]["them"] == 2
    assert (await client_re.get(f"{API}/units")).json() == []


async def test_ap_dung_ghi_du_hai_dong(client_re: httpx.AsyncClient, co_du_an):
    j = (await _chay_thu(client_re, CSV_OK)).json()
    r = await client_re.post(
        f"{API}/imports/{j['jobId']}/apply", json={"fileSha256": j["fileSha256"]}
    )
    assert r.status_code == 200, r.text
    ds = (await client_re.get(f"{API}/units")).json()
    assert {u["code"] for u in ds} == {"NT2-1408", "NT2-0812"}
    assert next(u for u in ds if u["code"] == "NT2-1408")["priceVnd"] == 5_620_000_000


async def test_ap_dung_voi_sha_lech_tra_409_va_khong_ghi_gi(
    client_re: httpx.AsyncClient, co_du_an
):
    """CỔNG 5. Không có neo sha thì người dùng xác nhận xoá 3 dòng và hệ ghi
    một file xoá 300 dòng — không có gì bắt được."""
    j = (await _chay_thu(client_re, CSV_OK)).json()
    r = await client_re.post(f"{API}/imports/{j['jobId']}/apply", json={"fileSha256": "0" * 64})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPORT_JOB_STALE"
    assert (await client_re.get(f"{API}/units")).json() == []


async def test_ap_dung_hai_lan_thi_lan_hai_409(client_re: httpx.AsyncClient, co_du_an):
    """Job đã dùng là job không dùng lại được. Cho phép là để một cú bấm hai lần
    chạy import hai lượt — và ở chế độ thay thế thì lượt hai xoá sạch."""
    j = (await _chay_thu(client_re, CSV_OK)).json()
    than = {"fileSha256": j["fileSha256"]}
    assert (await client_re.post(f"{API}/imports/{j['jobId']}/apply", json=than)).status_code == 200
    r = await client_re.post(f"{API}/imports/{j['jobId']}/apply", json=than)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPORT_JOB_STALE"


async def test_mot_dong_loi_thi_khong_dong_nao_duoc_ghi(
    client_re: httpx.AsyncClient, co_du_an
):
    """CỔNG 6 — cả-hoặc-không (BR08 · ER_04). Ghi một nửa là để tenant có một
    quỹ căn nửa cũ nửa mới mà không ai biết nửa nào là nửa nào."""
    j = (await _chay_thu(client_re, CSV_MOT_DONG_HONG)).json()
    assert [d["ma"] for d in j["baoCao"]["loi"]] == ["ER_02"]

    r = await client_re.post(
        f"{API}/imports/{j['jobId']}/apply", json={"fileSha256": j["fileSha256"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_04"
    assert (await client_re.get(f"{API}/units")).json() == []


async def test_trung_ma_trong_file_tra_er_06(client_re: httpx.AsyncClient, co_du_an):
    """CỔNG 7 — BR10, "không tự chọn dòng nào thắng"."""
    j = (await _chay_thu(client_re, CSV_TRUNG_MA)).json()
    assert [d["ma"] for d in j["baoCao"]["loi"]] == ["ER_06"]


async def test_thieu_cot_bat_buoc_tra_er_03(client_re: httpx.AsyncClient, co_du_an):
    r = await _chay_thu(client_re, "project_code,price_ty\nVOP2,5\n")
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_03"
    assert "code" in r.json()["error"]["message"]


async def test_thay_the_toan_bo_hien_so_dong_se_xoa(client_re: httpx.AsyncClient, co_du_an):
    for m in ("CU-01", "CU-02"):
        await client_re.post(f"{API}/units", json={"code": m, "projectCode": "VOP2"})
    j = (await _chay_thu(client_re, CSV_OK, mode="thay_the_toan_bo")).json()
    assert j["baoCao"]["xoa"] == 2
    assert sorted(j["baoCao"]["maSeXoa"]) == ["CU-01", "CU-02"]


async def test_thay_the_toan_bo_doi_xac_nhan_xoa(client_re: httpx.AsyncClient, co_du_an):
    """BR08 — "chế độ Thay thế toàn bộ cần xác nhận riêng". Hai điều kiện, không
    một: checkbox một mình thì người dùng bấm theo quán tính."""
    await client_re.post(f"{API}/units", json={"code": "CU-01", "projectCode": "VOP2"})
    j = (await _chay_thu(client_re, CSV_OK, mode="thay_the_toan_bo")).json()

    r = await client_re.post(
        f"{API}/imports/{j['jobId']}/apply", json={"fileSha256": j["fileSha256"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "CAN_XAC_NHAN_XOA"
    assert len((await client_re.get(f"{API}/units")).json()) == 1


async def test_so_dong_se_xoa_lech_thi_tu_choi(client_re: httpx.AsyncClient, co_du_an):
    """Người dùng xác nhận một CON SỐ, không phải một ý định. Số lệch nghĩa là
    dữ liệu đã đổi giữa hai bước — có người khác vừa thêm căn."""
    await client_re.post(f"{API}/units", json={"code": "CU-01", "projectCode": "VOP2"})
    j = (await _chay_thu(client_re, CSV_OK, mode="thay_the_toan_bo")).json()
    r = await client_re.post(
        f"{API}/imports/{j['jobId']}/apply",
        json={"fileSha256": j["fileSha256"], "xacNhanXoa": True, "soDongSeXoa": 99},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "CAN_XAC_NHAN_XOA"


async def test_thay_the_toan_bo_du_hai_dieu_kien_thi_xoa_that(
    client_re: httpx.AsyncClient, co_du_an
):
    await client_re.post(f"{API}/units", json={"code": "CU-01", "projectCode": "VOP2"})
    j = (await _chay_thu(client_re, CSV_OK, mode="thay_the_toan_bo")).json()
    r = await client_re.post(
        f"{API}/imports/{j['jobId']}/apply",
        json={"fileSha256": j["fileSha256"], "xacNhanXoa": True, "soDongSeXoa": 1},
    )
    assert r.status_code == 200, r.text
    assert {u["code"] for u in (await client_re.get(f"{API}/units")).json()} == {
        "NT2-1408", "NT2-0812"
    }


async def test_file_mau_tai_ve_dung_cot_ma_nhap_lieu_chap_nhan(
    client_re: httpx.AsyncClient, co_du_an
):
    """File mẫu SINH từ cùng danh sách cột mà `chay_thu` chấp nhận, không phải
    một file tĩnh commit vào repo — file tĩnh lệch schema ngay lần thêm cột đầu."""
    r = await client_re.get(f"{API}/imports/template", params={"entity": "unit"})
    assert r.status_code == 200
    header = r.text.splitlines()[0]
    assert "code" in header and "price_ty" in header
    assert "price_vnd" not in header, "file mẫu phải nhập bằng TỶ, không phải VND"

    j = (await _chay_thu(client_re, r.text + "U9,VOP2\n")).json()
    assert not j["baoCao"]["loi"]


async def test_import_ghi_nhat_ky(client_re: httpx.AsyncClient, co_du_an, pool):
    j = (await _chay_thu(client_re, CSV_OK)).json()
    await client_re.post(f"{API}/imports/{j['jobId']}/apply", json={"fileSha256": j["fileSha256"]})
    hd = [
        r["hanh_dong"]
        for r in await pool.fetch(
            "SELECT hanh_dong FROM control.audit_log WHERE tenant_id='rew' ORDER BY id"
        )
    ]
    assert "realestate.import.dry_run" in hd and "realestate.import.apply" in hd
```

- [ ] **Step 3: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_import.py -v`
Expected: FAIL — 404 trên `/imports`.

- [ ] **Step 4: Viết `service.py`**

```python
"""Điều phối import hai bước — chỗ DUY NHẤT của M4a có `service.py`.

CRUD không đi qua đây: router gọi thẳng `repo`, đúng nếp `modules/kb/router.py`.
Một lớp service chỉ chuyển tiếp lời gọi là một chỗ để lệch nhau. Import thì khác
— nó ghép ba thứ (kho tệp · hàm thuần · DB) và có một luật nghiệp vụ thật
(cả-hoặc-không), nên nó đáng một file.

RANH GIỚI VỚI `nhap_lieu.py`: file kia thuần, không biết Postgres tồn tại. File
này đọc `ma_dang_co` từ DB rồi TRUYỀN VÀO. Nhờ vậy 12 biến thể file hỏng test
được trong vài trăm mili-giây, còn ở đây chỉ còn phần cần DB thật.
"""

import hashlib
import json
from typing import Literal

import asyncpg

from portal.core.storage import KhoTep
from portal.modules.realestate import repo
from portal.modules.realestate.contracts import COT_GIA_PROJECT, COT_GIA_UNIT
from portal.modules.realestate.chinh_sach import COT_PROJECT, COT_UNIT
from portal.modules.realestate.nhap_lieu import BaoCaoChayThu, chay_thu, doc_bang

Entity = Literal["project", "unit"]

SONG_PHUT = 30
"""Job sống 30 phút. Đủ cho người dùng đọc báo cáo 500 dòng lỗi và quyết định;
đủ ngắn để một file bị bỏ quên không nằm trong kho tệp cả tuần.

Job quá hạn KHÔNG tự dọn ở M4a — xem §11 của spec."""

COT_BAT_BUOC: dict[str, tuple[str, ...]] = {
    "project": ("code",),
    "unit": ("code", "project_code"),
}
"""Căn phải có dự án: một căn không thuộc dự án nào thì `agent_api.units` lọc nó
ra bằng mệnh đề EXISTS (BR11) và nó biến mất khỏi mắt agent mà không báo gì."""

_COT_GIA: dict[str, dict[str, str]] = {"project": COT_GIA_PROJECT, "unit": COT_GIA_UNIT}
_COT_THAT: dict[str, frozenset[str]] = {"project": COT_PROJECT, "unit": COT_UNIT}


class LoiJobHetHan(Exception):
    """Job không tồn tại · hết hạn · đã áp dụng · sha lệch. MỘT lỗi cho cả bốn."""


class LoiXacNhanLech(Exception):
    """Chế độ thay thế mà thiếu xác nhận, hoặc số dòng xoá không khớp báo cáo."""


class LoiConLoi(Exception):
    """Báo cáo còn dòng lỗi ⇒ không ghi gì (ER_04, cả-hoặc-không)."""


def cot_file(entity: Entity) -> tuple[str, ...]:
    """Danh sách cột file import chấp nhận, theo thứ tự ổn định.

    Cột giá xuất hiện với hậu tố `_ty` (đơn vị NHẬP), không phải `_vnd`. File mẫu
    và `chay_thu` dùng chung hàm này — một chỗ, nên không lệch nhau được.
    """
    gia = _COT_GIA[entity]
    vnd_can_bo = set(gia.values())
    thuong = sorted(c for c in _COT_THAT[entity] if c not in vnd_can_bo)
    # `code` luôn đứng đầu: nó là định danh, và người mở file bằng Excel đọc cột
    # đầu tiên trước.
    thuong.remove("code")
    return ("code", *thuong, *sorted(gia))


async def chay_thu_import(
    conn: asyncpg.Connection,
    kho: KhoTep,
    *,
    tenant_id: str,
    entity: Entity,
    mode: str,
    ten_file: str,
    noi_dung: bytes,
    user_id: str | None,
) -> tuple[int, BaoCaoChayThu, str]:
    """Bước ①. Lưu file, tính báo cáo, tạo job. KHÔNG ghi vào projects/units.

    Lưu file TRƯỚC khi tạo hàng job: hàng trỏ tới một `s3_key` không tồn tại là
    một job không bao giờ áp dụng được, và nó đứng mãi ở chờ xác nhận. Cùng
    thứ tự với `modules/kb/router.py`.
    """
    sha = hashlib.sha256(noi_dung).hexdigest()
    hang = doc_bang(noi_dung, ten_file)  # raise LoiFile ⇒ router dịch sang ER_03

    bao_cao = chay_thu(
        hang,
        cot_bat_buoc=COT_BAT_BUOC[entity],
        cot_hop_le=cot_file(entity),
        cot_gia=_COT_GIA[entity],
        ma_dang_co=await repo.ma_dang_co(conn, entity),
        mode=mode,  # type: ignore[arg-type]
    )

    s3_key = f"tenants/{tenant_id}/imports/{sha}/{ten_file}"
    await kho.ghi(s3_key, noi_dung)

    job = await repo.tao_job(
        conn, tenant_id,
        entity=entity, mode=mode, s3_key=s3_key, file_sha256=sha,
        report=json.dumps(bao_cao.to_json(), ensure_ascii=False),
        created_by=user_id, song_phut=SONG_PHUT,
    )
    return job["id"], bao_cao, sha


async def ap_dung_import(
    conn: asyncpg.Connection,
    kho: KhoTep,
    *,
    tenant_id: str,
    job_id: int,
    file_sha256: str,
    xac_nhan_xoa: bool,
    so_dong_se_xoa: int | None,
) -> BaoCaoChayThu:
    """Bước ②. Đọc lại file từ kho, chạy thử LẠI, rồi ghi trong MỘT giao dịch.

    VÌ SAO CHẠY THỬ LẠI THAY VÌ DÙNG `report` ĐÃ LƯU: `report` chỉ có số đếm và
    danh sách mã, không có payload từng dòng — lưu cả payload là nhân đôi dữ liệu
    và tạo chỗ để nó lệch với file. Đọc lại từ kho thì file là nguồn sự thật duy
    nhất, và sha đã chứng minh nó không đổi.

    Hệ quả: `ma_dang_co` đọc lại lúc này, nên `so_dong_se_xoa` có thể khác báo
    cáo cũ — và đó CHÍNH LÀ điều kiện phải kiểm, xem bên dưới.
    """
    job = await repo.doc_job(conn, job_id)
    if job is None or job["state"] != "cho_xac_nhan" or job["file_sha256"] != file_sha256:
        raise LoiJobHetHan

    noi_dung = await kho.doc(job["s3_key"])
    entity: Entity = job["entity"]
    bao_cao = chay_thu(
        doc_bang(noi_dung, job["s3_key"]),
        cot_bat_buoc=COT_BAT_BUOC[entity],
        cot_hop_le=cot_file(entity),
        cot_gia=_COT_GIA[entity],
        ma_dang_co=await repo.ma_dang_co(conn, entity),
        mode=job["mode"],
    )

    if bao_cao.loi:
        raise LoiConLoi

    if job["mode"] == "thay_the_toan_bo" and bao_cao.so_dong_se_xoa:
        # HAI điều kiện. Checkbox một mình thì người dùng bấm theo quán tính;
        # con số một mình thì FE gửi lại được con số nó vừa đọc. Cùng nhau,
        # người dùng phải đã nhìn thấy số dòng sẽ mất.
        if not xac_nhan_xoa or so_dong_se_xoa != bao_cao.so_dong_se_xoa:
            raise LoiXacNhanLech

    # `danh_dau_da_ap_dung` TRƯỚC khi ghi: điều kiện `state='cho_xac_nhan'` nằm
    # trong WHERE nên hai request đồng thời thì cái thứ hai thua ở tầng DB. Cùng
    # giao dịch, nên nó lùi lại nếu phần ghi hỏng.
    if not await repo.danh_dau_da_ap_dung(conn, job_id):
        raise LoiJobHetHan

    ghi = repo.ghi_du_an if entity == "project" else repo.ghi_can
    for payload in (*bao_cao.them, *bao_cao.sua):
        ma = payload.pop("code")
        await ghi(conn, tenant_id, ma, payload)

    if bao_cao.xoa:
        await repo.xoa_theo_ma(conn, entity, bao_cao.xoa)

    return bao_cao
```

> **`code` bị `pop` khỏi payload** vì `repo._kiem_payload` từ chối nó (khoá đi
> bằng tham số riêng). `bao_cao.them`/`sua` là `dict` mới do `_dung_payload` dựng,
> nên `pop` không hỏng dữ liệu của ai.

- [ ] **Step 5: Thêm 3 route vào cuối `router.py`**

```python
# ─── Import hai bước ────────────────────────────────────────────────────────
# BR08: "không bao giờ ghi mà chưa qua bước xem trước."
#
# Neo của luồng là `file_sha256`: bước ② gửi lại, lệch ⇒ 409. Không có nó thì
# người dùng xác nhận xoá 3 dòng và hệ ghi một file xoá 300 dòng.

import io  # noqa: E402
import csv as _csv  # noqa: E402

from fastapi import File, Form, UploadFile  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402

from portal.modules.realestate import service  # noqa: E402
from portal.modules.realestate.contracts import (  # noqa: E402
    MODE,
    BaoCaoImportOut,
    DongLoiOut,
    ImportJobOut,
)
from portal.modules.realestate.nhap_lieu import BaoCaoChayThu, LoiFile  # noqa: E402

_FILE_IMPORT = File(...)
_FORM_ENTITY = Form(...)
_FORM_MODE = Form("them_va_cap_nhat")
"""Singleton mức module — `File(...)`/`Form(...)` gọi thẳng trong default là B008
của ruff. Cùng lý do `_FILE` ở `modules/kb/router.py`."""

GIOI_HAN_IMPORT_BYTE = 10 * 1024 * 1024
"""⚠️ CON SỐ TẠM. DL_01 không chốt ngưỡng cho file import. 10 MB đủ cho ~50.000
dòng CSV và đủ nhỏ để một lần upload không giữ request quá lâu. Chốt thật thì
sửa ở đây — một chỗ."""


def _job_het_han() -> loi.LoiPortal:
    """MỘT mã cho bốn tình huống (không tồn tại · hết hạn · đã áp dụng · sha
    lệch). Phân biệt chúng cho không một máy dò job id của tenant khác — cùng
    lý do `sai_dang_nhap()` của M2a gộp ba tình huống."""
    return loi.LoiPortal(
        "IMPORT_JOB_STALE", 409,
        "Phiên import không còn hiệu lực. Hãy tải lại file và xem trước lần nữa",
    )


def _ra_bao_cao(bc: BaoCaoChayThu) -> BaoCaoImportOut:
    return BaoCaoImportOut(
        them=len(bc.them), sua=len(bc.sua), xoa=bc.so_dong_se_xoa, maSeXoa=bc.xoa,
        loi=[DongLoiOut(dong=d.dong, ma=d.ma, lyDo=d.ly_do) for d in bc.loi],
    )


@ROUTER.get("/imports/template", response_class=PlainTextResponse)
async def file_mau(
    entity: str = Query("unit"),
    p: Principal = require(ACTIONS.CATALOG_READ),
) -> str:
    """Sinh từ cùng danh sách cột `chay_thu()` chấp nhận (`service.cot_file`).

    Không commit một file tĩnh vào repo: nó lệch schema ngay lần thêm cột đầu
    tiên, và người dùng chỉ biết khi import báo thiếu cột.
    """
    if entity not in ("project", "unit"):
        raise _entity_la()
    dem = io.StringIO()
    _csv.writer(dem).writerow(service.cot_file(entity))  # type: ignore[arg-type]
    return dem.getvalue()


@ROUTER.post("/imports", response_model=ImportJobOut)
async def chay_thu_import(
    file: UploadFile = _FILE_IMPORT,
    entity: str = _FORM_ENTITY,
    mode: str = _FORM_MODE,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ImportJobOut:
    """Bước ①. 200, không 201: chưa tài nguyên nghiệp vụ nào được tạo — job chỉ
    là một phiếu giữ chỗ, và trả 201 làm FE tưởng dữ liệu đã vào."""
    from portal.core.storage import kho_tep_tu_cai_dat

    if entity not in ("project", "unit"):
        raise _entity_la()
    if mode not in MODE:
        raise loi.LoiPortal("ER_01", 422, f"mode phải là một trong {MODE}")

    noi_dung = await file.read()
    if not noi_dung:
        raise loi.LoiPortal("ER_03", 422, "File rỗng")
    if len(noi_dung) > GIOI_HAN_IMPORT_BYTE:
        raise loi.LoiPortal("FILE_TOO_LARGE", 422, "File vượt dung lượng cho phép")

    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            job_id, bc, sha = await service.chay_thu_import(
                conn, kho_tep_tu_cai_dat(),
                tenant_id=p.tenant_id, entity=entity, mode=mode,
                ten_file=file.filename or "import.csv", noi_dung=noi_dung, user_id=p.user_id,
            )
        except LoiFile as e:
            raise loi.LoiPortal("ER_03", 422, str(e)) from e
        job = await repo.doc_job(conn, job_id)
        await _nhat_ky(
            conn, p, "realestate.import.dry_run",
            {"job_id": job_id, "entity": entity, "mode": mode, "bao_cao": bc.to_json()},
        )

    return ImportJobOut(
        jobId=job_id, entity=entity, mode=mode, state="cho_xac_nhan",
        fileSha256=sha, baoCao=_ra_bao_cao(bc), expiresAt=job["expires_at"],
    )


@ROUTER.post("/imports/{job_id}/apply", response_model=BaoCaoImportOut)
async def ap_dung_import(
    job_id: int,
    than: dict,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> BaoCaoImportOut:
    """Bước ②. Cả-hoặc-không: `tenant_conn()` mở một giao dịch, và mọi `raise`
    trong khối này làm nó lùi lại toàn bộ."""
    from portal.core.storage import kho_tep_tu_cai_dat

    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            bc = await service.ap_dung_import(
                conn, kho_tep_tu_cai_dat(),
                tenant_id=p.tenant_id, job_id=job_id,
                file_sha256=str(than.get("fileSha256") or ""),
                xac_nhan_xoa=bool(than.get("xacNhanXoa")),
                so_dong_se_xoa=than.get("soDongSeXoa"),
            )
        except service.LoiJobHetHan as e:
            raise _job_het_han() from e
        except service.LoiConLoi as e:
            raise loi.LoiPortal(
                "ER_04", 422, "File còn dòng lỗi. Không dòng nào được ghi"
            ) from e
        except service.LoiXacNhanLech as e:
            raise loi.LoiPortal(
                "CAN_XAC_NHAN_XOA", 422,
                "Chế độ Thay thế toàn bộ cần xác nhận số bản ghi sẽ bị xoá",
            ) from e
        except LoiTruongLa as e:
            raise _truong_la(e) from e
        await _nhat_ky(
            conn, p, "realestate.import.apply", {"job_id": job_id, "bao_cao": bc.to_json()}
        )
    return _ra_bao_cao(bc)
```

> **Dời mọi `import` lên đầu file** (ruff `E402`), giống Task 8 Step 4.

- [ ] **Step 6: Dời import, lint, chạy test**

```bash
uv run ruff check src/portal/modules/realestate/router.py
uv run pytest tests/modules/realestate/test_import.py -v
```

Expected: lint sạch; test PASS — 13 test

- [ ] **Step 7: Chạy toàn bộ module**

Run: `make test-module M=realestate`
Expected: PASS, không test nào đỏ.

- [ ] **Step 8: Commit**

```bash
uv run ruff format src/portal/modules/realestate tests/modules/realestate
git add src/portal/modules/realestate/service.py src/portal/modules/realestate/router.py \
        src/portal/modules/realestate/repo.py tests/modules/realestate/test_import.py
git commit -m "feat(m4a): import hai bước — neo bằng file_sha256, cả-hoặc-không (T9)"
```

---

## Task 10: `seed_bds.py` — bộ trường mẫu Bất động sản

**Files:**
- Create: `scripts/seed_bds.py`
- Modify: `Makefile` (thêm target `seed-bds`, thêm vào `up`)
- Create: `tests/modules/realestate/test_seed_bds.py`

**Interfaces:**
- Consumes: `chinh_sach.COT_PROJECT` · `COT_UNIT` · `GATED` · `KHONG_LOC_DUOC` (Task 5)
  · `gia.doi_don_vi_gia` (Task 1)
- Produces: `seed_bds.BO_TRUONG_MAU: dict[str, list[TruongMau]]` · `seed_bds.seed(conn, tenant_id)`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_seed_bds.py`:

```python
"""Bộ trường mẫu Bất động sản — 56 hàng `field_policy_live`.

ĐÂY LÀ CHỖ ĐẶT MẶC ĐỊNH CỦA PLATFORM (DL_01 BR01: "mặc định do platform đặt
theo bộ trường mẫu của lĩnh vực"). BA đè lên bằng PATCH /field-policy, không
bằng merge request.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def da_seed(pool: asyncpg.Pool, workspace_re: str):
    from scripts.seed_bds import seed

    async with pool.acquire() as conn, conn.transaction():
        await seed(conn, workspace_re)
    return workspace_re


async def test_seed_du_56_hang(pool: asyncpg.Pool, da_seed: str):
    """16 trường dự án + 40 trường căn. Lệch nghĩa là `BO_TRUONG_MAU` và
    `chinh_sach.COT_*` đã rời nhau."""
    assert await pool.fetchval(
        "SELECT count(*) FROM control.field_policy_live WHERE tenant_id = $1", da_seed
    ) == 56


async def test_seed_phu_dung_danh_sach_trang(pool: asyncpg.Pool, da_seed: str):
    """QUÉT ĐỘNG. Thiếu một trường ⇒ trường đó không khai chính sách được, và nó
    im lặng — người dùng chỉ thấy một ô trên form không có nhãn Agent dùng."""
    from portal.modules.realestate.chinh_sach import COT_PROJECT, COT_UNIT

    for entity, mong_doi in (("project", COT_PROJECT), ("unit", COT_UNIT)):
        co = {
            r["field"]
            for r in await pool.fetch(
                "SELECT field FROM control.field_policy_live WHERE tenant_id=$1 AND entity=$2",
                da_seed, entity,
            )
        }
        assert co == set(mong_doi), f"{entity}: thiếu {sorted(set(mong_doi) - co)}"


async def test_ba_truong_thuong_mai_seed_agent_khong_doc(pool: asyncpg.Pool, da_seed: str):
    """BR09. Fail-closed: chưa ai bật thì không lộ."""
    for f in ("commission", "bank_support", "csbh_full"):
        assert await pool.fetchval(
            """SELECT agent_readable FROM control.field_policy_live
                WHERE tenant_id=$1 AND entity='unit' AND field=$2""",
            da_seed, f,
        ) is False


async def test_nam_truong_cam_loc_seed_filterable_false(pool: asyncpg.Pool, da_seed: str):
    """BR04 + quyết định #17."""
    from portal.modules.realestate.chinh_sach import KHONG_LOC_DUOC

    for f in KHONG_LOC_DUOC:
        assert await pool.fetchval(
            """SELECT filterable FROM control.field_policy_live
                WHERE tenant_id=$1 AND entity='unit' AND field=$2""",
            da_seed, f,
        ) is False


async def test_moi_truong_filterable_deu_co_match_op(pool: asyncpg.Pool, da_seed: str):
    """`0002` có CHECK `filterable_needs_op`, nên seed thiếu op thì migration
    ném CheckViolation. Test này làm lỗi đó đọc được."""
    xau = await pool.fetch(
        """SELECT entity, field FROM control.field_policy_live
            WHERE tenant_id=$1 AND filterable AND match_op IS NULL""",
        da_seed,
    )
    assert not xau, f"filterable nhưng thiếu match_op: {[dict(r) for r in xau]}"


async def test_seed_chay_lai_khong_nhan_doi(pool: asyncpg.Pool, da_seed: str):
    """Idempotent — `make up` chạy được nhiều lần. Không idempotent thì lần thứ
    hai nổ vì trùng khoá chính, và người mới clone repo tưởng repo hỏng."""
    from scripts.seed_bds import seed

    async with pool.acquire() as conn, conn.transaction():
        await seed(conn, da_seed)
    assert await pool.fetchval(
        "SELECT count(*) FROM control.field_policy_live WHERE tenant_id=$1", da_seed
    ) == 56


async def test_seed_khong_de_len_thay_doi_cua_tenant(pool: asyncpg.Pool, da_seed: str):
    """Chạy lại seed KHÔNG được ghi đè cờ tenant đã sửa — nếu không thì mỗi lần
    deploy lại là một lần hoa hồng bật lại theo mặc định."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE control.field_policy_live SET agent_readable = true
                WHERE tenant_id=$1 AND entity='unit' AND field='commission'""",
            da_seed,
        )
    from scripts.seed_bds import seed

    async with pool.acquire() as conn, conn.transaction():
        await seed(conn, da_seed)
    assert await pool.fetchval(
        """SELECT agent_readable FROM control.field_policy_live
            WHERE tenant_id=$1 AND entity='unit' AND field='commission'""",
        da_seed,
    ) is True


async def test_khong_truong_nao_required_for_agent(pool: asyncpg.Pool, da_seed: str):
    """N2 CHƯA CHỐT (DL_01 TODO). Seed một danh sách đoán là hiện cảnh báo N căn
    chưa đủ dữ liệu dựa trên một tiêu chí không ai duyệt — tệ hơn không hiện."""
    assert await pool.fetchval(
        "SELECT count(*) FROM control.field_policy_live WHERE tenant_id=$1 AND required_for_agent",
        da_seed,
    ) == 0
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_seed_bds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.seed_bds'`

- [ ] **Step 3: Viết `scripts/seed_bds.py`**

```python
"""Bộ trường mẫu Bất động sản — mặc định của PLATFORM, không của tenant.

DL_01 BR01: "mặc định do platform đặt theo bộ trường mẫu của lĩnh vực". Đây là
bộ đó. Tenant (hoặc BA) đè lên bằng `PATCH /field-policy` — không bằng merge
request, vì chốt ba cờ cho từng trường là việc của BA cùng sales.

BA LUẬT CỦA FILE NÀY:

1. IDEMPOTENT, VÀ KHÔNG ĐÈ THAY ĐỔI CỦA TENANT. `ON CONFLICT DO NOTHING`, không
   `DO UPDATE`. Đè là mỗi lần deploy lại một lần hoa hồng bật lại theo mặc định.

2. `required_for_agent` ĐỂ TRỐNG HẾT. N2 chưa chốt (DL_01 TODO). Seed một danh
   sách đoán là hiện cảnh báo N căn chưa đủ dữ liệu theo một tiêu chí không ai
   duyệt — tệ hơn không hiện.

3. `filterable` CHỈ BẬT CHO TRƯỜNG CÓ DỮ LIỆU THẬT (BR04). Năm trường
   `KHONG_LOC_DUOC` để `false` — xem quyết định #17.

Chạy: make seed-bds   (sau make migrate)
"""

import asyncio
import sys
from urllib.parse import urlparse

import asyncpg

from portal.core.config import get_settings
from portal.modules.realestate.chinh_sach import (
    COT_PROJECT,
    COT_UNIT,
    GATED,
    KHONG_LOC_DUOC,
)

VERTICAL = "bds"

_LOC_DUOC: dict[str, tuple[str, str]] = {
    # field: (match_op, type)
    "unit_type": ("eq", "text"),
    "status": ("eq", "enum"),
    "direction": ("eq", "text"),
    "fund_type": ("eq", "text"),
    "project_code": ("eq", "text"),
    "code": ("eq", "text"),
    "price_vnd": ("lte", "money"),
    "area_m2": ("gte", "number"),
    "bedrooms": ("gte", "number"),
    "region": ("eq", "text"),
    "type": ("eq", "text"),
}
"""Sáu bộ lọc `nbx_mongo.search_units` thật sự đọc, cộng bốn bộ lọc dự án.

KHỚP ĐÚNG cái agent làm được hôm nay — không nhiều hơn. Khai một bộ lọc mà tầng
dưới không đọc chính là bug `floor`/`tower` của quyết định #17: khách hỏi tầng
14, hệ trả căn bất kỳ, agent đọc như thể đúng."""

_KIEU_SO = frozenset(
    {
        "price_vnd", "price_tts_vnd", "price_tttd_vnd", "price_loan_vnd",
        "area_m2", "area_build_m2", "bedrooms", "bathrooms", "floor",
        "floor_min", "floor_max", "sort_order", "sort_hot", "hot_sort", "lat", "lng",
    }
)
_KIEU_BOOL = frozenset({"is_hot", "is_featured", "is_active", "agent_enabled"})

NHAN_VI: dict[str, str] = {
    "code": "Mã", "name": "Tên dự án", "slug": "Slug", "type": "Loại hình",
    "region": "Miền", "location": "Vị trí", "investor": "Chủ đầu tư",
    "parent_code": "Dự án mẹ", "status": "Trạng thái", "is_hot": "Đẩy quỹ hot",
    "is_featured": "Dự án nổi bật", "sort_hot": "Thứ tự hot", "sort_order": "Thứ tự",
    "agent_enabled": "Agent dùng", "lat": "Vĩ độ", "lng": "Kinh độ",
    "project_code": "Dự án", "unit_type": "Loại hình căn", "direction": "Hướng",
    "zone": "Phân khu", "building": "Toà", "floor": "Tầng", "bedrooms": "Số phòng ngủ",
    "bathrooms": "Số WC", "price_vnd": "Giá Full VAT", "price_tts_vnd": "Giá TTS",
    "price_tttd_vnd": "Giá TTTĐ", "price_loan_vnd": "Giá vay", "price_label": "Nhãn giá",
    "loan_info": "Thông tin vay", "area_m2": "Diện tích đất",
    "area_build_m2": "Diện tích xây", "fund_type": "Loại quỹ", "hot_sort": "Thứ tự hot",
    "commission": "Hoa hồng", "bank_support": "Hỗ trợ ngân hàng",
    "csbh_full": "CSBH đầy đủ", "csbh_brief": "CSBH tóm tắt", "gift": "Quà tặng",
    "legal": "Pháp lý", "delivery_standard": "Tiêu chuẩn bàn giao",
    "floor_min": "Tầng nhỏ nhất", "floor_max": "Tầng lớn nhất", "axis": "Trục căn",
    "front": "Mặt tiền", "description": "Mô tả", "check_time": "Thời điểm check",
    "is_active": "Hiển thị public", "sale_email": "Người phụ trách",
}
"""Nhãn tiếng Việt lấy từ prototype `pform`/`uform`. Thiếu nhãn thì `label_vi`
rơi về chính tên cột — form hiện price_tttd_vnd cho người nhập liệu."""


def _hang(entity: str, field: str) -> dict:
    loc = _LOC_DUOC.get(field) if entity == "unit" or field in _LOC_DUOC else None
    if entity == "project" and field not in ("region", "type", "code"):
        loc = None
    kieu = (
        loc[1] if loc
        else "number" if field in _KIEU_SO
        else "boolean" if field in _KIEU_BOOL
        else "text"
    )
    return {
        "entity": entity,
        "field": field,
        "label_vi": NHAN_VI.get(field, field),
        "type": kieu,
        "is_core": True,
        "form_visible": True,
        # Mặc định agent ĐỌC ĐƯỢC, trừ ba trường thương mại. Ngược lại với
        # `filterable` — đọc thừa một trường là tốn token, lọc sai một trường là
        # trả lời sai. Hai rủi ro khác hạng nên hai mặc định khác nhau.
        "agent_readable": field not in GATED,
        "filterable": bool(loc) and field not in KHONG_LOC_DUOC,
        "match_op": loc[0] if loc and field not in KHONG_LOC_DUOC else None,
        "required_for_agent": False,  # N2 chưa chốt — xem docstring
    }


BO_TRUONG_MAU: dict[str, list[dict]] = {
    "project": [_hang("project", f) for f in sorted(COT_PROJECT)],
    "unit": [_hang("unit", f) for f in sorted(COT_UNIT)],
}


async def seed(conn: asyncpg.Connection, tenant_id: str) -> int:
    """Ghi bộ trường mẫu cho một tenant. Trả số hàng ĐÃ THÊM (0 nếu đã có đủ)."""
    them = 0
    for entity, hang in BO_TRUONG_MAU.items():
        for h in hang:
            kq = await conn.execute(
                """INSERT INTO control.field_policy_live
                       (tenant_id, entity, field, label_vi, type, is_core, form_visible,
                        agent_readable, filterable, match_op, required_for_agent)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (tenant_id, entity, field) DO NOTHING""",
                tenant_id, entity, h["field"], h["label_vi"], h["type"], h["is_core"],
                h["form_visible"], h["agent_readable"], h["filterable"], h["match_op"],
                h["required_for_agent"],
            )
            them += int(kq.endswith(" 1"))
    return them


async def _main() -> None:
    """CHỈ CHẠY TRÊN CONTAINER DEV — cùng rào chắn `scripts/dev_seed.py`."""
    dsn = get_settings().database_url
    host = urlparse(dsn).hostname or ""
    if host not in ("localhost", "127.0.0.1", "postgres"):
        sys.exit(f"từ chối chạy: DSN trỏ {host!r}, không phải container dev")

    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            ids = [r["id"] for r in await conn.fetch("SELECT id FROM control.tenants")]
            for t in ids:
                n = await seed(conn, t)
                print(f"  {t}: thêm {n} hàng chính sách trường")
        print(f"xong — {len(ids)} workspace, vertical {VERTICAL}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_seed_bds.py -v`
Expected: PASS — 8 test

Nếu `test_seed_du_56_hang` đỏ với một con số khác 56: **đừng sửa con số trong
test.** Chạy `test_seed_phu_dung_danh_sach_trang` trước — nó nói thiếu/thừa
trường nào, và `chinh_sach.COT_*` mới là nguồn sự thật.

- [ ] **Step 5: Thêm target vào `Makefile`**

Sửa `Makefile` — thêm sau target `seed-kho-tep`:

```makefile
seed-bds:      ## bộ trường mẫu Bất động sản cho mọi workspace (CHỈ localhost)
	uv run python -m scripts.seed_bds
```

và sửa dòng `up`:

```makefile
up: dev migrate grant-api-dev dev-seed seed-kho-tep seed-bds   ## dựng tất cả từ số 0
```

Thêm `seed-bds` vào dòng `.PHONY` ở đầu file.

- [ ] **Step 6: Dựng lại từ số 0, xác nhận chạy sạch**

```bash
make reset && make up
```

Expected: thoát mã 0, in `xong — 3 workspace, vertical bds`.

- [ ] **Step 7: Lint và commit**

```bash
uv run ruff check scripts/seed_bds.py tests/modules/realestate
uv run ruff format scripts/seed_bds.py tests/modules/realestate
git add scripts/seed_bds.py tests/modules/realestate/test_seed_bds.py Makefile
git commit -m "feat(m4a): seed bộ trường mẫu BĐS — 56 hàng, không đè thay đổi của tenant (T10)"
```

---

## Task 11: Ba cổng quét động

> Ba cổng cuối của spec §9. Chúng khác mọi test đã viết ở một điểm: chúng không
> chứng minh code hôm nay đúng, mà **bắt được người sửa code sáu tháng nữa**.
> Cổng 4 và 10 đã nằm trong Task 2/5; task này viết cổng 8 và 11.

**Files:**
- Create: `tests/modules/realestate/test_bo_loc_co_du_lieu.py`
- Create: `tests/modules/realestate/test_nhat_ky_day_du.py`
- Modify: `docs/contracts/isolation.md` (khai 4 bảng mới vào catalog §6.0)
- Modify: `docs/superpowers/specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md` (§7 — thêm G-11, G-12)

**Interfaces:**
- Consumes: `chinh_sach.KHONG_LOC_DUOC` · `COT_UNIT` · `COT_PROJECT` (Task 5) ·
  `portal.api.app.create_app` · `KhaiQuyen` (core)
- Produces: không gì cho task sau — đây là task cuối.

- [ ] **Step 1: Viết cổng 8 — bộ lọc phải có dữ liệu**

Tạo `tests/modules/realestate/test_bo_loc_co_du_lieu.py`:

```python
"""CỔNG 8 (spec §9) — quét động. BR04 + quyết định #17.

Cái này bắt được thứ mà review không bắt được: ai đó sáu tháng nữa bật
`filterable` cho `floor` vì "khách hay hỏi tầng", và mọi test khác vẫn xanh.

Nhắc lại vì sao nó nghiêm trọng: `schemas.py` khai filter cho LLM, tầng dưới
không đọc, khách hỏi căn tầng 14 → hệ trả căn tầng bất kỳ → agent đọc như thể
đúng tầng. "Sai âm thầm tệ hơn trả rỗng" — khách đi xem căn rồi mới biết.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def test_moi_truong_filterable_deu_la_cot_that(pool: asyncpg.Pool, workspace_re: str):
    """Bật lọc cho một trường không có cột là một mệnh đề WHERE nổ lúc chạy."""
    from portal.modules.realestate.chinh_sach import COT_PROJECT, COT_UNIT

    from scripts.seed_bds import seed

    async with pool.acquire() as conn, conn.transaction():
        await seed(conn, workspace_re)

    hop_le = {"project": COT_PROJECT, "unit": COT_UNIT}
    xau = [
        (r["entity"], r["field"])
        for r in await pool.fetch(
            "SELECT entity, field FROM control.field_policy_live WHERE tenant_id=$1 AND filterable",
            workspace_re,
        )
        if r["field"] not in hop_le.get(r["entity"], frozenset())
    ]
    assert not xau, f"filterable nhưng không phải cột thật: {xau}"


async def test_nam_truong_cam_loc_khong_bao_gio_filterable(
    pool: asyncpg.Pool, workspace_re: str
):
    from portal.modules.realestate.chinh_sach import KHONG_LOC_DUOC
    from scripts.seed_bds import seed

    async with pool.acquire() as conn, conn.transaction():
        await seed(conn, workspace_re)

    bat = await pool.fetch(
        """SELECT field FROM control.field_policy_live
            WHERE tenant_id=$1 AND filterable AND field = ANY($2::text[])""",
        workspace_re, list(KHONG_LOC_DUOC),
    )
    assert not bat, (
        f"quyết định #17 bị đảo ngược cho: {[r['field'] for r in bat]}. "
        "Muốn mở thì phải có dữ liệu thật TRƯỚC — xem DL_01 BR04."
    )


def test_repo_khong_nhan_bo_loc_theo_tang_hay_toa():
    """Quét CHỮ KÝ HÀM, không quét hành vi. Thêm `floor=` vào `liet_ke_can` là
    mở lại đường cũ, và một test hành vi sẽ không bắt được nếu người thêm cũng
    thêm luôn test cho nó."""
    import inspect

    from portal.modules.realestate import repo

    tham_so = set(inspect.signature(repo.liet_ke_can).parameters)
    cam = {"floor", "building", "zone", "floor_min", "floor_max", "tower"}
    assert not (tham_so & cam), f"repo.liet_ke_can nhận bộ lọc bị cấm: {tham_so & cam}"
```

- [ ] **Step 2: Viết cổng 11 — mọi thao tác ghi đều vào nhật ký**

Tạo `tests/modules/realestate/test_nhat_ky_day_du.py`:

```python
"""CỔNG 11 (spec §9) — quét động. BR13.

Bắt được người thêm một endpoint ghi mà quên `_nhat_ky()`. Review không bắt được
vì endpoint mới trông đúng: nó có `require(action)`, có `tenant_conn()`, có test
riêng — chỉ thiếu một dòng mà không test nào của nó quan tâm.
"""

import ast
import inspect
from pathlib import Path

MIEN_TRU: frozenset[str] = frozenset()
"""Route ghi được miễn ghi nhật ký. RỖNG có chủ ý — thêm tên vào đây phải kèm
một câu giải thích, và câu đó sẽ bị đọc lại ở mọi lần review sau."""


def _cay_router() -> ast.Module:
    from portal.modules.realestate import router

    return ast.parse(Path(inspect.getfile(router)).read_text(encoding="utf-8"))


def _la_route_ghi(fn: ast.AsyncFunctionDef) -> str:
    """Trả method HTTP nếu hàm là route POST/PATCH/DELETE, ngược lại ''."""
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
            continue
        if not (isinstance(d.func.value, ast.Name) and d.func.value.id == "ROUTER"):
            continue
        if d.func.attr in ("post", "patch", "delete", "put"):
            return d.func.attr
    return ""


def _co_goi_nhat_ky(fn: ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_nhat_ky"
        for n in ast.walk(fn)
    )


def test_moi_route_ghi_deu_ghi_nhat_ky():
    thieu = [
        fn.name
        for fn in ast.walk(_cay_router())
        if isinstance(fn, ast.AsyncFunctionDef)
        and _la_route_ghi(fn)
        and fn.name not in MIEN_TRU
        and not _co_goi_nhat_ky(fn)
    ]
    assert not thieu, (
        f"route ghi nhưng không vào nhật ký: {thieu}. BR13 — không ghi thì lúc "
        "một căn bị xoá nhầm, không ai lần được ai làm."
    )


def test_it_nhat_bay_route_ghi_duoc_quet():
    """Canh chính cái quét. Nếu `_la_route_ghi` hỏng (đổi tên `ROUTER`, đổi cách
    khai decorator) thì test trên xanh vì nó quét 0 route — một cổng luôn xanh
    là một cổng đã chết."""
    so = sum(
        1
        for fn in ast.walk(_cay_router())
        if isinstance(fn, ast.AsyncFunctionDef) and _la_route_ghi(fn)
    )
    assert so >= 7, f"chỉ quét được {so} route ghi — bộ quét hỏng, không phải code hỏng"
```

- [ ] **Step 3: Chạy hai cổng mới**

Run: `uv run pytest tests/modules/realestate/test_bo_loc_co_du_lieu.py tests/modules/realestate/test_nhat_ky_day_du.py -v`
Expected: PASS — 5 test

- [ ] **Step 4: Khai 4 bảng mới vào catalog cách ly**

Mở `docs/contracts/isolation.md`, tìm mục §6.0 (danh mục bảng), thêm bốn dòng
vào bảng `tenant_data`:

```markdown
| `tenant_data.project_highlights` | M4a | điểm nhấn vị trí, 1-N theo `project_code` | `0400` |
| `tenant_data.project_progress`   | M4a | mốc tiến độ dự án, 1-N                    | `0400` |
| `tenant_data.project_documents`  | M4a | tài liệu dự án (chỉ link), 1-N            | `0400` |
| `tenant_data.import_jobs`        | M4a | phiếu import chờ xác nhận — `report` chứa mã căn và giá của khách, nên là dữ liệu nghiệp vụ | `0400` |
```

- [ ] **Step 5: Thêm G-11 và G-12 vào hợp đồng Gói G**

Mở `docs/superpowers/specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md`, thêm hai
dòng vào bảng §7:

```markdown
| **G-11** | Serializer bỏ mọi khoá có giá trị `NULL`/rỗng trước khi đưa vào ngữ cảnh LLM | `DL_01` BR03 — hiện **7/18 khoá luôn rỗng**, gần 40% payload. Portal **không làm được**: agent đọc thẳng `agent_api` qua DSN, và SQL view trả tập cột cố định. Chỗ hỏng thật là `_serialize.py`. **Đây là điều kiện** để `floor`/`building`/`zone` được lên view — xem spec M4a §2.5(b) |
| **G-12** | Gỡ hai filter `floor` và `tower` khỏi `schemas.py` của kỹ năng tra căn | Quyết định #17 · `DL_01` BR04 · BR15. Portal seed `filterable = false` (cổng 8 của M4a canh), nhưng tool schema là artefact của repo agent — portal không với tới |
```

- [ ] **Step 6: Chạy toàn bộ test và lint**

```bash
make lint
make test
```

Expected: lint sạch; toàn bộ test PASS. Nếu `tests/isolation` đỏ, đọc lỗi trước
khi sửa — cổng 6 của M1 quét catalog, và nó có thể đang báo đúng.

- [ ] **Step 7: Commit**

```bash
git add tests/modules/realestate/test_bo_loc_co_du_lieu.py \
        tests/modules/realestate/test_nhat_ky_day_du.py \
        docs/contracts/isolation.md \
        docs/superpowers/specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md
git commit -m "feat(m4a): hai cổng quét động + khai catalog + G-11/G-12 cho Gói G (T11)"
```

---

## Task 12: `overview` jsonb và ba bảng con

> **Tại sao task này tồn tại.** Tự soát plan phát hiện spec §7 liệt kê 11 dòng API
> nhưng **không dòng nào chạm `overview` hay ba bảng con** — trong khi §2.1 đưa
> 9 ô của nhóm *Tổng quan* vào `overview` và 4 ô vào bảng con. Thiếu task này thì
> 13/35 ô của `pform` không có đường ghi, và nó chỉ lộ ra khi người làm FE dựng
> form. Đây là lỗ của **spec**, plan lấp lại.

**Files:**
- Modify: `src/portal/modules/realestate/repo.py` (thêm 3 hàm)
- Modify: `src/portal/modules/realestate/router.py` (mở rộng 2 route, thêm 2 route)
- Modify: `src/portal/modules/realestate/contracts.py` (thêm `MucConIn`/`MucConOut`)
- Create: `tests/modules/realestate/test_overview_va_bang_con.py`

**Interfaces:**
- Consumes: `repo._upsert` · `_JSON_SANG_COT_DU_AN` · `_nhat_ky` (Task 6, 7)
- Produces:
  - `repo.ghi_overview(conn, code, overview: str) -> asyncpg.Record | None`
  - `repo.liet_ke_muc_con(conn, loai, project_code) -> list[Record]`
  - `repo.thay_the_muc_con(conn, tenant_id, loai, project_code, muc: list[dict]) -> int`
  - `GET`/`PUT` `/projects/{code}/{loai}` với `loai ∈ {highlights, progress, documents}`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/realestate/test_overview_va_bang_con.py`:

```python
"""Nhóm Tổng quan (9 ô → `overview` jsonb) và ba editor dạng list.

Prototype tự ghi trên form: "Tổng quan · ghi vào overview jsonb — 11 khoá", và
"Video · Tiến độ · Tài liệu · ba editor dạng list". Đây là đường ghi cho chúng.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"

TONG_QUAN = {
    "scale": "1.200 ha",
    "units_text": "2.400 sản phẩm thấp tầng",
    "density": "21%",
    "area_summary": "90 – 300 m²",
    "product": "Biệt thự đơn lập, song lập, liền kề",
    "ownership": "Lâu dài",
    "ownership_type": "Sổ hồng",
    "apartment_standard": "Thô, Giãn xây",
    "description": "Đại đô thị phía Đông Hà Nội",
}


@pytest.fixture
async def co_du_an(client_re: httpx.AsyncClient):
    await client_re.post(f"{API}/projects", json={"code": "VOP2", "name": "Ocean Park 2"})
    return "VOP2"


async def test_ghi_va_doc_lai_overview(client_re: httpx.AsyncClient, co_du_an):
    r = await client_re.patch(f"{API}/projects/VOP2", json={"overview": TONG_QUAN})
    assert r.status_code == 200, r.text
    assert r.json()["overview"]["scale"] == "1.200 ha"
    assert (await client_re.get(f"{API}/projects/VOP2")).json()["overview"] == TONG_QUAN


async def test_overview_thay_the_nguyen_khoi_khong_tron(
    client_re: httpx.AsyncClient, co_du_an
):
    """PATCH ở mức DỰ ÁN là partial, nhưng `overview` gửi lên là NGUYÊN khối.

    Trộn từng khoá thì không có cách nào XOÁ một khoá — người dùng xoá ô Mật độ
    xây dựng trên form, bấm Lưu, và giá trị cũ vẫn còn.
    """
    await client_re.patch(f"{API}/projects/VOP2", json={"overview": TONG_QUAN})
    await client_re.patch(f"{API}/projects/VOP2", json={"overview": {"scale": "1.200 ha"}})
    assert (await client_re.get(f"{API}/projects/VOP2")).json()["overview"] == {
        "scale": "1.200 ha"
    }


async def test_patch_khong_gui_overview_thi_giu_nguyen(
    client_re: httpx.AsyncClient, co_du_an
):
    await client_re.patch(f"{API}/projects/VOP2", json={"overview": TONG_QUAN})
    await client_re.patch(f"{API}/projects/VOP2", json={"name": "Tên mới"})
    assert (await client_re.get(f"{API}/projects/VOP2")).json()["overview"] == TONG_QUAN


async def test_overview_khong_phai_object_thi_tu_choi(client_re: httpx.AsyncClient, co_du_an):
    r = await client_re.patch(f"{API}/projects/VOP2", json={"overview": "chuoi"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_01"


@pytest.mark.parametrize("loai", ["highlights", "progress", "documents"])
async def test_ba_bang_con_rong_tra_mang_rong(
    client_re: httpx.AsyncClient, co_du_an, loai: str
):
    assert (await client_re.get(f"{API}/projects/VOP2/{loai}")).json() == []


async def test_ghi_diem_nhan_vi_tri(client_re: httpx.AsyncClient, co_du_an):
    r = await client_re.put(
        f"{API}/projects/VOP2/highlights",
        json={"muc": [{"noiDung": "5 phút tới Ocean City"}, {"noiDung": "Cạnh VinUni"}]},
    )
    assert r.status_code == 200, r.text
    ds = (await client_re.get(f"{API}/projects/VOP2/highlights")).json()
    assert [m["noiDung"] for m in ds] == ["5 phút tới Ocean City", "Cạnh VinUni"]
    assert [m["sortOrder"] for m in ds] == [0, 1], "thứ tự phải theo đúng mảng gửi lên"


async def test_put_thay_the_toan_bo_danh_sach(client_re: httpx.AsyncClient, co_du_an):
    """PUT, không PATCH: ba editor này là danh sách kéo-thả-sắp-xếp trên form,
    nên FE luôn gửi trạng thái cuối. Merge từng mục thì không xoá được mục nào."""
    await client_re.put(f"{API}/projects/VOP2/highlights", json={"muc": [{"noiDung": "A"}]})
    await client_re.put(f"{API}/projects/VOP2/highlights", json={"muc": [{"noiDung": "B"}]})
    ds = (await client_re.get(f"{API}/projects/VOP2/highlights")).json()
    assert [m["noiDung"] for m in ds] == ["B"]


async def test_ghi_tien_do_va_tai_lieu(client_re: httpx.AsyncClient, co_du_an):
    await client_re.put(
        f"{API}/projects/VOP2/progress",
        json={"muc": [{"tieuDe": "Cất nóc toà S2", "mocNgay": "2026-09-30"}]},
    )
    await client_re.put(
        f"{API}/projects/VOP2/documents",
        json={"muc": [{"tieuDe": "Bảng giá T9", "link": "https://drive.example/x"}]},
    )
    assert (await client_re.get(f"{API}/projects/VOP2/progress")).json()[0]["tieuDe"] == (
        "Cất nóc toà S2"
    )
    assert (await client_re.get(f"{API}/projects/VOP2/documents")).json()[0]["link"] == (
        "https://drive.example/x"
    )


async def test_tai_lieu_thieu_link_bi_tu_choi(client_re: httpx.AsyncClient, co_du_an):
    """`0400` có CHECK `link <> ''`. Bắt trước ở API để lỗi đọc được, thay vì
    để asyncpg ném CheckViolationError lên FE."""
    r = await client_re.put(
        f"{API}/projects/VOP2/documents", json={"muc": [{"tieuDe": "X", "link": ""}]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ER_01"


async def test_loai_la_tra_404(client_re: httpx.AsyncClient, co_du_an):
    assert (await client_re.get(f"{API}/projects/VOP2/videos")).status_code == 404


async def test_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.put(f"{API}/projects/KHONG-CO/highlights", json={"muc": []})
    assert r.status_code == 404


async def test_xoa_du_an_thi_muc_con_di_theo(
    client_re: httpx.AsyncClient, co_du_an, pool
):
    """Không CASCADE theo `project_code` được (nó không phải FK), nên router phải
    dọn tay. Bỏ sót là để lại mục con mồ côi mà không màn nào hiện — và chúng
    hiện lại nguyên vẹn khi ai đó tạo lại dự án cùng mã."""
    await client_re.put(f"{API}/projects/VOP2/highlights", json={"muc": [{"noiDung": "A"}]})
    await client_re.delete(f"{API}/projects/VOP2")
    assert await pool.fetchval(
        "SELECT count(*) FROM tenant_data.project_highlights WHERE tenant_id='rew'"
    ) == 0


async def test_ghi_muc_con_vao_nhat_ky(client_re: httpx.AsyncClient, co_du_an, pool):
    await client_re.put(f"{API}/projects/VOP2/highlights", json={"muc": [{"noiDung": "A"}]})
    hd = await pool.fetchval(
        "SELECT hanh_dong FROM control.audit_log WHERE tenant_id='rew' ORDER BY id DESC LIMIT 1"
    )
    assert hd == "realestate.project.highlights.update"
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/realestate/test_overview_va_bang_con.py -v`
Expected: FAIL — `overview` bị `_payload` bỏ qua (chưa có trong ánh xạ), và 404
trên `/projects/{code}/highlights`.

- [ ] **Step 3: Thêm 3 hàm vào `repo.py`**

Chèn vào cuối `src/portal/modules/realestate/repo.py`:

```python
# ─── overview và ba bảng con ────────────────────────────────────────────────

BANG_CON: dict[str, tuple[str, tuple[str, ...]]] = {
    "highlights": ("tenant_data.project_highlights", ("noi_dung",)),
    "progress": ("tenant_data.project_progress", ("tieu_de", "moc_ngay", "ghi_chu")),
    "documents": ("tenant_data.project_documents", ("tieu_de", "link")),
}
"""Ba editor dạng list của prototype. `videos` KHÔNG có ở đây — video là media,
thuộc M4b (spec M4a §2.1)."""


async def ghi_overview(conn: asyncpg.Connection, code: str, overview: str) -> asyncpg.Record | None:
    """`overview` là chuỗi JSON đã serialize. Thay thế NGUYÊN KHỐI.

    Không `||` (merge từng khoá): trộn thì không có cách nào XOÁ một khoá, và
    người dùng xoá ô Mật độ xây dựng trên form rồi thấy giá trị cũ vẫn còn.
    """
    return await conn.fetchrow(
        f"""UPDATE tenant_data.projects
               SET overview = $2::jsonb, updated_at = clock_timestamp()
             WHERE code = $1 RETURNING {_COT_DU_AN}""",
        code, overview,
    )


async def liet_ke_muc_con(
    conn: asyncpg.Connection, loai: str, project_code: str
) -> list[asyncpg.Record]:
    bang, cot = BANG_CON[loai]
    return await conn.fetch(
        f"SELECT id, sort_order, {', '.join(cot)} FROM {bang} "
        f"WHERE project_code = $1 ORDER BY sort_order, id",
        project_code,
    )


async def thay_the_muc_con(
    conn: asyncpg.Connection, tenant_id: str, loai: str, project_code: str, muc: list[dict]
) -> int:
    """Xoá sạch rồi ghi lại — PUT, không PATCH.

    Ba editor này là danh sách kéo-thả-sắp-xếp, nên FE luôn gửi trạng thái cuối.
    Cả hai lệnh nằm trong giao dịch của `tenant_conn()`, nên "xoá sạch" không bao
    giờ quan sát được từ ngoài.
    """
    bang, cot = BANG_CON[loai]
    await conn.execute(f"DELETE FROM {bang} WHERE project_code = $1", project_code)
    if not muc:
        return 0

    dat_cho = ", ".join(
        "(" + ", ".join(f"${i * (len(cot) + 3) + j + 1}" for j in range(len(cot) + 3)) + ")"
        for i in range(len(muc))
    )
    gia_tri: list = []
    for i, m in enumerate(muc):
        gia_tri += [tenant_id, project_code, i, *[m.get(c) for c in cot]]

    await conn.execute(
        f"INSERT INTO {bang} (tenant_id, project_code, sort_order, {', '.join(cot)}) "
        f"VALUES {dat_cho}",
        *gia_tri,
    )
    return len(muc)


async def xoa_muc_con_cua_du_an(conn: asyncpg.Connection, project_code: str) -> None:
    """Gọi TRƯỚC khi xoá dự án. `project_code` không phải FK nên không CASCADE.

    Bỏ sót là để lại mục con mồ côi mà không màn nào hiện — và chúng hiện lại
    nguyên vẹn khi ai đó tạo lại một dự án cùng mã.
    """
    for bang, _ in BANG_CON.values():
        await conn.execute(f"DELETE FROM {bang} WHERE project_code = $1", project_code)
```

- [ ] **Step 4: Thêm contract vào `contracts.py`**

```python
class MucConOut(BaseModel):
    id: int
    sortOrder: int
    noiDung: str | None = None
    tieuDe: str | None = None
    mocNgay: date | None = None
    ghiChu: str | None = None
    link: str | None = None
    """Một model cho cả ba loại, khoá không dùng để `None`.

    Ba model riêng cho ba bảng 2–3 cột là ba chỗ để lệch nhau, và FE vẫn phải
    switch theo `loai` dù có tách hay không."""


class MucConIn(BaseModel):
    muc: list[dict] = Field(default_factory=list)
    """Mảng RỖNG là hợp lệ — nó nghĩa là "xoá hết", và người dùng phải làm được
    việc đó mà không cần một endpoint DELETE riêng."""
```

Thêm `from datetime import date` vào import đầu file và `"MucConIn", "MucConOut"`
vào `__all__`.

- [ ] **Step 5: Sửa `router.py` — `overview` + 2 route mới + dọn mục con**

Trong `router.py`:

**(a)** thêm xử lý `overview` vào cả `tao_du_an` và `sua_du_an`. Ngay sau dòng
`r = await repo.ghi_du_an(...)` trong **cả hai** hàm, chèn:

```python
        if "overview" in than:
            if not isinstance(than["overview"], dict):
                raise loi.LoiPortal("ER_01", 422, "overview phải là một object")
            r = await repo.ghi_overview(
                conn, code, json.dumps(than["overview"], ensure_ascii=False)
            )
```

Thêm `import json` lên đầu file.

**(b)** trong `xoa_du_an`, chèn **trước** `repo.xoa_du_an`:

```python
        await repo.xoa_muc_con_cua_du_an(conn, code)
```

**(c)** thêm hai route vào cuối file:

```python
_KHOA_MUC_CON_JSON_SANG_COT = {
    "noiDung": "noi_dung", "tieuDe": "tieu_de",
    "mocNgay": "moc_ngay", "ghiChu": "ghi_chu", "link": "link",
}

_MUC_CON_BAT_BUOC: dict[str, tuple[str, ...]] = {
    "highlights": ("noi_dung",),
    "progress": ("tieu_de",),
    "documents": ("tieu_de", "link"),
}
"""Khớp CHECK `<> ''` của `0400`. Bắt ở API để người dùng nhận một câu đọc được,
không phải `CheckViolationError` của asyncpg."""


def _ra_muc_con(r: asyncpg.Record) -> MucConOut:
    d = dict(r)
    return MucConOut(
        id=d["id"], sortOrder=d["sort_order"], noiDung=d.get("noi_dung"),
        tieuDe=d.get("tieu_de"), mocNgay=d.get("moc_ngay"),
        ghiChu=d.get("ghi_chu"), link=d.get("link"),
    )


@ROUTER.get("/projects/{code}/{loai}", response_model=list[MucConOut])
async def liet_ke_muc_con(
    code: str,
    loai: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[MucConOut]:
    if loai not in repo.BANG_CON:
        raise _khong_thay(f"danh sách {loai}")
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.liet_ke_muc_con(conn, loai, code)
    return [_ra_muc_con(r) for r in rows]


@ROUTER.put("/projects/{code}/{loai}", response_model=list[MucConOut])
async def thay_the_muc_con(
    code: str,
    loai: str,
    than: MucConIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[MucConOut]:
    """PUT thay thế toàn bộ danh sách — FE luôn gửi trạng thái cuối sau kéo-thả."""
    if loai not in repo.BANG_CON:
        raise _khong_thay(f"danh sách {loai}")

    muc = [
        {
            cot: m[khoa]
            for khoa, cot in _KHOA_MUC_CON_JSON_SANG_COT.items()
            if khoa in m
        }
        for m in than.muc
    ]
    for i, m in enumerate(muc):
        thieu = [c for c in _MUC_CON_BAT_BUOC[loai] if not str(m.get(c) or "").strip()]
        if thieu:
            raise loi.LoiPortal("ER_01", 422, f"Mục {i + 1} thiếu: {', '.join(thieu)}")

    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_du_an(conn, code) is None:
            raise _khong_thay("dự án")
        await repo.thay_the_muc_con(conn, p.tenant_id, loai, code, muc)
        rows = await repo.liet_ke_muc_con(conn, loai, code)
        await _nhat_ky(
            conn, p, f"realestate.project.{loai}.update", {"code": code, "so_muc": len(muc)}
        )
    return [_ra_muc_con(r) for r in rows]
```

> **Thứ tự khai route quan trọng.** `/projects/{code}/{loai}` phải đứng **sau**
> `/projects/{code}` trong file — FastAPI khớp theo thứ tự đăng ký, và một route
> hai đoạn đứng trước sẽ không nuốt route một đoạn, nhưng đặt đúng thứ tự làm
> file đọc theo đúng mức chi tiết tăng dần.

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/realestate/test_overview_va_bang_con.py -v`
Expected: PASS — 15 test

- [ ] **Step 7: Chạy lại cổng nhật ký quét động**

Run: `uv run pytest tests/modules/realestate/test_nhat_ky_day_du.py -v`
Expected: PASS. Route `PUT` mới có `_nhat_ky()`; nếu quên thì cổng 11 đỏ — đúng
như nó sinh ra để làm.

- [ ] **Step 8: Toàn bộ test và lint**

```bash
make lint && make test
```

Expected: lint sạch, toàn bộ PASS.

- [ ] **Step 9: Commit**

```bash
git add src/portal/modules/realestate tests/modules/realestate/test_overview_va_bang_con.py
git commit -m "feat(m4a): overview jsonb + ba editor dạng list — lấp 13/35 ô pform spec bỏ sót (T12)"
```

---

## Sau khi xong 12 task

**Còn lại, không thuộc plan này:**

| Việc | Thuộc |
|---|---|
| Màn hình `projects` · `pform` · `uform` · `domains` · Import | Repo `odyssey-portal-frontend` — hợp đồng ở spec §8 |
| Test FE canh hai nhãn chính sách suy từ dữ liệu | Repo FE — spec §10 |
| Media dự án (13 ô ảnh/video) | **M4b**, spec riêng chưa viết |
| Dọn `import_jobs` quá hạn | Chưa giao — xem "Còn treo" bên dưới |

**Còn treo sau plan này:**

- **N2** — BA chốt trường nào `required_for_agent`. Cơ chế đã xong (Task 8 cổng 9
  chứng minh), chỉ thiếu con số.
- **Ba cờ cho từng trường** — Task 10 seed một bộ mặc định; BA đè lên bằng API.
- **Dọn `import_jobs` quá hạn.** Job hết hạn ở lại DB và file ở lại kho tệp. Không
  chặn gì, nhưng một workspace import hàng ngày sẽ tích rác. Cách rẻ nhất: một
  handler `jobs` của M1 chạy hàng ngày — chưa viết vì nó cần quyết định retention,
  và retention là việc của **M8**.
- **`sale_email` chưa nối `control.users`** — lưu chuỗi, chưa kiểm người đó còn là
  thành viên workspace không. Nối được sau M2b mà không đổi cột.
- **Bảng lookup `unit_types`** — điều kiện mở lại ở spec §12.

