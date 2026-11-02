# Vòng 2 — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bỏ trần 6 ảnh/danh mục, và cho năm endpoint danh sách của module `realestate` phân trang có số trang (`offset` + `total`) mà không mất `nextCursor` đang dùng.

**Architecture:** Vị từ `WHERE` của mỗi danh sách tách thành **một** hàm dựng chuỗi, dùng chung cho câu lấy hàng **và** câu `COUNT(*)` — hai câu viết rời nhau là hai chỗ để lệch, và chỗ lệch cho `total` không khớp `items`. `offset` và `cursor` là hai lối phân trang song song: `cursor` giữ nguyên hành vi keyset đang có, `offset` là lối mới cho bảng có số trang; endpoint nhận cả hai, `offset` thắng khi khác 0.

**Tech Stack:** FastAPI · asyncpg · Pydantic v2 · pytest + testcontainers

## Global Constraints

- **Không migration, không đổi lược đồ Postgres.** Cột `status` giữ nguyên ở cả năm bảng `tenant_data`. (Năm view `agent_api.*` mà bản plan đầu nhắc tới **không còn tồn tại** — `0917_bo_agent_api` xoá cả 9 view; agent đọc thẳng bảng gốc và tự lọc `status='published'`.)
- **Không bỏ `nextCursor` khỏi response.** Nó là hợp đồng đang dùng; bỏ một field khỏi response là phá vỡ với mọi client khác.
- Định danh (hàm/biến/hằng/tham số, **kể cả biến cục bộ**) theo nếp file đang sửa: `router.py`/`repo.py` của module này dùng **tiếng Việt** (`liet_ke_du_an`, `_cach_ly`, `_xin_du_phong`, `dang_co`) — theo đúng nếp đó, đừng dịch sang tiếng Anh.
- **Comment thưa** — chỉ giải thích *vì sao*, không mô tả *cái gì*. File này có comment rất dày; đừng nối theo mật độ đó.
- Chạy test: `.venv/bin/python -m pytest` (⚠️ `uv` **không** có trên PATH máy này). Một file: `.venv/bin/python -m pytest tests/modules/realestate/<file> -v`.
- Cổng trước MR: `make check` (lint + test). `ruff format --check` là một phần của nó — chạy `ruff format` trước khi commit.
- ⚠️ **Ràng buộc này đã ĐỔI sau khi merge `develop` (2026-08-11).** `make test-isolation` nay **XANH hoàn toàn** — `0917_bo_agent_api` revoke lại PUBLIC của `0908` nên xung đột tự hết. Lỗi nền hiện tại là **đúng 3 test**, cả ba có sẵn trên `develop` và **không** liên quan plan này:
  - `tests/isolation/test_loc_tenant_o_tang_app.py::test_moi_cau_sql_cham_tenant_data_deu_mang_vi_tu_tenant` — 2 câu SQL thiếu vị từ tenant ở `modules/ops/repo.py:76,110`
  - `tests/modules/test_heartbeat.py` × 2 — RLS thiếu trên `control.agent_heartbeats`
  Mốc nền: **3 failed / 1049 passed**. Sau task của bạn, con số failed phải vẫn là **3** — khác đi là bạn gây ra.
- Commit: message **một dòng ngắn (≤60 ký tự)**, **KHÔNG** trailer `Co-Authored-By: Claude`. Không `git push` — push là việc của người dùng.
- Repo đang có thay đổi chưa commit **không thuộc plan này** (`src/portal/modules/kb/settings.py`, `tests/modules/kb/test_embed_client.py`, hai file `docs/superpowers/*/2026-08-10-ingest-qdrant*`). `git add` **đúng đường dẫn** của task, đừng dùng `git add -A`.

**Spec:** [docs/superpowers/specs/2026-08-10-man-du-an-vong-2-design.md](../specs/2026-08-10-man-du-an-vong-2-design.md) — đọc §4.3 (trần ảnh), §4.8 (phân trang), §7 (hợp đồng agent).

## Cấu trúc file

| File | Trách nhiệm sau plan này |
|---|---|
`src/portal/modules/realestate/repo.py` | thêm 5 hàm dựng vị từ `_loc_*()`, 5 hàm `dem_*()`, và tham số `offset` cho 5 hàm `liet_ke_*()` |
`src/portal/modules/realestate/router.py` | bỏ trần ảnh; 5 endpoint danh sách nhận `offset`, trả `total` |
`src/portal/modules/realestate/contracts.py` | 5 model `Trang*` thêm `total: int` |
`docs/contracts/mat-bang-agent.md` | **mới** — hợp đồng gửi repo `odyssey-agent` |
`CLAUDE.md` | một dòng Change Log (đổi hợp đồng với repo khác) |

---

### Task 1: Bỏ trần 6 ảnh mỗi danh mục

Trần này cưỡng chế ở app, không có ràng buộc DB nào chống lưng — nên bỏ nó là bỏ một nhánh kiểm và một hàm dựng lỗi, không phải migration.

**Files:**
- Modify: `src/portal/modules/realestate/router.py` — bỏ `TRAN_ANH_MOI_DANH_MUC` (dòng 789), `_chan_qua_nhieu_anh()` (797–840), `_qua_nhieu_anh()` (106–113), và chỗ gọi `_chan_qua_nhieu_anh`
- Modify: `src/portal/modules/realestate/repo.py` — bỏ `dem_anh_theo_danh_muc()` (656–682) nếu không còn ai gọi
- Test: `tests/modules/realestate/test_media_tran_anh.py` (file có sẵn — đảo nghĩa, xem Step 1)

