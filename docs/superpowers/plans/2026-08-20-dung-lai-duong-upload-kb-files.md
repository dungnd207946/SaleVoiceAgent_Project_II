# Dựng lại đường upload `/kb/files` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khôi phục 3 route `GET/POST/DELETE /api/v1/kb/files` + job nạp `kb_file_index` để màn «Tài liệu tra cứu» (`/kb`) của FE sống lại trên backend thật.

**Architecture:** Kho riêng `kb_files` (bảng có sẵn, migration `0300`) nối vào máy móc hiện hành của module kb: upload ghi S3 + hàng `dang_xu_ly` + enqueue; worker bóc chữ bằng `TextExtractor`, nhúng qua `RagClient` (chunk → embed → Qdrant `<tenant>_documents`) với `anchor_code='__ALL__'`, `doc_type='kb_file'`, `status='published'` — agent `kb_search` thấy ngay nhờ sentinel union sẵn có, không sửa gì bên agent. `kb_files.state` là sổ duy nhất — KHÔNG ghi `kb_index_state`, KHÔNG migration.

**Tech Stack:** FastAPI · asyncpg · pydantic · qdrant-client (đều sẵn có — không thêm dependency nào).

**Spec:** `docs/superpowers/specs/2026-08-20-dung-lai-duong-upload-kb-files-design.md` — đọc spec TRƯỚC khi làm task. Repo: `/Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-portal-backend`, nhánh `feat/kb-files-upload` (đã tồn tại).

## Global Constraints

- Mọi lệnh chạy từ repo root: `cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-portal-backend`.
- ⚠️ Working tree đang có sửa đổi CHƯA COMMIT của phiên khác ở `src/portal/modules/kb/settings.py`, `.env.example`, `deploy/odyssey-portal-backend.env.example` — **KHÔNG chạm 3 file này, KHÔNG `git add -A`/`git add .`** — chỉ `git add` từng file đích danh.
- Mọi SQL trên `tenant_data` phải mang vị từ `tenant_id = portal.current_tenant()` viết THẲNG trong string literal (cổng `tests/isolation` đọc TĨNH f-string, không expand biến).
- Không migration mới. Không sửa FE (`odyssey-portal-frontend`), không sửa repo agent.
- Commit message dạng `<type>: <mô tả>` (feat/fix/docs/test), KHÔNG kèm attribution/footer.
- Test: `uv run pytest <path> -q`. Lint đầy đủ là HAI lệnh: `uv run ruff check src tests` VÀ `uv run ruff format --check src tests` (bài học `make lint` 2026-08-14).
- Docstring/comment viết tiếng Việt theo giọng của module (giải thích VÌ SAO, không kể lại code làm gì).
- Mã lỗi HTTP dùng `loi.LoiPortal(code, status, message)` — envelope `{error:{code,message}}` do handler chung dựng.

---

### Task 1: Contracts — `TaiLieuOut`, hằng số, và cổng doc_type rời nhau

**Files:**
- Modify: `src/portal/modules/kb/contracts.py`
- Test (modify): `tests/modules/kb/test_doc_type_roi_nhau.py`

**Interfaces:**
- Produces: `TaiLieuOut` (pydantic BaseModel, field camelCase: `id:int · tenFile:str · loai:str · kichThuoc:int · state:str · chunkCount:int · loiMessage:str · uploadedAt:datetime · uploadedBy:str|None`), `LOAI_HO_TRO = ("pdf","docx","xlsx")`, `DOC_TYPE_KB_FILE = "kb_file"`, `KIND_KB_FILE_INDEX = "kb_file_index"` — Task 3/4/5/6 import các tên này từ `portal.modules.kb.contracts`.

- [ ] **Step 1: Viết test đỏ** — mở `tests/modules/kb/test_doc_type_roi_nhau.py`, sửa hàm `test_doc_type_cua_ba_bang_roi_nhau` để đưa kho kb_files vào phép kiểm rời-nhau. Thêm import và một entry vào `theo_bang`:

```python
from portal.modules.kb.contracts import TITLE_PREFIXES, doc_type_of, DOC_TYPE_KB_FILE
```

và ngay sau dòng `theo_bang["documents"] = cua_documents`:

```python
    # Kho «Tài liệu tra cứu» (kb_files) là nguồn thứ TƯ ghi vào <slug>_documents
    # (spec 2026-08-20). Vị từ xoá của nó cũng là doc_type — mất tính rời nhau
    # thì xoá một tệp tra cứu cuốn theo point của bảng khác cùng record_id.
    theo_bang["kb_files"] = {DOC_TYPE_KB_FILE}
```

- [ ] **Step 2: Chạy test, xác nhận ĐỎ đúng lý do**

Run: `uv run pytest tests/modules/kb/test_doc_type_roi_nhau.py -q`
Expected: FAIL `ImportError: cannot import name 'DOC_TYPE_KB_FILE'`

- [ ] **Step 3: Thêm vào `contracts.py`.** Đặt cạnh các hằng `KIND_*` sẵn có (tìm `KIND_INDEX` trong file):

```python
KIND_KB_FILE_INDEX = "kb_file_index"
"""Job nạp MỘT tệp của kho «Tài liệu tra cứu» — spec 2026-08-20."""

DOC_TYPE_KB_FILE = "kb_file"
"""doc_type của point kb_files trong `<slug>_documents`. PHẢI rời khỏi mọi doc_type
khác — nó là vị từ xoá; `tests/modules/kb/test_doc_type_roi_nhau.py` canh."""

LOAI_HO_TRO = ("pdf", "docx", "xlsx")
"""KB_01 §I.2 — khớp CHECK `kb_files_loai_check` của migration 0300.
Không hỗ trợ: ảnh scan không lớp chữ · file đặt mật khẩu."""
```

Và ở khu DTO của router (cạnh `IndexStatusOut` — theo đúng khuôn pydantic của nó; nếu file chưa import `BaseModel`/`datetime` thì thêm import):

```python
class TaiLieuOut(BaseModel):
    """Một hàng của màn «Tài liệu tra cứu». camelCase vì đây là hợp đồng HTTP —
    khớp từng field với `odyssey-portal-frontend/src/features/kb/api.ts` (FE không sửa gì)."""

    id: int
    tenFile: str
    loai: str
    kichThuoc: int
    state: str
    """`dang_xu_ly · san_sang · loi` — CHECK của migration 0300. Chỉ `san_sang`
    nghĩa là point đã lên Qdrant (BR06)."""
    chunkCount: int
    loiMessage: str
    """Rỗng trừ khi `state == 'loi'`. Phải nói LÝ DO VÀ CÁCH SỬA, không chỉ "Lỗi"."""
    uploadedAt: datetime
    uploadedBy: str | None
```

