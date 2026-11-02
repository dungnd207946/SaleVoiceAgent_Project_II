# Tối ưu pipeline nạp kiến thức — kế hoạch thi công

> **For agentic workers:** REQUIRED SUB-SKILL: dùng superpowers:subagent-driven-development (khuyến nghị) hoặc superpowers:executing-plans để thi công từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Goal:** Một đợt nạp 659 ảnh xuống còn ~10–12 phút thay vì ~2h20, không còn ảnh nào âm thầm mất caption, và mỗi dự án có một thanh tiến độ đọc được.

**Architecture:** Worker chạy N task đồng thời trong MỘT tiến trình, mỗi loại việc mang trần đồng thời riêng khai ngay ở `register()`; core cưỡng chế trần bằng bộ đếm in-flight + claim theo kind. Ảnh gốc tải đúng một lần ở `kb_thumb`, hai chặng sau (caption, vector visual) đọc bản thumb. Lỗi VLM tách tạm/vĩnh viễn. Tiến độ đếm từ `kb_index_state`, không đếm hàng đợi job.

**Tech Stack:** Python 3.13 · asyncio · asyncpg · FastAPI · Pydantic · httpx · pytest · React + TanStack Query (FE)

**Spec:** `docs/superpowers/specs/2026-08-25-toi-uu-pipeline-nap-kien-thuc-design.md`
**Nhánh:** `feat/kb-ingest-speedup` ở CẢ HAI repo (`odyssey-portal-backend`, `odyssey-portal-frontend`), rẽ từ `origin/develop`.

## Global Constraints

- **Định danh tiếng Anh** — tên hàm, biến, hằng, tham số, component, hook, tên file. Tiếng Việt chỉ ở comment, docstring và tên hàm test.
- **Comment ít**: tối đa 1 dòng `#` cho một quyết định; docstring module 1 dòng (3 nếu có cảnh báo chặn bug thật).
- **Luật 1**: mọi truy vấn `tenant_data` đi qua `tenant_conn()`, trong một giao dịch.
- **Luật 3**: module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`.
- **KHÔNG sửa `CLAUDE.md`** — nhiều người cùng sửa file đó. Ghi lại các mục cần thêm rồi báo người dùng (Task 12).
- `make check` phải xanh trước khi mở MR. Test cần Docker nằm ở `tests/modules` và `tests/integration`; `tests/unit` không cần.
- Không thêm dependency mới.

---

### Task 1: Khai trần đồng thời theo loại việc

**Files:**
- Modify: `src/portal/core/jobs.py:103-111` (`register`), thêm `_CONCURRENCY`, `concurrency_of`
- Test: `tests/unit/test_jobs_registry.py` (tạo mới)

**Interfaces:**
- Produces: `register(kind, handler, *, retries=0, max_concurrency=1)` · `concurrency_of(kind: str) -> int` (mặc định 1)

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_jobs_registry.py`:

```python
"""Trần đồng thời khai theo loại việc — core cưỡng chế, module khai."""

import pytest

from portal.core.jobs import JobResult, concurrency_of, register


@pytest.fixture(autouse=True)
def _giu_nguyen_so_handler():
    from portal.core import jobs

    handlers = dict(jobs._HANDLERS)
    concurrency = dict(jobs._CONCURRENCY)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(handlers)
    jobs._CONCURRENCY.clear()
    jobs._CONCURRENCY.update(concurrency)


async def _handler(conn, payload):
    return JobResult()


def test_mac_dinh_mot_luot_mot_lan():
    register("t_default", _handler)
    assert concurrency_of("t_default") == 1


def test_khai_tran_cao_hon():
    register("t_wide", _handler, max_concurrency=6)
    assert concurrency_of("t_wide") == 6


def test_kind_chua_dang_ky_van_tra_mot():
    assert concurrency_of("t_unknown") == 1


def test_tran_duoi_mot_bi_tu_choi():
    with pytest.raises(ValueError, match="max_concurrency"):
        register("t_zero", _handler, max_concurrency=0)
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/unit/test_jobs_registry.py -q`
Expected: FAIL — `ImportError: cannot import name 'concurrency_of'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/core/jobs.py`, thêm ngay dưới `_RETRIES`:

```python
# Trần đồng thời theo loại việc. Module sở hữu kind khai trần của nó ở register();
# core chỉ cưỡng chế. Mặc định 1 = hành vi cũ.
_CONCURRENCY: dict[str, int] = {}
```

Sửa `register`:

```python
def register(kind: str, handler: JobHandler, *, retries: int = 0, max_concurrency: int = 1) -> None:
    """`retries` = số lượt THỬ LẠI (không tính lượt đầu). `max_concurrency` = trần đồng thời."""
    if not kind:
        raise ValueError("kind rỗng")
    if retries < 0:
        raise ValueError(f"retries âm cho kind={kind!r}")
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency phải ≥ 1 cho kind={kind!r}")
    _HANDLERS[kind] = handler
    _RETRIES[kind] = retries
    _CONCURRENCY[kind] = max_concurrency


def concurrency_of(kind: str) -> int:
    return _CONCURRENCY.get(kind, 1)
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/unit/test_jobs_registry.py -q`
Expected: PASS 4 test

- [ ] **Step 5: Commit**

```bash
git add src/portal/core/jobs.py tests/unit/test_jobs_registry.py
git commit -m "feat(jobs): let each job kind declare its concurrency ceiling"
```

---

### Task 2: Nhặt job theo tập kind + đếm in-flight

**Files:**
- Modify: `src/portal/core/jobs.py` — thêm `_CLAIM_BY_KIND_SQL`, `_INFLIGHT`, `_CLAIM_LOCK`, `kinds_with_headroom()`; `run_once(pool, *, kinds=None)`
- Test: `tests/modules/test_worker.py` (thêm test), `tests/unit/test_jobs_registry.py` (thêm test headroom)

**Interfaces:**
- Consumes: `concurrency_of()` (Task 1)
- Produces: `run_once(pool, *, kinds: list[str] | None = None) -> int | None` · `kinds_with_headroom() -> list[str]`

- [ ] **Step 1: Viết test đỏ (đơn vị) cho headroom**

Thêm vào `tests/unit/test_jobs_registry.py`:

```python
def test_headroom_bo_kind_da_dat_tran():
    from portal.core import jobs

    register("t_busy", _handler, max_concurrency=1)
    register("t_free", _handler, max_concurrency=2)
    jobs._INFLIGHT["t_busy"] = 1
    jobs._INFLIGHT["t_free"] = 1
    try:
        ready = jobs.kinds_with_headroom()
        assert "t_busy" not in ready
        assert "t_free" in ready
    finally:
        jobs._INFLIGHT.clear()
```

