# Nối chiều index Qdrant cho cổng nạp — kế hoạch thi công

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cổng nạp dữ liệu ngoài đặt việc nạp lên Qdrant cho bản ghi vừa chiếu, để
`kb_search` và `send_media` của agent thấy được dữ liệu đẩy qua API.

**Architecture:** Móc vào `ingest/chieu.py::chieu_mot()` ngay sau `_upsert`, trong cùng
savepoint của bản ghi — đối xứng với `_xep_purge` đã nằm ở đó, và phủ cả đường
nhặt-con-đang-chờ vì đường đó cũng gọi `chieu_mot`. Cổng nạp chỉ **đặt việc**; toàn bộ
pipeline nhúng vector giữ nguyên, không sửa `modules/kb`. Kèm một CRM giả + adapter để
xác minh trọn chuỗi tới Qdrant.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · pytest (`asyncio_mode=auto`) ·
qdrant-client · httpx · Pillow · python-docx · openpyxl · uv.

**Spec:** [`docs/superpowers/specs/2026-08-17-noi-chieu-index-cho-cong-nap-design.md`](../specs/2026-08-17-noi-chieu-index-cho-cong-nap-design.md)

## Global Constraints

- Nhánh làm việc: `feat/api-ingest`. **Không** checkout, merge, push tới `develop`.
  Không `git push` — người dùng tự push.
- **Không sửa một dòng nào trong `src/portal/modules/kb/`.** Nếu thấy cần sửa thì chỗ móc
  đã chọn sai — dừng và báo.
- **Không thêm dependency.** Mọi thứ cần đã có trong `pyproject.toml`.
- **Không sửa `scripts/demo_cong_nap_e2e.py`** — nó chạy được không cần embed, giữ nguyên
  tính chất đó.
- Luật 3 (`tests/test_module_boundaries.py`, đọc AST): module chỉ import
  `portal.core.*` và `portal.modules.<khác>.contracts`. Hai hàm đặt việc phải import qua
  `portal.modules.kb.contracts`, **không** import `portal.modules.kb.ops.enqueue`.
- Mọi endpoint HTTP mới phải khai `require(...)` (`tests/api/test_moi_route_khai_action.py`).
  Kế hoạch này không thêm endpoint nào vào `src/portal` nên không chạm luật đó.
- Ruff: line-length 120, target py313, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước commit.
- `actor` của mọi việc do cổng nạp đặt là chuỗi `"ingest"` — khớp `_xep_purge` đã dùng.
- Commit: tiếng Anh, ngắn, **không** dòng `Co-Authored-By`.

---

### Task 1: Đặt việc nạp theo entity

**Files:**
- Modify: `src/portal/modules/ingest/chieu.py`
- Test: `tests/modules/ingest/test_xep_viec_nap.py` (tạo mới)

**Interfaces:**
- Consumes: `dat_viec_nap` / `dat_viec_thumb` từ `portal.modules.kb.contracts` (mặt tiền
  `__getattr__`, đã có sẵn cho `modules/realestate`):
  - `dat_viec_nap(conn, *, tenant_id: str, actor: str, entity: str, record_id: int, project_code: str, vertical: str = "real_estate") -> int | None`
  - `dat_viec_thumb(conn, *, tenant_id: str, actor: str, entity: str, record_id: int, project_code: str, ghi_de: bool = False, tu_duyet: bool = False) -> int | None`
  - Cả hai trả `None` khi record đã có việc cùng `kind` ở trạng thái `queued` (tự gộp).
- Produces:
  - `chieu._upsert(...) -> int` — nay TRẢ VỀ `id` của hàng vừa ghi (trước đây trả `None`).
  - `chieu._qua_viec_thumb(entity: Entity, cot: dict[str, object]) -> bool`
  - `chieu._xep_nap(conn, tenant_id: str, *, entity: Entity, record_id: int, cot: dict[str, object]) -> None`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/ingest/test_xep_viec_nap.py`:

```python
"""Cổng nạp đặt việc lên Qdrant — bảng luật theo entity.

Cùng khuôn `test_nap.py`: gọi THẲNG `service.nap_lo` bằng `api_pool` (role `portal_api`),
không qua HTTP. Kiểm ở tầng `control.jobs` vì đó là ranh giới thật giữa cổng nạp và
pipeline nhúng — cổng nạp không nhúng gì, nó chỉ đặt việc.
"""

import json
from datetime import UTC, datetime

import pytest

from portal.modules.ingest import contracts, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def _bg(entity: str, ma: str, data: dict, *, luc: datetime = LUC, op: str = "upsert"):
    return contracts.BanGhiIn(entity=entity, externalId=ma, op=op, occurredAt=luc, data=data)


def _lo(*bg):
    return contracts.LoNapIn(records=list(bg), syncId="test-viec")


DU_AN = {"name": "Khu đô thị Thử", "region": "Hà Nội", "category": ["chung_cu"]}
PHAN_KHU = {"projectExternalId": "P1", "name": "Phân khu A"}
CAN = {
    "projectExternalId": "P1",
    "zoneExternalId": "Z1",
    "unitCode": "A-1203",
    "saleStatus": "available",
    "productType": "chung_cu",
    "priceVnd": 4850000000,
}
ANH = {
    "projectExternalId": "P1",
    "mediaUrl": "https://cdn.thu.vn/phoi-canh.jpg",
    "contentType": "image",
    "category": "tong_quan",
}
TAI_LIEU_CO_CHU = {"projectExternalId": "P1", "title": "Bảng giá tháng 8", "body": "Giá từ 45 triệu/m²"}
TAI_LIEU_CHI_TEP = {"projectExternalId": "P1", "title": "Chính sách bán hàng", "fileUrl": "tenants/x/csbh.docx"}


async def _viec(pool, tenant_id: str, kind: str) -> list[dict]:
    """Payload mọi việc `kind` của tenant, cũ → mới."""
    rows = await pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id",
        tenant_id,
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


async def test_du_an_va_phan_khu_dat_viec_nap(api_pool, hai_tenant):
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU)),
        dry_run=False,
    )
    assert ra.accepted == 2, ra.results

    viec = await _viec(api_pool, a, "kb_index")
    bang = sorted(v["entity"] for v in viec)
    assert bang == ["projects", "zones"], viec


async def test_can_khong_dat_viec_nao(api_pool, hai_tenant):
    """`units` không nhúng — agent lọc căn bằng SQL trên cột thật."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU), _bg("unit", "U1", CAN)),
        dry_run=False,
    )
    viec = await _viec(api_pool, a, "kb_index")
    assert all(v["entity"] != "units" for v in viec), viec


async def test_anh_dat_viec_thumb_chu_khong_dat_viec_nap(api_pool, hai_tenant):
    """Đặt nạp thẳng thì point mang `thumb_url` rỗng vĩnh viễn và không gì kích hoạt lại."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN), _bg("media", "M1", ANH)), dry_run=False
    )
    thumb = await _viec(api_pool, a, "kb_thumb")
    nap = await _viec(api_pool, a, "kb_index")
    assert [v["entity"] for v in thumb] == ["media"], thumb
    assert all(v["entity"] != "media" for v in nap), nap


async def test_tai_lieu_co_body_dat_viec_nap(api_pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    nap = await _viec(api_pool, a, "kb_index")
    assert any(v["entity"] == "documents" for v in nap), nap
    assert await _viec(api_pool, a, "kb_thumb") == []


async def test_tai_lieu_chi_co_tep_dat_viec_thumb_va_tu_duyet(api_pool, hai_tenant):
    """Chuỗi thumb → bóc chữ → nạp. `tu_duyet` bỏ van duyệt OCR vì tenant dùng API
    không có ai ngồi trong portal để duyệt (quyết định #3 của spec)."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D2", TAI_LIEU_CHI_TEP)),
        dry_run=False,
    )
    thumb = await _viec(api_pool, a, "kb_thumb")
    assert len(thumb) == 1, thumb
    assert thumb[0]["entity"] == "documents"
    assert thumb[0]["tu_duyet"] is True, thumb[0]
    assert await _viec(api_pool, a, "kb_index") != [], "dự án vẫn phải có việc nạp"


async def test_payload_viec_mang_project_code(api_pool, hai_tenant):
    """Chỉ báo tiến độ đếm theo khoá này; việc thiếu nó không đếm vào dự án nào."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU), _bg("media", "M1", ANH)),
        dry_run=False,
    )
    moi = await _viec(api_pool, a, "kb_index") + await _viec(api_pool, a, "kb_thumb")
    assert moi, "không có việc nào được đặt"
    assert all(v.get("project_code") for v in moi), moi


async def test_day_lai_y_het_khong_nhan_doi_viec(api_pool, hai_tenant):
    """Hai hàm đặt việc tự gộp khi record đã có việc cùng loại đang `queued`."""
    a, _ = hai_tenant
    lo = _lo(_bg("project", "P1", DU_AN))
    await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    assert len(await _viec(api_pool, a, "kb_index")) == 1


async def test_viec_thuoc_dung_tenant(api_pool, hai_tenant):
    a, b = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    assert len(await _viec(api_pool, a, "kb_index")) == 1
    assert await _viec(api_pool, b, "kb_index") == []
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -v`
Expected: FAIL — mọi test đọc `kb_index`/`kb_thumb` trả danh sách rỗng
(`AssertionError: []`), vì cổng nạp chưa đặt việc nào. `test_can_khong_dat_viec_nao` và
`test_viec_thuoc_dung_tenant` có thể XANH sẵn (chúng khẳng định sự VẮNG MẶT) — đó là bình
thường, đừng coi là đã xong.

- [ ] **Step 3: Cho `_upsert` trả về `id`**

Trong `src/portal/modules/ingest/chieu.py`, sửa chữ ký và câu cuối của `_upsert`:

```python
async def _upsert(
    conn: asyncpg.Connection,
    *,
    bang: str,
    tenant_id: str,
    external_id: str,
    cot: dict[str, object],
    ve_mac_dinh: tuple[str, ...] = (),
) -> int:
```

và thay `await conn.execute(...)` ở cuối hàm bằng:

```python
    return int(
        await conn.fetchval(
            f"""
            INSERT INTO tenant_data.{bang} ({", ".join(ten_cot)})
            VALUES ({tham_so})
            ON CONFLICT (tenant_id, external_id) DO UPDATE SET {dat}, updated_at = now()
            RETURNING id
            """,  # noqa: S608 — tên bảng từ `_BANG`, tên cột từ `hop_dong.HOP_DONG`/`_COT_CHA_TUY_CHON`
            *day_du.values(),
        )
    )
```

`RETURNING id` thay cho một câu `SELECT id` riêng: hàng mới chưa có id nào để đọc trước
đó, và `hien_trang` là `None` với mọi bản ghi lần đầu tới.

- [ ] **Step 4: Thêm hai hàm đặt việc**

Thêm import ở đầu file (dòng `from portal.modules.kb.contracts import KIND_DELETE_INDEX`
đã có, mở rộng nó — cùng cửa mà `modules/realestate` đang dùng):

```python
from portal.modules.kb.contracts import KIND_DELETE_INDEX, dat_viec_nap, dat_viec_thumb
```

Thêm hai hàm, đặt ngay TRƯỚC `chieu_mot`:

```python
def _qua_viec_thumb(entity: Entity, cot: dict[str, object]) -> bool:
    """Bản ghi còn một chặng trước khi nạp được, nên đi qua việc thumb.

    Ảnh/video cần bản nhỏ; tài liệu chỉ có tệp cần bóc chữ. Việc thumb TỰ nối sang việc
    nạp khi xong — đặt song song thì nạp có thể chạy trước và point mang khoá thumb rỗng.
    """
    if entity == "media":
        return cot.get("content_type") in ("image", "video")
    if entity == "document":
        co_body = bool(str(cot.get("body") or "").strip())
        co_tep = bool(str(cot.get("file_url") or "").strip())
        return not co_body and co_tep
    return False


async def _xep_nap(
    conn: asyncpg.Connection, tenant_id: str, *, entity: Entity, record_id: int, cot: dict[str, object]
) -> None:
    """Bản ghi vừa chiếu ⇒ đặt việc nạp — cùng luật đường giao diện.

    `units` không nhúng (`verticals/real_estate.py`) nên không có gì để đặt. `entity`
    truyền đi là TÊN BẢNG: `modules/kb` dùng `documents`/`media`, không phải số ít.
    """
    if entity == "unit":
        return
    ma_du_an = str(cot.get("project_code") or "")
    if _qua_viec_thumb(entity, cot):
        await dat_viec_thumb(
            conn,
            tenant_id=tenant_id,
            actor="ingest",
            entity=_BANG[entity],
            record_id=record_id,
            project_code=ma_du_an,
            tu_duyet=entity == "document",
        )
        return
    await dat_viec_nap(
        conn,
        tenant_id=tenant_id,
        actor="ingest",
        entity=_BANG[entity],
        record_id=record_id,
        project_code=ma_du_an,
    )
