# M10 — Đấu nối agent ngoài · Kế hoạch thi công

> **Cho agentic worker:** BẮT BUỘC dùng sub-skill `superpowers:subagent-driven-development`
> (khuyến nghị) hoặc `superpowers:executing-plans` để thi công từng task. Các bước dùng
> checkbox (`- [ ]`) để theo dõi.

**Goal:** Pod agent chạy ngoài cụm chỉ cần `PORTAL_URL` + `AGENT_API_KEY` là tự lấy được
`tenant_id` + DSN Postgres + khoá kho tệp + tên collection Qdrant, rồi chạy đúng ba lớp cách ly đã
có của M1/M3/M6.

**Architecture:** Một module mới `portal.modules.enrollment` theo đúng nếp `modules/config` của M3:
một hàm thuần (`bi_mat.py`) không chạm I/O, cộng `repo/service/router/contracts`. Một migration
trong dải `0900`–`0999`. Bí mật **suy dẫn tất định** từ `AGENT_MASTER_KEY` bằng HMAC-SHA256 —
portal chỉ lưu một số nguyên `secret_version`, không lưu mật khẩu nào. Bảng `control` dùng pool
trực tiếp, **không** `tenant_conn()` — cùng lý do đã ghi ở `modules/config/repo.py:6`.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · Alembic · pydantic v2 · `hmac`/`hashlib`/`secrets`
stdlib · `minio` (MinioAdmin, đã có từ M3) · `httpx` (đã có) · pytest + testcontainers · ruff
(line-length 120).

## Global Constraints

- **Không thêm action mới.** Ba test khoá cứng `len(ALL_ACTIONS) == 13`
  (`tests/api/test_actions.py:8` · `tests/api/test_contracts.py:46` · `tests/modules/auth/test_login.py:57`).
  Route `/admin/*` và `/agent/v1/*` khai `require(None, ly_do="…")` **cộng** dependency riêng.
- **Không bí mật nào ở trạng thái nghỉ.** Không cột nào trong `agent_keys` /
  `agent_credentials` chứa plaintext. Cổng 6 quét động.
- **Không log bí mật.** Không `logger.*`, không `print`, không `repr()` của `BootstrapOut`.
- **Comment và docstring bằng tiếng Việt**, giải thích *vì sao* chứ không chỉ *cái gì*.
- **Lint:** ruff, `line-length = 120`, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- **Mọi route khai `require(action)` hoặc `require(None, ly_do=…)`** — thiếu là
  `tests/api/test_moi_route_khai_action.py` đỏ.