**Interfaces:**
- Consumes: —
- Produces: `POST …/media` không còn trả `422 MEDIA_LIMIT` trong bất kỳ trường hợp nào.

- [ ] **Step 1: Tìm test đang canh trần và đảo nghĩa nó**

Trần đang có test canh. Tìm chúng trước khi sửa code:

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
grep -rn "MEDIA_LIMIT\|TRAN_ANH_MOI_DANH_MUC\|qua_nhieu_anh" tests/
```

Mỗi test khẳng định "ảnh thứ 7 bị chặn" phải đổi thành khẳng định **ngược lại** — ảnh thứ 7 được nhận. **Đừng xoá test**: xoá đi thì không còn gì canh việc trần đã thật sự bỏ, và một `if` sót lại ở đâu đó sẽ không ai thấy.

Thêm test này vào file test media có sẵn (đặt tên file theo file `grep` vừa tìm ra):

```python
async def test_nap_chin_anh_cung_danh_muc_deu_duoc_nhan(client_re, du_an_co_san):
    """Trần 6 ảnh/danh mục đã bỏ (spec vòng 2 §4.3) — chín ảnh cùng danh mục
    phải vào đủ chín. Test này là cổng canh: một nhánh kiểm trần sót lại ở
    router sẽ làm nó đỏ ở ảnh thứ bảy."""
    for i in range(9):
        r = await client_re.post(
            f"/api/v1/projects/{du_an_co_san}/media",
            json={
                "category": "ngoai_that",
                "contentType": "image",
                "mediaUrl": f"tenants/t/kb-bds/sha{i}/anh-{i}.webp",
                "contentHash": f"sha{i}",
            },
        )
        assert r.status_code == 201, f"ảnh thứ {i + 1} bị từ chối: {r.text}"

    r = await client_re.get(f"/api/v1/projects/{du_an_co_san}/media?category=ngoai_that")
    assert len(r.json()["items"]) == 9
```

⚠️ Tên fixture (`client_re`, `du_an_co_san`) và khuôn body **phải khớp** file test có sẵn — đọc file đó rồi dùng đúng fixture của nó, đừng dùng tên trong ví dụ này nếu nó khác.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `.venv/bin/python -m pytest tests/modules/realestate/ -k "chin_anh" -v`
Expected: FAIL ở ảnh thứ 7 — `ảnh thứ 7 bị từ chối: {"error":{"code":"MEDIA_LIMIT",...}}`

- [ ] **Step 3: Bỏ nhánh kiểm ở router**

Trong `src/portal/modules/realestate/router.py`, bỏ hằng và hàm:

```python
TRAN_ANH_MOI_DANH_MUC = 6
"""…docstring…"""


async def _chan_qua_nhieu_anh(...) -> None:
    """…docstring dài…"""
    ...
```

Bỏ luôn hàm dựng lỗi ở dòng 106–113:

```python
def _qua_nhieu_anh(category: str) -> loi.LoiPortal:
    ...
```

Rồi bỏ **chỗ gọi**. Tìm bằng:

```bash
grep -n "_chan_qua_nhieu_anh\|_qua_nhieu_anh" src/portal/modules/realestate/router.py
```

Xoá cả dòng `await _chan_qua_nhieu_anh(...)` (thường trong `POST …/media`). Nếu nó là câu duy nhất trong một block `async with`, kiểm block đó còn việc gì khác trước khi xoá.

- [ ] **Step 4: Bỏ hàm đếm ở repo nếu không còn ai gọi**

```bash
grep -rn "dem_anh_theo_danh_muc" src/ tests/
```

Không còn chỗ gọi nào ⇒ bỏ `async def dem_anh_theo_danh_muc(...)` khỏi `repo.py` (dòng 656–682). Còn chỗ gọi ⇒ **giữ lại** và ghi vào báo cáo là chỗ nào.

- [ ] **Step 5: Chạy test**

Run: `.venv/bin/python -m pytest tests/modules/realestate/ -v && ruff format --check src tests && ruff check src tests`
Expected: PASS toàn bộ, `ruff` sạch. Nếu `ruff format --check` đỏ thì chạy `ruff format src tests` rồi commit cả phần format.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/realestate/router.py \
        src/portal/modules/realestate/repo.py \
        tests/modules/realestate/
git commit -m "feat(re): bỏ trần 6 ảnh mỗi danh mục"
```

---

### Task 2: `offset` + `total` cho `/projects` — dựng khuôn dùng chung

Task này làm **một** endpoint và **dựng khuôn** cho bốn cái còn lại. Reviewer gác thiết kế ở đây, trước khi nó được nhân bản bốn lần.

`liet_ke_du_an` là hàm duy nhất trong năm hàm có tham số filter **không** nằm liền ở `$1..$k` (`SENTINEL_TENANT` đang ở `$5`), nên nó phải đánh số lại — và đó chính là lý do làm nó trước: nếu khuôn chịu được ca khó nhất thì bốn ca kia chỉ là áp lại.

**Files:**
- Modify: `src/portal/modules/realestate/contracts.py:301-306` (`TrangDuAn`)
- Modify: `src/portal/modules/realestate/repo.py:279-318` (`liet_ke_du_an`) + thêm `_loc_du_an()` và `dem_du_an()`
- Modify: `src/portal/modules/realestate/router.py:887-903` (`liet_ke_du_an` endpoint)
- Test: `tests/modules/realestate/test_phan_trang_so.py` (**mới**)

