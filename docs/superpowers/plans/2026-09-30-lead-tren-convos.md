# Lead stage · điểm · đối tượng trên `/convos` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hiện lead mới nhất của từng khách trên `/convos` (có bộ lọc theo stage), và lead của từng phiên trên `/convos/$phone`.

**Architecture:** Backend `ops` tính lead bằng `LEFT JOIN LATERAL` vào `tenant_data.escalations`: theo khách cho `/convos/khach` (kèm bộ lọc, áp trước phân trang), theo phiên cho `/convos/khach/{phone}/phien` và `/convos/phien/{id}`. Frontend thêm một chip dùng chung `ChipStage`, một cột Lead ở hàng khách, một ô lọc dạng menu (`LocStage`, portal ra `body`), và ba chỗ hiện lead ở trang chi tiết.

**Tech Stack:** FastAPI + asyncpg + pytest (BE, `odyssey-portal-backend`) · React 19 + TanStack Router/Query + Tailwind v4 + Vitest + MSW (FE, `odyssey-portal-frontend`).

**Spec:** `docs/superpowers/specs/2026-09-30-lead-tren-convos-design.md` (repo FE). Bản vẽ: `public/demo-lead-convos.html`.

## Global Constraints

- Stage hợp lệ và thứ tự phễu: `lead` → `mql` → `sql` → `hen_gap`. Nhãn: `Lead` · `MQL` · `SQL` · `Hẹn gặp`.
- Tham số lọc `lead_stage` ∈ `lead | mql | sql | hen_gap | none`; vắng = không lọc; giá trị khác ⇒ 422.
- **Lead của PHIÊN** = hàng escalation mới nhất (`created_at DESC, id DESC`) của phiên có `lead_stage IS NOT NULL`. Lấy CẢ BA trường từ CÙNG hàng đó.
- **Lead của KHÁCH** = lead của phiên mới nhất (`COALESCE(started_at, created_at) DESC`) CÓ lead. Nối qua `escalations.session_id = conversations.session_id`, gom theo `COALESCE(conversations.phone, '')`. KHÔNG dùng `escalations.phone`.
- DTO camelCase: `leadStage: str | None`, `leadScore: int | None`, `audience: str | None`.
- Đối tượng: `end_user` → «Khách mua», `broker` → «Môi giới», giá trị lạ hiện nguyên văn.
- Điểm hiện số thô: font mono 12.5px `text-fg` + chữ «điểm» 11.5px `text-muted-2`. Không thang, không màu nóng/lạnh.
- Chip chỉ có nhãn (KHÔNG chấm). Cao 22px, `rounded-full`, viền 1px, 11.5px/600, `px-[9px]`.
- Token màu (ở `@theme` trong `src/styles/theme.css`):
  `--color-lead-1-bg: #f0efec` · `--color-lead-1-fg: #5f656e` · `--color-lead-1-vien: #8a857b`
  `--color-lead-2-bg: #fbf1dc` · `--color-lead-2-fg: #7a5410` · `--color-lead-2-vien: #a57c2c`
  `--color-lead-3-bg: #fde6d4` · `--color-lead-3-fg: #9a3f0c` · `--color-lead-3-vien: #c46a33`
  `--color-lead-4-bg: #b4501a` · `--color-lead-4-fg: #ffffff` · `--color-lead-4-vien: #b4501a`