- [ ] **Step 4: Chạy lại test, XANH**

Run: `uv run pytest tests/modules/kb/test_doc_type_roi_nhau.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/contracts.py tests/modules/kb/test_doc_type_roi_nhau.py
git commit -m "feat(kb): hop dong kho tai lieu tra cuu — TaiLieuOut + doc_type kb_file"
```

---

### Task 2: `files_repo.py` — SQL của bảng `kb_files`

**Files:**
- Create: `src/portal/modules/kb/files_repo.py`
- Create: `tests/modules/kb/test_kb_files_router.py` (phần repo; Task 3/4 sẽ thêm test router vào cùng file)

**Interfaces:**
- Consumes: bảng `tenant_data.kb_files` (migration `0300`, đã có RLS FORCE).
- Produces (Task 3/5/6 dùng đúng chữ ký):
  - `HangTaiLieu` (dataclass frozen: `id:int · ten_file:str · s3_key:str · kich_thuoc:int · loai:str · state:str · chunk_count:int · loi_message:str · uploaded_at:datetime · uploaded_by:str|None`)
  - `async them(conn, *, ten_file, s3_key, kich_thuoc, loai, uploaded_by) -> HangTaiLieu`
  - `async liet_ke(conn) -> list[HangTaiLieu]`
  - `async doc(conn, record_id: int) -> HangTaiLieu | None`
  - `async xoa(conn, record_id: int) -> None`
  - `async danh_dau_san_sang(conn, *, record_id: int, chunk_count: int) -> None`
  - `async danh_dau_loi(conn, *, record_id: int, loi_message: str) -> None`

- [ ] **Step 1: Viết test đỏ** — tạo `tests/modules/kb/test_kb_files_router.py`:

```python
"""Kho «Tài liệu tra cứu» — repo SQL (Task 2) + 3 route /kb/files (Task 3, 4).

Khuôn của module: gọi thẳng hàm (module kb không có fixture client đăng nhập),
Principal dựng sẵn. user_id dùng `u_seed_test` — user seed toàn cục ở
tests/conftest.py, thoả FK `kb_files.uploaded_by → control.users(id)`.
"""

from portal.core.db.session import tenant_conn
from portal.modules.kb import files_repo

from .conftest import OTHER_TENANT, TENANT


async def _them_mau(pool, tenant: str, ten: str = "bao-gia.pdf") -> files_repo.HangTaiLieu:
    async with tenant_conn(pool, tenant) as conn:
        return await files_repo.them(
            conn,
            ten_file=ten,
            s3_key=f"tenants/{tenant}/kb/abc123/{ten}",
            kich_thuoc=1234,
            loai="pdf",
            uploaded_by="u_seed_test",
        )


async def test_them_roi_liet_ke_moi_nhat_truoc(api_pool, seed_kb):
    a = await _them_mau(api_pool, TENANT, "a.pdf")
    b = await _them_mau(api_pool, TENANT, "b.docx")
    async with tenant_conn(api_pool, TENANT) as conn:
        ds = await files_repo.liet_ke(conn)
    assert [t.id for t in ds][:2] == [b.id, a.id]  # mới nhất trước (uploaded_at DESC, id DESC)
    assert ds[0].state == "dang_xu_ly" and ds[0].chunk_count == 0 and ds[0].loi_message == ""


async def test_khong_thay_hang_cua_tenant_khac(api_pool, seed_kb):
    """RLS + vị từ app: OTHER_TENANT không thấy hàng của TENANT — bug cách ly ở đây
    trông y hệt chạy đúng nếu chỉ seed một tenant."""
    await _them_mau(api_pool, TENANT)
    async with tenant_conn(api_pool, OTHER_TENANT) as conn:
        assert await files_repo.liet_ke(conn) == []


async def test_doc_xoa_va_danh_dau(api_pool, seed_kb):
    t = await _them_mau(api_pool, TENANT)
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=7)
        sau = await files_repo.doc(conn, t.id)
        assert sau is not None and (sau.state, sau.chunk_count) == ("san_sang", 7)

        await files_repo.danh_dau_loi(conn, record_id=t.id, loi_message="hỏng thử")
        sau = await files_repo.doc(conn, t.id)
        assert sau is not None and (sau.state, sau.loi_message) == ("loi", "hỏng thử")

        await files_repo.xoa(conn, t.id)
        assert await files_repo.doc(conn, t.id) is None
```

- [ ] **Step 2: Chạy, xác nhận ĐỎ** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → FAIL `ModuleNotFoundError`/`ImportError` cho `files_repo`.

- [ ] **Step 3: Viết `src/portal/modules/kb/files_repo.py`:**

```python
"""SQL của `tenant_data.kb_files` — sổ DUY NHẤT của kho «Tài liệu tra cứu».

KHÔNG ghi `kb_index_state` cho kho này (spec 2026-08-20 §5): CHECK `entity` của bảng
đó không nhận 'kb_files', reconcile chưa có thân, và vị từ xoá không cần tra sổ vì
`doc_type='kb_file'` là hằng. Hàng `san_sang` nghĩa là point ĐÃ lên Qdrant — service
đánh dấu SAU CÙNG, đúng thứ tự bốn-bước của bản M6 gốc (commit 0390d86).
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

_COT = "id, ten_file, s3_key, kich_thuoc, loai, state, chunk_count, loi_message, uploaded_at, uploaded_by"


@dataclass(frozen=True, slots=True)
class HangTaiLieu:
    id: int
    ten_file: str
    s3_key: str
    kich_thuoc: int
    loai: str
    state: str
    chunk_count: int
    loi_message: str
    uploaded_at: datetime
    uploaded_by: str | None


def _hang(r: asyncpg.Record) -> HangTaiLieu:
    return HangTaiLieu(
        id=r["id"],
        ten_file=r["ten_file"],
        s3_key=r["s3_key"],
        kich_thuoc=r["kich_thuoc"],
        loai=r["loai"],
        state=r["state"],
        chunk_count=r["chunk_count"],
        loi_message=r["loi_message"],
        uploaded_at=r["uploaded_at"],
        uploaded_by=r["uploaded_by"],
    )


async def them(
    conn: asyncpg.Connection, *, ten_file: str, s3_key: str, kich_thuoc: int, loai: str, uploaded_by: str | None
) -> HangTaiLieu:
    r = await conn.fetchrow(
        "INSERT INTO tenant_data.kb_files (tenant_id, ten_file, s3_key, kich_thuoc, loai, uploaded_by) "
        f"VALUES (portal.current_tenant(), $1, $2, $3, $4, $5) RETURNING {_COT}",
        ten_file,
        s3_key,
        kich_thuoc,
        loai,
        uploaded_by,
    )
    return _hang(r)


async def liet_ke(conn: asyncpg.Connection) -> list[HangTaiLieu]:
    """Mới nhất trước — khớp index `kb_files_tenant_moi_idx` (tenant_id, uploaded_at DESC)."""
    rows = await conn.fetch(
        f"SELECT {_COT} FROM tenant_data.kb_files "
        "WHERE tenant_id = portal.current_tenant() ORDER BY uploaded_at DESC, id DESC"
    )
    return [_hang(r) for r in rows]


async def doc(conn: asyncpg.Connection, record_id: int) -> HangTaiLieu | None:
    r = await conn.fetchrow(
        f"SELECT {_COT} FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    return None if r is None else _hang(r)


async def xoa(conn: asyncpg.Connection, record_id: int) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant() AND id = $1", record_id
    )


async def danh_dau_san_sang(conn: asyncpg.Connection, *, record_id: int, chunk_count: int) -> None:
    await conn.execute(
        "UPDATE tenant_data.kb_files SET state = 'san_sang', chunk_count = $2, loi_message = '' "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        chunk_count,
    )


async def danh_dau_loi(conn: asyncpg.Connection, *, record_id: int, loi_message: str) -> None:
    await conn.execute(
        "UPDATE tenant_data.kb_files SET state = 'loi', loi_message = $2 "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
        loi_message,
    )
```