- [ ] **Step 2: Viết test đỏ (tích hợp) cho claim theo kind**

Thêm vào `tests/modules/test_worker.py`:

```python
async def test_nhat_dung_kind_duoc_yeu_cau(tenant, api_pool_jobs):
    """Job cũ hơn thuộc kind khác KHÔNG được nhặt: không có vế này, một hàng đợi
    đầy caption chặn làn index dù làn đó rỗng."""
    ran: list[str] = []

    async def handle(conn, payload):
        ran.append(str(payload["ten"]))
        return JobResult(count=1)

    register("cu", handle)
    register("moi", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="cu", actor="t", payload={"ten": "cu"})
        await enqueue(conn, tenant_id=tenant, kind="moi", actor="t", payload={"ten": "moi"})

    assert await run_once(api_pool_jobs, kinds=["moi"]) is not None
    assert ran == ["moi"]
```

- [ ] **Step 3: Chạy để chắc cả hai đỏ**

Run: `uv run pytest tests/unit/test_jobs_registry.py -q && uv run pytest tests/modules/test_worker.py::test_nhat_dung_kind_duoc_yeu_cau -q`
Expected: FAIL — `AttributeError: kinds_with_headroom` và `TypeError: run_once() got an unexpected keyword argument 'kinds'`

- [ ] **Step 4: Cài đặt**

Trong `src/portal/core/jobs.py`, thêm import `asyncio` và `from collections import Counter` ở đầu file, rồi thêm cạnh `_CAU_NHAT_JOB`:

```python
_CLAIM_BY_KIND_SQL = """SELECT id, tenant_id, kind, payload, attempts FROM control.jobs
                    WHERE state = 'queued' AND run_after <= now() AND kind = ANY($1)
                    ORDER BY id
                      FOR UPDATE SKIP LOCKED LIMIT 1"""

_INFLIGHT: Counter[str] = Counter()

# Claim và tăng bộ đếm phải nằm trong CÙNG một khoá: tính headroom rồi mới claim thì
# hai làn cùng thấy chỗ trống của một kind và cùng nhặt, trần bị vượt.
_CLAIM_LOCK = asyncio.Lock()


def kinds_with_headroom() -> list[str]:
    return [k for k in _HANDLERS if _INFLIGHT[k] < concurrency_of(k)]
```

Sửa phần đầu của `run_once`:

```python
async def run_once(pool: asyncpg.Pool, *, kinds: list[str] | None = None) -> int | None:
    """Nhặt và chạy MỘT job. Trả id job đã chạy, hoặc None nếu không có gì để nhặt.

    `kinds` giới hạn tập loại việc được nhặt — làn của worker truyền vào tập kind
    còn chỗ trống. None = mọi kind, hành vi cũ.

    FOR UPDATE SKIP LOCKED: worker khác đang giữ job nào thì bỏ qua job đó, KHÔNG
    đợi. Nhờ vậy chạy nhiều worker (và nhiều làn trong một worker) mà không nhặt
    trùng và không tắc.

    Job failed KHÔNG được nhặt lại. Retry là quyết định của từng loại job, mặc
    định không có — retry vô hạn một job hỏng là cách chắc chắn nhất để lấp đầy
    log mà không ai đọc.
    """
    async with _CLAIM_LOCK:
        async with pool.acquire() as claim_conn, claim_conn.transaction():
            if kinds is None:
                row = await claim_conn.fetchrow(_CAU_NHAT_JOB)
            else:
                row = await claim_conn.fetchrow(_CLAIM_BY_KIND_SQL, kinds)
            if row is None:
                return None
            await claim_conn.execute(
                "UPDATE control.jobs SET state = 'running', started_at = now() WHERE id = $1",
                row["id"],
            )
        _INFLIGHT[str(row["kind"])] += 1

    try:
        return await _run_claimed_job(pool, row)
    finally:
        _INFLIGHT[str(row["kind"])] -= 1
```

Chuyển toàn bộ phần thân còn lại của `run_once` (từ `job_id, tenant_id, kind = ...` tới hết) thành hàm riêng:

```python
async def _run_claimed_job(pool: asyncpg.Pool, row: asyncpg.Record) -> int:
    job_id, tenant_id, kind = row["id"], row["tenant_id"], row["kind"]
    payload = json.loads(row["payload"])
    handler = get_handler(kind)
    # … giữ nguyên phần thân cũ, không đổi một dòng nào …
```

- [ ] **Step 5: Chạy lại cả hai**

Run: `uv run pytest tests/unit/test_jobs_registry.py tests/modules/test_worker.py -q`
Expected: PASS toàn bộ (9 test cũ của `test_worker.py` phải còn xanh — `run_once(pool)` không tham số vẫn chạy)

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/jobs.py tests/unit/test_jobs_registry.py tests/modules/test_worker.py
git commit -m "feat(jobs): claim by kind and track in-flight count per kind"
```

---

### Task 3: Worker nhiều làn + thu hồi việc kẹt định kỳ

**Files:**
- Modify: `src/portal/worker/__main__.py` (viết lại `main`), `src/portal/core/config.py` (thêm `worker_budget`)
- Test: `tests/modules/test_worker_lanes.py` (tạo mới)

**Interfaces:**
- Consumes: `kinds_with_headroom()`, `run_once(pool, kinds=…)` (Task 2)
- Produces: `Settings.worker_budget` (env `WORKER_BUDGET`, mặc định 12)

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/test_worker_lanes.py`:

```python
"""Làn worker: nhiều job chạy đồng thời, nhưng không kind nào vượt trần của nó."""

import asyncio

import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, enqueue, register
from portal.worker.__main__ import run_lane

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _giu_nguyen_so_handler():
    from portal.core import jobs

    handlers, concurrency = dict(jobs._HANDLERS), dict(jobs._CONCURRENCY)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(handlers)
    jobs._CONCURRENCY.clear()
    jobs._CONCURRENCY.update(concurrency)
    jobs._INFLIGHT.clear()


@pytest.fixture
async def tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('lane', 'Lane', 'u_seed_test')"
        )
    yield "lane"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'lane'")


@pytest.fixture
async def api_pool_lanes(api_dsn):
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=8)
    yield p
    await p.close()


async def test_ba_job_chay_dong_thoi(tenant, api_pool_lanes):
    """Ba job của một kind trần 3 phải chồng lấn — tuần tự thì tổng ≥ 0.9s."""
    running = 0
    peak = 0

    async def handle(conn, payload):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.3)
        running -= 1
        return JobResult(count=1)

    register("lane_wide", handle, max_concurrency=3)
    async with tenant_conn(api_pool_lanes, tenant) as conn:
        for i in range(3):
            await enqueue(conn, tenant_id=tenant, kind="lane_wide", actor="t", payload={"i": i})

    lanes = [asyncio.create_task(run_lane(api_pool_lanes)) for _ in range(3)]
    await asyncio.sleep(0.9)
    for t in lanes:
        t.cancel()
    assert peak == 3


async def test_khong_vuot_tran_cua_kind(tenant, api_pool_lanes):
    """Trần 1 thì dù có 3 làn rảnh, hai job cùng kind KHÔNG được chạy chồng."""
    running = 0
    peak = 0

    async def handle(conn, payload):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.2)
        running -= 1
        return JobResult(count=1)

    register("lane_narrow", handle, max_concurrency=1)
    async with tenant_conn(api_pool_lanes, tenant) as conn:
        for i in range(3):
            await enqueue(conn, tenant_id=tenant, kind="lane_narrow", actor="t", payload={"i": i})

    lanes = [asyncio.create_task(run_lane(api_pool_lanes)) for _ in range(3)]
    await asyncio.sleep(0.7)
    for t in lanes:
        t.cancel()
    assert peak == 1
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/test_worker_lanes.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_lane'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/core/config.py`, thêm vào `Settings` (cạnh các field runtime khác):

```python
    worker_budget: int = 12
```

Viết lại phần cuối `src/portal/worker/__main__.py` (giữ nguyên docstring module và `load_handlers`):

```python
IDLE_SLEEP_SEC = 2.0
RECLAIM_EVERY_SEC = 60.0


async def run_lane(pool: asyncpg.Pool) -> None:
    """Một làn: nhặt và chạy job thuộc những kind còn chỗ trống, mãi mãi."""
    while True:
        kinds = kinds_with_headroom()
        if not kinds or await run_once(pool, kinds=kinds) is None:
            await asyncio.sleep(IDLE_SLEEP_SEC)


async def reclaim_loop(pool: asyncpg.Pool) -> None:
    """Thu hồi việc kẹt theo NHỊP, không theo lúc rảnh.

    Bản cũ chỉ gọi khi hàng đợi rỗng, nên trong đúng một đợt backfill dài — lúc dễ
    có việc kẹt nhất — nó không bao giờ chạy.
    """
    while True:
        await asyncio.sleep(RECLAIM_EVERY_SEC)
        try:
            await thu_hoi_viec_ket(pool)
        except Exception:
            log.exception("thu hồi việc kẹt hỏng")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("handler đã nạp: %s", load_handlers() or "(chưa có)")

    budget = get_settings().worker_budget
    pool = await create_pool(get_settings().database_url, max_size=budget + 4)
    try:
        await thu_hoi_viec_ket(pool)
        log.info("chạy %d làn", budget)
        await asyncio.gather(reclaim_loop(pool), *[run_lane(pool) for _ in range(budget)])
    finally:
        await pool.close()
```

Sửa import ở đầu file:

```python
import asyncpg

from portal.core.jobs import kinds_with_headroom, run_once, thu_hoi_viec_ket
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/test_worker_lanes.py tests/modules/test_worker.py -q`
Expected: PASS

- [ ] **Step 5: Khai biến env**

Thêm vào `.env.example` và `.env` (khối worker), và vào `deploy/odyssey-portal-backend.env.example`:

```
# Số job chạy đồng thời trong một worker. Trần từng loại việc khai ở register().
WORKER_BUDGET=12
```

- [ ] **Step 6: Commit**

```bash
git add src/portal/worker/__main__.py src/portal/core/config.py .env .env.example deploy/odyssey-portal-backend.env.example tests/modules/test_worker_lanes.py
git commit -m "feat(worker): run N lanes in one process and reclaim stuck jobs on a timer"
```

---

### Task 4: Khai trần cho các loại việc KB

**Files:**
- Modify: `src/portal/modules/kb/contracts.py` (thêm `LANE_THUMB`/`LANE_CAPTION`/`LANE_INDEX`), `src/portal/modules/kb/jobs.py:908-920` (các lời gọi `register`)
- Test: `tests/unit/test_kb_lane_ceilings.py` (tạo mới)

**Interfaces:**
- Consumes: `register(..., max_concurrency=)` (Task 1)
- Produces: `LANE_THUMB = 8` · `LANE_CAPTION = 6` · `LANE_INDEX = 4` — Task 9 dùng lại `LANE_CAPTION` cho trần của gate, đừng gõ số 6 lần thứ hai

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_kb_lane_ceilings.py`:

```python
"""Trần đồng thời của ba chặng nặng — số đo prod 2026-08-25 nằm trong spec."""

from portal.core.jobs import concurrency_of
from portal.modules.kb import jobs as kb_jobs  # noqa: F401 — import để register() chạy
from portal.modules.kb.contracts import KIND_CAPTION, KIND_INDEX, KIND_THUMB


def test_thumb_rong_nhat_vi_thuan_cho_mang():
    assert concurrency_of(KIND_THUMB) == 8


def test_caption_theo_muc_dashscope_chiu_duoc():
    assert concurrency_of(KIND_CAPTION) == 6


def test_index_hep_hon_vi_embed_service_dung_chung_cpu():
    assert concurrency_of(KIND_INDEX) == 4


def test_viec_khac_van_mot_luot_mot_lan():
    from portal.modules.kb.contracts import KIND_SYNC_PROJECT

    assert concurrency_of(KIND_SYNC_PROJECT) == 1
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/unit/test_kb_lane_ceilings.py -q`
Expected: FAIL — `assert 1 == 8`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/contracts.py`, cạnh `RETRY_VIEC_KB`:

```python
# Trần đồng thời ba chặng nặng. Số đo prod 2026-08-25: thumb thuần chờ mạng (12 luồng
# đạt 8,47 MB/s), caption ~2,3s/ảnh và 4 lượt song song không nghẽn, index ăn CPU của
# embed service dùng chung với stt/tts.
LANE_THUMB = 8
LANE_CAPTION = 6
LANE_INDEX = 4
```

Trong `src/portal/modules/kb/jobs.py`, import ba hằng đó rồi sửa ba dòng register:

```python
register(KIND_INDEX, handle_index, retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
register(KIND_CAPTION, handle_caption, retries=RETRY_VIEC_KB, max_concurrency=LANE_CAPTION)
register(KIND_THUMB, handle_thumb, retries=RETRY_VIEC_KB, max_concurrency=LANE_THUMB)
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/unit/test_kb_lane_ceilings.py -q`
Expected: PASS 4 test

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/jobs.py tests/unit/test_kb_lane_ceilings.py
git commit -m "feat(kb): declare concurrency ceilings for thumb, caption and index"
```

---

### Task 5: EmbedClient đọc được khoá nội bộ

**Files:**
- Modify: `src/portal/modules/kb/clients/embed.py` (`__init__`, `_tai_base64`), `src/portal/modules/kb/jobs.py:46-64` (`dependencies`)
- Test: `tests/modules/kb/test_embed_client.py` (thêm test)

**Interfaces:**
- Produces: `EmbedClient(base_url, token, objects=None)` — `objects` là `ObjectStore` hoặc None

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/kb/test_embed_client.py`:

```python
async def test_khoa_noi_bo_doc_tu_kho_khong_qua_http():
    """Thumb nằm trong MinIO cùng máy. Đi bằng HTTP là tự bắn ra ngoài rồi vòng lại,
    và với URL ngoài thì đó là tải lại ảnh gốc nhiều MB lần thứ hai."""
    http_called = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal http_called
        if "embed" not in str(req.url):
            http_called = True
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    class FakeStore:
        def __init__(self) -> None:
            self.keys_read: list[str] = []

        async def doc(self, *, key: str) -> bytes:
            self.keys_read.append(key)
            return b"RIFF____WEBPfake"

    kho = FakeStore()
    c = EmbedClient(base_url="https://embed.test", token="tok", objects=kho)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await c.visual_image(["tenants/t1/kb-bds/thumb/abc.webp"])

    assert kho.keys_read == ["tenants/t1/kb-bds/thumb/abc.webp"]
    assert http_called is False


async def test_url_ngoai_van_di_bang_http():
    def handler(req: httpx.Request) -> httpx.Response:
        if "embed" in str(req.url):
            return httpx.Response(200, json={"embeddings": [[0.1] * 768]})
        return httpx.Response(200, content=b"\xff\xd8\xffanh")

    c = EmbedClient(base_url="https://embed.test", token="tok", objects=None)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await c.visual_image(["https://cdn.example.com/a.jpg"]) != []
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_embed_client.py -q -k khoa_noi_bo`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'objects'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/clients/embed.py`:

```python
    def __init__(self, *, base_url: str, token: str, objects: Any = None) -> None:
        if not token:
            raise ValueError("thiếu KB_SANTA_MODELS_TOKEN — embed service từ chối request không auth")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._objects = objects
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)
        self._gate = asyncio.Semaphore(settings.WORKER_CONCURRENCY)
```

Sửa đầu `_tai_base64`, thay đúng ba dòng lấy byte:

```python
    async def _tai_base64(self, url: str) -> str:
        """Ảnh vượt `VISUAL_MAX_BYTES` thì thu nhỏ trước khi encode — xem hằng số đó.

        Khoá nội bộ đọc thẳng từ kho, không vòng qua HTTP.
        """
        from portal.modules.kb.storage.object_store import is_internal_key

        if self._objects is not None and is_internal_key(url):
            data = await self._objects.doc(key=url)
        else:
            r = await self._http.get(url, follow_redirects=True)
            r.raise_for_status()
            data = r.content
        # … phần còn lại giữ nguyên (thu nhỏ nếu quá VISUAL_MAX_BYTES, rồi b64encode) …
```

Trong `src/portal/modules/kb/jobs.py`, sửa `dependencies()`:

```python
    kho = object_store()
    embed = EmbedClient(base_url=env.embed_url, token=env.santa_models_token, objects=kho)
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    return (
        RagClient(embed=embed, store=store),
        MediaClient(embed=embed, store=store),
        kho,
    )
```

Cũng sửa docstring của `dependencies()`: câu «worker chạy tuần tự một job một lúc» nay sai — đổi thành «worker chạy nhiều làn».

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_embed_client.py -q`
Expected: PASS toàn bộ file

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/embed.py src/portal/modules/kb/jobs.py tests/modules/kb/test_embed_client.py
git commit -m "feat(kb): read internal object keys straight from the store when embedding images"
```

---

### Task 6: Vector visual lấy từ thumb

**Files:**
- Modify: `src/portal/modules/kb/clients/media.py:49`
- Test: `tests/modules/kb/test_media_visual_nguon_anh.py` (tạo mới)

**Interfaces:**
- Consumes: `EmbedClient.visual_image` (Task 5)

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_media_visual_nguon_anh.py`:

```python
"""Nguồn ảnh cho vector visual. Đo trên prod 2026-08-25: ảnh gốc 11,5 MB mất 4,16s
(tải + embed), thumb 31 KB mất 0,26s — và model là siglip2-base-patch16-256, nó
nhìn ảnh ở 256px nên bản gốc không cho thêm gì."""

import pytest

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.contracts import MediaDirective


class FakeEmbed:
    def __init__(self) -> None:
        self.images_sent: list[str] = []

    async def dense(self, texts):
        return [[0.1] * 1024]

    async def visual_image(self, urls):
        self.images_sent.extend(urls)
        return [[0.2] * 768]


class FakeVectorStore:
    async def delete_by_record(self, *a, **kw):
        return 0

    async def upsert(self, name, points):
        return len(points)


def _directive(**kw) -> MediaDirective:
    defaults = dict(
        workspace_slug="ws",
        record_id=1,
        anchor_code="P1",
        content_type="image",
        category="tong_quan",
        media_url="https://cdn.example.com/goc.jpg",
        file_url=None,
        caption="ảnh sân vườn",
        thumb_url="tenants/t1/kb-bds/thumb/abc.webp",
        anchor_name="Dự án 1",
        status="published",
        anchor_status="published",
    )
    defaults.update(kw)
    return MediaDirective(**defaults)


async def test_dung_thumb_khi_co():
    embed = FakeEmbed()
    await MediaClient(embed=embed, store=FakeVectorStore()).index(_directive())
    assert embed.images_sent == ["tenants/t1/kb-bds/thumb/abc.webp"]


async def test_roi_ve_anh_goc_khi_chua_co_thumb():
    embed = FakeEmbed()
    await MediaClient(embed=embed, store=FakeVectorStore()).index(_directive(thumb_url=None))
    assert embed.images_sent == ["https://cdn.example.com/goc.jpg"]
```

Đã đối chiếu với `MediaDirective` (`contracts.py:56-71`): đủ field, `caption_profile` bỏ trống vì có mặc định.

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_media_visual_nguon_anh.py -q`
Expected: FAIL — `assert ['https://cdn.example.com/goc.jpg'] == ['tenants/t1/…']`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/clients/media.py`, sửa đúng một dòng:

```python
        # Thumb trước: model visual nhìn ở 256px, còn ảnh gốc có thể 47 MB tải qua Internet.
        image_src = directive.thumb_url or directive.file_url or directive.media_url
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_media_visual_nguon_anh.py tests/modules/kb -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/media.py tests/modules/kb/test_media_visual_nguon_anh.py
git commit -m "perf(kb): embed the thumbnail instead of re-downloading the original image"
```

---

### Task 7: Caption gửi thumb thay vì URL ảnh gốc

**Files:**
- Modify: `src/portal/modules/kb/jobs.py` — `_caption_anh` (410-427), `handle_caption` (495-545)
- Test: `tests/modules/kb/test_caption_nguon_anh.py` (tạo mới)

**Interfaces:**
- Produces: `_caption_anh(*, tenant_id, media_url, profile, thumb_url="")`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_caption_nguon_anh.py`:

```python
"""Ảnh > 10 MB bị DashScope từ chối `400 Multimodal file size is too large` khi gửi
bằng URL — đo trên prod 2026-08-25: 24% ảnh của một tenant thật rơi vào đó và mất
caption trong im lặng. Thumb 31 KB thì mô tả được."""

import pytest

from portal.modules.kb import jobs as kb_jobs


class FakeVlm:
    def __init__(self) -> None:
        self.urls_sent: list[str] = []
        self.bytes_sent: list[bytes] = []

    async def caption(self, image_url, *, profile):
        self.urls_sent.append(image_url)
        return "mô tả từ url"

    async def caption_bytes(self, data, *, mime, profile):
        self.bytes_sent.append(data)
        return "mô tả từ byte"

    async def aclose(self):
        return None


class FakeStore:
    async def doc(self, *, key: str) -> bytes:
        return b"RIFF____WEBPthumb"


@pytest.fixture
def fake_vlm(monkeypatch) -> FakeVlm:
    v = FakeVlm()
    monkeypatch.setattr(kb_jobs, "_vlm", lambda: v)
    monkeypatch.setattr(kb_jobs, "object_store", lambda: FakeStore())
    return v


async def test_co_thumb_thi_gui_byte_thumb(fake_vlm):
    caption, _ = await kb_jobs._caption_anh(
        tenant_id="t1",
        media_url="https://cdn.example.com/goc.jpg",
        profile="caption",
        thumb_url="tenants/t1/kb-bds/thumb/abc.webp",
    )
    assert caption == "mô tả từ byte"
    assert fake_vlm.bytes_sent == [b"RIFF____WEBPthumb"]
    assert fake_vlm.urls_sent == []


async def test_khong_co_thumb_thi_van_gui_url(fake_vlm):
    caption, _ = await kb_jobs._caption_anh(
        tenant_id="t1",
        media_url="https://cdn.example.com/goc.jpg",
        profile="caption",
        thumb_url="",
    )
    assert caption == "mô tả từ url"
    assert fake_vlm.urls_sent == ["https://cdn.example.com/goc.jpg"]
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_caption_nguon_anh.py -q`
Expected: FAIL — `TypeError: _caption_anh() got an unexpected keyword argument 'thumb_url'`

- [ ] **Step 3: Cài đặt**

Sửa `_caption_anh` trong `src/portal/modules/kb/jobs.py`:

```python
async def _caption_anh(
    *, tenant_id: str, media_url: str, profile: str, thumb_url: str = ""
) -> tuple[str, "Callable[[], bytes | Awaitable[bytes]]"]:
    """Ảnh trong kho ta đi bằng byte, ảnh dán URL ngoài đi bằng URL — DashScope không
    mở được endpoint nội bộ, kể cả khi đã presign. Trả kèm cách lấy byte cho thumb.

    Có thumb thì gửi thumb: ảnh gốc quá cỡ bị DashScope từ chối 400, và đó là 24% ảnh
    của một tenant thật (đo 2026-08-25).
    """
    if thumb_url:
        from portal.modules.kb.storage.object_store import is_internal_key

        if is_internal_key(thumb_url):
            data = await object_store().doc(key=thumb_url)
            async with _mo_vlm() as vlm:
                return await vlm.caption_bytes(data, mime="image/webp", profile=profile), lambda: data

    data = await _anh_trong_kho(tenant_id=tenant_id, media_url=media_url)
    # … phần còn lại giữ nguyên …