- Luật repo FE: không mã màu ngoài `theme.css`; class chứa `border` phải kèm token màu viền trong CÙNG chuỗi (`tests/vien-tran.test.ts`); nút phải có `cursor-pointer` (Tailwind v4); desktop không đổi class nào, responsive chỉ THÊM `max-md:`/`max-lg:`; field mới trên kiểu FE khai TUỲ CHỌN (backend cũ chưa trả).
- Luật repo BE: mọi SQL vào `tenant_data` phải VIẾT THẲNG `tenant_id = portal.current_tenant()` (cổng `make test-isolation` đọc tĩnh văn bản); đừng viết `tenant_data.<bảng>` trong docstring.
- Typecheck FE là `npx tsc -b --force` (KHÔNG `--noEmit`). Vitest chạy với `NODE_OPTIONS="--no-experimental-webstorage"` (máy dev dùng Node 24).
- Commit lên nhánh `dungnd` của MỖI repo. Mỗi commit kết thúc bằng `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. FE đang có thay đổi CHƯA commit của việc khác (`src/main.tsx`, `src/lib/canhPhienHetHan.ts`, `tests/phien-het-han.test.tsx`, `CLAUDE.md`) — commit bằng `git commit -- <đường dẫn>`, KHÔNG `git add -A`.

## Review Focus

1. **Khách từng SQL, phiên sau lại Lead, lọc `sql`** ⇒ khách KHÔNG có trong kết quả (lọc theo lead MỚI NHẤT, không theo lịch sử). → test ở Task 1.
2. **Phiên mới nhất của khách không chuyển sale** ⇒ vẫn hiện lead của phiên gần nhất có lead, không rơi về «Chưa phân loại». → test ở Task 1.
3. **Lọc ra 0 khách rồi mở lại menu stage** ⇒ menu vẫn hiện đủ, không bị tấm nền `overflow-hidden` cắt. → test ở Task 5 (menu nằm NGOÀI tấm nền trong DOM).
4. **Stage lạ agent ghi thêm (vd `chot`)** ⇒ chip trung tính hiện nguyên văn, không crash, không có trong menu lọc. → test ở Task 3 và Task 4.
5. **Có stage nhưng `lead_score`/`audience` NULL** ⇒ hiện chip, bỏ phần thiếu, không in «null»/«undefined»/«· » thừa. → test ở Task 4 và Task 6.

---

## PHẦN A — BACKEND (`odyssey-portal-backend`)

Chạy test BE: `uv run pytest tests/modules/ops -q`. Suite BE vốn có bài đỏ sẵn — chụp baseline `uv run pytest tests/modules/ops -q 2>&1 | tail -3` TRƯỚC Task 1 để so.

### Task 1: Lead của khách + bộ lọc `lead_stage` ở `GET /convos/khach`

**Files:**
- Modify: `tests/modules/ops/conftest.py` (hàm `them_ca`)
- Modify: `src/portal/modules/ops/repo.py` (`liet_ke_khach`, `dem_tong`, hằng mới)
- Modify: `src/portal/modules/ops/contracts.py` (`KhachOut`)
- Modify: `src/portal/modules/ops/router.py` (`_ra_khach`, `liet_ke_khach`)
- Test: `tests/modules/ops/test_lead.py` (mới)

**Interfaces:**
- Produces: `repo.liet_ke_khach(conn, *, tim, tu_ngay, da_chuyen, lead_stage: str = "", limit, offset)` và `repo.dem_tong(conn, *, tim, tu_ngay, da_chuyen, lead_stage: str = "")`; hàng trả thêm cột `lead_stage`, `lead_score`, `audience`. `KhachOut.leadStage/leadScore/audience`. Hằng `repo.LOC_LEAD: dict[str, str]`.
- Produces (test helper): `them_ca(..., lead_stage: str | None = None, lead_score: int | None = None, audience: str | None = None)`.

- [ ] **Step 1: Mở rộng helper `them_ca`**

Trong `tests/modules/ops/conftest.py`, thay thân `them_ca` bằng:

```python
async def them_ca(
    conn: asyncpg.Connection,
    session_id: str,
    *,
    tenant: str = TENANT,
    phone: str | None = "0912448111",
    ten: str | None = "Minh Anh",
    du_an: str | None = None,
    tool_thieu: str | None = None,
    summary: str | None = "Khách: Minh Anh, SĐT: 0912448111. Lý do chuyển: hỏi sổ hồng.",
    summary_luc: datetime | None = None,
    message_seq: int | None = 7,
    trang_thai: str = "new",
    tao_luc: datetime | None = None,
    lead_stage: str | None = None,
    lead_score: int | None = None,
    audience: str | None = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO tenant_data.escalations
            (tenant_id, session_id, phone, customer_name, project, missing_data_tool,
             summary, summary_at, message_seq, status, created_at,
             lead_stage, lead_score, audience)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        RETURNING id
        """,
        tenant,
        session_id,
        phone,
        ten,
        du_an,
        tool_thieu,
        summary,
        summary_luc,
        message_seq,
        trang_thai,
        tao_luc or luc(27),
        lead_stage,
        lead_score,
        audience,
    )
```

- [ ] **Step 2: Viết test hỏng**

Tạo `tests/modules/ops/test_lead.py`:

```python
"""Lead (stage · điểm · đối tượng) trên /convos — mỗi test neo một luật của spec §2."""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, luc, them_ca, them_phien

pytestmark = pytest.mark.asyncio

MOI = {"tu_ngay": "all"}
A = "0911000001"
B = "0911000002"
C = "0911000003"


async def _mot(conn, phone):
    hang = await repo.liet_ke_khach(conn, tu_ngay="all")
    return next(r for r in hang if r["phone"] == phone)


async def test_lead_khach_la_cua_phien_moi_nhat_co_lead(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s2", phone=A, bat_dau=luc(25))
    await them_phien(conn_ops, "s3", phone=A, bat_dau=luc(27))  # phiên mới nhất KHÔNG chuyển sale
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_score=80, tao_luc=luc(20))
    await them_ca(conn_ops, "s2", phone=A, lead_stage="lead", lead_score=40, tao_luc=luc(25))

    r = await _mot(conn_ops, A)

    assert (r["lead_stage"], r["lead_score"]) == ("lead", 40)


async def test_trong_phien_hang_null_moi_hon_bi_bo_qua(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="mql", lead_score=65, tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, tao_luc=luc(20, 11))  # hàng mới hơn, không có lead

    r = await _mot(conn_ops, A)

    assert r["lead_stage"] == "mql"


async def test_ba_truong_lay_tu_cung_mot_hang(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_score=70, audience="broker", tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="lead", lead_score=30, audience=None, tao_luc=luc(20, 11))

    r = await _mot(conn_ops, A)

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == ("lead", 30, None)


async def test_khach_khong_co_lead_ra_null(conn_ops):
    await them_phien(conn_ops, "s1", phone=C, bat_dau=luc(20))

    r = await _mot(conn_ops, C)

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == (None, None, None)


async def _ba_khach(conn):
    # A: từng SQL, nay Lead · B: SQL · C: chưa có lead
    await them_phien(conn, "a1", phone=A, bat_dau=luc(20))
    await them_phien(conn, "a2", phone=A, bat_dau=luc(25))
    await them_ca(conn, "a1", phone=A, lead_stage="sql", tao_luc=luc(20))
    await them_ca(conn, "a2", phone=A, lead_stage="lead", tao_luc=luc(25))
    await them_phien(conn, "b1", phone=B, bat_dau=luc(22))
    await them_ca(conn, "b1", phone=B, lead_stage="sql", tao_luc=luc(22))
    await them_phien(conn, "c1", phone=C, bat_dau=luc(23))
    await them_phien(conn, "c2", phone=C, bat_dau=luc(24))


async def test_loc_sql_theo_lead_moi_nhat_khong_theo_lich_su(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="sql")

    assert [r["phone"] for r in hang] == [B]


async def test_loc_none_la_khach_khong_co_lead(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="none")

    assert [r["phone"] for r in hang] == [C]


async def test_dem_tong_theo_dung_bo_loc(conn_ops):
    await _ba_khach(conn_ops)

    assert await repo.dem_tong(conn_ops, tu_ngay="all", lead_stage="none") == (1, 2)
    assert await repo.dem_tong(conn_ops, tu_ngay="all", lead_stage="sql") == (1, 1)
    assert await repo.dem_tong(conn_ops, tu_ngay="all") == (3, 5)


async def test_loc_ap_truoc_phan_trang(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="none", limit=1, offset=0)

    assert [r["phone"] for r in hang] == [C]


async def test_lead_tenant_khac_khong_lot_sang(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20), tenant=TENANT_KHAC)
    await them_ca(conn_ops, "s1", phone=A, lead_stage="hen_gap", tenant=TENANT_KHAC)

    r = await _mot(conn_ops, A)

    assert r["lead_stage"] is None


async def test_api_tra_camelcase(client_ops, conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="hen_gap", lead_score=90, audience="end_user")

    r = await client_ops.get("/api/v1/convos/khach", params=MOI)

    k = next(i for i in r.json()["items"] if i["phone"] == A)
    assert (k["leadStage"], k["leadScore"], k["audience"]) == ("hen_gap", 90, "end_user")


async def test_api_loc_theo_lead_stage(client_ops, conn_ops):
    await _ba_khach(conn_ops)

    r = await client_ops.get("/api/v1/convos/khach", params={**MOI, "lead_stage": "sql"})

    assert r.status_code == 200
    assert [i["phone"] for i in r.json()["items"]] == [B]
    assert r.json()["tongKhach"] == 1


async def test_api_lead_stage_la_thi_422(client_ops):
    r = await client_ops.get("/api/v1/convos/khach", params={**MOI, "lead_stage": "xyz"})

    assert r.status_code == 422
```

- [ ] **Step 3: Chạy test, xác nhận hỏng**

Run: `uv run pytest tests/modules/ops/test_lead.py -q`
Expected: FAIL — `TypeError: liet_ke_khach() got an unexpected keyword argument 'lead_stage'` / `KeyError: 'lead_stage'`.

- [ ] **Step 4: Cài repo**

Trong `src/portal/modules/ops/repo.py`, ngay SAU hằng `_TEN_DU_AN` (và docstring của nó), thêm:

```python
_LEAD_KHACH = """
    LEFT JOIN LATERAL (
        SELECT e.lead_stage, e.lead_score, e.audience
          FROM tenant_data.escalations e
          JOIN tenant_data.conversations c
            ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
         WHERE e.tenant_id = portal.current_tenant()
           AND c.tenant_id = portal.current_tenant()
           AND COALESCE(c.phone, '') = t.phone
           AND e.lead_stage IS NOT NULL
         ORDER BY COALESCE(c.started_at, c.created_at) DESC, e.created_at DESC, e.id DESC
         LIMIT 1
    ) l ON TRUE
"""
"""Lead của KHÁCH = lead của PHIÊN mới nhất có lead (spec §2).

Khoá sắp đầu là thời điểm PHIÊN, không phải `created_at` của hàng ca: danh sách, ô «Lead
hiện tại» và phiên trên cùng có chip ở trang chi tiết phải LUÔN là cùng một hàng. Hai khoá
sau chọn hàng mới nhất TRONG phiên. Nối qua phiên, KHÔNG qua `phone` của hàng ca (đó là
ảnh chụp lúc chuyển, lệch được với khoá gom nhóm)."""

LOC_LEAD: dict[str, str] = {
    "": "TRUE",
    "none": "l.lead_stage IS NULL",
    "lead": "l.lead_stage = 'lead'",
    "mql": "l.lead_stage = 'mql'",
    "sql": "l.lead_stage = 'sql'",
    "hen_gap": "l.lead_stage = 'hen_gap'",
}
"""Điều kiện lọc theo lead MỚI NHẤT. Khoá đã được router kiểm bằng `pattern`; tra dict chứ
không ghép chuỗi người dùng vào SQL."""
```

Thay TOÀN BỘ hàm `liet_ke_khach` bằng:

```python
async def liet_ke_khach(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
    lead_stage: str = "",
    limit: int = TRANG_MAC_DINH,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Một hàng một khách, sắp theo phiên gần nhất, kèm lead mới nhất (`_LEAD_KHACH`).

    `array_agg(... ORDER BY ...)[1]` chứ KHÔNG `max()`: cần giá trị của phiên MỚI
    NHẤT, không phải giá trị lớn nhất theo thứ tự chữ cái. `max(customer_name)`
    chạy được, không báo lỗi, và trả tên sai.

    `FILTER (WHERE ... IS NOT NULL)` để một phiên bỏ trống trường không đẩy NULL lên
    đầu mảng và xoá mất giá trị đã biết từ phiên trước.

    Không lọc lead ⇒ `LIMIT` nằm TRONG subquery để LATERAL chỉ chạy cho đúng một trang.
    Có lọc ⇒ `LIMIT` phải nằm SAU `WHERE` của lead, không thì trang cắt trước rồi mới lọc
    và thanh phân trang nói về một tập khác.
    """
    loc = LOC_LEAD[lead_stage]
    trang_trong = "LIMIT $4 OFFSET $5" if not lead_stage else ""
    trang_ngoai = "LIMIT $4 OFFSET $5" if lead_stage else ""
    sql = f"""
        SELECT t.*, l.lead_stage, l.lead_score, l.audience, {_TEN_DU_AN.format(cot="t.du_an")}
          FROM (
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
         WHERE {_CACH_LY}
         GROUP BY 1
        HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
         ORDER BY gan_nhat DESC
         {trang_trong}
          ) t
        {_LEAD_KHACH}
         WHERE {loc}
         ORDER BY t.gan_nhat DESC
         {trang_ngoai}
    """
    return list(await conn.fetch(sql, tim, _escape_like(tim), da_chuyen, limit, offset))
```

Thay TOÀN BỘ hàm `dem_tong` bằng:

```python
async def dem_tong(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
    lead_stage: str = "",
) -> tuple[int, int]:
    """`(số khách, số phiên)` TRÊN TẬP ĐÃ LỌC — không phải tổng toàn bảng.

    Hai con số này hiện cạnh thanh lọc; nếu đếm toàn bảng thì lọc xong con số không
    đổi và người dùng tưởng bộ lọc không chạy. Lọc lead dùng CHUNG `_LEAD_KHACH` +
    `LOC_LEAD` với `liet_ke_khach` để hai chỗ không lệch điều kiện; không lọc thì bỏ
    LATERAL cho nhẹ.
    """
    lead = _LEAD_KHACH if lead_stage else ""
    sql = f"""
        SELECT count(*) AS so_khach, COALESCE(sum(t.n), 0) AS so_phien
          FROM (
            SELECT COALESCE(phone, '') AS phone, count(*) AS n
              FROM tenant_data.conversations
             WHERE {_CACH_LY}
             GROUP BY COALESCE(phone, '')
            HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
          ) t
          {lead}
         WHERE {LOC_LEAD[lead_stage]}
    """
    r = await conn.fetchrow(sql, tim, _escape_like(tim), da_chuyen)
    return int(r["so_khach"]), int(r["so_phien"])
```

- [ ] **Step 5: Cài contract + router**

Trong `src/portal/modules/ops/contracts.py`, thêm vào CUỐI `KhachOut` (sau `tenDuAn: str | None`):

```python
    leadStage: str | None = None
    """Lead MỚI NHẤT của khách (lead của phiên mới nhất có lead — spec §2). NULL = chưa
    phân loại. Chuỗi thô agent ghi; không `Literal` để một bậc mới không làm 500."""
    leadScore: int | None = None
    audience: str | None = None
```

Trong `src/portal/modules/ops/router.py`, `_ra_khach` thêm ba đối số cuối cho `KhachOut(...)`:

```python
        leadStage=r["lead_stage"],
        leadScore=r["lead_score"],
        audience=r["audience"],
```

và thay endpoint `liet_ke_khach` bằng:

```python
@ROUTER.get("/convos/khach", response_model=TrangKhach)
async def liet_ke_khach(
    q: str = "",
    tu_ngay: str = Query("30", pattern="^(7|30|all)$"),
    da_chuyen: bool = False,
    lead_stage: str = Query("", pattern="^(|lead|mql|sql|hen_gap|none)$"),
    limit: int = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG),
    offset: int = Query(0, ge=0),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangKhach:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_khach(
            conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen, lead_stage=lead_stage, limit=limit, offset=offset
        )
        so_khach, so_phien = await repo.dem_tong(
            conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen, lead_stage=lead_stage
        )
    return TrangKhach(items=[_ra_khach(r) for r in hang], tongKhach=so_khach, tongPhien=so_phien)
```

- [ ] **Step 6: Chạy test, xác nhận qua**

Run: `uv run pytest tests/modules/ops -q`
Expected: `test_lead.py` 12 passed; các test ops khác không đổi so với baseline.

- [ ] **Step 7: Chạy cổng cách ly + lint**

Run: `make test-isolation && uv run ruff check . && uv run ruff format --check .`
Expected: isolation xanh; ruff sạch (nếu format lệch: `uv run ruff format src tests` rồi chạy lại).

- [ ] **Step 8: Commit**

```bash
git add tests/modules/ops/test_lead.py
git commit -m "feat(ops): latest lead per customer and lead_stage filter on /convos/khach

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/portal/modules/ops/repo.py src/portal/modules/ops/contracts.py src/portal/modules/ops/router.py \
  tests/modules/ops/conftest.py tests/modules/ops/test_lead.py
```

### Task 2: Lead của từng phiên ở `/convos/khach/{phone}/phien` và `/convos/phien/{id}`

**Files:**
- Modify: `src/portal/modules/ops/repo.py` (`liet_ke_phien`, `doc_phien`, hằng mới)
- Modify: `src/portal/modules/ops/contracts.py` (`PhienOut`)
- Modify: `src/portal/modules/ops/router.py` (`_ra_phien`)
- Test: `tests/modules/ops/test_lead.py`

**Interfaces:**
- Consumes: `them_ca(..., lead_stage, lead_score, audience)` (Task 1).
- Produces: hàng của `repo.liet_ke_phien` / `repo.doc_phien` có thêm `lead_stage`, `lead_score`, `audience`; `PhienOut.leadStage/leadScore/audience`.

- [ ] **Step 1: Viết test hỏng** — thêm vào cuối `tests/modules/ops/test_lead.py`:

```python
async def test_lead_tung_phien(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s2", phone=A, bat_dau=luc(25))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="lead", lead_score=30, tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="mql", lead_score=65, audience="broker", tao_luc=luc(20, 11))

    hang = await repo.liet_ke_phien(conn_ops, phone=A)

    theo = {r["session_id"]: (r["lead_stage"], r["lead_score"], r["audience"]) for r in hang}
    assert theo == {"s1": ("mql", 65, "broker"), "s2": (None, None, None)}


async def test_lead_phien_khong_nhan_ban_hang_theo_so_luot(conn_ops):
    """LATERAL + LEFT JOIN lượt: GROUP BY phải gồm cột lead, không được nhân số lượt."""
    from .conftest import them_luot

    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_luot(conn_ops, "s1", 1)
    await them_luot(conn_ops, "s1", 2)
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql")

    (r,) = await repo.liet_ke_phien(conn_ops, phone=A)

    assert (r["so_luot"], r["lead_stage"]) == (2, "sql")


async def test_doc_phien_co_lead(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="hen_gap", lead_score=90, audience="end_user")

    r = await repo.doc_phien(conn_ops, "s1")

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == ("hen_gap", 90, "end_user")


async def test_api_phien_tra_lead_camelcase(client_ops, conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_score=70)

    ds = (await client_ops.get(f"/api/v1/convos/khach/{A}/phien")).json()
    ct = (await client_ops.get("/api/v1/convos/phien/s1")).json()

    assert (ds[0]["leadStage"], ds[0]["leadScore"], ds[0]["audience"]) == ("sql", 70, None)
    assert ct["phien"]["leadStage"] == "sql"
```

- [ ] **Step 2: Chạy, xác nhận hỏng**

Run: `uv run pytest tests/modules/ops/test_lead.py -q -k "phien"`
Expected: FAIL — `KeyError: 'lead_stage'`.

- [ ] **Step 3: Cài repo**

Trong `repo.py`, ngay SAU `_COT_PHIEN`, thêm:

```python
_LEAD_PHIEN = """
    LEFT JOIN LATERAL (
        SELECT e.lead_stage, e.lead_score, e.audience
          FROM tenant_data.escalations e
         WHERE e.tenant_id = portal.current_tenant()
           AND e.session_id = c.session_id
           AND e.lead_stage IS NOT NULL
         ORDER BY e.created_at DESC, e.id DESC
         LIMIT 1
    ) l ON TRUE
"""
"""Lead của PHIÊN = hàng ca mới nhất CÓ stage của phiên đó; ba trường cùng một hàng (spec §2)."""

_COT_LEAD = "l.lead_stage, l.lead_score, l.audience"
```

Trong `liet_ke_phien`, câu SQL đổi thành (chèn `_LEAD_PHIEN` TRƯỚC join lượt, thêm `_COT_LEAD` vào SELECT và GROUP BY):

```python
            f"""
            SELECT {_COT_PHIEN}, {_COT_LEAD}, {_TEN_DU_AN.format(cot="c.project")}, count(m.seq) AS so_luot,
                   (array_agg(m.content ORDER BY m.seq)
                      FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
              FROM tenant_data.conversations c
              {_LEAD_PHIEN}
              LEFT JOIN tenant_data.conversation_messages m
                     ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
             WHERE c.tenant_id = portal.current_tenant()
               AND c.phone IS NOT DISTINCT FROM $1
             GROUP BY {_COT_PHIEN}, {_COT_LEAD}, c.created_at
             ORDER BY COALESCE(c.started_at, c.created_at) DESC
            """,
```

Trong `doc_phien`, câu SQL đổi tương tự:

```python
        f"""
        SELECT {_COT_PHIEN}, {_COT_LEAD}, {_TEN_DU_AN.format(cot="c.project")}, c.skill_calls, count(m.seq) AS so_luot,
               (array_agg(m.content ORDER BY m.seq)
                  FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
          FROM tenant_data.conversations c
          {_LEAD_PHIEN}
          LEFT JOIN tenant_data.conversation_messages m
                 ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
         WHERE c.tenant_id = portal.current_tenant() AND c.session_id = $1
         GROUP BY {_COT_PHIEN}, {_COT_LEAD}, c.skill_calls, c.created_at
        """,
```

- [ ] **Step 4: Cài contract + router**

`contracts.py` — thêm vào CUỐI `PhienOut` (sau `phone: str | None`):

```python
    leadStage: str | None = None
    """Lead của CHÍNH phiên này (hàng ca mới nhất có stage). NULL = phiên không chuyển sale."""
    leadScore: int | None = None
    audience: str | None = None
```

`router.py` — `_ra_phien` thêm ba đối số cuối cho `PhienOut(...)`:

```python
        leadStage=r["lead_stage"],
        leadScore=r["lead_score"],
        audience=r["audience"],
```

- [ ] **Step 5: Chạy test + cổng**

Run: `uv run pytest tests/modules/ops -q && make test-isolation && uv run ruff check . && uv run ruff format --check .`
Expected: `test_lead.py` 16 passed; phần còn lại khớp baseline; isolation + ruff sạch.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(ops): per-session lead on session list and session detail

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/portal/modules/ops/repo.py src/portal/modules/ops/contracts.py src/portal/modules/ops/router.py \
  tests/modules/ops/test_lead.py
```

---

## PHẦN B — FRONTEND (`odyssey-portal-frontend`)

Chạy test FE: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run <tệp>`. Baseline toàn suite trước Task 3: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -4` (đo 2026-09-30: 102 tệp · 1300 pass · 11 skip, CÓ tính 5 bài của việc hết phiên chưa commit).

### Task 3: Token màu + `lead.ts` + `ChipStage` + cổng tương phản

**Files:**
- Modify: `src/styles/theme.css` (thêm 12 token vào khối `@theme`, ngay sau `--color-badge-kenh-voice-vien`)
- Create: `src/features/ops/lead.ts`
- Create: `src/features/ops/components/ChipStage.tsx`
- Test: `tests/chip-stage-mau.test.ts` (mới), `tests/chip-stage.test.tsx` (mới)

**Interfaces:**
- Produces (`lead.ts`): `BAC_LEAD: readonly ['lead','mql','sql','hen_gap']` · `type BacLead` · `NHAN_BAC: Record<BacLead, string>` · `laBacLead(v: unknown): v is BacLead` · `type LocStage = BacLead | 'none'` · `laLocStage(v: unknown): v is LocStage` · `nhanDoiTuong(a: string): string`.
- Produces (`ChipStage.tsx`): `ChipStage({ stage }: { stage: string })` · `DiemLead({ diem }: { diem: number })` · `TomTatLead({ stage, diem, doiTuong }: { stage: string | null | undefined; diem: number | null | undefined; doiTuong: string | null | undefined })`.

- [ ] **Step 1: Viết cổng tương phản (hỏng vì chưa có token)**

Tạo `tests/chip-stage-mau.test.ts`:

```ts
/**
 * Chip stage phải đọc được và NỔI trên mọi nền nó đứng lên — cùng lý do cổng
 * `chip-kenh-mau`: jsdom không vẽ, chỉ số học bắt được lớp lỗi này. Nền quan trọng
 * nhất là `acs` — hàng phiên ĐANG CHỌN ở `/convos/$phone`, chỗ chip kênh từng tàng hình.
 */
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const THEME = path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/styles/theme.css')

function doSang(hex: string): number {
  const h = hex.replace('#', '')
  const k = [0, 2, 4]
    .map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * (k[0] as number) + 0.7152 * (k[1] as number) + 0.0722 * (k[2] as number)
}

function tuongPhan(a: string, b: string): number {
  const [x, y] = [doSang(a), doSang(b)]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

async function docToken(): Promise<Record<string, string>> {
  const css = await readFile(THEME, 'utf8')
  const ra: Record<string, string> = {}
  for (const [, ten, gt] of css.matchAll(/(--color-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    ra[ten as string] = (gt as string).toLowerCase()
  }
  return ra
}

const BAC = [1, 2, 3, 4] as const

describe('ChipStage — bốn bậc phễu', () => {
  it('chữ trên nền chip đạt WCAG AA (4.5)', async () => {
    const t = await docToken()
    for (const b of BAC) {
      const bg = t[`--color-lead-${b}-bg`] as string
      const fg = t[`--color-lead-${b}-fg`] as string
      expect(tuongPhan(fg, bg), `chữ/nền bậc ${b}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('RANH GIỚI chip (viền, hoặc chính nền với chip đặc) tách khỏi nền `acs` và nền thẻ ≥ 3', async () => {
    const t = await docToken()
    for (const nen of ['--color-acs', '--color-n1', '--color-n0']) {
      for (const b of BAC) {
        const vien = t[`--color-lead-${b}-vien`] as string
        expect(tuongPhan(vien, t[nen] as string), `viền bậc ${b} vs ${nen}`).toBeGreaterThanOrEqual(3)
      }
    }
  })

  it('viền bậc 1–3 tách khỏi chính nền chip ≥ 3 (bậc 4 là chip đặc, viền = nền)', async () => {
    const t = await docToken()
    for (const b of [1, 2, 3] as const) {
      const vien = t[`--color-lead-${b}-vien`] as string
      const bg = t[`--color-lead-${b}-bg`] as string
      expect(tuongPhan(vien, bg), `viền/nền bậc ${b}`).toBeGreaterThanOrEqual(3)
    }
  })
})
```

- [ ] **Step 2: Viết test component (hỏng vì chưa có tệp)**

Tạo `tests/chip-stage.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChipStage, TomTatLead } from '@/features/ops/components/ChipStage'
import { laLocStage, nhanDoiTuong } from '@/features/ops/lead'