- [ ] **Step 4: Chạy, XANH** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → PASS (3 bài).

- [ ] **Step 5: Cổng cách ly phải giữ baseline** — `uv run pytest tests/isolation -q`. Expected: KHÔNG dòng đỏ MỚI nào trỏ vào `files_repo.py` (baseline hiện tại của repo giữ nguyên).

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/files_repo.py tests/modules/kb/test_kb_files_router.py
git commit -m "feat(kb): files_repo — SQL kho kb_files"
```

---

### Task 3: Router — `GET /kb/files` + `POST /kb/files`

**Files:**
- Modify: `src/portal/modules/kb/router.py`
- Test (modify): `tests/modules/kb/test_kb_files_router.py`

**Interfaces:**
- Consumes: `files_repo` (Task 2), `TaiLieuOut/LOAI_HO_TRO/KIND_KB_FILE_INDEX` (Task 1), `object_store()` từ `portal.modules.kb.jobs` (sẵn có), `enqueue` từ `portal.core.jobs`, `nhat_ky.ghi` từ `portal.core.nhat_ky`.
- Produces: handler `kb_liet_ke(p, pool)`, `kb_tai_len(file, p, pool)` — Task 4 thêm `kb_xoa` vào cùng file; hàm `_ra_tai_lieu(t) -> TaiLieuOut` và `GIOI_HAN_BYTE` dùng chung.

- [ ] **Step 1: Viết test đỏ** — thêm vào `tests/modules/kb/test_kb_files_router.py`:

```python
import io
import json

import pytest
from fastapi import UploadFile

from portal.api.loi import LoiPortal
from portal.core.auth.principal import Principal
from portal.modules.kb import router
from portal.modules.kb.contracts import KIND_KB_FILE_INDEX
from portal.modules.kb.fake import FakeObjectStore

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())


@pytest.fixture
def fake_store(monkeypatch):
    """Router lấy kho tệp qua tên module-level `object_store` — patch đúng tên đó."""
    store = FakeObjectStore()
    monkeypatch.setattr(router, "object_store", lambda: store)
    return store


def _up(ten: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=ten)


async def test_get_kho_rong_tra_mang_rong(api_pool, seed_kb):
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []


async def test_post_202_ghi_s3_hang_va_job(api_pool, seed_kb, fake_store):
    ra = await router.kb_tai_len(file=_up("Báo giá Q3.pdf", b"%PDF-fake"), p=_P, pool=api_pool)

    # Hàng: tên GỐC giữ nguyên (kể cả dấu + khoảng trắng), trạng thái khởi đầu.
    assert (ra.tenFile, ra.loai, ra.state, ra.chunkCount) == ("Báo giá Q3.pdf", "pdf", "dang_xu_ly", 0)
    assert ra.uploadedBy == "u_seed_test"

    # Tệp nằm trong kho, key mang tiền tố tenant + tên ASCII lành (không dấu, không khoảng trắng).
    (key,) = fake_store.stored
    assert key.startswith(f"tenants/{TENANT}/kb/") and key.endswith("/Bao-gia-Q3.pdf")

    # Job được xếp đúng tenant, đúng kind, payload trỏ đúng hàng.
    async with tenant_conn(api_pool, TENANT) as conn:
        job = await conn.fetchrow(
            "SELECT kind, payload FROM control.jobs WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1", TENANT
        )
    assert job["kind"] == KIND_KB_FILE_INDEX
    payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
    assert payload["record_id"] == ra.id

    # Nhật ký kb.upload — KB_01 BR09.
    async with tenant_conn(api_pool, TENANT) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'kb.upload'", TENANT
        )
    assert n == 1


async def test_post_duoi_la_422(api_pool, seed_kb, fake_store):
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("virus.exe", b"xx"), p=_P, pool=api_pool)
    assert e.value.code == "UNSUPPORTED_TYPE"
    assert fake_store.stored == {}  # từ chối TRƯỚC khi chạm kho tệp


async def test_post_qua_tran_va_rong_422(api_pool, seed_kb, fake_store):
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("to.pdf", b"x" * (router.GIOI_HAN_BYTE + 1)), p=_P, pool=api_pool)
    assert e.value.code == "FILE_TOO_LARGE"
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("rong.pdf", b""), p=_P, pool=api_pool)
    assert e.value.code == "FILE_TOO_LARGE"
```

Lưu ý cho người thi công: `LoiPortal` — đọc `src/portal/api/loi.py` để lấy đúng tên thuộc tính mã lỗi (nếu là `ma`/`code` khác nhau thì sửa assert theo, KHÔNG sửa class).

- [ ] **Step 2: Chạy, ĐỎ** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → FAIL `AttributeError: ... has no attribute 'kb_liet_ke'`.

- [ ] **Step 3: Thêm vào `src/portal/modules/kb/router.py`.** Bổ sung import (gộp vào các dòng import sẵn có):

```python
import hashlib
import logging
import re
import unicodedata

from fastapi import APIRouter, Depends, File, UploadFile

from portal.core import nhat_ky
from portal.core.jobs import enqueue
from portal.modules.kb import files_repo
from portal.modules.kb.contracts import KIND_KB_FILE_INDEX, LOAI_HO_TRO, IndexStatusOut, TaiLieuOut
from portal.modules.kb.jobs import object_store