**Interfaces:**
- Consumes: —
- Produces:
  - `contracts.TrangDuAn` có thêm field `total: int`
  - `repo._loc_du_an() -> str` — vị từ `WHERE` dùng `$1` (tìm), `$2` (region), `$3` (sentinel)
  - `repo.dem_du_an(conn, *, tim: str = "", region: str = "") -> int`
  - `repo.liet_ke_du_an(conn, *, tim="", region="", limit=TRANG_MAC_DINH, cursor=None, offset=0) -> list[asyncpg.Record]`
  - endpoint `GET /projects` nhận query `offset: int = 0`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/realestate/test_phan_trang_so.py`:

```python
"""Phân trang CÓ SỐ TRANG (`offset` + `total`) — spec vòng 2 §4.8.

CANH ĐÚNG MỘT THỨ MÀ CURSOR KHÔNG LÀM ĐƯỢC: nhảy thẳng tới trang thứ n mà
không đi qua n-1 trang trước. Và canh `total` khớp vị từ lọc — `total` đếm theo
một mệnh đề `WHERE` khác câu lấy hàng là lỗi kinh điển của lối này: người dùng
thấy "237 hàng" rồi bấm trang cuối ra rỗng.
"""
import pytest


@pytest.mark.asyncio
async def test_total_dem_dung_so_du_an_va_khong_dem_sentinel(client_re, nap_du_an):
    await nap_du_an(7)

    r = await client_re.get("/api/v1/projects?limit=3")

    assert r.status_code == 200
    than = r.json()
    assert len(than["items"]) == 3
    # 7 dự án thật. `__ALL__` bị ẩn khỏi danh sách nên KHÔNG được đếm vào total —
    # nếu nó lọt vào thì total = 8 và trang cuối hiện một hàng trống.
    assert than["total"] == 7


@pytest.mark.asyncio
async def test_offset_nhay_thang_toi_trang_thu_ba(client_re, nap_du_an):
    ma = await nap_du_an(7)

    trang1 = (await client_re.get("/api/v1/projects?limit=3&offset=0")).json()
    trang3 = (await client_re.get("/api/v1/projects?limit=3&offset=6")).json()

    assert [d["projectCode"] for d in trang1["items"]] == ma[:3]
    # offset=6 với limit=3 ⇒ trang thứ ba, còn đúng 1 hàng.
    assert [d["projectCode"] for d in trang3["items"]] == ma[6:7]
    assert trang3["total"] == 7


@pytest.mark.asyncio
async def test_total_theo_dung_bo_loc_dang_ap(client_re, nap_du_an):
    """`total` phải đếm theo CÙNG vị từ với câu lấy hàng. Nếu hai câu lệch nhau
    thì test này đỏ — và đó là toàn bộ lý do `_loc_du_an()` tồn tại."""
    await nap_du_an(5, region="Hà Nội")
    await nap_du_an(2, region="Đà Nẵng")

    r = (await client_re.get("/api/v1/projects?region=Đà Nẵng&limit=50")).json()

    assert len(r["items"]) == 2
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_nextcursor_van_con_va_van_dung(client_re, nap_du_an):
    """`nextCursor` KHÔNG bị bỏ — nó là hợp đồng đang dùng (Global Constraints)."""
    await nap_du_an(7)

    trang1 = (await client_re.get("/api/v1/projects?limit=3")).json()
    assert trang1["nextCursor"] is not None

    trang2 = (await client_re.get(f"/api/v1/projects?limit=3&cursor={trang1['nextCursor']}")).json()
    ma1 = {d["projectCode"] for d in trang1["items"]}
    ma2 = {d["projectCode"] for d in trang2["items"]}
    assert not (ma1 & ma2), "hai trang keyset không được trùng hàng nào"


@pytest.mark.asyncio
async def test_offset_am_va_offset_qua_lon(client_re, nap_du_an):
    await nap_du_an(3)

    # `offset` âm bị FastAPI chặn ở tầng validate (ge=0) — 422, không phải 500.
    assert (await client_re.get("/api/v1/projects?offset=-5")).status_code == 422
    # Vượt quá số hàng ⇒ trang rỗng, `total` vẫn đúng. KHÔNG phải lỗi.
    r = (await client_re.get("/api/v1/projects?limit=10&offset=99")).json()
    assert r["items"] == []
    assert r["total"] == 3
```

Fixture `nap_du_an(n, region=…)` chưa có — thêm vào `tests/modules/realestate/conftest.py`:

```python
@pytest.fixture
def nap_du_an(client_re):
    """Tạo `n` dự án, trả list `project_code` theo ĐÚNG thứ tự danh sách sẽ trả
    (`ORDER BY id DESC` ⇒ mã tạo sau đứng trước)."""

    async def _nap(n: int, *, region: str = "Hà Nội") -> list[str]:
        ma = []
        for i in range(n):
            code = f"PT{region[:2]}{i:02d}"
            r = await client_re.post(
                "/api/v1/projects",
                json={"projectCode": code, "name": f"Dự án {code}", "region": region},
            )
            assert r.status_code == 201, r.text
            ma.append(code)
        return list(reversed(ma))

    return _nap