describe('ChipStage', () => {
  it('bốn bậc hiện đúng nhãn và lớp màu của bậc', () => {
    render(
      <>
        <ChipStage stage="lead" />
        <ChipStage stage="mql" />
        <ChipStage stage="sql" />
        <ChipStage stage="hen_gap" />
      </>,
    )
    expect(screen.getByText('Lead')).toHaveClass('bg-lead-1-bg')
    expect(screen.getByText('MQL')).toHaveClass('bg-lead-2-bg')
    expect(screen.getByText('SQL')).toHaveClass('bg-lead-3-bg')
    expect(screen.getByText('Hẹn gặp')).toHaveClass('bg-lead-4-bg')
  })

  it('stage LẠ hiện nguyên văn bằng chip trung tính, không crash', () => {
    render(<ChipStage stage="chot" />)
    expect(screen.getByText('chot')).toHaveClass('bg-badge-neutral-bg')
  })
})

describe('TomTatLead', () => {
  it('không có stage ⇒ chữ «Chưa phân loại», không chip', () => {
    render(<TomTatLead stage={null} diem={null} doiTuong={null} />)
    expect(screen.getByText('Chưa phân loại')).toBeInTheDocument()
  })

  it('đủ ba trường ⇒ chip + «90 điểm» + «· Khách mua»', () => {
    const { container } = render(<TomTatLead stage="hen_gap" diem={90} doiTuong="end_user" />)
    expect(screen.getByText('Hẹn gặp')).toBeInTheDocument()
    expect(container.textContent).toContain('90điểm')
    expect(container.textContent).toContain('· Khách mua')
  })

  it('có stage nhưng thiếu điểm và đối tượng ⇒ chỉ chip, không «null»/«·» thừa', () => {
    const { container } = render(<TomTatLead stage="sql" diem={null} doiTuong={undefined} />)
    expect(container.textContent).toBe('SQL')
  })

  it('có đối tượng mà thiếu điểm ⇒ không mở đầu bằng «·»', () => {
    const { container } = render(<TomTatLead stage="sql" diem={null} doiTuong="broker" />)
    expect(container.textContent).toBe('SQLMôi giới')
  })
})