log = logging.getLogger(__name__)
```

Rồi thêm khối route (cuối file):

```python
# ─── Kho «Tài liệu tra cứu» — 3 route của màn /kb (spec 2026-08-20) ────────────────

GIOI_HAN_BYTE = 25 * 1024 * 1024
"""⚠️ CON SỐ TẠM — KB_01 BR12 để ngưỡng dung lượng chưa chốt (đầu vào bảng giá).
Giữ nguyên 25 MB của bản M6 gốc. Đặt ở router như bản gốc, KHÔNG đưa vào
settings.py (file đó đang có sửa đổi chưa commit của phiên khác)."""

_FILE = File(...)


def _loai_khong_ho_tro() -> "loi.LoiPortal":
    return loi.LoiPortal("UNSUPPORTED_TYPE", 422, "Chỉ nhận file PDF, DOCX hoặc XLSX")


def _qua_dung_luong() -> "loi.LoiPortal":
    return loi.LoiPortal("FILE_TOO_LARGE", 422, "File vượt dung lượng cho phép (25 MB)")


def _khong_co_tai_lieu() -> "loi.LoiPortal":
    return loi.LoiPortal("NO_DOCUMENT", 404, "Không tìm thấy tài liệu")


def _ten_lanh(ten: str) -> str:
    """Tên tệp trong key S3 rút về ASCII lành — key là ĐỊNH DANH, không phải tên hiển thị
    (tên gốc nằm ở cột ten_file). Unicode/khoảng trắng trong key bắt mọi chỗ đọc
    (presign, public_url) gánh encoding, và đó là chỗ lệch nhau âm thầm."""
    mo = unicodedata.normalize("NFKD", ten).encode("ascii", "ignore").decode()
    mo = re.sub(r"[^A-Za-z0-9._-]+", "-", mo).strip("-.")
    return mo or "tep"


def _ra_tai_lieu(t: files_repo.HangTaiLieu) -> TaiLieuOut:
    return TaiLieuOut(
        id=t.id,
        tenFile=t.ten_file,
        loai=t.loai,
        kichThuoc=t.kich_thuoc,
        state=t.state,
        chunkCount=t.chunk_count,
        loiMessage=t.loi_message,
        uploadedAt=t.uploaded_at,
        uploadedBy=t.uploaded_by,
    )