```

- [ ] **Step 5: Nối vào `chieu_mot`**

Ở cuối `chieu_mot`, thay đoạn từ `await _upsert(...)` tới hết hàm bằng:

```python
    record_id = await _upsert(
        conn, bang=bang, tenant_id=tenant_id, external_id=external_id, cot=cot, ve_mac_dinh=ve_mac_dinh
    )
    if entity == "project":
        await _sync_tour_360(conn, tenant_id, external_id=external_id)
    await _xep_nap(conn, tenant_id, entity=entity, record_id=record_id, cot=cot)
    if hien_trang is not None and hien_trang["status"] == "published" and cot.get("status") != "published":
        await _xep_purge(
            conn,
            tenant_id,
            entity=entity,
            record_id=hien_trang["id"],
            project_code=hien_trang["project_code"],
            zone_code=hien_trang["zone_code"] if entity == "zone" else None,
        )
```

Thứ tự tạm thời như trên (nạp rồi purge) chỉ để Task 1 xanh; Task 2 sẽ đảo lại và thêm
điều kiện loại trừ.

- [ ] **Step 6: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -v`
Expected: PASS — 8 test.

- [ ] **Step 7: Chạy lại test cũ của module để chắc không vỡ gì**

Run: `uv run pytest tests/modules/ingest -q`
Expected: PASS toàn bộ. Nếu `test_nap.py` đỏ ở một assert đếm job `kb_delete` thì đọc kỹ:
nó dùng `ORDER BY id DESC LIMIT 1` nên việc nạp mới thêm không chen vào được, và một lỗi
ở đó nghĩa là thứ tự trong Step 5 đặt sai.

- [ ] **Step 8: Lint và commit**

```bash
make lint
git add src/portal/modules/ingest/chieu.py tests/modules/ingest/test_xep_viec_nap.py
git commit -m "feat(ingest): enqueue an index job for every projected record"
```

---

### Task 2: Bốn ca KHÔNG đặt việc

**Files:**
- Modify: `src/portal/modules/ingest/chieu.py` (chỉ đoạn cuối `chieu_mot`)
- Test: `tests/modules/ingest/test_xep_viec_nap.py` (thêm test)

**Interfaces:**
- Consumes: `chieu._xep_nap`, `chieu._xep_purge` (Task 1).
- Produces: không có API mới — chỉ một bất biến: **một lượt chiếu đặt việc nạp HOẶC
  việc xoá point, không bao giờ cả hai.**

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/modules/ingest/test_xep_viec_nap.py`:

```python
async def test_stale_khong_dat_viec(api_pool, hai_tenant):
    """Bản ghi cũ hơn không được chiếu, nên không có việc nào — `chieu_mot` không chạy."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN, luc=LUC)), dry_run=False
    )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN | {"region": "Đà Nẵng"}, luc=LUC - timedelta(hours=1))),
        dry_run=False,
    )
    assert len(await _viec(api_pool, a, "kb_index")) == 1, "lượt stale không được đặt việc thứ hai"


async def test_con_cho_cha_dat_viec_dung_luc_cha_toi(api_pool, hai_tenant):
    """Con tới trước cha nằm chờ, KHÔNG có việc. Cha chiếu xong thì lan truyền đặt việc
    cho cả con — đường `_chieu_con_dang_cho`, đường mà mọi bản ghi tới trước cha đi qua."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("zone", "Z9", {"projectExternalId": "P9", "name": "PK"})), dry_run=False)
    assert await _viec(api_pool, a, "kb_index") == [], "con đang chờ cha không được đặt việc"

    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P9", DU_AN, luc=LUC + timedelta(minutes=1))), dry_run=False
    )
    bang = sorted(v["entity"] for v in await _viec(api_pool, a, "kb_index"))
    assert bang == ["projects", "zones"], bang


async def test_op_delete_khong_dat_viec_nap(api_pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    truoc = len(await _viec(api_pool, a, "kb_index"))
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("document", "D1", {}, op="delete", luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )
    assert len(await _viec(api_pool, a, "kb_index")) == truoc, "op:delete không được đặt việc nạp"
    assert await _viec(api_pool, a, "kb_delete") != [], "op:delete vẫn phải xếp việc xoá point"


async def test_roi_published_chi_xoa_point_khong_nap(api_pool, hai_tenant):
    """Hai việc chống nhau: nạp-rồi-xoá tiêu một lượt embed cho point bị xoá ngay sau đó."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    truoc = [v for v in await _viec(api_pool, a, "kb_index") if v["entity"] == "documents"]
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("document", "D1", TAI_LIEU_CO_CHU | {"status": "archived"}, luc=LUC + timedelta(hours=1)),
        ),
        dry_run=False,
    )
    sau = [v for v in await _viec(api_pool, a, "kb_index") if v["entity"] == "documents"]
    assert len(sau) == len(truoc), "lượt rời published không được đặt thêm việc nạp"
    assert await _viec(api_pool, a, "kb_delete") != [], "rời published phải xếp việc xoá point"
```

Thêm `timedelta` vào dòng import ở đầu file:

```python
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 2: Chạy test để xác nhận ca nào đỏ**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -k "stale or cho_cha or op_delete or roi_published" -v`
Expected: `test_stale_khong_dat_viec`, `test_con_cho_cha_dat_viec_dung_luc_cha_toi`,
`test_op_delete_khong_dat_viec_nap` PASS (ba ca này tự đúng nhờ luồng điều khiển);
`test_roi_published_chi_xoa_point_khong_nap` **FAIL** — `len(sau) == len(truoc) + 1` vì
Task 1 đặt việc nạp trước rồi xếp việc xoá.

- [ ] **Step 3: Thêm điều kiện loại trừ**

Trong `chieu_mot`, thay đoạn cuối (đoạn vừa viết ở Task 1 Step 5) bằng:

```python
    record_id = await _upsert(
        conn, bang=bang, tenant_id=tenant_id, external_id=external_id, cot=cot, ve_mac_dinh=ve_mac_dinh
    )
    if entity == "project":
        await _sync_tour_360(conn, tenant_id, external_id=external_id)

    if hien_trang is not None and hien_trang["status"] == "published" and cot.get("status") != "published":
        # Rời `published` thì CHỈ xoá point, không đặt việc nạp: hai việc chống nhau và
        # thứ tự chạy không xác định — nạp-rồi-xoá tiêu một lượt embed cho point bị xoá
        # ngay sau đó, xoá-rồi-nạp để lại point mà agent lọc bỏ. Cả hai đều trả tiền
        # embed cho thứ không ai đọc.
        await _xep_purge(
            conn,
            tenant_id,
            entity=entity,
            record_id=hien_trang["id"],
            project_code=hien_trang["project_code"],
            zone_code=hien_trang["zone_code"] if entity == "zone" else None,
        )
        return

    await _xep_nap(conn, tenant_id, entity=entity, record_id=record_id, cot=cot)
```

- [ ] **Step 4: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -v`
Expected: PASS — 12 test.

- [ ] **Step 5: Lint và commit**

```bash
make lint
git add src/portal/modules/ingest/chieu.py tests/modules/ingest/test_xep_viec_nap.py
git commit -m "fix(ingest): a record leaving published only purges, never re-indexes"
```

---

### Task 3: `tour_360` hai chiều

**Files:**
- Modify: `src/portal/modules/ingest/chieu.py` (hàm `_sync_tour_360`)
- Test: `tests/modules/ingest/test_xep_viec_nap.py` (thêm test)

**Interfaces:**
- Consumes: `portal.modules.realestate.contracts.sync_tour_360(conn, tenant_id, *, project_code: str, link: str, ten_du_an: str) -> tuple[int | None, int | None]` — trả `(id vừa ghi, id vừa xoá)`.
- Produces: không có API mới.

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/modules/ingest/test_xep_viec_nap.py`:

```python
LINK_360 = "https://kuula.co/share/collection/7MgHS?logo=1&fs=1"


async def test_link360_dat_viec_nap_cho_hang_media_tour(api_pool, hai_tenant):
    """Hàng media tour sinh ra mà không có point ⇒ `send_media` không bao giờ gửi được tour."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": LINK_360})), dry_run=False
    )
    async with tenant_conn(api_pool, a) as conn:
        mid = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant() "
            " AND content_type = 'tour_360'"
        )
    assert mid is not None, "chưa sinh hàng media tour"
    nap = await _viec(api_pool, a, "kb_index")
    assert any(v["entity"] == "media" and v["record_id"] == mid for v in nap), nap
    assert await _viec(api_pool, a, "kb_thumb") == [], "tour là một link, không có ảnh để thu nhỏ"


async def test_bo_link360_xep_viec_xoa_point_cua_hang_tour(api_pool, hai_tenant):
    """Hàng bị DELETE thật. Point cũ sống sót ⇒ agent gửi cho khách một link tour đã chết."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": LINK_360})), dry_run=False
    )
    async with tenant_conn(api_pool, a) as conn:
        mid = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant() "
            " AND content_type = 'tour_360'"
        )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P360", DU_AN | {"link360": ""}, luc=LUC + timedelta(minutes=1))),
        dry_run=False,
    )
    xoa = await _viec(api_pool, a, "kb_delete")
    assert any(v.get("entity") == "media" and v.get("record_id") == mid for v in xoa), xoa
```

Thêm import `tenant_conn` ở đầu file:

```python
from portal.core.db.session import tenant_conn
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -k link360 -v`
Expected: FAIL cả hai — `_sync_tour_360` hiện bỏ qua giá trị trả về nên không việc nào
được đặt cho hàng tour.

- [ ] **Step 3: Dùng giá trị trả về của `sync_tour_360`**

Thay thân `_sync_tour_360` trong `src/portal/modules/ingest/chieu.py` bằng:

```python
async def _sync_tour_360(conn: asyncpg.Connection, tenant_id: str, *, external_id: str) -> None:
    """`link_360` → một hàng `media` tour_360, đọc TỪ hàng vừa ghi chứ không từ payload.

    Đọc lại từ DB vì payload có thể là upsert một phần: thiếu `link_360` trong lô này không
    có nghĩa là khách muốn xoá tour.

    Dùng CẢ HAI giá trị trả về, như `realestate/router.py::_sync_tour_360`. Bỏ chúng đi là
    hàng tour không có point (`send_media` không gửi được) và point của tour đã rút thì sống
    sót (agent gửi một link đã chết) — chiều thứ hai tệ hơn vì nó là thông tin SAI.
    """
    from portal.modules.realestate.contracts import sync_tour_360

    row = await conn.fetchrow(
        "SELECT project_code, name, coalesce(link_360, '') AS link FROM tenant_data.projects "
        " WHERE tenant_id = portal.current_tenant() AND external_id = $1",
        external_id,
    )
    if row is None:
        return
    ma_du_an = str(row["project_code"])
    moi, da_xoa = await sync_tour_360(
        conn,
        tenant_id,
        project_code=ma_du_an,
        link=str(row["link"]),
        ten_du_an=str(row["name"] or ""),
    )
    if moi is not None:
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="ingest",
            entity="media",
            record_id=moi,
            project_code=ma_du_an,
        )
    if da_xoa is not None:
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_DELETE_INDEX,
            actor="ingest",
            payload={"vertical": "real_estate", "entity": "media", "record_id": da_xoa},
        )
```

`enqueue` đã được import ở đầu file (`from portal.core.jobs import enqueue`).

- [ ] **Step 4: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/modules/ingest/test_xep_viec_nap.py -v`
Expected: PASS — 14 test.

- [ ] **Step 5: Chạy toàn bộ test module lần cuối**

Run: `uv run pytest tests/modules/ingest -q`
Expected: PASS. Hai test cũ `test_link360_qua_cong_nap_sinh_hang_media_tour` và
`test_bo_link360_qua_cong_nap_thi_xoa_hang_tour` vẫn xanh — chúng kiểm hàng trong
Postgres, phần này chỉ thêm việc vào hàng đợi.

- [ ] **Step 6: Lint và commit**

```bash
make lint
git add src/portal/modules/ingest/chieu.py tests/modules/ingest/test_xep_viec_nap.py
git commit -m "fix(ingest): enqueue index and purge jobs for the tour_360 media row"
```

---

### Task 4: Dữ liệu và tệp của CRM giả

**Files:**
- Create: `scripts/crm_gia/__init__.py`
- Create: `scripts/crm_gia/du_lieu.py`
- Create: `scripts/crm_gia/tep.py`
- Test: `tests/unit/test_crm_gia.py`

**Interfaces:**
- Produces:
  - `du_lieu.DU_AN: list[dict]` · `du_lieu.PHAN_KHU: list[dict]` · `du_lieu.CAN: list[dict]` · `du_lieu.TAI_LIEU: list[dict]` · `du_lieu.ANH: list[dict]` — bản ghi theo hình dạng CRM giả (khoá tiếng Việt).
  - `du_lieu.MOC: str` — mốc `capNhatLuc` mặc định, ISO 8601 có offset.
  - `tep.sinh(ten: str) -> tuple[bytes, str]` — trả `(nội dung, content-type)` cho một tên tệp trong `tep.TEN_TEP`.
  - `tep.TEN_TEP: tuple[str, ...]`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_crm_gia.py`:

```python
"""CRM giả — bộ dữ liệu và tệp sinh tại chỗ.