describe('lead.ts', () => {
  it('nhanDoiTuong dịch hai mã đã biết, giữ nguyên mã lạ', () => {
    expect(nhanDoiTuong('end_user')).toBe('Khách mua')
    expect(nhanDoiTuong('broker')).toBe('Môi giới')
    expect(nhanDoiTuong('investor')).toBe('investor')
  })

  it('laLocStage chỉ nhận bốn bậc + none', () => {
    expect(['lead', 'mql', 'sql', 'hen_gap', 'none'].every(laLocStage)).toBe(true)
    expect(laLocStage('xyz')).toBe(false)
    expect(laLocStage(undefined)).toBe(false)
  })
})
```

- [ ] **Step 3: Chạy, xác nhận hỏng**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/chip-stage-mau.test.ts tests/chip-stage.test.tsx`
Expected: FAIL — token `undefined`; `Failed to resolve import "@/features/ops/components/ChipStage"`.

- [ ] **Step 4: Thêm token vào `theme.css`**

Ngay SAU dòng `--color-badge-kenh-voice-vien: …;` (vẫn trong `@theme`), chèn:

```css

  /* Chip STAGE của lead (`features/ops/components/ChipStage.tsx`) — bốn bậc phễu
     lead → mql → sql → hen_gap, ẤM DẦN: đá → cát → mơ → đất nung đặc. Họ ấm có chủ ý:
     trên cùng màn teal đã là «Đã chuyển sales», xanh dương là Chat, tím là Voice.
     Đo (cổng `tests/chip-stage-mau.test.ts`): chữ/nền ≥ 5.11 · viền/acs ≥ 3.20 ·
     viền/surface ≥ 3.64 · viền/nền chip ≥ 3.19. Bậc 4 là chip ĐẶC: nền chính là ranh giới. */
  --color-lead-1-bg: #f0efec;
  --color-lead-1-fg: #5f656e;
  --color-lead-1-vien: #8a857b;
  --color-lead-2-bg: #fbf1dc;
  --color-lead-2-fg: #7a5410;
  --color-lead-2-vien: #a57c2c;
  --color-lead-3-bg: #fde6d4;
  --color-lead-3-fg: #9a3f0c;
  --color-lead-3-vien: #c46a33;
  --color-lead-4-bg: #b4501a;
  --color-lead-4-fg: #ffffff;
  --color-lead-4-vien: #b4501a;
```

- [ ] **Step 5: Tạo `src/features/ops/lead.ts`**

```ts
/**
 * Lead của khách — bậc phễu, nhãn và đối tượng. MỘT chỗ cho cả chip, bộ lọc và route.
 *
 * Nguồn: `tenant_data.escalations` (migration backend `0968`), agent ghi. Tập bậc do
 * người dùng chốt 2026-09-30 (spec `2026-09-30-lead-tren-convos-design.md`). Bậc LẠ agent
 * ghi thêm vẫn tới được FE: nó hiện nguyên văn bằng chip trung tính, không vào bộ lọc.
 */
export const BAC_LEAD = ['lead', 'mql', 'sql', 'hen_gap'] as const
export type BacLead = (typeof BAC_LEAD)[number]

export const NHAN_BAC: Record<BacLead, string> = {
  lead: 'Lead',
  mql: 'MQL',
  sql: 'SQL',
  hen_gap: 'Hẹn gặp',
}

export function laBacLead(v: unknown): v is BacLead {
  return typeof v === 'string' && (BAC_LEAD as readonly string[]).includes(v)
}

/** Giá trị bộ lọc `?stage=` / `lead_stage`: bốn bậc + `none` (khách chưa có lead). */
export type LocStage = BacLead | 'none'

export function laLocStage(v: unknown): v is LocStage {
  return v === 'none' || laBacLead(v)
}

const DOI_TUONG: Record<string, string> = { end_user: 'Khách mua', broker: 'Môi giới' }

/** Mã lạ hiện NGUYÊN VĂN — đoán một nhãn tiếng Việt cho mã không biết là nói sai. */
export function nhanDoiTuong(a: string): string {
  return DOI_TUONG[a] ?? a
}
```

- [ ] **Step 6: Tạo `src/features/ops/components/ChipStage.tsx`**