@ROUTER.get("/kb/files", response_model=list[TaiLieuOut])
async def kb_liet_ke(
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[TaiLieuOut]:
    """Kho rỗng trả [] — đó là trạng thái bình thường của workspace mới (BR04)."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        return [_ra_tai_lieu(t) for t in await files_repo.liet_ke(conn)]


@ROUTER.post("/kb/files", status_code=202, response_model=TaiLieuOut)
async def kb_tai_len(
    file: UploadFile = _FILE,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaiLieuOut:
    """202 — bóc chữ và nhúng chạy BẤT ĐỒNG BỘ qua job `kb_file_index`.

    Trả về sau khi index xong nghĩa là người dùng nhìn spinner vài phút cho một
    tệp lớn, và request timeout trước khi job xong (KB_01 §I.2, giữ từ bản gốc).
    """
    ten_goc = file.filename or ""
    loai_tep = ten_goc.rsplit(".", 1)[-1].lower()
    if loai_tep not in LOAI_HO_TRO:
        raise _loai_khong_ho_tro()

    noi_dung = await file.read()
    if not noi_dung or len(noi_dung) > GIOI_HAN_BYTE:
        raise _qua_dung_luong()

    # Lên kho tệp TRƯỚC khi ghi hàng: hàng trỏ tới một s3_key không tồn tại là một
    # tài liệu job không bao giờ nạp được, và nó đứng mãi ở «Đang xử lý» (bài học 0390d86).
    sha = hashlib.sha256(noi_dung).hexdigest()
    store = object_store()
    key = store.key(tenant_id=p.tenant_id, path=f"kb/{sha}/{_ten_lanh(ten_goc)}")
    await store.put(key=key, data=noi_dung, content_type=file.content_type or "application/octet-stream")

    async with tenant_conn(pool, p.tenant_id) as conn:
        t = await files_repo.them(
            conn, ten_file=ten_goc, s3_key=key, kich_thuoc=len(noi_dung), loai=loai_tep, uploaded_by=p.user_id
        )
        await enqueue(
            conn, tenant_id=p.tenant_id, kind=KIND_KB_FILE_INDEX, actor=p.user_id, payload={"record_id": t.id}
        )
        await nhat_ky.ghi(conn, p.tenant_id, "kb.upload", p.user_id, {"file_id": t.id, "ten_file": t.ten_file})
    return _ra_tai_lieu(t)
```

Lưu ý thi công: router đã import `from portal.api import loi` sẵn — giữ nguyên cách gọi `loi.LoiPortal`. Nếu `LoiPortal.__init__` có chữ ký khác `(code, status, message)` thì đọc `src/portal/api/loi.py` và theo nó (các route hiện có trong file này đã gọi đúng — bắt chước).

- [ ] **Step 4: Chạy, XANH** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → PASS.

- [ ] **Step 5: Cổng route-khai-action + toàn module** — `uv run pytest tests/modules/kb tests/api -q` (cổng `test_moi_route_khai_action` quét mọi APIRoute — hai route mới đã dùng `require()` nên phải xanh; nếu cổng đó nằm chỗ khác thì `grep -rn "khai_action" tests/` để tìm và chạy đúng file). Expected: PASS, không hồi quy.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/router.py tests/modules/kb/test_kb_files_router.py
git commit -m "feat(kb): GET/POST /kb/files — upload vao kho, enqueue kb_file_index"
```

---

### Task 4: Router — `DELETE /kb/files/{file_id}`

**Files:**
- Modify: `src/portal/modules/kb/router.py`
- Test (modify): `tests/modules/kb/test_kb_files_router.py`

**Interfaces:**
- Consumes: `files_repo` (Task 2), `DOC_TYPE_KB_FILE` (Task 1), `QdrantStore.delete_by_record` (sẵn có — trả 0 êm khi collection chưa tồn tại), `collection_name` từ `clients/rag.py`.
- Produces: handler `kb_xoa(file_id, p, pool)`; factory module-level `_qdrant_store()` (test patch tên này).

- [ ] **Step 1: Viết test đỏ** — thêm vào `tests/modules/kb/test_kb_files_router.py`:

```python
class _QdrantGia:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, int, str]] = []
        self.closed = False

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str = "") -> int:
        self.deleted.append((name, record_id, doc_type))
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def qdrant_gia(monkeypatch):
    q = _QdrantGia()
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)
    return q


async def test_delete_go_point_truoc_xoa_hang(api_pool, seed_kb, fake_store, qdrant_gia):
    ra = await router.kb_tai_len(file=_up("xoa-toi.pdf", b"%PDF-fake"), p=_P, pool=api_pool)
    await router.kb_xoa(ra.id, p=_P, pool=api_pool)

    assert qdrant_gia.deleted == [(f"{TENANT}_documents", ra.id, "kb_file")]
    assert qdrant_gia.closed  # client Qdrant phải được đóng — worker sống dài đã dạy bài này
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []
    assert fake_store.stored == {}  # tệp S3 cũng đi

    async with tenant_conn(api_pool, TENANT) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'kb.delete'", TENANT
        )
    assert n == 1


async def test_delete_s3_hong_van_xoa_duoc_hang(api_pool, seed_kb, fake_store, qdrant_gia, monkeypatch):
    """S3 là best-effort: object content-addressed nằm lại vô hại, còn point + hàng PHẢI đi."""
    ra = await router.kb_tai_len(file=_up("s3-hong.pdf", b"%PDF-fake"), p=_P, pool=api_pool)

    async def _no(*, key: str) -> None:
        raise RuntimeError("minio sập giả lập")

    monkeypatch.setattr(fake_store, "delete", _no)
    await router.kb_xoa(ra.id, p=_P, pool=api_pool)
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []


async def test_delete_id_la_404(api_pool, seed_kb, qdrant_gia):
    with pytest.raises(LoiPortal) as e:
        await router.kb_xoa(999_999, p=_P, pool=api_pool)
    assert e.value.code == "NO_DOCUMENT"
    assert qdrant_gia.deleted == []  # 404 thì không chạm Qdrant
```

- [ ] **Step 2: Chạy, ĐỎ** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → FAIL `AttributeError: kb_xoa`.

- [ ] **Step 3: Thêm vào `router.py`** (import bổ sung: `from portal.modules.kb.clients.rag import collection_name` và `from portal.modules.kb.index.store import QdrantStore`):

```python
def _qdrant_store() -> QdrantStore:
    """Xoá point KHÔNG đi qua `open_dependencies()`: bộ đó dựng cả EmbedClient (raise
    khi thiếu KB_SANTA_MODELS_TOKEN), mà xoá point không cần embed — cùng lý lẽ
    `ops/collections.xoa_kho_cua_workspace` đã ghi."""
    from portal.core.config import get_settings

    cfg = get_settings()
    return QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)


@ROUTER.delete("/kb/files/{file_id}", status_code=204)
async def kb_xoa(
    file_id: int,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    """BR07 — gỡ khỏi kho tri thức NGAY, trong cùng thao tác. Không thùng rác.

    Thứ tự là quyết định: point Qdrant TRƯỚC → hàng DB → tệp S3 (best-effort).
    Chết giữa chừng theo chiều này để lại tài nguyên mồ côi vô hại (tệp không ai
    trỏ tới); chiều ngược lại để lại point mà agent vẫn trích dẫn cho một tài liệu
    người dùng đã thấy biến mất khỏi màn (bài học 0390d86).
    `delete_by_record` trả 0 êm khi collection chưa tồn tại (job chưa từng chạy).
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        t = await files_repo.doc(conn, file_id)
        if t is None:
            raise _khong_co_tai_lieu()

        q = _qdrant_store()
        try:
            await q.delete_by_record(collection_name(p.tenant_id), record_id=file_id, doc_type=DOC_TYPE_KB_FILE)
        finally:
            await q.aclose()

        await files_repo.xoa(conn, file_id)
        try:
            await object_store().delete(key=t.s3_key)
        except Exception as e:  # noqa: BLE001 — best-effort, xem docstring
            log.warning("xoá tệp S3 %s bỏ qua: %s: %s", t.s3_key, type(e).__name__, e)
        await nhat_ky.ghi(conn, p.tenant_id, "kb.delete", p.user_id, {"file_id": file_id, "ten_file": t.ten_file})
```

Nhớ thêm `DOC_TYPE_KB_FILE` vào dòng import từ `contracts` (Task 3 đã import `KIND_KB_FILE_INDEX, LOAI_HO_TRO, TaiLieuOut`).

- [ ] **Step 4: Chạy, XANH** — `uv run pytest tests/modules/kb/test_kb_files_router.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/router.py tests/modules/kb/test_kb_files_router.py
git commit -m "feat(kb): DELETE /kb/files/{id} — go point truoc, hang sau, S3 best-effort"
```

---

### Task 5: `service.index_kb_file()` — orchestration nạp một tệp

**Files:**
- Modify: `src/portal/modules/kb/service.py`
- Create: `tests/modules/kb/test_kb_file_index_job.py`

**Interfaces:**
- Consumes: `files_repo` (Task 2), `DOC_TYPE_KB_FILE` (Task 1), `TextExtractor` (import ở MODULE TOP của service.py — test monkeypatch `service.TextExtractor`), `collections.create` (import trong thân hàm, theo nếp jobs.py), `TextDirective/ChunkSpec` từ contracts, `settings.SYSTEM_ANCHOR`.
- Produces: `async index_kb_file(conn, *, tenant_id: str, slug: str, record_id: int, rag: IndexClient, media: IndexClient, store: ObjectStore) -> str` (message cho JobResult); hằng `THONG_DIEP_KHONG_CO_CHU` (Task 6 và test dùng). Ném exception cho lỗi HẠ TẦNG (handler Task 6 bắt); lỗi NỘI DUNG tự đánh dấu `loi` và trả message.

- [ ] **Step 1: Viết test đỏ** — tạo `tests/modules/kb/test_kb_file_index_job.py`:

```python
"""service.index_kb_file + handler kb_file_index — pipeline kho «Tài liệu tra cứu».

Extraction chạy THẬT trên docx dựng trong test (python-docx là dependency sẵn);
embed/Qdrant là FakeIndexClient; kho tệp là FakeObjectStore.
"""

import io

import docx
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import files_repo, service
from portal.modules.kb import settings as kb_settings
from portal.modules.kb.clients.extract import ExtractResult
from portal.modules.kb.contracts import DOC_TYPE_KB_FILE
from portal.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import TENANT


def _docx_bytes(doan: str) -> bytes:
    d = docx.Document()
    d.add_heading("Chính sách chung", level=1)
    d.add_paragraph(doan)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def _hang_moi(pool, ten: str, data: bytes, store: FakeObjectStore) -> files_repo.HangTaiLieu:
    key = f"tenants/{TENANT}/kb/sha-gia/{ten}"
    store.stored[key] = data
    async with tenant_conn(pool, TENANT) as conn:
        return await files_repo.them(
            conn, ten_file=ten, s3_key=key, kich_thuoc=len(data), loai=ten.rsplit(".", 1)[-1], uploaded_by=None
        )


async def test_nap_docx_thanh_san_sang(api_pool, seed_kb):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    t = await _hang_moi(api_pool, "chinh-sach.docx", _docx_bytes("Ưu đãi thanh toán sớm 3%."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        msg = await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=media, store=store
        )

    assert "+1 point" in msg
    # Collection được dựng trước (idempotent) — upload có thể là hành động KB đầu tiên.
    assert rag.created_collections == [TENANT] and media.created_collections == [TENANT]

    (d,) = rag.indexed
    assert (d.doc_type, d.anchor_code, d.status, d.anchor_status) == (
        DOC_TYPE_KB_FILE,
        kb_settings.SYSTEM_ANCHOR,
        "published",
        "published",
    )
    assert d.anchor_name == "chinh-sach.docx" and d.file_name == "chinh-sach.docx"
    assert "Ưu đãi thanh toán" in d.text

    async with tenant_conn(api_pool, TENANT) as conn:
        sau = await files_repo.doc(conn, t.id)
    assert sau is not None and (sau.state, sau.chunk_count) == ("san_sang", 1)


async def test_khong_co_chu_thanh_loi_co_chi_duong(api_pool, seed_kb, monkeypatch):
    """PDF scan → ExtractResult(text='') → hàng `loi`, message nói LÝ DO VÀ CÁCH SỬA."""

    class _KhongChu:
        def __init__(self, *, vlm=None) -> None: ...

        async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
            return ExtractResult(text="")

    monkeypatch.setattr(service, "TextExtractor", _KhongChu)
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    t = await _hang_moi(api_pool, "scan.pdf", b"%PDF-fake-scan", store)

    async with tenant_conn(api_pool, TENANT) as conn:
        await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=t.id, rag=rag, media=media, store=store
        )
        sau = await files_repo.doc(conn, t.id)

    assert sau is not None and sau.state == "loi"
    assert "duyệt OCR" in sau.loi_message  # cách sửa phải nằm trong message
    assert rag.indexed == []  # không nhúng gì


async def test_hang_da_bi_xoa_thi_bo_qua_em(api_pool, seed_kb):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    async with tenant_conn(api_pool, TENANT) as conn:
        msg = await service.index_kb_file(
            conn, tenant_id=TENANT, slug=TENANT, record_id=987_654, rag=rag, media=media, store=store
        )
    assert "bỏ qua" in msg and rag.indexed == []
```

- [ ] **Step 2: Chạy, ĐỎ** — `uv run pytest tests/modules/kb/test_kb_file_index_job.py -q` → FAIL `AttributeError: ... 'index_kb_file'`.

- [ ] **Step 3: Thêm vào `service.py`.** Import bổ sung ở đầu file: `from portal.modules.kb import files_repo`, `from portal.modules.kb.clients.extract import TextExtractor` (module top — test monkeypatch qua tên `service.TextExtractor`), và thêm `ChunkSpec`, `TextDirective`, `DOC_TYPE_KB_FILE` vào dòng import từ `contracts`. Thân hàm:

```python
THONG_DIEP_KHONG_CO_CHU = (
    "Không bóc được chữ từ tệp này — PDF dạng scan chưa hỗ trợ ở kho Tài liệu tra cứu. "
    "Tải bản có lớp chữ, hoặc nạp vào tài liệu của một dự án để đi qua luồng duyệt OCR."
)


async def index_kb_file(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    slug: str,
    record_id: int,
    rag: IndexClient,
    media: IndexClient,
    store: ObjectStore,
) -> str:
    """Nạp MỘT tệp của kho «Tài liệu tra cứu» (spec 2026-08-20 §4).

    Thứ tự là lời hứa — đánh dấu `san_sang` SAU CÙNG: hỏng ở bước nào trước đó thì
    hàng ở `dang_xu_ly`/`loi`, và BR06 nói chỉ hàng `san_sang` là đã lên Qdrant.

    Lỗi NỘI DUNG (không có lớp chữ) tự đánh dấu `loi` tại đây — người dùng sửa được.
    Lỗi HẠ TẦNG (S3/embed/Qdrant) NÉM lên cho handler đánh dấu — phân loại ở một chỗ.

    KHÔNG ghi `kb_index_state`: kb_files là sổ duy nhất (spec §5 — CHECK entity của
    sổ kia không nhận 'kb_files', và vị từ xoá là hằng doc_type nên không cần tra).

    KHÔNG truyền VLM: màn /kb không có UI duyệt, và «model sinh ⇒ người xem» —
    chữ OCR không được tự nạp (KB_01 §I.2 loại trừ scan từ đầu).
    """
    from portal.modules.kb.ops import collections

    row = await files_repo.doc(conn, record_id)
    if row is None:
        return f"kb_files#{record_id}: hàng không còn, bỏ qua"

    # Idempotent — upload có thể là hành động KB đầu tiên của workspace; thiếu bước
    # này job nổ 404 ở delete_by_record (bài học handle_sync_project).
    await collections.create(rag=rag, media=media, workspace_slug=slug)

    data = await store.doc(key=store.key(tenant_id=tenant_id, path=row.s3_key))
    ra = await TextExtractor(vlm=None).extract(data, filename=row.ten_file)
    if not ra.text:
        await files_repo.danh_dau_loi(conn, record_id=record_id, loi_message=THONG_DIEP_KHONG_CO_CHU)
        return f"kb_files#{record_id}: không có lớp chữ, đã đánh dấu lỗi"

    directive = TextDirective(
        workspace_slug=slug,
        record_id=record_id,
        doc_type=DOC_TYPE_KB_FILE,
        anchor_code=settings.SYSTEM_ANCHOR,
        anchor_name=row.ten_file,
        section="",
        text=ra.text,
        chunk=ChunkSpec(),
        status="published",
        anchor_status="published",
        updated_at=row.uploaded_at,
        file_url=row.s3_key,
        file_name=row.ten_file,
    )
    result = await rag.index(directive)
    await files_repo.danh_dau_san_sang(conn, record_id=record_id, chunk_count=result.points_upserted)
    return f"kb_files#{record_id}: +{result.points_upserted} point"
```

- [ ] **Step 4: Chạy, XANH** — `uv run pytest tests/modules/kb/test_kb_file_index_job.py -q` → PASS (3 bài).

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/service.py tests/modules/kb/test_kb_file_index_job.py
git commit -m "feat(kb): service.index_kb_file — boc chu, nhung, danh dau san_sang sau cung"
```

---

### Task 6: Handler `kb_file_index` — bắt rộng, hàng không bao giờ treo

**Files:**
- Modify: `src/portal/modules/kb/jobs.py`
- Test (modify): `tests/modules/kb/test_kb_file_index_job.py`

**Interfaces:**
- Consumes: `service.index_kb_file` (Task 5), `files_repo.danh_dau_loi` (Task 2), `KIND_KB_FILE_INDEX` (Task 1), `open_dependencies()`/`workspace_slug()` (sẵn có trong jobs.py).
- Produces: `async handle_kb_file_index(conn, payload) -> JobResult`, đăng ký `register(KIND_KB_FILE_INDEX, handle_kb_file_index, retries=0)`.

- [ ] **Step 1: Viết test đỏ** — thêm vào `tests/modules/kb/test_kb_file_index_job.py`:

```python
from portal.core.jobs import retries_of
from portal.modules.kb import jobs
from portal.modules.kb.contracts import KIND_KB_FILE_INDEX


class _RagNo(FakeIndexClient):
    async def index(self, directive):
        raise RuntimeError("embed sập giả lập")


@pytest.fixture
def bo_gia(monkeypatch):
    """Handler lấy client qua jobs.dependencies() — patch đúng tên đó; open_dependencies
    bọc quanh và chỉ gọi aclose nếu có (fake không có, getattr trả None)."""
    bo = (FakeIndexClient(), FakeIndexClient(), FakeObjectStore())
    monkeypatch.setattr(jobs, "dependencies", lambda: bo)
    return bo


async def test_handler_duong_thuong(api_pool, seed_kb, bo_gia):
    rag, _media, store = bo_gia
    t = await _hang_moi(api_pool, "qua-job.docx", _docx_bytes("Nội dung đi qua handler."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 1 and len(rag.indexed) == 1
    assert sau is not None and sau.state == "san_sang"


async def test_handler_loi_ha_tang_khong_treo_hang(api_pool, seed_kb, monkeypatch):
    """Chế độ hỏng tệ nhất của bản M6 gốc là hàng treo `dang_xu_ly` vĩnh viễn (spinner
    quay mãi). Handler phải nuốt lỗi hạ tầng, đánh dấu `loi`, và KHÔNG ném — ném là
    rollback luôn cả cú UPDATE vừa ghi."""
    store = FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (_RagNo(), FakeIndexClient(), store))
    t = await _hang_moi(api_pool, "ha-tang-hong.docx", _docx_bytes("Sẽ không lên được Qdrant."), store)

    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": t.id})
        sau = await files_repo.doc(conn, t.id)

    assert ra.count == 0 and "RuntimeError" in ra.message
    assert sau is not None and sau.state == "loi" and sau.loi_message != ""


async def test_handler_hang_bien_mat_bo_qua(api_pool, seed_kb, bo_gia):
    async with tenant_conn(api_pool, TENANT) as conn:
        ra = await jobs.handle_kb_file_index(conn, {"record_id": 111_222})
    assert ra.count == 0 and "bỏ qua" in ra.message


def test_kind_dang_ky_khong_retry():
    """retries=0 là CHỦ Ý: handler không bao giờ ném nên retry ở tầng job là vô nghĩa;
    retry transient đã nằm trong EmbedClient."""
    assert retries_of(KIND_KB_FILE_INDEX) == 0
```

- [ ] **Step 2: Chạy, ĐỎ** — `uv run pytest tests/modules/kb/test_kb_file_index_job.py -q` → FAIL `AttributeError: handle_kb_file_index`.

- [ ] **Step 3: Thêm vào `jobs.py`.** Import bổ sung: `from portal.modules.kb import files_repo` (đầu file, cạnh `from portal.modules.kb import service, settings`) và thêm `KIND_KB_FILE_INDEX` vào khối import từ `contracts`. Handler đặt cạnh `handle_index`:

```python
async def handle_kb_file_index(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Nạp một tệp của kho «Tài liệu tra cứu». BẮT RỘNG có chủ ý (spec 2026-08-20 §4):

    hàng treo `dang_xu_ly` vĩnh viễn là chế độ hỏng tệ nhất (spinner quay mãi — bài học
    ghi trong commit 0390d86), nên MỌI thất bại phải kết thúc ở `loi` với message chỉ
    đường. Không re-raise: handler chạy trong giao dịch của worker, ném là rollback luôn
    cú UPDATE `loi` vừa ghi — vì thế phần nạp chạy trong SAVEPOINT (conn.transaction()
    lồng) để lỗi Postgres giữa chừng không đầu độc giao dịch ngoài. Retry transient đã
    nằm trong EmbedClient; đăng ký retries=0.
    """
    record_id = int(payload["record_id"])
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    slug = workspace_slug(tenant_id)
    try:
        async with conn.transaction():
            async with open_dependencies() as (rag, media, store):
                msg = await service.index_kb_file(
                    conn, tenant_id=tenant_id, slug=slug, record_id=record_id, rag=rag, media=media, store=store
                )
        return JobResult(count=0 if "bỏ qua" in msg or "lỗi" in msg else 1, message=msg)
    except Exception as e:  # noqa: BLE001 — xem docstring
        log.warning("kb_file_index #%s: %s: %s", record_id, type(e).__name__, e)
        await files_repo.danh_dau_loi(
            conn, record_id=record_id, loi_message="Lỗi hệ thống khi nạp tài liệu — thử tải lại tệp."
        )
        return JobResult(count=0, message=f"kb_files#{record_id}: {type(e).__name__}: {e}")
```

Và ở khối `register(...)` cuối file:

```python
register(KIND_KB_FILE_INDEX, handle_kb_file_index, retries=0)
```

- [ ] **Step 4: Chạy, XANH** — `uv run pytest tests/modules/kb/test_kb_file_index_job.py -q` → PASS.

- [ ] **Step 5: Chạy TRỌN module kb** — `uv run pytest tests/modules/kb -q`. Expected: PASS toàn bộ (không hồi quy các bài sẵn có).

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/jobs.py tests/modules/kb/test_kb_file_index_job.py
git commit -m "feat(kb): handler kb_file_index — bat rong, hang khong bao gio treo dang_xu_ly"
```

---

### Task 7: Hợp đồng payload + Change Log + lint

**Files:**
- Modify: `docs/contracts/payload-qdrant.md`
- Modify: `CLAUDE.md` (repo backend — MỘT dòng Change Log; ⚠️ file đang chứa một cặp conflict marker `<<<<<<< HEAD`/`>>>>>>> develop` có sẵn trong bảng Change Log — KHÔNG sửa/dọn nó, chỉ thêm dòng mới lên ĐẦU bảng, ngoài vùng conflict)

**Interfaces:** không — task tài liệu + cổng chất lượng.

- [ ] **Step 1: Thêm mục `kb_file` vào `docs/contracts/payload-qdrant.md`.** Đọc cấu trúc file trước, thêm một mục theo đúng khuôn các doc_type sẵn có, nội dung PHẢI có đủ các ý:

```markdown
## doc_type `kb_file` — kho «Tài liệu tra cứu» (màn /kb, spec 2026-08-20)

Point nằm trong `<tenant>_documents`, nguồn là bảng `tenant_data.kb_files`
(KHÔNG phải `documents` — kho thứ tư ghi vào collection này, sổ của nó là chính
`kb_files.state`, không có dòng `kb_index_state` nào).

- `project_id` = `"__ALL__"` — nội dung cấp workspace; kb_search hợp lệ nhờ
  sentinel union sẵn có phía agent (`data/qdrant_search.py::build_scope_filter`).
- `project_name` = **tên tệp** (wart có chủ ý: không có dự án nào để gọi tên;
  chỗ render của agent dùng khoá này làm nhãn ngữ cảnh, tên tệp là nhãn đúng
  nhất hiện có).
- `record_id` = `kb_files.id` · `status` luôn `"published"` (kho này không có
  khái niệm nháp — BR06 gắn vào `kb_files.state`, chỉ hàng `san_sang` có point).
- `file_public_url`/`file_name` mang link + tên tệp để agent gửi được tệp gốc.
- Vị từ xoá: `(doc_type='kb_file', record_id)` — tính rời nhau của doc_type do
  `tests/modules/kb/test_doc_type_roi_nhau.py` canh.
```

- [ ] **Step 2: Thêm MỘT dòng vào đầu bảng Change Log của `CLAUDE.md`:**

```markdown
| 2026-08-20 | **Dựng lại đường upload màn «Tài liệu tra cứu»** — 3 route `GET/POST/DELETE /kb/files` + job `kb_file_index` (spec `2026-08-20-dung-lai-duong-upload-kb-files-design.md`). Route cũ bị xoá khi merge `66ff3e7` chọn phương án A của `MERGE-REVIEW-kb.md` mà không ai nối lại. Kho dùng bảng `kb_files` sẵn có (`0300`, không migration), nạp qua đúng pipeline hiện hành (`TextExtractor(vlm=None)` → `RagClient` → `<tenant>_documents`) với `anchor='__ALL__'` · `doc_type='kb_file'` · `status='published'` — agent kb_search thấy nhờ sentinel union, không sửa gì bên agent. `kb_files.state` là sổ DUY NHẤT (không ghi `kb_index_state` — CHECK entity không nhận, reconcile chưa có thân, vị từ xoá là hằng doc_type). PDF scan → `loi` + chỉ đường sang luồng duyệt OCR của tài liệu dự án (KB_01 §I.2). Handler bắt RỘNG, mọi thất bại kết thúc ở `loi` — hàng không bao giờ treo `dang_xu_ly` (bài học 0390d86). FE không đổi một dòng. |
```

- [ ] **Step 3: Lint + format (HAI lệnh) + trọn module**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest tests/modules/kb tests/unit -q
```

Expected: ruff sạch trên các file MỚI/ĐÃ SỬA của nhánh này (nếu `ruff format --check` kêu ở file mình sửa thì `uv run ruff format <file>` từng file đích danh — KHÔNG format cả repo); pytest xanh.

- [ ] **Step 4: Commit**

```bash
git add docs/contracts/payload-qdrant.md CLAUDE.md
git commit -m "docs(kb): hop dong payload doc_type kb_file + Change Log"
```

---

### Task 8 (orchestrator — KHÔNG giao subagent): E2E trên stack local

Chạy bởi phiên chính sau khi Task 1–7 xong, cần api (8100) + worker + qdrant (6343) + minio (9002) đang chạy.

- [ ] Khởi động lại worker nếu đang chạy bản cũ (`make worker` — handler mới phải được nạp; api 8100 chạy `--reload` tự nhặt).
- [ ] Login lấy cookie: `curl -s -c /tmp/kbe2e.txt -X POST http://localhost:8100/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"dang@anphuland.vn","password":"odyssey-dev"}'`
- [ ] Tạo một PDF có lớp chữ + upload: `curl -s -b /tmp/kbe2e.txt -F "file=@<đường dẫn pdf>" http://localhost:8100/api/v1/kb/files` → 202, `state=dang_xu_ly`.
- [ ] Chờ worker chạy job → `curl -s -b /tmp/kbe2e.txt http://localhost:8100/api/v1/kb/files` → `state=san_sang`, `chunkCount ≥ 1`.
- [ ] Đếm point: query Qdrant `http://localhost:6343` collection `anphu_documents` filter `doc_type=kb_file` → count > 0, payload có `project_id="__ALL__"`, `status="published"`.
- [ ] Mở màn `http://localhost:5273/kb` — danh sách hiện tệp vừa tải.
- [ ] DELETE qua curl → 204; point về 0; màn `/kb` trống.
- [ ] Upload một PDF scan (không lớp chữ) → hàng thành `loi` với message chỉ đường.

---

## Self-review (đã chạy)

- **Spec coverage:** §3 (3 route, mã lỗi, thứ tự POST/DELETE) → Task 3, 4. §4 (job, thứ tự bốn-bước, chính sách lỗi, savepoint, retries=0) → Task 5, 6. §5 (kb_files sổ duy nhất) → docstring files_repo + không task nào chạm kb_index_state. §6 (payload-qdrant.md) → Task 7. §7 (không OCR/thumbnail/FE/collection-mismatch) → không task nào chạm. §8 (kiểm chứng) → test từng task + Task 8 E2E. §9 (phạm vi file) → khớp, thêm `test_doc_type_roi_nhau.py` (cổng có sẵn, spec nhắc tính rời nhau).
- **Placeholder:** không còn "TBD/tương tự Task N"; mọi bước code có code thật. Hai chỗ cố ý giao người thi công ĐỌC file thật trước khi bắt chước (thuộc tính mã lỗi của `LoiPortal`; khuôn mục trong `payload-qdrant.md`) — là chỉ dẫn đọc-nguồn, không phải lỗ hổng.
- **Type consistency:** `HangTaiLieu`/`index_kb_file`/`handle_kb_file_index`/`_qdrant_store`/`_ra_tai_lieu` — tên và chữ ký thống nhất giữa Task 2→6; test import đúng các tên đó.