```

⚠️ Đọc `tests/modules/realestate/conftest.py` trước: nếu fixture client tên khác `client_re` thì dùng đúng tên có sẵn ở **cả** fixture này và cả năm test. Và nếu `POST /projects` cần thêm field bắt buộc nào (kiểm `ProjectIn`), thêm vào body — nhưng **đừng** thêm `overview`, vì test cần dự án `draft` lẫn `published` đều liệt kê được và `region`+`name` là đủ để tạo.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `.venv/bin/python -m pytest tests/modules/realestate/test_phan_trang_so.py -v`
Expected: FAIL — `KeyError: 'total'` ở test đầu, và `offset` bị bỏ qua nên `test_offset_nhay_thang_toi_trang_thu_ba` trả trang 1 ở cả hai lần gọi.

- [ ] **Step 3: Thêm `total` vào `TrangDuAn`**

`src/portal/modules/realestate/contracts.py`, sửa `TrangDuAn` (dòng 301):

```python
class TrangDuAn(BaseModel):
    items: list[DuAnOut]
    nextCursor: str | None = None
    """`None` = hết trang. FE dừng khi thấy `null`, không phải khi `items` rỗng —
    trang cuối vừa khớp `limit` hàng vẫn cho `items` đầy."""
    total: int = 0
    """Tổng số hàng khớp bộ lọc, KHÔNG phải số hàng trong `items`. Có để FE dựng
    được thanh trang có số; `nextCursor` giữ lại cho client đi bằng keyset."""
```

- [ ] **Step 4: Tách vị từ và thêm hàm đếm ở repo**

`src/portal/modules/realestate/repo.py`. Thêm ngay **trên** `liet_ke_du_an`:

```python
def _loc_du_an() -> str:
    """Vị từ `WHERE` của danh sách dự án — dùng cho CẢ câu lấy hàng lẫn câu đếm.

    Một hàm chứ hai câu SQL viết rời: `total` đếm theo một mệnh đề khác câu lấy
    hàng là lỗi kinh điển của phân trang có số — người dùng thấy "237 hàng" rồi
    bấm trang cuối ra rỗng. Tham số filter chiếm `$1..$3`; câu lấy hàng nối thêm
    keyset/limit/offset từ `$4`.
    """
    return f"""{_cach_ly()}
               AND ($1 = '' OR name ILIKE '%' || $1 || '%' OR project_code ILIKE '%' || $1 || '%')
               AND ($2 = '' OR region = $2)
               AND project_code <> $3"""
```

Rồi viết lại thân `liet_ke_du_an` — **giữ nguyên docstring dài đang có**, chỉ đổi chữ ký và câu SQL:

```python
async def liet_ke_du_an(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    region: str = "",
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """…GIỮ NGUYÊN docstring hiện có, thêm một đoạn:…

    `offset` và `cursor` là hai lối phân trang SONG SONG, không trộn: `cursor`
    cho keyset (client cũ), `offset` cho bảng có số trang. Gửi cả hai thì cả hai
    áp — vô nghĩa nhưng không sai, và router không cho ca đó xảy ra.
    """
    return await conn.fetch(
        f"""SELECT {_COT_RA["project"]} FROM tenant_data.projects
             WHERE {_loc_du_an()}
               AND {_menh_de_keyset("", 4)}
             ORDER BY id DESC
             LIMIT $5 OFFSET $6""",
        tim,
        region,
        SENTINEL_TENANT,
        _sau(cursor),
        _gioi_han(limit),
        max(0, offset),
    )


async def dem_du_an(conn: asyncpg.Connection, *, tim: str = "", region: str = "") -> int:
    """Tổng số dự án khớp bộ lọc — `total` của `TrangDuAn`.

    KHÔNG nhận `cursor`/`offset`: `total` là tổng của cả tập, không phải của một
    trang. Dùng CÙNG `_loc_du_an()` với câu lấy hàng."""
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.projects WHERE {_loc_du_an()}",
        tim,
        region,
        SENTINEL_TENANT,
    )
```

⚠️ **Thứ tự tham số đã đổi.** `SENTINEL_TENANT` từ `$5` lên `$3`, `_sau(cursor)` từ `$4` xuống `$4` (không đổi số nhưng đổi vị trí trong danh sách đối số), `limit` từ `$3` lên `$5`. Truyền sai thứ tự vẫn **typecheck và vẫn trả hàng** — chỉ sai kết quả. Test `test_total_theo_dung_bo_loc_dang_ap` là cổng canh cho đúng chuyện này.

- [ ] **Step 5: Nối vào endpoint**

`src/portal/modules/realestate/router.py`, sửa `liet_ke_du_an` (dòng 887):

```python
_OFFSET_Q = Query(0, ge=0)
"""Singleton mức module, cùng lý do `_LIMIT_Q`: `Query(...)` trong default là
B008 (ruff)."""