```tsx
import { NHAN_BAC, laBacLead, nhanDoiTuong, type BacLead } from '../lead'

/**
 * Chip bậc phễu. CHỈ NHÃN (người dùng chốt 2026-09-30, bỏ chấm phễu) — nhãn tự nói bậc,
 * màu ấm dần củng cố. Mỗi chuỗi lớp mang `border` CÙNG token viền của nó: cổng
 * `vien-tran` đòi màu viền nằm trong cùng chuỗi, và viết trọn lớp ở đây để Tailwind
 * quét thấy (ghép `bg-lead-${n}` động thì lớp bị cắt khỏi bundle).
 */
const LOP: Record<BacLead, string> = {
  lead: 'border border-lead-1-vien bg-lead-1-bg text-lead-1-fg',
  mql: 'border border-lead-2-vien bg-lead-2-bg text-lead-2-fg',
  sql: 'border border-lead-3-vien bg-lead-3-bg text-lead-3-fg',
  hen_gap: 'border border-lead-4-vien bg-lead-4-bg text-lead-4-fg',
}

const LOP_LA = 'border border-border-strong bg-badge-neutral-bg text-badge-neutral-fg'

export function ChipStage({ stage }: { stage: string }) {
  const bac = laBacLead(stage)
  return (
    <span
      data-stage={stage}
      className={`inline-flex h-[22px] items-center whitespace-nowrap rounded-full px-[9px] text-[11.5px] font-semibold ${bac ? LOP[stage] : LOP_LA}`}
    >
      {bac ? NHAN_BAC[stage] : stage}
    </span>
  )
}

/** «90 điểm» — số thô, không thang (người dùng chốt: điểm chạy 30–120, không gắn với bậc). */
export function DiemLead({ diem }: { diem: number }) {
  return (
    <span className="font-mono text-[12.5px] tabular-nums text-fg">
      {diem}
      <span className="ml-[3px] font-sans text-[11.5px] text-muted-2">điểm</span>
    </span>
  )
}

/** Ô lead ở hàng khách: chip trên, «điểm · đối tượng» dưới. Phần nào NULL thì bỏ phần đó. */
export function TomTatLead({
  stage,
  diem,
  doiTuong,
}: {
  stage: string | null | undefined
  diem: number | null | undefined
  doiTuong: string | null | undefined
}) {
  if (!stage) return <span className="block text-[12px] text-muted-2">Chưa phân loại</span>
  const coDiem = diem !== null && diem !== undefined
  return (
    <>
      <span className="block">
        <ChipStage stage={stage} />
      </span>
      {(coDiem || doiTuong) && (
        <span className="mt-1.5 flex items-baseline gap-1.5 text-[12px] text-muted">
          {coDiem && <DiemLead diem={diem} />}
          {doiTuong && <span>{coDiem ? `· ${nhanDoiTuong(doiTuong)}` : nhanDoiTuong(doiTuong)}</span>}
        </span>
      )}
    </>
  )
}
```

- [ ] **Step 7: Chạy test + cổng cấu trúc**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/chip-stage-mau.test.ts tests/chip-stage.test.tsx tests/vien-tran.test.ts tests/module-boundaries.test.ts`
Expected: tất cả PASS.

- [ ] **Step 8: Commit**

```bash
git add src/features/ops/lead.ts src/features/ops/components/ChipStage.tsx tests/chip-stage-mau.test.ts tests/chip-stage.test.tsx
git commit -m "feat(ops): ChipStage — four warm funnel steps with contrast gate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/styles/theme.css src/features/ops/lead.ts src/features/ops/components/ChipStage.tsx \
  tests/chip-stage-mau.test.ts tests/chip-stage.test.tsx