Test đơn vị: không cần Docker, không cần backend. Cái đáng canh ở đây là bộ dữ liệu
KHÔNG trả đúng schema của Portal — nếu nó trả đúng thì adapter chỉ là copy và e2e mất
tác dụng kiểm tính khả dụng của hợp đồng.
"""

from scripts.crm_gia import du_lieu, tep


def test_khoi_luong_du_de_cham_moi_luat():
    assert len(du_lieu.DU_AN) == 3
    assert len(du_lieu.PHAN_KHU) == 7
    assert len(du_lieu.CAN) >= 120
    assert len(du_lieu.TAI_LIEU) == 12
    assert len(du_lieu.ANH) == 20


def test_mot_du_an_khong_co_phan_khu_nao():
    """Chạm luật `zoneExternalId` tuỳ chọn — `units.zone_code` nullable từ `0902`."""
    co_phan_khu = {p["duAn"] for p in du_lieu.PHAN_KHU}
    thieu = [d["ma"] for d in du_lieu.DU_AN if d["ma"] not in co_phan_khu]
    assert len(thieu) == 1, thieu


def test_khoa_khong_trung_ten_hop_dong_cua_portal():
    """Không được xuất hiện tên trường của hợp đồng cổng nạp."""
    cam = {"externalId", "salePhase", "priceVnd", "productType", "contentType", "mediaUrl", "fileUrl"}
    for hang in du_lieu.DU_AN + du_lieu.PHAN_KHU + du_lieu.CAN + du_lieu.TAI_LIEU + du_lieu.ANH:
        assert not (cam & set(hang)), hang


def test_gia_va_dien_tich_khong_o_don_vi_cua_portal():
    """Giá theo TRIỆU đồng, diện tích là CHUỖI — adapter phải thật sự quy đổi."""
    can = du_lieu.CAN[0]
    assert "giaBanTrieuDong" in can and isinstance(can["giaBanTrieuDong"], int)
    assert isinstance(du_lieu.DU_AN[0]["dienTichDatM2"], str)


def test_co_can_chua_co_gia():
    assert any(c.get("giaBanTrieuDong") in (None, 0) for c in du_lieu.CAN)


def test_du_bay_danh_muc_anh_va_co_video():
    assert len({a["nhomAnh"] for a in du_lieu.ANH}) == 7
    assert any(a["loaiNoiDung"] == "Video" for a in du_lieu.ANH)


def test_mot_du_an_co_link_tour():
    assert sum(1 for d in du_lieu.DU_AN if d.get("linkTour")) == 1


def test_tai_lieu_co_ca_hai_dang():
    co_noi_dung = [t for t in du_lieu.TAI_LIEU if t.get("noiDung")]
    chi_tep = [t for t in du_lieu.TAI_LIEU if not t.get("noiDung") and t.get("tenTep")]
    assert co_noi_dung and chi_tep


def test_tai_lieu_dung_du_bon_dinh_dang_tep():
    """Bốn nhánh của `kb/clients/extract.py` đều phải có bản ghi chạm tới."""
    dung = {t["tenTep"] for t in du_lieu.TAI_LIEU if t["tenTep"]}
    assert dung == {"bang_gia.docx", "quy_hoach.xlsx", "bang_gia_co_chu.pdf", "csbh_scan.pdf"}


def test_sinh_duoc_moi_tep_va_dung_dinh_dang():
    for ten in tep.TEN_TEP:
        data, kieu = tep.sinh(ten)
        assert data, ten
        assert kieu
    assert tep.sinh("bang_gia.docx")[0][:2] == b"PK", "docx là zip"
    assert tep.sinh("quy_hoach.xlsx")[0][:2] == b"PK", "xlsx là zip"
    assert tep.sinh("phoi_canh.png")[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert tep.sinh("csbh_scan.pdf")[0][:5] == b"%PDF-"
    assert tep.sinh("bang_gia_co_chu.pdf")[0][:5] == b"%PDF-"


def test_pdf_co_lop_chu_boc_duoc_bang_pypdf():
    """Bài canh cấu trúc PDF dựng tay. Offset `xref` lệch một byte thì `extract_text()`
    trả rỗng và tệp ÂM THẦM rơi sang nhánh OCR — không lỗi ở đâu cả, chỉ là nhánh
    «thư viện bóc ⇒ tự động» không bao giờ được kiểm."""
    import io

    from pypdf import PdfReader

    data, _ = tep.sinh("bang_gia_co_chu.pdf")
    chu = PdfReader(io.BytesIO(data)).pages[0].extract_text()
    assert "CHINH SACH BAN HANG" in chu, chu
    assert "Chiet khau" in chu, chu


def test_pdf_scan_khong_co_lop_chu():
    """Không có lớp chữ là ĐIỀU KIỆN để đi nhánh OCR: `pypdf` bóc ra chữ thì
    `TextExtractor` dừng ở đó và VLM không bao giờ được gọi."""
    import io

    from pypdf import PdfReader

    data, _ = tep.sinh("csbh_scan.pdf")
    assert not (PdfReader(io.BytesIO(data)).pages[0].extract_text() or "").strip()


def test_sinh_tep_la_xac_dinh():
    """Hai lượt gọi ra cùng byte — e2e chạy lại không đổi dấu tay nội dung."""
    assert tep.sinh("bang_gia.docx")[0] == tep.sinh("bang_gia.docx")[0]
    assert tep.sinh("bang_gia_co_chu.pdf")[0] == tep.sinh("bang_gia_co_chu.pdf")[0]
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_crm_gia.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.crm_gia'`

- [ ] **Step 3: Tạo bộ dữ liệu**

Tạo `scripts/crm_gia/__init__.py` (rỗng) và `scripts/crm_gia/du_lieu.py`:

```python
"""Bộ dữ liệu của CRM giả — CỐ ĐỊNH, không ngẫu nhiên.

TÊN TRƯỜNG VÀ ĐƠN VỊ CỐ Ý KHÁC hợp đồng cổng nạp: giá theo triệu đồng, diện tích là
chuỗi có dấu phân cách, giai đoạn bán viết tiếng Việt có dấu, mã bản ghi dạng `PRJ-0001`.
Trả đúng schema của Portal thì adapter chỉ là copy, và e2e mất đúng thứ nó tồn tại để
kiểm: hợp đồng này có viết adapter được hay không.

Cố định chứ không sinh ngẫu nhiên: một lượt e2e đỏ phải dựng lại được.
"""

MOC = "2026-08-17T09:00:00+07:00"

DU_AN: list[dict] = [
    {
        "ma": "PRJ-0001",
        "tenDuAn": "Khu đô thị Ánh Dương",
        "khuVuc": "Hà Nội",
        "diaChi": "Đường Lê Văn Lương, Nam Từ Liêm, Hà Nội",
        "chuDauTu": "Công ty CP Đầu tư Ánh Dương",
        "donViPhatTrien": "Ánh Dương Land",
        "giaiDoanBan": "Đang bán",
        "loaiHinh": ["Chung cư", "Shophouse"],
        "dienTichDatM2": "125.000 m²",
        "dienTichSanM2": "480.000 m²",
        "matDoXayDungPhanTram": 38.5,
        "quyMoSanPham": "3 toà tháp, 1.240 căn hộ",
        "hinhThucSoHuu": "Sổ hồng lâu dài",
        "tieuChuanBanGiao": "Hoàn thiện cơ bản",
        "tongMucDauTuTyDong": 12000,
        "gioiThieu": "## Tổng quan\n\nKhu đô thị Ánh Dương nằm ở trục Lê Văn Lương.",
        "tienIch": "## Tiện ích\n\nBể bơi bốn mùa, trường liên cấp, trung tâm thương mại.",
        "linkTour": "https://kuula.co/share/collection/7MgHS?logo=1&fs=1",
        "capNhatLuc": MOC,
    },
    {
        "ma": "PRJ-0002",
        "tenDuAn": "Vườn Xanh Riverside",
        "khuVuc": "Đà Nẵng",
        "diaChi": "Đường Võ Nguyên Giáp, Ngũ Hành Sơn, Đà Nẵng",
        "chuDauTu": "Tổng công ty Vườn Xanh",
        "donViPhatTrien": "Vườn Xanh Homes",
        "giaiDoanBan": "Sắp mở bán",
        "loaiHinh": ["Biệt thự", "Liền kề"],
        "dienTichDatM2": "86.400 m²",
        "dienTichSanM2": "150.000 m²",
        "matDoXayDungPhanTram": 31.0,
        "quyMoSanPham": "212 căn thấp tầng",
        "hinhThucSoHuu": "Sổ hồng lâu dài",
        "tieuChuanBanGiao": "Hoàn thiện mặt ngoài",
        "tongMucDauTuTyDong": 7400,
        "gioiThieu": "## Tổng quan\n\nVườn Xanh Riverside bám mặt sông Cổ Cò.",
        "tienIch": "## Tiện ích\n\nCông viên ven sông, bến du thuyền, sân tennis.",
        "linkTour": "",
        "capNhatLuc": MOC,
    },
    {
        "ma": "PRJ-0003",
        "tenDuAn": "Sunrise Central Tower",
        "khuVuc": "TP Hồ Chí Minh",
        "diaChi": "Đường Nguyễn Hữu Thọ, Quận 7, TP Hồ Chí Minh",
        "chuDauTu": "Sunrise Group",
        "donViPhatTrien": "Sunrise Services",
        "giaiDoanBan": "Bàn giao",
        "loaiHinh": ["Chung cư", "Văn phòng"],
        "dienTichDatM2": "9.800 m²",
        "dienTichSanM2": "112.000 m²",
        "matDoXayDungPhanTram": 44.0,
        "quyMoSanPham": "2 toà, 860 căn hộ và 12 tầng văn phòng",
        "hinhThucSoHuu": "Sổ hồng 50 năm",
        "tieuChuanBanGiao": "Full nội thất",
        "tongMucDauTuTyDong": 9100,
        "gioiThieu": "## Tổng quan\n\nSunrise Central Tower nằm trên trục Nguyễn Hữu Thọ.",
        "tienIch": "## Tiện ích\n\nSky bar, phòng gym, khu vui chơi trẻ em.",
        "linkTour": "",
        "capNhatLuc": MOC,
    },
]

# PRJ-0003 CỐ Ý không có phân khu nào — chạm luật `zoneExternalId` tuỳ chọn.
_PHAN_KHU_THO: list[tuple[str, str, str, str]] = [
    ("PRJ-0001", "ZON-0001", "Toà A1", "Chung cư"),
    ("PRJ-0001", "ZON-0002", "Toà A2", "Chung cư"),
    ("PRJ-0001", "ZON-0003", "Phố thương mại", "Shophouse"),
    ("PRJ-0002", "ZON-0004", "Đảo Ngọc", "Biệt thự"),
    ("PRJ-0002", "ZON-0005", "Hoa Anh Đào", "Liền kề"),
    ("PRJ-0002", "ZON-0006", "Bến Thuyền", "Biệt thự"),
    ("PRJ-0002", "ZON-0007", "Vườn Mai", "Liền kề"),
]

PHAN_KHU: list[dict] = [
    {
        "ma": ma,
        "duAn": du_an,
        "tenPhanKhu": ten,
        "loaiHinh": loai,
        "quyMoSanPham": f"{40 + i * 7} sản phẩm",
        "gioiThieu": f"## {ten}\n\nPhân khu {ten} thuộc {du_an}, mật độ thấp, hướng vào công viên nội khu.",
        "capNhatLuc": MOC,
    }
    for i, (du_an, ma, ten, loai) in enumerate(_PHAN_KHU_THO)
]

_HUONG = ["Đông", "Tây", "Nam", "Bắc", "Đông Bắc", "Đông Nam", "Tây Bắc", "Tây Nam"]
_TINH_TRANG = ["Còn hàng", "Đã cọc", "Đã bán"]
_LOAI_CAN = ["Chung cư", "Studio", "Duplex", "Penthouse", "Biệt thự", "Liền kề", "Shophouse"]


def _can() -> list[dict]:
    """126 căn: 60 cho PRJ-0001, 42 cho PRJ-0002, 24 cho PRJ-0003 (không phân khu).

    Ba căn đầu của PRJ-0003 CỐ Ý chưa có giá — chạm luật «căn chưa có giá không được
    chiếm top khuyến nghị» mà repo agent đã phải sửa một lần.
    """
    ra: list[dict] = []
    bo = [("PRJ-0001", ["ZON-0001", "ZON-0002", "ZON-0003"], 60), ("PRJ-0002", ["ZON-0004", "ZON-0005", "ZON-0006", "ZON-0007"], 42), ("PRJ-0003", [], 24)]
    n = 0
    for du_an, phan_khu, so_luong in bo:
        for i in range(so_luong):
            n += 1
            chua_co_gia = du_an == "PRJ-0003" and i < 3
            ra.append(
                {
                    "ma": f"UNT-{n:04d}",
                    "duAn": du_an,
                    "phanKhu": phan_khu[i % len(phan_khu)] if phan_khu else "",
                    "maCan": f"{chr(65 + i % 4)}-{10 + i % 25:02d}{i % 9 + 1:02d}",
                    "tinhTrang": _TINH_TRANG[i % 3],
                    "loaiCan": _LOAI_CAN[i % len(_LOAI_CAN)],
                    "giaBanTrieuDong": 0 if chua_co_gia else 2400 + i * 35,
                    "giaMoiM2TrieuDong": 0 if chua_co_gia else 48 + i % 20,
                    "huongNha": _HUONG[i % len(_HUONG)],
                    "soPhongNgu": 1 + i % 4,
                    "toaBlock": f"Block {chr(65 + i % 3)}",
                    "tang": 2 + i % 28,
                    "soTang": 1 if i % 5 else 3,
                    "dienTichThongThuyM2": f"{58 + i % 40},5 m²",
                    "dienTichTimTuongM2": f"{62 + i % 40},0 m²",
                    "capNhatLuc": MOC,
                }
            )
    return ra


CAN: list[dict] = _can()

# Bốn định dạng tệp CỐ Ý đều có mặt, mỗi cái chạm một nhánh của `kb/clients/extract.py`:
# `csbh_scan.pdf` (OCR qua VLM) · `bang_gia_co_chu.pdf` (pypdf) · `quy_hoach.xlsx`
# (openpyxl) · `bang_gia.docx` (python-docx). Thiếu một nhánh là nhánh đó không bao giờ
# được kiểm, và ba nhánh còn lại vẫn xanh nên không ai biết.
_TAI_LIEU_THO: list[tuple[str, str, str, str, str]] = [
    ("PRJ-0001", "Chính sách bán hàng tháng 8", "csbh", "", "csbh_scan.pdf"),
    ("PRJ-0001", "Bảng giá căn hộ toà A1", "khac", "## Bảng giá\n\nGiá từ 48 triệu/m², chiết khấu 3% khi thanh toán nhanh.", ""),
    ("PRJ-0001", "Hướng dẫn thủ tục vay", "huong_dan", "## Vay vốn\n\nHỗ trợ vay tới 70% giá trị căn, lãi suất 0% 18 tháng.", ""),
    ("PRJ-0001", "Tiến độ thi công quý 3", "khac", "", "quy_hoach.xlsx"),
    ("PRJ-0002", "Chính sách bán hàng Vườn Xanh", "csbh", "", "bang_gia_co_chu.pdf"),
    ("PRJ-0002", "Quy hoạch phân khu", "khac", "", "quy_hoach.xlsx"),
    ("PRJ-0002", "Giới thiệu tiện ích ven sông", "khac", "## Tiện ích\n\nBến du thuyền 40 chỗ, đường chạy bộ 2,4 km.", ""),
    ("PRJ-0002", "Hướng dẫn nhận nhà", "huong_dan", "## Nhận nhà\n\nMang theo CCCD và hợp đồng mua bán bản gốc.", ""),
    ("PRJ-0003", "Chính sách bán hàng Sunrise", "csbh", "", "bang_gia.docx"),
    ("PRJ-0003", "Bảng giá văn phòng", "khac", "## Văn phòng\n\nGiá thuê từ 480 nghìn/m²/tháng.", ""),
    ("PRJ-0003", "Nội quy toà nhà", "khac", "## Nội quy\n\nGiờ chuyển đồ từ 8h tới 17h các ngày trong tuần.", ""),
    ("PRJ-0003", "Sổ tay cư dân", "huong_dan", "", "bang_gia_co_chu.pdf"),
]

TAI_LIEU: list[dict] = [
    {
        "ma": f"DOC-{i + 1:04d}",
        "duAn": du_an,
        "tieuDe": tieu_de,
        "phanLoai": loai,
        "noiDung": noi_dung,
        "tenTep": ten_tep,
        "capNhatLuc": MOC,
    }
    for i, (du_an, tieu_de, loai, noi_dung, ten_tep) in enumerate(_TAI_LIEU_THO)
]

_NHOM_ANH = ["Tổng quan", "Ngoại thất", "Nội thất", "Tiện ích", "Mặt bằng", "Vị trí", "Tiến độ"]


def _anh() -> list[dict]:
    """20 mục: đủ 7 nhóm cho mỗi vòng, hai mục cuối là video."""
    ra: list[dict] = []
    for i in range(20):
        du_an = DU_AN[i % 3]["ma"]
        la_video = i >= 18
        ra.append(
            {
                "ma": f"IMG-{i + 1:04d}",
                "duAn": du_an,
                "phanKhu": "",
                "can": "",
                "loaiNoiDung": "Video" if la_video else "Ảnh",
                "nhomAnh": _NHOM_ANH[i % 7],
                "duongDan": f"https://cdn.crm-gia.test/{'video' if la_video else 'anh'}/{i + 1:04d}.{'mp4' if la_video else 'png'}",
                "tenTep": "" if la_video else "phoi_canh.png",
                "moTa": f"{_NHOM_ANH[i % 7]} dự án {du_an}",
                "capNhatLuc": MOC,
            }
        )
    return ra


ANH: list[dict] = _anh()
```

- [ ] **Step 4: Tạo bộ sinh tệp**

Tạo `scripts/crm_gia/tep.py`:

```python
"""Tệp do CRM giả phục vụ — sinh tại chỗ, XÁC ĐỊNH, không đọc đĩa.