@ROUTER.get("/projects", response_model=TrangDuAn)
async def liet_ke_du_an(
    search: str = "",
    region: str = "",
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangDuAn:
    # `offset` khác 0 ⇒ đi bằng offset, bỏ `cursor`: trộn hai lối phân trang cho
    # một kết quả không ai giải thích được (keyset cắt từ id nào, rồi bỏ thêm n
    # hàng nữa). Ưu tiên `offset` vì nó là lối của UI có số trang.
    if offset:
        cursor = None
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_du_an(
                conn, tim=search, region=region, limit=xin, cursor=cursor, offset=offset
            )
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        # CÙNG giao dịch với câu lấy hàng — hai giao dịch rời nhau cho `total`
        # lệch khỏi `items` khi có ai đang ghi.
        tong = await repo.dem_du_an(conn, tim=search, region=region)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangDuAn(items=[_ra_du_an(r) for r in items], nextCursor=ke_tiep, total=tong)
```

`_OFFSET_Q` khai **một lần** ở mức module, cạnh `_LIMIT_Q` (dòng 283) — bốn endpoint còn lại dùng lại nó ở Task 3.

- [ ] **Step 6: Chạy test**

Run: `.venv/bin/python -m pytest tests/modules/realestate/test_phan_trang_so.py -v`
Expected: PASS (5 test).

- [ ] **Step 7: Nghiệm thu — tháo bản vá, xác nhận test đỏ**

Test dễ xanh-giả ở đây. Kiểm ba chỗ:

```bash
# (a) đổi `_loc_du_an()` trong `dem_du_an` thành một vị từ khác (bỏ dòng region)
#     → `test_total_theo_dung_bo_loc_dang_ap` phải ĐỎ
# (b) bỏ `OFFSET $6` khỏi câu SQL
#     → `test_offset_nhay_thang_toi_trang_thu_ba` phải ĐỎ
# (c) bỏ `if offset: cursor = None`
#     → chạy lại toàn file, ghi lại kết quả (có thể vẫn xanh — nếu vậy, nói rõ
#        trong báo cáo là nhánh đó chưa có cổng canh)
```

Mỗi lần `git checkout -- <file>` để trả lại. Dán output thật của cả ba vào báo cáo.

- [ ] **Step 8: Chạy toàn bộ và lint**

Run: `.venv/bin/python -m pytest tests/modules/realestate/ tests/api/ -v && ruff format --check src tests && ruff check src tests`
Expected: PASS. `tests/api/test_contracts.py` có thể đỏ nếu `contracts/` cần sinh lại — nếu vậy chạy `make contracts` và commit kèm.

- [ ] **Step 9: Commit**

```bash
git add src/portal/modules/realestate/contracts.py \
        src/portal/modules/realestate/repo.py \
        src/portal/modules/realestate/router.py \
        tests/modules/realestate/ \
        contracts/
git commit -m "feat(re): /projects nhận offset và trả total"
```

---

### Task 3: `offset` + `total` cho bốn danh sách còn lại

Áp lại đúng khuôn Task 2 cho `zones` · `units` · `documents` · `media`. Bốn hàm này **đã** có filter liền ở `$1..$k` nên không phải đánh số lại — chỉ nối `OFFSET` và thêm hàm đếm.

**Files:**
- Modify: `src/portal/modules/realestate/contracts.py:308-325` (`TrangPhanKhu`, `TrangCan`, `TrangTaiLieu`, `TrangMedia`)
- Modify: `src/portal/modules/realestate/repo.py` — `liet_ke_phan_khu` (~361), `liet_ke_can` (~436), `liet_ke_tai_lieu` (~518), `liet_ke_media` (~597); thêm `_loc_*()` và `dem_*()` cho mỗi cái
- Modify: `src/portal/modules/realestate/router.py:1008, 1129, 1250, 1372` (bốn endpoint)
- Test: `tests/modules/realestate/test_phan_trang_so.py` (thêm vào file Task 2 tạo)

**Interfaces:**
- Consumes: `repo._loc_du_an()`/`repo.dem_du_an()` (Task 2) làm khuôn; `router._OFFSET_Q` (Task 2)
- Produces:
  - `repo.dem_phan_khu(conn, *, project_code="") -> int`
  - `repo.dem_can(conn, *, project_code="", zone_code="", product_type="", sale_status="") -> int`
  - `repo.dem_tai_lieu(conn, *, project_code="") -> int`
  - `repo.dem_media(conn, *, project_code="", zone_code="", unit_code="", category="", content_type="") -> int`
  - bốn hàm `liet_ke_*` nhận thêm `offset: int = 0`
  - bốn `Trang*` có `total: int = 0`

- [ ] **Step 1: Viết test đỏ cho cả bốn**

Thêm vào `tests/modules/realestate/test_phan_trang_so.py`:

```python
@pytest.mark.asyncio
async def test_total_va_offset_cho_can(client_re, nap_du_an, nap_can):
    ma = (await nap_du_an(1))[0]
    await nap_can(ma, 5)

    trang2 = (await client_re.get(f"/api/v1/projects/{ma}/units?limit=2&offset=2")).json()

    assert trang2["total"] == 5
    assert len(trang2["items"]) == 2


@pytest.mark.asyncio
async def test_total_cua_can_theo_dung_bo_loc(client_re, nap_du_an, nap_can):
    """Cổng canh vị từ dùng chung — `units` có BỐN filter, nhiều nhất trong năm
    danh sách, nên nó là chỗ dễ để `dem_can` lệch khỏi `liet_ke_can` nhất."""
    ma = (await nap_du_an(1))[0]
    await nap_can(ma, 3, product_type="chung_cu")
    await nap_can(ma, 2, product_type="biet_thu")

    r = (await client_re.get(f"/api/v1/projects/{ma}/units?productType=biet_thu&limit=50")).json()

    assert len(r["items"]) == 2
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_total_va_offset_cho_media(client_re, nap_du_an, nap_media):
    ma = (await nap_du_an(1))[0]
    await nap_media(ma, 4, category="ngoai_that")
    await nap_media(ma, 3, category="noi_that")

    r = (await client_re.get(f"/api/v1/projects/{ma}/media?category=noi_that&limit=2&offset=2")).json()

    assert r["total"] == 3
    assert len(r["items"]) == 1


@pytest.mark.asyncio
async def test_total_cho_phan_khu_va_tai_lieu(client_re, nap_du_an, nap_phan_khu, nap_tai_lieu):
    ma = (await nap_du_an(1))[0]
    await nap_phan_khu(ma, 3)
    await nap_tai_lieu(ma, 4)

    assert (await client_re.get(f"/api/v1/projects/{ma}/zones?limit=2")).json()["total"] == 3
    assert (await client_re.get(f"/api/v1/projects/{ma}/documents?limit=2")).json()["total"] == 4
```

Bốn fixture `nap_can` / `nap_media` / `nap_phan_khu` / `nap_tai_lieu` — thêm vào `tests/modules/realestate/conftest.py`, cùng khuôn `nap_du_an` của Task 2:

```python
@pytest.fixture
def nap_phan_khu(client_re):
    async def _nap(project_code: str, n: int) -> list[str]:
        ma = []
        for i in range(n):
            code = f"PK{i:02d}"
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/zones",
                json={"zoneCode": code, "name": f"Phân khu {code}", "category": "chung_cu"},
            )
            assert r.status_code == 201, r.text
            ma.append(code)
        return list(reversed(ma))

    return _nap


