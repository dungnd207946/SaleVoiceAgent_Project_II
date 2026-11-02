# Mở rộng API feedback + PhienOut.phone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm 3 mở rộng additive vào backend (`odyssey-portal-backend`) để FE dựng được màn `/quality` (feedback agent) và deep-link đúng phiên từ `/convos`: (1) `PhienOut.phone`, (2) filter `rating`/`session_id` cho `GET /agent/feedback`, (3) `FeedbackOut.customer_name`/`phone` + `DanhSachFeedbackOut.theo_sao`/`diem_trung_binh`.

**Architecture:** Cả ba đều mở rộng response/query đã có trong hai module `ops` (M7 — Hội thoại) và `enrollment` (M10 — đấu nối agent). Không migration mới, không endpoint mới, không breaking change cho ai đang đọc các response này.

**Tech Stack:** FastAPI, asyncpg, Pydantic v2, pytest + pytest-asyncio, testcontainers Postgres (qua `pg_dsn`/`pool`/`api_pool` fixture có sẵn).

## Global Constraints

- Mọi câu SQL chạm `tenant_data` phải mang vị từ `tenant_id = portal.current_tenant()` (luật 1, CLAUDE.md) — không viết câu nào thiếu nó.
- `tenant_id` KHÔNG BAO GIỜ nhận từ input client — service tự suy (từ `Principal.tenant_id` phiên, hoặc từ `repo.tra_khoa()` theo api_key).
- Response model đổi hình dạng ⇒ cập nhật `docs/contracts/dau-noi-agent.md` nếu field đó nằm trong hợp đồng với `santa-hotline-agent` (chỉ áp cho việc 2/3 — endpoint `/agent/feedback`; việc 1 là nội bộ Portal, module `ops` không nằm trong hợp đồng đó).
- Chạy `uv run ruff check .` và `uv run ruff format --check .` xanh trước khi commit mỗi task.
- Toàn bộ lệnh pytest chạy bằng `.venv/bin/python -m pytest ...` (venv đã dựng sẵn trong repo).

---

### Task 1: `ops.contracts.PhienOut` thêm `phone`

**Files:**
- Modify: `src/portal/modules/ops/repo.py:124-127` (hằng `_COT_PHIEN`), `src/portal/modules/ops/repo.py:170-182` (`doc_phien`)
- Modify: `src/portal/modules/ops/contracts.py` (class `PhienOut`)
- Modify: `src/portal/modules/ops/router.py:61-73` (hàm `_ra_phien`)
- Test: `tests/modules/ops/test_api.py`

**Interfaces:**
- Consumes: `_COT_PHIEN` (hằng string nối vào 2 câu SQL: `liet_ke_phien` và `doc_phien`, cả hai đều `GROUP BY {_COT_PHIEN}, ...`)
- Produces: `PhienOut.phone: str | None` — dùng ở CẢ HAI endpoint `GET /convos/khach/{phone}/phien` (list) và `GET /convos/phien/{session_id}` (chi tiết), vì cả hai đều gọi chung `_ra_phien()`.

⚠️ **Bẫy đã phát hiện, đọc trước khi sửa:** `doc_phien()` hiện SELECT `c.phone` RIÊNG (ngoài `_COT_PHIEN`) chỉ cho câu SQL của chính nó — `liet_ke_phien()` (dùng `_COT_PHIEN` không có `phone`) thì KHÔNG có cột này trong `Record` trả về. Hai hàm này đều feed vào CÙNG một `_ra_phien()`. Nếu chỉ thêm `phone=r["phone"]` vào `_ra_phien()` mà không sửa gì ở `liet_ke_phien()`, endpoint `GET /convos/khach/{phone}/phien` sẽ **502 KeyError** ngay khi FE gọi tới (vì `Record` từ câu SQL đó không có khoá `"phone"`). Cách đúng: chuyển `c.phone` vào **`_COT_PHIEN`** (dùng chung cả hai câu), và bỏ dòng SELECT `c.phone` riêng lẻ trong `doc_phien()` (nay trùng — `_COT_PHIEN` đã mang nó).