NĂM TỆP phủ TRỌN bốn nhánh của `kb/clients/extract.py`:
  · `bang_gia_co_chu.pdf` → PDF CÓ lớp chữ, `pypdf` bóc ⇒ nạp thẳng, không qua van duyệt.
  · `csbh_scan.pdf` → ảnh xuất thành PDF nên KHÔNG có lớp chữ ⇒ nhánh OCR qua VLM.
  · `bang_gia.docx` → `python-docx`.
  · `quy_hoach.xlsx` → `openpyxl`.
  · `phoi_canh.png` → ảnh cho media (nhánh thumb, không phải bóc chữ).

Nhánh OCR cần `KB_VLM_API_KEY` — xem phần điều kiện của `scripts/e2e_nap_toi_qdrant.py`.

Xác định (không dấu thời gian, không ngẫu nhiên) để dấu tay nội dung của một lượt e2e
không đổi giữa hai lần chạy — nếu đổi thì bài kiểm «chạy lại không nhúng lại» sai.
"""

import io

TEN_TEP: tuple[str, ...] = (
    "bang_gia.docx",
    "quy_hoach.xlsx",
    "phoi_canh.png",
    "csbh_scan.pdf",
    "bang_gia_co_chu.pdf",
)

_KIEU = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "png": "image/png",
    "pdf": "application/pdf",
}


def _docx() -> bytes:
    import docx

    tep = docx.Document()
    tep.add_heading("Chính sách bán hàng", level=1)
    tep.add_paragraph("Chiết khấu 3% khi thanh toán trước 70% giá trị căn hộ.")
    tep.add_heading("Điều kiện áp dụng", level=2)
    tep.add_paragraph("Áp dụng cho hợp đồng ký trong tháng 8, không cộng dồn ưu đãi khác.")
    ra = io.BytesIO()
    tep.save(ra)
    return ra.getvalue()


def _xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Tiến độ"
    ws.append(["Hạng mục", "Kế hoạch", "Thực hiện"])
    ws.append(["Móng toà A1", "Q1/2026", "Đã xong"])
    ws.append(["Thân toà A1", "Q3/2026", "Đang thi công"])
    ra = io.BytesIO()
    wb.save(ra)
    return ra.getvalue()


def _anh_png() -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (640, 400), (222, 232, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 600, 360], outline=(60, 90, 120), width=4)
    d.text((60, 60), "PHOI CANH DU AN", fill=(20, 40, 70))
    ra = io.BytesIO()
    im.save(ra, format="PNG")
    return ra.getvalue()


def _pdf_scan() -> bytes:
    """Ảnh xuất thành PDF ⇒ KHÔNG có lớp chữ ⇒ `pypdf` trả rỗng ⇒ đi nhánh OCR."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (827, 1169), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((80, 120), "CHINH SACH BAN HANG", fill=(0, 0, 0))
    d.text((80, 180), "Chiet khau 3% khi thanh toan nhanh", fill=(0, 0, 0))
    ra = io.BytesIO()
    im.save(ra, format="PDF")
    return ra.getvalue()


def _pdf_co_lop_chu() -> bytes:
    """PDF CÓ lớp chữ thật — `pypdf` bóc được nên đi nhánh «thư viện bóc ⇒ tự động».

    Dựng tay vì repo không có thư viện TẠO chữ trong PDF: `pypdf` chỉ đọc, `pypdfium2` chỉ
    render, và Docling đã bị bỏ (kéo theo 1,35 GB phụ thuộc). Đổi lại phải tự tính bảng
    `xref` bằng offset THẬT của từng object — viết cứng con số là PDF hỏng, và nó hỏng IM
    LẶNG: `extract_text()` trả rỗng rồi tệp rơi sang nhánh OCR mà không lỗi ở đâu cả.
    `test_pdf_co_lop_chu_boc_duoc_bang_pypdf` là thứ canh đúng điều đó.

    Chữ KHÔNG DẤU: font Helvetica chuẩn của PDF dùng bảng mã một byte, nên tiếng Việt có
    dấu đòi nhúng font TrueType — một việc lớn hơn nhiều thứ nó mua được ở đây.
    """
    noi_dung = (
        b"BT /F1 14 Tf 72 780 Td (CHINH SACH BAN HANG) Tj ET\n"
        b"BT /F1 11 Tf 72 750 Td (Chiet khau 3% khi thanh toan truoc 70% gia tri can.) Tj ET\n"
        b"BT /F1 11 Tf 72 730 Td (Ap dung cho hop dong ky trong thang 8, khong cong don.) Tj ET\n"
    )
    than_obj = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
        b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(noi_dung)).encode() + b" >>\nstream\n" + noi_dung + b"endstream",
    ]
    ra = bytearray(b"%PDF-1.4\n")
    moc: list[int] = []
    for i, than in enumerate(than_obj, start=1):
        moc.append(len(ra))
        ra += str(i).encode() + b" 0 obj\n" + than + b"\nendobj\n"
    dau_xref = len(ra)
    ra += b"xref\n0 " + str(len(than_obj) + 1).encode() + b"\n0000000000 65535 f \n"
    for o in moc:
        ra += f"{o:010d} 00000 n \n".encode()
    ra += b"trailer\n<< /Size " + str(len(than_obj) + 1).encode() + b" /Root 1 0 R >>\n"
    ra += b"startxref\n" + str(dau_xref).encode() + b"\n%%EOF\n"
    return bytes(ra)


_SINH = {
    "bang_gia.docx": _docx,
    "quy_hoach.xlsx": _xlsx,
    "phoi_canh.png": _anh_png,
    "csbh_scan.pdf": _pdf_scan,
    "bang_gia_co_chu.pdf": _pdf_co_lop_chu,
}


def sinh(ten: str) -> tuple[bytes, str]:
    """`(nội dung, content-type)`. Tên ngoài `TEN_TEP` ⇒ `KeyError` — không đoán mò."""
    return _SINH[ten](), _KIEU[ten.rsplit(".", 1)[-1]]
```

- [ ] **Step 5: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/unit/test_crm_gia.py -v`
Expected: PASS — 13 test. Hai bài quan trọng nhất là
`test_pdf_co_lop_chu_boc_duoc_bang_pypdf` (PDF dựng tay đúng cấu trúc) và
`test_pdf_scan_khong_co_lop_chu` (điều kiện để nhánh OCR chạy).

- [ ] **Step 6: Lint và commit**

```bash
make lint
git add scripts/crm_gia tests/unit/test_crm_gia.py
git commit -m "test(crm-gia): fixed dataset and generated files for a fake customer CRM"
```

---

### Task 5: Server CRM giả

**Files:**
- Create: `scripts/crm_gia/__main__.py`
- Modify: `Makefile`
- Test: `tests/unit/test_crm_gia_server.py`

**Interfaces:**
- Consumes: `du_lieu` và `tep` (Task 4).
- Produces:
  - `scripts.crm_gia.__main__.app` — ứng dụng FastAPI.
  - `scripts.crm_gia.__main__.an(loai: str, ma: str) -> None` và `reset() -> None` — điều khiển ẩn bản ghi.
  - HTTP: `GET /api/duan|phankhu|can|tailieu|anh` (`?trang=`, `?tu=`, `?duAn=`) → `{"tong": int, "trang": int, "duLieu": [...]}` · `GET /tep/{ten}` · `POST /gia-lap/an/{loai}/{ma}` · `POST /gia-lap/reset`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_crm_gia_server.py`:

```python
"""Server CRM giả — phân trang, `?tu=`, ẩn bản ghi, phục vụ tệp.

Dùng `TestClient` nên không cần chạy uvicorn và không cần Docker.
"""

import pytest
from fastapi.testclient import TestClient

from scripts.crm_gia.__main__ import app, reset


@pytest.fixture
def client():
    reset()
    with TestClient(app) as c:
        yield c
    reset()


def test_danh_sach_du_an_co_bao_bi_phan_trang(client):
    r = client.get("/api/duan")
    assert r.status_code == 200
    than = r.json()
    assert than["tong"] == 3
    assert than["trang"] == 1
    assert len(than["duLieu"]) == 3


def test_can_phan_trang_theo_trang(client):
    t1 = client.get("/api/can", params={"trang": 1}).json()
    t2 = client.get("/api/can", params={"trang": 2}).json()
    assert len(t1["duLieu"]) == 50
    assert t1["tong"] == t2["tong"] >= 120
    assert {c["ma"] for c in t1["duLieu"]} & {c["ma"] for c in t2["duLieu"]} == set()


def test_loc_theo_du_an(client):
    ra = client.get("/api/phankhu", params={"duAn": "PRJ-0002"}).json()
    assert ra["duLieu"], ra
    assert all(p["duAn"] == "PRJ-0002" for p in ra["duLieu"])


def test_tu_moc_moi_hon_moi_thu_tra_rong(client):
    ra = client.get("/api/duan", params={"tu": "2099-01-01T00:00:00+07:00"}).json()
    assert ra["duLieu"] == []