- **Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`** — vi phạm là
  `tests/test_module_boundaries.py` đỏ. **Không** import `modules/kb/*` hay `modules/realestate/*`.
- **Lỗi:** module `raise loi.LoiPortal(ma, http, thong_diep)`, không tự trả JSON.
- **Nhật ký:** `nhat_ky.ghi(conn, tenant_id, hanh_dong, actor, chi_tiet)` gọi **sau khi** việc xong.
  `actor` = `"platform_admin"` (chưa biết người thật — spec §11).
- **Bảng `control` không dùng `tenant_conn()`** — pool trực tiếp, theo `modules/config/repo.py:6`.
- **Spec nguồn:** `docs/superpowers/specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md`.
  Hợp đồng nền: `docs/contracts/isolation.md` · `docs/contracts/bundle.md`.

## ⚠️ Đọc trước: bốn chỗ plan này đã lệch spec *(cập nhật 2026-08-03)*

KB được viết lại (`docs/build_module_knowledgebase/`) sau khi plan này viết xong. **Cơ chế đấu nối
không đổi** — chỉ nội dung khối `kb` và một cổng test. Chi tiết ở spec §12; bốn chỗ cụ thể:

| Task | Sửa |
|---|---|
| T5 | `KbOut.collection` → **hai** trường `documents` + `media` |
| T6 | `tao_collection_neu_thieu` tạo **hai** collection, named vectors khác nhau |
| T7 | `san_sang_du_lieu`: `field_policy_live` và `agent_enabled` **không còn tồn tại** → đếm `projects WHERE status='published'` |
| T9 | Cổng 1 vẫn `SELECT agent_api.units` — **giữ nguyên**. Nhưng `agent_api` hiện **rỗng** (`0401` đã rút view), nên Task 6 của plan KB phải chạy trước |

**Không task nào bị chặn về thiết kế** — spec §12 đã chốt cả hai quyết định. T9 chỉ chặn về **thứ
tự**: nó cần view `agent_api` tồn tại. T1–T8 và T10–T11 làm được ngay; T1–T4 không liên quan KB chút
nào.

Fixture của T9 seed `status='published'` thay vì `agent_enabled=true`, và không dùng
`seed_field_policy` (`field_policy_live` đã bị xoá khỏi hệ).

## Thứ tự với M4a

M4a **không chặn** M10 về mặt code. Nhưng cổng test 1 chỉ có nghĩa khi có dữ liệu thật (spec §6), và
Task 9 cần `seed_bds.py` của M4a. **Nếu M4a chưa xong Task 10 (`seed_bds.py`), làm Task 1–8 và 10–11
trước, để Task 9 lại sau.** Task 9 là task duy nhất phụ thuộc M4a.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `src/portal/core/khoa_api.py` | **Dùng chung với M8.** `sinh_khoa()` · `bam_khoa()` · `gioi_han_nhip()`. Không biết gì về agent |
| `src/portal/core/auth/quan_tri_nen_tang.py` | Cổng `X-Platform-Admin-Token`. Xuyên tenant, ngoài 13 action |
| `src/portal/modules/enrollment/bi_mat.py` | **HÀM THUẦN.** `dan_xuat(loai, tenant_id, version, master) -> str` |
| `src/portal/modules/enrollment/contracts.py` | pydantic v2 — `BootstrapOut` · `DeploymentIn/Out` · `KhoaMoiOut` · `SanSangDuLieu` |
| `src/portal/modules/enrollment/repo.py` | SQL thô trên `control.agent_keys` · `agent_credentials` · `deployments` |
| `src/portal/modules/enrollment/ha_tang_ngoai.py` | Gọi MinioAdmin + Qdrant. Tách khỏi `service.py` để test được bằng fake |
| `src/portal/modules/enrollment/service.py` | `cap_phat()` · `xac_thuc_khoa()` · `xoay_bi_mat()` · `thu_hoi()` · `san_sang_du_lieu()` |
| `src/portal/modules/enrollment/router.py` | 6 endpoint |
| `src/portal/modules/enrollment/loi.py` | 5 hằng lỗi của M10 |
| `src/portal/modules/enrollment/fake.py` | Dữ liệu giả cho FE (cơ chế ② spec tổng) |
| `migrations/versions/0900_agent_enrollment.py` | 2 bảng |
| `scripts/agent_gia.py` | **Sửa:** bootstrap thay vì đọc env |
| `scripts/seed_kho_tep.py` | **Sửa:** bỏ `MAT_KHAU_DEV`, gọi `bi_mat.dan_xuat()` |
| `src/portal/core/config.py` | **Sửa:** `agent_master_key` · `platform_admin_token` · `bootstrap_ttl_seconds` |
| `docs/contracts/dau-noi-agent.md` | Hợp đồng 12 mục cho Gói G |

**Vì sao `ha_tang_ngoai.py` tách khỏi `service.py`:** `cap_phat()` chạm bốn hệ (Postgres · MinIO
user · MinIO policy · Qdrant). Ba trong bốn ở ngoài Postgres và không có trong test unit. Tách ra
một mặt tiền hẹp để `service.py` test được bằng một fake, còn `ha_tang_ngoai.py` test bằng
testcontainers riêng. Đây **không** phải lớp bọc `core/storage.py` — nó gọi `chinh_sach_tien_to()`
và `ten_collection()` có sẵn, không định nghĩa lại gì.

---

## Task 1: `core/khoa_api.py` — sinh và băm khoá

**Files:**
- Create: `src/portal/core/khoa_api.py`
- Test: `tests/core/test_khoa_api.py`

**Interfaces:**
- Consumes: chỉ stdlib
- Produces: `sinh_khoa(tien_to: str = "ody_ag") -> tuple[str, str, str]` trả
  `(khoa_tho, sha256_hex, tien_to_hien_thi)` · `bam_khoa(khoa_tho: str) -> str` trả sha256 hex

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_khoa_api.py
"""Khoá API — sinh và băm. Dùng chung M10 (agent) và M8 (tenant integration)."""

import hashlib
import re

import pytest

from portal.core.khoa_api import bam_khoa, sinh_khoa


def test_sinh_khoa_dung_dinh_dang():
    """Tiền tố nhận diện được bằng mắt; phần ngẫu nhiên là base64url không padding."""
    tho, sha, hien_thi = sinh_khoa()
    assert tho.startswith("ody_ag_")
    phan_ngau_nhien = tho.removeprefix("ody_ag_")
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", phan_ngau_nhien), tho
    assert sha == hashlib.sha256(tho.encode()).hexdigest()
    assert hien_thi == tho[:12]


def test_sinh_khoa_khong_lap():
    """256 bit entropy — 500 lần sinh không được trùng."""
    assert len({sinh_khoa()[0] for _ in range(500)}) == 500


def test_bam_khoa_on_dinh():
    assert bam_khoa("ody_ag_abc") == bam_khoa("ody_ag_abc")
    assert bam_khoa("ody_ag_abc") != bam_khoa("ody_ag_abd")


@pytest.mark.parametrize("tien_to", ["ody_ag", "ody_tn"])
def test_tien_to_doi_duoc(tien_to: str):
    """M8 dùng tiền tố khác — hàm không được khoá cứng 'ody_ag'."""
    tho, _, _ = sinh_khoa(tien_to)
    assert tho.startswith(f"{tien_to}_")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_khoa_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.core.khoa_api'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/portal/core/khoa_api.py
"""Khoá API — sinh, băm, giới hạn nhịp. DÙNG CHUNG, không thuộc module nào.

VÌ SAO Ở `core/` CHỨ KHÔNG Ở `modules/enrollment/`: M8 (gói F) cũng phát khoá
API — cho tích hợp của khách hàng, không cho pod agent. Hai loại khoá khác nhau
về người phát, người dùng và bán kính thiệt hại (spec M10 §9), nên KHÔNG dùng
chung bảng. Nhưng phần cơ khí — sinh 256 bit, băm sha256, đếm nhịp trên Redis —
thì giống hệt. M10 viết trước nên M10 đặt nó ở đây; M8 dùng lại, không viết lần hai.

VÌ SAO LƯU sha256 CHỨ KHÔNG LƯU KHOÁ: một `SELECT` trên bảng khoá không được
đủ để mạo danh bất kỳ ai. Khoá thô tồn tại đúng một lần, trong response tạo khoá.
"""

import hashlib
import secrets

DO_DAI_BYTE = 32
"""256 bit. Đủ để không ai dò được, và vừa một dòng khi copy."""


def bam_khoa(khoa_tho: str) -> str:
    """sha256 hex của khoá thô. Đây là thứ DUY NHẤT được lưu vào DB.

    Không salt, không bcrypt: khoá đã là 256 bit ngẫu nhiên đều, không phải mật
    khẩu người chọn. Bảng cầu vồng vô nghĩa với không gian đó, còn bcrypt thì
    biến một phép tra index thành một phép quét toàn bảng.
    """
    return hashlib.sha256(khoa_tho.encode()).hexdigest()


def sinh_khoa(tien_to: str = "ody_ag") -> tuple[str, str, str]:
    """Trả `(khoa_tho, sha256_hex, tien_to_hien_thi)`.

    `tien_to_hien_thi` là 12 ký tự đầu — đủ để admin nhận ra khoá nào trên màn
    hình mà không đủ để dùng. Nó KHÔNG phải bí mật; lưu thẳng vào DB được.
    """
    khoa_tho = f"{tien_to}_{secrets.token_urlsafe(DO_DAI_BYTE)}"
    return khoa_tho, bam_khoa(khoa_tho), khoa_tho[:12]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_khoa_api.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Add rate limiter with a failing test**

```python
# thêm vào tests/core/test_khoa_api.py
from portal.core.khoa_api import gioi_han_nhip


async def test_gioi_han_nhip_cho_qua_roi_chan(redis_client):
    """10 lần đầu qua, lần 11 bị chặn."""
    khoa = "sha-test-1"
    for i in range(10):
        assert await gioi_han_nhip(redis_client, khoa, so_lan=10, giay=300) is True, f"lần {i + 1}"
    assert await gioi_han_nhip(redis_client, khoa, so_lan=10, giay=300) is False


async def test_gioi_han_nhip_tach_theo_khoa(redis_client):
    """Khoá A bị chặn không được kéo khoá B theo."""
    for _ in range(10):
        await gioi_han_nhip(redis_client, "sha-A", so_lan=10, giay=300)
    assert await gioi_han_nhip(redis_client, "sha-A", so_lan=10, giay=300) is False
    assert await gioi_han_nhip(redis_client, "sha-B", so_lan=10, giay=300) is True
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_khoa_api.py -v -k gioi_han`
Expected: FAIL — `ImportError: cannot import name 'gioi_han_nhip'`

- [ ] **Step 7: Implement the rate limiter**

```python
# thêm vào src/portal/core/khoa_api.py
from redis.asyncio import Redis

TIEN_TO_NHIP = "nhip:khoa:"


async def gioi_han_nhip(redis: Redis, sha_khoa: str, *, so_lan: int, giay: int) -> bool:
    """True = cho qua. False = vượt ngưỡng.

    Cửa sổ cố định, không trượt. Cửa sổ trượt chính xác hơn nhưng ở đây ta chống
    dò khoá chứ không chia băng thông công bằng — một cửa sổ 5 phút cho 10 lần
    là đủ, và nó rẻ hơn một bậc.

    Đếm theo BĂM của khoá, không theo khoá thô: Redis không phải chỗ để khoá thô
    đi qua, kể cả trong tên key.
    """
    key = f"{TIEN_TO_NHIP}{sha_khoa}"
    dem = await redis.incr(key)
    if dem == 1:
        await redis.expire(key, giay)
    return dem <= so_lan
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest tests/core/test_khoa_api.py -v`
Expected: 7 PASSED

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add src/portal/core/khoa_api.py tests/core/test_khoa_api.py
git commit -m "feat(m10): core/khoa_api — sinh · băm · giới hạn nhịp, dùng chung với M8 (T1)"
```

---

## Task 2: `bi_mat.py` — suy dẫn tất định

**Files:**
- Create: `src/portal/modules/enrollment/__init__.py` (rỗng)
- Create: `src/portal/modules/enrollment/bi_mat.py`
- Test: `tests/modules/enrollment/test_bi_mat.py`
- Create: `tests/modules/enrollment/__init__.py` (rỗng)

**Interfaces:**
- Consumes: chỉ stdlib
- Produces: `dan_xuat(loai: str, tenant_id: str, version: int, master: bytes) -> str` ·
  hằng `LOAI_PG = "pg"` · `LOAI_S3 = "s3"` · `DO_DAI_MASTER_TOI_THIEU = 32`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_bi_mat.py
"""Suy dẫn bí mật — HÀM THUẦN. Đây là phần dễ sai nhất của M10 và nó test được
không cần Postgres, MinIO hay Qdrant. Cùng lý do bundle.render() của M3 là hàm thuần."""

import re

import pytest

from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, dan_xuat

MASTER = b"x" * 32
MASTER_KHAC = b"y" * 32


def test_tat_dinh():
    """CỐT LÕI: hai pod của cùng tenant phải suy ra CÙNG mật khẩu.

    Nếu tính chất này vỡ, pod voice khởi động lại sẽ đá văng pod chat —
    vì portal.current_tenant() parse tenant TỪ TÊN ROLE nên hai pod dùng
    chung một role agent_<slug>. Xem spec §3.
    """
    a = dan_xuat(LOAI_PG, "anphu", 1, MASTER)
    b = dan_xuat(LOAI_PG, "anphu", 1, MASTER)
    assert a == b


def test_khac_loai_khac_ket_qua():
    """Mật khẩu Postgres và secret key S3 không được trùng nhau."""
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) != dan_xuat(LOAI_S3, "anphu", 1, MASTER)


def test_khac_tenant_khac_ket_qua():
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) != dan_xuat(LOAI_PG, "bcland", 1, MASTER)


def test_khac_version_khac_ket_qua():
    """Đây là cơ chế xoay khoá: tăng version là đổi mật khẩu."""
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) != dan_xuat(LOAI_PG, "anphu", 2, MASTER)


def test_khac_master_khac_ket_qua():
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) != dan_xuat(LOAI_PG, "anphu", 1, MASTER_KHAC)


def test_dinh_dang_dung_duoc_lam_mat_khau():
    """base64url không padding: an toàn trong DSN, trong policy JSON, trong shell."""
    ra = dan_xuat(LOAI_PG, "anphu", 1, MASTER)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", ra), ra


def test_khong_tach_duoc_truong_bang_dau_hai_cham():
    """('a','b:c') và ('a:b','c') phải cho kết quả KHÁC nhau.

    Nếu nối chuỗi ngây thơ f"{loai}:{tenant}:{version}" thì tenant_id chứa dấu
    hai chấm sẽ va vào không gian của tenant khác. tenant_id được regex chặn ở
    create_agent_role() nên chuyện này không xảy ra hôm nay — nhưng hàm thuần
    không được dựa vào một ràng buộc nằm ở file khác.
    """
    assert dan_xuat("pg", "a:b", 1, MASTER) != dan_xuat("pg:a", "b", 1, MASTER)


def test_master_qua_ngan_bi_tu_choi():
    with pytest.raises(ValueError, match="32 byte"):
        dan_xuat(LOAI_PG, "anphu", 1, b"ngan")


def test_loai_la_bi_tu_choi():
    """Gõ sai 'pgg' không được âm thầm sinh ra một mật khẩu hợp lệ khác."""
    with pytest.raises(ValueError, match="loai"):
        dan_xuat("pgg", "anphu", 1, MASTER)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_bi_mat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.enrollment'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/portal/modules/enrollment/bi_mat.py
"""Suy dẫn bí mật tất định — HÀM THUẦN, không I/O.

VÌ SAO SUY DẪN CHỨ KHÔNG LƯU: portal.current_tenant() (0001_schemas_and_functions.py:41)
parse tenant TỪ TÊN ROLE bằng regex '^agent_(.+)$'. Nên mỗi tenant có ĐÚNG MỘT role
`agent_<slug>`, dùng chung cho pod chat lẫn pod voice — không tách role theo deployment
được, vì `agent_anphu_chat` sẽ parse ra tenant `anphu_chat` không tồn tại.

Hệ quả: đổi mật khẩu mỗi lần bootstrap là pod voice đá văng pod chat. Nên hai pod
phải suy ra CÙNG một mật khẩu. Suy dẫn tất định làm được điều đó mà không cần lưu
bí mật nào trong DB — portal chỉ lưu `secret_version`, một int.

Xoay khoá = tăng version + ALTER ROLE + MinioAdmin.user_add. Kết nối đang mở KHÔNG
đứt: Postgres chỉ hỏi mật khẩu lúc nối mới.
"""

import base64
import hashlib
import hmac
from typing import Final

LOAI_PG: Final = "pg"
LOAI_S3: Final = "s3"
_LOAI_HOP_LE: Final = frozenset({LOAI_PG, LOAI_S3})

DO_DAI_MASTER_TOI_THIEU: Final = 32
"""256 bit. Khoá gốc ngắn hơn là hạ toàn bộ hệ xuống mức đó."""


def dan_xuat(loai: str, tenant_id: str, version: int, master: bytes) -> str:
    """Trả chuỗi base64url 43 ký tự, dùng làm mật khẩu Postgres hoặc secret key S3.

    Thông điệp HMAC dùng ĐỘ DÀI CÓ TIỀN TỐ chứ không nối bằng dấu hai chấm:
    f"{loai}:{tenant}:{ver}" cho ('pg','a:b') và ('pg:a','b') ra cùng chuỗi, tức
    hai tenant khác nhau có thể suy ra cùng mật khẩu. Hôm nay regex của
    create_agent_role() chặn tenant_id có dấu hai chấm — nhưng hàm thuần không
    được dựa vào một ràng buộc nằm ở file khác.
    """
    if loai not in _LOAI_HOP_LE:
        raise ValueError(f"loai phải thuộc {sorted(_LOAI_HOP_LE)}, nhận {loai!r}")
    if len(master) < DO_DAI_MASTER_TOI_THIEU:
        raise ValueError(f"khoá gốc phải từ {DO_DAI_MASTER_TOI_THIEU} byte, nhận {len(master)}")

    phan = [loai.encode(), tenant_id.encode(), str(version).encode()]
    thong_diep = b"".join(len(p).to_bytes(4, "big") + p for p in phan)
    dau = hmac.new(master, thong_diep, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(dau).decode().rstrip("=")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/modules/enrollment/test_bi_mat.py -v`
Expected: 9 PASSED

- [ ] **Step 5: Lint and commit**

```bash
make lint
git add src/portal/modules/enrollment/ tests/modules/enrollment/
git commit -m "feat(m10): bi_mat.dan_xuat — HMAC tất định, hai pod cùng mật khẩu (T2)"
```

---

## Task 3: Migration `0900` — hai bảng

**Files:**
- Create: `migrations/versions/0900_agent_enrollment.py`
- Test: `tests/modules/enrollment/test_migration_0900.py`

**Interfaces:**
- Consumes: `control.deployments` (M3, migration `0200`) · `control.tenants` (M1, `0002`)
- Produces: bảng `control.agent_keys` · `control.agent_credentials`

**Trước khi viết:** chạy `.venv/bin/alembic heads` để lấy revision hiện tại và đặt vào
`down_revision`. Dải `0900`–`0999` là của M10 (spec tổng §4④). **Không** đoán — M4a vừa thêm `0400`
và `0401`.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_migration_0900.py
"""Migration 0900 — hai bảng hẹp cho đấu nối agent."""

import pytest


async def test_agent_keys_co_du_cot(pool):
    rows = await pool.fetch(
        """SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_schema='control' AND table_name='agent_keys'"""
    )
    cot = {r["column_name"]: r["is_nullable"] for r in rows}
    assert set(cot) == {
        "id", "deployment_id", "key_sha256", "key_prefix",
        "label", "created_at", "created_by", "revoked_at", "last_used_at",
    }
    assert cot["key_sha256"] == "NO"
    assert cot["deployment_id"] == "NO"
    assert cot["revoked_at"] == "YES", "khoá còn sống thì cột này NULL"


async def test_key_sha256_la_unique(pool):
    """Hai hàng cùng băm là hai deployment mạo danh nhau được."""
    idx = await pool.fetch(
        """SELECT indexdef FROM pg_indexes
            WHERE schemaname='control' AND tablename='agent_keys'"""
    )
    assert any("UNIQUE" in r["indexdef"] and "key_sha256" in r["indexdef"] for r in idx), idx


async def test_xoa_deployment_keo_theo_khoa(pool, tenant_anphu):
    """ON DELETE CASCADE: gỡ pod là mọi khoá của nó chết theo, không còn khoá mồ côi."""
    dep = await pool.fetchval(
        "INSERT INTO control.deployments (tenant_id, kind) VALUES ($1,'chat') RETURNING id",
        tenant_anphu,
    )
    await pool.execute(
        "INSERT INTO control.agent_keys (deployment_id, key_sha256, key_prefix) VALUES ($1,'sha-x','ody_ag_aaaa')",
        dep,
    )
    await pool.execute("DELETE FROM control.deployments WHERE id=$1", dep)
    assert await pool.fetchval("SELECT count(*) FROM control.agent_keys WHERE deployment_id=$1", dep) == 0


async def test_agent_credentials_mac_dinh_version_1(pool, tenant_anphu):
    await pool.execute("INSERT INTO control.agent_credentials (tenant_id) VALUES ($1)", tenant_anphu)
    v = await pool.fetchval("SELECT secret_version FROM control.agent_credentials WHERE tenant_id=$1", tenant_anphu)
    assert v == 1


async def test_agent_khong_doc_duoc_hai_bang(pool):
    """Pod agent KHÔNG được SELECT bảng khoá — nó chỉ cần credential của chính nó,
    và nó đã nhận qua bootstrap. Cấp SELECT ở đây là cho một pod đọc băm khoá của pod khác."""
    for bang in ("agent_keys", "agent_credentials"):
        co = await pool.fetchval(
            "SELECT has_table_privilege('agent_all', $1, 'SELECT')", f"control.{bang}"
        )
        assert co is False, f"agent_all không được SELECT control.{bang}"
```

Thêm fixture vào `tests/modules/enrollment/conftest.py`:

```python
# tests/modules/enrollment/conftest.py
"""Fixture dùng chung cho test M10."""

import pytest


@pytest.fixture
async def tenant_anphu(pool) -> str:
    """Một tenant có thật — FK của deployments và agent_credentials cần nó."""
    await pool.execute(
        "INSERT INTO control.tenants (id, name) VALUES ('anphu','An Phú Land') ON CONFLICT DO NOTHING"
    )
    return "anphu"
```

> **Kiểm trước khi chạy:** mở `migrations/versions/0002_control_core.py` xem `control.tenants` có
> đúng hai cột `id` · `name` bắt buộc không. Nếu có cột `NOT NULL` khác thì bổ sung vào `INSERT` của
> fixture — đừng đổi bảng.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_migration_0900.py -v`
Expected: FAIL — `relation "control.agent_keys" does not exist`

- [ ] **Step 3: Write the migration**

```python
# migrations/versions/0900_agent_enrollment.py
"""control.agent_keys + control.agent_credentials — đấu nối pod agent ngoài

VÌ SAO HAI BẢNG HẸP CHỨ KHÔNG THÊM CỘT VÀO deployments: cùng lý do
0007_agent_heartbeats.py viết ra. `agent_keys.last_used_at` bị ghi mỗi lần
bootstrap; `deployments` là hồ sơ triển khai và có FK từ agent_heartbeats trỏ
vào. Một bảng bị ghi thường xuyên không nên là neo danh tính của thứ khác.

VÌ SAO agent_credentials CHỈ CÓ MỘT SỐ NGUYÊN: bí mật được SUY DẪN từ
AGENT_MASTER_KEY (modules/enrollment/bi_mat.py), không lưu. Bảng này giữ đúng
`secret_version` để biết đang ở thế hệ nào. Một SELECT trên toàn schema control
không lộ được mật khẩu nào.

VÌ SAO KHÔNG CẤP QUYỀN CHO agent_all: pod đã nhận credential của nó qua
bootstrap. Cho nó SELECT bảng này là cho một pod đọc băm khoá của pod khác —
băm không dùng để mạo danh được, nhưng nó là dữ liệu vận hành của tenant khác
và không có lý do gì để lộ.

VÌ SAO KHÔNG RLS: cả hai bảng là control plane, chỉ portal_api đọc. Ngoại lệ RLS
duy nhất trong schema control vẫn là agent_heartbeats (0007), vì đó là bảng
control DUY NHẤT mà agent được ghi.

Revision ID: 0900_enrollment
"""

from alembic import op

revision = "0900_enrollment"
down_revision = "0401_agent_api_full"  # ⚠️ THAY bằng output thật của `alembic heads`
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.agent_keys (
            id            bigserial PRIMARY KEY,
            deployment_id bigint      NOT NULL REFERENCES control.deployments(id) ON DELETE CASCADE,
            key_sha256    text        NOT NULL UNIQUE,
            key_prefix    text        NOT NULL,
            label         text        NOT NULL DEFAULT '',
            created_at    timestamptz NOT NULL DEFAULT now(),
            created_by    text        NOT NULL DEFAULT '',
            revoked_at    timestamptz,
            last_used_at  timestamptz
        )
        """
    )
    # Bootstrap tra theo băm — đây là truy vấn nóng nhất của module.
    # UNIQUE ở trên đã sinh index; không thêm index thứ hai trên cùng cột.
    op.execute("CREATE INDEX agent_keys_deployment_idx ON control.agent_keys (deployment_id)")

    op.execute(
        """
        CREATE TABLE control.agent_credentials (
            tenant_id      text        PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
            secret_version integer     NOT NULL DEFAULT 1 CHECK (secret_version >= 1),
            rotated_at     timestamptz NOT NULL DEFAULT now(),
            rotated_by     text        NOT NULL DEFAULT ''
        )
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.agent_keys TO portal_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.agent_credentials TO portal_api")
    op.execute("GRANT USAGE ON SEQUENCE control.agent_keys_id_seq TO portal_api")


def downgrade() -> None:
    op.execute("DROP TABLE control.agent_credentials")
    op.execute("DROP TABLE control.agent_keys")
```

- [ ] **Step 4: Fix `down_revision`, then run the migration**

```bash
.venv/bin/alembic heads          # lấy revision thật
# sửa down_revision trong 0900_agent_enrollment.py cho khớp
make migrate
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/modules/enrollment/test_migration_0900.py -v`
Expected: 5 PASSED

- [ ] **Step 6: Verify downgrade works**

```bash
.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```
Expected: cả hai lệnh xanh, không lỗi dependency

- [ ] **Step 7: Run the M1 isolation gates**

Run: `make test-isolation`
Expected: PASS — cổng 6 quét `control` không được đỏ vì hai bảng mới

- [ ] **Step 8: Declare the two tables in the isolation catalog**

Mở `docs/contracts/isolation.md §6.0` và thêm hai dòng vào danh sách bảng `control` được khai báo:

```markdown
| `control.agent_keys` | Control plane. `tenant_id` gián tiếp qua `deployment_id`. Chỉ `portal_api` đọc; `agent_all` KHÔNG có quyền nào |
| `control.agent_credentials` | Control plane. Giữ `secret_version`, không giữ bí mật. Chỉ `portal_api` |
```

> Nếu cổng 6 (`test_isolation_catalog.py`) đọc một danh sách trong **code** chứ không trong
> markdown, thêm hai tên bảng vào đúng danh sách đó. Chạy `grep -rn "agent_heartbeats"
> tests/isolation/` để tìm chỗ M1 khai `agent_heartbeats` và làm y hệt.

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add migrations/versions/0900_agent_enrollment.py tests/modules/enrollment/ docs/contracts/isolation.md
git commit -m "feat(m10): migration 0900 — agent_keys + agent_credentials, agent_all zero quyền (T3)"
```

---

## Task 4: Cấu hình và cổng quản trị nền tảng

**Files:**
- Modify: `src/portal/core/config.py`
- Create: `src/portal/core/auth/quan_tri_nen_tang.py`
- Create: `src/portal/modules/enrollment/loi.py`
- Test: `tests/core/test_quan_tri_nen_tang.py`

**Interfaces:**
- Consumes: `Settings` từ `portal.core.config`
- Produces: `Settings.agent_master_key: str` · `Settings.platform_admin_token: str` ·
  `Settings.bootstrap_ttl_seconds: int` · `Settings.master_key_bytes() -> bytes` ·
  `require_quan_tri_nen_tang` (FastAPI dependency) · `loi.khoa_agent_khong_hop_le()` và 4 hằng khác

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_quan_tri_nen_tang.py
"""Cổng quản trị nền tảng — XUYÊN TENANT, ngoài 13 action của PQ_01."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.api.loi import LoiPortal
from portal.core.auth.quan_tri_nen_tang import require_quan_tri_nen_tang


def _app(token: str) -> TestClient:
    import portal.core.auth.quan_tri_nen_tang as m

    app = FastAPI()

    @app.get("/thu")
    async def thu(_: None = require_quan_tri_nen_tang()):
        return {"ok": True}

    @app.exception_handler(LoiPortal)
    async def _h(_req, exc: LoiPortal):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": {"code": exc.ma, "message": exc.thong_diep}}, status_code=exc.http)

    m._TOKEN_TEST = token  # noqa: SLF001
    return TestClient(app)


def test_token_dung_thi_qua(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "t" * 32)
    from portal.core.config import get_settings

    get_settings.cache_clear()
    c = _app("t" * 32)
    r = c.get("/thu", headers={"X-Platform-Admin-Token": "t" * 32})
    assert r.status_code == 200


def test_thieu_header_thi_401(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "t" * 32)
    from portal.core.config import get_settings

    get_settings.cache_clear()
    r = _app("t" * 32).get("/thu")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_ADMIN_TOKEN"


def test_token_sai_thi_401_cung_cau_chu(monkeypatch):
    """Thiếu header và sai token phải trả CÙNG message — khác message là máy dò
    phân biệt được 'có cấu hình token' với 'token sai'."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "t" * 32)
    from portal.core.config import get_settings

    get_settings.cache_clear()
    c = _app("t" * 32)
    thieu = c.get("/thu").json()["error"]
    sai = c.get("/thu", headers={"X-Platform-Admin-Token": "sai"}).json()["error"]
    assert thieu == sai


def test_khong_them_action_nao():
    """M10 KHÔNG được chạm 13 nhóm của PQ_01."""
    from portal.core.auth.actions import ALL_ACTIONS

    assert len(ALL_ACTIONS) == 13
    assert not any("platform" in a for a in ALL_ACTIONS)
```

Và một test cho `Settings`:

```python
# tests/core/test_config_m10.py
"""AGENT_MASTER_KEY là bí mật hạng cao nhất — app phải từ chối khởi động nếu nó yếu."""

import pytest

from portal.core.config import Settings


def test_master_key_ngan_bi_tu_choi():
    s = Settings(agent_master_key="ngan", environment="production")
    with pytest.raises(ValueError, match="AGENT_MASTER_KEY"):
        s.master_key_bytes()


def test_master_key_rong_bi_tu_choi_o_production():
    s = Settings(agent_master_key="", environment="production")
    with pytest.raises(ValueError, match="AGENT_MASTER_KEY"):
        s.master_key_bytes()


def test_dev_co_mac_dinh_dung_duoc():
    """Dev không phải đặt biến môi trường mới chạy được `make up`."""
    s = Settings(environment="development")
    assert len(s.master_key_bytes()) >= 32
```

> **Kiểm trước khi viết:** `Settings` hiện có trường `environment` không? Chạy
> `grep -n environment src/portal/core/config.py`. Nếu chưa có, thêm
> `environment: str = "development"` cùng lúc — nó cần cho ba test trên và cho §2.1 của spec.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/core/test_quan_tri_nen_tang.py tests/core/test_config_m10.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.core.auth.quan_tri_nen_tang`

- [ ] **Step 3: Extend `Settings`**

```python
# thêm vào class Settings trong src/portal/core/config.py

    environment: str = "development"
    """development | production. Quyết định app có từ chối khởi động khi bí mật yếu không."""

    agent_master_key: str = ""
    """Khoá gốc suy dẫn mọi credential agent (modules/enrollment/bi_mat.py).

    BÍ MẬT HẠNG CAO NHẤT TRONG HỆ. Rò nó là suy được credential của MỌI tenant.
    Không có giá trị mặc định ở production; dev dùng khoá cố định để `make up` chạy được.
    Đổi nó = mọi tenant phải xoay bí mật.
    """

    platform_admin_token: str = ""
    """Token cho route /admin/* của M10. TẠM THỜI — M2b sẽ thay bằng vai trò thật.

    Không dùng ACTIONS: 13 nhóm của PQ_01 là quyền TRONG một workspace, còn admin
    nền tảng hành động xuyên tenant. Xem spec M10 §4.
    """

    bootstrap_ttl_seconds: int = 3600
    """TTL của credential trả về từ bootstrap. Pod tự làm mới trước khi hết."""

    def master_key_bytes(self) -> bytes:
        """Khoá gốc dạng bytes. Ném ValueError nếu nó không đủ mạnh ở production.

        Ném lúc GỌI chứ không phải lúc dựng Settings: `Settings()` được dựng trong
        test và trong script với đủ loại cấu hình, và một validator cứng ở đó làm
        mọi thứ không liên quan cũng vỡ. Chỗ duy nhất cần khoá mạnh là chỗ dùng nó.
        """
        from portal.modules.enrollment.bi_mat import DO_DAI_MASTER_TOI_THIEU

        if self.environment == "development" and not self.agent_master_key:
            return b"dev-master-key-khong-dung-o-production-32b"
        raw = self.agent_master_key.encode()
        if len(raw) < DO_DAI_MASTER_TOI_THIEU:
            raise ValueError(
                f"AGENT_MASTER_KEY phải từ {DO_DAI_MASTER_TOI_THIEU} byte, nhận {len(raw)}. "
                f"Sinh bằng: python -c 'import secrets;print(secrets.token_urlsafe(32))'"
            )
        return raw
```

- [ ] **Step 4: Write the error constants**

```python
# src/portal/modules/enrollment/loi.py
"""Năm lỗi của M10. Theo auth.md: module raise LoiPortal, không tự trả JSON."""

from portal.api.loi import LoiPortal

_KHOA_KHONG_HOP_LE = "Khoá đấu nối không hợp lệ"
"""MỘT câu chữ cho cả bốn nhánh: thiếu header · sai định dạng · không khớp · đã thu hồi.

Khác message là máy dò chỉ cần đọc message để biết khoá nào có thật — cùng lý do
ba mã 401/403 của M2a dùng cùng câu chữ (auth.md).
"""


def khoa_agent_khong_hop_le() -> LoiPortal:
    return LoiPortal("INVALID_AGENT_KEY", 401, _KHOA_KHONG_HOP_LE)


def token_quan_tri_khong_hop_le() -> LoiPortal:
    return LoiPortal("INVALID_ADMIN_TOKEN", 401, "Token quản trị nền tảng không hợp lệ")


def tenant_bi_tam_ngung(tenant_id: str) -> LoiPortal:
    return LoiPortal("TENANT_SUSPENDED", 403, f"Workspace {tenant_id} đang tạm ngưng")


def vuot_gioi_han_nhip() -> LoiPortal:
    return LoiPortal("RATE_LIMITED", 429, "Quá nhiều lần đấu nối. Thử lại sau ít phút")


def chua_cap_phat(thieu: str) -> LoiPortal:
    return LoiPortal("NOT_PROVISIONED", 409, f"Deployment chưa cấp phát xong: thiếu {thieu}")
```

- [ ] **Step 5: Write the platform admin gate**

```python
# src/portal/core/auth/quan_tri_nen_tang.py
"""Cổng quản trị NỀN TẢNG — xuyên tenant, ngoài 13 nhóm của PQ_01.

VÌ SAO KHÔNG DÙNG ACTIONS: 13 nhóm của PQ_01 §3.1 là quyền TRONG một workspace.
`Principal` mang `tenant_id`; `require()` trả về một Principal đã gắn workspace.
Admin nền tảng hành động XUYÊN tenant — họ không có tenant_id để mang. Và M2a
phát cả 13 action cho MỌI user, nên thêm 'platform_admin.manage' vào đó là phát
quyền quản trị nền tảng cho mọi người dùng workspace. Ba test khoá cứng con số 13
sẽ đỏ, và chúng đỏ ĐÚNG.

TẠM THỜI: một token tĩnh trong env. Hệ quả đã biết — không biết ai đang gọi, nên
audit_log.actor ghi "platform_admin" chứ không ghi tên người. Khi M2b chốt vai trò
thật, hàm này đổi RUỘT và giữ nguyên CHỮ KÝ, nên không route nào phải sửa.
"""

import hmac
from typing import Annotated, Any

from fastapi import Depends, Header

from portal.core.config import get_settings
from portal.modules.enrollment import loi

ACTOR_QUAN_TRI = "platform_admin"
"""Ghi vào audit_log.actor. Chưa biết người thật — xem docstring module."""


async def _kiem_token(x_platform_admin_token: Annotated[str, Header()] = "") -> None:
    c = get_settings()
    mong_doi = c.platform_admin_token
    if c.environment == "production" and len(mong_doi) < 32:
        raise RuntimeError(
            "PLATFORM_ADMIN_TOKEN phải từ 32 ký tự ở production. "
            "Sinh bằng: python -c 'import secrets;print(secrets.token_urlsafe(32))'"
        )
    # compare_digest cả khi header rỗng: thoát sớm là để lộ độ dài qua thời gian.
    if not mong_doi or not hmac.compare_digest(x_platform_admin_token, mong_doi):
        raise loi.token_quan_tri_khong_hop_le()


def require_quan_tri_nen_tang() -> Any:
    """Dùng làm default của tham số endpoint:

        async def tao(_: None = require_quan_tri_nen_tang()): ...

    Route vẫn PHẢI khai thêm `require(None, ly_do=...)` để qua cổng
    test_moi_route_khai_action.py của M2a. Hai thứ khác nhau: require(None) nói
    "route này cố ý không dùng action"; hàm này nói "nhưng nó vẫn có cổng riêng".
    """
    return Depends(_kiem_token)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/core/test_quan_tri_nen_tang.py tests/core/test_config_m10.py -v`
Expected: 7 PASSED

- [ ] **Step 7: Verify the 13-action gate is still green**

Run: `.venv/bin/pytest tests/api/test_actions.py tests/api/test_contracts.py tests/modules/auth/test_login.py -v`
Expected: PASS — con số 13 không đổi

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add src/portal/core/config.py src/portal/core/auth/quan_tri_nen_tang.py \
        src/portal/modules/enrollment/loi.py tests/core/
git commit -m "feat(m10): cổng quản trị nền tảng ngoài 13 action + AGENT_MASTER_KEY (T4)"
```

---

## Task 5: `repo.py` — SQL trên hai bảng mới

**Files:**
- Create: `src/portal/modules/enrollment/repo.py`
- Create: `src/portal/modules/enrollment/contracts.py`
- Test: `tests/modules/enrollment/test_repo.py`

**Interfaces:**
- Consumes: `pool` (asyncpg), bảng của Task 3
- Produces:
  - `contracts.KhoaHopLe` (dataclass: `deployment_id: int`, `tenant_id: str`, `kind: str`)
  - `repo.tra_khoa(conn, sha: str) -> KhoaHopLe | None` — **chỉ** trả khoá chưa thu hồi
  - `repo.them_khoa(conn, deployment_id: int, sha: str, prefix: str, label: str, boi: str) -> int`
  - `repo.thu_hoi_khoa(conn, key_id: int) -> bool`
  - `repo.cham_last_used(conn, sha: str) -> None`
  - `repo.them_deployment(conn, tenant_id: str, kind: str) -> int`
  - `repo.liet_ke_deployment(conn) -> list[dict]` — **dict thô, không phải `DeploymentOut`.**
    Repo không dựng model: `DeploymentOut` cần `san_sang_du_lieu` mà repo không có cách lấy
    (nó nằm ở `tenant_data`, cần `tenant_conn`). `service.py` ghép hai nguồn — Task 8 Step 4.
  - `repo.doc_version(conn, tenant_id: str) -> int` — tạo hàng với version 1 nếu chưa có
  - `repo.tang_version(conn, tenant_id: str, boi: str) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_repo.py
"""Repo M10 — bảng control, pool trực tiếp, KHÔNG tenant_conn().

Lý do không tenant_conn: giống modules/config/repo.py:6. Bảng control không có
RLS (trừ agent_heartbeats), và admin nền tảng đọc xuyên tenant.
"""

import pytest

from portal.modules.enrollment import repo


@pytest.fixture
async def dep_chat(pool, tenant_anphu) -> int:
    return await repo.them_deployment(pool, tenant_anphu, "chat")


async def test_tra_khoa_tra_ve_tenant_va_deployment(pool, dep_chat, tenant_anphu):
    await repo.them_khoa(pool, dep_chat, "sha-1", "ody_ag_aaaa", "pod chat", "platform_admin")
    ra = await repo.tra_khoa(pool, "sha-1")
    assert ra is not None
    assert ra.tenant_id == tenant_anphu
    assert ra.deployment_id == dep_chat
    assert ra.kind == "chat"


async def test_tra_khoa_khong_thay_thi_None(pool):
    assert await repo.tra_khoa(pool, "sha-khong-co") is None


async def test_khoa_da_thu_hoi_coi_nhu_khong_ton_tai(pool, dep_chat):
    """CỐT LÕI của cổng 2: thu hồi phải làm khoá BIẾN MẤT khỏi đường tra,
    không phải trả về một hàng có cờ để service nhớ kiểm."""
    kid = await repo.them_khoa(pool, dep_chat, "sha-2", "ody_ag_bbbb", "", "platform_admin")
    assert await repo.tra_khoa(pool, "sha-2") is not None
    assert await repo.thu_hoi_khoa(pool, kid) is True
    assert await repo.tra_khoa(pool, "sha-2") is None


async def test_thu_hoi_lan_hai_tra_False(pool, dep_chat):
    kid = await repo.them_khoa(pool, dep_chat, "sha-3", "ody_ag_cccc", "", "platform_admin")
    assert await repo.thu_hoi_khoa(pool, kid) is True
    assert await repo.thu_hoi_khoa(pool, kid) is False


async def test_cham_last_used(pool, dep_chat):
    await repo.them_khoa(pool, dep_chat, "sha-4", "ody_ag_dddd", "", "platform_admin")
    assert await pool.fetchval("SELECT last_used_at FROM control.agent_keys WHERE key_sha256='sha-4'") is None
    await repo.cham_last_used(pool, "sha-4")
    assert await pool.fetchval("SELECT last_used_at FROM control.agent_keys WHERE key_sha256='sha-4'") is not None


async def test_doc_version_tao_hang_neu_chua_co(pool, tenant_anphu):
    """Tenant chưa từng cấp phát vẫn phải đọc được version — mặc định 1."""
    assert await repo.doc_version(pool, tenant_anphu) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM control.agent_credentials WHERE tenant_id=$1", tenant_anphu
    ) == 1


async def test_doc_version_hai_lan_khong_tao_hai_hang(pool, tenant_anphu):
    await repo.doc_version(pool, tenant_anphu)
    await repo.doc_version(pool, tenant_anphu)
    assert await pool.fetchval(
        "SELECT count(*) FROM control.agent_credentials WHERE tenant_id=$1", tenant_anphu
    ) == 1


async def test_tang_version(pool, tenant_anphu):
    assert await repo.doc_version(pool, tenant_anphu) == 1
    assert await repo.tang_version(pool, tenant_anphu, "platform_admin") == 2
    assert await repo.doc_version(pool, tenant_anphu) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.enrollment.repo`

- [ ] **Step 3: Write contracts**

```python
# src/portal/modules/enrollment/contracts.py
"""Hình dạng dữ liệu của M10. NGUỒN SỰ THẬT DUY NHẤT — FE lấy type qua
contracts/openapi.json theo nếp M2a (BE sinh, FE sao)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["chat", "voice"]


@dataclass(frozen=True)
class KhoaHopLe:
    """Kết quả tra khoá. Chỉ tồn tại cho khoá CHƯA thu hồi — repo.tra_khoa lọc sẵn."""

    deployment_id: int
    tenant_id: str
    kind: str


class KhoTepOut(BaseModel):
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    prefix: str


class KbOut(BaseModel):
    url: str
    collection: str


class BootstrapOut(BaseModel):
    """⚠️ CHỨA MẬT KHẨU. Cấm log, cấm trace, cấm đưa vào APM span (G-10)."""

    tenant_id: str
    deployment_id: int
    kind: Kind
    postgres_dsn: str
    storage: KhoTepOut
    kb: KbOut
    live_url: str
    expires_at: datetime


class SanSangDuLieu(BaseModel):
    """Chẩn đoán, ĐỌC THUẦN. Không lưu thành trạng thái — spec §5.1.

    Cấp phát xong không có nghĩa agent nói được. field_policy_live rỗng ⇒
    portal.pol() trả false cho mọi trường ⇒ agent tư vấn bằng payload toàn NULL.
    """

    field_policy_rows: int
    projects_agent_enabled: int
    kb_chunks: int


class DeploymentIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    kind: Kind


class DeploymentOut(BaseModel):
    id: int
    tenant_id: str
    kind: Kind
    endpoint: str
    provisioned_at: datetime
    so_khoa_con_song: int
    san_sang_du_lieu: SanSangDuLieu


class KhoaMoiOut(BaseModel):
    """Khoá thô xuất hiện ĐÚNG MỘT LẦN, ở đây. Không đường nào đọc lại được."""

    id: int
    api_key: str
    key_prefix: str
```

- [ ] **Step 4: Write repo**

```python
# src/portal/modules/enrollment/repo.py
"""SQL thô trên control.agent_keys · agent_credentials · deployments.

KHÔNG dùng tenant_conn(): cả ba bảng ở schema `control`, không có RLS, và admin
nền tảng đọc xuyên tenant. Cùng lý do đã ghi ở modules/config/repo.py:6.
"""

import asyncpg

from portal.modules.enrollment.contracts import KhoaHopLe


async def them_deployment(conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str, kind: str) -> int:
    return await conn.fetchval(
        "INSERT INTO control.deployments (tenant_id, kind) VALUES ($1, $2) RETURNING id",
        tenant_id,
        kind,
    )


async def tra_khoa(conn: asyncpg.Connection | asyncpg.Pool, sha: str) -> KhoaHopLe | None:
    """Tra khoá theo băm. Khoá ĐÃ THU HỒI trả về None.

    Lọc `revoked_at IS NULL` NGAY TRONG SQL chứ không trả cờ cho service kiểm:
    một chỗ quên kiểm cờ là một khoá đã thu hồi vẫn dùng được, và lỗi đó im lặng.
    """
    r = await conn.fetchrow(
        """
        SELECT k.deployment_id, d.tenant_id, d.kind
          FROM control.agent_keys k
          JOIN control.deployments d ON d.id = k.deployment_id
         WHERE k.key_sha256 = $1 AND k.revoked_at IS NULL
        """,
        sha,
    )
    return KhoaHopLe(r["deployment_id"], r["tenant_id"], r["kind"]) if r else None


async def them_khoa(
    conn: asyncpg.Connection | asyncpg.Pool,
    deployment_id: int,
    sha: str,
    prefix: str,
    label: str,
    boi: str,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO control.agent_keys (deployment_id, key_sha256, key_prefix, label, created_by)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        deployment_id,
        sha,
        prefix,
        label,
        boi,
    )


async def thu_hoi_khoa(conn: asyncpg.Connection | asyncpg.Pool, key_id: int) -> bool:
    """True nếu vừa thu hồi. False nếu không có hàng nào, hoặc đã thu hồi từ trước.

    `revoked_at IS NULL` trong WHERE làm thao tác idempotent mà vẫn phân biệt được
    'vừa thu hồi' với 'đã thu hồi rồi' — admin bấm hai lần không nên thấy lỗi,
    nhưng cũng không nên thấy 'đã thu hồi' hai lần trong nhật ký.
    """
    ra = await conn.execute(
        "UPDATE control.agent_keys SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        key_id,
    )
    return ra.endswith(" 1")


async def cham_last_used(conn: asyncpg.Connection | asyncpg.Pool, sha: str) -> None:
    await conn.execute("UPDATE control.agent_keys SET last_used_at = now() WHERE key_sha256 = $1", sha)


async def doc_version(conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str) -> int:
    """Đọc secret_version, tạo hàng mặc định 1 nếu tenant chưa từng cấp phát.

    Tạo-nếu-thiếu ở đây chứ không bắt caller nhớ: mọi đường đọc version đều cần
    một hàng tồn tại, và quên tạo là bootstrap ném lỗi trên một tenant hợp lệ.
    """
    return await conn.fetchval(
        """
        INSERT INTO control.agent_credentials (tenant_id) VALUES ($1)
        ON CONFLICT (tenant_id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id
        RETURNING secret_version
        """,
        tenant_id,
    )


async def tang_version(conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str, boi: str) -> int:
    return await conn.fetchval(
        """
        INSERT INTO control.agent_credentials (tenant_id, secret_version, rotated_by)
        VALUES ($1, 2, $2)
        ON CONFLICT (tenant_id) DO UPDATE
            SET secret_version = control.agent_credentials.secret_version + 1,
                rotated_at = now(), rotated_by = EXCLUDED.rotated_by
        RETURNING secret_version
        """,
        tenant_id,
        boi,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/modules/enrollment/test_repo.py -v`
Expected: 8 PASSED

- [ ] **Step 6: Lint and commit**

```bash
make lint
git add src/portal/modules/enrollment/repo.py src/portal/modules/enrollment/contracts.py \
        tests/modules/enrollment/test_repo.py
git commit -m "feat(m10): repo + contracts — thu hồi lọc trong SQL, không trả cờ (T5)"
```

---

## Task 6: `ha_tang_ngoai.py` — cấp phát role · khoá MinIO · collection

**Files:**
- Create: `src/portal/modules/enrollment/ha_tang_ngoai.py`
- Test: `tests/modules/enrollment/test_ha_tang_ngoai.py`

**Interfaces:**
- Consumes: `portal.core.storage.chinh_sach_tien_to` · `portal.core.ten_tai_nguyen.ten_role_agent`,
  `ten_khoa_truy_cap`, `ten_collection` · `bi_mat.dan_xuat`
- Produces: `class HaTangNgoai` với `async dat_mat_khau_role(conn, tenant_id, mat_khau)` ·
  `dat_khoa_kho_tep(tenant_id, secret)` · `async tao_collection_neu_thieu(tenant_id)` ·
  `async thieu_gi(conn, tenant_id) -> str` (chuỗi rỗng = đủ)

**Vì sao một class chứ không bốn hàm rời:** `service.py` cần thay được cả cụm bằng một fake trong
test unit. Bốn hàm module-level phải monkeypatch bốn chỗ; một class thì tiêm một tham số.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_ha_tang_ngoai.py
"""Cấp phát hạ tầng — idempotent, gọi lại nhiều lần cho cùng kết quả.

Cấp phát chạm bốn hệ và KHÔNG thể nằm trong một transaction (ba trong bốn ở
ngoài Postgres). Nên nó phải chịu được gọi lại: hỏng giữa chừng thì admin bấm
lại là xong. Xem spec §5.
"""

import pytest

from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai


@pytest.fixture
def ha_tang(minio_endpoint, qdrant_url):
    return HaTangNgoai.tu_cai_dat()


async def test_dat_mat_khau_role_tao_role_neu_chua_co(pool, tenant_anphu, ha_tang):
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "mk-1" + "x" * 40)
    assert await pool.fetchval("SELECT 1 FROM pg_roles WHERE rolname='agent_anphu'") == 1


async def test_dat_mat_khau_role_goi_lai_khong_vo(pool, tenant_anphu, ha_tang):
    """Role đã có ⇒ ALTER, không CREATE. Đây là nhánh chạy ở MỌI lần xoay khoá."""
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "mk-1" + "x" * 40)
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "mk-2" + "y" * 40)
    assert await pool.fetchval("SELECT 1 FROM pg_roles WHERE rolname='agent_anphu'") == 1


async def test_mat_khau_moi_dang_nhap_duoc_mat_khau_cu_thi_khong(pool, tenant_anphu, ha_tang, api_dsn, dsn_as):
    """Cổng 4 của spec — xoay khoá phải có tác dụng thật."""
    import asyncpg

    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "cu" + "a" * 40)
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "moi" + "b" * 40)

    c = await asyncpg.connect(dsn_as(api_dsn, "agent_anphu", "moi" + "b" * 40))
    await c.close()

    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(dsn_as(api_dsn, "agent_anphu", "cu" + "a" * 40))


async def test_role_moi_thuoc_nhom_agent_all(pool, tenant_anphu, ha_tang):
    """Toàn bộ quyền đến từ nhóm — create_agent_role() của M1 lo việc này.
    Test canh để nếu ai đó thay lời gọi bằng CREATE ROLE trần thì đỏ ngay."""
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "mk" + "x" * 40)
    assert await pool.fetchval("SELECT pg_has_role('agent_anphu','agent_all','MEMBER')") is True


async def test_tao_collection_idempotent(ha_tang, tenant_anphu):
    await ha_tang.tao_collection_neu_thieu(tenant_anphu)
    await ha_tang.tao_collection_neu_thieu(tenant_anphu)  # không được ném


async def test_thieu_gi_bao_dung_thu_dang_thieu(pool, tenant_anphu, ha_tang):
    thieu = await ha_tang.thieu_gi(pool, tenant_anphu)
    assert "role" in thieu
    await ha_tang.dat_mat_khau_role(pool, tenant_anphu, "mk" + "x" * 40)
    await ha_tang.tao_collection_neu_thieu(tenant_anphu)
    assert "role" not in await ha_tang.thieu_gi(pool, tenant_anphu)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_ha_tang_ngoai.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.enrollment.ha_tang_ngoai`

- [ ] **Step 3: Write the implementation**

```python
# src/portal/modules/enrollment/ha_tang_ngoai.py
"""Cấp phát trên ba hệ ngoài Postgres-thuần: role · khoá MinIO · collection Qdrant.

VÌ SAO TÁCH KHỎI service.py: service.py là nghiệp vụ và test được bằng unit test.
Ba việc ở đây cần MinIO thật và Qdrant thật. Tách ra một mặt tiền hẹp để service.py
tiêm được một fake, còn file này test bằng testcontainers.

ĐÂY KHÔNG PHẢI LỚP BỌC core/storage.py: nó GỌI chinh_sach_tien_to() và
ten_collection() có sẵn. Định nghĩa lại quy tắc đặt tên ở đây là tạo chủ thứ hai
cho cùng một khái niệm — đúng cái commit c4a1de9 vừa sửa khi đưa ten_collection()
về core/.

MỌI THAO TÁC IDEMPOTENT. Cấp phát chạm bốn hệ và không thể nằm trong một
transaction; chịu được gọi lại là cách duy nhất để hỏng-giữa-chừng không thành
trạng thái nửa vời.
"""

import asyncpg
from minio import MinioAdmin
from minio.credentials import StaticProvider
from qdrant_client import AsyncQdrantClient

from portal.core.config import get_settings
from portal.core.storage import chinh_sach_tien_to
from portal.core.ten_tai_nguyen import ten_collection, ten_khoa_truy_cap, ten_role_agent


class HaTangNgoai:
    def __init__(self, admin: MinioAdmin, qdrant: AsyncQdrantClient, bucket: str) -> None:
        self._admin = admin
        self._qdrant = qdrant
        self._bucket = bucket

    @classmethod
    def tu_cai_dat(cls) -> "HaTangNgoai":
        c = get_settings()
        endpoint = (c.s3_endpoint_url or "").removeprefix("http://").removeprefix("https://")
        return cls(
            admin=MinioAdmin(endpoint, credentials=StaticProvider(c.s3_access_key, c.s3_secret_key), secure=False),
            qdrant=AsyncQdrantClient(url=c.qdrant_url, api_key=c.qdrant_api_key or None),
            bucket=c.s3_bucket,
        )

    async def dat_mat_khau_role(self, conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str, mat_khau: str) -> None:
        """Tạo role nếu chưa có, đổi mật khẩu nếu đã có.

        KHÔNG sửa control.create_agent_role() của M1. Nhánh rẽ nằm ở đây; hàm của
        M1 giữ nguyên hợp đồng "tạo role mới". Nhánh ALTER là đường chạy ở MỌI lần
        xoay khoá, nên nó không phải trường hợp hiếm.
        """
        role = ten_role_agent(tenant_id)
        da_co = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if da_co:
            await conn.execute(f'ALTER ROLE "{role}" PASSWORD $1'.replace("$1", f"'{mat_khau}'"))
        else:
            await conn.execute("SELECT control.create_agent_role($1, $2)", tenant_id, mat_khau)

    def dat_khoa_kho_tep(self, tenant_id: str, secret: str) -> None:
        """Khoá MinIO + policy CHỈ mở tenants/<id>/*. Gỡ rồi thêm lại — nếp seed_kho_tep.py:59."""
        khoa = ten_khoa_truy_cap(tenant_id)
        try:
            self._admin.user_remove(khoa)
        except Exception:  # noqa: BLE001 — chưa có user thì user_remove ném; đó là trạng thái hợp lệ
            pass
        self._admin.user_add(khoa, secret)
        self._admin.policy_add(khoa, policy=chinh_sach_tien_to(tenant_id, self._bucket))
        self._admin.policy_set(khoa, user=khoa)

    async def tao_collection_neu_thieu(self, tenant_id: str) -> None:
        ten = ten_collection(tenant_id)
        if not await self._qdrant.collection_exists(ten):
            await self._qdrant.create_collection(ten, vectors_config=self._cau_hinh_vector())

    @staticmethod
    def _cau_hinh_vector():
        """PHẢI trùng cấu hình M6 dùng khi index. Khác chiều là mọi truy vấn ném lỗi.

        Đọc từ modules/kb/kho_tri_thuc.py — KHÔNG đặt số ở đây lần thứ hai.
        """
        from portal.modules.kb.kho_tri_thuc import CAU_HINH_VECTOR

        return CAU_HINH_VECTOR

    async def thieu_gi(self, conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str) -> str:
        """Chuỗi rỗng = cấp phát đủ. Ngược lại liệt kê thứ thiếu, để lỗi NOT_PROVISIONED
        nói được thiếu cái gì thay vì chỉ nói 'chưa xong'."""
        thieu = []
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", ten_role_agent(tenant_id)):
            thieu.append("role Postgres")
        if not await self._qdrant.collection_exists(ten_collection(tenant_id)):
            thieu.append("collection Qdrant")
        return " · ".join(thieu)
```

> **Hai chỗ phải kiểm trước khi chạy:**
> 1. `modules/kb/kho_tri_thuc.py` có hằng `CAU_HINH_VECTOR` không? Chạy
>    `grep -n 'VectorParams\|size=\|CAU_HINH' src/portal/modules/kb/kho_tri_thuc.py`. Nếu chưa có,
>    **trích nó ra thành hằng module-level ở file đó** rồi import — đừng chép số sang đây.
>    Import `modules.kb.kho_tri_thuc` là **vi phạm ranh giới module**
>    (`test_module_boundaries.py` chỉ cho import `modules/<khác>/contracts`). Nếu test đó đỏ, đưa
>    `CAU_HINH_VECTOR` vào `modules/kb/contracts.py` và import từ đó.
> 2. `MinioAdmin(...)` nhận tham số gì trong version đang cài? Chạy
>    `sed -n '45,55p' scripts/seed_kho_tep.py` và **chép y hệt cách nó dựng** — đừng đoán chữ ký.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/modules/enrollment/test_ha_tang_ngoai.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Verify module boundaries**

Run: `.venv/bin/pytest tests/test_module_boundaries.py -v`
Expected: PASS. Nếu đỏ vì import `modules.kb.kho_tri_thuc`, làm theo ghi chú (1) ở trên.

- [ ] **Step 6: Lint and commit**

```bash
make lint
git add src/portal/modules/enrollment/ha_tang_ngoai.py tests/modules/enrollment/test_ha_tang_ngoai.py
git commit -m "feat(m10): ha_tang_ngoai — cấp phát idempotent role · MinIO · Qdrant (T6)"
```

---

## Task 7: `service.py` — cấp phát, xác thực, xoay khoá

**Files:**
- Create: `src/portal/modules/enrollment/service.py`
- Test: `tests/modules/enrollment/test_service.py`

**Interfaces:**
- Consumes: `repo.*` (Task 5) · `HaTangNgoai` (Task 6) · `bi_mat.dan_xuat` (Task 2) ·
  `khoa_api.*` (Task 1) · `loi.*` (Task 4)
- Produces:
  - `cap_phat(pool, ha_tang, tenant_id, kind, label, boi) -> tuple[int, contracts.KhoaMoiOut]`
  - `bootstrap(pool, redis, ha_tang, khoa_tho) -> contracts.BootstrapOut`
  - `xoay_bi_mat(pool, ha_tang, tenant_id, boi) -> int`
  - `san_sang_du_lieu(pool, tenant_id) -> contracts.SanSangDuLieu`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_service.py
"""Nghiệp vụ M10. Cấp phát + bootstrap end-to-end trên hạ tầng thật."""

import pytest

from portal.api.loi import LoiPortal
from portal.modules.enrollment import service
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai


@pytest.fixture
def ha_tang(minio_endpoint, qdrant_url):
    return HaTangNgoai.tu_cai_dat()


async def test_bootstrap_tra_du_bon_khoi(pool, redis_client, ha_tang, tenant_anphu):
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "pod chat", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)

    assert ra.tenant_id == tenant_anphu
    assert ra.kind == "chat"
    assert "agent_anphu" in ra.postgres_dsn
    assert ra.storage.prefix == f"tenants/{tenant_anphu}/"
    assert ra.kb.collection == f"kb_{tenant_anphu}"
    assert ra.live_url.endswith(f"tenants/{tenant_anphu}/LIVE")


async def test_bootstrap_hai_lan_cung_mat_khau(pool, redis_client, ha_tang, tenant_anphu):
    """CỔNG 3. Pod chat và pod voice phải nhận CÙNG mật khẩu — chúng dùng chung
    role agent_<slug> vì current_tenant() parse tenant từ tên role."""
    _, k1 = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    _, k2 = await service.cap_phat(pool, ha_tang, tenant_anphu, "voice", "", "platform_admin")
    a = await service.bootstrap(pool, redis_client, ha_tang, k1.api_key)
    b = await service.bootstrap(pool, redis_client, ha_tang, k2.api_key)
    assert a.postgres_dsn == b.postgres_dsn
    assert a.deployment_id != b.deployment_id
    assert (a.kind, b.kind) == ("chat", "voice")


async def test_khoa_sai_thi_401(pool, redis_client, ha_tang):
    with pytest.raises(LoiPortal) as e:
        await service.bootstrap(pool, redis_client, ha_tang, "ody_ag_khong-co-that")
    assert e.value.ma == "INVALID_AGENT_KEY"


async def test_khoa_thu_hoi_va_khoa_khong_co_cung_cau_chu(pool, redis_client, ha_tang, tenant_anphu):
    """CỔNG 2. Khác message là máy dò biết khoá nào từng có thật."""
    from portal.modules.enrollment import repo

    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    await repo.thu_hoi_khoa(pool, khoa.id)

    with pytest.raises(LoiPortal) as thu_hoi:
        await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    with pytest.raises(LoiPortal) as khong_co:
        await service.bootstrap(pool, redis_client, ha_tang, "ody_ag_khong-co-that")

    assert thu_hoi.value.ma == khong_co.value.ma == "INVALID_AGENT_KEY"
    assert thu_hoi.value.thong_diep == khong_co.value.thong_diep


async def test_tenant_tam_ngung_thi_403(pool, redis_client, ha_tang, tenant_anphu):
    """CỔNG 5. Workspace đóng thì pod không được nhận credential mới."""
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    await pool.execute("UPDATE control.tenants SET status='suspended' WHERE id=$1", tenant_anphu)
    with pytest.raises(LoiPortal) as e:
        await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    assert e.value.ma == "TENANT_SUSPENDED"


async def test_vuot_nhip_thi_429(pool, redis_client, ha_tang, tenant_anphu):
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    for _ in range(10):
        await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    with pytest.raises(LoiPortal) as e:
        await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    assert e.value.ma == "RATE_LIMITED"


async def test_bootstrap_dung_dsn_that_de_doc_agent_api(pool, redis_client, ha_tang, tenant_anphu, api_dsn):
    """CỔNG 1 (nửa đầu): DSN trả về phải nối được và đọc được view."""
    import asyncpg

    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    c = await asyncpg.connect(ra.postgres_dsn)
    try:
        await c.fetch("SELECT * FROM agent_api.units LIMIT 1")
    finally:
        await c.close()


async def test_xoay_bi_mat_doi_mat_khau(pool, redis_client, ha_tang, tenant_anphu):
    """CỔNG 4."""
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    truoc = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    assert await service.xoay_bi_mat(pool, ha_tang, tenant_anphu, "platform_admin") == 2
    sau = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    assert truoc.postgres_dsn != sau.postgres_dsn


async def test_cap_phat_hai_lan_khong_vo(pool, ha_tang, tenant_anphu):
    """Tenant đã có role và collection ⇒ cấp phát deployment thứ hai vẫn chạy."""
    await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    await service.cap_phat(pool, ha_tang, tenant_anphu, "voice", "", "platform_admin")


async def test_khoa_tho_khong_luu_vao_db(pool, ha_tang, tenant_anphu):
    """CỔNG 6 (nửa đầu)."""
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    hit = await pool.fetchval(
        "SELECT count(*) FROM control.agent_keys WHERE key_sha256 = $1 OR label = $1 OR key_prefix = $1",
        khoa.api_key,
    )
    assert hit == 0
```

> **Kiểm trước khi chạy:** `control.tenants` có cột `status` với giá trị `'suspended'` không? Chạy
> `grep -n "status" migrations/versions/0002_control_core.py src/portal/core/tenant_status.py`.
> Dùng đúng tên cột và đúng giá trị mà `tenant_status.py` đã định nghĩa — **đừng** đặt tên mới.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.enrollment.service`

- [ ] **Step 3: Write the implementation**

```python
# src/portal/modules/enrollment/service.py
"""Nghiệp vụ đấu nối agent.

LUẬT MỘT CÂU CỦA MODULE: api_key nói "tôi là ai"; credential nói "tôi được làm gì".
Không gộp hai vai. api_key mở được ĐÚNG MỘT thứ — bộ credential của tenant nó thuộc về.
"""

from datetime import UTC, datetime, timedelta

import asyncpg
from redis.asyncio import Redis

from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.core.khoa_api import bam_khoa, gioi_han_nhip, sinh_khoa
from portal.core.storage import duong_dan_live
from portal.core.ten_tai_nguyen import ten_collection, ten_khoa_truy_cap, ten_role_agent
from portal.modules.enrollment import contracts, loi, repo
from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, dan_xuat
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai

NHIP_SO_LAN = 10
NHIP_GIAY = 300
"""10 lần / 5 phút cho mỗi khoá. Chống dò khoá, không phải chia băng thông."""


async def cap_phat(
    pool: asyncpg.Pool,
    ha_tang: HaTangNgoai,
    tenant_id: str,
    kind: str,
    label: str,
    boi: str,
) -> tuple[int, contracts.KhoaMoiOut]:
    """Tạo deployment + cấp phát hạ tầng + phát một khoá. IDEMPOTENT ở phần hạ tầng.

    Thứ tự có chủ ý: hạ tầng TRƯỚC, khoá SAU. Hỏng ở hạ tầng thì chưa có khoá nào
    được phát ra ngoài. Hỏng sau khi phát khoá thì bootstrap trả NOT_PROVISIONED —
    xấu nhưng chẩn đoán được, và admin bấm lại là xong.
    """
    c = get_settings()
    master = c.master_key_bytes()
    version = await repo.doc_version(pool, tenant_id)

    await ha_tang.dat_mat_khau_role(pool, tenant_id, dan_xuat(LOAI_PG, tenant_id, version, master))
    ha_tang.dat_khoa_kho_tep(tenant_id, dan_xuat(LOAI_S3, tenant_id, version, master))
    await ha_tang.tao_collection_neu_thieu(tenant_id)

    dep_id = await repo.them_deployment(pool, tenant_id, kind)
    tho, sha, prefix = sinh_khoa()
    key_id = await repo.them_khoa(pool, dep_id, sha, prefix, label, boi)

    await nhat_ky.ghi(pool, tenant_id, "agent.cap_phat", boi, {"deployment_id": dep_id, "key_prefix": prefix})
    return dep_id, contracts.KhoaMoiOut(id=key_id, api_key=tho, key_prefix=prefix)


async def bootstrap(
    pool: asyncpg.Pool,
    redis: Redis,
    ha_tang: HaTangNgoai,
    khoa_tho: str,
) -> contracts.BootstrapOut:
    """Đổi api_key lấy bộ credential. Endpoint DUY NHẤT trong hệ trả mật khẩu qua HTTP.

    Thứ tự kiểm có chủ ý: nhịp TRƯỚC khi tra DB. Kẻ dò khoá không được phép làm
    portal chạy một query cho mỗi lần đoán.
    """
    sha = bam_khoa(khoa_tho)
    if not await gioi_han_nhip(redis, sha, so_lan=NHIP_SO_LAN, giay=NHIP_GIAY):
        raise loi.vuot_gioi_han_nhip()

    khoa = await repo.tra_khoa(pool, sha)
    if khoa is None:
        raise loi.khoa_agent_khong_hop_le()

    trang_thai = await pool.fetchval("SELECT status FROM control.tenants WHERE id = $1", khoa.tenant_id)
    if trang_thai != "active":
        raise loi.tenant_bi_tam_ngung(khoa.tenant_id)

    thieu = await ha_tang.thieu_gi(pool, khoa.tenant_id)
    if thieu:
        raise loi.chua_cap_phat(thieu)

    c = get_settings()
    master = c.master_key_bytes()
    version = await repo.doc_version(pool, khoa.tenant_id)
    mat_khau_pg = dan_xuat(LOAI_PG, khoa.tenant_id, version, master)
    secret_s3 = dan_xuat(LOAI_S3, khoa.tenant_id, version, master)

    await repo.cham_last_used(pool, sha)
    await nhat_ky.ghi(
        pool, khoa.tenant_id, "agent.bootstrap", "agent", {"deployment_id": khoa.deployment_id}
    )

    return contracts.BootstrapOut(
        tenant_id=khoa.tenant_id,
        deployment_id=khoa.deployment_id,
        kind=khoa.kind,
        postgres_dsn=_dsn_agent(c.database_url, ten_role_agent(khoa.tenant_id), mat_khau_pg),
        storage=contracts.KhoTepOut(
            endpoint=c.s3_endpoint_url or "",
            bucket=c.s3_bucket,
            access_key=ten_khoa_truy_cap(khoa.tenant_id),
            secret_key=secret_s3,
            prefix=f"tenants/{khoa.tenant_id}/",
        ),
        kb=contracts.KbOut(url=c.qdrant_url, collection=ten_collection(khoa.tenant_id)),
        live_url=duong_dan_live(khoa.tenant_id),
        expires_at=datetime.now(UTC) + timedelta(seconds=c.bootstrap_ttl_seconds),
    )


def _dsn_agent(dsn_goc: str, role: str, mat_khau: str) -> str:
    """Thay user/password của DSN portal bằng của agent, giữ nguyên host/port/db.

    Dựng lại bằng urlsplit chứ không nối chuỗi: mật khẩu base64url có thể chứa '-'
    và '_', và một f-string ngây thơ sẽ hỏng khi host có cổng hoặc DSN có query.
    """
    from urllib.parse import quote, urlsplit, urlunsplit

    p = urlsplit(dsn_goc)
    netloc = f"{quote(role, safe='')}:{quote(mat_khau, safe='')}@{p.hostname}"
    if p.port:
        netloc += f":{p.port}"
    return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


async def xoay_bi_mat(pool: asyncpg.Pool, ha_tang: HaTangNgoai, tenant_id: str, boi: str) -> int:
    """Tăng version rồi áp mật khẩu mới lên Postgres và MinIO.

    Kết nối Postgres đang mở KHÔNG đứt — Postgres chỉ hỏi mật khẩu lúc nối mới.
    Pod có trọn một chu kỳ TTL để chuyển sang bản mới.
    """
    c = get_settings()
    master = c.master_key_bytes()
    version = await repo.tang_version(pool, tenant_id, boi)

    await ha_tang.dat_mat_khau_role(pool, tenant_id, dan_xuat(LOAI_PG, tenant_id, version, master))
    ha_tang.dat_khoa_kho_tep(tenant_id, dan_xuat(LOAI_S3, tenant_id, version, master))

    await nhat_ky.ghi(pool, tenant_id, "agent.xoay_bi_mat", boi, {"secret_version": version})
    return version


async def san_sang_du_lieu(pool: asyncpg.Pool, tenant_id: str) -> contracts.SanSangDuLieu:
    """Ba con số chẩn đoán. ĐỌC THUẦN — không cache, không lưu thành trạng thái.

    Cấp phát xong không có nghĩa agent nói được: field_policy_live rỗng ⇒
    portal.pol() trả false cho mọi trường ⇒ agent tư vấn bằng payload toàn NULL.
    Hỏng im lặng và trông như đang hoạt động. Xem spec §5.1 và M4a §1.

    M10 ĐỌC, M10 không seed. Seed là scripts/seed_bds.py của M4a.

    HAI NGUỒN, HAI CÁCH NỐI — cố ý, không phải thiếu nhất quán:
      control.field_policy_live  → pool trực tiếp (schema control, không RLS)
      tenant_data.*              → tenant_conn()  (RLS; đọc ngoài giao dịch trả 0 hàng
                                    và KHÔNG báo lỗi — isolation.md §4.2)
    Gộp cả ba vào pool trực tiếp là hai con số sau luôn bằng 0, và cổng 9 sẽ xanh
    trong khi nó đang nói dối.
    """
    fp = await pool.fetchval(
        "SELECT count(*) FROM control.field_policy_live WHERE tenant_id = $1", tenant_id
    )
    async with tenant_conn(pool, tenant_id) as conn:
        pj = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.projects WHERE agent_enabled"
        )
        kb = await conn.fetchval(
            "SELECT coalesce(sum(chunk_count), 0) FROM tenant_data.kb_files"
        )
    return contracts.SanSangDuLieu(field_policy_rows=fp, projects_agent_enabled=pj, kb_chunks=int(kb))


async def liet_ke_deployment(pool: asyncpg.Pool) -> list[contracts.DeploymentOut]:
    """Ghép hai nguồn: hàng deployment (control) + chẩn đoán dữ liệu (tenant_data).

    Ở service chứ không ở repo: repo không nối tenant_conn(), và không ở router
    vì router chỉ điều phối.
    """
    rows = await repo.liet_ke_deployment(pool)
    return [
        contracts.DeploymentOut(**r, san_sang_du_lieu=await san_sang_du_lieu(pool, r["tenant_id"]))
        for r in rows
    ]
```

Thêm import ở đầu `service.py`:

```python
from portal.core.db.session import tenant_conn
```

> **Hai chỗ phải kiểm trước khi chạy:**
> 1. `control.tenants.status` — giá trị "đang hoạt động" là `'active'`? Đọc
>    `src/portal/core/tenant_status.py` và dùng đúng hằng của nó thay vì chuỗi `"active"`.
> 2. `tenant_data.kb_files` có cột `chunk_count`? Chạy `grep -n chunk_count migrations/versions/0300_kb_files.py`.
>    Nếu tên khác, sửa truy vấn — đừng thêm cột.
> 3. `tenant_conn` nằm ở `portal.core.db.session` — xác nhận bằng
>    `grep -n "def tenant_conn" src/portal/core/db/session.py`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/modules/enrollment/test_service.py -v`
Expected: 10 PASSED

- [ ] **Step 5: Lint and commit**

```bash
make lint
git add src/portal/modules/enrollment/service.py tests/modules/enrollment/test_service.py
git commit -m "feat(m10): service — bootstrap · cấp phát · xoay bí mật, cổng 2·3·4·5 (T7)"
```

---

## Task 8: `router.py` — sáu endpoint

**Files:**
- Create: `src/portal/modules/enrollment/router.py`
- Create: `src/portal/modules/enrollment/fake.py`
- Modify: `src/portal/api/app.py` (đăng ký router)
- Test: `tests/modules/enrollment/test_router.py`

**Interfaces:**
- Consumes: `service.*` (Task 7) · `require_quan_tri_nen_tang` (Task 4)
- Produces: `ROUTER: APIRouter` với 6 đường của spec §4

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_router.py
"""Sáu endpoint của M10. Hai cổng xác thực khác nhau, không lẫn vào nhau."""

import pytest

TOKEN = "t" * 40
HEADER_ADMIN = {"X-Platform-Admin-Token": TOKEN}


@pytest.fixture(autouse=True)
def _dat_token(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("AGENT_MASTER_KEY", "m" * 40)
    from portal.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_tao_deployment_tra_khoa_dung_mot_lan(app_client, tenant_anphu):
    r = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers=HEADER_ADMIN,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"].startswith("ody_ag_")

    ds = await app_client.get("/api/v1/admin/deployments", headers=HEADER_ADMIN)
    assert body["api_key"] not in ds.text, "khoá thô không được xuất hiện lần thứ hai"


async def test_admin_thieu_token_thi_401(app_client, tenant_anphu):
    r = await app_client.post("/api/v1/admin/deployments", json={"tenant_id": tenant_anphu, "kind": "chat"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_ADMIN_TOKEN"


async def test_bootstrap_khong_nhan_cookie_phien(app_client, tenant_anphu, phien_hop_le):
    """CỔNG 7. Cookie phiên hợp lệ mà không có Bearer ⇒ vẫn 401.
    Hai đường xác thực phải tách hẳn — trộn chúng là mở một đường vào bằng phiên user."""
    r = await app_client.post("/api/v1/agent/v1/bootstrap", cookies={"odyssey_session": phien_hop_le})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_AGENT_KEY"


async def test_bootstrap_bang_bearer_thi_qua(app_client, tenant_anphu):
    tao = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers=HEADER_ADMIN,
    )
    key = tao.json()["api_key"]
    r = await app_client.post("/api/v1/agent/v1/bootstrap", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    assert r.json()["kb"]["collection"] == f"kb_{tenant_anphu}"


async def test_liet_ke_co_khoi_san_sang_du_lieu(app_client, tenant_anphu):
    await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers=HEADER_ADMIN,
    )
    r = await app_client.get("/api/v1/admin/deployments", headers=HEADER_ADMIN)
    d = r.json()[0]["san_sang_du_lieu"]
    assert set(d) == {"field_policy_rows", "projects_agent_enabled", "kb_chunks"}
    assert d["field_policy_rows"] == 0, "chưa chạy seed_bds.py ⇒ phải báo 0, không báo sẵn sàng"


async def test_thu_hoi_khoa_thi_bootstrap_401(app_client, tenant_anphu):
    tao = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers=HEADER_ADMIN,
    )
    key, kid = tao.json()["api_key"], tao.json()["id"]
    assert (await app_client.delete(f"/api/v1/admin/keys/{kid}", headers=HEADER_ADMIN)).status_code == 204
    r = await app_client.post("/api/v1/agent/v1/bootstrap", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 401
```

> **Kiểm trước khi viết:** fixture `app_client` ở `tests/conftest.py:207` nhận những tham số gì và
> đăng ký router thế nào? Chạy `sed -n '206,240p' tests/conftest.py`. Nếu nó nhận danh sách router
> thì thêm `ROUTER` của M10 vào; nếu nó gọi `create_app()` mặc định thì Step 4 (sửa `app.py`) là đủ.
> Fixture `phien_hop_le` — nếu chưa có, tìm test M2a nào tạo phiên
> (`grep -rn "odyssey_session" tests/modules/auth/`) và mượn đúng cách nó làm.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_router.py -v`
Expected: FAIL — 404 trên mọi đường

- [ ] **Step 3: Write the router**

```python
# src/portal/modules/enrollment/router.py
"""Sáu endpoint. Hai cổng xác thực KHÁC NHAU, cố ý không dùng chung:

  /agent/v1/bootstrap  → Bearer api_key của deployment (máy)
  /admin/*             → header X-Platform-Admin-Token (người)

Cả sáu khai require(None, ly_do=...) để qua cổng test_moi_route_khai_action.py
của M2a — chúng cố ý không dùng 13 action của PQ_01, vì 13 nhóm đó là quyền
TRONG một workspace còn hai vai này ở ngoài workspace. Xem spec §4.
"""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Header, Request, Response, status
from redis.asyncio import Redis

from portal.core.auth.quan_tri_nen_tang import ACTOR_QUAN_TRI, require_quan_tri_nen_tang
from portal.core.auth.require import require
from portal.modules.enrollment import contracts, loi, repo, service
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai

ROUTER = APIRouter()

LY_DO_AGENT = "xác thực bằng api_key của deployment, không phải phiên người dùng"
LY_DO_ADMIN = "xác thực bằng token quản trị nền tảng, không phải phiên workspace"


def _pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _ha_tang() -> HaTangNgoai:
    return HaTangNgoai.tu_cai_dat()


@ROUTER.post("/agent/v1/bootstrap", response_model=contracts.BootstrapOut)
async def bootstrap(
    request: Request,
    authorization: Annotated[str, Header()] = "",
    _: None = require(None, ly_do=LY_DO_AGENT),
) -> contracts.BootstrapOut:
    """⚠️ Response CHỨA MẬT KHẨU. Không log, không trace, không APM span (G-10)."""
    if not authorization.startswith("Bearer "):
        raise loi.khoa_agent_khong_hop_le()
    return await service.bootstrap(
        _pool(request), _redis(request), _ha_tang(), authorization.removeprefix("Bearer ").strip()
    )


@ROUTER.post("/admin/deployments", response_model=contracts.KhoaMoiOut, status_code=status.HTTP_201_CREATED)
async def tao_deployment(
    request: Request,
    body: contracts.DeploymentIn,
    _: None = require(None, ly_do=LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
) -> contracts.KhoaMoiOut:
    """Khoá thô trả về ĐÚNG MỘT LẦN, ở đây. Không endpoint nào đọc lại được."""
    _, khoa = await service.cap_phat(
        _pool(request), _ha_tang(), body.tenant_id, body.kind, "", ACTOR_QUAN_TRI
    )
    return khoa


@ROUTER.get("/admin/deployments", response_model=list[contracts.DeploymentOut])
async def liet_ke_deployment(
    request: Request,
    _: None = require(None, ly_do=LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
) -> list[contracts.DeploymentOut]:
    return await service.liet_ke_deployment(_pool(request))


@ROUTER.post(
    "/admin/deployments/{deployment_id}/keys",
    response_model=contracts.KhoaMoiOut,
    status_code=status.HTTP_201_CREATED,
)
async def phat_khoa(
    request: Request,
    deployment_id: int,
    _: None = require(None, ly_do=LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
) -> contracts.KhoaMoiOut:
    """Phát khoá thứ hai cho một deployment — dùng để xoay khoá không gián đoạn:
    phát mới, nạp vào pod, rồi mới thu hồi khoá cũ."""
    return await service.phat_khoa_them(_pool(request), deployment_id, ACTOR_QUAN_TRI)


@ROUTER.delete("/admin/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def thu_hoi(
    request: Request,
    key_id: int,
    _: None = require(None, ly_do=LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
) -> Response:
    await service.thu_hoi_khoa(_pool(request), key_id, ACTOR_QUAN_TRI)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ROUTER.post("/admin/tenants/{tenant_id}/rotate-secrets")
async def xoay_bi_mat(
    request: Request,
    tenant_id: str,
    _: None = require(None, ly_do=LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
) -> dict[str, int]:
    v = await service.xoay_bi_mat(_pool(request), _ha_tang(), tenant_id, ACTOR_QUAN_TRI)
    return {"secret_version": v}
```

- [ ] **Step 4: Add the two missing service functions**

```python
# thêm vào src/portal/modules/enrollment/service.py

async def phat_khoa_them(pool: asyncpg.Pool, deployment_id: int, boi: str) -> contracts.KhoaMoiOut:
    """Khoá thứ hai cho một deployment đã có.

    Vì sao cần: xoay khoá không gián đoạn. Phát mới → nạp vào pod → thu hồi cũ.
    Nếu chỉ có một khoá mỗi deployment thì mọi lần xoay đều có một khoảng chết.
    """
    tenant_id = await pool.fetchval("SELECT tenant_id FROM control.deployments WHERE id = $1", deployment_id)
    if tenant_id is None:
        raise loi.chua_cap_phat(f"deployment {deployment_id}")
    tho, sha, prefix = sinh_khoa()
    key_id = await repo.them_khoa(pool, deployment_id, sha, prefix, "", boi)
    await nhat_ky.ghi(pool, tenant_id, "agent.phat_khoa", boi, {"key_prefix": prefix})
    return contracts.KhoaMoiOut(id=key_id, api_key=tho, key_prefix=prefix)


async def thu_hoi_khoa(pool: asyncpg.Pool, key_id: int, boi: str) -> None:
    """Idempotent: thu hồi hai lần không phải lỗi, nhưng chỉ ghi nhật ký một lần."""
    tenant_id = await pool.fetchval(
        """SELECT d.tenant_id FROM control.agent_keys k
             JOIN control.deployments d ON d.id = k.deployment_id WHERE k.id = $1""",
        key_id,
    )
    if await repo.thu_hoi_khoa(pool, key_id) and tenant_id:
        await nhat_ky.ghi(pool, tenant_id, "agent.thu_hoi_khoa", boi, {"key_id": key_id})
```

> `service.liet_ke_deployment` đã viết ở Task 7 Step 3 (nó ghép `repo.liet_ke_deployment` với
> `san_sang_du_lieu`). Router chỉ gọi — không lặp, không dựng model.

Và `repo.liet_ke_deployment`:

```python
# thêm vào src/portal/modules/enrollment/repo.py

async def liet_ke_deployment(conn: asyncpg.Connection | asyncpg.Pool) -> list[dict]:
    """Xuyên tenant — admin nền tảng xem tình trạng vận hành là quyền control plane,
    không phải quyền đọc dữ liệu tenant (cùng lập luận với policy hb_portal_all của 0007)."""
    rows = await conn.fetch(
        """
        SELECT d.id, d.tenant_id, d.kind, d.endpoint, d.provisioned_at,
               count(k.id) FILTER (WHERE k.revoked_at IS NULL) AS so_khoa_con_song
          FROM control.deployments d
          LEFT JOIN control.agent_keys k ON k.deployment_id = d.id
         GROUP BY d.id
         ORDER BY d.provisioned_at DESC
        """
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Register the router**

Mở `src/portal/api/app.py`, tìm chỗ M3/M6 đăng ký router và thêm y hệt:

```python
from portal.modules.enrollment.router import ROUTER as ENROLLMENT_ROUTER
# ... trong danh sách routers:
("enrollment", ENROLLMENT_ROUTER),
```

- [ ] **Step 6: Write `fake.py`**

```python
# src/portal/modules/enrollment/fake.py
"""Dữ liệu giả cho FE — cơ chế ② của spec tổng §4.

KHÔNG có khoá thô giả trông giống thật ở đây: một chuỗi 'ody_ag_...' trong
fixture là thứ người ta copy nhầm vào cấu hình thật rồi mất một buổi tìm hiểu
vì sao 401.
"""

from datetime import UTC, datetime

from portal.modules.enrollment.contracts import DeploymentOut, SanSangDuLieu

DEPLOYMENTS_GIA = [
    DeploymentOut(
        id=1,
        tenant_id="anphu",
        kind="chat",
        endpoint="https://agent-anphu.internal",
        provisioned_at=datetime(2026, 8, 3, tzinfo=UTC),
        so_khoa_con_song=1,
        san_sang_du_lieu=SanSangDuLieu(field_policy_rows=59, projects_agent_enabled=3, kb_chunks=412),
    ),
    DeploymentOut(
        id=2,
        tenant_id="bcland",
        kind="chat",
        endpoint="",
        provisioned_at=datetime(2026, 8, 3, tzinfo=UTC),
        so_khoa_con_song=0,
        san_sang_du_lieu=SanSangDuLieu(field_policy_rows=0, projects_agent_enabled=0, kb_chunks=0),
    ),
]
"""Hàng thứ hai cố ý là workspace CHƯA seed — để FE dựng được trạng thái cảnh báo."""
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/modules/enrollment/test_router.py -v`
Expected: 6 PASSED

- [ ] **Step 8: Run the M2a route gate**

Run: `.venv/bin/pytest tests/api/test_moi_route_khai_action.py -v`
Expected: PASS — sáu route mới đều khai `require(None, ly_do=...)`

- [ ] **Step 9: Regenerate contracts, lint, commit**

```bash
make contracts
make lint
git add src/portal/modules/enrollment/ src/portal/api/app.py contracts/ tests/modules/enrollment/
git commit -m "feat(m10): sáu endpoint — hai cổng xác thực tách hẳn, cổng 7 (T8)"
```

---

## Task 9: Cổng cách ly và cổng quét động

**Files:**
- Test: `tests/modules/enrollment/test_bootstrap_cach_ly.py`
- Test: `tests/modules/enrollment/test_khong_ro_bi_mat.py`
- Test: `tests/modules/enrollment/test_san_sang_du_lieu.py`

**Interfaces:**
- Consumes: toàn bộ Task 1–8 · `scripts/seed_bds.py` (M4a)

**⚠️ Task này cần M4a Task 10 (`seed_bds.py`) đã xong.** Nếu chưa, làm Task 10–11 trước.

- [ ] **Step 1: Write gate 1 — cross-tenant isolation with real data**

```python
# tests/modules/enrollment/test_bootstrap_cach_ly.py
"""CỔNG 1 — cách ly xuyên tenant qua đường M10 vừa mở.

⚠️ Cổng này CHỈ CÓ NGHĨA khi CẢ HAI tenant có dữ liệu. Với bảng rỗng nó vẫn
xanh — 0 hàng của B là đúng ngay cả khi A cũng 0 hàng, và thế thì nó chứng
minh một mệnh đề rỗng. Fixture dưới đây seed cả hai.
"""

import asyncpg
import pytest

from portal.modules.enrollment import service
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai


@pytest.fixture
def ha_tang(minio_endpoint, qdrant_url):
    return HaTangNgoai.tu_cai_dat()


@pytest.fixture
async def hai_tenant_co_du_lieu(pool):
    """Hai workspace, mỗi bên một dự án bật agent_enabled và một căn."""
    from scripts.seed_bds import seed_field_policy

    for tid, ten in (("anphu", "An Phú Land"), ("bcland", "BC Land")):
        await pool.execute(
            "INSERT INTO control.tenants (id, name) VALUES ($1,$2) ON CONFLICT DO NOTHING", tid, ten
        )
        await seed_field_policy(pool, tid)
        await pool.execute(
            """INSERT INTO tenant_data.projects (tenant_id, code, name, agent_enabled)
               VALUES ($1, $2, $3, true) ON CONFLICT DO NOTHING""",
            tid,
            f"DA-{tid}",
            f"Dự án {tid}",
        )
        await pool.execute(
            """INSERT INTO tenant_data.units (tenant_id, code, project_code, is_active)
               VALUES ($1, $2, $3, true) ON CONFLICT DO NOTHING""",
            tid,
            f"CAN-{tid}",
            f"DA-{tid}",
        )
    return ("anphu", "bcland")


async def test_dsn_cua_A_khong_thay_hang_nao_cua_B(pool, redis_client, ha_tang, hai_tenant_co_du_lieu):
    a, b = hai_tenant_co_du_lieu
    _, khoa = await service.cap_phat(pool, ha_tang, a, "chat", "", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)

    c = await asyncpg.connect(ra.postgres_dsn)
    try:
        codes = {r["code"] for r in await c.fetch("SELECT code FROM agent_api.units")}
    finally:
        await c.close()

    assert f"CAN-{a}" in codes, "phải thấy dữ liệu của chính mình — nếu không, cổng này vô nghĩa"
    assert f"CAN-{b}" not in codes
    assert codes == {f"CAN-{a}"}


async def test_dsn_cua_A_khong_cham_duoc_bang_goc(pool, redis_client, ha_tang, hai_tenant_co_du_lieu):
    """Agent chỉ được đọc view, không được chạm tenant_data.* — G-6."""
    a, _ = hai_tenant_co_du_lieu
    _, khoa = await service.cap_phat(pool, ha_tang, a, "chat", "", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)

    c = await asyncpg.connect(ra.postgres_dsn)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.fetch("SELECT * FROM tenant_data.units")
    finally:
        await c.close()


async def test_dsn_cua_A_khong_doc_duoc_bang_khoa(pool, redis_client, ha_tang, hai_tenant_co_du_lieu):
    a, _ = hai_tenant_co_du_lieu
    _, khoa = await service.cap_phat(pool, ha_tang, a, "chat", "", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)

    c = await asyncpg.connect(ra.postgres_dsn)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.fetch("SELECT * FROM control.agent_keys")
    finally:
        await c.close()
```

> **Kiểm:** `scripts/seed_bds.py` của M4a có hàm nào seed `field_policy_live` cho một tenant? Chạy
> `grep -n "^async def \|^def " scripts/seed_bds.py` và dùng đúng tên nó có. Nếu nó chỉ có `main()`
> chạy cho mọi tenant, **trích một hàm `seed_field_policy(conn, tenant_id)`** ở đó rồi gọi — đừng
> chép 59 hàng seed sang test.

- [ ] **Step 2: Run gate 1**

Run: `.venv/bin/pytest tests/modules/enrollment/test_bootstrap_cach_ly.py -v`
Expected: 3 PASSED

- [ ] **Step 3: Write gate 6 — dynamic secret-leak scan**

```python
# tests/modules/enrollment/test_khong_ro_bi_mat.py
"""CỔNG 6 — quét ĐỘNG. Nó bắt được người thêm cột `password_cache` sáu tháng nữa.

Cùng hạng với cổng 5 và 6 của M1: một test đọc catalog thay vì một danh sách
cứng mà ai đó phải nhớ cập nhật.
"""

import logging

import pytest

from portal.core.config import get_settings
from portal.modules.enrollment import service
from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, dan_xuat
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai


@pytest.fixture
def ha_tang(minio_endpoint, qdrant_url):
    return HaTangNgoai.tu_cai_dat()


async def test_khong_cot_text_nao_chua_bi_mat(pool, ha_tang, tenant_anphu):
    """Quét MỌI cột text của hai bảng, so với mật khẩu vừa suy dẫn."""
    await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    master = get_settings().master_key_bytes()
    bi_mat = {
        dan_xuat(LOAI_PG, tenant_anphu, 1, master),
        dan_xuat(LOAI_S3, tenant_anphu, 1, master),
    }

    cot = await pool.fetch(
        """SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='control'
              AND table_name IN ('agent_keys','agent_credentials')
              AND data_type IN ('text','character varying')"""
    )
    assert cot, "không quét được cột nào — truy vấn catalog sai, không phải bảng sạch"

    for r in cot:
        for bm in bi_mat:
            hit = await pool.fetchval(
                f'SELECT count(*) FROM control."{r["table_name"]}" WHERE "{r["column_name"]}" = $1', bm  # noqa: S608
            )
            assert hit == 0, f'bí mật rò vào control.{r["table_name"]}.{r["column_name"]}'


async def test_bootstrap_khong_ghi_bi_mat_vao_log(pool, redis_client, ha_tang, tenant_anphu, caplog):
    """G-10 ở phía portal. Response chứa mật khẩu; một logger DEBUG nào đó in nó ra
    là mật khẩu của mọi tenant nằm trong log tập trung."""
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    with caplog.at_level(logging.DEBUG):
        ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)

    van_ban = caplog.text
    for bm in (ra.postgres_dsn, ra.storage.secret_key, khoa.api_key):
        assert bm not in van_ban


async def test_bootstrapout_repr_khong_lo_mat_khau(pool, redis_client, ha_tang, tenant_anphu):
    """Một f-string vô ý trong except là đủ để lộ. Chặn ở tầng model."""
    _, khoa = await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    ra = await service.bootstrap(pool, redis_client, ha_tang, khoa.api_key)
    assert ra.storage.secret_key not in repr(ra)
    assert ra.storage.secret_key not in str(ra)
```

- [ ] **Step 4: Run gate 6 to verify the repr test fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_khong_ro_bi_mat.py -v`
Expected: hai test đầu PASS, `test_bootstrapout_repr_khong_lo_mat_khau` FAIL

- [ ] **Step 5: Make `repr` safe**

```python
# sửa contracts.py — thay str bằng SecretStr cho ba trường nhạy cảm
from pydantic import BaseModel, Field, SecretStr


class KhoTepOut(BaseModel):
    endpoint: str
    bucket: str
    access_key: str
    secret_key: SecretStr
    """SecretStr: repr() và str() in '**********'. Một f-string vô ý trong except
    là đủ để lộ, và chặn ở tầng model rẻ hơn chặn ở mọi chỗ gọi."""
    prefix: str


class BootstrapOut(BaseModel):
    ...
    postgres_dsn: SecretStr
    ...
```

FastAPI mặc định serialize `SecretStr` thành `"**********"` — response JSON sẽ **vô dụng** nếu để
nguyên. Dùng `field_serializer` (pydantic v2; `json_encoders` đã deprecated):

```python
from pydantic import BaseModel, Field, SecretStr, field_serializer


class KhoTepOut(BaseModel):
    endpoint: str
    bucket: str
    access_key: str
    secret_key: SecretStr
    prefix: str

    @field_serializer("secret_key", when_used="json")
    def _lo_secret(self, v: SecretStr) -> str:
        """`when_used="json"` — response HTTP có giá trị thật, còn repr()/str() thì không.

        Đúng chỗ cần: pod PHẢI nhận được secret; log thì KHÔNG được thấy nó.
        """
        return v.get_secret_value()


class BootstrapOut(BaseModel):
    tenant_id: str
    deployment_id: int
    kind: Kind
    postgres_dsn: SecretStr
    storage: KhoTepOut
    kb: KbOut
    live_url: str
    expires_at: datetime

    @field_serializer("postgres_dsn", when_used="json")
    def _lo_dsn(self, v: SecretStr) -> str:
        return v.get_secret_value()
```

Sửa `service.bootstrap()` — bọc hai giá trị:

```python
        postgres_dsn=SecretStr(_dsn_agent(c.database_url, ten_role_agent(khoa.tenant_id), mat_khau_pg)),
        storage=contracts.KhoTepOut(
            ...
            secret_key=SecretStr(secret_s3),
            ...
        ),
```

Sửa ba test của Task 7 so sánh DSN — thêm `.get_secret_value()`:

```python
# test_bootstrap_tra_du_bon_khoi
assert "agent_anphu" in ra.postgres_dsn.get_secret_value()

# test_bootstrap_hai_lan_cung_mat_khau
assert a.postgres_dsn.get_secret_value() == b.postgres_dsn.get_secret_value()

# test_bootstrap_dung_dsn_that_de_doc_agent_api  và  test_xoay_bi_mat_doi_mat_khau
c = await asyncpg.connect(ra.postgres_dsn.get_secret_value())
assert truoc.postgres_dsn.get_secret_value() != sau.postgres_dsn.get_secret_value()
```

Và Task 9 `test_bootstrap_khong_ghi_bi_mat_vao_log` — hai dòng đầu của vòng lặp:

```python
    for bm in (ra.postgres_dsn.get_secret_value(), ra.storage.secret_key.get_secret_value(), khoa.api_key):
```

Và Task 9 `test_bootstrapout_repr_khong_lo_mat_khau`:

```python
    thuc = ra.storage.secret_key.get_secret_value()
    assert thuc not in repr(ra)
    assert thuc not in str(ra)
```

Và Task 9 cổng cách ly + Task 10 `agent_gia` — `agent_gia` đọc từ **JSON response**, không từ model,
nên nó **không đổi**: `d["postgres_dsn"]` đã là chuỗi thật nhờ `field_serializer`.

- [ ] **Step 6: Run all gates**

Run: `.venv/bin/pytest tests/modules/enrollment/ -v`
Expected: tất cả PASS

- [ ] **Step 7: Write gate 9 — data readiness**

```python
# tests/modules/enrollment/test_san_sang_du_lieu.py
"""CỔNG 9 — cấp phát xong ≠ agent nói được.

M4a §1: bootstrap sạch, SELECT sạch, field_policy_live rỗng ⇒ pol() trả false
cho mọi trường ⇒ agent tư vấn bằng payload toàn NULL. Hỏng im lặng và trông như
đang hoạt động. Đây là cổng duy nhất bắt được nó.
"""

from portal.modules.enrollment import service
from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai
import pytest


@pytest.fixture
def ha_tang(minio_endpoint, qdrant_url):
    return HaTangNgoai.tu_cai_dat()


async def test_chua_seed_thi_bao_khong(pool, ha_tang, tenant_anphu):
    await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    d = await service.san_sang_du_lieu(pool, tenant_anphu)
    assert d.field_policy_rows == 0
    assert d.projects_agent_enabled == 0


async def test_seed_roi_thi_bao_co(pool, ha_tang, tenant_anphu):
    from scripts.seed_bds import seed_field_policy

    await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    await seed_field_policy(pool, tenant_anphu)
    await pool.execute(
        """INSERT INTO tenant_data.projects (tenant_id, code, name, agent_enabled)
           VALUES ($1,'DA-1','Dự án 1', true)""",
        tenant_anphu,
    )
    d = await service.san_sang_du_lieu(pool, tenant_anphu)
    assert d.field_policy_rows > 0
    assert d.projects_agent_enabled == 1


async def test_du_an_tat_agent_khong_duoc_dem(pool, ha_tang, tenant_anphu):
    """agent_enabled=false ⇒ agent không thấy dự án đó (M4a BR11), nên nó không
    tính vào 'sẵn sàng'."""
    await service.cap_phat(pool, ha_tang, tenant_anphu, "chat", "", "platform_admin")
    await pool.execute(
        """INSERT INTO tenant_data.projects (tenant_id, code, name, agent_enabled)
           VALUES ($1,'DA-2','Dự án 2', false)""",
        tenant_anphu,
    )
    assert (await service.san_sang_du_lieu(pool, tenant_anphu)).projects_agent_enabled == 0
```

- [ ] **Step 8: Run gate 9**

Run: `.venv/bin/pytest tests/modules/enrollment/test_san_sang_du_lieu.py -v`
Expected: 3 PASSED

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add src/portal/modules/enrollment/contracts.py src/portal/modules/enrollment/service.py \
        tests/modules/enrollment/
git commit -m "feat(m10): cổng 1 · 6 · 9 — cách ly có dữ liệu thật, quét động bí mật (T9)"
```

---

## Task 10: `agent_gia.py` chuyển sang bootstrap

**Files:**
- Modify: `scripts/agent_gia.py`
- Modify: `scripts/seed_kho_tep.py`
- Modify: `Makefile` (target `agent-gia` và `dev-seed`)
- Test: `tests/modules/enrollment/test_agent_gia_end_to_end.py`

**Interfaces:**
- Consumes: `POST /agent/v1/bootstrap`
- Produces: `agent_gia` chạy chỉ với `PORTAL_URL` + `AGENT_API_KEY`

**Vì sao task này quan trọng hơn vẻ ngoài:** `agent_gia.py` là **spec sống** của Gói G (M3 §7).
Người nhận Gói G đọc 100 dòng Python nhanh hơn đọc 400 dòng văn bản. Nếu nó vẫn đọc credential từ
env thì hợp đồng §7 nói một đằng, mã mẫu làm một nẻo.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/enrollment/test_agent_gia_end_to_end.py
"""CỔNG 8 — chuỗi thông từ api_key tới heartbeat.

Đây là cổng DUY NHẤT chứng minh toàn bộ đường ống. Bảy cổng kia mỗi cái kiểm
một đoạn; cổng này kiểm chúng nối được với nhau.
"""

import pytest

from scripts.agent_gia import AgentGia


async def test_chi_can_hai_bien_moi_truong(app_client, pool, tenant_anphu, kho_tep):
    """Không TENANT_ID, không DSN, không khoá S3 — chỉ URL và api_key."""
    tao = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers={"X-Platform-Admin-Token": "t" * 40},
    )
    api_key = tao.json()["api_key"]

    agent = AgentGia(portal_url=str(app_client.base_url), api_key=api_key)
    await agent.bootstrap()

    # `tao.json()["id"]` là id của KHOÁ, không phải của deployment — KhoaMoiOut.id.
    # Deployment id lấy từ DB để khỏi lẫn hai khái niệm.
    dep_id = await pool.fetchval("SELECT id FROM control.deployments WHERE tenant_id=$1", tenant_anphu)
    assert agent.tenant_id == tenant_anphu
    assert agent.deployment_id == dep_id
    assert agent.postgres_dsn and agent.kb["collection"] == f"kb_{tenant_anphu}"


async def test_ghi_duoc_heartbeat(app_client, pool, tenant_anphu, kho_tep):
    tao = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers={"X-Platform-Admin-Token": "t" * 40},
    )
    agent = AgentGia(portal_url=str(app_client.base_url), api_key=tao.json()["api_key"])
    await agent.bootstrap()
    await agent.ghi_nhip_tim(running_version=None, bundle_sha="")

    r = await pool.fetchrow(
        "SELECT tenant_id, deployment_id FROM control.agent_heartbeats WHERE tenant_id=$1", tenant_anphu
    )
    assert r is not None
    assert r["deployment_id"] == agent.deployment_id


async def test_khoa_bi_thu_hoi_thi_bootstrap_nem(app_client, pool, tenant_anphu, kho_tep):
    """Fail-fast (G-2): không được fallback về credential cũ."""
    tao = await app_client.post(
        "/api/v1/admin/deployments",
        json={"tenant_id": tenant_anphu, "kind": "chat"},
        headers={"X-Platform-Admin-Token": "t" * 40},
    )
    agent = AgentGia(portal_url=str(app_client.base_url), api_key=tao.json()["api_key"])
    await agent.bootstrap()
    await app_client.delete(
        f"/api/v1/admin/keys/{tao.json()['id']}", headers={"X-Platform-Admin-Token": "t" * 40}
    )
    with pytest.raises(RuntimeError, match="401"):
        await agent.bootstrap()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/modules/enrollment/test_agent_gia_end_to_end.py -v`
Expected: FAIL — `ImportError: cannot import name 'AgentGia'`

- [ ] **Step 3: Rewrite `agent_gia.py`**

Đọc file hiện tại trước (`cat scripts/agent_gia.py`) và **giữ nguyên** phần poll LIVE / verify
sha256 / ghi heartbeat. Thay đúng phần lấy cấu hình:

```python
# scripts/agent_gia.py — phần đầu, thay chỗ đọc env
"""Agent giả — SPEC SỐNG của Gói G. Đọc 100 dòng này nhanh hơn đọc 400 dòng hợp đồng.

Nó KHÔNG giả lập LLM, không giả lập tool. Nó làm đúng phần hợp đồng M3 + M10 quan tâm:
bootstrap → poll LIVE → verify sha → heartbeat.

CHỈ HAI BIẾN MÔI TRƯỜNG (G-1):
    PORTAL_URL     https://portal.internal
    AGENT_API_KEY  ody_ag_...
Không TENANT_ID, không DSN, không khoá S3. Nếu bạn thấy mình cần thêm một biến
nữa thì hoặc bootstrap thiếu trường, hoặc bạn đang đi đường tắt.
"""

import asyncio
import os
from dataclasses import dataclass, field

import httpx


@dataclass
class AgentGia:
    portal_url: str
    api_key: str

    tenant_id: str = ""
    deployment_id: int = 0
    postgres_dsn: str = field(default="", repr=False)
    storage: dict = field(default_factory=dict, repr=False)
    kb: dict = field(default_factory=dict)
    live_url: str = ""

    async def bootstrap(self) -> None:
        """Lấy danh tính và credential. FAIL-FAST (G-2): hỏng thì NÉM, không fallback.

        Fallback âm thầm về credential cũ là đường quay lại cấu hình sai mà không
        ai thấy — pod chạy tiếp, đọc dữ liệu bằng khoá đã thu hồi, và không có gì
        báo động.
        """
        async with httpx.AsyncClient(base_url=self.portal_url, timeout=10) as c:
            r = await c.post("/api/v1/agent/v1/bootstrap", headers={"Authorization": f"Bearer {self.api_key}"})
        if r.status_code != 200:
            raise RuntimeError(f"bootstrap thất bại: {r.status_code} {r.text[:200]}")

        d = r.json()
        self.tenant_id = d["tenant_id"]
        self.deployment_id = d["deployment_id"]
        self.postgres_dsn = d["postgres_dsn"]
        self.storage = d["storage"]
        self.kb = d["kb"]
        self.live_url = d["live_url"]
        # KHÔNG print/log d — nó chứa mật khẩu (G-10).
        print(f"bootstrap xong: tenant={self.tenant_id} deployment={self.deployment_id} kb={self.kb['collection']}")

    async def ghi_nhip_tim(self, running_version: int | None, bundle_sha: str) -> None:
        """Upsert vào control.agent_heartbeats bằng DSN NHẬN TỪ BOOTSTRAP."""
        import asyncpg

        conn = await asyncpg.connect(self.postgres_dsn)
        try:
            await conn.execute(
                """
                INSERT INTO control.agent_heartbeats
                    (tenant_id, deployment_id, running_version, bundle_sha, agent_version)
                VALUES ($1, $2, $3, $4, 'agent-gia')
                ON CONFLICT (tenant_id, deployment_id) DO UPDATE
                    SET running_version = excluded.running_version,
                        bundle_sha      = excluded.bundle_sha,
                        last_error      = '',
                        last_seen_at    = now()
                """,
                self.tenant_id,
                self.deployment_id,
                running_version,
                bundle_sha,
            )
        finally:
            await conn.close()


async def main() -> None:
    portal = os.environ.get("PORTAL_URL")
    key = os.environ.get("AGENT_API_KEY")
    if not portal or not key:
        raise SystemExit("cần PORTAL_URL và AGENT_API_KEY. Chỉ hai biến đó — xem docstring.")

    agent = AgentGia(portal_url=portal, api_key=key)
    await agent.bootstrap()
    # ... phần poll LIVE / verify sha / heartbeat GIỮ NGUYÊN từ bản M3,
    #     chỉ thay nguồn cấu hình bằng agent.storage / agent.live_url


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/modules/enrollment/test_agent_gia_end_to_end.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Fix `seed_kho_tep.py`**

```python
# scripts/seed_kho_tep.py — bỏ MAT_KHAU_DEV
# TRƯỚC:  admin.user_add(khoa, MAT_KHAU_DEV)
# SAU:
from portal.core.config import get_settings
from portal.modules.enrollment.bi_mat import LOAI_S3, dan_xuat

# ... trong vòng lặp theo tenant:
secret = dan_xuat(LOAI_S3, tenant_id, 1, get_settings().master_key_bytes())
admin.user_add(khoa, secret)
```

Xoá hằng `MAT_KHAU_DEV` và thêm comment giải thích:

```python
# VÌ SAO BỎ MAT_KHAU_DEV: dev và production phải đi CÙNG một đường code sinh bí
# mật. Một mật khẩu cố định ở dev nghĩa là đường thật (bi_mat.dan_xuat) chỉ được
# chạy lần đầu ở production — chỗ tệ nhất để phát hiện nó sai.
```

- [ ] **Step 6: Update the Makefile**

```makefile
agent-gia:      ## đóng vai pod: bootstrap, poll LIVE, ghi nhịp tim (KEY=ody_ag_...)
	PORTAL_URL=http://localhost:8100 AGENT_API_KEY=$(KEY) .venv/bin/python -m scripts.agent_gia
```

Và trong `dev-seed`, thêm bước tạo một deployment + in api_key cho tenant demo:

```python
# thêm vào cuối scripts/dev_seed.py
async def tao_deployment_demo(pool) -> None:
    """Một deployment + api_key cho tenant demo, IN RA MÀN HÌNH.

    In khoá thô ra stdout là chấp nhận được ở đây và CHỈ ở đây: dev_seed đã có
    guard chỉ-localhost, và không có nó thì `make up` xong vẫn không chạy được
    `make agent-gia`.
    """
    from portal.modules.enrollment import service
    from portal.modules.enrollment.ha_tang_ngoai import HaTangNgoai

    _, khoa = await service.cap_phat(pool, HaTangNgoai.tu_cai_dat(), "anphu", "chat", "dev", "dev-seed")
    print(f"\n  AGENT_API_KEY={khoa.api_key}")
    print(f"  chạy thử:  make agent-gia KEY={khoa.api_key}\n")
```

- [ ] **Step 7: Verify the whole dev flow from zero**

```bash
make reset && make up
```
Expected: chạy hết không lỗi, và in ra một dòng `AGENT_API_KEY=ody_ag_...`

- [ ] **Step 8: Run the full test suite**

Run: `make test`
Expected: tất cả xanh — đặc biệt `make test-isolation` không được đỏ

- [ ] **Step 9: Lint and commit**

```bash
make lint
git add scripts/ Makefile tests/modules/enrollment/test_agent_gia_end_to_end.py
git commit -m "feat(m10): agent_gia bootstrap · seed_kho_tep dùng bi_mat · cổng 8 (T10)"
```

---

## Task 11: Hợp đồng bàn giao Gói G

**Files:**
- Modify: `docs/contracts/dau-noi-agent.md` — **đã viết trước, commit `<sẽ điền>`**
- Modify: `docs/superpowers/specs/2026-08-02-m4a-du-lieu-bds-design.md` (§10 — đánh dấu đã làm)

**Interfaces:**
- Consumes: spec M10 §7 (12 mục G-1…G-12) · code đã ship ở T1–T10
- Produces: hợp đồng đã **đối chiếu với code thật**, gỡ nhãn "BẢN GIAO TRƯỚC"

> **File này đã tồn tại.** Nó được viết **trước** khi code để bên `santa-hotline-agent` làm song
> song — bảy việc trong §8 của nó không phụ thuộc portal. Task 11 vì vậy **không phải viết mới**,
> mà là **đối chiếu và chốt**: hợp đồng viết theo spec, giờ phải khớp với code đã ship.

- [ ] **Step 1: Đối chiếu §2 với `BootstrapOut` thật**

Với mỗi trường trong ví dụ JSON của §2, đối chiếu **tên** và **kiểu** với code. Một hợp đồng nói
`kb_collection` trong khi code trả `kb.collection` là một buổi debug của người khác.

Đừng đọc bằng mắt — lấy schema thật:

```bash
.venv/bin/python -c "
from portal.modules.enrollment.contracts import BootstrapOut
import json; print(json.dumps(BootstrapOut.model_json_schema(), indent=2, ensure_ascii=False))"
```

So từng khoá với §2 của hợp đồng. Lệch chỗ nào ⇒ **sửa hợp đồng, không sửa code** — trừ khi code
sai so với spec §4.

- [ ] **Step 2: Đối chiếu bốn mã lỗi**

```bash
grep -n 'LoiPortal(' src/portal/modules/enrollment/loi.py
```

Bốn mã trong bảng §2 của hợp đồng (`INVALID_AGENT_KEY` · `TENANT_SUSPENDED` · `NOT_PROVISIONED` ·
`RATE_LIMITED`) phải khớp **cả mã lẫn HTTP status**. `INVALID_ADMIN_TOKEN` **không** vào hợp đồng —
nó là mã của route `/admin/*`, bên agent không bao giờ gặp.

- [ ] **Step 3: Gỡ nhãn "BẢN GIAO TRƯỚC"**

Xoá khối `>` ở đầu file và thay bằng:

```markdown
> **Ngày:** 2026-08-03 · **Cập nhật:** <ngày ship> · **Cho:** `santa-hotline-agent` (Gói G) ·
> **Bổ sung cho:** [`bundle.md`](bundle.md) — không thay thế.
> **Trạng thái:** portal đã ship. Đối chiếu với code tại `modules/enrollment/`.
```

- [ ] **Step 4: Mark the M4a debt as paid**

Trong `docs/superpowers/specs/2026-08-02-m4a-du-lieu-bds-design.md` §10, đổi dòng:

```markdown
- `docs/contracts/dau-noi-agent.md` — thêm **G-11** và **G-12** (§6.2). Nếu M10 chưa ship, ghi tạm
  vào spec M10 §7.
```

thành:

```markdown
- ✅ `docs/contracts/dau-noi-agent.md` — **G-11** và **G-12** đã vào hợp đồng (M10 T11).
```

- [ ] **Step 5: Commit**

```bash
git add docs/contracts/ docs/superpowers/specs/2026-08-02-m4a-du-lieu-bds-design.md
git commit -m "docs(m10): hợp đồng đấu nối — 12 mục Gói G, trả nợ G-11·G-12 của M4a (T11)"
```

---

## Sau khi xong 11 task

- [ ] `make check` xanh toàn bộ
- [ ] `make test-isolation` xanh — 6 cổng M1 không được đỏ vì hai bảng mới
- [ ] `make reset && make up` từ số 0 chạy hết, in ra `AGENT_API_KEY=...`
- [ ] `make agent-gia KEY=<khoá vừa in>` bootstrap được và ghi heartbeat
- [ ] Chín cổng test của spec §6 đều có test tương ứng và đều xanh
- [ ] Gửi `docs/contracts/dau-noi-agent.md` cho người nhận Gói G

**Ba việc còn treo, ghi rõ ở spec §11 — không thuộc plan này:**
1. **Cách ly Redis của agent** — kho thứ tư. Xem `isolation.md §11`. Chặn tenant thứ hai lên production.
2. **Vai *quản trị nền tảng* thật** — chờ M2b. `require_quan_tri_nen_tang()` đổi ruột, giữ chữ ký.
3. **Xoay `AGENT_MASTER_KEY`** — chưa có quy trình xoay theo lô.