```

### Task 4: Kiểu API + cột Lead ở hàng khách + dữ liệu giả MSW

**Files:**
- Modify: `src/features/ops/api.ts` (`Khach`, `Phien`, `LocKhach`, `danhSachKhach`)
- Modify: `src/features/ops/components/KhachRow.tsx`
- Modify: `src/features/ops/msw.ts` (`KHACH_GIA`, `PHIEN_ANH_1`, `PHIEN_ANH_2`, handler `/convos/khach`)
- Test: `tests/convos-list.test.tsx`

**Interfaces:**
- Consumes: `TomTatLead` (Task 3), `LocStage` (Task 3).
- Produces: `Khach.leadStage?/leadScore?/audience?` · `Phien.leadStage?/leadScore?/audience?` (đều `… | null`, tuỳ chọn) · `LocKhach.stage?: LocStage` · `danhSachKhach` gửi `lead_stage` khi `loc.stage` có.

- [ ] **Step 1: Viết test hỏng** — thêm vào cuối `tests/convos-list.test.tsx` (trong file, TRƯỚC dòng cuối nếu có `})` đóng describe thì thêm `describe` mới ở cuối tệp):

```tsx
describe('cột Lead trên danh sách khách', () => {
  function trangCo(items: object[]) {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ tongKhach: items.length, tongPhien: items.length, items }),
      ),
    )
  }
  const goc = {
    soPhien: 1,
    ganNhat: '2026-07-27T14:22:00+07:00',
    dauTien: '2026-07-27T14:22:00+07:00',
    daChuyen: false,
    summaryCuoi: null,
    duAn: null,
    tenDuAn: null,
  }

  it('hiện chip + điểm + đối tượng trong cột riêng của hàng', async () => {
    trangCo([{ ...goc, phone: '0911', ten: 'An', leadStage: 'sql', leadScore: 120, audience: 'broker' }])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(within(cot).getByText('SQL')).toBeInTheDocument()
    expect(cot.textContent).toContain('120điểm')
    expect(cot.textContent).toContain('Môi giới')
  })

  it('khách chưa có lead ⇒ «Chưa phân loại» mờ, không chip', async () => {
    trangCo([{ ...goc, phone: '0912', ten: 'Bình', leadStage: null, leadScore: null, audience: null }])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(cot.textContent).toBe('Chưa phân loại')
  })

  it('backend cũ chưa trả khoá lead ⇒ vẫn «Chưa phân loại», không «undefined»', async () => {
    trangCo([{ ...goc, phone: '0913', ten: 'Chi' }])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(cot.textContent).toBe('Chưa phân loại')
  })

  it('stage lạ hiện nguyên văn', async () => {
    trangCo([{ ...goc, phone: '0914', ten: 'Dũng', leadStage: 'chot', leadScore: 50, audience: null }])
    dung()
    expect(await screen.findByText('chot')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy, xác nhận hỏng**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/convos-list.test.tsx`
Expected: 4 bài mới FAIL — `Unable to find an element by: [data-testid="cot-lead"]`.

- [ ] **Step 3: Kiểu API** — trong `src/features/ops/api.ts`:

Thêm import đầu tệp (cạnh các import khác): `import type { LocStage } from './lead'`

Thêm vào CUỐI `interface Khach`:

```ts
  /** Lead MỚI NHẤT của khách — lead của phiên mới nhất có lead (spec §2). `null` = chưa
   *  phân loại. TUỲ CHỌN: backend cũ chưa trả khoá ⇒ `undefined`, xử như `null`. */
  readonly leadStage?: string | null
  readonly leadScore?: number | null
  readonly audience?: string | null
```

Thêm vào CUỐI `interface Phien`:

```ts
  /** Lead của CHÍNH phiên này. `null` = phiên không chuyển sale. Tuỳ chọn như `Khach`. */
  readonly leadStage?: string | null
  readonly leadScore?: number | null
  readonly audience?: string | null
```

Thêm vào `interface LocKhach` (sau `daChuyen`):

```ts
  /** Lọc theo lead mới nhất; `'none'` = khách chưa có lead. Vắng = mọi stage. */
  readonly stage?: LocStage
```

Trong `danhSachKhach`, ngay sau dòng `p.set('tu_ngay', …)`, thêm:

```ts
  if (loc.stage) p.set('lead_stage', loc.stage)
```

- [ ] **Step 4: Cột Lead trong `KhachRow.tsx`**

Thêm import: `import { TomTatLead } from './ChipStage'`

Chèn khối sau NGAY TRƯỚC `<span className="w-[132px] shrink-0 self-stretch …">` (cột thời gian):

```tsx
      {/* CỘT LEAD RIÊNG (spec §4.2): việc chính của màn là DÒ MẮT DỌC «ai đang nóng»,
          chen chip vào hàng chip dự án thì mỗi hàng nằm một chỗ. Cùng kẻ dọc
          `border-border-soft` với hai cột kia. Mobile: rơi xuống dưới tóm tắt. */}
      <span
        data-testid="cot-lead"
        className="w-[158px] shrink-0 self-stretch border-l border-border-soft pl-4 pt-px max-md:order-last max-md:w-auto max-md:basis-full max-md:border-l-0 max-md:pl-0"
      >
        <TomTatLead stage={khach.leadStage} diem={khach.leadScore} doiTuong={khach.audience} />
      </span>
```

- [ ] **Step 5: Dữ liệu giả MSW** — trong `src/features/ops/msw.ts`:

Item `phone: '0912448111'` của `KHACH_GIA` thêm: `leadStage: 'hen_gap', leadScore: 90, audience: 'end_user',`
Item `phone: '0987112222'` thêm: `leadStage: 'mql', leadScore: 65, audience: null,`
Item `phone: ''` thêm: `leadStage: null, leadScore: null, audience: null,`
`PHIEN_ANH_1` (`s-anh-1`) thêm: `leadStage: 'hen_gap', leadScore: 90, audience: 'end_user',`
`PHIEN_ANH_2` (`s-anh-2`) thêm: `leadStage: 'sql', leadScore: 70, audience: 'end_user',`

Handler `/api/v1/convos/khach` thay bằng (lọc như backend, tổng theo tập đã lọc):

```ts
  http.get('/api/v1/convos/khach', ({ request }) => {
    const u = new URL(request.url)
    const offset = Number(u.searchParams.get('offset') ?? 0)
    const limit = Number(u.searchParams.get('limit') ?? 10)
    const stage = u.searchParams.get('lead_stage')
    if (!stage) {
      return HttpResponse.json({ ...KHACH_GIA, items: KHACH_GIA.items.slice(offset, offset + limit) })
    }
    const loc = KHACH_GIA.items.filter((k) =>
      stage === 'none' ? !k.leadStage : k.leadStage === stage,
    )
    return HttpResponse.json({
      tongKhach: loc.length,
      tongPhien: loc.reduce((s, k) => s + k.soPhien, 0),
      items: loc.slice(offset, offset + limit),
    })
  }),
```

- [ ] **Step 6: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/convos-list.test.tsx tests/convos-phien.test.tsx tests/overview-man.test.tsx tests/boot.test.tsx`
Expected: tất cả PASS (bài cũ không đổi — nếu một bài cũ đếm chữ trên màn và đụng «Hẹn gặp»/«MQL» mới, thu hẹp truy vấn bài đó bằng `within(...)`, KHÔNG xoá dữ liệu giả).

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(ops): Lead column on the /convos customer row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/features/ops/api.ts src/features/ops/components/KhachRow.tsx src/features/ops/msw.ts tests/convos-list.test.tsx
```

### Task 5: Ô lọc stage (`LocStage`) + nối vào `KhachList` + search param `?stage=`

**Files:**
- Create: `src/features/ops/components/LocStage.tsx`
- Modify: `src/features/ops/components/KhachList.tsx` (thanh lọc)
- Modify: `src/routes/_app/convos.index.tsx` (`TimKiem`, `validateSearch`, `loc`, `datLoc`)
- Test: `tests/loc-stage.test.tsx` (mới), `tests/convos-list.test.tsx`

**Interfaces:**
- Consumes: `ChipStage` (Task 3), `BAC_LEAD`/`NHAN_BAC`/`LocStage`/`laLocStage` (Task 3), `LocKhach.stage` (Task 4).
- Produces: `LocStage({ gia, doi }: { gia: LocStage | undefined; doi: (v: LocStage | undefined) => void })`.

- [ ] **Step 1: Viết test component hỏng** — tạo `tests/loc-stage.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LocStage } from '@/features/ops/components/LocStage'

function nut() {
  return screen.getByRole('button', { name: /stage/i })
}

describe('LocStage — một ô, bấm mới mở menu', () => {
  it('đóng sẵn: chỉ một nút ghi «Tất cả», không có menu', () => {
    render(<LocStage gia={undefined} doi={() => {}} />)
    expect(nut()).toHaveTextContent('Tất cả')
    expect(nut()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('bấm mở menu đủ sáu mục theo thứ tự phễu', async () => {
    render(<LocStage gia={undefined} doi={() => {}} />)
    await userEvent.click(nut())
    const muc = screen.getAllByRole('menuitemradio').map((m) => m.textContent)
    expect(muc).toEqual(['Tất cả', 'Lead', 'MQL', 'SQL', 'Hẹn gặp', 'Chưa phân loại'])
    expect(nut()).toHaveAttribute('aria-expanded', 'true')
  })

  it('chọn một mục ⇒ gọi `doi` đúng giá trị và đóng menu', async () => {
    const doi = vi.fn()
    render(<LocStage gia={undefined} doi={doi} />)
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'SQL' }))
    expect(doi).toHaveBeenCalledWith('sql')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('«Tất cả» ⇒ `doi(undefined)`; «Chưa phân loại» ⇒ `doi("none")`', async () => {
    const doi = vi.fn()
    render(<LocStage gia="sql" doi={doi} />)
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Tất cả' }))
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Chưa phân loại' }))
    expect(doi.mock.calls).toEqual([[undefined], ['none']])
  })

  it('đang lọc ⇒ ô hiện CHÍNH chip của stage và mục đó được đánh dấu', async () => {
    render(<LocStage gia="hen_gap" doi={() => {}} />)
    expect(nut().querySelector('[data-stage="hen_gap"]')).not.toBeNull()
    await userEvent.click(nut())
    expect(screen.getByRole('menuitemradio', { name: 'Hẹn gặp' })).toHaveAttribute('aria-checked', 'true')
  })

  it('Esc và bấm ra ngoài đều đóng menu', async () => {
    render(
      <>
        <LocStage gia={undefined} doi={() => {}} />
        <p>ngoài</p>
      </>,
    )
    await userEvent.click(nut())
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await userEvent.click(nut())
    await userEvent.click(screen.getByText('ngoài'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('↓/↑ đi giữa các mục, Enter chọn', async () => {
    const doi = vi.fn()
    render(<LocStage gia={undefined} doi={doi} />)
    await userEvent.click(nut())
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(doi).toHaveBeenCalledWith('mql')
  })

  it('menu PORTAL ra body — không nằm trong khối cha (tấm nền `overflow-hidden` sẽ cắt nó)', async () => {
    const { container } = render(<LocStage gia={undefined} doi={() => {}} />)
    await userEvent.click(nut())
    expect(container.contains(screen.getByRole('menu'))).toBe(false)
  })
})
```

Chú ý bài ↓/↑: mở menu thì focus nằm ở mục ĐANG CHỌN («Tất cả» khi chưa lọc); ↓ hai lần ⇒ «MQL».

- [ ] **Step 2: Chạy, xác nhận hỏng**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/loc-stage.test.tsx`
Expected: FAIL — `Failed to resolve import "@/features/ops/components/LocStage"`.

- [ ] **Step 3: Tạo `src/features/ops/components/LocStage.tsx`**

```tsx
import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '@/components/icons'
import { CAO_O } from '@/components/ui/Bang'
import { BAC_LEAD, NHAN_BAC, type LocStage as GiaLoc } from '../lead'
import { ChipStage } from './ChipStage'

/**
 * Bộ lọc stage — MỘT ô 36px, bấm mới mở menu (người dùng chốt 2026-09-30: bày sáu nút
 * ra thì chiếm chỗ). Không dùng `<select>` gốc: option gốc không vẽ được chip màu, mà
 * chip trong menu là thứ dạy màu nào là bậc nào.
 *
 * Menu PORTAL ra `document.body`, `position: fixed` theo toạ độ nút: tấm nền
 * `KhachList` mang `overflow-hidden`, lọc ra 0 khách thì tấm nền chỉ cao ~200px và
 * một menu `absolute` bị cắt mất (cùng bài học `HopTip`, CLAUDE.md 2026-08-14).
 * Menu `fixed` không đi theo nút khi cuộn ⇒ cuộn/đổi cỡ cửa sổ là đóng.
 */
const MUC: readonly { gia: GiaLoc | undefined; nhan: string }[] = [
  { gia: undefined, nhan: 'Tất cả' },
  ...BAC_LEAD.map((b) => ({ gia: b, nhan: NHAN_BAC[b] })),
  { gia: 'none', nhan: 'Chưa phân loại' },
]

const RONG_MENU = 220
const CAO_MENU_UOC = 290 // 6 mục × ~36px + 2 kẻ + đệm — đủ để quyết lật, không cần đo

export function LocStage({ gia, doi }: { gia: GiaLoc | undefined; doi: (v: GiaLoc | undefined) => void }) {
  const [mo, setMo] = useState(false)
  const [viTri, setViTri] = useState<{ left: number; top: number } | null>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const mucRef = useRef<(HTMLButtonElement | null)[]>([])
  const dangChon = Math.max(
    0,
    MUC.findIndex((m) => m.gia === gia),
  )

  useLayoutEffect(() => {
    if (!mo || !nutRef.current) return
    const r = nutRef.current.getBoundingClientRect()
    const latLen = r.bottom + 6 + CAO_MENU_UOC > window.innerHeight && r.top - 6 - CAO_MENU_UOC > 0
    setViTri({ left: r.left, top: latLen ? r.top - 6 - CAO_MENU_UOC : r.bottom + 6 })
  }, [mo])

  useEffect(() => {
    if (!mo) return
    mucRef.current[dangChon]?.focus()
    const dong = () => setMo(false)
    const bamNgoai = (e: MouseEvent) => {
      const t = e.target as Node
      if (!menuRef.current?.contains(t) && !nutRef.current?.contains(t)) dong()
    }
    document.addEventListener('mousedown', bamNgoai)
    window.addEventListener('scroll', dong, true)
    window.addEventListener('resize', dong)
    return () => {
      document.removeEventListener('mousedown', bamNgoai)
      window.removeEventListener('scroll', dong, true)
      window.removeEventListener('resize', dong)
    }
  }, [mo, dangChon])

  const chon = (v: GiaLoc | undefined) => {
    doi(v)
    setMo(false)
    nutRef.current?.focus()
  }

  const phim = (e: KeyboardEvent) => {
    const i = mucRef.current.findIndex((el) => el === document.activeElement)
    if (e.key === 'Escape') {
      e.preventDefault()
      setMo(false)
      nutRef.current?.focus()
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const buoc = e.key === 'ArrowDown' ? 1 : -1
      mucRef.current[(i + buoc + MUC.length) % MUC.length]?.focus()
    }
  }

  const lopNut = mo
    ? 'border border-ac bg-surface ring-[3px] ring-acs'
    : gia
      ? 'border border-ac bg-surface'
      : 'border border-border-field bg-bg'

  return (
    <>
      <button
        ref={nutRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={mo}
        onClick={() => setMo((v) => !v)}
        className={`${CAO_O} ${lopNut} flex min-w-[176px] cursor-pointer items-center gap-2 rounded-md pl-3 pr-2.5 text-[13.5px] max-md:min-w-0`}
      >
        <span className="text-muted-2">Stage</span>
        {gia && gia !== 'none' ? (
          <ChipStage stage={gia} />
        ) : (
          <span className="font-medium text-fg">{gia === 'none' ? 'Chưa phân loại' : 'Tất cả'}</span>
        )}
        <span className={`ml-auto text-muted-2 transition-transform ${mo ? 'rotate-180' : ''}`}>
          <Icon name="moXuong" className="size-3.5" />
        </span>
      </button>
      {mo &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label="Lọc theo stage"
            onKeyDown={phim}
            style={viTri ? { left: viTri.left, top: viTri.top, width: RONG_MENU } : { width: RONG_MENU }}
            className="fixed z-[80] rounded-lg border border-border-strong bg-surface p-1.5 shadow-[0_10px_30px_-10px_rgba(20,22,26,0.22),0_2px_6px_rgba(20,22,26,0.06)]"
          >
            {MUC.map((m, i) => (
              <div key={m.nhan}>
                {(i === 1 || i === MUC.length - 1) && <hr className="mx-1 my-1 border-border-soft" />}
                <button
                  ref={(el) => {
                    mucRef.current[i] = el
                  }}
                  type="button"
                  role="menuitemradio"
                  aria-checked={m.gia === gia}
                  onClick={() => chon(m.gia)}
                  className={`flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-[7px] text-left text-[13.5px] outline-none focus-visible:bg-n2 ${
                    m.gia === gia ? 'bg-acs' : 'hover:bg-n2'
                  }`}
                >
                  {m.gia && m.gia !== 'none' ? <ChipStage stage={m.gia} /> : <span className="text-muted">{m.nhan}</span>}
                  <span className={`ml-auto text-[13px] text-ac ${m.gia === gia ? '' : 'invisible'}`}>✓</span>
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  )
}
```

Chỗ phải kiểm khi cài: `Icon` nhận `SVGProps` (không có prop `size`) nên cỡ đặt bằng `className="size-3.5"`; `<hr>` mang `border-border-soft` (cổng `vien-tran` không soi `border-` kèm token, nhưng nếu nó đỏ thì đổi thành `border-t border-border-soft`). Tên truy cập của mục là chữ bên trong (`Lead`, `SQL`…) vì chip mang đúng nhãn đó; dấu ✓ không vào tên vì nó là ký tự rời — nếu `getByRole('menuitemradio', { name: 'SQL' })` trượt vì ✓, thêm `aria-hidden` cho span ✓.

- [ ] **Step 4: Chạy test component**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/loc-stage.test.tsx`
Expected: 8 PASS.

- [ ] **Step 5: Viết test nối dây hỏng** — thêm vào `describe('cột Lead trên danh sách khách', …)` ở `tests/convos-list.test.tsx`:

```tsx
  it('chọn stage trong menu ⇒ `datLoc` nhận `stage` và về trang 1', async () => {
    const datLoc = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ tuNgay: '30', trang: 3 }} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /stage/i }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'SQL' }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ stage: 'sql', trang: 1 }))
  })

  it('loc.stage được gửi lên API thành `lead_stage`', async () => {
    let thamSo: string | null = null
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        thamSo = new URL(request.url).searchParams.get('lead_stage')
        return HttpResponse.json({ tongKhach: 0, tongPhien: 0, items: [] })
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ tuNgay: '30', stage: 'none' }} datLoc={() => {}} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(thamSo).toBe('none'))
  })