@pytest.fixture
def nap_can(client_re):
    async def _nap(project_code: str, n: int, *, product_type: str = "chung_cu") -> None:
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/units",
                json={"unitCode": f"{product_type[:2].upper()}-{i:03d}", "productType": product_type},
            )
            assert r.status_code == 201, r.text

    return _nap


@pytest.fixture
def nap_tai_lieu(client_re):
    async def _nap(project_code: str, n: int) -> None:
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/documents",
                json={"title": f"Tài liệu {i}", "loai": "khac"},
            )
            assert r.status_code == 201, r.text

    return _nap


@pytest.fixture
def nap_media(client_re):
    async def _nap(project_code: str, n: int, *, category: str = "ngoai_that") -> None:
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/media",
                json={
                    "category": category,
                    "contentType": "image",
                    "mediaUrl": f"tenants/t/kb-bds/{category}{i}/a.webp",
                    "contentHash": f"{category}{i}",
                },
            )
            assert r.status_code == 201, r.text

    return _nap
```

⚠️ **Kiểm từng `*In` model trước khi dùng body ở trên** (`ZoneIn`, `UnitIn`, `DocumentIn`, `MediaUploadIn` trong `contracts.py`): field bắt buộc nào thiếu sẽ cho 422 và test đỏ vì lý do không liên quan. Sửa body cho khớp, đừng sửa model.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `.venv/bin/python -m pytest tests/modules/realestate/test_phan_trang_so.py -v`
Expected: FAIL — bốn test mới `KeyError: 'total'`; năm test của Task 2 vẫn PASS.

- [ ] **Step 3: Thêm `total` vào bốn model**

`src/portal/modules/realestate/contracts.py`, mỗi model thêm một dòng:

```python
class TrangPhanKhu(BaseModel):
    items: list[PhanKhuOut]
    nextCursor: str | None = None
    total: int = 0


class TrangCan(BaseModel):
    items: list[CanOut]
    nextCursor: str | None = None
    total: int = 0


class TrangTaiLieu(BaseModel):
    items: list[TaiLieuOut]
    nextCursor: str | None = None
    total: int = 0


class TrangMedia(BaseModel):
    items: list[MediaOut]
    nextCursor: str | None = None
    total: int = 0
```

Docstring của `total` viết **một lần** ở `TrangDuAn` (Task 2) là đủ — bốn chỗ này không cần lặp lại.

- [ ] **Step 4: Tách vị từ + hàm đếm cho `zones` và `documents`**

Hai danh sách này có **một** filter, khuôn giống nhau. Trong `repo.py`:

```python
def _loc_phan_khu() -> str:
    """Vị từ `WHERE` của danh sách phân khu — dùng chung với `dem_phan_khu()`,
    cùng lý do `_loc_du_an()`. Filter chiếm `$1`."""
    return f"""{_cach_ly()}
               AND ($1 = '' OR project_code = $1)"""


async def dem_phan_khu(conn: asyncpg.Connection, *, project_code: str = "") -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.zones WHERE {_loc_phan_khu()}", project_code
    )
```

`liet_ke_phan_khu` — chữ ký thêm `offset: int = 0`, câu SQL thành:

```python
    return await conn.fetch(
        f"""SELECT {_COT_RA["zone"]} FROM tenant_data.zones
             WHERE {_loc_phan_khu()}
               AND {_menh_de_keyset("", 2)}
             ORDER BY id DESC
             LIMIT $3 OFFSET $4""",
        project_code,
        _sau(cursor),
        _gioi_han(limit),
        max(0, offset),
    )
```

`documents` y hệt, đổi `zones`→`documents`, `zone`→`document`, `_loc_phan_khu`→`_loc_tai_lieu`, `dem_phan_khu`→`dem_tai_lieu`.

- [ ] **Step 5: Tách vị từ + hàm đếm cho `units` và `media`**

```python
def _loc_can() -> str:
    """Filter chiếm `$1..$4`."""
    return f"""{_cach_ly()}
               AND ($1 = '' OR project_code = $1)
               AND ($2 = '' OR zone_code    = $2)
               AND ($3 = '' OR product_type = $3)
               AND ($4 = '' OR sale_status  = $4)"""