```

Trong `handle_caption`, thêm `thumb_url` vào câu SELECT và truyền xuống:

```python
    row = await conn.fetchrow(
        "SELECT content_type, category, media_url, caption, caption_auto, thumb_url FROM tenant_data.media "
        " WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
```

```python
                caption, _ = await _caption_anh(
                    tenant_id=tenant_id,
                    media_url=str(row["media_url"]),
                    profile=profile,
                    thumb_url=str(row["thumb_url"] or ""),
                )
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_caption_nguon_anh.py tests/modules/kb -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/jobs.py tests/modules/kb/test_caption_nguon_anh.py
git commit -m "fix(kb): caption from the thumbnail so oversized images stop failing silently"
```

---

### Task 8: Tách lỗi VLM tạm thời khỏi lỗi vĩnh viễn

**Files:**
- Modify: `src/portal/modules/kb/clients/vlm.py` (`_chat`), `src/portal/modules/kb/jobs.py` (`handle_caption`), `src/portal/modules/kb/contracts.py` (thêm `RETRY_CAPTION`)
- Test: `tests/modules/kb/test_vlm_loi_tam_thoi.py` (tạo mới)

**Interfaces:**
- Produces: `TemporaryVlmError` (trong `clients/vlm.py`) · `RETRY_CAPTION = 4`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_vlm_loi_tam_thoi.py`:

```python
"""429 và 5xx là «thử lại đi», ảnh vỡ là «thôi bỏ». Gộp hai thứ đó làm một là hoặc
mất mô tả vì một cơn nghẽn thoáng qua, hoặc retry vô ích một ảnh hỏng vĩnh viễn."""

import httpx
import pytest

from portal.modules.kb.clients.vlm import TemporaryVlmError, VlmClient


def _client(handler) -> VlmClient:
    c = VlmClient(base_url="https://vlm.test", api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.parametrize("ma", [429, 500, 503])
async def test_ma_tam_thoi_nem_TemporaryVlmError(ma):
    c = _client(lambda req: httpx.Response(ma, json={"error": "busy"}))
    with pytest.raises(TemporaryVlmError):
        await c.caption("https://x/a.jpg", profile="caption")


async def test_400_van_la_loi_thuong():
    c = _client(lambda req: httpx.Response(400, json={"error": "file too large"}))
    with pytest.raises(httpx.HTTPStatusError):
        await c.caption("https://x/a.jpg", profile="caption")
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_vlm_loi_tam_thoi.py -q`
Expected: FAIL — `ImportError: cannot import name 'TemporaryVlmError'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/clients/vlm.py`, thêm trên `class VlmClient`:

```python
class TemporaryVlmError(RuntimeError):
    """429/5xx/timeout — nghẽn thoáng qua, job phải thử lại chứ không bỏ mô tả."""
```

Sửa `_chat`, thay `r.raise_for_status()`:

```python
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryVlmError(f"VLM {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
```

Và bọc lời gọi mạng:

```python
        try:
            r = await self._http.post(...)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TemporaryVlmError(f"{type(exc).__name__}: {exc}") from exc
```

Trong `src/portal/modules/kb/contracts.py`, cạnh `RETRY_VIEC_KB`:

```python
RETRY_CAPTION = 4
```

Trong `handle_caption`, thêm một nhánh except TRƯỚC `except Exception`:

```python
        except TemporaryVlmError:
            raise
        except Exception as e:  # noqa: BLE001 — xem docstring: mô tả hỏng KHÔNG được chặn nạp
```

Và đổi register:

```python
register(KIND_CAPTION, handle_caption, retries=RETRY_CAPTION, max_concurrency=6)
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_vlm_loi_tam_thoi.py tests/modules/kb -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/vlm.py src/portal/modules/kb/jobs.py src/portal/modules/kb/contracts.py tests/modules/kb/test_vlm_loi_tam_thoi.py
git commit -m "feat(kb): retry captions on 429 and 5xx instead of dropping the description"
```

---

### Task 9: Tự điều tiết nhịp gọi VLM

**Files:**
- Create: `src/portal/modules/kb/clients/rate_gate.py`
- Modify: `src/portal/modules/kb/clients/vlm.py` (dùng gate trong `_chat`)
- Test: `tests/unit/test_vlm_rate_gate.py` (tạo mới)

**Interfaces:**
- Produces: `VlmRateGate(ceiling, floor=1, cooldown_sec=30.0, recover_after=50, clock=time.monotonic)` với `permits: int`, `penalize()`, `reward()`, `paused_for() -> float`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_vlm_rate_gate.py`:

```python
"""Điều tiết nhịp gọi VLM — logic thuần, không mạng, không chờ thật."""

import pytest

from portal.modules.kb.clients.rate_gate import VlmRateGate


def _gate(**kw) -> VlmRateGate:
    clock_state = {"t": 0.0}
    g = VlmRateGate(ceiling=6, clock=lambda: clock_state["t"], **kw)
    g._clock_state = clock_state  # test dời thời gian qua đây
    return g


def test_bat_dau_o_tran():
    assert _gate().permits == 6


def test_429_giam_mot_nua():
    g = _gate()
    g.penalize()
    assert g.permits == 3
    g.penalize()
    assert g.permits == 1


def test_khong_bao_gio_xuong_duoi_san():
    g = _gate(floor=2)
    for _ in range(5):
        g.penalize()
    assert g.permits == 2


def test_thanh_cong_du_nhieu_thi_hoi_dan():
    g = _gate(recover_after=3)
    g.penalize()
    before = g.permits
    for _ in range(3):
        g.reward()
    assert g.permits == before + 1


def test_khong_vuot_tran_khi_hoi():
    g = _gate(recover_after=1)
    for _ in range(20):
        g.reward()
    assert g.permits == 6


def test_sau_429_phai_nghi_het_cooldown():
    g = _gate(cooldown_sec=30.0)
    g.penalize()
    assert g.paused_for() == pytest.approx(30.0)
    g._clock_state["t"] = 31.0
    assert g.paused_for() == 0.0


async def test_giam_permits_thi_chan_that_su():
    """penalize() phải CHẶN bớt lượt chạy, không chỉ đổi một con số trang trí."""
    import asyncio

    g = VlmRateGate(ceiling=4, cooldown_sec=0.0)
    g.penalize()  # còn 2
    running = 0
    peak = 0

    async def one_call() -> None:
        nonlocal running, peak
        async with g:
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

    await asyncio.gather(*[one_call() for _ in range(4)])
    assert peak == 2
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/unit/test_vlm_rate_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.clients.rate_gate`

- [ ] **Step 3: Cài đặt**

Tạo `src/portal/modules/kb/clients/rate_gate.py`:

```python
"""Điều tiết nhịp gọi VLM trong một tiến trình: gặp 429 thì lùi, êm rồi thì tiến lại."""

import asyncio
import time
from collections.abc import Callable


class VlmRateGate:
    def __init__(
        self,
        *,
        ceiling: int,
        floor: int = 1,
        cooldown_sec: float = 30.0,
        recover_after: int = 50,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ceiling < 1 or floor < 1 or floor > ceiling:
            raise ValueError(f"ceiling/floor không hợp lệ: {ceiling}/{floor}")
        self._ceiling = ceiling
        self._floor = floor
        self._cooldown = cooldown_sec
        self._recover_after = recover_after
        self._clock = clock
        self.permits = ceiling
        self._paused_until = 0.0
        self._successes = 0
        self._in_use = 0
        # Condition chứ không Semaphore: `permits` GIẢM được lúc chạy, mà semaphore thì
        # khoá cứng số slot lúc dựng — dùng nó là penalize() chỉ đổi một con số trang trí.
        self._cond = asyncio.Condition()

    def penalize(self) -> None:
        self.permits = max(self._floor, self.permits // 2)
        self._successes = 0
        self._paused_until = self._clock() + self._cooldown

    def reward(self) -> None:
        self._successes += 1
        if self._successes >= self._recover_after:
            self._successes = 0
            self.permits = min(self._ceiling, self.permits + 1)

    def paused_for(self) -> float:
        return max(0.0, self._paused_until - self._clock())

    async def __aenter__(self) -> "VlmRateGate":
        cho = self.paused_for()
        if cho:
            await asyncio.sleep(cho)
        async with self._cond:
            await self._cond.wait_for(lambda: self._in_use < self.permits)
            self._in_use += 1
        return self

    async def __aexit__(self, *exc) -> None:
        async with self._cond:
            self._in_use -= 1
            self._cond.notify()
```

Trong `src/portal/modules/kb/clients/vlm.py`, dựng gate cấp module và dùng trong `_chat`:

```python
from portal.modules.kb.clients.rate_gate import VlmRateGate
from portal.modules.kb.contracts import LANE_CAPTION

# Cùng trần với làn caption của worker: hai con số lệch nhau thì một cái thành vô nghĩa.
_GATE = VlmRateGate(ceiling=LANE_CAPTION)
```

```python
    async def _chat(self, *, spec: prompts.PromptSpec, image_part: dict) -> str:
        async with _GATE:
            try:
                r = await self._http.post(...)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TemporaryVlmError(f"{type(exc).__name__}: {exc}") from exc
            if r.status_code == 429 or r.status_code >= 500:
                _GATE.penalize()
                raise TemporaryVlmError(f"VLM {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            _GATE.reward()
            return _parse_content(r.json())
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/unit/test_vlm_rate_gate.py tests/modules/kb/test_vlm_loi_tam_thoi.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/rate_gate.py src/portal/modules/kb/clients/vlm.py tests/unit/test_vlm_rate_gate.py
git commit -m "feat(kb): back off VLM concurrency after a 429 and recover on success"
```

---

### Task 10: Tiến độ theo dự án — SQL, contract, endpoint

**Files:**
- Modify: `src/portal/modules/realestate/repo.py:945-1002` (`_PROJECT_STATUS_SQL`), `src/portal/modules/realestate/contracts.py:357-364` (`KbStatusOut`), `src/portal/modules/realestate/router.py:1116-1131`
- Test: `tests/modules/realestate/test_kb_status.py` (thêm test)

**Interfaces:**
- Produces: `KbStatusOut(projectCode, indexing, hasError, total: int, done: int)`

- [ ] **Step 1: Viết test đỏ**

Trong `tests/modules/realestate/test_kb_status.py`, **sửa** `test_hinh_dang_response_dung_hai_co` (dòng 192) — đây là cổng CỐ Ý canh việc con số bò trở lại, và đợt này đảo đúng quyết định đó, nên nó phải được viết lại chứ không phải "tự nhiên đỏ":

```python
async def test_hinh_dang_response_dung_bon_truong(client_re, workspace_re):
    """Cổng cũ (`test_hinh_dang_response_dung_hai_co`) cấm mọi con số, viết cho thời
    nhập tay vài bản ghi. Cổng mới chốt ĐÚNG bốn trường: thêm nữa là bắt người dùng
    diễn giải, bớt đi là FE không vẽ được thanh."""
    await _tao_du_an(client_re, "kbs8", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs8")
    assert set(m) == {"projectCode", "indexing", "hasError", "total", "done"}
```

Và **thêm** ba test (dùng helper sẵn có `_tao_du_an` · `_ghi_so` · `_don_viec` · `_cua`):

```python
async def test_tong_dem_moi_muc_cua_du_an(client_re, workspace_re, pool):
    """Dự án trần đã là MỘT mục: hàng `projects` chính là doc tổng quan của agent."""
    await _tao_du_an(client_re, "kbs9", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs9")
    assert m["total"] == 1
    assert m["done"] == 0, "chưa nạp gì mà đã tính là xong"


async def test_nap_xong_thi_done_bang_tong(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "kbs10", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbs10",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs10")
    assert m["done"] == m["total"] and m["total"] > 0


async def test_done_khong_bao_gio_am(client_re, workspace_re, pool):
    """`lech` đếm cả mục chưa có dòng sổ, nên trên dữ liệu drift nó vượt được `tong` —
    số âm ở đây làm FE vẽ thanh ngược."""
    await _tao_du_an(client_re, "kbs11", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs11")
    assert m["done"] >= 0
```

Sửa luôn docstring đầu file — nó đang mở đầu bằng «HAI CỜ, KHÔNG CÓ SỐ (D03 giao diện)», nay sai.

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/realestate/test_kb_status.py -q`
Expected: FAIL — `KeyError: 'total'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/realestate/repo.py`, thêm CTE `tong` vào `_PROJECT_STATUS_SQL` (ngay sau CTE `lech`):

```sql
tong AS (
    SELECT project_code, count(*) AS n FROM muc GROUP BY project_code
),
```

và hai cột vào SELECT cuối, kèm JOIN:

```sql
SELECT p.project_code,
       coalesce(viec.pending, 0) > 0 AS indexing,
       (coalesce(so.error_count, 0) > 0
        OR coalesce(viec.failed, 0) > 0
        OR (coalesce(lech.stale_count, 0) > 0 AND coalesce(viec.pending, 0) = 0)) AS has_error,
       coalesce(tong.n, 0) AS total,
       greatest(coalesce(tong.n, 0) - coalesce(lech.stale_count, 0), 0) AS done
  FROM tenant_data.projects p
  LEFT JOIN so ON so.project_code = p.project_code
  LEFT JOIN lech ON lech.project_code = p.project_code
  LEFT JOIN tong ON tong.project_code = p.project_code
  LEFT JOIN viec ON viec.project_code = p.project_code
 WHERE p.tenant_id = portal.current_tenant()
 ORDER BY p.project_code
```

`greatest(…, 0)` là bắt buộc: `lech` đếm cả mục chưa có dòng sổ, nên trên dữ liệu drift nó có thể vượt `tong` và cho ra số âm — FE sẽ vẽ thanh ngược.

Trong `contracts.py`:

```python
class KbStatusOut(BaseModel):
    """Một dòng cho mỗi dự án — chỉ báo trên danh sách đọc đúng danh sách này.

    CÓ SỐ, từ 2026-08-25. Quyết định «hai cờ, không có số» viết cho thời nhập tay vài
    bản ghi; nay cổng nạp đổ vào hàng trăm ảnh một lượt và một dòng chữ không phân
    biệt được «chậm» với «kẹt». `total = 0` nghĩa là chưa có gì để nạp.
    """

    projectCode: str
    indexing: bool
    hasError: bool
    total: int = 0
    done: int = 0
```

Trong `router.py`:

```python
    return [
        KbStatusOut(
            projectCode=r["project_code"],
            indexing=r["indexing"],
            hasError=r["has_error"],
            total=r["total"],
            done=r["done"],
        )
        for r in rows
    ]
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/realestate/test_kb_status.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/realestate/repo.py src/portal/modules/realestate/contracts.py src/portal/modules/realestate/router.py tests/modules/realestate/test_kb_status.py
git commit -m "feat(realestate): kb-status carries how many items reached the agent"
```

---

### Task 11: Thanh tiến độ ở frontend

**Files (repo `odyssey-portal-frontend`, nhánh `feat/kb-ingest-speedup`):**
- Modify: `src/features/realestate/api.ts:489-493` (`KbStatus`), `src/features/realestate/components/KbBadge.tsx`
- Test: `tests/kb-tien-do.test.tsx` (tạo mới)

**Interfaces:**
- Consumes: `KbStatusOut` (Task 10) — `total`, `done`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/kb-tien-do.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { KbBadge } from '../src/features/realestate/components/KbBadge'

const goc = { projectCode: 'VGP', indexing: false, hasError: false, total: 0, done: 0 }

describe('KbBadge — thanh tiến độ', () => {
  it('đang nạp thì hiện phần trăm', () => {
    render(<KbBadge tt={{ ...goc, indexing: true, total: 659, done: 412 }} />)
    expect(screen.getByText('63%')).toBeInTheDocument()
  })

  it('nạp đủ thì hiện 100%', () => {
    render(<KbBadge tt={{ ...goc, total: 1470, done: 1470 }} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('dự án chưa có gì để nạp thì không vẽ thanh', () => {
    const { container } = render(<KbBadge tt={{ ...goc, total: 0, done: 0 }} />)
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('lỗi thì hiện nút Thử lại chứ không hiện thanh', () => {
    const { container } = render(<KbBadge tt={{ ...goc, hasError: true, total: 10, done: 3 }} />)
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('con số đầy đủ nằm ở title để rê chuột mới thấy', () => {
    render(<KbBadge tt={{ ...goc, indexing: true, total: 659, done: 412 }} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('title', '412/659 mục đã tới agent')
  })
})
```

⚠️ Mở một test `.tsx` sẵn có (ví dụ `tests/kb.test.tsx`) để chép đúng cách bọc provider của repo; `KbBadge` dùng `useMutation` nên có thể cần `QueryClientProvider`.

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `npm test -- kb-tien-do`
Expected: FAIL — không tìm thấy `63%`

- [ ] **Step 3: Cài đặt**

Trong `src/features/realestate/api.ts`:

```ts
export interface KbStatus {
  readonly projectCode: string
  readonly indexing: boolean
  readonly hasError: boolean
  /** Tổng mục agent cần biết. 0 = dự án chưa có gì để nạp. */
  readonly total: number
  /** Số mục đã lên Qdrant và không lệch. */
  readonly done: number
}
```

Viết lại phần render của `src/features/realestate/components/KbBadge.tsx` (giữ nguyên phần `useMutation` và nhánh `hasError`):

```tsx
  if (tt.hasError) {
    // … giữ nguyên khối cũ …
  }

  if (tt.total <= 0) return null

  const pct = Math.round((tt.done / tt.total) * 100)

  return (
    <span
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      title={`${tt.done}/${tt.total} mục đã tới agent`}
      className="inline-flex items-center gap-2 whitespace-nowrap"
    >
      <span className="h-[5px] w-[118px] overflow-hidden rounded-full bg-fill-strong">
        <span
          className={`block h-full rounded-full bg-ac transition-[width] duration-500 ${pct >= 100 ? 'opacity-75' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="text-[12px] tabular-nums text-muted">{pct}%</span>
    </span>
  )
```

⚠️ `block` trên thanh trong là bắt buộc — `<span>` mặc định là `inline`, và inline thì `width`/`height` bị bỏ qua nên thanh không được vẽ. Bản mô phỏng đã dính đúng lỗi này một lần.

Bản mô phỏng để đối chiếu: `docs/design/tien-do-nap.html` (repo backend).

- [ ] **Step 4: Chạy lại**

Run: `npm test -- kb-tien-do && npm run build`
Expected: PASS 5 test, build không lỗi kiểu

- [ ] **Step 5: Commit (repo frontend)**

```bash
git add src/features/realestate/api.ts src/features/realestate/components/KbBadge.tsx tests/kb-tien-do.test.tsx
git commit -m "feat(realestate): show ingest progress per project instead of a static note"
```

---

### Task 12: Kiểm chứng trên prod và bàn giao

**Files:**
- Không sửa code. Ghi kết quả vào phần cuối spec.

- [ ] **Step 1: Chạy toàn bộ cổng ở local**

Run: `make check`
Expected: xanh, trừ 2 test đã đỏ sẵn của `tests/modules/test_heartbeat.py` (nợ cũ, RLS thiếu trên `control.agent_heartbeats`). So danh sách đỏ với `git stash` + chạy lại nếu nghi có hồi quy.

- [ ] **Step 2: Đo lại trên prod sau khi deploy**

Trên `10.50.99.104`, đếm ảnh mất caption và thời gian nạp:

```sql
SELECT count(*) FILTER (WHERE coalesce(caption, caption_auto, '') = '') AS thieu_caption,
       count(*) AS tong
  FROM tenant_data.media WHERE content_type = 'image';
```

Kỳ vọng: `thieu_caption` giảm về ~0 sau khi chạy lại đợt nạp (trước bản vá: ~24%). Thời gian nạp trọn một tenant ~10–12 phút thay vì ~2h20.

- [ ] **Step 3: Ghi kết quả đo vào spec**

Thêm mục «Kết quả đo sau khi ship» vào cuối `docs/superpowers/specs/2026-08-25-toi-uu-pipeline-nap-kien-thuc-design.md` với số thật.

- [ ] **Step 4: Soạn mục Change Log cho CLAUDE.md — KHÔNG tự sửa file**

Viết sẵn một đoạn cho người dùng tự dán vào `CLAUDE.md` (nhiều người cùng sửa file đó, dễ conflict). Nội dung cần nêu: worker chạy nhiều làn với trần theo kind khai ở `register()` · biến env mới `WORKER_BUDGET` · thumb là nguồn ảnh cho caption và vector visual · `TemporaryVlmError` + retry 4 lượt cho caption · `KbStatusOut` có thêm `total`/`done` · hai bug đã sửa (`thu_hoi_viec_ket` không chạy khi bận, 24% ảnh mất caption).

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-25-toi-uu-pipeline-nap-kien-thuc-design.md
git commit -m "docs(kb): record measured results after the ingest pipeline rework"
```

---

## Thứ tự và phụ thuộc

```
Task 1 → Task 2 → Task 3 → Task 4      (làn worker)
Task 5 → Task 6                         (vector visual từ thumb)
Task 7                                  (caption từ thumb — độc lập với 5/6)
Task 8 → Task 9                         (lỗi VLM + điều tiết)
Task 10 → Task 11                       (tiến độ: BE rồi FE)
Task 12                                 (sau tất cả)
```

Task 5–7 và Task 10–11 chạy song song được với nhóm 1–4. Task 11 nằm ở repo frontend, và phải deploy SAU Task 10 — FE khai `total`/`done` là bắt buộc nên backend cũ sẽ làm màn trắng; nếu muốn deploy lệch thứ tự thì khai `total?: number` optional ở FE trước.