```

Chú ý: đổi sang «Tất cả» phải xoá `stage` khỏi object gửi `datLoc`. `doi` của `KhachList` trộn `{...loc, ...p}` nên `doi({ stage: undefined })` để lại khoá `stage: undefined` — với `exactOptionalPropertyTypes` đó là lỗi kiểu; Step 6 xử bằng cách loại khoá khi `undefined`.

- [ ] **Step 6: Nối vào `KhachList.tsx`**

Thêm import: `import { LocStage } from './LocStage'`

Chèn NGAY SAU `</div>` đóng nhóm `KHOANG` (trước `<label className="flex items-center gap-2 …">`):

```tsx
          <LocStage
            gia={loc.stage}
            doi={(v) => {
              if (v) {
                doi({ stage: v })
              } else {
                const { stage: _bo, ...conLai } = loc
                datLoc?.({ ...conLai, trang: 1 })
              }
            }}
          />
```

(Nếu eslint báo `_bo` không dùng, cấu hình repo cho phép tiền tố `_`; nếu không, dùng `void _bo` ngay dưới.)

- [ ] **Step 7: Search param ở `src/routes/_app/convos.index.tsx`**

Thêm import: `import { type LocStage, laLocStage } from '@/features/ops/lead'`

`TimKiem` thêm: `stage?: LocStage | undefined`

`validateSearch` thêm dòng: `stage: laLocStage(s.stage) ? s.stage : undefined,`

Trong `ManDanhSachKhach`, object `loc` thêm: `...(s.stage !== undefined ? { stage: s.stage } : {}),`

Trong `datLoc`: thêm `const stage = l.stage` cạnh các hằng khác; `chiDoiTrang` thêm vế `&& stage === s.stage`; object `search` thêm `stage,`.

- [ ] **Step 8: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/loc-stage.test.tsx tests/convos-list.test.tsx tests/vien-tran.test.ts tests/o-chon.test.ts && npx tsc -b --force`
Expected: tất cả PASS; tsc thoát 0.

- [ ] **Step 9: Commit**

```bash
git add src/features/ops/components/LocStage.tsx tests/loc-stage.test.tsx
git commit -m "feat(ops): one-box stage filter menu on /convos, ?stage= search param

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/features/ops/components/LocStage.tsx src/features/ops/components/KhachList.tsx \
  src/routes/_app/convos.index.tsx tests/loc-stage.test.tsx tests/convos-list.test.tsx
```

### Task 6: Lead ở trang chi tiết khách (`PhienKhach`)

**Files:**
- Modify: `src/features/ops/components/PhienKhach.tsx` (header, hàng phiên, dòng thông tin phiên)
- Test: `tests/convos-phien.test.tsx`

**Interfaces:**
- Consumes: `ChipStage`, `DiemLead` (Task 3); `nhanDoiTuong` (Task 3); `Phien.leadStage/leadScore/audience` (Task 4); backend Task 2.

- [ ] **Step 1: Viết test hỏng** — thêm cuối `tests/convos-phien.test.tsx` (dùng `dung`, `choPhien` có sẵn trong tệp):

```tsx
describe('lead ở trang chi tiết khách', () => {
  const phien = (id: string, bd: string, lead: object) => ({
    sessionId: id,
    ten: 'Nguyễn Minh Anh',
    batDau: bd,
    ketThuc: null,
    soLuot: 3,
    tinNhanDau: 'xin chào',
    summary: null,
    duAn: null,
    tenDuAn: null,
    daChuyen: false,
    runningVersion: null,
    source: 'chat',
    phone: '0912448111',
    ...lead,
  })
  const P1 = phien('p-moi', '2026-07-27T14:00:00+07:00', { leadStage: null, leadScore: null, audience: null })
  const P2 = phien('p-giua', '2026-07-25T14:00:00+07:00', { leadStage: 'hen_gap', leadScore: 90, audience: 'end_user' })
  const P3 = phien('p-cu', '2026-07-20T14:00:00+07:00', { leadStage: 'lead', leadScore: 30, audience: null })

  function datApi() {
    server.use(
      http.get('/api/v1/convos/khach/:phone/phien', () => HttpResponse.json([P1, P2, P3])),
      http.get('/api/v1/convos/phien/:id', ({ params }) => {
        const p = [P1, P2, P3].find((x) => x.sessionId === params.id)
        return HttpResponse.json({ phien: p, luot: [], skillCalls: [] })
      }),
    )
  }

  it('ô «Lead hiện tại» = phiên mới nhất CÓ lead (bỏ qua phiên mới nhất không có lead)', async () => {
    datApi()
    dung()
    const o = await screen.findByTestId('lead-hien-tai')
    expect(within(o).getByText('Hẹn gặp')).toBeInTheDocument()
    expect(o.textContent).toContain('90')
    expect(o.textContent).toContain('Khách mua')
  })

  it('từng hàng phiên mang chip của CHÍNH phiên đó; phiên không có lead thì không chip', async () => {
    datApi()
    dung()
    await screen.findByTestId('lead-hien-tai')
    const cot = screen.getByTestId('cuon-phien')
    expect(cot.querySelectorAll('[data-stage]')).toHaveLength(2)
    expect(cot.querySelector('[data-stage="lead"]')).not.toBeNull()
  })

  it('dòng thông tin phiên hiện stage · điểm · đối tượng của phiên đang xem', async () => {
    datApi()
    dung('0912448111', 'p-giua')
    await choPhien('p-giua')
    const dong = screen.getByTestId('dong-phien')
    expect(dong.querySelector('[data-stage="hen_gap"]')).not.toBeNull()
    expect(dong.textContent).toContain('90điểm')
    expect(dong.textContent).toContain('Khách mua')
  })

  it('phiên có stage nhưng thiếu đối tượng ⇒ dòng thông tin không in «null»', async () => {
    datApi()
    dung('0912448111', 'p-cu')
    await choPhien('p-cu')
    expect(screen.getByTestId('dong-phien').textContent).not.toMatch(/null|undefined/)
  })

  it('khách không có lead nào ⇒ không có ô «Lead hiện tại»', async () => {
    server.use(http.get('/api/v1/convos/khach/:phone/phien', () => HttpResponse.json([P1])))
    dung()
    await screen.findByText(/27\/07\/2026/)
    expect(screen.queryByTestId('lead-hien-tai')).not.toBeInTheDocument()
  })
})
```