async def dem_can(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    product_type: str = "",
    sale_status: str = "",
) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.units WHERE {_loc_can()}",
        project_code,
        zone_code,
        product_type,
        sale_status,
    )
```

`liet_ke_can` — câu SQL thành `AND {_menh_de_keyset("", 5)} ORDER BY id DESC LIMIT $6 OFFSET $7`, đối số theo đúng thứ tự `project_code, zone_code, product_type, sale_status, _sau(cursor), _gioi_han(limit), max(0, offset)`.

```python
def _loc_media() -> str:
    """Filter chiếm `$1..$5`."""
    return f"""{_cach_ly()}
               AND ($1 = '' OR project_code  = $1)
               AND ($2 = '' OR zone_code     = $2)
               AND ($3 = '' OR unit_code     = $3)
               AND ($4 = '' OR category      = $4)
               AND ($5 = '' OR content_type  = $5)"""


async def dem_media(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    unit_code: str = "",
    category: str = "",
    content_type: str = "",
) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.media WHERE {_loc_media()}",
        project_code,
        zone_code,
        unit_code,
        category,
        content_type,
    )
```

`liet_ke_media` — `AND {_menh_de_keyset("", 6)} ORDER BY id DESC LIMIT $7 OFFSET $8`.

⚠️ Đọc câu SQL **hiện có** của mỗi hàm trước khi sửa: số `$n` của keyset và limit ở trên suy từ số filter, nhưng nếu một hàm có filter mà bảng ở đây không liệt kê thì số bị lệch. Đối chiếu với `grep -n "_menh_de_keyset" src/portal/modules/realestate/repo.py`.

- [ ] **Step 6: Nối bốn endpoint**

Mỗi endpoint trong `router.py` (dòng 1008 `zones`, 1129 `units`, 1250 `documents`, 1372 `media`) thêm đúng ba thứ, theo khuôn Task 2:

1. tham số `offset: int = _OFFSET_Q` (đặt sau `cursor`)
2. `if offset: cursor = None` ở đầu thân hàm, kèm comment đã viết ở Task 2 — **đừng** lặp lại comment dài đó bốn lần; viết một dòng `# Xem `liet_ke_du_an`: offset thắng cursor.`
3. gọi `repo.dem_*(...)` **trong cùng** `async with tenant_conn(...)`, truyền **đúng** bộ filter mà endpoint đó đang truyền cho `liet_ke_*`, rồi `total=tong` vào model trả về

⚠️ Chỗ dễ sai nhất: truyền cho `dem_*` một bộ filter **khác** bộ đã truyền cho `liet_ke_*` (ví dụ quên `zone_code` ở `units`). Test `test_total_cua_can_theo_dung_bo_loc` canh ca `product_type`; nếu bạn thêm filter nào ngoài bảng trên thì thêm một assertion cho nó.

- [ ] **Step 7: Chạy test**

Run: `.venv/bin/python -m pytest tests/modules/realestate/test_phan_trang_so.py -v`
Expected: PASS (9 test).

- [ ] **Step 8: Nghiệm thu — tháo bản vá cho hai chỗ khó nhất**

```bash
# (a) trong `dem_can`, bỏ dòng `AND ($3 = '' OR product_type = $3)` khỏi `_loc_can()`
#     → chỉ ảnh hưởng `dem_can`? KHÔNG — `_loc_can()` dùng chung, nên cả
#       `liet_ke_can` đổi theo và test có thể vẫn xanh. Đây là điều PHẢI kiểm:
#       nếu vẫn xanh thì cổng canh đang không phân biệt được hai câu, nói rõ ra.
# (b) trong endpoint `units`, truyền `product_type=""` cho `dem_can` (giữ đúng
#     cho `liet_ke_can`) → `test_total_cua_can_theo_dung_bo_loc` phải ĐỎ
```

`git checkout --` sau mỗi lần. Dán output thật.

- [ ] **Step 9: Chạy toàn bộ và lint**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/isolation && ruff format --check src tests && ruff check src tests`
Expected: PASS. (Bỏ `tests/isolation` vì nó **đỏ sẵn có 13 test** từ `0908`/`0909` — xem Global Constraints. Chạy riêng `make test-isolation` một lần và so con số đỏ với 13; khác 13 thì báo lại.)

- [ ] **Step 10: Commit**

```bash
git add src/portal/modules/realestate/contracts.py \
        src/portal/modules/realestate/repo.py \
        src/portal/modules/realestate/router.py \
        tests/modules/realestate/ \
        contracts/
git commit -m "feat(re): offset và total cho 4 danh sách còn lại"
```

---

### Task 4: Hợp đồng mặt bằng gửi repo `odyssey-agent`

Frontend sẽ thôi ghi `projects.map_media_id` (spec §4.5), nên agent phải đổi cách đọc mặt bằng. Không có job CI nào so hai repo — hợp đồng là **file copy tay**, và file này là bản gốc.

**Files:**
- Create: `docs/contracts/mat-bang-agent.md`
- Modify: `CLAUDE.md` — một dòng Change Log

**Interfaces:**
- Consumes: —
- Produces: `docs/contracts/mat-bang-agent.md` — bản gốc để copy sang repo `odyssey-agent`

- [ ] **Step 1: Đọc một hợp đồng có sẵn để theo đúng khuôn**

```bash
ls docs/contracts/
sed -n 1,40p docs/contracts/dau-noi-agent.md
```

Theo đúng khuôn file đó: nó có mục nào, đánh số §ra sao, ghi ngày và trạng thái thế nào. **Đừng** phát minh khuôn mới.

- [ ] **Step 2: Viết `docs/contracts/mat-bang-agent.md`**

```markdown
# Hợp đồng: đọc mặt bằng dự án