def test_an_ban_ghi_thi_no_roi_danh_sach(client):
    assert client.post("/gia-lap/an/duan/PRJ-0002").status_code == 204
    ma = [d["ma"] for d in client.get("/api/duan").json()["duLieu"]]
    assert "PRJ-0002" not in ma
    assert client.post("/gia-lap/reset").status_code == 204
    assert "PRJ-0002" in [d["ma"] for d in client.get("/api/duan").json()["duLieu"]]


def test_phuc_vu_tep(client):
    r = client.get("/tep/phoi_canh.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/tep/khong-ton-tai.png").status_code == 404
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_crm_gia_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.crm_gia.__main__'`

- [ ] **Step 3: Viết server**

Tạo `scripts/crm_gia/__main__.py`:

```python
"""CRM giả — đóng vai hệ thống của khách hàng. KHÔNG phải hợp đồng của Portal.

    uv run python -m scripts.crm_gia            # cổng 8123
    uv run python -m scripts.crm_gia --port 9123

Cổng 8123 vì mọi cổng khác trên máy dev đã có chủ: 5442 (pg) · 6382 (redis) ·
6343 (qdrant) · 9002 (minio) · 8100 (api) · 5273 (fe) · 8016 (embed).

Bốn thứ nó có, mỗi thứ ép adapter xử lý một tình huống thật: phân trang · `?tu=` để lấy
thay đổi · bản ghi BIẾN MẤT khỏi danh sách (phát hiện xoá bằng bản kê, không bằng event) ·
endpoint phục vụ tệp cho nhánh bóc chữ.

Ẩn bản ghi qua endpoint TƯỜNG MINH, không ngẫu nhiên: một lượt e2e đỏ phải dựng lại được.
"""

import argparse

from fastapi import FastAPI, HTTPException, Query, Response

from scripts.crm_gia import du_lieu, tep

TRANG_KICH_CO = 50

_BANG = {
    "duan": ("ma", du_lieu.DU_AN),
    "phankhu": ("duAn", du_lieu.PHAN_KHU),
    "can": ("duAn", du_lieu.CAN),
    "tailieu": ("duAn", du_lieu.TAI_LIEU),
    "anh": ("duAn", du_lieu.ANH),
}

_DA_AN: dict[str, set[str]] = {loai: set() for loai in _BANG}

app = FastAPI(title="CRM giả", docs_url="/docs")


def an(loai: str, ma: str) -> None:
    _DA_AN[loai].add(ma)


def reset() -> None:
    for s in _DA_AN.values():
        s.clear()


def _tra(loai: str, *, du_an: str | None, trang: int, tu: str | None) -> dict:
    khoa_du_an, hang = _BANG[loai]
    ra = [h for h in hang if h["ma"] not in _DA_AN[loai]]
    if du_an and khoa_du_an == "duAn":
        ra = [h for h in ra if h["duAn"] == du_an]
    if tu:
        # So chuỗi ISO cùng offset — đủ cho dữ liệu cố định, và không kéo một thư viện
        # phân tích ngày vào một script.
        ra = [h for h in ra if h["capNhatLuc"] > tu]
    dau = (trang - 1) * TRANG_KICH_CO
    return {"tong": len(ra), "trang": trang, "duLieu": ra[dau : dau + TRANG_KICH_CO]}


@app.get("/api/{loai}")
def danh_sach(
    loai: str,
    duAn: str | None = Query(default=None),  # noqa: N803 — tên tham số của CRM giả
    trang: int = Query(default=1, ge=1),
    tu: str | None = Query(default=None),
) -> dict:
    if loai not in _BANG:
        raise HTTPException(status_code=404, detail=f"không có loại {loai!r}")
    return _tra(loai, du_an=duAn, trang=trang, tu=tu)


@app.get("/tep/{ten}")
def doc_tep(ten: str) -> Response:
    try:
        data, kieu = tep.sinh(ten)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"không có tệp {ten!r}") from None
    return Response(content=data, media_type=kieu)


@app.post("/gia-lap/an/{loai}/{ma}", status_code=204)
def gia_lap_an(loai: str, ma: str) -> None:
    if loai not in _BANG:
        raise HTTPException(status_code=404, detail=f"không có loại {loai!r}")
    an(loai, ma)


@app.post("/gia-lap/reset", status_code=204)
def gia_lap_reset() -> None:
    reset()


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="CRM giả cho e2e cổng nạp")
    p.add_argument("--port", type=int, default=8123)
    p.add_argument("--host", default="127.0.0.1")
    a = p.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/unit/test_crm_gia_server.py -v`
Expected: PASS — 6 test.

- [ ] **Step 5: Thêm target Makefile**

Thêm vào `Makefile`, ngay sau target `agent-gia`:

```makefile
crm-gia:        ## chạy CRM giả cho e2e cổng nạp (cổng 8123)
	uv run python -m scripts.crm_gia
```

- [ ] **Step 6: Chạy thử server và xác nhận bằng mắt**

```bash
make crm-gia &
sleep 2
curl -s 'http://127.0.0.1:8123/api/duan' | head -c 200
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' 'http://127.0.0.1:8123/tep/bang_gia.docx'
kill %1
```

Expected: JSON có `"tong":3`, và dòng thứ hai in
`200 application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

- [ ] **Step 7: Lint và commit**

```bash
make lint
git add scripts/crm_gia/__main__.py tests/unit/test_crm_gia_server.py Makefile
git commit -m "test(crm-gia): serve the fake CRM over HTTP with paging and hide controls"
```

---

### Task 6: Hàm dịch của adapter

**Files:**
- Create: `scripts/adapter_crm_gia.py`
- Test: `tests/unit/test_adapter_crm_gia.py`

**Interfaces:**
- Produces (hàm THUẦN, không I/O):
  - `so_tu_chuoi(v: object) -> float | None` — `"125.000 m²"` → `125000.0`, `"58,5 m²"` → `58.5`
  - `trieu_sang_vnd(v: object) -> int | None` · `ty_sang_vnd(v: object) -> int | None`
  - `dich_du_an(h: dict) -> dict` · `dich_phan_khu(h: dict) -> dict` · `dich_can(h: dict) -> dict` · `dich_tai_lieu(h: dict, *, goc_tep: str) -> dict` · `dich_anh(h: dict, *, goc_tep: str) -> dict` — trả phần `data` của `BanGhiIn`
  - `chia_lo(items: list, tran: int = 500) -> list[list]`
  - `trang_ban_ke(ma: list[str], tran: int) -> list[tuple[str | None, list[str], bool]]` — `(afterExternalId, mã của trang, isLastPage)`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_adapter_crm_gia.py`:

```python
"""Adapter CRM giả — phần DỊCH và phần CHIA TRANG, cả hai là hàm thuần.

Đây là chỗ đáng test nhất của adapter: quy đổi đơn vị sai thì lệch 1000 lần mà không lỗi,
và chia trang bản kê sai thì bản ghi rơi vào trang không chứa nó rồi bị gắn cờ SAI.
"""

from scripts import adapter_crm_gia as ad
from scripts.crm_gia import du_lieu

GOC_TEP = "http://127.0.0.1:8123/tep"


def test_so_tu_chuoi_bo_dau_phan_cach_nghin_va_don_vi():
    assert ad.so_tu_chuoi("125.000 m²") == 125000.0
    assert ad.so_tu_chuoi("58,5 m²") == 58.5
    assert ad.so_tu_chuoi("") is None
    assert ad.so_tu_chuoi(None) is None
    assert ad.so_tu_chuoi(44.0) == 44.0


def test_quy_doi_gia_ve_vnd_thuc():
    assert ad.trieu_sang_vnd(4850) == 4_850_000_000
    assert ad.ty_sang_vnd(12000) == 12_000_000_000_000
    assert ad.trieu_sang_vnd(0) is None, "0 nghĩa là CHƯA CÓ GIÁ, không phải giá bằng không"


def test_dich_du_an_ra_dung_ten_va_enum_cua_hop_dong():
    ra = ad.dich_du_an(du_lieu.DU_AN[0])
    assert ra["name"] == "Khu đô thị Ánh Dương"
    assert ra["region"] == "Hà Nội"
    assert ra["salePhase"] == "dang_ban"
    assert ra["category"] == ["chung_cu", "shophouse"]
    assert ra["totalLandAreaM2"] == 125000.0
    assert ra["totalInvestmentVnd"] == 12_000_000_000_000
    assert ra["link360"].startswith("https://kuula.co/")
    assert ra["status"] == "published"


def test_dich_can_ra_enum_va_gia_vnd():
    ra = ad.dich_can(du_lieu.CAN[0])
    assert ra["projectExternalId"] == "PRJ-0001"
    assert ra["zoneExternalId"] == "ZON-0001"
    assert ra["saleStatus"] in ("available", "booked", "sold")
    assert ra["productType"] in ("chung_cu", "studio", "duplex", "penthouse", "biet_thu", "lien_ke", "shophouse")
    assert ra["priceVnd"] == 2_400_000_000


def test_dich_can_khong_phan_khu_thi_bo_han_khoa_do():
    khong_pk = next(c for c in du_lieu.CAN if not c["phanKhu"])
    assert "zoneExternalId" not in ad.dich_can(khong_pk)


def test_dich_can_chua_co_gia_thi_bo_khoa_gia():
    chua_gia = next(c for c in du_lieu.CAN if not c["giaBanTrieuDong"])
    ra = ad.dich_can(chua_gia)
    assert "priceVnd" not in ra, "gửi 0 là bịa một mức giá không tồn tại"


def test_dich_tai_lieu_co_tep_thi_fileUrl_tro_ve_crm_gia():
    co_tep = next(t for t in du_lieu.TAI_LIEU if t["tenTep"])
    ra = ad.dich_tai_lieu(co_tep, goc_tep=GOC_TEP)
    assert ra["fileUrl"] == f"{GOC_TEP}/{co_tep['tenTep']}"
    assert "body" not in ra


def test_dich_tai_lieu_co_noi_dung_thi_khong_co_fileUrl():
    co_chu = next(t for t in du_lieu.TAI_LIEU if t["noiDung"])
    ra = ad.dich_tai_lieu(co_chu, goc_tep=GOC_TEP)
    assert ra["body"] == co_chu["noiDung"]
    assert "fileUrl" not in ra
    assert ra["loai"] in ("csbh", "phap_ly", "huong_dan", "khac")


def test_dich_anh_ra_content_type_va_category_cua_hop_dong():
    ra = ad.dich_anh(du_lieu.ANH[0], goc_tep=GOC_TEP)
    assert ra["contentType"] in ("image", "video")
    assert ra["category"] in ("tong_quan", "ngoai_that", "noi_that", "tien_ich", "mat_bang", "vi_tri", "tien_do")
    assert ra["mediaUrl"]


def test_chia_lo_khong_vuot_tran():
    lo = ad.chia_lo(list(range(1201)), tran=500)
    assert [len(x) for x in lo] == [500, 500, 201]


def test_trang_ban_ke_khong_chua_khe_va_sap_theo_byte():
    """`afterExternalId` là mã LỚN NHẤT ĐÃ GỬI của trang trước — không phải mã đã QUÉT.
    Chọn nghĩa sai tạo một khe im lặng ở ranh giới trang, và `delete` rơi ở đó không ai thấy.
    """
    ma = sorted(["b", "A", "c", "B", "a"])  # thứ tự byte: A, B, a, b, c
    trang = ad.trang_ban_ke(ma, tran=2)
    assert [t[1] for t in trang] == [["A", "B"], ["a", "b"], ["c"]]
    assert [t[0] for t in trang] == [None, "B", "b"]
    assert [t[2] for t in trang] == [False, False, True]


def test_trang_ban_ke_mot_trang_thi_la_trang_cuoi():
    trang = ad.trang_ban_ke(["x", "y"], tran=500)
    assert trang == [(None, ["x", "y"], True)]


def test_trang_ban_ke_rong_van_tra_mot_trang_cuoi():
    """Entity không còn bản ghi nào vẫn phải gửi một bản kê rỗng — nếu không thì thứ
    mình đang giữ không bao giờ bị kiểm."""
    assert ad.trang_ban_ke([], tran=500) == [(None, [], True)]
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_adapter_crm_gia.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.adapter_crm_gia'`

- [ ] **Step 3: Viết phần dịch**

Tạo `scripts/adapter_crm_gia.py`:

```python
"""Adapter CRM giả → cổng nạp Portal. ĐÂY LÀ THỨ ĐƯA CHO ĐỘI KỸ THUẬT BÊN KHÁCH XEM.

Nó đóng đúng vai hệ thống của khách: đọc CRM của họ, DỊCH sang hợp đồng cổng nạp, đẩy
`/events`, rồi gửi `/manifest` để đối soát. Bốn việc mà một adapter thật cũng phải làm:

  1. Đẩy theo lô ≤ 500 bản ghi (`TRAN_LO` của hợp đồng).
  2. ĐỌC `results` và in bản ghi `rejected` kèm lý do — không chỉ xem mã HTTP. Cổng nạp
     luôn trả 200 và nói về từng bản ghi trong `results`.
  3. Bản kê sắp theo THỨ TỰ BYTE, `afterExternalId` = mã lớn nhất ĐÃ GỬI ở trang trước.
  4. Nhận `externalIdLech` rồi đẩy lại đúng những mã đó.

    uv run python scripts/adapter_crm_gia.py --token <token nạp> --dao-thu-tu
"""

import argparse
import sys

import httpx

GOC_INGEST = "/api/v1/ingest/realestate/v1"
TRAN_LO = 500
TRAN_BAN_KE = 20_000

# CRM giả nói tiếng Việt có dấu; hợp đồng dùng enum không dấu. Bảng tra chứ không đoán:
# thiếu một khoá là KeyError ngay ở adapter, thay vì một bản ghi bị cổng nạp từ chối
# sau khi đã đi hết đường mạng.
GIAI_DOAN = {"Sắp mở bán": "sap_mo_ban", "Đang bán": "dang_ban", "Bàn giao": "ban_giao", "Đóng giỏ hàng": "dong_gio_hang"}
LOAI_HINH = {
    "Chung cư": "chung_cu",
    "Biệt thự": "biet_thu",
    "Liền kề": "lien_ke",
    "Shophouse": "shophouse",
    "Đất nền": "dat_nen",
    "Văn phòng": "van_phong",
}
TINH_TRANG = {"Còn hàng": "available", "Đã cọc": "booked", "Đã bán": "sold"}
LOAI_CAN = {
    "Chung cư": "chung_cu",
    "Studio": "studio",
    "Duplex": "duplex",
    "Penthouse": "penthouse",
    "Officetel": "officetel",
    "Condotel": "condotel",
    "Biệt thự": "biet_thu",
    "Liền kề": "lien_ke",
    "Shophouse": "shophouse",
    "Nhà phố": "nha_pho",
    "Đất nền": "dat_nen",
    "Văn phòng": "van_phong",
}
HUONG = {
    "Đông": "dong",
    "Tây": "tay",
    "Nam": "nam",
    "Bắc": "bac",
    "Đông Bắc": "dong_bac",
    "Đông Nam": "dong_nam",
    "Tây Bắc": "tay_bac",
    "Tây Nam": "tay_nam",
}
NHOM_ANH = {
    "Tổng quan": "tong_quan",
    "Ngoại thất": "ngoai_that",
    "Nội thất": "noi_that",
    "Tiện ích": "tien_ich",
    "Mặt bằng": "mat_bang",
    "Vị trí": "vi_tri",
    "Tiến độ": "tien_do",
}
PHAN_LOAI_TAI_LIEU = {"csbh": "csbh", "phap_ly": "phap_ly", "huong_dan": "huong_dan", "khac": "khac"}


def so_tu_chuoi(v: object) -> float | None:
    """`"125.000 m²"` → `125000.0`. CRM dùng `.` cho nghìn và `,` cho thập phân.

    Đổi sai ở đây lệch 1000 lần mà không có lỗi nào — cổng nạp nhận một con số hợp lệ.
    """
    if v is None or v == "":
        return None
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v)
    s = str(v)
    s = "".join(c for c in s if c.isdigit() or c in ".,")
    if not s:
        return None
    return float(s.replace(".", "").replace(",", "."))


def trieu_sang_vnd(v: object) -> int | None:
    """`0`/rỗng ⇒ `None`: CRM ghi 0 nghĩa là CHƯA CÓ GIÁ, và gửi 0 là bịa một mức giá."""
    s = so_tu_chuoi(v)
    return int(s * 1_000_000) if s else None


def ty_sang_vnd(v: object) -> int | None:
    s = so_tu_chuoi(v)
    return int(s * 1_000_000_000) if s else None


def _bo_rong(d: dict) -> dict:
    """Khoá rỗng/None bị BỎ HẲN, không gửi lên.

    Gửi `null` cho một trường bắt buộc là bị từ chối, còn gửi `null` cho trường tuỳ chọn
    thì hợp đồng coi là «vắng mặt» và cột về DEFAULT — đúng thứ mình muốn, nhưng nói rõ
    bằng cách không gửi thì đọc log dễ hơn.
    """
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def dich_du_an(h: dict) -> dict:
    return _bo_rong(
        {
            "name": h["tenDuAn"],
            "region": h.get("khuVuc"),
            "address": h.get("diaChi"),
            "investor": h.get("chuDauTu"),
            "developer": h.get("donViPhatTrien"),
            "category": [LOAI_HINH[x] for x in h.get("loaiHinh", [])],
            "salePhase": GIAI_DOAN[h["giaiDoanBan"]] if h.get("giaiDoanBan") else None,
            "productScale": h.get("quyMoSanPham"),
            "overview": h.get("gioiThieu"),
            "amenities": h.get("tienIch"),
            "ownershipForm": h.get("hinhThucSoHuu"),
            "handoverStandard": h.get("tieuChuanBanGiao"),
            "totalLandAreaM2": so_tu_chuoi(h.get("dienTichDatM2")),
            "floorAreaM2": so_tu_chuoi(h.get("dienTichSanM2")),
            "buildDensityPct": so_tu_chuoi(h.get("matDoXayDungPhanTram")),
            "totalInvestmentVnd": ty_sang_vnd(h.get("tongMucDauTuTyDong")),
            "link360": h.get("linkTour"),
            "status": "published",
        }
    )


def dich_phan_khu(h: dict) -> dict:
    return _bo_rong(
        {
            "projectExternalId": h["duAn"],
            "name": h["tenPhanKhu"],
            "category": LOAI_HINH[h["loaiHinh"]] if h.get("loaiHinh") else None,
            "productScale": h.get("quyMoSanPham"),
            "overview": h.get("gioiThieu"),
            "status": "published",
        }
    )


def dich_can(h: dict) -> dict:
    return _bo_rong(
        {
            "projectExternalId": h["duAn"],
            "zoneExternalId": h.get("phanKhu"),
            "unitCode": h["maCan"],
            "saleStatus": TINH_TRANG[h["tinhTrang"]],
            "productType": LOAI_CAN[h["loaiCan"]],
            "priceVnd": trieu_sang_vnd(h.get("giaBanTrieuDong")),
            "pricePerM2Vnd": trieu_sang_vnd(h.get("giaMoiM2TrieuDong")),
            "direction": HUONG[h["huongNha"]] if h.get("huongNha") else None,
            "bedrooms": h.get("soPhongNgu"),
            "block": h.get("toaBlock"),
            "floor": h.get("tang"),
            "numFloors": h.get("soTang"),
            "areaBuiltM2": so_tu_chuoi(h.get("dienTichThongThuyM2")),
            "areaWallM2": so_tu_chuoi(h.get("dienTichTimTuongM2")),
            "status": "published",
        }
    )


def dich_tai_lieu(h: dict, *, goc_tep: str) -> dict:
    """Có `tenTep` ⇒ gửi `fileUrl` trỏ về CRM giả, KHÔNG gửi `body`.

    Hai trường cùng lúc thì cổng nạp coi là «đã có chữ» và không bóc tệp — mất đúng nhánh
    mình muốn kiểm.
    """
    return _bo_rong(
        {
            "projectExternalId": h["duAn"],
            "title": h["tieuDe"],
            "loai": PHAN_LOAI_TAI_LIEU[h["phanLoai"]],
            "body": h.get("noiDung"),
            "fileUrl": f"{goc_tep}/{h['tenTep']}" if h.get("tenTep") else None,
            "status": "published",
        }
    )


def dich_anh(h: dict, *, goc_tep: str) -> dict:
    """Ảnh trỏ về tệp của CRM giả để nhánh thumb có thứ thật tải về; video giữ URL ngoài."""
    duong_dan = f"{goc_tep}/{h['tenTep']}" if h.get("tenTep") else h["duongDan"]
    return _bo_rong(
        {
            "projectExternalId": h["duAn"],
            "zoneExternalId": h.get("phanKhu"),
            "unitExternalId": h.get("can"),
            "mediaUrl": duong_dan,
            "contentType": "video" if h["loaiNoiDung"] == "Video" else "image",
            "category": NHOM_ANH[h["nhomAnh"]],
            "caption": h.get("moTa"),
            "fileName": h.get("tenTep"),
            "status": "published",
        }
    )


def chia_lo(items: list, tran: int = TRAN_LO) -> list[list]:
    return [items[i : i + tran] for i in range(0, len(items), tran)] or [[]]


def trang_ban_ke(ma: list[str], tran: int = TRAN_BAN_KE) -> list[tuple[str | None, list[str], bool]]:
    """`[(afterExternalId, mã của trang, isLastPage)]`. Đầu vào PHẢI đã sắp theo byte.

    `afterExternalId` là mã lớn nhất ĐÃ GỬI ở trang trước, không phải mã đã QUÉT — chọn
    nghĩa thứ hai tạo một khe ở ranh giới trang mà không trang nào kiểm, và một `delete`
    bị rơi ở đó không ai phát hiện.

    Danh sách rỗng vẫn ra MỘT trang cuối: entity không còn bản ghi nào bên khách thì bản kê
    rỗng chính là lời khai «tôi không giữ gì», và không gửi thì thứ mình đang giữ không bao
    giờ bị kiểm.
    """
    if not ma:
        return [(None, [], True)]
    khoi = [ma[i : i + tran] for i in range(0, len(ma), tran)]
    ra: list[tuple[str | None, list[str], bool]] = []
    truoc: str | None = None
    for i, k in enumerate(khoi):
        ra.append((truoc, k, i == len(khoi) - 1))
        truoc = k[-1]
    return ra
```

- [ ] **Step 4: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/unit/test_adapter_crm_gia.py -v`
Expected: PASS — 13 test.

- [ ] **Step 5: Lint và commit**

```bash
make lint
git add scripts/adapter_crm_gia.py tests/unit/test_adapter_crm_gia.py
git commit -m "test(adapter): translate fake CRM records into the ingest contract"
```

---

### Task 7: Đường đẩy của adapter

**Files:**
- Modify: `scripts/adapter_crm_gia.py`
- Test: `tests/unit/test_adapter_day.py`

**Interfaces:**
- Consumes: các hàm dịch của Task 6.
- Produces:
  - `doc_het(crm: httpx.Client, loai: str, *, tu: str | None = None) -> list[dict]` — ghép mọi trang.
  - `dung_ban_ghi(loai: str, hang: dict, *, goc_tep: str, luc: str) -> dict` — một phần tử `records`.
  - `THU_TU: tuple[str, ...]` = `("duan", "phankhu", "can", "tailieu", "anh")` và `THU_TU_DAO` — thứ tự đảo để bản ghi con phải chờ cha.
  - `day(portal: httpx.Client, records: list[dict], *, sync_id: str) -> tuple[int, int, int, list[dict]]` — `(accepted, rejected, stale, danh sách bị từ chối)`.
  - `doi_soat(portal: httpx.Client, entity: str, muc: list[dict]) -> list[str]` — trả `externalIdLech` gộp mọi trang.
  - `chay(...) -> int` — một vòng trọn vẹn; trả số bản ghi bị từ chối.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_adapter_day.py`:

```python
"""Đường đẩy của adapter — ghép trang, dựng bản ghi, đọc `results`, đẩy lại mã lệch.

Dùng `httpx.MockTransport` nên không cần backend và không cần CRM giả chạy: cái đáng canh
là adapter có ĐỌC `results` và có đẩy lại `externalIdLech` hay không.
"""

import httpx

from scripts import adapter_crm_gia as ad

GOC_TEP = "http://crm/tep"


def test_doc_het_ghep_moi_trang():
    def xu_ly(req: httpx.Request) -> httpx.Response:
        trang = int(dict(req.url.params).get("trang", 1))
        if trang == 1:
            return httpx.Response(200, json={"tong": 3, "trang": 1, "duLieu": [{"ma": "A"}, {"ma": "B"}]})
        return httpx.Response(200, json={"tong": 3, "trang": 2, "duLieu": [{"ma": "C"}]})

    crm = httpx.Client(transport=httpx.MockTransport(xu_ly), base_url="http://crm")
    assert [h["ma"] for h in ad.doc_het(crm, "duan")] == ["A", "B", "C"]


def test_dung_ban_ghi_mang_vo_dung_hinh_dang():
    hang = {"ma": "PRJ-0001", "tenDuAn": "X", "giaiDoanBan": "Đang bán", "loaiHinh": [], "capNhatLuc": "2026-08-17T09:00:00+07:00"}
    bg = ad.dung_ban_ghi("duan", hang, goc_tep=GOC_TEP, luc="2026-08-17T10:00:00+07:00")
    assert bg["entity"] == "project"
    assert bg["externalId"] == "PRJ-0001"
    assert bg["op"] == "upsert"
    assert bg["occurredAt"] == "2026-08-17T10:00:00+07:00"
    assert bg["data"]["name"] == "X"


def test_day_doc_results_va_tra_ve_ban_ghi_bi_tu_choi():
    """Cổng nạp LUÔN trả 200; bản ghi hỏng nằm trong `results`. Chỉ xem mã HTTP là bỏ sót."""

    def xu_ly(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "accepted": 1,
                "rejected": 1,
                "stale": 0,
                "dryRun": False,
                "results": [
                    {"externalId": "A", "status": "accepted", "field": "", "reason": ""},
                    {"externalId": "B", "status": "rejected", "field": "productType", "reason": "Thiếu trường bắt buộc"},
                ],
            },
        )

    portal = httpx.Client(transport=httpx.MockTransport(xu_ly), base_url="http://portal")
    nhan, tu_choi, cu, hong = ad.day(portal, [{"entity": "unit"}], sync_id="s1")
    assert (nhan, tu_choi, cu) == (1, 1, 0)
    assert [h["externalId"] for h in hong] == ["B"]


def test_doi_soat_gop_ma_lech_moi_trang_va_gui_dung_moc_trang_truoc():
    da_gui: list[dict] = []

    def xu_ly(req: httpx.Request) -> httpx.Response:
        import json as _json

        than = _json.loads(req.content)
        da_gui.append(than)
        lech = ["A"] if than.get("afterExternalId") is None else ["c"]
        return httpx.Response(200, json={"dryRun": False, "soLech": 1, "soNghiMatTich": 0, "externalIdLech": lech, "externalIdNghiMatTich": []})

    portal = httpx.Client(transport=httpx.MockTransport(xu_ly), base_url="http://portal")
    muc = [{"externalId": m, "updatedAt": "2026-08-17T09:00:00+07:00"} for m in ["A", "B", "c"]]
    lech = ad.doi_soat(portal, "project", muc, tran=2)
    assert lech == ["A", "c"]
    assert [t.get("afterExternalId") for t in da_gui] == [None, "B"]
    assert [t["isLastPage"] for t in da_gui] == [False, True]


def test_doi_soat_sap_ma_theo_byte_truoc_khi_chia_trang():
    """Sắp bằng thứ tự khác — collation có ngôn ngữ, không phân biệt hoa thường — làm ranh
    giới lệch, và bản ghi rơi vào trang không chứa nó bị gắn cờ SAI."""
    da_gui: list[dict] = []

    def xu_ly(req: httpx.Request) -> httpx.Response:
        import json as _json

        da_gui.append(_json.loads(req.content))
        return httpx.Response(200, json={"dryRun": False, "soLech": 0, "soNghiMatTich": 0, "externalIdLech": [], "externalIdNghiMatTich": []})

    portal = httpx.Client(transport=httpx.MockTransport(xu_ly), base_url="http://portal")
    muc = [{"externalId": m, "updatedAt": "2026-08-17T09:00:00+07:00"} for m in ["b", "A", "a", "B"]]
    ad.doi_soat(portal, "project", muc, tran=10)
    assert [m["externalId"] for m in da_gui[0]["records"]] == ["A", "B", "a", "b"]


def test_thu_tu_dao_dat_con_truoc_cha():
    assert ad.THU_TU.index("duan") < ad.THU_TU.index("can")
    assert ad.THU_TU_DAO.index("can") < ad.THU_TU_DAO.index("duan")
    assert set(ad.THU_TU) == set(ad.THU_TU_DAO)
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_adapter_day.py -v`
Expected: FAIL — `AttributeError: module 'scripts.adapter_crm_gia' has no attribute 'doc_het'`

- [ ] **Step 3: Viết đường đẩy**

Thêm vào cuối `scripts/adapter_crm_gia.py`:

```python
# ─── Đọc CRM ────────────────────────────────────────────────────────────────

ENTITY = {"duan": "project", "phankhu": "zone", "can": "unit", "tailieu": "document", "anh": "media"}
THU_TU: tuple[str, ...] = ("duan", "phankhu", "can", "tailieu", "anh")
THU_TU_DAO: tuple[str, ...] = ("can", "anh", "tailieu", "phankhu", "duan")
"""Con trước cha. Bản ghi con phải nằm chờ ở `cho_cha_*` rồi được lan truyền khi cha tới —
đường mà MỌI bản ghi tới trước cha đi qua trong thực tế, nên phải chạy thật một lần."""


def doc_het(crm: httpx.Client, loai: str, *, tu: str | None = None) -> list[dict]:
    """Ghép mọi trang. CRM giả trả `{"tong", "trang", "duLieu"}`."""
    ra: list[dict] = []
    trang = 1
    while True:
        ts: dict[str, object] = {"trang": trang}
        if tu:
            ts["tu"] = tu
        r = crm.get(f"/api/{loai}", params=ts)
        r.raise_for_status()
        than = r.json()
        ra.extend(than["duLieu"])
        if len(ra) >= than["tong"] or not than["duLieu"]:
            return ra
        trang += 1


_DICH = {
    "duan": lambda h, goc: dich_du_an(h),
    "phankhu": lambda h, goc: dich_phan_khu(h),
    "can": lambda h, goc: dich_can(h),
    "tailieu": lambda h, goc: dich_tai_lieu(h, goc_tep=goc),
    "anh": lambda h, goc: dich_anh(h, goc_tep=goc),
}


def dung_ban_ghi(loai: str, hang: dict, *, goc_tep: str, luc: str) -> dict:
    """Vỏ bản ghi. `occurredAt` PHẢI mang múi giờ — bản naive từng bị diễn giải theo giờ
    HOST của server, tức trọng tài thứ tự đổi nghĩa theo máy deploy."""
    return {
        "entity": ENTITY[loai],
        "externalId": hang["ma"],
        "op": "upsert",
        "occurredAt": luc,
        "data": _DICH[loai](hang, goc_tep),
    }


# ─── Đẩy ────────────────────────────────────────────────────────────────────


def day(portal: httpx.Client, records: list[dict], *, sync_id: str) -> tuple[int, int, int, list[dict]]:
    """Một lô. Trả `(accepted, rejected, stale, danh sách bị từ chối)`.

    Cổng nạp LUÔN trả 200 khi request hợp lệ — mã HTTP nói về REQUEST, `results` nói về
    từng bản ghi. Adapter chỉ xem mã HTTP sẽ báo thành công cho một lô hỏng hết.
    """
    r = portal.post(f"{GOC_INGEST}/events", json={"records": records, "syncId": sync_id})
    r.raise_for_status()
    than = r.json()
    hong = [k for k in than["results"] if k["status"] == "rejected"]
    return than["accepted"], than["rejected"], than["stale"], hong


def doi_soat(portal: httpx.Client, entity: str, muc: list[dict], *, tran: int = TRAN_BAN_KE) -> list[str]:
    """Bản kê phân trang cho MỘT entity. Trả `externalIdLech` gộp mọi trang.

    SẮP THEO THỨ TỰ BYTE trước khi chia trang: Postgres so bằng `COLLATE "C"`, còn sắp
    bằng thứ tự có ngôn ngữ (không phân biệt hoa thường) làm ranh giới trang lệch, và bản
    ghi rơi vào trang không chứa nó sẽ bị gắn cờ nghi mất tích SAI.
    """
    theo_ma = {m["externalId"]: m for m in muc}
    ma_sap = sorted(theo_ma)
    lech: list[str] = []
    for after, ma_trang, la_cuoi in trang_ban_ke(ma_sap, tran):
        than: dict[str, object] = {
            "entity": entity,
            "records": [theo_ma[m] for m in ma_trang],
            "isLastPage": la_cuoi,
        }
        if after is not None:
            than["afterExternalId"] = after
        r = portal.post(f"{GOC_INGEST}/manifest", json=than)
        r.raise_for_status()
        lech.extend(r.json()["externalIdLech"])
    return lech


# ─── Một vòng trọn vẹn ──────────────────────────────────────────────────────


def chay(
    crm: httpx.Client,
    portal: httpx.Client,
    *,
    goc_tep: str,
    luc: str,
    dao_thu_tu: bool = False,
    tu: str | None = None,
) -> int:
    """Đọc → dịch → đẩy → đối soát → đẩy lại mã lệch. Trả số bản ghi bị từ chối.

    Đẩy TOÀN BỘ bộ dữ liệu, gồm cả tài liệu phải OCR: pipeline chỉ được coi là kiểm nếu
    cả bốn nhánh bóc chữ đều chạy thật.
    """
    tong_hong = 0
    theo_loai: dict[str, list[dict]] = {}
    for loai in THU_TU_DAO if dao_thu_tu else THU_TU:
        hang = doc_het(crm, loai, tu=tu)
        theo_loai[loai] = hang
        records = [dung_ban_ghi(loai, h, goc_tep=goc_tep, luc=luc) for h in hang]
        for i, lo in enumerate(chia_lo(records)):
            if not lo:
                continue
            nhan, tu_choi, cu, hong = day(portal, lo, sync_id=f"{loai}-{i}")
            print(f"  {loai} lô {i + 1}: nhận {nhan} · từ chối {tu_choi} · cũ {cu}")
            for h in hong:
                print(f"    ✗ {h['externalId']} [{h['field'] or 'bản ghi'}] {h['reason']}")
            tong_hong += tu_choi

    for loai, hang in theo_loai.items():
        muc = [{"externalId": h["ma"], "updatedAt": h["capNhatLuc"]} for h in hang]
        lech = doi_soat(portal, ENTITY[loai], muc)
        if not lech:
            continue
        print(f"  {loai}: đẩy lại {len(lech)} mã lệch")
        theo_ma = {h["ma"]: h for h in hang}
        records = [dung_ban_ghi(loai, theo_ma[m], goc_tep=goc_tep, luc=luc) for m in lech if m in theo_ma]
        for lo in chia_lo(records):
            if lo:
                day(portal, lo, sync_id=f"{loai}-lech")
    return tong_hong


def main() -> int:
    p = argparse.ArgumentParser(description="Adapter CRM giả → cổng nạp Portal")
    p.add_argument("--token", required=True, help="token nạp (Bearer)")
    p.add_argument("--portal", default="http://localhost:8100")
    p.add_argument("--crm", default="http://127.0.0.1:8123")
    p.add_argument("--luc", default="2026-08-17T10:00:00+07:00", help="occurredAt của lượt đẩy")
    p.add_argument("--dao-thu-tu", action="store_true", help="đẩy con trước cha")
    p.add_argument("--tu", default=None, help="chỉ lấy bản ghi đổi sau mốc này")
    a = p.parse_args()

    with (
        httpx.Client(base_url=a.crm, timeout=30) as crm,
        httpx.Client(base_url=a.portal, timeout=60, headers={"Authorization": f"Bearer {a.token}"}) as portal,
    ):
        hong = chay(crm, portal, goc_tep=f"{a.crm}/tep", luc=a.luc, dao_thu_tu=a.dao_thu_tu, tu=a.tu)
    print(f"Xong — {hong} bản ghi bị từ chối")
    return 1 if hong else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Chạy test để xác nhận xanh**

Run: `uv run pytest tests/unit/test_adapter_day.py tests/unit/test_adapter_crm_gia.py -v`
Expected: PASS — 19 test.

- [ ] **Step 5: Lint và commit**

```bash
make lint
git add scripts/adapter_crm_gia.py tests/unit/test_adapter_day.py
git commit -m "test(adapter): push batches, read per-record results, reconcile by manifest"
```

---

### Task 8: Script e2e xác minh tới Qdrant

**Files:**
- Create: `scripts/e2e_nap_toi_qdrant.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `scripts.adapter_crm_gia.chay` · `scripts.crm_gia` (chạy như tiến trình riêng) ·
  `qdrant_client.QdrantClient` · HTTP Portal (`POST /api/v1/auth/login`,
  `POST /api/v1/me/workspace`, `GET /api/v1/me`, `POST|DELETE …/keys`, `GET …/tong-quan`).
- Produces: `scripts/e2e_nap_toi_qdrant.py` chạy được, thoát `0` nếu mọi bước xanh.

- [ ] **Step 1: Viết script**

Tạo `scripts/e2e_nap_toi_qdrant.py`:

```python
"""E2E: CRM giả → adapter → cổng nạp → Postgres → hàng đợi → point trên Qdrant.

CẦN GÌ TRƯỚC KHI CHẠY:
  · `make dev && make migrate && make grant-api-dev && make dev-seed` (Postgres + Qdrant)
  · `make api` và `make worker` đang chạy
  · `make crm-gia` đang chạy (cổng 8123)
  · embed service THẬT tới được (`KB_EMBED_URL` + `KB_SANTA_MODELS_TOKEN`) — quyết định
    của spec là chỉ embed thật, nên script này KHÔNG chạy được offline và KHÔNG chạy trong
    CI. Mỗi lượt chạy TỐN TIỀN EMBED.
  · VLM THẬT tới được (`KB_VLM_API_KEY`, và `KB_VLM_BASE_URL` nếu khác mặc định
    DashScope) — bộ dữ liệu có một tài liệu là PDF SCAN, và nó chỉ tới được agent qua
    nhánh OCR. Thiếu khoá này thì bước «ba nhánh bóc chữ đều ra point» đỏ, và đỏ ĐÚNG:
    một nhánh của pipeline chưa chạy.

    uv run python scripts/e2e_nap_toi_qdrant.py

Thoát 0 nếu mọi bước xanh, 1 nếu có bước đỏ.

⚠️ Bản kê của adapter phủ TOÀN BỘ không gian mã (`isLastPage: true` ở trang cuối), nên
script này chỉ được chạy trên workspace dev dùng riêng cho nó. Trên một workspace có dữ
liệu thật, bản kê đầy đủ sẽ gắn cờ nghi mất tích cho mọi bản ghi không do CRM giả tạo.
Dùng `--tenant` để chỉ đúng workspace đó.
"""

import argparse
import sys
import time

import httpx
from qdrant_client import QdrantClient, models

from scripts import adapter_crm_gia as ad

XANH, DO, HET = "\033[32m", "\033[31m", "\033[0m"
GOC_INGEST = ad.GOC_INGEST


class Ket:
    def __init__(self) -> None:
        self.hang: list[tuple[str, bool, str]] = []

    def ghi(self, ten: str, dat: bool, chi_tiet: str = "") -> bool:
        dau = f"{XANH}✓{HET}" if dat else f"{DO}✗{HET}"
        print(f"  {dau} {ten}{f' — {chi_tiet}' if chi_tiet and not dat else ''}")
        self.hang.append((ten, dat, chi_tiet))
        return dat

    def xong(self) -> int:
        do = [t for t, dat, _ in self.hang if not dat]
        print(f"\n{len(self.hang) - len(do)}/{len(self.hang)} bước xanh")
        return 1 if do else 0


def dang_nhap(portal: httpx.Client, email: str, mat_khau: str, tenant: str) -> str:
    r = portal.post("/api/v1/auth/login", json={"email": email, "password": mat_khau})
    r.raise_for_status()
    for ten, gia_tri in r.cookies.items():
        portal.cookies.set(ten, gia_tri)
    portal.post("/api/v1/me/workspace", json={"workspaceId": tenant}).raise_for_status()
    return str(portal.get("/api/v1/me").json()["currentWorkspaceId"])


def cho_hang_doi_can(portal: httpx.Client, ket: Ket, *, han_giay: int) -> bool:
    """Chờ tới khi không còn việc `queued|running`. Suy từ `GET …/tong-quan` thì không
    thấy hàng đợi, nên script đọc chỉ báo lệch của module BĐS — nó CÓ đếm việc đang chờ.
    """
    het = time.monotonic() + han_giay
    while time.monotonic() < het:
        r = portal.get("/api/v1/projects/kb-status")
        r.raise_for_status()
        dang = [d for d in r.json() if d["indexing"]]
        if not dang:
            return ket.ghi("hàng đợi cạn", True)
        time.sleep(3)
    return ket.ghi("hàng đợi cạn", False, f"quá {han_giay}s vẫn còn việc đang chạy")


def dem_point(qc: QdrantClient, ten: str) -> int:
    if not qc.collection_exists(ten):
        return -1
    return int(qc.count(collection_name=ten, exact=True).count)


def mot_point(qc: QdrantClient, ten: str) -> dict:
    diem, _ = qc.scroll(collection_name=ten, limit=1, with_payload=True)
    return dict(diem[0].payload) if diem else {}


def dem_theo_doc_type(qc: QdrantClient, ten: str, doc_type: str) -> int:
    """Đếm point của một loại tài liệu. `doc_type` suy từ tiền tố `title` (`kb.contracts`)."""
    if not qc.collection_exists(ten):
        return -1
    loc = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))])
    return int(qc.count(collection_name=ten, count_filter=loc, exact=True).count)


def main() -> int:
    p = argparse.ArgumentParser(description="E2E cổng nạp → Qdrant")
    p.add_argument("--portal", default="http://localhost:8100")
    p.add_argument("--crm", default="http://127.0.0.1:8123")
    p.add_argument("--qdrant", default="http://localhost:6343")
    p.add_argument("--email", default="dang@anphuland.vn")
    p.add_argument("--password", default="odyssey-dev")
    p.add_argument("--tenant", default="anphu")
    p.add_argument("--han-giay", type=int, default=900)
    a = p.parse_args()

    ket = Ket()
    qc = QdrantClient(url=a.qdrant)
    print(f"E2E cổng nạp → Qdrant — portal {a.portal} · crm {a.crm} · qdrant {a.qdrant}\n")

    with httpx.Client(base_url=a.portal, timeout=60) as portal:
        tenant = dang_nhap(portal, a.email, a.password, a.tenant)
        ket.ghi(f"đăng nhập và vào workspace {tenant}", tenant == a.tenant, f"vào {tenant}")

        r = portal.post(f"{GOC_INGEST}/keys", json={"label": "e2e qdrant"})
        ket.ghi("tạo token nạp", r.status_code == 201, f"HTTP {r.status_code}")
        token = r.json()["token"]
        token_id = r.json()["id"]

        col_doc, col_media = f"{tenant}_documents", f"{tenant}_media"
        doc0, media0 = dem_point(qc, col_doc), dem_point(qc, col_media)
        print(f"  point trước: documents={doc0} media={media0}")

        try:
            with (
                httpx.Client(base_url=a.crm, timeout=30) as crm,
                httpx.Client(base_url=a.portal, timeout=60, headers={"Authorization": f"Bearer {token}"}) as khach,
            ):
                crm.post("/gia-lap/reset")

                print("\nVòng 1 — đẩy ĐẢO THỨ TỰ (con trước cha)")
                hong = ad.chay(
                    crm, khach, goc_tep=f"{a.crm}/tep", luc="2026-08-17T10:00:00+07:00", dao_thu_tu=True
                )
                ket.ghi("vòng 1 không có bản ghi bị từ chối", hong == 0, f"{hong} bản ghi hỏng")

                print("\nChờ worker")
                cho_hang_doi_can(portal, ket, han_giay=a.han_giay)

                doc1, media1 = dem_point(qc, col_doc), dem_point(qc, col_media)
                print(f"  point sau vòng 1: documents={doc1} media={media1}")
                ket.ghi("collection documents có thêm point", doc1 > doc0, f"{doc0} → {doc1}")
                ket.ghi("collection media có thêm point", media1 > media0, f"{media0} → {media1}")

                pl = mot_point(qc, col_doc)
                ket.ghi("point documents mang project_id", bool(pl.get("project_id")), str(pl)[:120])
                ket.ghi("point documents mang status", bool(pl.get("status")), str(pl)[:120])
                ket.ghi("point documents mang text", bool(pl.get("text")), str(pl)[:120])

                pm = mot_point(qc, col_media)
                ket.ghi("point media mang media_url", bool(pm.get("media_url")), str(pm)[:120])
                ket.ghi("point media có thumb_url", bool(pm.get("thumb_url")), str(pm)[:120])

                # Ba tài liệu `csbh` của bộ dữ liệu đi ba nhánh bóc chữ KHÁC NHAU: docx ·
                # PDF có lớp chữ · PDF scan qua OCR. Nhánh nào không ra chữ thì tài liệu
                # đó ra 0 point, nên con số này là phép kiểm rẻ nhất cho cả ba.
                csbh = dem_theo_doc_type(qc, col_doc, "csbh")
                ket.ghi("ba nhánh bóc chữ đều ra point (docx · pdf lớp chữ · OCR)", csbh >= 3, f"chỉ {csbh} point csbh")

                print("\nVòng 2 — delta, không đổi nội dung gì")
                ad.chay(crm, khach, goc_tep=f"{a.crm}/tep", luc="2026-08-17T11:00:00+07:00")
                cho_hang_doi_can(portal, ket, han_giay=a.han_giay)
                doc2, media2 = dem_point(qc, col_doc), dem_point(qc, col_media)
                ket.ghi("vòng 2 không đổi số point (dấu tay trùng)", (doc2, media2) == (doc1, media1), f"{doc1},{media1} → {doc2},{media2}")

                print("\nChiều xoá — rút link360 và xoá mềm một tài liệu")
                khach.post(
                    f"{GOC_INGEST}/events",
                    json={
                        "records": [
                            {
                                "entity": "project",
                                "externalId": "PRJ-0001",
                                "op": "upsert",
                                "occurredAt": "2026-08-17T12:00:00+07:00",
                                "data": ad.dich_du_an({**_du_an_1(), "linkTour": ""}),
                            },
                            {
                                "entity": "document",
                                "externalId": "DOC-0002",
                                "op": "delete",
                                "occurredAt": "2026-08-17T12:00:00+07:00",
                                "data": {},
                            },
                        ],
                        "syncId": "e2e-xoa",
                    },
                ).raise_for_status()
                cho_hang_doi_can(portal, ket, han_giay=a.han_giay)
                doc3, media3 = dem_point(qc, col_doc), dem_point(qc, col_media)
                ket.ghi("point documents giảm sau xoá mềm", doc3 < doc2, f"{doc2} → {doc3}")
                ket.ghi("point media giảm sau khi rút tour", media3 < media2, f"{media2} → {media3}")
        finally:
            portal.delete(f"{GOC_INGEST}/keys/{token_id}")
            print("  đã xoá token nạp")

    return ket.xong()


def _du_an_1() -> dict:
    from scripts.crm_gia import du_lieu

    return dict(du_lieu.DU_AN[0])


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Thêm target Makefile**

Thêm vào `Makefile`, ngay sau target `crm-gia`:

```makefile
e2e-qdrant:     ## E2E cổng nạp → Qdrant (cần: make api, make worker, make crm-gia, embed THẬT)
	uv run python scripts/e2e_nap_toi_qdrant.py $(ARGS)
```

- [ ] **Step 3: Kiểm script không lỗi cú pháp và tham số chạy được**

Run: `uv run python scripts/e2e_nap_toi_qdrant.py --help`
Expected: in bảng tham số, thoát 0. Không cần backend cho bước này.

- [ ] **Step 4: Chạy thật (cần hạ tầng)**

```bash
make dev && make migrate && make grant-api-dev && make dev-seed
make api &
make worker &
make crm-gia &
make e2e-qdrant
```

Expected: mọi bước in `✓`, dòng cuối `N/N bước xanh`, mã thoát 0.

Nếu `hàng đợi cạn` đỏ: đọc `control.jobs` tìm hàng `state='failed'` —
`SELECT kind, message FROM control.jobs WHERE state = 'failed' ORDER BY id DESC LIMIT 5;`
Nguyên nhân hay gặp nhất là embed service không tới được, và thông điệp việc sẽ nói vậy.

- [ ] **Step 5: Lint và commit**

```bash
make lint
git add scripts/e2e_nap_toi_qdrant.py Makefile
git commit -m "test(e2e): verify ingested records reach Qdrant and leave on delete"
```

---

## Điều kiện hạ tầng của e2e

Không có chỗ nào thu hẹp so với spec: e2e chạy **trọn pipeline thật**, gồm cả bốn nhánh
bóc chữ. Giá phải trả là Task 8 cần **hai** dịch vụ ngoài, và thiếu cái nào cũng làm một
bước cụ thể đỏ — đỏ đúng, không phải đỏ nhiễu:

| Dịch vụ | Biến env | Thiếu thì bước nào đỏ |
|---|---|---|
| embed service | `KB_EMBED_URL` · `KB_SANTA_MODELS_TOKEN` | mọi bước đếm point (không point nào được ghi) |
| VLM (OCR) | `KB_VLM_API_KEY` · `KB_VLM_BASE_URL` | «ba nhánh bóc chữ đều ra point» — chỉ đếm được 2/3 |

Task 1–7 **không** cần hai dịch vụ này: chúng chạy bằng Docker (Task 1–3) hoặc không cần
gì cả (Task 4–7). Nên nếu chưa mở được tunnel thì vẫn làm được 7 task đầu.

## Self-review

**Spec coverage:**

| Mục spec | Task |
|---|---|
| §4.2 chỗ móc trong `chieu_mot`, trong savepoint | Task 1 Step 5 |
| §4.2 import qua mặt tiền `kb.contracts` | Task 1 Step 4 + Global Constraints |
| §4.3 bảng luật 7 dòng theo entity | Task 1 Step 1 (test) + Step 4 (`_xep_nap`/`_qua_viec_thumb`) |
| §4.3 `entity` là tên bảng, payload mang `project_code` | Task 1 test `test_payload_viec_mang_project_code` + `_BANG[entity]` |
| §4.4 bốn ca không đặt việc | Task 2 |
| §4.5 chống trùng | Task 1 test `test_day_lai_y_het_khong_nhan_doi_viec` |
| §5 `tour_360` hai chiều | Task 3 |
| §6.1 chỉ embed thật, không CI | Task 8 docstring + Điều kiện hạ tầng |
| §6.4 tài liệu gồm PDF có lớp chữ VÀ PDF scan | Task 4 `tep.py` (5 tệp, 4 nhánh) + 2 test canh lớp chữ |
| §6.2 giữ nguyên `demo_cong_nap_e2e.py` | Global Constraints |
| §6.3(a) server CRM giả, 4 tình huống, tệp sinh tại chỗ | Task 4 + Task 5 |
| §6.3(b) adapter, 4 việc + vòng đảo thứ tự | Task 6 + Task 7 |
| §6.3(c) script e2e 7 bước | Task 8 |
| §6.4 dữ liệu mới, khối lượng | Task 4 Step 3 + test khối lượng |
| §7 bảng test | Task 1/2/3 (11 dòng bảng spec ↔ 14 test) |
| §8 bề mặt thay đổi | khớp — cộng `tests/unit/*` mà spec không liệt kê rõ |

**Placeholder scan:** không có TBD/TODO. Mọi step có code hoặc lệnh cụ thể kèm kết quả
mong đợi.

**Type consistency:** `_xep_nap(conn, tenant_id, *, entity, record_id, cot)` dùng nhất quán
ở Task 1 và Task 2. `_upsert` trả `int` từ Task 1 và mọi lời gọi sau đó nhận `record_id`.
`ad.chay(...)` có cùng bộ tham số ở Task 7 (định nghĩa) và Task 8 (lời gọi):
`crm, portal, *, goc_tep, luc, dao_thu_tu, tu`. `trang_ban_ke` trả
`list[tuple[str | None, list[str], bool]]` ở cả định nghĩa lẫn hai chỗ dùng.