Thêm `within` vào import `@testing-library/react` đầu tệp (hiện chỉ có `render, screen, waitFor`). Feedback của phiên (`GET /api/v1/agent/feedback?session_id=…`) đã có fake mặc định ở `features/quality/msw.ts` — không cần dựng lại.

- [ ] **Step 2: Chạy, xác nhận hỏng**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/convos-phien.test.tsx`
Expected: 5 bài mới FAIL — không tìm thấy `lead-hien-tai`.

- [ ] **Step 3: Cài `PhienKhach.tsx`**

Thêm import: `import { ChipStage, DiemLead } from './ChipStage'` và `import { nhanDoiTuong } from '../lead'`

Ngay sau chỗ `ds.data` sẵn sàng (cạnh các biến dẫn xuất như `soChat`/`soVoice`), thêm:

```tsx
  // Lead HIỆN TẠI = phiên mới nhất CÓ lead (spec §2). `ds.data` đã sắp mới nhất trước và
  // lead của mỗi phiên là hàng ca mới nhất của nó ⇒ trùng đúng lead của hàng khách ở
  // `/convos`. Đọc `ds.data`, KHÔNG `dsLoc`: đổi tab kênh không được đổi lead hiện tại.
  const leadNay = ds.data.find((p) => p.leadStage)
```

(Đặt ở chỗ `ds.data` chắc chắn đã có — nếu các biến dẫn xuất nằm sau nhánh `isPending`, đặt cùng chỗ đó.)

Header — thay `<div className="mt-3 flex items-center gap-3">` bằng `<div className="mt-3 flex items-center gap-3 max-md:flex-wrap">`, và chèn trước `</div>` đóng của nó (sau khối tên/số):

```tsx
            {leadNay?.leadStage && (
              <div
                data-testid="lead-hien-tai"
                className="ml-auto flex items-start gap-3.5 rounded-lg border border-border bg-n2 py-2.5 pl-4 pr-3.5 max-md:ml-0 max-md:basis-full"
              >
                <div>
                  <p className="text-[12px] text-muted-2">Lead hiện tại</p>
                  <div className="mt-1.5">
                    <ChipStage stage={leadNay.leadStage} />
                  </div>
                </div>
                {leadNay.leadScore !== null && leadNay.leadScore !== undefined && (
                  <>
                    <span aria-hidden className="w-px self-stretch bg-border" />
                    <div>
                      <p className="text-[12px] text-muted-2">Điểm</p>
                      <p className="mt-1.5 font-mono text-[20px] font-medium leading-[22px] tracking-tight tabular-nums">
                        {leadNay.leadScore}
                      </p>
                    </div>
                  </>
                )}
                {leadNay.audience && (
                  <>
                    <span aria-hidden className="w-px self-stretch bg-border" />
                    <div>
                      <p className="text-[12px] text-muted-2">Đối tượng</p>
                      <p className="mt-1.5 text-[13.5px] font-medium leading-[22px]">
                        {nhanDoiTuong(leadNay.audience)}
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}
```

Hàng phiên — thay khối dòng meta cuối:

```tsx
                          <span className="mt-1 block font-mono text-[11.5px] text-muted-2">
                            {p.soLuot} lượt{dai ? ` · ${dai}` : ''}
                            {p.tenDuAn || p.duAn ? ` · ${p.tenDuAn || p.duAn}` : ''}
                          </span>
```

bằng:

```tsx
                          <span className="mt-1 flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-mono text-[11.5px] text-muted-2">
                              {p.soLuot} lượt{dai ? ` · ${dai}` : ''}
                              {p.tenDuAn || p.duAn ? ` · ${p.tenDuAn || p.duAn}` : ''}
                            </span>
                            {p.leadStage && <ChipStage stage={p.leadStage} />}
                          </span>
```

Dòng thông tin phiên — ngay sau `<span>{ct.data.phien.soLuot} lượt</span>`, chèn:

```tsx
                      {ct.data.phien.leadStage && (
                        <>
                          <span aria-hidden className="h-4 w-px bg-border max-md:hidden" />
                          <ChipStage stage={ct.data.phien.leadStage} />
                          {ct.data.phien.leadScore !== null && ct.data.phien.leadScore !== undefined && (
                            <DiemLead diem={ct.data.phien.leadScore} />
                          )}
                          {ct.data.phien.audience && (
                            <span className="text-[12px] text-muted">
                              {nhanDoiTuong(ct.data.phien.audience)}
                            </span>
                          )}
                        </>
                      )}
```

- [ ] **Step 4: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/convos-phien.test.tsx tests/convos-list.test.tsx && npx tsc -b --force`
Expected: tất cả PASS (bài cũ của `convos-phien` không đổi — nếu một bài cũ khớp chữ «lượt» chính xác trên dòng meta hàng phiên và trượt vì cấu trúc span mới, truy theo `textContent` của hàng thay vì sửa hành vi).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ops): current lead box, per-session chips and lead on the session line

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" -- \
  src/features/ops/components/PhienKhach.tsx tests/convos-phien.test.tsx
```

### Task 7: Kiểm toàn bộ + soi bằng mắt + tài liệu

**Files:**
- Modify: `CLAUDE.md` (FE, thêm MỘT dòng Change Log ở đầu bảng — tệp này đang có sửa đổi chưa commit của việc hết phiên; chỉ thêm dòng của mình, commit cả tệp sau khi hỏi người dùng hoặc commit bằng `git add -p` chỉ phần của mình)
- Modify: `CLAUDE.md` (BE, thêm một dòng Change Log)

- [ ] **Step 1: Toàn suite FE + lint**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -4 && npx tsc -b --force && npx eslint --max-warnings 0 src tests && npx prettier --check src/features/ops src/routes/_app/convos.index.tsx src/styles/theme.css tests/chip-stage-mau.test.ts tests/chip-stage.test.tsx tests/loc-stage.test.tsx tests/convos-list.test.tsx tests/convos-phien.test.tsx`
Expected: số pass = baseline + các bài mới, 0 fail; tsc/eslint sạch; prettier sạch trên tệp đã đụng (lệch thì `npx prettier --write <tệp>` — theo TỆP, đúng luật repo).

- [ ] **Step 2: Toàn suite BE + cổng**

Run (repo BE): `uv run pytest tests/modules/ops -q && make test-isolation && uv run ruff check . && uv run ruff format --check .`
Expected: khớp baseline + 16 bài mới xanh.

- [ ] **Step 3: Soi bằng mắt với backend thật**

Chạy BE (`make api` ở repo BE) và FE (`make dev` với `VITE_MSW=0`), đăng nhập tenant `green_park` (có dữ liệu lead thật), mở `/convos`, `/convos?stage=sql`, `/convos?stage=none`, và trang chi tiết khách có lead. Chụp ảnh (headless Chrome như lúc làm bản vẽ) và so với `public/demo-lead-convos.html`: cột Lead thẳng hàng, ô lọc 36px ngang ô tìm, menu không bị cắt khi lọc ra ít khách, chip trên hàng phiên ĐANG CHỌN vẫn thấy viền.

- [ ] **Step 4: Change Log**

FE `CLAUDE.md`, dòng mới đầu bảng Change Log:

```
| 2026-09-30 | **Lead stage · điểm · đối tượng trên `/convos`** (spec `docs/superpowers/specs/2026-09-30-lead-tren-convos-design.md`, bản vẽ `public/demo-lead-convos.html`). `ChipStage` (`features/ops/components/ChipStage.tsx`) — chỉ nhãn, bốn bậc ẤM DẦN (token `--color-lead-{1..4}-{bg,fg,vien}`, cổng `tests/chip-stage-mau.test.ts`), bậc lạ hiện nguyên văn bằng chip trung tính. Hàng khách có CỘT Lead riêng (lead MỚI NHẤT = lead của phiên mới nhất có lead). Bộ lọc stage là MỘT ô + menu `LocStage` portal ra `body` (tấm nền `overflow-hidden` cắt menu `absolute`), `?stage=lead\|mql\|sql\|hen_gap\|none`. Trang chi tiết: ô «Lead hiện tại» suy từ danh sách phiên (không thêm request) + chip từng phiên + lead trên dòng thông tin phiên. Nhãn/bậc/đối tượng ở `features/ops/lead.ts`. |
```

BE `CLAUDE.md`, dòng mới đầu bảng Change Log:

```
| 2026-09-30 | **`ops`: lead trên `/convos`.** `GET /convos/khach` trả `leadStage/leadScore/audience` = lead của PHIÊN mới nhất CÓ lead (LATERAL `_LEAD_KHACH`, nối qua `session_id`, không qua `escalations.phone`) và nhận `lead_stage=lead\|mql\|sql\|hen_gap\|none` (lọc TRƯỚC `LIMIT`, `dem_tong` dùng chung `LOC_LEAD`). `/convos/khach/{phone}/phien` + `/convos/phien/{id}` trả lead của TỪNG phiên (`_LEAD_PHIEN`, cột lead phải vào `GROUP BY`). 16 bài `tests/modules/ops/test_lead.py`. |
```

- [ ] **Step 5: Commit tài liệu**

BE: `git commit -m "docs(claude): log lead on /convos" -- CLAUDE.md` (kèm dòng Co-Authored-By).
FE: `CLAUDE.md` đang lẫn sửa đổi của việc hết phiên — HỎI người dùng trước khi commit tệp này.