- [ ] **Step 1: Viết test thất bại cho endpoint chi tiết (`doc_phien`)**

Thêm vào `tests/modules/ops/test_api.py`, ngay dưới `test_chi_tiet_phien_tra_luot_theo_thu_tu`:

```python
async def test_chi_tiet_phien_tra_phone(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-anh")

    assert r.status_code == 200
    assert r.json()["phien"]["phone"] == "0912448111"


async def test_chi_tiet_phien_khong_so_thi_phone_null(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-an")

    assert r.status_code == 200
    assert r.json()["phien"]["phone"] is None
```

(`du_lieu` fixture đã tạo `s-anh` với `phone="0912448111"` và `s-an` với `phone=None` — xem `tests/modules/ops/test_api.py:12-19`.)

- [ ] **Step 2: Viết test thất bại cho endpoint danh sách (`liet_ke_phien`) — chính bẫy KeyError**

Thêm vào cùng file:

```python
async def test_liet_ke_phien_tra_phone(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["phone"] == "0912448111"
```

- [ ] **Step 3: Chạy test để xác nhận thất bại**

Run: `.venv/bin/python -m pytest tests/modules/ops/test_api.py -k "phone" -v`
Expected: FAIL — `pydantic.ValidationError` (thiếu trường `phone` trong `PhienOut`), vì contract chưa khai trường này.

- [ ] **Step 4: Thêm `phone` vào `_COT_PHIEN`, bỏ SELECT riêng trong `doc_phien`**

Sửa `src/portal/modules/ops/repo.py`:

```python
_COT_PHIEN = """
    c.session_id, c.customer_name, c.started_at, c.ended_at, c.summary, c.project,
    c.transferred_to_sales, c.running_version, c.source, c.phone
"""
```

Trong `doc_phien()`, đổi:

```python
    return await conn.fetchrow(
        f"""
        SELECT {_COT_PHIEN}, c.phone, c.skill_calls, count(m.seq) AS so_luot,
               (array_agg(m.content ORDER BY m.seq)
                  FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
          FROM tenant_data.conversations c
          LEFT JOIN tenant_data.conversation_messages m
                 ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
         WHERE c.tenant_id = portal.current_tenant() AND c.session_id = $1
         GROUP BY {_COT_PHIEN}, c.phone, c.skill_calls, c.created_at
        """,
        session_id,
    )
```

thành (bỏ `c.phone` trùng lặp ở cả SELECT lẫn GROUP BY, vì `_COT_PHIEN` đã mang nó):

```python
    return await conn.fetchrow(
        f"""
        SELECT {_COT_PHIEN}, c.skill_calls, count(m.seq) AS so_luot,
               (array_agg(m.content ORDER BY m.seq)
                  FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
          FROM tenant_data.conversations c
          LEFT JOIN tenant_data.conversation_messages m
                 ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
         WHERE c.tenant_id = portal.current_tenant() AND c.session_id = $1
         GROUP BY {_COT_PHIEN}, c.skill_calls, c.created_at
        """,
        session_id,
    )
```

Thêm một dòng docstring giải thích (ngay trên `_COT_PHIEN`):

```python
# `phone` nằm trong bộ cột dùng chung (không phải riêng `doc_phien`) từ 2026-08-12:
# FE cần nó ở CẢ danh sách phiên lẫn chi tiết phiên để suy `/convos/$phone` từ một
# `session_id` (màn feedback `/quality`). Để riêng ở `doc_phien` như trước sẽ làm
# `_ra_phien()` KeyError khi gọi từ `liet_ke_phien()` (Record đó không có cột này).
```

- [ ] **Step 5: Thêm `phone` vào `PhienOut`**

Sửa `src/portal/modules/ops/contracts.py`, trong `class PhienOut`, thêm sau `source: str | None`:

```python
    #: Số điện thoại của khách — để FE suy `/convos/$phone` từ một `session_id`
    #: (không có cách nào khác tra ngược, xem `docs/superpowers/specs` phía FE).
    #: `None` = nhóm «Chưa có số» (cùng ngữ nghĩa `KhachOut.ten`).
    phone: str | None
```

- [ ] **Step 6: Thêm `phone=r["phone"]` vào `_ra_phien()`**

Sửa `src/portal/modules/ops/router.py`:

```python
def _ra_phien(r: asyncpg.Record) -> PhienOut:
    return PhienOut(
        sessionId=r["session_id"],
        ten=r["customer_name"],
        batDau=r["started_at"],
        ketThuc=r["ended_at"],
        soLuot=r["so_luot"],
        tinNhanDau=r["tin_nhan_dau"],
        summary=r["summary"],
        duAn=r["project"],
        daChuyen=r["transferred_to_sales"],
        runningVersion=r["running_version"],
        source=r["source"],
        phone=r["phone"],
    )
```

- [ ] **Step 7: Chạy lại test, xác nhận qua**

Run: `.venv/bin/python -m pytest tests/modules/ops/test_api.py -v`
Expected: PASS toàn bộ (test cũ + 3 test mới).

- [ ] **Step 8: Lint + chạy toàn bộ test module ops**

Run: `uv run ruff check src/portal/modules/ops/ && uv run ruff format --check src/portal/modules/ops/ && .venv/bin/python -m pytest tests/modules/ops -v`
Expected: tất cả PASS, lint sạch.

- [ ] **Step 9: Commit**

```bash
git add src/portal/modules/ops/repo.py src/portal/modules/ops/contracts.py src/portal/modules/ops/router.py tests/modules/ops/test_api.py
git commit -m "feat(ops): PhienOut trả thêm phone — FE suy /convos/\$phone từ session_id"
```

---

### Task 2: `GET /agent/feedback` thêm filter `rating` + `session_id`

**Files:**
- Modify: `src/portal/modules/enrollment/service.py:238-281` (`liet_ke_feedback_cua_tenant`)
- Modify: `src/portal/modules/enrollment/router_tenant.py:119-129` (`liet_ke_feedback`)
- Test: `tests/modules/enrollment/test_feedback.py`

**Interfaces:**
- Consumes: `contracts.DanhSachFeedbackOut` (không đổi hình dạng ở task này — chỉ đổi câu WHERE của query bên dưới)
- Produces: `service.liet_ke_feedback_cua_tenant(pool, tenant_id, limit, before_id, ratings=None, session_id=None) -> contracts.DanhSachFeedbackOut` — chữ ký MỚI có 2 tham số cuối, cả hai optional với default `None` (giữ tương thích ngược với mọi lời gọi hiện có không truyền chúng).

- [ ] **Step 1: Viết test thất bại — filter `session_id`**

Thêm vào `tests/modules/enrollment/test_feedback.py`, sau `test_liet_ke_feedback_phan_trang_keyset`:

```python
async def test_liet_ke_feedback_loc_theo_session_id(client_admin):
    khoa = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_muc_tieu", "rating": 5},
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_khac", "rating": 1},
    )

    r = await client_admin.get(f"{GOC}/feedback", params={"session_id": "sess_muc_tieu"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["session_id"] for i in body["items"]] == ["sess_muc_tieu"]
```

- [ ] **Step 2: Viết test thất bại — filter `rating` (lặp lại, đa chọn)**

```python
async def test_liet_ke_feedback_loc_theo_rating(client_admin):
    khoa = await _tao_khoa(client_admin)
    for i, rating in enumerate((1, 3, 5)):
        await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": f"sess_r{i}", "rating": rating},
        )

    r = await client_admin.get(f"{GOC}/feedback", params=[("rating", 1), ("rating", 5)])
    assert r.status_code == 200, r.text
    ratings = sorted(i["rating"] for i in r.json()["items"])
    assert ratings == [1, 5]
```