**Ngày:** 2026-08-10 · **Hướng:** `odyssey-portal-backend` → `odyssey-agent` · **Trạng thái:** chờ repo agent áp

## 1. Thay đổi

Portal thôi ghi `tenant_data.projects.map_media_id`. Từ vòng 2 của màn dự án, cột đó **luôn `NULL`** với mọi dự án Portal tạo hoặc sửa.

Lý do: tab Mặt bằng gộp còn một vùng ảnh duy nhất — không còn khái niệm "ảnh mặt bằng chính", nên không còn gì để trỏ vào. Người yêu cầu đã được cảnh báo về khoảng hồi quy ở §4 và chọn phương án này.

## 2. Agent phải đổi sang

```sql
SELECT id, media_url, thumb_url, caption
  FROM agent_api.media
 WHERE project_code = $1
   AND zone_code IS NULL AND unit_code IS NULL
   AND category = 'mat_bang'
 ORDER BY created_at
```

`agent_api.media` đã có đủ cột (`category` nằm trong `_COT_MEDIA`, `migrations/versions/0401_agent_doc_kb.py`) và đã `GRANT SELECT` cho role nhóm `agent_all`. **Không cần migration.**

Truy vấn trả **nhiều** hàng — agent trả cả bộ mặt bằng, không phải một ảnh.

## 3. Cột `map_media_id` không bị xoá

Giữ lại để dữ liệu cũ không mất và để repo agent đổi theo nhịp riêng. Nhưng **đừng đọc nó nữa**: một dự án cũ còn `map_media_id` khác `NULL` và một dự án mới có `NULL` sẽ cho hai hành vi khác nhau cho cùng một câu hỏi — đúng loại lỗi chỉ hiện trên dữ liệu thật.

## 4. Khoảng hồi quy

Từ lúc Portal ship tới lúc repo agent áp hợp đồng này, agent đọc `map_media_id` nhận `NULL` và trả lời "chưa có mặt bằng" cho dự án **có** ảnh mặt bằng.

Nếu cần đóng khoảng đó trước: Portal đặt `mapMediaId` = ảnh đầu của danh mục `mat_bang` như một lưới an toàn, gỡ sau khi repo agent xong.

## 5. Cách kiểm đã áp đúng

Sau khi repo agent đổi, hỏi agent "cho xem mặt bằng dự án <mã>" trên một dự án có ≥2 ảnh `mat_bang` và `map_media_id IS NULL`. Đúng: trả đủ số ảnh. Sai: trả "chưa có mặt bằng".
```

- [ ] **Step 3: Thêm một dòng Change Log vào `CLAUDE.md`**

`CLAUDE.md` có mục "Tự bảo trì file này" yêu cầu cập nhật **trong cùng commit với code** khi đổi hợp đồng với repo khác. Thêm vào bảng Change Log:

```markdown
| 2026-08-10 | Vòng 2 màn dự án: bỏ trần 6 ảnh/danh mục (`TRAN_ANH_MOI_DANH_MUC` gỡ khỏi `router.py`); năm endpoint danh sách `realestate` nhận `offset` và trả `total` (`nextCursor` giữ nguyên); Portal thôi ghi `projects.map_media_id` — hợp đồng mới `docs/contracts/mat-bang-agent.md`, **copy tay** sang repo `odyssey-agent` |
```

⚠️ Đọc bảng Change Log hiện có và chèn dòng vào **đúng chỗ** theo thứ tự ngày của nó. Không sửa dòng nào đang có.

- [ ] **Step 4: Kiểm không có test nào canh `map_media_id` bị Portal ghi**

```bash
grep -rn "map_media_id\|mapMedia\|map_media" tests/
```

Có test khẳng định Portal **ghi** `map_media_id` ⇒ nó sẽ đỏ khi frontend đổi. Ghi danh sách đó vào báo cáo; **đừng sửa** ở task này (backend vẫn nhận `mapMedia` trong body, chỉ FE thôi gửi) — nhưng plan frontend cần biết.

- [ ] **Step 5: Chạy test và lint**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/isolation && ruff format --check src tests && ruff check src tests`
Expected: PASS — task này chỉ thêm tài liệu, không đổi code, nên con số phải **y hệt** Task 3.

- [ ] **Step 6: Commit**

```bash
git add docs/contracts/mat-bang-agent.md CLAUDE.md
git commit -m "docs(re): hợp đồng đọc mặt bằng cho repo agent"
```

---

## Sau khi xong bốn task

1. Review toàn nhánh (`superpowers:requesting-code-review`).
2. Bàn giao lệnh push cho người dùng — **không tự push**.
3. Chuyển sang [2026-08-10-vong-2-frontend.md](2026-08-10-vong-2-frontend.md): nó phụ thuộc `total`/`offset` của Task 2–3 và việc bỏ trần của Task 1.
4. Nhắc người dùng **copy tay** `docs/contracts/mat-bang-agent.md` sang repo `odyssey-agent`.