- [ ] **Step 3: Chạy test, xác nhận thất bại**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -k "loc_theo" -v`
Expected: FAIL — `422 Unprocessable Entity` (tham số `session_id`/`rating` chưa khai ở endpoint, FastAPI/Pydantic từ chối tham số lạ trên query... thực ra FastAPI mặc định BỎ QUA query param lạ không khai, nên thực tế test sẽ FAIL vì filter không có tác dụng — cả hai session/rating đều trả về, không lọc). Assertion `assert [...] == ["sess_muc_tieu"]` sẽ thấy cả hai session và fail.

- [ ] **Step 4: Sửa `service.liet_ke_feedback_cua_tenant` nhận thêm filter**

Sửa `src/portal/modules/enrollment/service.py`:

```python
async def liet_ke_feedback_cua_tenant(
    pool: asyncpg.Pool,
    tenant_id: str,
    limit: int,
    before_id: int | None,
    ratings: list[int] | None = None,
    session_id: str | None = None,
) -> contracts.DanhSachFeedbackOut:
    """Feedback của workspace hiện tại, mới nhất trước — đường FE Portal (`router_tenant.py`).

    Xin thừa `limit + 1` hàng để biết có trang sau mà không cần một câu COUNT
    riêng cho việc đó — `total` vẫn cần một COUNT thật vì FE dựng thanh trang có
    số (cùng lý lẽ `TrangDuAn.total` ở module realestate).

    `ratings`/`session_id` chỉ lọc DANH SÁCH (`items`) — KHÔNG lọc thống kê
    tổng (`total`, `theo_sao`, `diem_trung_binh` — thêm ở service này bởi task
    khác), vì thống kê phải phản ánh TOÀN BỘ feedback của tenant bất kể đang
    lọc gì trên màn.
    """
    dieu_kien = ["tenant_id = portal.current_tenant()"]
    tham_so: list[object] = []

    if ratings:
        tham_so.append(ratings)
        dieu_kien.append(f"rating = ANY(${len(tham_so)})")
    if session_id:
        tham_so.append(session_id)
        dieu_kien.append(f"session_id = ${len(tham_so)}")

    where_items = " AND ".join(dieu_kien)

    async with tenant_conn(pool, tenant_id) as conn:
        if before_id is None:
            rows = await conn.fetch(
                f"""
                SELECT id, session_id, rating, comment, created_at
                  FROM tenant_data.agent_feedback
                 WHERE {where_items}
                 ORDER BY id DESC
                 LIMIT ${len(tham_so) + 1}
                """,
                *tham_so,
                limit + 1,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT id, session_id, rating, comment, created_at
                  FROM tenant_data.agent_feedback
                 WHERE {where_items} AND id < ${len(tham_so) + 1}
                 ORDER BY id DESC
                 LIMIT ${len(tham_so) + 2}
                """,
                *tham_so,
                before_id,
                limit + 1,
            )
        total = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.agent_feedback WHERE tenant_id = portal.current_tenant()"
        )

    co_trang_sau = len(rows) > limit
    rows = rows[:limit]
    return contracts.DanhSachFeedbackOut(
        items=[contracts.FeedbackOut(**r) for r in rows],
        next_before_id=rows[-1]["id"] if co_trang_sau and rows else None,
        total=total,
    )
```

⚠️ Lưu ý tham số vị trí `$N` phải khớp đúng thứ tự `tham_so` rồi mới tới `before_id`/`limit` — xây chuỗi SQL bằng f-string CHỈ cho **tên cột** (`ANY($n)`), giá trị luôn đi qua `$n` (asyncpg), không bao giờ ghép thẳng vào SQL.

- [ ] **Step 5: Sửa endpoint nhận 2 query param mới**

Sửa `src/portal/modules/enrollment/router_tenant.py`:

```python
@ROUTER_TENANT.get("/feedback", response_model=contracts.DanhSachFeedbackOut)
async def liet_ke_feedback(
    limit: int = Query(default=contracts.FEEDBACK_TRANG_MAC_DINH, gt=0, le=contracts.FEEDBACK_GIOI_HAN_TRANG),
    before_id: int | None = Query(default=None),
    rating: list[int] = Query(default=[]),
    session_id: str | None = Query(default=None),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.DanhSachFeedbackOut:
    """Feedback của workspace hiện tại, mới nhất trước — cùng quyền xem Hội thoại
    (`ACTIONS.CONVOS_READ`, PQ_01 nhóm 2): feedback là một góc nhìn khác của
    cùng dữ liệu hội thoại, không phải một khái niệm quyền riêng.

    `rating` lặp lại được (`?rating=1&rating=2`) — lọc theo TẬP sao. `session_id`
    lọc đúng một phiên — dùng khi FE nhúng feedback vào chi tiết một hội thoại
    (`PhienKhach.tsx`), thay vì cần một endpoint riêng.
    """
    return await service.liet_ke_feedback_cua_tenant(
        pool, p.tenant_id, limit, before_id, ratings=rating or None, session_id=session_id
    )
```

- [ ] **Step 6: Chạy lại test, xác nhận qua**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/portal/modules/enrollment/ && uv run ruff format --check src/portal/modules/enrollment/`
Expected: sạch.

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/enrollment/service.py src/portal/modules/enrollment/router_tenant.py tests/modules/enrollment/test_feedback.py
git commit -m "feat(enrollment): GET /agent/feedback thêm filter rating[] + session_id"
```

---

### Task 3: `FeedbackOut` thêm `customer_name`/`phone` qua LEFT JOIN

**Files:**
- Modify: `src/portal/modules/enrollment/contracts.py` (class `FeedbackOut`)
- Modify: `src/portal/modules/enrollment/service.py` (`liet_ke_feedback_cua_tenant`)
- Test: `tests/modules/enrollment/test_feedback.py`

**Interfaces:**
- Consumes: bảng `tenant_data.conversations` (đã có, cột `tenant_id`, `session_id`, `phone`, `customer_name`) — KHÔNG FK, chỉ JOIN tại thời điểm đọc.
- Produces: `contracts.FeedbackOut.customer_name: str | None`, `contracts.FeedbackOut.phone: str | None`.

⚠️ Test module `enrollment` không có fixture sẵn để tạo hàng `tenant_data.conversations` (module đó không sở hữu bảng này). Dùng `pool.execute()` chèn thẳng trong test, giống cách `tests/modules/ops/conftest.py::them_phien` làm ở module `ops` nhưng viết tại chỗ (đủ đơn giản để không cần factory riêng).

- [ ] **Step 1: Viết test thất bại — có hàng `conversations` khớp**

Thêm vào `tests/modules/enrollment/test_feedback.py`:

```python
async def test_liet_ke_feedback_join_ten_va_sdt_tu_conversations(client_admin, pool):
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, phone, customer_name)
        VALUES ($1, $2, $3, $4)
        """,
        TENANT_A,
        "sess_co_ten",
        "0912345678",
        "Trần Văn A",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_co_ten", "rating": 5},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["customer_name"] == "Trần Văn A"
    assert item["phone"] == "0912345678"


async def test_liet_ke_feedback_khong_co_conversations_thi_null(client_admin):
    """Feedback vẫn hiện được dù chưa từng có hàng `conversations` khớp —
    KHÔNG FK, đúng lý lẽ đã chốt (agent có thể gọi feedback trước/độc lập
    với việc ghi conversations)."""
    khoa = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_khong_co_conv", "rating": 3},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["session_id"] == "sess_khong_co_conv")
    assert item["customer_name"] is None
    assert item["phone"] is None
```

- [ ] **Step 2: Viết test thất bại — cách ly tenant qua JOIN**

```python
async def test_liet_ke_feedback_join_khong_lo_ten_tenant_khac(client_admin, pool):
    """Cùng session_id trùng ở hai tenant KHÔNG được lộ tên/sđt của tenant kia
    qua JOIN — vị từ JOIN phải mang CẢ tenant_id, không chỉ session_id."""
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, phone, customer_name)
        VALUES ($1, $2, $3, $4)
        """,
        TENANT_B,
        "sess_trung_id",
        "0900000000",
        "Người của B",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_trung_id", "rating": 4},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    item = next(i for i in r.json()["items"] if i["session_id"] == "sess_trung_id")
    assert item["customer_name"] is None
    assert item["phone"] is None
```

- [ ] **Step 3: Chạy test, xác nhận thất bại**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -k "join" -v`
Expected: FAIL — `pydantic.ValidationError` hoặc `KeyError` (`FeedbackOut` chưa có `customer_name`/`phone`, service chưa JOIN).

- [ ] **Step 4: Thêm 2 trường vào `FeedbackOut`**

Sửa `src/portal/modules/enrollment/contracts.py`:

```python
class FeedbackOut(BaseModel):
    id: int
    session_id: str
    rating: int
    comment: str
    created_at: datetime
    #: Từ `tenant_data.conversations` cùng `(tenant_id, session_id)` — KHÔNG FK
    #: (agent có thể gọi feedback trước/độc lập với việc ghi conversations,
    #: cùng lý lẽ `conversation_messages`). `None` khi không có hàng khớp.
    customer_name: str | None
    phone: str | None
```

- [ ] **Step 5: Thêm LEFT JOIN vào 2 câu SELECT trong `service.liet_ke_feedback_cua_tenant`**

Sửa cả hai nhánh (`before_id is None` / `else`) trong `src/portal/modules/enrollment/service.py`, đổi:

```python
                SELECT id, session_id, rating, comment, created_at
                  FROM tenant_data.agent_feedback
```

thành (cả hai chỗ):

```python
                SELECT f.id, f.session_id, f.rating, f.comment, f.created_at,
                       c.customer_name, c.phone
                  FROM tenant_data.agent_feedback f
                  LEFT JOIN tenant_data.conversations c
                         ON c.tenant_id = f.tenant_id AND c.session_id = f.session_id
```

và đổi `tenant_id = portal.current_tenant()` → `f.tenant_id = portal.current_tenant()`, `session_id = $N`/`id < $N` → `f.session_id = $N`/`f.id < $N` (thêm tiền tố bảng `f.` vì giờ có 2 bảng trong câu). Cập nhật `where_items`/điều kiện tương ứng trong `dieu_kien` list ở Task 2 cho khớp tiền tố `f.`.

- [ ] **Step 6: Chạy lại test, xác nhận qua**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -v`
Expected: PASS toàn bộ (bao gồm mọi test cũ từ Task 1/2 — xác nhận đổi tiền tố `f.` không phá gì).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check src/portal/modules/enrollment/ && uv run ruff format --check src/portal/modules/enrollment/
git add src/portal/modules/enrollment/contracts.py src/portal/modules/enrollment/service.py tests/modules/enrollment/test_feedback.py
git commit -m "feat(enrollment): FeedbackOut thêm customer_name/phone qua LEFT JOIN conversations"
```

---

### Task 4: `DanhSachFeedbackOut` thêm `theo_sao` + `diem_trung_binh`

**Files:**
- Modify: `src/portal/modules/enrollment/contracts.py` (class `DanhSachFeedbackOut`)
- Modify: `src/portal/modules/enrollment/service.py` (`liet_ke_feedback_cua_tenant`)
- Test: `tests/modules/enrollment/test_feedback.py`

**Interfaces:**
- Produces: `contracts.DanhSachFeedbackOut.theo_sao: dict[str, int]` (khoá `"1".."5"`, LUÔN đủ 5 khoá kể cả đếm 0), `contracts.DanhSachFeedbackOut.diem_trung_binh: float` (làm tròn 2 chữ số thập phân, `0.0` khi chưa có feedback nào).

⚠️ **Bất biến quan trọng nhất của task này**: `theo_sao`/`diem_trung_binh` tính trên **TOÀN BỘ** feedback của tenant, **bỏ qua filter `rating`/`session_id`** đang áp cho `items` (đã ghi trong spec — dải thống kê phải phản ánh tổng thể, không phải tập đã lọc). Câu SQL đếm theo sao phải dùng `WHERE tenant_id = portal.current_tenant()` TRẦN, không cộng `dieu_kien` của Task 2/3.

- [ ] **Step 1: Viết test thất bại**

```python
async def test_liet_ke_feedback_thong_ke_khong_bi_anh_huong_boi_filter(client_admin):
    khoa = await _tao_khoa(client_admin)
    for i, rating in enumerate((1, 1, 5)):
        await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": f"sess_tk{i}", "rating": rating},
        )

    # Lọc chỉ 5 sao — items chỉ còn 1 hàng, nhưng thống kê vẫn phải phản ánh CẢ 3.
    r = await client_admin.get(f"{GOC}/feedback", params=[("rating", 5)])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["theo_sao"] == {"1": 2, "2": 0, "3": 0, "4": 0, "5": 1}
    assert body["diem_trung_binh"] == pytest.approx((1 + 1 + 5) / 3, abs=0.01)


async def test_liet_ke_feedback_thong_ke_rong_khi_chua_co_gi(client_admin):
    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["theo_sao"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    assert body["diem_trung_binh"] == 0.0
```

Thêm `import pytest` vào đầu `tests/modules/enrollment/test_feedback.py` nếu chưa có (cần cho `pytest.approx`).

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -k "thong_ke" -v`
Expected: FAIL — `pydantic.ValidationError` (`DanhSachFeedbackOut` chưa có `theo_sao`/`diem_trung_binh`).

- [ ] **Step 3: Thêm 2 trường vào `DanhSachFeedbackOut`**

Sửa `src/portal/modules/enrollment/contracts.py`:

```python
class DanhSachFeedbackOut(BaseModel):
    """Phân trang keyset theo `id DESC` (mới nhất trước). KHÔNG đục cursor như
    `realestate.contracts.ma_con_tro` — lộ `id` trần ở đây không mở ra gì: hàng
    đã bị RLS + `ACTIONS.CONVOS_READ` khoá vào đúng một workspace, và FE feedback
    không cần một hợp đồng cursor riêng cho một danh sách nhỏ, chỉ đọc."""

    items: list[FeedbackOut]
    next_before_id: int | None = None
    """Truyền lại làm `before_id` để lấy trang sau. `None` = hết trang."""
    total: int
    theo_sao: dict[str, int]
    """Khoá `"1".."5"`, LUÔN đủ 5 khoá (đếm 0 vẫn có mặt) — FE vẽ 5 thanh phân bố
    không phải tự lấp khoá thiếu. Tính trên TOÀN BỘ feedback của tenant, KHÔNG
    theo filter `rating`/`session_id` đang áp cho `items` (xem service)."""
    diem_trung_binh: float
    """Làm tròn 2 chữ số. `0.0` khi tenant chưa có feedback nào — KHÔNG `None`,
    vì FE hiện số này trực tiếp (`4.3`) và `None` buộc FE tự thêm nhánh rẽ cho
    một ca chỉ xảy ra lúc mới bắt đầu dùng tính năng."""
```

- [ ] **Step 4: Thêm câu đếm-theo-sao vào service, tính độc lập filter**

Sửa `src/portal/modules/enrollment/service.py`, trong khối `async with tenant_conn(...)`, thêm sau câu `total = await conn.fetchval(...)`:

```python
        theo_sao_rows = await conn.fetch(
            """
            SELECT rating, count(*) AS n
              FROM tenant_data.agent_feedback
             WHERE tenant_id = portal.current_tenant()
             GROUP BY rating
            """
        )
```

Sau khi thoát khối `async with` (hoặc ngay trước `return`), tính hai giá trị tổng hợp:

```python
    theo_sao = {str(i): 0 for i in range(1, 6)}
    tong_diem = 0
    for r in theo_sao_rows:
        theo_sao[str(r["rating"])] = r["n"]
        tong_diem += r["rating"] * r["n"]
    diem_trung_binh = round(tong_diem / total, 2) if total else 0.0

    co_trang_sau = len(rows) > limit
    rows = rows[:limit]
    return contracts.DanhSachFeedbackOut(
        items=[contracts.FeedbackOut(**r) for r in rows],
        next_before_id=rows[-1]["id"] if co_trang_sau and rows else None,
        total=total,
        theo_sao=theo_sao,
        diem_trung_binh=diem_trung_binh,
    )
```

- [ ] **Step 5: Chạy lại toàn bộ test feedback, xác nhận qua**

Run: `.venv/bin/python -m pytest tests/modules/enrollment/test_feedback.py -v`
Expected: PASS toàn bộ (mọi test từ 4 task, không test nào đỏ vì thiếu `theo_sao`/`diem_trung_binh` — Pydantic yêu cầu đủ trường bắt buộc, nên các assertion cũ chỉ đọc field cụ thể vẫn qua).

- [ ] **Step 6: Lint + chạy toàn bộ suite enrollment + ops (hồi quy)**

Run: `uv run ruff check src/portal/modules/enrollment/ && uv run ruff format --check src/portal/modules/enrollment/ && .venv/bin/python -m pytest tests/modules/enrollment tests/modules/ops tests/unit -v`
Expected: tất cả PASS.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/enrollment/contracts.py src/portal/modules/enrollment/service.py tests/modules/enrollment/test_feedback.py
git commit -m "feat(enrollment): DanhSachFeedbackOut thêm theo_sao + diem_trung_binh (không theo filter)"
```

---

### Task 5: Cập nhật hợp đồng agent (`docs/contracts/dau-noi-agent.md`)

**Files:**
- Modify: `docs/contracts/dau-noi-agent.md` §2b (mục Feedback, thêm ở phiên trước)

**Interfaces:** không có — chỉ tài liệu.

⚠️ Việc 2/3 (filter + JOIN) chỉ ảnh hưởng `GET /agent/feedback` — endpoint đó KHÔNG nằm trong hợp đồng gửi `santa-hotline-agent` (agent chỉ gọi `POST /agent/feedback`, không gọi GET; GET là của FE Portal qua session). Response `POST /agent/feedback` (204, không body) không đổi gì ở cả 4 task trên. **Không cần banner breaking-change nào** — chỉ cần một dòng Change Log ở CLAUDE.md ghi lại mở rộng, không phải một mục hợp đồng mới.

- [ ] **Step 1: Thêm dòng Change Log vào `CLAUDE.md`**

Thêm một dòng mới ở đầu bảng Change Log (theo mẫu các dòng 2026-08-12 đã có):

```markdown
| 2026-08-12 | **Mở rộng API phục vụ màn `/quality` (FE) — 4 việc additive, không breaking**: (1) `ops.contracts.PhienOut` thêm `phone` (sửa `_COT_PHIEN` dùng chung cho `liet_ke_phien`/`doc_phien`, tránh KeyError); (2) `GET /agent/feedback` thêm filter `rating[]`/`session_id`; (3) `enrollment.contracts.FeedbackOut` thêm `customer_name`/`phone` qua LEFT JOIN `tenant_data.conversations` (không FK); (4) `DanhSachFeedbackOut` thêm `theo_sao`/`diem_trung_binh`, tính trên TOÀN BỘ feedback bất kể filter đang áp cho `items`. Không đụng `POST /agent/feedback` — hợp đồng với `santa-hotline-agent` không đổi. |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: changelog 4 mở rộng API phục vụ màn /quality"
```
