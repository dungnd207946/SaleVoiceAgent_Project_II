# M1 — Nền cách ly đa-tenant + hạ tầng dùng chung · Implementation Plan

> **Đọc lưu ý này trước.** Plan này **đã thi hành xong**, khi code còn ở monorepo
> `odyssey-portal-fullstack`. Mọi đường dẫn `apps/backend/…` dưới đây **nay là root của repo
> `odyssey-portal-backend`** (tách ngày 2026-07-30).
>
> Đường dẫn giữ nguyên văn có chủ ý: đây là biên bản việc đã làm. Viết lại chúng sẽ khiến plan khai
> sai rằng file được tạo ở chỗ khác với thực tế lúc đó.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng nền Postgres của control plane — cơ chế cách ly đa-tenant kiểm chứng được bằng 6 cổng test, cộng hạ tầng dùng chung (`jobs` + worker + handler registry, `agent_heartbeats` + `derive_tenant_status()`) mà 4 module sau cần.

**Architecture:** Base table ở `tenant_data`, agent **không có quyền nào** trên đó. Agent đọc qua **view definer** ở schema `agent_api`; view tự lọc tenant bằng `portal.current_tenant()` — hàm suy tenant từ **`session_user`** (`agent_<slug>`), nên session không tự khai tenant khác được. RLS + `FORCE` trên `tenant_data` bảo vệ mọi truy cập của `portal_api` và của chủ bảng. Mỗi bảng `tenant_data` bật cách ly bằng **một** helper DDL (`control.enforce_tenant_isolation`), và một catalog test canh không ai quên gọi nó.

**Tech Stack:** Python 3.13+ · `uv` · asyncpg (runtime) · Alembic + psycopg (migration, SQL thuần) · Postgres 18-alpine · pytest + pytest-asyncio + testcontainers

**Spec:** `docs/superpowers/specs/2026-07-29-m1-nen-cach-ly-da-tenant.md`
**Hợp đồng:** `docs/contracts/isolation.md`
**Code nguồn để đối chiếu:** `docs/product/2026-07-28-slice-1a.ref.md` (plan cũ — **không theo nguyên văn**, xem §"Bốn chỗ khác plan nguồn" của spec)

---

## Global Constraints

- **Postgres sàn cứng ≥ 15**, dùng `postgres:18-alpine`. Cổng dev **5433** (tránh đụng Postgres 16 của hệ thống).
- **Không dùng ORM.** Runtime là asyncpg + SQL thuần. Alembic chỉ `op.execute()` với SQL thuần, không model, không autogenerate.
- **Tất cả comment + docstring bằng tiếng Việt.** Mỗi file migration có header giải thích **vì sao**, không chỉ **cái gì**.
- **Giá lưu `bigint` VND.** Không cột nào tên `*_ty`. Đổi đơn vị làm ở biên nhập (M4).
- **`portal_api` và `agent_*` không được:** superuser · `BYPASSRLS` · `CREATEROLE` · owner của bảng nào.
- **`portal_migrator` là DDL-only.** Không tiến trình nào phục vụ bằng role này. *Không test được trong testcontainers* (ở đó `POSTGRES_USER` là bootstrap superuser) → thành yêu cầu runbook ở Task 9.
- **Không tạo role `BYPASSRLS`** (sửa lỗi C3). Mặc định làm bản chặt — spec tổng §3.4.
- **6 toán tử `match_op` duy nhất:** `eq · substring · gte · lte · exists · contains`. Là `CHECK` constraint, không phải quy ước.
- **Mọi truy vấn `tenant_data` phải nằm trong giao dịch**, qua `tenant_conn()`. Không có đường đọc ngoài giao dịch.
- Ruff line-length **120**, rules `E,F,W,I,UP,B,SIM`.
- **Test không được để lại hàng trong DB.** `pg_dsn` là fixture scope **session** — một container cho cả
  lượt chạy. Mỗi file test đặt tenant theo **tiền tố riêng** (`cs_` cho `test_control_schema`, …) và có
  fixture `autouse` dọn sau mỗi test. Không làm vậy thì fixture của task sau đụng khoá trùng.
- **`tenants.id` dài 2–31 ký tự** — `CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')` đòi tối thiểu 2. Id một ký tự
  trong test sẽ vỡ ở `tenants_id_check` **trước khi** tới constraint mà test muốn kiểm.
- **`tenants.id` là slug** có `CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$')` — nó đi vào tên role `agent_<id>`, đường dẫn `tenants/<id>/`, tên collection `kb_<id>`.

---

## Năm chỗ khác `slice-1a.ref.md` — đọc trước khi code

Plan nguồn có code chạy được, nhưng **năm chỗ phải làm khác**. Nếu copy nguyên văn thì sai.

| # | Plan nguồn | Plan này | Vì sao |
|---|---|---|---|
| 1 | M1 tạo **10 bảng `control` + 7 bảng `tenant_data`** | M1 tạo **3 bảng `control` + 2 bảng `tenant_data` + 2 bảng hạ tầng** | Module sau tự sở hữu bảng của nó. `users`/`memberships` → M2a; `config_drafts`/`config_versions`/`deployments` → M3; `appointments`/`contacts`/`conversations` → M7; 3 bảng Finance → ngoài MVP |
| 2 | Chỉ `ENABLE ROW LEVEL SECURITY` | Thêm **`FORCE ROW LEVEL SECURITY`**, trong helper | Postgres **miễn RLS cho chủ bảng**. Không có `FORCE` thì điều kiện 1 của cách ly là quy ước, không phải cưỡng chế — và **cổng 3 không tồn tại được** |
| 3 | Bật RLS bằng vòng `for table in _TABLES` trong migration | **`control.enforce_tenant_isolation('<bảng>')`** + **catalog test** | Module sau thêm bảng phải bật được cách ly mà không sửa file của M1, và không được quên |
| 4 | `tenants` có cột `plan` | **Không có `plan`** | Hoá đơn không gắn vào khoá cách ly (spec nguồn §2.2). Nó thuộc bảng `accounts` tách riêng, thêm sau |
| 5 | `pol()`/`gated_extras()` là `LANGUAGE sql STABLE` thường | **`SECURITY DEFINER`** + `SET search_path` cố định | Agent **không có `SELECT` trên `control.field_policy_live`**. Nếu dựa vào việc Postgres inline hàm SQL vào view rồi kiểm quyền theo chủ view thì đó là dựa vào chi tiết tối ưu hoá. `SECURITY DEFINER` làm nó tường minh. **`session_user` không bị `SECURITY DEFINER` đổi**, nên `current_tenant()` vẫn đúng |

Ba sửa lỗi **C1 · C2 · C3** của plan nguồn thì **nhận nguyên**.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `Makefile` | `dev · migrate · test · test M=<module> · lint · worker` | 1 |
| `docker-compose.dev.yml` | Postgres 18 cổng 5433 | 1 |
| `apps/backend/pyproject.toml` | deps · ruff · pytest markers | 1 |
| `apps/backend/.env.example` | mẫu biến môi trường | 1 |
| `apps/backend/alembic.ini` · `migrations/env.py` | cấu hình Alembic, URL từ `Settings` | 1 |
| `apps/backend/src/portal/core/config.py` | `Settings` · `to_alembic_url()` | 1 |
| `apps/backend/src/portal/core/db/pool.py` | `create_pool()` | 1 |
| `apps/backend/tests/conftest.py` | container Postgres · chạy migration · fixture | 1 |
| `migrations/versions/0001_schemas_and_functions.py` | schema `portal`/`control` · `current_tenant()` | 2 |
| `migrations/versions/0002_control_core.py` | `tenants` · `tenant_verticals` · `field_policy_live` | 2 |
| `migrations/versions/0003_role_and_isolation_helper.py` | role `portal_api` · `enforce_tenant_isolation()` | 3 |
| `migrations/versions/0004_tenant_data_core.py` | `projects` · `units` lõi + bật cách ly | 4 |
| `apps/backend/src/portal/core/db/session.py` | `tenant_conn()` | 4 |
| `migrations/versions/0005_agent_api.py` | `pol()` · `gated_extras()` · `agent_api` · 2 view · `create_agent_role()` · `grant_agent_write()` | 5 |
| `migrations/versions/0006_jobs.py` | `jobs` + index `SKIP LOCKED` | 7 |
| `apps/backend/src/portal/core/jobs.py` | `register()` · `enqueue()` · `JobHandler` | 7 |
| `apps/backend/src/portal/worker/__main__.py` | vòng lặp worker · gom handler | 7 |
| `migrations/versions/0007_agent_heartbeats.py` | `agent_heartbeats` | 8 |
| `apps/backend/src/portal/core/tenant_status.py` | `derive_tenant_status()` — hàm thuần | 8 |
| `apps/backend/tests/isolation/test_*.py` | **6 cổng** | 4·5·6 |
| `apps/backend/tests/test_module_boundaries.py` | test AST cấm import chéo | 9 |
| `.gitlab-ci.yml` · `deploy/README.md` | job `isolation` không path-filter · ràng buộc production | 9 |

---

## Task 1: Monorepo scaffold + DB test harness

**Files:**
- Create: `Makefile`, `docker-compose.dev.yml`, `.gitignore`
- Create: `apps/backend/pyproject.toml`, `apps/backend/.env.example`, `apps/backend/.python-version`
- Create: `apps/backend/alembic.ini`, `apps/backend/migrations/env.py`, `apps/backend/migrations/script.py.mako`
- Create: `apps/backend/src/portal/__init__.py`, `src/portal/core/__init__.py`, `src/portal/core/config.py`, `src/portal/core/db/__init__.py`, `src/portal/core/db/pool.py`
- Test: `apps/backend/tests/conftest.py`, `tests/unit/test_config.py`, `tests/integration/test_harness.py`

**Interfaces:**
- Consumes: —
- Produces: `Settings` (thuộc tính `database_url: str`, property `alembic_url: str`) · `to_alembic_url(dsn: str) -> str` · `get_settings() -> Settings` · `create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool` · fixture pytest `pg_dsn: str` (DSN container, migration đã chạy) và `pool: asyncpg.Pool` (kết nối bằng `portal_migrator`)

- [ ] **Step 1: Tạo `apps/backend/pyproject.toml`**

```toml
[project]
name = "portal"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "asyncpg>=0.30",
    "pydantic-settings>=2.6",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",
    "sqlalchemy>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=1.0",
    "testcontainers[postgres]>=4.15",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/portal"]

[tool.ruff]
line-length = 120
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["integration: cần Postgres container"]
```

> `requires-python` giữ `>=3.13` — đó là cái code **thực sự** cần. Bản Python để dev/CI chạy pin bằng `.python-version`; dùng bản mới nhất mà `uv sync` resolve sạch (asyncpg thường trễ 1–2 tháng sau CPython minor mới).

- [ ] **Step 2: Tạo `apps/backend/.python-version`**

```
3.13
```

Sau khi `uv sync` chạy được, nếu bản mới hơn resolve sạch thì cập nhật file này. Đừng nâng `requires-python`.

- [ ] **Step 3: Tạo `docker-compose.dev.yml` ở gốc repo**

```yaml
services:
  postgres:
    image: postgres:18-alpine   # sàn cứng >= 15; bump tag khi có major mới
    environment:
      POSTGRES_USER: portal_migrator
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: portal
    ports: ["5433:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U portal_migrator -d portal"]
      interval: 3s
      timeout: 3s
      retries: 20

  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
```

> Redis và MinIO dựng sẵn ở đây dù M1 chưa dùng — M2a cần Redis, M3 cần MinIO. Dựng một lần đỡ sửa file sau. Cổng lệch (`6380`, `9000`) để không đụng dịch vụ có sẵn trên máy.

- [ ] **Step 4: Tạo `apps/backend/.env.example`**

```dotenv
# DSN runtime (asyncpg). Dev trỏ container ở docker-compose.dev.yml
DATABASE_URL=postgresql://portal_migrator:dev@localhost:5433/portal
```

- [ ] **Step 5: Tạo `.gitignore` ở gốc repo**

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.pytest_cache/
.ruff_cache/
node_modules/
dist/
.DS_Store
```

- [ ] **Step 6: Tạo `apps/backend/src/portal/core/config.py`**

```python
"""Cấu hình portal. Mọi biến môi trường khai ở đây, không đọc os.environ rải rác."""

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DSN = "postgresql://portal_migrator:dev@localhost:5433/portal"


def to_alembic_url(dsn: str) -> str:
    """Alembic chạy qua SQLAlchemy + psycopg (sync); runtime dùng asyncpg.

    Tách thành hàm vì cả Settings lẫn conftest đều cần phép đổi này — và chính
    việc hai chỗ tự đổi theo cách khác nhau đã từng sinh bug env.py migrate sai DB.
    """
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _DEFAULT_DSN

    @property
    def alembic_url(self) -> str:
        return to_alembic_url(self.database_url)


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Tạo `apps/backend/src/portal/core/db/pool.py`**

```python
"""Factory pool asyncpg. Không giữ singleton — caller quản vòng đời."""

import asyncpg


async def create_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
```

Tạo `src/portal/__init__.py`, `src/portal/core/__init__.py`, `src/portal/core/db/__init__.py` — cả ba rỗng.

- [ ] **Step 8: Khởi tạo Alembic và sửa `migrations/env.py`**

```bash
cd apps/backend && uv sync && uv run alembic init -t generic migrations
```

Sửa `apps/backend/alembic.ini`: `script_location = migrations`, **xoá** dòng `sqlalchemy.url` (lấy từ settings).

Trong `apps/backend/migrations/env.py`, thay phần cấu hình URL bằng:

```python
from portal.core.config import get_settings

config = context.config

# URL do caller nạp sẵn THẮNG; không có thì mới lấy từ Settings.
# BẮT BUỘC có điều kiện: command.upgrade() truyền chính Config mà fixture pg_dsn
# đã set_main_option("sqlalchemy.url", <DSN container>) vào đây. Set vô điều kiện
# thì fixture bị ghi đè bằng default localhost:5433 -> migrate SAI database.
# Tệ hơn: nếu đang có container dev ở 5433 thì test PASS nhưng vừa migrate DB dev
# của người đang chạy.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().alembic_url)

target_metadata = None  # không dùng ORM — migration là SQL thuần
```

`if not ...` xử lý cả trường hợp template `alembic init` để lại dòng `sqlalchemy.url =` rỗng.

- [ ] **Step 9: Tạo `apps/backend/tests/conftest.py`**

```python
"""Harness test: một container Postgres cho cả session, migration chạy một lần."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from portal.core.config import to_alembic_url
from portal.core.db.pool import create_pool

# Đường dẫn TUYỆT ĐỐI: Config("alembic.ini") tương đối làm `cd tests && pytest`
# ném CommandError. Đã kiểm chứng cả hai chiều.
BACKEND_ROOT = Path(__file__).resolve().parent.parent

MIGRATOR_USER = "portal_migrator"
MIGRATOR_PASSWORD = "dev"
API_PASSWORD = "apidev"


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    """Container Postgres đã chạy migration xong. DSN dạng asyncpg."""
    with PostgresContainer(
        "postgres:18-alpine",
        username=MIGRATOR_USER,
        password=MIGRATOR_PASSWORD,
        dbname="portal",
    ) as pg:
        dsn = (
            f"postgresql://{MIGRATOR_USER}:{MIGRATOR_PASSWORD}"
            f"@{pg.get_container_host_ip()}:{pg.get_exposed_port(5432)}/portal"
        )
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", to_alembic_url(dsn))
        command.upgrade(cfg, "head")
        yield dsn


@pytest.fixture
async def pool(pg_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    """Pool bằng portal_migrator — dùng để seed dữ liệu test."""
    p = await create_pool(pg_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


def dsn_as(dsn: str, user: str, password: str) -> str:
    """Đổi thông tin đăng nhập trong DSN, giữ nguyên host/port/db.

    Dùng để nối bằng portal_api hoặc agent_<tenant> trong test cách ly.
    """
    tail = dsn.split("@", 1)[1]
    return f"postgresql://{user}:{password}@{tail}"
```

> **Không định nghĩa fixture `event_loop`.** pytest-asyncio 1.x đã gỡ cơ chế override đó — khai nó là dead code **im lặng** (không warning), và người đọc sau sẽ tưởng loop scope session đã được cấu hình. Cũng không cần `asyncio_default_fixture_loop_scope`: `pg_dsn` scope session nhưng thuần đồng bộ, còn `pool` là function-scoped — `asyncio_mode = "auto"` đã cấp loop mới mỗi test.

- [ ] **Step 10: Viết `tests/unit/test_config.py` (không cần Docker)**

```python
"""Test Settings — chạy được không cần Docker, nhờ đó `make test-unit` luôn thật."""

from portal.core.config import Settings, to_alembic_url


def test_dsn_mac_dinh_tro_cong_5433():
    assert Settings().database_url == "postgresql://portal_migrator:dev@localhost:5433/portal"


def test_alembic_url_doi_sang_psycopg():
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.alembic_url == "postgresql+psycopg://u:p@h:5432/db"


def test_to_alembic_url_chi_doi_tien_to_dau_tien():
    got = to_alembic_url("postgresql://u:p@h/db?opt=postgresql://x")
    assert got == "postgresql+psycopg://u:p@h/db?opt=postgresql://x"


def test_bien_moi_truong_de_duoc_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://a:b@c:1/d")
    assert Settings().database_url == "postgresql://a:b@c:1/d"
```

- [ ] **Step 11: Viết `tests/integration/test_harness.py`**

```python
import pytest

pytestmark = pytest.mark.integration


async def test_ket_noi_duoc_va_migration_da_chay(pool):
    """Harness sống: kết nối được và bảng alembic_version tồn tại."""
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT 1") == 1
        exists = await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        assert exists is True
```

- [ ] **Step 12: Tạo `Makefile` ở gốc repo**

```makefile
BE := apps/backend

.PHONY: dev migrate test test-unit test-isolation lint worker

dev:            ## dựng postgres + redis + minio
	docker compose -f docker-compose.dev.yml up -d

migrate:
	cd $(BE) && uv run alembic upgrade head

test:
	cd $(BE) && uv run pytest -v

test-unit:      ## không cần Docker
	cd $(BE) && uv run pytest tests/unit -v

test-isolation: ## 6 cổng cách ly — chạy cho MỌI pull request
	cd $(BE) && uv run pytest tests/isolation -v

# Chạy test của một module: make test M=m4
test-module:
	cd $(BE) && uv run pytest tests/modules/$(M) -v

lint:
	cd $(BE) && uv run ruff check . && uv run ruff format --check .

worker:
	cd $(BE) && uv run python -m portal.worker
```

- [ ] **Step 13: Chạy test — xác nhận PASS**

```bash
docker info                       # phải OK trước
make test-unit                    # 4 PASS, không cần Docker
cd apps/backend && uv run pytest tests/integration/test_harness.py -v
```

Expected: `test-unit` 4 PASS · harness 1 PASS. `alembic upgrade head` với 0 revision vẫn tạo bảng `alembic_version`.

- [ ] **Step 14: Commit**

```bash
git add Makefile docker-compose.dev.yml .gitignore apps/
git commit -m "feat(m1): scaffold monorepo + harness test Postgres bằng testcontainers"
```

---

## Task 2: Schema `portal`/`control` + `current_tenant()` + 3 bảng lõi

**Files:**
- Create: `apps/backend/migrations/versions/0001_schemas_and_functions.py`
- Create: `apps/backend/migrations/versions/0002_control_core.py`
- Test: `apps/backend/tests/integration/test_control_schema.py`

**Interfaces:**
- Consumes: fixture `pool` (Task 1)
- Produces: schema `portal` · schema `control` · `portal.current_tenant() -> text` · `control.tenants(id, name, lifecycle, created_at)` · `control.tenant_verticals(tenant_id, vertical, enabled_at)` · `control.field_policy_live(tenant_id, entity, field, is_core, agent_readable, filterable, match_op, label_vi, type, enum_values)`

- [ ] **Step 1: Viết test trước**

`apps/backend/tests/integration/test_control_schema.py`:

```python
"""Schema control + hàm current_tenant. M1 chỉ tạo 3 bảng lõi — module sau tự tạo bảng của nó."""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _don_tenant_cua_module(pool):
    """Dọn tenant do module này tạo.

    pg_dsn là fixture scope SESSION — một container Postgres dùng chung cho cả
    lượt chạy. Hàng không dọn sẽ sống tới hết session và đụng fixture của task
    sau (T4/T5/T6/T8 đều tự tạo tenant). Tiền tố cs_ giới hạn phạm vi dọn đúng
    module này; dấu _ trong LIKE phải escape, không thì nó là ký tự đại diện.
    """
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_ba_bang_control_loi_ton_tai(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'control' ORDER BY tablename"
        )
    assert [r["tablename"] for r in rows] == ["field_policy_live", "tenant_verticals", "tenants"]


async def test_tenants_khong_co_cot_plan(pool):
    """Hoá đơn không gắn vào khoá cách ly — nó thuộc bảng accounts tách riêng, thêm sau."""
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'control' AND table_name = 'tenants'"
        )
    names = {r["column_name"] for r in cols}
    assert names == {"id", "name", "lifecycle", "created_at"}


async def test_lifecycle_chi_nhan_ba_gia_tri(pool):
    async with pool.acquire() as conn:
        with pytest.raises(Exception, match="tenants_lifecycle_check"):
            await conn.execute("INSERT INTO control.tenants (id, name, lifecycle) VALUES ('cs_x', 'X', 'ready')")


async def test_slug_phai_hop_le_vi_no_di_vao_ten_role(pool):
    """id đi vào tên role agent_<id>, đường dẫn tenants/<id>/, tên collection kb_<id>."""
    async with pool.acquire() as conn:
        for bad in ("Anphu", "an-phu", "1anphu", "an phu", "an;drop"):
            with pytest.raises(Exception, match="tenants_id_check"):
                await conn.execute(
                    "INSERT INTO control.tenants (id, name) VALUES ($1, 'X')", bad
                )
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('cs_an_phu2', 'OK')")


async def test_current_tenant_lay_tu_guc_khi_role_khong_phai_agent(pool):
    """portal_migrator không khớp ^agent_ nên rơi về GUC app.tenant_id."""
    async with pool.acquire() as conn, conn.transaction():
        assert await conn.fetchval("SELECT portal.current_tenant()") is None
        await conn.execute("SELECT set_config('app.tenant_id', 'anphu', true)")
        assert await conn.fetchval("SELECT portal.current_tenant()") == "anphu"


async def test_current_tenant_chuoi_rong_thanh_null(pool):
    """Fail-closed: GUC rỗng phải ra NULL, không phải chuỗi rỗng khớp tenant_id = ''."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', '', true)")
        assert await conn.fetchval("SELECT portal.current_tenant()") is None


async def test_match_op_chi_nhan_sau_toan_tu(pool):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('cs_a', 'A')")
        with pytest.raises(Exception, match="field_policy_live_match_op_check"):
            await conn.execute(
                """INSERT INTO control.field_policy_live
                       (tenant_id, entity, field, filterable, match_op)
                   VALUES ('cs_a', 'unit', 'x', true, 'bogus')"""
            )


async def test_filterable_bat_buoc_co_match_op(pool):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('cs_b', 'B')")
        with pytest.raises(Exception, match="field_policy_live_filterable_needs_op"):
            await conn.execute(
                """INSERT INTO control.field_policy_live
                       (tenant_id, entity, field, filterable)
                   VALUES ('cs_b', 'unit', 'x', true)"""
            )


async def test_enum_values_chi_voi_type_enum(pool):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('cs_c', 'C')")
        with pytest.raises(Exception, match="field_policy_live_enum_needs_type"):
            await conn.execute(
                """INSERT INTO control.field_policy_live
                       (tenant_id, entity, field, type, enum_values)
                   VALUES ('cs_c', 'unit', 'x', 'text', ARRAY['a','b'])"""
            )
```

- [ ] **Step 2: Chạy test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/integration/test_control_schema.py -v`
Expected: FAIL — `schemaname = 'control'` trả rỗng, `portal.current_tenant()` không tồn tại.

- [ ] **Step 3: Tạo `migrations/versions/0001_schemas_and_functions.py`**

```python
"""schema portal + control, và hàm xác định tenant hiệu lực

VÌ SAO CÓ FILE NÀY: cách ly đa-tenant của cả hệ đứng trên đúng một hàm —
portal.current_tenant(). Mọi policy RLS và mọi view agent_api gọi nó.

HAI NGUỒN, VÌ HAI BẢN CHẤT KHÁC NHAU:
  - Pod agent phục vụ ĐÚNG MỘT tenant suốt đời tiến trình -> tenant là thuộc
    tính của DANH TÍNH KẾT NỐI, gói vào tên role `agent_<slug>`. Agent KHÔNG
    tự đổi được (đổi session_user cần SET SESSION AUTHORIZATION = superuser).
  - Portal API phục vụ MỌI tenant, đổi theo từng request -> tenant là thuộc
    tính của ĐƠN VỊ CÔNG VIỆC, đặt bằng SET LOCAL app.tenant_id trong giao dịch.

THỨ TỰ COALESCE CÓ Ý NGHĨA AN NINH: nguồn KHÔNG đổi được (tên role) đứng
TRƯỚC nguồn đổi được (GUC). Đảo lại thì một kết nối agent có GUC bị đặt sẽ
leo thang sang tenant khác.

DÙNG session_user, KHÔNG dùng current_user: trong view definer (migration
0005) current_user trả về OWNER của view, không phải role đang gọi.

Trả NULL khi không xác định được -> mọi so sánh `tenant_id = NULL` ra false
-> 0 hàng. Hỏng thì trả rỗng, không trả nhầm của người khác.

Revision ID: 0001_schemas
Revises: None
"""

from alembic import op

revision = "0001_schemas"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA portal")
    op.execute("CREATE SCHEMA control")

    op.execute(
        """
        CREATE FUNCTION portal.current_tenant() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(
                substring(session_user::text from '^agent_(.+)$'),
                nullif(current_setting('app.tenant_id', true), '')
            )
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA control CASCADE")
    op.execute("DROP SCHEMA portal CASCADE")
```

- [ ] **Step 4: Tạo `migrations/versions/0002_control_core.py`**

```python
"""3 bảng control lõi: neo danh tính + cơ chế gate cột

M1 CHỈ tạo ba bảng này. Module sau tự sở hữu bảng của nó:
  users · memberships                    -> M2a (dải revision 0100-0149)
  config_drafts · config_versions
  tenants.live_version · deployments     -> M3  (0200-0299)
  jobs · agent_heartbeats                -> vẫn M1, nhưng migration riêng (0006, 0007)
  appointments · contacts · conversations -> M7  (0600-0699)

VÌ SAO tenants KHÔNG có cột `plan`: hoá đơn không được gắn vào khoá cách ly.
tenants.id là khoá dùng cho BỐN việc cùng lúc (policy RLS · TENANT_ID của pod ·
đường dẫn tenants/<id>/ trên kho tệp · tên collection kb_<id>). Gắn gói cước
vào đây thì lúc một tập đoàn cần nhiều workspace sẽ phải đánh lại đúng cái
khoá cách ly. Đường lùi rẻ đã để sẵn: thêm bảng `accounts` PHÍA TRÊN tenants.

VÌ SAO lifecycle chứ không phải status: status hiển thị (provisioning ·
publishing · ready · disconnected) là HÀM THUẦN của lifecycle + heartbeat +
live_version — xem portal.core.tenant_status. Không thể vừa lưu vừa suy ra.

Revision ID: 0002_control_core
Revises: 0001_schemas
"""

from alembic import op

revision = "0002_control_core"
down_revision = "0001_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CHECK trên id ở TẦNG DB, không chỉ tầng app: slug đi thẳng vào tên role
    # agent_<id> trong control.create_agent_role(). Một slug có ký tự lạ là một
    # đường injection vào câu CREATE ROLE.
    op.execute(
        """
        CREATE TABLE control.tenants (
            id         text PRIMARY KEY
                       CONSTRAINT tenants_id_check CHECK (id ~ '^[a-z][a-z0-9_]{1,30}$'),
            name       text NOT NULL,
            lifecycle  text NOT NULL DEFAULT 'active'
                       CONSTRAINT tenants_lifecycle_check
                       CHECK (lifecycle IN ('active', 'suspended', 'closed')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE control.tenant_verticals (
            tenant_id  text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            vertical   text NOT NULL CHECK (vertical IN ('realestate', 'finance')),
            enabled_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, vertical)
        )
        """
    )

    # Bản HIỆU LỰC của chính sách field. View agent_api đọc bảng này để cưỡng
    # chế gate cột. M3 ghi lại toàn bộ bảng mỗi lần publish; màn khai trường
    # của M4 ghi vào config_drafts, KHÔNG ghi thẳng vào đây.
    #
    # is_core = true  -> cột thật, gate bằng CASE WHEN trong view
    # is_core = false -> key trong extras jsonb, gate bằng portal.gated_extras()
    #
    # agent_readable -> tier 1: agent thấy field (ExtraFieldSpec)
    # filterable + match_op -> tier 2: field bơm vào tool schema (ToolParamSpec)
    op.execute(
        """
        CREATE TABLE control.field_policy_live (
            tenant_id      text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity         text NOT NULL,
            field          text NOT NULL,
            is_core        boolean NOT NULL DEFAULT false,
            agent_readable boolean NOT NULL DEFAULT false,
            filterable     boolean NOT NULL DEFAULT false,
            match_op       text
                           CONSTRAINT field_policy_live_match_op_check
                           CHECK (match_op IS NULL OR match_op IN
                                  ('eq', 'substring', 'gte', 'lte', 'exists', 'contains')),
            label_vi       text NOT NULL DEFAULT '',
            type           text NOT NULL DEFAULT 'text',
            enum_values    text[],
            PRIMARY KEY (tenant_id, entity, field),
            CONSTRAINT field_policy_live_filterable_needs_op
                CHECK (NOT filterable OR match_op IS NOT NULL),
            CONSTRAINT field_policy_live_enum_needs_type
                CHECK (enum_values IS NULL OR type = 'enum')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE control.field_policy_live")
    op.execute("DROP TABLE control.tenant_verticals")
    op.execute("DROP TABLE control.tenants")
```

- [ ] **Step 5: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/integration/test_control_schema.py -v`
Expected: 9 PASS. Chạy tiếp `uv run pytest -v` để chắc fixture dọn không phá test Task 1.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/migrations/versions/0001_schemas_and_functions.py \
        apps/backend/migrations/versions/0002_control_core.py \
        apps/backend/tests/integration/test_control_schema.py
git commit -m "feat(m1): schema control + current_tenant() suy tenant từ session_user"
```

---

## Task 3: Role `portal_api` + helper `enforce_tenant_isolation()`

**Files:**
- Create: `apps/backend/migrations/versions/0003_role_and_isolation_helper.py`
- Test: `apps/backend/tests/integration/test_isolation_helper.py`

**Interfaces:**
- Consumes: schema `portal`/`control`, `portal.current_tenant()` (Task 2)
- Produces: role `portal_api` (LOGIN, non-superuser, không `BYPASSRLS`) · role nhóm `agent_all` (NOLOGIN) · `control.enforce_tenant_isolation(p_qualified_table text) -> void`

- [ ] **Step 1: Viết test trước**

`apps/backend/tests/integration/test_isolation_helper.py`:

```python
"""Helper enforce_tenant_isolation — API mà 8 module còn lại dùng để bật cách ly."""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def probe(pool):
    """Bảng thử trong tenant_data, dọn sau mỗi test."""
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        await conn.execute(
            """CREATE TABLE tenant_data.probe (
                   id        bigserial PRIMARY KEY,
                   tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
                   note      text NOT NULL DEFAULT ''
               )"""
        )
    yield "tenant_data.probe"
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")


async def test_helper_bat_rls_va_force_va_policy(pool, probe):
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.enforce_tenant_isolation($1)", probe)
        row = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = $1::regclass", probe
        )
        assert row["relrowsecurity"] is True
        assert row["relforcerowsecurity"] is True, "FORCE thiếu -> chủ bảng đi xuyên cách ly"
        pols = await conn.fetch(
            "SELECT policyname FROM pg_policies "
            "WHERE schemaname = 'tenant_data' AND tablename = 'probe'"
        )
        assert [p["policyname"] for p in pols] == ["tenant_isolation"]


async def test_helper_grant_cho_portal_api(pool, probe):
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.enforce_tenant_isolation($1)", probe)
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert await conn.fetchval(
                "SELECT has_table_privilege('portal_api', $1, $2)", probe, priv
            ) is True


async def test_helper_tu_choi_bang_ngoai_tenant_data(pool):
    """Thà vỡ lúc migrate hơn vỡ lúc chạy."""
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS control.wrong_place")
        await conn.execute("CREATE TABLE control.wrong_place (tenant_id text)")
        with pytest.raises(Exception, match="chỉ dùng cho bảng trong schema tenant_data"):
            await conn.execute("SELECT control.enforce_tenant_isolation('control.wrong_place')")
        await conn.execute("DROP TABLE control.wrong_place")


async def test_helper_tu_choi_bang_khong_co_cot_tenant_id(pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
        await conn.execute("DROP TABLE IF EXISTS tenant_data.no_tenant")
        await conn.execute("CREATE TABLE tenant_data.no_tenant (id bigserial PRIMARY KEY)")
        with pytest.raises(Exception, match="thiếu cột tenant_id"):
            await conn.execute("SELECT control.enforce_tenant_isolation('tenant_data.no_tenant')")
        await conn.execute("DROP TABLE tenant_data.no_tenant")


async def test_portal_api_khong_phai_superuser_khong_bypassrls(pool):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
            "FROM pg_roles WHERE rolname = 'portal_api'"
        )
    assert r is not None, "role portal_api chưa tồn tại"
    assert r["rolsuper"] is False
    assert r["rolbypassrls"] is False
    assert r["rolcreaterole"] is False
    assert r["rolcreatedb"] is False


async def test_role_nhom_agent_all_ton_tai_va_khong_login(pool):
    """Mọi quyền của agent đi qua nhóm này — nên nó không được đăng nhập được."""
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'agent_all'"
        )
    assert r is not None, "role nhóm agent_all chưa tồn tại"
    assert r["rolcanlogin"] is False
    assert r["rolsuper"] is False
    assert r["rolbypassrls"] is False


async def test_khong_co_role_nao_co_bypassrls(pool):
    """Sửa lỗi C3: role BYPASSRLS là role nguy hiểm nhất hệ thống. Không tạo khi chưa cần."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rolname FROM pg_roles WHERE rolbypassrls AND NOT rolsuper"
        )
    assert [r["rolname"] for r in rows] == []
```

- [ ] **Step 2: Chạy test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/integration/test_isolation_helper.py -v`
Expected: FAIL — `control.enforce_tenant_isolation` và role `portal_api` chưa tồn tại.

- [ ] **Step 3: Tạo `migrations/versions/0003_role_and_isolation_helper.py`**

```python
"""role portal_api + helper bật cách ly cho một bảng

VÌ SAO CÓ HELPER: cách ly đúng chỉ khi BỐN điều kiện cùng đúng, và cả bốn hỏng
ÂM THẦM nếu sai (app chạy bình thường, test một-tenant vẫn xanh, chỉ dữ liệu là
rò). Viết bốn điều kiện đó ra một lời gọi duy nhất, một lần, thay vì lặp lại ở
mỗi module — mỗi lần lặp là một cơ hội sai.

  1. ENABLE ROW LEVEL SECURITY
  2. FORCE ROW LEVEL SECURITY   <- Postgres MIỄN RLS cho chủ bảng. Thiếu dòng
                                   này thì mọi truy vấn chạy bằng owner (script
                                   backfill, phiên debug) đi xuyên cách ly.
  3. policy tenant_isolation với CẢ USING (chặn đọc) và WITH CHECK (chặn ghi
     sang tenant khác)
  4. grant chuẩn cho role runtime

Điều kiện thứ tư của cách ly — SET LOCAL trong giao dịch tường minh — không ở
đây được, nó ở tầng Python: portal.core.db.session.tenant_conn().

HỆ QUẢ CỦA `FORCE` MÀ MIGRATION SAU PHẢI BIẾT: migration nào BACKFILL dữ liệu
(không chỉ DDL) cũng bị RLS lọc, vì nó chạy bằng owner. Luật: backfill phải
SET LOCAL app.tenant_id cho từng tenant, HOẶC
    ALTER TABLE ... NO FORCE ROW LEVEL SECURITY
    -> backfill ->
    ALTER TABLE ... FORCE ROW LEVEL SECURITY
trong CÙNG một migration. Ghi vào header của migration đó.

Revision ID: 0003_role_isolation
Revises: 0002_control_core
"""

from alembic import op

revision = "0003_role_isolation"
down_revision = "0002_control_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_all: role NHÓM (NOLOGIN) mà mọi agent_<tenant> là thành viên.
    # Nhờ nó, quyền của agent cấp MỘT LẦN cho nhóm thay vì lặp lại cho từng
    # role — nên create_agent_role() chỉ còn hai dòng, và module sau thêm bảng
    # agent ghi được thì grant một lần, không phải quét danh sách role đang có.
    # Nó cũng là chỗ để policy RLS trỏ tới (`TO agent_all`) — xem migration 0007.
    op.execute("CREATE ROLE agent_all NOLOGIN")

    # portal_api: role runtime của Portal API và của worker.
    # KHÔNG BYPASSRLS, KHÔNG superuser, KHÔNG owner bảng nào -> kể cả bug quên
    # WHERE cũng không rò chéo tenant. Mật khẩu do runbook deploy đặt; ở đây
    # đặt tạm để test nối được.
    op.execute("CREATE ROLE portal_api LOGIN PASSWORD 'apidev'")
    op.execute("GRANT USAGE ON SCHEMA portal, control TO portal_api")
    op.execute("GRANT EXECUTE ON FUNCTION portal.current_tenant() TO portal_api")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA control TO portal_api"
    )
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA control TO portal_api")
    # Bảng control tạo về sau (bởi M2a/M3, hoặc migration 0006/0007 của M1)
    # cũng được grant, khỏi phải nhớ.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA control "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_api"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT USAGE ON SEQUENCES TO portal_api")

    op.execute(
        """
        CREATE FUNCTION control.enforce_tenant_isolation(p_qualified_table text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            v_oid    oid;
            v_schema text;
        BEGIN
            v_oid := p_qualified_table::regclass;

            SELECT n.nspname INTO v_schema
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.oid = v_oid;

            IF v_schema <> 'tenant_data' THEN
                RAISE EXCEPTION
                    'enforce_tenant_isolation chỉ dùng cho bảng trong schema tenant_data, không phải %',
                    v_schema;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_attribute
                 WHERE attrelid = v_oid AND attname = 'tenant_id' AND attnum > 0 AND NOT attisdropped
            ) THEN
                RAISE EXCEPTION 'bảng % thiếu cột tenant_id — không bật được cách ly', p_qualified_table;
            END IF;

            EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', p_qualified_table);
            EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', p_qualified_table);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %s '
                'USING (tenant_id = portal.current_tenant()) '
                'WITH CHECK (tenant_id = portal.current_tenant())',
                p_qualified_table
            );
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON %s TO portal_api', p_qualified_table
            );
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION control.enforce_tenant_isolation(text)")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control REVOKE USAGE ON SEQUENCES FROM portal_api")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA control "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM portal_api"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA control FROM portal_api")
    op.execute("REVOKE ALL ON SCHEMA portal, control FROM portal_api")
    op.execute("DROP ROLE portal_api")
    op.execute("DROP ROLE agent_all")
```

- [ ] **Step 4: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/integration/test_isolation_helper.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/migrations/versions/0003_role_and_isolation_helper.py \
        apps/backend/tests/integration/test_isolation_helper.py
git commit -m "feat(m1): role portal_api + enforce_tenant_isolation() gồm FORCE RLS"
```

---

## Task 4: `tenant_data` lõi + `tenant_conn()` — CỔNG 1 (portal) · CỔNG 3 · CỔNG 6

> ✅ **ĐÃ LÀM — code trên branch là nguồn sự thật, không phải các khối code dưới đây.**
> Commit `fc09d31` (bản đầu) + `e96b227` (fix round 1). Các khối dưới giữ lại để đối chiếu.
>
> **Hai chỗ plan này SAI, lộ ra lúc thi hành:**
>
> 1. **Thiếu `apps/backend/tests/__init__.py`.** Không có nó thì `from tests.conftest import ...`
>    ném `ModuleNotFoundError`: pytest ở chế độ prepend dừng basedir ở thư mục **đầu tiên không có**
>    `__init__.py`, nên `tests/` nằm trên `sys.path` và `import tests` bất khả. Thêm file rỗng đó.
> 2. **Teardown của `owned_probe` thiếu `DROP OWNED BY`.** Setup cấp 4 `GRANT` cho role probe mà
>    teardown không thu hồi, nên `DROP ROLE` ném `DependentObjectsStillExistError` — và trong
>    container scope session thì lỗi đó lây sang mọi test sau. Thêm `DROP OWNED BY <role>` trước
>    `DROP ROLE`, và **drop bảng TRƯỚC khi drop role** (nếu lượt trước chết giữa đường, role cũ vẫn
>    sở hữu bảng nên `DROP ROLE` không chạy được).
>
> **Bốn chỗ plan này YẾU — review bắt được, đều cùng một dạng: *test pass được trong khi tính chất
> nó đặt tên đã vỡ*.** Bản trên branch đã sửa cả bốn:
>
> | # | Chỗ yếu | Vỡ thế nào mà test vẫn xanh | Đã sửa thành |
> |---|---|---|---|
> | 1 | Cổng 1 dùng `pytest.raises(InsufficientPrivilegeError)` trần | SQLSTATE **42501** do *cả* `permission denied for table` *lẫn* `new row violates row-level security policy` sinh ra. Policy thành `WITH CHECK (false)`, hoặc mất hẳn `GRANT INSERT`, test vẫn xanh | thêm `match="row-level security"` **+ test INSERT dương** (ghi vào đúng tenant mình phải thành công — nếu không thì *"insert bị chặn"* có thể đúng vì insert bị chặn với mọi người) |
> | 2 | Cổng 6 lọc `c.relkind = 'r'` | Bảng **phân mảnh** (`'p'`) lọt qua âm thầm — đúng thứ cổng 6 sinh ra để bắt ở module tương lai | `c.relkind IN ('r', 'p')` ở **cả hai** truy vấn |
> | 3 | Cổng 6 chỉ kiểm policy **theo tên** | `CREATE POLICY tenant_isolation ON t USING (true)` vẫn pass | assert `pg_policies.qual` **và** `with_check` đều chứa `current_tenant`. **`with_check` NULL (policy chỉ có `USING`) phải tính là VỠ**, không được bỏ qua — nó để hở chiều ghi |
> | 4 | `tenant_conn()` nhận mọi pool | `current_tenant()` ưu tiên `session_user` **trước** GUC. Gọi `tenant_conn(pool, "t1")` trên pool nối bằng `agent_t2` thì `SET LOCAL` **bị bỏ qua âm thầm** → đọc dữ liệu tenant khác, **không lỗi nào**. T5 làm nó thành reachable | đọc lại `portal.current_tenant()` sau `set_config`, lệch thì `RaiseError` nêu cả tenant hiệu lực và tenant được yêu cầu. Một roundtrip rẻ đổi lấy việc biến lỗi im lặng thành lỗi to |
>
> Kèm: role probe của cổng 3 khai tường minh `NOSUPERUSER NOBYPASSRLS` + assert lại từ `pg_roles`
> (toàn bộ giá trị của cổng 3 đứng trên việc probe **không** phải superuser, nên nó phải nói ra chứ
> không giả định).
>
> **Kết quả đã kiểm:** isolation 11 test xanh · suite 32 xanh · Step 9 chạy **hai lần** (lần sau vì
> cổng 6 đổi assertion): xoá `FORCE` ⇒ đúng 2 test đỏ, khôi phục ⇒ xanh, `git diff` trên 0003 rỗng.

**Files:**
- Create: `apps/backend/migrations/versions/0004_tenant_data_core.py`
- Create: `apps/backend/src/portal/core/db/session.py`
- Test: `apps/backend/tests/isolation/__init__.py`, `tests/isolation/conftest.py`, `tests/isolation/test_rls_isolation.py` (**CỔNG 1**), `tests/isolation/test_force_rls.py` (**CỔNG 3**), `tests/isolation/test_isolation_catalog.py` (**CỔNG 6**)

**Interfaces:**
- Consumes: `control.enforce_tenant_isolation()`, role `portal_api` (Task 3)
- Produces: schema `tenant_data` · `tenant_data.projects` · `tenant_data.units` · `tenant_conn(pool, tenant_id) -> AsyncIterator[asyncpg.Connection]` · fixture `seeded` (2 tenant, 2 project, 2 unit) và `api_pool`

- [ ] **Step 1: Tạo `tests/isolation/conftest.py`**

```python
"""Fixture dùng chung cho 6 cổng cách ly."""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from tests.conftest import API_PASSWORD, dsn_as

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    """Hai tenant t1/t2, mỗi tenant một project và một unit. Dọn sau test.

    Seed bằng portal_migrator (owner). Vì FORCE RLS áp cho owner, phải SET LOCAL
    app.tenant_id cho từng tenant — đây chính là luật ghi ở header migration 0003.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            for t in ("t1", "t2"):
                await conn.execute("INSERT INTO control.tenants (id, name) VALUES ($1, $1)", t)
        for t, unit_code, comm in (("t1", "A-01", "2%"), ("t2", "B-01", "3%")):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", t)
                await conn.execute(
                    "INSERT INTO tenant_data.projects (tenant_id, code, name) VALUES ($1, $2, $2)",
                    t, f"P-{t}",
                )
                await conn.execute(
                    """INSERT INTO tenant_data.units
                           (tenant_id, code, project_code, price_vnd, commission, extras)
                       VALUES ($1, $2, $3, 3500000000, $4, '{"fund_type":"A","phi_quan_ly":"12k"}'::jsonb)""",
                    t, unit_code, f"P-{t}", comm,
                )
    yield pool
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id IN ('t1', 't2')")


@pytest.fixture
async def api_pool(pg_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    """Pool nối bằng portal_api — role runtime thật, không phải owner."""
    p = await create_pool(dsn_as(pg_dsn, "portal_api", API_PASSWORD), min_size=1, max_size=2)
    yield p
    await p.close()
```

- [ ] **Step 2: Viết CỔNG 1 (phần portal) — `tests/isolation/test_rls_isolation.py`**

```python
"""CỔNG 1 — cách ly hàng. KHÔNG ĐƯỢC skip.

Cổng này canh: portal_api chỉ thấy hàng của tenant đã SET LOCAL, và không ghi
được hàng sang tenant khác. Phần agent role thêm ở Task 5.
"""

import asyncpg
import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def test_portal_api_chi_thay_tenant_da_set(seeded, api_pool):
    async with tenant_conn(api_pool, "t1") as conn:
        rows = await conn.fetch("SELECT code FROM tenant_data.units ORDER BY code")
    assert [r["code"] for r in rows] == ["A-01"]

    async with tenant_conn(api_pool, "t2") as conn:
        rows = await conn.fetch("SELECT code FROM tenant_data.units ORDER BY code")
    assert [r["code"] for r in rows] == ["B-01"]


async def test_khong_ghi_duoc_hang_sang_tenant_khac(seeded, api_pool):
    """WITH CHECK của policy chặn chiều GHI, USING chặn chiều ĐỌC."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_conn(api_pool, "t1") as conn:
            await conn.execute(
                "INSERT INTO tenant_data.units (tenant_id, code) VALUES ('t2', 'X-99')"
            )


async def test_khong_xoa_duoc_hang_tenant_khac(seeded, api_pool):
    async with tenant_conn(api_pool, "t1") as conn:
        deleted = await conn.execute("DELETE FROM tenant_data.units WHERE code = 'B-01'")
    assert deleted == "DELETE 0"
    async with tenant_conn(api_pool, "t2") as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.units") == 1


async def test_tenant_conn_tu_choi_tenant_rong(api_pool):
    with pytest.raises(ValueError, match="tenant_id rỗng"):
        async with tenant_conn(api_pool, ""):
            pass
```

- [ ] **Step 3: Viết CỔNG 3 — `tests/isolation/test_force_rls.py`**

```python
"""CỔNG 3 — chủ bảng KHÔNG được đi xuyên RLS.

Postgres MIỄN RLS cho role sở hữu bảng; chỉ FORCE ROW LEVEL SECURITY mới áp.
Không có cổng này thì mọi test một-tenant vẫn xanh trong khi cách ly đã vỡ.

VÌ SAO PHẢI TẠO ROLE OWNER RIÊNG: trong testcontainers, POSTGRES_USER
(portal_migrator) chính là bootstrap superuser — mà superuser bỏ qua RLS bất kể
FORCE. Nên cổng này tạo một role NOSUPERUSER, cho nó làm owner một bảng thử, và
kiểm trên đó. Test này CŨNG chứng minh chính FORCE là thứ đang làm việc: tắt
FORCE đi thì owner thấy cả hai tenant.
"""

import pytest

from portal.core.db.pool import create_pool
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration

OWNER_ROLE = "t_probe_owner"
OWNER_PASSWORD = "probedev"


@pytest.fixture
async def owned_probe(seeded, pool):
    """Bảng tenant_data.probe do một role NOSUPERUSER sở hữu, đã bật cách ly."""
    async with pool.acquire() as conn:
        await conn.execute(f"DROP ROLE IF EXISTS {OWNER_ROLE}")
        await conn.execute(f"CREATE ROLE {OWNER_ROLE} LOGIN PASSWORD '{OWNER_PASSWORD}'")
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        await conn.execute(
            """CREATE TABLE tenant_data.probe (
                   id        bigserial PRIMARY KEY,
                   tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
                   note      text NOT NULL DEFAULT ''
               )"""
        )
        await conn.execute("SELECT control.enforce_tenant_isolation('tenant_data.probe')")
        # Seed TRƯỚC khi chuyển owner: lúc này portal_migrator là superuser nên
        # bỏ qua RLS, ghi được cả hai tenant trong một lượt.
        await conn.execute(
            "INSERT INTO tenant_data.probe (tenant_id, note) VALUES ('t1', 'của t1'), ('t2', 'của t2')"
        )
        await conn.execute(f"ALTER TABLE tenant_data.probe OWNER TO {OWNER_ROLE}")
        await conn.execute(f"GRANT USAGE ON SCHEMA tenant_data, portal, control TO {OWNER_ROLE}")
        await conn.execute(f"GRANT EXECUTE ON FUNCTION portal.current_tenant() TO {OWNER_ROLE}")
        await conn.execute(f"GRANT SELECT ON control.tenants TO {OWNER_ROLE}")
    yield
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        await conn.execute(f"DROP ROLE IF EXISTS {OWNER_ROLE}")


async def test_chu_bang_bi_rls_chan_khi_co_force(owned_probe, pg_dsn):
    p = await create_pool(dsn_as(pg_dsn, OWNER_ROLE, OWNER_PASSWORD), min_size=1, max_size=1)
    try:
        async with p.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', 't1', true)")
            rows = await conn.fetch("SELECT note FROM tenant_data.probe")
        assert [r["note"] for r in rows] == ["của t1"], "chủ bảng thấy hàng của tenant khác"
    finally:
        await p.close()


async def test_tat_force_di_thi_chu_bang_thay_het(owned_probe, pool, pg_dsn):
    """Chứng minh chính FORCE là thứ đang làm việc — không phải may mắn.

    Nếu ai đó bỏ FORCE khỏi enforce_tenant_isolation(), test trên sẽ đỏ và test
    này sẽ là chỗ giải thích tại sao.
    """
    async with pool.acquire() as conn:
        await conn.execute("ALTER TABLE tenant_data.probe NO FORCE ROW LEVEL SECURITY")

    p = await create_pool(dsn_as(pg_dsn, OWNER_ROLE, OWNER_PASSWORD), min_size=1, max_size=1)
    try:
        async with p.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', 't1', true)")
            count = await conn.fetchval("SELECT count(*) FROM tenant_data.probe")
        assert count == 2, "bỏ FORCE mà chủ bảng vẫn bị chặn — giả định của cổng 3 sai"
    finally:
        await p.close()
        async with pool.acquire() as conn:
            await conn.execute("ALTER TABLE tenant_data.probe FORCE ROW LEVEL SECURITY")
```

- [ ] **Step 4: Viết CỔNG 6 — `tests/isolation/test_isolation_catalog.py`**

```python
"""CỔNG 6 — catalog test. Mọi bảng tenant_data phải có RLS + FORCE + policy.

Đây là cổng làm cho "mỗi module tự sở hữu bảng của nó" an toàn: module sau thêm
bảng mà quên gọi control.enforce_tenant_isolation() thì CI đỏ ngay, không phải
chờ ai review nhớ ra.

Chạy cho MỌI pull request, không path-filter.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_moi_bang_tenant_data_da_bat_cach_ly(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname,
                   c.relrowsecurity,
                   c.relforcerowsecurity,
                   EXISTS (
                       SELECT 1 FROM pg_policy p
                        WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation'
                   ) AS has_policy
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'tenant_data' AND c.relkind = 'r'
             ORDER BY c.relname
            """
        )

    assert rows, "schema tenant_data không có bảng nào — migration 0004 chưa chạy?"
    thieu = [
        f"{r['relname']}: rls={r['relrowsecurity']} force={r['relforcerowsecurity']} "
        f"policy={r['has_policy']}"
        for r in rows
        if not (r["relrowsecurity"] and r["relforcerowsecurity"] and r["has_policy"])
    ]
    assert not thieu, (
        "Bảng tenant_data thiếu cách ly. Trong migration của module bạn, thêm:\n"
        "    op.execute(\"SELECT control.enforce_tenant_isolation('tenant_data.<bảng>')\")\n"
        + "\n".join(thieu)
    )


async def test_moi_bang_tenant_data_co_cot_tenant_id(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'tenant_data' AND c.relkind = 'r'
               AND NOT EXISTS (
                   SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                      AND a.attnum > 0 AND NOT a.attisdropped
               )
            """
        )
    assert [r["relname"] for r in rows] == []


async def test_khong_co_cot_nao_ten_duoi_ty(pool):
    """Giá lưu bigint VND. Đổi đơn vị (tỷ -> VND) làm ở biên nhập, không ở tầng đọc."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            r"""SELECT table_name, column_name FROM information_schema.columns
                 WHERE table_schema = 'tenant_data' AND column_name LIKE '%\_ty'"""
        )
    assert [(r["table_name"], r["column_name"]) for r in rows] == []
```

- [ ] **Step 5: Chạy 3 file test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/isolation -v`
Expected: FAIL — schema `tenant_data` chưa có, `portal.core.db.session` chưa có.

- [ ] **Step 6: Tạo `migrations/versions/0004_tenant_data_core.py`**

```python
"""schema tenant_data + 2 bảng lõi để CHỨNG MINH cách ly

M1 chỉ tạo cột LÕI — vừa đủ để 6 cổng test chứng minh cách ly hàng và gate cột.
M4 ALTER thêm ~40 cột cho projects và ~45 cột cho units. Đó là NGOẠI LỆ đã hẹn
trước của luật "module không sửa bảng của module khác" (spec tổng §4④).

BA ĐIỀU BẮT BUỘC:
  1. Giá là bigint VND, không phải tỷ. Không cột nào tên *_ty. Đổi đơn vị làm
     ở biên NHẬP (M4). Đây chính là bug tỷ -> x1e9 mà agent đã phải sửa một lần.
  2. UNIQUE (tenant_id, code), KHÔNG phải UNIQUE(code). Hai tenant được dùng
     cùng mã căn. `code`/`phone` unique TOÀN CỤC là đúng chỗ đơn-tenant của CMS
     cũ lộ ra.
  3. KHÔNG tạo cột `tower`, và `floor` có cột nhưng KHÔNG được seed filterable.
     Quyết định #17 gỡ hai FILTER floor/tower khỏi tool schema, không gỡ cột:
     nbx_mongo khai hai filter đó cho LLM nhưng không đọc chúng, nên khách hỏi
     "căn tầng 14" thì trả căn tầng bất kỳ và agent đọc như thể đúng tầng.
     Sai âm thầm tệ hơn trả rỗng. `tower` thì vốn hardcode "" nên không tạo.

BA CỘT GATED: commission · bank_support · csbh_full. Chúng nhạy cảm thương mại
— hoa hồng lộ ra cho khách là sự cố thật. Chỉ lộ qua view agent_api khi
field_policy_live cho phép (migration 0005).

Revision ID: 0004_tenant_data
Revises: 0003_role_isolation
"""

from alembic import op

revision = "0004_tenant_data"
down_revision = "0003_role_isolation"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS tenant_data")
    op.execute("GRANT USAGE ON SCHEMA tenant_data TO portal_api")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_data GRANT USAGE ON SEQUENCES TO portal_api")

    op.execute(
        f"""
        CREATE TABLE tenant_data.projects (
            id         bigserial PRIMARY KEY,
            tenant_id  {_TENANT_FK},
            code       text NOT NULL,
            name       text NOT NULL DEFAULT '',
            slug       text NOT NULL DEFAULT '',
            type       text NOT NULL DEFAULT '',
            region     text NOT NULL DEFAULT '',
            location   text NOT NULL DEFAULT '',
            investor   text NOT NULL DEFAULT '',
            status     text NOT NULL DEFAULT 'draft',
            is_hot     boolean NOT NULL DEFAULT false,
            sort_hot   integer NOT NULL DEFAULT 0,
            overview   jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            lat        double precision,
            lng        double precision,
            extras     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT projects_tenant_code_key UNIQUE (tenant_id, code)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE tenant_data.units (
            id             bigserial PRIMARY KEY,
            tenant_id      {_TENANT_FK},
            code           text NOT NULL,
            project_code   text NOT NULL DEFAULT '',
            unit_type      text NOT NULL DEFAULT '',
            status         text NOT NULL DEFAULT 'unknown'
                           CHECK (status IN ('available', 'sold', 'booked', 'unknown')),
            direction      text NOT NULL DEFAULT '',
            price_vnd      bigint,
            price_tts_vnd  bigint,
            area_m2        numeric(10, 2),
            area_build_m2  numeric(10, 2),
            bedrooms       smallint,
            floor          smallint,
            fund_type      text NOT NULL DEFAULT '',
            commission     text NOT NULL DEFAULT '',
            bank_support   text NOT NULL DEFAULT '',
            csbh_full      text NOT NULL DEFAULT '',
            csbh_brief     text NOT NULL DEFAULT '',
            gift           text NOT NULL DEFAULT '',
            legal          text NOT NULL DEFAULT '',
            extras         jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT units_tenant_code_key UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("CREATE INDEX units_tenant_project_idx ON tenant_data.units (tenant_id, project_code)")
    op.execute("CREATE INDEX units_tenant_status_idx ON tenant_data.units (tenant_id, status)")

    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.projects')")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.units')")


def downgrade() -> None:
    op.execute("DROP TABLE tenant_data.units")
    op.execute("DROP TABLE tenant_data.projects")
    op.execute("DROP SCHEMA tenant_data CASCADE")
```

- [ ] **Step 7: Tạo `src/portal/core/db/session.py`**

```python
"""Cửa DUY NHẤT để truy vấn tenant_data.

VÌ SAO PHẢI LÀ SET LOCAL, KHÔNG BAO GIỜ LÀ SET TRẦN:
SET LOCAL chỉ sống trong một giao dịch; SET trần sống cả kết nối. Kết nối được
tái dùng từ pool, nên với SET trần:

    request A (anphu)   -> lấy kết nối #7 -> SET app.tenant_id='anphu' -> trả #7 về pool
    request B (sunrise) -> lấy kết nối #7 -> quên set -> KẾ THỪA 'anphu'
                                                     -> đọc dữ liệu của An Phú

Lỗi này CHỈ hiện khi có tải thật. Cổng 4 (tests/isolation/test_pool_leak.py)
canh đúng nó.

set_config(..., is_local => true) là dạng hàm của SET LOCAL, dùng được với tham
số bind — nên tenant_id không bao giờ nối chuỗi vào SQL.

tenant_id PHẢI đến từ membership đã xác thực (M2a), KHÔNG BAO GIỜ từ path param,
query string, hay body. Nếu bạn thấy mình đang đọc tenant_id từ request rồi
truyền thẳng vào đây — dừng lại, đó là lỗ hổng.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def tenant_conn(pool: asyncpg.Pool, tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    if not tenant_id:
        raise ValueError("tenant_id rỗng — tenant_conn() luôn cần tenant tường minh")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
        yield conn
```

- [ ] **Step 8: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/isolation -v`
Expected: CỔNG 1 (4 PASS) · CỔNG 3 (2 PASS) · CỔNG 6 (3 PASS).

- [ ] **Step 9: Kiểm tay rằng cổng 3 thật sự canh `FORCE`**

Sửa tạm `migrations/versions/0003_role_and_isolation_helper.py`, xoá dòng:

```python
EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', p_qualified_table);
```

Run: `cd apps/backend && uv run pytest tests/isolation -v`
Expected: **`test_chu_bang_bi_rls_chan_khi_co_force` ĐỎ** + `test_moi_bang_tenant_data_da_bat_cach_ly` ĐỎ.

Khôi phục lại dòng đó, chạy lại — xanh. **Ghi kết quả vào commit message.**

- [ ] **Step 10: Commit**

```bash
git add apps/backend/migrations/versions/0004_tenant_data_core.py \
        apps/backend/src/portal/core/db/session.py \
        apps/backend/tests/isolation/
git commit -m "feat(m1): tenant_data lõi + tenant_conn() — CỔNG 1, 3, 6

Đã kiểm tay: xoá FORCE ROW LEVEL SECURITY khỏi enforce_tenant_isolation()
làm test_chu_bang_bi_rls_chan_khi_co_force và catalog test ĐỎ."
```

---

## Task 5: `agent_api` view definer — CỔNG 1 (agent) · CỔNG 2 · CỔNG 5

**Files:**
- Create: `apps/backend/migrations/versions/0005_agent_api.py`
- Create: `apps/backend/tests/isolation/test_view_column_gate.py` (**CỔNG 2**), `tests/isolation/test_role_privileges.py` (**CỔNG 5**)
- Modify: `apps/backend/tests/isolation/conftest.py` (thêm fixture `agent_pool`), `tests/isolation/test_rls_isolation.py` (thêm phần agent role)

**Interfaces:**
- Consumes: `control.field_policy_live` (Task 2), `tenant_data.projects`/`units` (Task 4)
- Produces: `portal.pol(p_entity text, p_field text) -> boolean` · `portal.gated_extras(p_entity text, p_extras jsonb) -> jsonb` · schema `agent_api` · `agent_api.projects` · `agent_api.units` · `control.grant_agent_write(p_qualified_table text) -> void` · `control.create_agent_role(p_tenant text, p_password text) -> void`

- [ ] **Step 1: Thêm fixture `agent_pool` vào `tests/isolation/conftest.py`**

Nối vào cuối file:

```python
AGENT_PASSWORD = "agentdev"


@pytest.fixture
async def agent_roles(seeded, pool):
    """Tạo role agent_t1 và agent_t2 bằng đúng hàm mà provisioning dùng."""
    async with pool.acquire() as conn:
        for t in ("t1", "t2"):
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")
            await conn.execute("SELECT control.create_agent_role($1, $2)", t, AGENT_PASSWORD)
    yield
    async with pool.acquire() as conn:
        for t in ("t1", "t2"):
            await conn.execute(f"REASSIGN OWNED BY agent_{t} TO portal_migrator")
            await conn.execute(f"DROP OWNED BY agent_{t}")
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")


@pytest.fixture
async def agent_pool(agent_roles, pg_dsn):
    """Factory: agent_pool('t1') -> pool nối bằng role agent_t1."""
    pools: list[asyncpg.Pool] = []

    async def make(tenant: str) -> asyncpg.Pool:
        p = await create_pool(dsn_as(pg_dsn, f"agent_{tenant}", AGENT_PASSWORD), min_size=1, max_size=2)
        pools.append(p)
        return p

    yield make
    for p in pools:
        await p.close()
```

- [ ] **Step 2: Thêm phần agent vào CỔNG 1 — nối vào `tests/isolation/test_rls_isolation.py`**

```python
async def test_agent_role_chi_thay_tenant_cua_minh(agent_pool):
    """CỔNG 1 lõi: agent_t1 đọc view chỉ thấy hàng của t1.

    Không SET LOCAL gì cả — tenant suy từ session_user. Agent KHÔNG tự đổi được.
    """
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        rows = await conn.fetch("SELECT code FROM agent_api.units ORDER BY code")
    assert [r["code"] for r in rows] == ["A-01"]

    p2 = await agent_pool("t2")
    async with p2.acquire() as conn:
        rows = await conn.fetch("SELECT code FROM agent_api.units ORDER BY code")
    assert [r["code"] for r in rows] == ["B-01"]


async def test_agent_dat_guc_tenant_khac_cung_vo_dung(agent_pool):
    """Thứ tự COALESCE: tên role thắng GUC. Agent không leo thang được."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', 't2', true)")
        rows = await conn.fetch("SELECT code FROM agent_api.units")
    assert [r["code"] for r in rows] == ["A-01"], "GUC đè được tên role — cách ly agent vỡ"


async def test_agent_khong_doc_duoc_bang_goc(agent_pool):
    """Agent có ZERO quyền trên tenant_data — mạnh hơn RLS: không vào được cửa."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT code FROM tenant_data.units")
```

- [ ] **Step 3: Viết CỔNG 2 — `tests/isolation/test_view_column_gate.py`**

```python
"""CỔNG 2 — gate cột. agent_readable=false thì cột về NULL và key extras bị lọc.

Ba cột GATED (commission · bank_support · csbh_full) nhạy cảm thương mại: hoa
hồng lộ ra cho khách là sự cố thật, không phải tính năng phụ.

Cổng này cũng chứng minh gate là DỮ LIỆU, không phải schema: đổi
field_policy_live là view đổi theo NGAY, không cần migration.
"""

import pytest

pytestmark = pytest.mark.integration


async def _set_policy(pool, tenant, entity, field, *, is_core, readable):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO control.field_policy_live
                   (tenant_id, entity, field, is_core, agent_readable)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (tenant_id, entity, field)
               DO UPDATE SET is_core = $4, agent_readable = $5""",
            tenant, entity, field, is_core, readable,
        )


async def test_mac_dinh_khong_co_policy_thi_cot_gated_ve_null(agent_pool):
    """Chặn mặc định: không có hàng policy -> pol() trả false."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        row = await conn.fetchrow("SELECT commission, bank_support, csbh_full FROM agent_api.units")
    assert row["commission"] is None
    assert row["bank_support"] is None
    assert row["csbh_full"] is None


async def test_bat_agent_readable_thi_cot_hien_ra(agent_pool, pool):
    p1 = await agent_pool("t1")
    await _set_policy(pool, "t1", "unit", "commission", is_core=True, readable=True)
    async with p1.acquire() as conn:
        row = await conn.fetchrow("SELECT commission, bank_support FROM agent_api.units")
    assert row["commission"] == "2%"
    assert row["bank_support"] is None, "bật một cột không được mở cột khác"


async def test_policy_cua_tenant_khac_khong_mo_cot_cho_minh(agent_pool, pool):
    """pol() lọc theo current_tenant() — policy của t2 không ảnh hưởng t1."""
    p1 = await agent_pool("t1")
    await _set_policy(pool, "t2", "unit", "commission", is_core=True, readable=True)
    async with p1.acquire() as conn:
        row = await conn.fetchrow("SELECT commission FROM agent_api.units")
    assert row["commission"] is None


async def test_extras_chi_giu_key_da_khai(agent_pool, pool):
    """Seed có extras = {"fund_type": "A", "phi_quan_ly": "12k"}."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        assert await conn.fetchval("SELECT extras FROM agent_api.units") == "{}"

    await _set_policy(pool, "t1", "unit", "phi_quan_ly", is_core=False, readable=True)
    async with p1.acquire() as conn:
        extras = await conn.fetchval("SELECT extras FROM agent_api.units")
    assert extras == '{"phi_quan_ly": "12k"}'


async def test_is_core_true_khong_mo_key_extras(agent_pool, pool):
    """gated_extras() chỉ nhận key có is_core = false. Khai sai loại thì không mở."""
    p1 = await agent_pool("t1")
    await _set_policy(pool, "t1", "unit", "phi_quan_ly", is_core=True, readable=True)
    async with p1.acquire() as conn:
        assert await conn.fetchval("SELECT extras FROM agent_api.units") == "{}"


async def test_view_khong_lo_cot_tenant_id(agent_pool):
    """Agent không cần biết tenant_id — nó chỉ có một tenant."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        with pytest.raises(Exception, match="tenant_id"):
            await conn.fetch("SELECT tenant_id FROM agent_api.units")
```

- [ ] **Step 4: Viết CỔNG 5 — `tests/isolation/test_role_privileges.py`**

```python
"""CỔNG 5 — quyền role. Canh điều kiện 2 và 3 của cách ly.

Cả hai hỏng ÂM THẦM: app chạy bình thường, chỉ dữ liệu là rò.
"""

import pytest

pytestmark = pytest.mark.integration

RUNTIME_ROLES = ("portal_api", "agent_all", "agent_t1", "agent_t2")


async def test_khong_role_runtime_nao_co_dac_quyen(agent_roles, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
            "FROM pg_roles WHERE rolname = ANY($1::text[])",
            list(RUNTIME_ROLES),
        )
    assert {r["rolname"] for r in rows} == set(RUNTIME_ROLES)
    for r in rows:
        assert r["rolsuper"] is False, f"{r['rolname']} là superuser"
        assert r["rolbypassrls"] is False, f"{r['rolname']} có BYPASSRLS"
        assert r["rolcreaterole"] is False
        assert r["rolcreatedb"] is False


async def test_role_runtime_khong_so_huu_bang_nao(agent_roles, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('control', 'tenant_data', 'agent_api', 'portal')
                  AND c.relkind IN ('r', 'v')
                  AND pg_get_userbyid(c.relowner) = ANY($1::text[])""",
            list(RUNTIME_ROLES),
        )
    assert [(r["relname"], r["owner"]) for r in rows] == []


async def test_agent_khong_co_quyen_nao_tren_tenant_data(agent_roles, pool):
    """Điều kiện 3: zero privilege trên bảng gốc. Có quyền là bỏ qua gate cột."""
    async with pool.acquire() as conn:
        for table in ("tenant_data.units", "tenant_data.projects"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                got = await conn.fetchval(
                    "SELECT has_table_privilege('agent_t1', $1, $2)", table, priv
                )
                assert got is False, f"agent_t1 có {priv} trên {table}"


async def test_agent_chi_doc_duoc_bang_control_duy_nhat_la_heartbeat(agent_roles, pool):
    """Agent cần USAGE trên control để ghi agent_heartbeats (nó ở schema control).

    Nhưng KHÔNG được có quyền nào trên bảng control khác. Đây là chỗ dễ nới lỏng
    "cho tiện" nhất, nên có test canh.

    agent_heartbeats do migration 0007 tạo — trước đó danh sách cho phép là rỗng.
    """
    allowed = {"agent_heartbeats"}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'control' ORDER BY tablename"
        )
        vi_pham = []
        for r in rows:
            if r["tablename"] in allowed:
                continue
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if await conn.fetchval(
                    "SELECT has_table_privilege('agent_t1', $1, $2)",
                    f"control.{r['tablename']}", priv,
                ):
                    vi_pham.append(f"control.{r['tablename']}:{priv}")
    assert vi_pham == [], f"agent_t1 có quyền không được phép: {vi_pham}"


async def test_agent_chi_select_tren_view_agent_api(agent_roles, pool):
    async with pool.acquire() as conn:
        for view in ("agent_api.units", "agent_api.projects"):
            assert await conn.fetchval(
                "SELECT has_table_privilege('agent_t1', $1, 'SELECT')", view
            ) is True
            for priv in ("INSERT", "UPDATE", "DELETE"):
                assert await conn.fetchval(
                    "SELECT has_table_privilege('agent_t1', $1, $2)", view, priv
                ) is False


async def test_view_agent_api_khong_dung_security_invoker(pool):
    """Sửa lỗi C1. security_invoker=true buộc agent có SELECT trên bảng gốc,
    và khi có quyền đó thì agent query thẳng bảng gốc, bỏ qua toàn bộ gate cột."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.relname, c.reloptions
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'agent_api' AND c.relkind = 'v'"""
        )
    assert rows, "schema agent_api không có view nào"
    for r in rows:
        opts = r["reloptions"] or []
        assert not any("security_invoker=true" in o for o in opts), (
            f"view {r['relname']} bật security_invoker — xem docs/contracts/isolation.md §5.1"
        )


async def test_create_agent_role_tu_choi_slug_khong_hop_le(pool):
    """Slug đi thẳng vào câu CREATE ROLE — validate ở cả DB và hàm."""
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('okslug', 'OK')")
        with pytest.raises(Exception, match="tenant id không hợp lệ"):
            await conn.execute("SELECT control.create_agent_role('bad;slug', 'p')")
        with pytest.raises(Exception, match="tenant chưa tồn tại"):
            await conn.execute("SELECT control.create_agent_role('nosuch', 'p')")
        await conn.execute("DELETE FROM control.tenants WHERE id = 'okslug'")
```

- [ ] **Step 5: Chạy test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/isolation -v`
Expected: FAIL — `control.create_agent_role` và schema `agent_api` chưa tồn tại.

- [ ] **Step 6: Tạo `migrations/versions/0005_agent_api.py`**

```python
"""schema agent_api — view DEFINER là hợp đồng đọc DUY NHẤT của agent

VÌ SAO KHÔNG DÙNG security_invoker (sửa lỗi C1 — spec gốc §5.4 ghi SAI):
  security_invoker=true bắt Postgres kiểm quyền của NGƯỜI GỌI trên bảng gốc,
  nghĩa là agent role phải được GRANT SELECT ON tenant_data.units. Có quyền đó
  là agent query THẲNG bảng gốc và bỏ qua toàn bộ gate cột. Cơ chế "view lo cột"
  bị vô hiệu hoàn toàn.

  Nên view ở đây là DEFINER (mặc định): agent có ZERO quyền trên tenant_data,
  chỉ SELECT được trên view. "Không vào được cửa" mạnh hơn "được vào nhưng bị
  lọc hàng".

HAI HỆ QUẢ CỦA DEFINER, cả hai phải xử lý tường minh:
  1. View chạy bằng quyền owner nên RLS của owner KHÔNG áp -> view PHẢI tự lọc
     tenant trong WHERE. Thiếu WHERE là rò hết, không có lỗi nào.
  2. Tenant phải suy từ session_user, KHÔNG phải current_user: trong view
     definer current_user trả về OWNER của view, không phải agent.

VÌ SAO pol() VÀ gated_extras() LÀ SECURITY DEFINER:
  Agent KHÔNG có SELECT trên control.field_policy_live. Nếu để hàm SQL thường
  thì việc nó đọc được bảng đó phụ thuộc vào Postgres có inline hàm vào câu
  query của view hay không — tức phụ thuộc một chi tiết TỐI ƯU HOÁ. Khai
  SECURITY DEFINER làm nó tường minh và không đổi theo phiên bản.
  session_user KHÔNG bị SECURITY DEFINER đổi, nên current_tenant() vẫn đúng.
  SET search_path cố định để chặn search_path injection.

Revision ID: 0005_agent_api
Revises: 0004_tenant_data
"""

from alembic import op

revision = "0005_agent_api"
down_revision = "0004_tenant_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pol(): field này agent đọc được không. KHÔNG có hàng policy -> false (chặn mặc định).
    op.execute(
        """
        CREATE FUNCTION portal.pol(p_entity text, p_field text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(
                (SELECT agent_readable FROM control.field_policy_live
                  WHERE tenant_id = portal.current_tenant()
                    AND entity = p_entity AND field = p_field),
                false)
        $$
        """
    )

    # gated_extras(): chỉ giữ key đã khai agent_readable VÀ is_core = false.
    # is_core = true nghĩa là cột thật, gate bằng CASE WHEN — không phải key extras.
    op.execute(
        """
        CREATE FUNCTION portal.gated_extras(p_entity text, p_extras jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
              FROM jsonb_each(coalesce(p_extras, '{}'::jsonb)) AS e
             WHERE EXISTS (
                   SELECT 1 FROM control.field_policy_live f
                    WHERE f.tenant_id = portal.current_tenant()
                      AND f.entity = p_entity
                      AND f.field = e.key
                      AND f.is_core = false
                      AND f.agent_readable
             )
        $$
        """
    )

    op.execute("CREATE SCHEMA agent_api")

    # View KHÔNG lộ tenant_id: agent chỉ có một tenant, biết id của mình là dư.
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

    # floor CÓ trong bảng nhưng KHÔNG lên view: quyết định #17 — dữ liệu tầng
    # không tin được, và agent đọc một giá trị không tin được như thể đúng thì
    # sai âm thầm, tệ hơn trả rỗng. M4 quyết định lại khi có dữ liệu thật.
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

    op.execute("GRANT USAGE ON SCHEMA agent_api TO portal_api")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO portal_api")

    # QUYỀN ĐỌC CỦA AGENT CẤP CHO ROLE NHÓM, MỘT LẦN.
    # Nhờ vậy create_agent_role() chỉ còn CREATE ROLE + GRANT agent_all — không
    # có danh sách grant nào phải nhớ cập nhật khi thêm view.
    op.execute("GRANT USAGE ON SCHEMA agent_api, portal TO agent_all")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO agent_all")
    op.execute("GRANT EXECUTE ON FUNCTION portal.current_tenant() TO agent_all")
    # View thêm về sau (M3/M4/M7) tự động được cấp — không ai phải nhớ.
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ON TABLES TO agent_all")

    # Hàm module sau gọi trong migration của mình để mở đường GHI cho agent.
    # Cấp cho NHÓM nên không phải quét danh sách role đang tồn tại, và role tạo
    # về sau cũng có ngay.
    op.execute(
        """
        CREATE FUNCTION control.grant_agent_write(p_qualified_table text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE v_schema text;
        BEGIN
            SELECT n.nspname INTO v_schema
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.oid = p_qualified_table::regclass;
            IF v_schema <> 'tenant_data' THEN
                RAISE EXCEPTION 'agent chỉ được ghi bảng trong tenant_data, không phải %', v_schema;
            END IF;
            EXECUTE format('GRANT USAGE ON SCHEMA tenant_data TO agent_all');
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %s TO agent_all', p_qualified_table);
        END $$
        """
    )

    # Cấp role cho một tenant. Gọi lúc provisioning.
    # Đặt tên agent_<tenant> là HỢP ĐỒNG: portal.current_tenant() parse chính tên này.
    op.execute(
        r"""
        CREATE FUNCTION control.create_agent_role(p_tenant text, p_password text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            IF p_tenant !~ '^[a-z][a-z0-9_]{1,30}$' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM control.tenants WHERE id = p_tenant) THEN
                RAISE EXCEPTION 'tenant chưa tồn tại: %', p_tenant;
            END IF;

            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', r, p_password);
            -- Toàn bộ quyền đến từ nhóm. Hàm này KHÔNG có danh sách grant riêng
            -- nào — thêm view hay bảng mới thì grant cho agent_all, không sửa đây.
            EXECUTE format('GRANT agent_all TO %I', r);
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION control.create_agent_role(text, text)")
    op.execute("DROP FUNCTION control.grant_agent_write(text)")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api REVOKE SELECT ON TABLES FROM agent_all")
    op.execute("DROP SCHEMA agent_api CASCADE")
    op.execute("DROP FUNCTION portal.gated_extras(text, jsonb)")
    op.execute("DROP FUNCTION portal.pol(text, text)")
```

- [ ] **Step 7: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/isolation -v`
Expected: CỔNG 1 (7 PASS) · CỔNG 2 (6 PASS) · CỔNG 3 (2 PASS) · CỔNG 5 (8 PASS) · CỔNG 6 (3 PASS).

- [ ] **Step 8: Commit**

```bash
git add apps/backend/migrations/versions/0005_agent_api.py apps/backend/tests/isolation/
git commit -m "feat(m1): agent_api view definer + create_agent_role — CỔNG 1, 2, 5

Theo sửa lỗi C1: view definer, KHÔNG security_invoker. pol()/gated_extras()
là SECURITY DEFINER để không phụ thuộc vào việc Postgres có inline hàm SQL.
Mọi quyền của agent cấp cho role nhóm agent_all, nên create_agent_role()
chỉ còn CREATE ROLE + GRANT agent_all — M7 thêm bảng agent ghi được bằng
grant_agent_write() mà không sửa hàm nào."
```

---

## Task 6: CỔNG 4 — rò rỉ qua connection pool

**Files:**
- Test: `apps/backend/tests/isolation/test_pool_leak.py`

**Interfaces:**
- Consumes: `tenant_conn()` (Task 4), fixture `seeded`/`api_pool` (Task 4)
- Produces: — (chỉ test)

- [ ] **Step 1: Viết CỔNG 4**

`apps/backend/tests/isolation/test_pool_leak.py`:

```python
"""CỔNG 4 — rò rỉ tenant qua connection pool. Điều kiện 4 của cách ly.

Lỗi này CHỈ hiện khi có tải thật: ở máy dev một người bấm một lúc thì không bao
giờ thấy. Không có cổng này thì nó sống tới production.

max_size=1 để BUỘC hai request dùng đúng một kết nối vật lý — đó là điều kiện
tái hiện, không phải chi tiết ngẫu nhiên.
"""

import asyncio

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from tests.conftest import API_PASSWORD, dsn_as

pytestmark = pytest.mark.integration


@pytest.fixture
async def one_conn_pool(pg_dsn):
    p = await create_pool(dsn_as(pg_dsn, "portal_api", API_PASSWORD), min_size=1, max_size=1)
    yield p
    await p.close()


async def test_request_sau_khong_ke_thua_tenant_cua_request_truoc(seeded, one_conn_pool):
    async with tenant_conn(one_conn_pool, "t1") as conn:
        assert [r["code"] for r in await conn.fetch("SELECT code FROM tenant_data.units")] == ["A-01"]

    # Cùng kết nối vật lý, KHÔNG set tenant. Phải ra 0 hàng, không phải A-01.
    async with one_conn_pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch("SELECT code FROM tenant_data.units")
    assert [r["code"] for r in rows] == [], "kế thừa tenant của request trước — cách ly vỡ"


async def test_guc_khong_song_qua_ranh_gioi_giao_dich(seeded, one_conn_pool):
    """set_config(..., is_local => true) tự hết hiệu lực khi transaction kết thúc."""
    async with tenant_conn(one_conn_pool, "t1"):
        pass
    async with one_conn_pool.acquire() as conn:
        assert await conn.fetchval("SELECT portal.current_tenant()") is None


async def test_hai_tenant_xen_ke_khong_lan_nhau(seeded, one_conn_pool):
    """Chạy xen kẽ trên cùng pool max_size=1 — asyncpg xếp hàng, mỗi lượt phải đúng tenant."""

    async def doc(tenant: str) -> list[str]:
        async with tenant_conn(one_conn_pool, tenant) as conn:
            rows = await conn.fetch("SELECT code FROM tenant_data.units ORDER BY code")
        return [r["code"] for r in rows]

    got = await asyncio.gather(*(doc(t) for t in ("t1", "t2", "t1", "t2", "t1")))
    assert got == [["A-01"], ["B-01"], ["A-01"], ["B-01"], ["A-01"]]


async def test_set_tran_ngoai_giao_dich_thi_ro_that(seeded, one_conn_pool):
    """Chứng minh SET trần LÀ lỗ hổng — đây là lý do tenant_conn() dùng SET LOCAL.

    Nếu test này ngừng rò (Postgres đổi hành vi), giả định của cổng 4 sai và
    phải xem lại tenant_conn().
    """
    async with one_conn_pool.acquire() as conn:
        await conn.execute("SET app.tenant_id = 't1'")   # KHÔNG có transaction, KHÔNG LOCAL

    async with one_conn_pool.acquire() as conn:
        leaked = await conn.fetchval("SELECT portal.current_tenant()")
    assert leaked == "t1", "SET trần không rò nữa — xem lại giả định của cổng 4"

    async with one_conn_pool.acquire() as conn:
        await conn.execute("RESET app.tenant_id")
```

- [ ] **Step 2: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/isolation/test_pool_leak.py -v`
Expected: 4 PASS.

Nếu `test_request_sau_khong_ke_thua...` FAIL thì `tenant_conn()` đang dùng `SET` trần thay vì `set_config(..., true)` — sửa `session.py`.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/tests/isolation/test_pool_leak.py
git commit -m "test(m1): CỔNG 4 — rò rỉ tenant qua connection pool"
```

---

## Task 7: `control.jobs` + worker + handler registry

**Files:**
- Create: `apps/backend/migrations/versions/0006_jobs.py`
- Create: `apps/backend/src/portal/core/jobs.py`
- Create: `apps/backend/src/portal/worker/__init__.py`, `src/portal/worker/__main__.py`
- Test: `apps/backend/tests/modules/__init__.py`, `tests/modules/test_worker.py`

**Interfaces:**
- Consumes: `tenant_conn()` (Task 4), `control.tenants` (Task 2)
- Produces: `control.jobs(id, tenant_id, kind, state, actor, payload, started_at, finished_at, count, message, force)` · `JobHandler = Callable[[asyncpg.Connection, dict], Awaitable[JobResult]]` · `JobResult` dataclass (`count: int`, `message: str`) · `register(kind: str, handler: JobHandler) -> None` · `get_handler(kind: str) -> JobHandler | None` · `enqueue(conn, *, tenant_id, kind, actor, payload) -> int` · `run_once(pool) -> int | None`

- [ ] **Step 1: Viết test trước**

`apps/backend/tests/modules/test_worker.py`:

```python
"""Worker + handler registry. Cơ chế làm module sau thêm loại job mà không sửa file của M1."""

import asyncio

import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, enqueue, register, run_once

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name) VALUES ('jt', 'JobTenant')")
    yield "jt"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'jt'")


@pytest.fixture
async def api_pool_jobs(pg_dsn):
    from portal.core.db.pool import create_pool
    from tests.conftest import API_PASSWORD, dsn_as

    p = await create_pool(dsn_as(pg_dsn, "portal_api", API_PASSWORD), min_size=1, max_size=4)
    yield p
    await p.close()


async def test_kind_moi_khong_can_migration(tenant, api_pool_jobs):
    """kind là text tự do — module sau thêm loại job không cần đổi schema."""
    seen: list[dict] = []

    async def handle(conn, payload):
        seen.append(payload)
        return JobResult(count=len(payload), message="xong")

    register("kind_hoan_toan_moi", handle)

    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(
            conn, tenant_id=tenant, kind="kind_hoan_toan_moi", actor="test", payload={"a": 1}
        )

    assert await run_once(api_pool_jobs) == job_id
    assert seen == [{"a": 1}]

    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, count, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "success"
    assert row["count"] == 1
    assert row["message"] == "xong"


async def test_handler_chay_trong_tenant_conn_nen_bi_rls(tenant, api_pool_jobs):
    """Handler thấy đúng tenant của job — không phải thấy tất cả."""
    got: list[str | None] = []

    async def handle(conn, payload):
        got.append(await conn.fetchval("SELECT portal.current_tenant()"))
        return JobResult(count=0, message="")

    register("kiem_tenant", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="kiem_tenant", actor="test", payload={})
    await run_once(api_pool_jobs)
    assert got == [tenant]


async def test_handler_nem_loi_thi_job_failed_khong_retry(tenant, api_pool_jobs):
    async def handle(conn, payload):
        raise RuntimeError("cố tình vỡ")

    register("hong", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="hong", actor="test", payload={})

    await run_once(api_pool_jobs)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "failed"
    assert "cố tình vỡ" in row["message"]

    assert await run_once(api_pool_jobs) is None, "job failed bị nhặt lại — mặc định KHÔNG retry"


async def test_kind_khong_co_handler_thi_failed_ro_rang(tenant, api_pool_jobs):
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="khong_ai_khai", actor="t", payload={})
    await run_once(api_pool_jobs)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "failed"
    assert "không có handler" in row["message"]


async def test_hai_worker_khong_nhat_trung_mot_job(tenant, api_pool_jobs):
    """SKIP LOCKED: worker thứ hai bỏ qua job đang bị khoá, không đợi."""
    started = asyncio.Event()
    release = asyncio.Event()
    lan_chay = 0

    async def handle(conn, payload):
        nonlocal lan_chay
        lan_chay += 1
        started.set()
        await release.wait()
        return JobResult(count=0, message="")

    register("cham", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="cham", actor="t", payload={})

    task = asyncio.create_task(run_once(api_pool_jobs))
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await run_once(api_pool_jobs) is None, "worker thứ hai nhặt trùng job"
    release.set()
    await task
    assert lan_chay == 1


async def test_khong_co_job_thi_tra_none(api_pool_jobs):
    assert await run_once(api_pool_jobs) is None
```

- [ ] **Step 2: Chạy test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/modules/test_worker.py -v`
Expected: FAIL — `portal.core.jobs` chưa tồn tại.

- [ ] **Step 3: Tạo `migrations/versions/0006_jobs.py`**

```python
"""control.jobs — hàng đợi job dùng chung

VÌ SAO Ở M1 CHỨ KHÔNG Ở M3: bốn module cần nó — M4 (import file), M6 (build
index), M8 (job xoá quá hạn), M3 (publish). Để nó ở M3 là buộc ba module đợi
một module.

VÌ SAO KHÔNG DÙNG BackgroundTasks CỦA FASTAPI: nó chết cùng tiến trình và không
để lại dấu vết nào. Một bảng job là cách rẻ nhất để lời hứa "job xoá quá hạn
phải có giám sát" (quyết định #19 — 6 tháng nằm trong hợp đồng với khách) thành
thật thay vì khẩu hiệu: job không chạy thì bảng này cho thấy ngay.

VÌ SAO kind LÀ text TỰ DO, KHÔNG PHẢI enum/CHECK: module sau thêm loại job mà
không cần migration. Danh sách đã biết: publish (M3) · import (M4) ·
rag_build (M6) · retention_delete (M8).

VÌ SAO CÓ CỘT payload: handler tự định nghĩa hình dạng đầu vào của mình. M1
không cần biết M4 truyền gì.

Revision ID: 0006_jobs
Revises: 0005_agent_api
"""

from alembic import op

revision = "0006_jobs"
down_revision = "0005_agent_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.jobs (
            id          bigserial PRIMARY KEY,
            tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            kind        text NOT NULL CHECK (kind <> ''),
            state       text NOT NULL DEFAULT 'queued'
                        CONSTRAINT jobs_state_check
                        CHECK (state IN ('queued', 'running', 'success', 'failed')),
            actor       text NOT NULL DEFAULT '',
            payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at  timestamptz NOT NULL DEFAULT now(),
            started_at  timestamptz,
            finished_at timestamptz,
            count       integer NOT NULL DEFAULT 0,
            message     text NOT NULL DEFAULT '',
            force       boolean NOT NULL DEFAULT false
        )
        """
    )
    # Index riêng cho vòng lặp FOR UPDATE SKIP LOCKED — chỉ hàng queued.
    op.execute("CREATE INDEX jobs_queued_idx ON control.jobs (id) WHERE state = 'queued'")
    # Index cho màn danh sách job của một workspace.
    op.execute("CREATE INDEX jobs_tenant_created_idx ON control.jobs (tenant_id, created_at DESC)")
    # Giám sát: job running quá lâu là bất thường, người xử lý chứ không phải
    # máy đoán. Worker chết giữa lúc chạy để lại đúng trạng thái này.
    op.execute(
        """
        CREATE VIEW control.jobs_stuck AS
        SELECT id, tenant_id, kind, actor, started_at, now() - started_at AS stuck_for
          FROM control.jobs
         WHERE state = 'running' AND started_at < now() - interval '15 minutes'
        """
    )
    op.execute("GRANT SELECT ON control.jobs_stuck TO portal_api")


def downgrade() -> None:
    op.execute("DROP VIEW control.jobs_stuck")
    op.execute("DROP TABLE control.jobs")
```

- [ ] **Step 4: Tạo `src/portal/core/jobs.py`**

```python
"""Hàng đợi job + sổ đăng ký handler.

CƠ CHẾ ĐỘC LẬP MODULE: mỗi module ship modules/<m>/jobs.py gọi register(),
worker tự gom. Thêm một loại job KHÔNG sửa file nào của M1.

    # portal/modules/m4_realestate/jobs.py
    from portal.core.jobs import JobResult, register

    async def handle_import(conn, payload):
        ...
        return JobResult(count=n, message=f"nhập {n} hàng")

    register("import", handle_import)

Handler nhận connection đã ở TRONG tenant_conn() của job, nên nó bị RLS như mọi
thứ khác — handler không thấy tenant khác dù có quên WHERE.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg

from portal.core.db.session import tenant_conn

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobResult:
    """Kết quả một job. count/message ghi vào hàng jobs để UI hiện."""

    count: int = 0
    message: str = ""


JobHandler = Callable[[asyncpg.Connection, dict], Awaitable[JobResult]]

_HANDLERS: dict[str, JobHandler] = {}


def register(kind: str, handler: JobHandler) -> None:
    if not kind:
        raise ValueError("kind rỗng")
    _HANDLERS[kind] = handler


def get_handler(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


async def enqueue(
    conn: asyncpg.Connection, *, tenant_id: str, kind: str, actor: str, payload: dict
) -> int:
    """Xếp một job. Gọi TRONG tenant_conn() của request đã xác thực.

    Chuỗi tin cậy: tenant_id của job đến từ membership đã kiểm, nên khi worker
    đọc lại nó thì vẫn truy được về một người thật, không phải input tự do.
    """
    return await conn.fetchval(
        """INSERT INTO control.jobs (tenant_id, kind, actor, payload)
           VALUES ($1, $2, $3, $4::jsonb) RETURNING id""",
        tenant_id, kind, actor, json.dumps(payload),
    )


async def run_once(pool: asyncpg.Pool) -> int | None:
    """Nhặt và chạy MỘT job. Trả id job đã chạy, hoặc None nếu hàng đợi rỗng.

    FOR UPDATE SKIP LOCKED: worker khác đang giữ job nào thì bỏ qua job đó, KHÔNG
    đợi. Nhờ vậy chạy nhiều worker song song mà không nhặt trùng và không tắc.

    Job failed KHÔNG được nhặt lại. Retry là quyết định của từng loại job, mặc
    định không có — retry vô hạn một job hỏng là cách chắc chắn nhất để lấp đầy
    log mà không ai đọc.
    """
    async with pool.acquire() as claim_conn:
        async with claim_conn.transaction():
            row = await claim_conn.fetchrow(
                """SELECT id, tenant_id, kind, payload FROM control.jobs
                    WHERE state = 'queued' ORDER BY id
                      FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            if row is None:
                return None
            await claim_conn.execute(
                "UPDATE control.jobs SET state = 'running', started_at = now() WHERE id = $1",
                row["id"],
            )

    job_id, tenant_id, kind = row["id"], row["tenant_id"], row["kind"]
    payload = json.loads(row["payload"])
    handler = get_handler(kind)

    if handler is None:
        await _finish(pool, tenant_id, job_id, "failed", 0, f"không có handler cho kind={kind!r}")
        return job_id

    try:
        async with tenant_conn(pool, tenant_id) as conn:
            result = await handler(conn, payload)
    except Exception as exc:  # noqa: BLE001 — mọi lỗi handler thành job failed, có thông điệp thật
        log.exception("job %s (%s) hỏng", job_id, kind)
        await _finish(pool, tenant_id, job_id, "failed", 0, f"{type(exc).__name__}: {exc}")
        return job_id

    await _finish(pool, tenant_id, job_id, "success", result.count, result.message)
    return job_id


async def _finish(
    pool: asyncpg.Pool, tenant_id: str, job_id: int, state: str, count: int, message: str
) -> None:
    async with tenant_conn(pool, tenant_id) as conn:
        await conn.execute(
            """UPDATE control.jobs
                  SET state = $2, finished_at = now(), count = $3, message = $4
                WHERE id = $1""",
            job_id, state, count, message[:2000],
        )
```

- [ ] **Step 5: Tạo `src/portal/worker/__main__.py`**

```python
"""Tiến trình worker. Chạy: make worker

Gom handler bằng cách import modules/<m>/jobs.py của mọi module có file đó —
nên thêm một loại job không cần sửa file này.

Job theo giờ KHÔNG dùng scheduler trong tiến trình: cron trên máy chủ gọi một
lệnh ghi một hàng vào control.jobs. Như vậy job có dấu vết, và "job không chạy"
là thứ nhìn thấy được.
"""

import asyncio
import importlib
import logging
import pkgutil

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.jobs import run_once

log = logging.getLogger(__name__)

IDLE_SLEEP_SEC = 2.0


def load_handlers() -> list[str]:
    """Import portal.modules.<m>.jobs của mọi module có file đó."""
    loaded: list[str] = []
    try:
        import portal.modules as mods
    except ModuleNotFoundError:
        return loaded  # chưa có module nào — đúng ở M1
    for info in pkgutil.iter_modules(mods.__path__):
        name = f"portal.modules.{info.name}.jobs"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue  # module không có job — bình thường
        loaded.append(name)
    return loaded


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("handler đã nạp: %s", load_handlers() or "(chưa có)")

    pool = await create_pool(get_settings().database_url)
    try:
        while True:
            if await run_once(pool) is None:
                await asyncio.sleep(IDLE_SLEEP_SEC)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Tạo `src/portal/worker/__init__.py` rỗng và `tests/modules/__init__.py` rỗng.

- [ ] **Step 6: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/modules/test_worker.py tests/isolation -v`
Expected: worker 6 PASS · 6 cổng vẫn xanh (catalog test phải bỏ qua `control.jobs` vì nó ở schema `control`, không phải `tenant_data`).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/migrations/versions/0006_jobs.py \
        apps/backend/src/portal/core/jobs.py apps/backend/src/portal/worker/ \
        apps/backend/tests/modules/
git commit -m "feat(m1): control.jobs + worker SKIP LOCKED + handler registry

kind là text tự do nên module sau thêm loại job không cần migration.
Handler chạy trong tenant_conn() nên bị RLS như mọi thứ khác."
```

---

## Task 8: `agent_heartbeats` + `derive_tenant_status()`

**Files:**
- Create: `apps/backend/migrations/versions/0007_agent_heartbeats.py`
- Create: `apps/backend/src/portal/core/tenant_status.py`
- Test: `apps/backend/tests/unit/test_tenant_status.py`, `tests/modules/test_heartbeat.py`

**Interfaces:**
- Consumes: `control.tenants` (Task 2), `control.create_agent_role()` (Task 5)
- Produces: `control.agent_heartbeats(...)` + RLS 2 policy theo role · `TenantStatus` (StrEnum) · `derive_tenant_status(lifecycle, last_seen_at, running_version, live_version, now) -> TenantStatus` · `HEARTBEAT_STALE_AFTER: timedelta`

- [ ] **Step 1: Viết unit test trước (không cần DB)**

`apps/backend/tests/unit/test_tenant_status.py`:

```python
"""derive_tenant_status là HÀM THUẦN — test đủ 6 nhánh, không cần DB, không cần M3.

Sửa lỗi C2: không thể vừa lưu status vừa suy ra nó. Cột lưu là `lifecycle`
(ý chí của người vận hành); status hiển thị là hàm của lifecycle + heartbeat +
live_version.
"""

from datetime import datetime, timedelta, timezone

from portal.core.tenant_status import HEARTBEAT_STALE_AFTER, TenantStatus, derive_tenant_status

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
TUOI = NOW - timedelta(seconds=10)
CU = NOW - HEARTBEAT_STALE_AFTER - timedelta(seconds=1)


def _goi(**kw):
    args = dict(lifecycle="active", last_seen_at=TUOI, running_version=5, live_version=5, now=NOW)
    args.update(kw)
    return derive_tenant_status(**args)


def test_suspended_thang_moi_thu_khac():
    assert _goi(lifecycle="suspended", last_seen_at=None) is TenantStatus.SUSPENDED


def test_closed_thang_moi_thu_khac():
    assert _goi(lifecycle="closed", running_version=None) is TenantStatus.CLOSED


def test_chua_co_heartbeat_nao_la_dang_cap():
    assert _goi(last_seen_at=None) is TenantStatus.PROVISIONING


def test_heartbeat_cu_la_mat_ket_noi():
    assert _goi(last_seen_at=CU) is TenantStatus.DISCONNECTED


def test_heartbeat_cu_thang_ca_lech_version():
    """Pod chết thì nói pod chết, đừng nói đang xuất bản."""
    assert _goi(last_seen_at=CU, running_version=4) is TenantStatus.DISCONNECTED


def test_version_lech_la_dang_xuat_ban():
    assert _goi(running_version=4) is TenantStatus.PUBLISHING


def test_chua_publish_lan_nao_ma_pod_song_thi_san_sang():
    """live_version=None: M3 chưa có, hoặc tenant chưa publish. Pod sống là ready."""
    assert _goi(running_version=None, live_version=None) is TenantStatus.READY


def test_da_publish_ma_agent_chua_nap_gi_la_dang_xuat_ban():
    assert _goi(running_version=None, live_version=1) is TenantStatus.PUBLISHING


def test_version_khop_va_heartbeat_tuoi_la_san_sang():
    assert _goi() is TenantStatus.READY


def test_agent_chay_version_moi_hon_van_la_san_sang():
    """Rollback: live_version về 4 nhưng agent còn 5 tới lượt poll sau. Không phải lỗi."""
    assert _goi(running_version=5, live_version=4) is TenantStatus.READY


def test_nguong_cu_la_90_giay():
    """4.5 lần chu kỳ poll 20s của agent — chịu được vài lần miss mà không báo động giả."""
    assert HEARTBEAT_STALE_AFTER == timedelta(seconds=90)


def test_tu_lanh_pod_len_lai_thi_ve_ready():
    assert _goi(last_seen_at=CU) is TenantStatus.DISCONNECTED
    assert _goi(last_seen_at=TUOI) is TenantStatus.READY
```

- [ ] **Step 2: Chạy test — xác nhận FAIL**

Run: `cd apps/backend && uv run pytest tests/unit/test_tenant_status.py -v`
Expected: FAIL — `portal.core.tenant_status` chưa tồn tại.

- [ ] **Step 3: Tạo `src/portal/core/tenant_status.py`**

```python
"""Trạng thái hiển thị của một workspace — HÀM THUẦN, không đọc DB.

Sửa lỗi C2 của spec: cột lưu là `lifecycle` (ý chí của người vận hành), còn
trạng thái người dùng thấy là hàm của lifecycle + heartbeat + live_version.
Không thể vừa lưu vừa suy ra — hai nguồn sự thật cho một câu hỏi.

TỰ LÀNH: pod chết -> heartbeat cũ -> disconnected; pod lên lại -> tự về ready.
Không có trạng thái nào phải sửa tay.

live_version là cột M3 thêm vào control.tenants. Hàm nhận nó là THAM SỐ, nên
M1 test được đầy đủ mà không cần M3, và M2a gọi được ngay với live_version=None.
"""

from datetime import datetime, timedelta
from enum import StrEnum

# 4.5 lần chu kỳ poll 20s của agent — chịu được vài lần miss mà không báo động giả.
HEARTBEAT_STALE_AFTER = timedelta(seconds=90)


class TenantStatus(StrEnum):
    SUSPENDED = "suspended"
    CLOSED = "closed"
    PROVISIONING = "provisioning"
    DISCONNECTED = "disconnected"
    PUBLISHING = "publishing"
    READY = "ready"


def derive_tenant_status(
    lifecycle: str,
    last_seen_at: datetime | None,
    running_version: int | None,
    live_version: int | None,
    now: datetime,
) -> TenantStatus:
    # Ý chí của người vận hành thắng mọi thứ khác: workspace bị đình chỉ thì
    # nói đình chỉ, kể cả khi pod vẫn đang chạy.
    if lifecycle == "suspended":
        return TenantStatus.SUSPENDED
    if lifecycle == "closed":
        return TenantStatus.CLOSED

    # Chưa có nhịp tim nào -> pod chưa từng lên. Workspace mới tạo là đây, và
    # đó KHÔNG phải lỗi.
    if last_seen_at is None:
        return TenantStatus.PROVISIONING

    # Nhịp tim cũ thắng cả lệch version: pod chết thì nói pod chết, đừng nói
    # "đang xuất bản" cho một tiến trình không còn tồn tại.
    if now - last_seen_at > HEARTBEAT_STALE_AFTER:
        return TenantStatus.DISCONNECTED

    # Chưa publish lần nào (M3 chưa có, hoặc tenant chưa bấm) -> pod sống là đủ.
    if live_version is None:
        return TenantStatus.READY

    # Agent chạy version CŨ hơn -> đang áp dụng. Chạy version MỚI hơn cũng là
    # ready: đó là rollback, agent sẽ hạ version ở lượt poll sau (<= 20s).
    if running_version is None or running_version < live_version:
        return TenantStatus.PUBLISHING

    return TenantStatus.READY
```

- [ ] **Step 4: Chạy unit test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/unit/test_tenant_status.py -v`
Expected: 12 PASS.

- [ ] **Step 5: Viết test tích hợp `tests/modules/test_heartbeat.py`**

```python
"""agent_heartbeats — đường agent GHI. M1 sở hữu cả hai chiều của seam agent:
agent_api view là chiều ĐỌC, bảng này là chiều GHI.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def hb_tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        for t in ("hb1", "hb2"):
            await conn.execute("INSERT INTO control.tenants (id, name) VALUES ($1, $1)", t)
            await conn.execute("SELECT control.create_agent_role($1, 'agentdev')", t)
    yield
    async with pool.acquire() as conn:
        for t in ("hb1", "hb2"):
            await conn.execute(f"DROP OWNED BY agent_{t}")
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")
        async with conn.transaction():
            await conn.execute("DELETE FROM control.tenants WHERE id IN ('hb1', 'hb2')")


async def _agent_conn(pg_dsn, tenant):
    from tests.conftest import dsn_as

    return await asyncpg.connect(dsn_as(pg_dsn, f"agent_{tenant}", "agentdev"))


async def test_agent_upsert_duoc_heartbeat_cua_minh(hb_tenant, pg_dsn):
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        await conn.execute(
            """INSERT INTO control.agent_heartbeats
                   (tenant_id, deployment_id, running_version, bundle_sha, agent_version)
               VALUES ('hb1', 1, 3, 'sha256:abc', '1.4.2')
               ON CONFLICT (tenant_id, deployment_id) DO UPDATE
                   SET running_version = excluded.running_version,
                       last_seen_at    = now()"""
        )
        got = await conn.fetchval(
            "SELECT running_version FROM control.agent_heartbeats WHERE tenant_id = 'hb1'"
        )
        assert got == 3
    finally:
        await conn.close()


async def test_agent_khong_ghi_duoc_heartbeat_cua_tenant_khac(hb_tenant, pg_dsn):
    """Policy hb_agent_own_tenant (TO agent_all) chặn WITH CHECK sang tenant khác."""
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                """INSERT INTO control.agent_heartbeats (tenant_id, deployment_id)
                   VALUES ('hb2', 1)"""
            )
    finally:
        await conn.close()


async def test_agent_khong_doc_duoc_heartbeat_cua_tenant_khac(hb_tenant, pg_dsn):
    """USING của policy chặn chiều đọc — agent không biết workspace khác tồn tại."""
    admin = await _agent_conn(pg_dsn, "hb2")
    try:
        await admin.execute(
            "INSERT INTO control.agent_heartbeats (tenant_id, deployment_id) VALUES ('hb2', 1)"
        )
    finally:
        await admin.close()

    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        rows = await conn.fetch("SELECT tenant_id FROM control.agent_heartbeats")
        assert [r["tenant_id"] for r in rows] == []
    finally:
        await conn.close()


async def test_portal_api_doc_duoc_heartbeat_moi_workspace(hb_tenant, pg_dsn):
    """Policy hb_portal_all: admin nền tảng xem tình trạng vận hành là quyền
    control plane, KHÔNG phải quyền đọc dữ liệu tenant."""
    from portal.core.db.pool import create_pool
    from tests.conftest import API_PASSWORD, dsn_as

    for t in ("hb1", "hb2"):
        c = await _agent_conn(pg_dsn, t)
        try:
            await c.execute(
                "INSERT INTO control.agent_heartbeats (tenant_id, deployment_id) VALUES ($1, 1)", t
            )
        finally:
            await c.close()

    p = await create_pool(dsn_as(pg_dsn, "portal_api", API_PASSWORD), min_size=1, max_size=2)
    try:
        async with p.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tenant_id FROM control.agent_heartbeats "
                "WHERE tenant_id IN ('hb1', 'hb2') ORDER BY tenant_id"
            )
        assert [r["tenant_id"] for r in rows] == ["hb1", "hb2"]
    finally:
        await p.close()


async def test_agent_khong_doc_duoc_bang_control_khac(hb_tenant, pg_dsn):
    conn = await _agent_conn(pg_dsn, "hb1")
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT id FROM control.tenants")
    finally:
        await conn.close()
```

- [ ] **Step 6: Tạo `migrations/versions/0007_agent_heartbeats.py`**

```python
"""control.agent_heartbeats — chiều GHI của seam agent

VÌ SAO Ở M1 CHỨ KHÔNG Ở M3: M2a cần nó cho badge trạng thái workspace ở app
shell, M9 cần nó cho bước 3 wizard. Để nó ở M3 là buộc hai module đợi.
Nó cũng nhất quán về khái niệm — M1 sở hữu TOÀN BỘ seam agent: agent_api view
là đường agent ĐỌC, bảng này là đường agent GHI.

VÌ SAO BẢNG HẸP RIÊNG, KHÔNG NHÉT VÀO tenants: agent ghi bảng này mỗi 20 giây.
Nhét vào tenants là cho agent quyền UPDATE trên neo danh tính của cả hệ.

VÌ SAO deployment_id KHÔNG CÓ FK Ở ĐÂY: bảng control.deployments thuộc M3.
Giữ cột từ đầu để không phải đổi PRIMARY KEY về sau; M3 thêm FK trong migration
0200-0299 của nó.

VÌ SAO RLS CÓ POLICY THEO ROLE, KHÔNG PHẢI MỘT `CHECK`:
Bảng này là ngoại lệ duy nhất của "schema control không có RLS" — vì nó là bảng
control plane DUY NHẤT mà agent được GHI, nên phải có gì đó chặn agent_hb1 ghi
hàng của hb2.

Cách sai mà dễ nghĩ ra đầu tiên: CHECK (tenant_id = portal.current_tenant()).
Nó chạy, nhưng nó là một CHECK phụ thuộc BIẾN PHIÊN — và
`pg_restore` một bản sao lưu sẽ nạp lại từng hàng KHÔNG có app.tenant_id nào
được đặt, nên CHECK ra false và **mọi hàng bị từ chối**. Kho tệp và Postgres
đều mang lời hứa sao lưu (retention 6 tháng nằm trong hợp đồng), nên một cơ chế
làm restore vỡ là lỗi thật, không phải chuyện lý thuyết.

Cách đúng: RLS với HAI policy phân theo role.
  - agent_all  -> chỉ hàng của tenant mình, cả đọc lẫn ghi
  - portal_api -> tất cả. Portal PHẢI đọc được heartbeat của mọi workspace:
                  admin nền tảng xem tình trạng vận hành là quyền control plane
                  (không phải quyền đọc dữ liệu tenant).
RLS chỉ áp lúc truy vấn, không áp lúc COPY của pg_restore -> restore sạch.

KHÔNG dùng FORCE ở đây: `control` là dữ liệu control plane, và owner
(portal_migrator) cần khôi phục/sửa được bằng tay. Catalog test (cổng 6) chỉ
quét schema tenant_data nên không đòi FORCE ở bảng này.

Revision ID: 0007_heartbeats
Revises: 0006_jobs
"""

from alembic import op

revision = "0007_heartbeats"
down_revision = "0006_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.agent_heartbeats (
            tenant_id       text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            deployment_id   bigint NOT NULL,
            running_version integer,
            bundle_sha      text NOT NULL DEFAULT '',
            agent_version   text NOT NULL DEFAULT '',
            last_error      text NOT NULL DEFAULT '',
            last_seen_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, deployment_id)
        )
        """
    )
    op.execute("ALTER TABLE control.agent_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY hb_agent_own_tenant ON control.agent_heartbeats
            TO agent_all
            USING (tenant_id = portal.current_tenant())
            WITH CHECK (tenant_id = portal.current_tenant())
        """
    )
    op.execute(
        """
        CREATE POLICY hb_portal_all ON control.agent_heartbeats
            TO portal_api
            USING (true) WITH CHECK (true)
        """
    )

    # Agent cần USAGE trên control để với tới bảng này — và ĐÚNG bảng này.
    # Cấp cho NHÓM nên role tạo về sau cũng có ngay, và create_agent_role()
    # không phải sửa. Cổng 5 canh rằng không ai nới thêm bảng control nào khác.
    op.execute("GRANT USAGE ON SCHEMA control TO agent_all")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.agent_heartbeats TO agent_all")


def downgrade() -> None:
    op.execute("DROP TABLE control.agent_heartbeats")
    op.execute("REVOKE USAGE ON SCHEMA control FROM agent_all")
```

- [ ] **Step 7: Chạy toàn bộ test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest -v`
Expected: tất cả PASS. Chú ý: `create_agent_role()` **không cần sửa** ở migration này — mọi quyền của agent đi qua role nhóm `agent_all`, nên `GRANT ... TO agent_all` ở đây tự động áp cho cả role đã tạo lẫn role tạo về sau. Đó chính là lý do chọn role nhóm ở Task 3.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/migrations/versions/0007_agent_heartbeats.py \
        apps/backend/src/portal/core/tenant_status.py \
        apps/backend/tests/unit/test_tenant_status.py \
        apps/backend/tests/modules/test_heartbeat.py
git commit -m "feat(m1): agent_heartbeats + derive_tenant_status() hàm thuần

derive_tenant_status nhận live_version là tham số nên M1 test đủ 6 nhánh
không cần DB và không cần M3. CHECK tenant_id = current_tenant() chặn agent
ghi heartbeat của tenant khác (schema control không có RLS)."
```

---

## Task 9: Test ranh giới module + CI + runbook

**Files:**
- Create: `apps/backend/tests/test_module_boundaries.py`
- Create: `.gitlab-ci.yml`
- Create: `deploy/README.md`
- Modify: `README.md` (đổi "Chưa có code" → hướng dẫn chạy)

**Interfaces:**
- Consumes: cây `portal/modules/` (chưa có module nào ở M1 — test vẫn phải chạy được và xanh)
- Produces: — (chỉ test + tài liệu vận hành)

- [ ] **Step 1: Viết test ranh giới module**

`apps/backend/tests/test_module_boundaries.py`:

```python
"""Cấm import chéo ruột module — cưỡng chế bằng AST, không phải bằng quy ước.

LUẬT: portal.modules.<a> chỉ được import
  - portal.core.*
  - portal.modules.<b>.contracts   (mặt tiền — DTO + Protocol, không logic)
Import portal.modules.<b>.service / .repo / .router là LỖI.

Vì sao cưỡng chế: yêu cầu "xây module này không ảnh hưởng module khác" chỉ thật
khi có thứ chặn. Một import chéo lọt qua review là hai module dính nhau âm thầm,
và người nhận module sau sẽ không biết mình vừa phá cái gì.

Ở M1 chưa có module nào — test phải xanh và tự chạy lại được khi module xuất hiện.
"""

import ast
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "src" / "portal" / "modules"
CHO_PHEP_DUOI = "contracts"


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def test_khong_module_nao_import_ruot_module_khac():
    if not MODULES_DIR.exists():
        return  # chưa có module nào — đúng ở M1

    vi_pham: list[str] = []
    for py in sorted(MODULES_DIR.rglob("*.py")):
        rel = py.relative_to(MODULES_DIR)
        chu_so_huu = rel.parts[0]
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for name in _imported_names(tree):
            if not name.startswith("portal.modules."):
                continue
            phan = name.split(".")
            if len(phan) < 3:
                continue
            bi_import = phan[2]
            if bi_import == chu_so_huu:
                continue  # trong cùng module — bình thường
            if len(phan) >= 4 and phan[3] == CHO_PHEP_DUOI:
                continue  # qua mặt tiền — hợp lệ
            vi_pham.append(f"{rel}: import {name}")

    assert not vi_pham, (
        "Import chéo ruột module. Chỉ được import portal.modules.<khác>.contracts:\n"
        + "\n".join(vi_pham)
    )


def test_module_nao_cung_co_file_contracts():
    """contracts.py là file duy nhất module khác được đọc. Không có nó thì
    module này không giao tiếp được, và người khác sẽ đi đường tắt."""
    if not MODULES_DIR.exists():
        return
    thieu = [
        d.name
        for d in sorted(MODULES_DIR.iterdir())
        if d.is_dir() and not d.name.startswith("_") and not (d / "contracts.py").exists()
    ]
    assert thieu == [], f"module thiếu contracts.py: {thieu}"
```

- [ ] **Step 2: Chạy test — xác nhận PASS**

Run: `cd apps/backend && uv run pytest tests/test_module_boundaries.py -v`
Expected: 2 PASS (cả hai return sớm vì `modules/` chưa tồn tại).

- [ ] **Step 3: Tạo `.gitlab-ci.yml`**

```yaml
# Job `isolation` KHÔNG path-filter: module nào cũng merge độc lập được, nhưng
# không ai merge được thứ làm vỡ cách ly.
stages: [lint, test]

variables:
  DOCKER_HOST: tcp://docker:2375
  DOCKER_TLS_CERTDIR: ""
  TESTCONTAINERS_RYUK_DISABLED: "true"

.uv:
  image: ghcr.io/astral-sh/uv:python3.13-bookworm-slim
  before_script:
    - cd apps/backend && uv sync --frozen

lint:
  extends: .uv
  stage: lint
  script:
    - uv run ruff check .
    - uv run ruff format --check .

unit:
  extends: .uv
  stage: test
  script:
    - uv run pytest tests/unit -v      # không cần Docker

isolation:
  extends: .uv
  stage: test
  services: [docker:dind]
  script:
    - uv run pytest tests/isolation tests/test_module_boundaries.py -v
  # KHÔNG có `rules: changes:` — cổng cách ly chạy cho MỌI pull request.

integration:
  extends: .uv
  stage: test
  services: [docker:dind]
  script:
    - uv run pytest tests/integration tests/modules -v
```

- [ ] **Step 4: Tạo `deploy/README.md`**

```markdown
# Vận hành — ràng buộc không kiểm được bằng test

Ba việc dưới đây **không test được trong testcontainers** (ở đó `POSTGRES_USER`
chính là bootstrap superuser). Chúng là ràng buộc của runbook deploy, và nếu sai
thì cách ly vỡ **âm thầm** — app chạy bình thường, chỉ dữ liệu là rò.

## 1. `portal_migrator` phải là non-superuser

```sql
CREATE ROLE portal_migrator LOGIN PASSWORD '<bí mật>' CREATEROLE;
-- KHÔNG: SUPERUSER, KHÔNG: BYPASSRLS
ALTER SCHEMA portal      OWNER TO portal_migrator;
ALTER SCHEMA control     OWNER TO portal_migrator;
ALTER SCHEMA tenant_data OWNER TO portal_migrator;
ALTER SCHEMA agent_api   OWNER TO portal_migrator;
```

**Vì sao:** superuser bỏ qua RLS **bất kể `FORCE`**. Nếu `portal_migrator` là
superuser thì `FORCE ROW LEVEL SECURITY` không bảo vệ gì, và cổng test 3 ở môi
trường thật là vô nghĩa.

`CREATEROLE` là cần: `control.create_agent_role()` chạy `CREATE ROLE`.

## 2. `portal_migrator` chỉ chạy migration, không phục vụ

Tiến trình API và worker nối bằng **`portal_api`**. Không tiến trình nào nối
bằng `portal_migrator`.

**Vì sao:** `portal_migrator` là owner của bảng. RLS + `FORCE` áp cho owner
nhưng không có lý do gì để chạy runtime bằng role có toàn quyền DDL.

## 3. Mật khẩu

Migration `0003` tạo `portal_api` với mật khẩu `apidev` — **chỉ để test nối
được**. Deploy phải đặt lại:

```sql
ALTER ROLE portal_api PASSWORD '<bí mật>';
```

Mật khẩu của `agent_<tenant>` do `control.create_agent_role()` nhận làm tham số.
Chỗ cấp workspace phải sinh mật khẩu ngẫu nhiên và **đẩy vào nơi pod đọc được**
(secret của CI/K8s). Việc này trước đây không ai ghi ra.

## 4. Migration có backfill dữ liệu

`FORCE ROW LEVEL SECURITY` áp cho owner, nên migration **backfill** (không chỉ
DDL) sẽ bị lọc và thấy 0 hàng. Hai cách đúng:

```python
# Cách 1: đặt phạm vi cho từng tenant
op.execute("SET LOCAL app.tenant_id = 'anphu'")
op.execute("UPDATE tenant_data.units SET ... WHERE ...")

# Cách 2: tắt FORCE trong CÙNG migration, bật lại ngay
op.execute("ALTER TABLE tenant_data.units NO FORCE ROW LEVEL SECURITY")
op.execute("UPDATE tenant_data.units SET ...")
op.execute("ALTER TABLE tenant_data.units FORCE ROW LEVEL SECURITY")
```

Cách 2 phải bật lại **trong cùng migration** — để lại `NO FORCE` là cổng test 6
đỏ ở PR tiếp theo, nhưng trong khoảng đó cách ly đã hở.

## 5. Cấp một workspace — bốn việc, cả-bốn-hoặc-không

M1 chỉ ship việc thứ hai. Ghép lại là M3/M9.

| # | Việc | Ở module |
|---|---|---|
| 1 | `INSERT` hàng `control.tenants` | M1 (schema) · M9 (luồng) |
| 2 | `control.create_agent_role(slug, <mật khẩu ngẫu nhiên>)` + đẩy mật khẩu vào secret | **M1** |

> Mọi quyền của agent đến từ role nhóm `agent_all`. Thêm bảng agent ghi được thì
> gọi `control.grant_agent_write('tenant_data.<bảng>')` **một lần** trong migration
> của module đó — không phải quét danh sách role đang tồn tại, và role tạo về sau
> cũng có ngay.
| 3 | Tạo collection Qdrant `kb_<slug>` | M6 |
| 4 | Tạo tiền tố `tenants/<slug>/` trên MinIO + access key giới hạn đúng tiền tố đó | M3 |
```

- [ ] **Step 5: Cập nhật `README.md`**

Đổi dòng `**Trạng thái:** đang viết spec. Chưa có code.` thành:

```markdown
**Trạng thái:** M1 (nền cách ly) đang làm. Các module khác chưa bắt đầu.

## Chạy local

```bash
make dev                      # postgres 5433 · redis 6380 · minio 9000
cd apps/backend && uv sync
make migrate
make test                     # tất cả
make test-unit                # không cần Docker
make test-isolation           # 6 cổng cách ly
```

Ràng buộc production (không test được bằng testcontainers): [deploy/README.md](deploy/README.md).
```

- [ ] **Step 6: Chạy toàn bộ + lint**

```bash
make lint
make test
```

Expected: lint xanh, tất cả test PASS.

- [ ] **Step 7: Kiểm tay rằng cổng 6 thật sự canh bảng mới**

Thêm tạm vào cuối `upgrade()` của `migrations/versions/0007_agent_heartbeats.py`:

```python
    op.execute(
        "CREATE TABLE tenant_data.quen_bat_cach_ly ("
        "  id bigserial PRIMARY KEY,"
        "  tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE)"
    )
```

Run: `cd apps/backend && uv run pytest tests/isolation/test_isolation_catalog.py -v`
Expected: **`test_moi_bang_tenant_data_da_bat_cach_ly` ĐỎ**, thông điệp chỉ đúng bảng `quen_bat_cach_ly` và chỉ ra câu lệnh phải thêm.

Xoá đoạn tạm đó, chạy lại — xanh. **Ghi kết quả vào commit message.**

- [ ] **Step 8: Commit**

```bash
git add apps/backend/tests/test_module_boundaries.py .gitlab-ci.yml deploy/README.md README.md
git commit -m "feat(m1): test ranh giới module + CI job isolation + runbook deploy

Đã kiểm tay: thêm một bảng tenant_data không gọi enforce_tenant_isolation()
làm catalog test ĐỎ với thông điệp chỉ đúng bảng thiếu.

Job isolation trong CI KHÔNG path-filter: module nào cũng merge độc lập
được, nhưng không ai merge được thứ làm vỡ cách ly."
```

---

## Bảng đối chiếu — spec §7 (6 cổng) ↔ task

| Cổng | File | Task |
|---|---|---|
| 1 · Cross-tenant read = 0 hàng | `tests/isolation/test_rls_isolation.py` | 4 (portal) · 5 (agent) |
| 2 · Gate cột | `tests/isolation/test_view_column_gate.py` | 5 |
| 3 · Chủ bảng không bypass RLS | `tests/isolation/test_force_rls.py` | 4 |
| 4 · Rò qua connection pool | `tests/isolation/test_pool_leak.py` | 6 |
| 5 · Quyền role | `tests/isolation/test_role_privileges.py` | 5 |
| 6 · Catalog test | `tests/isolation/test_isolation_catalog.py` | 4 |
| 7 · Cách ly tiền tố kho tệp | — | **M3** |
| 8 · Cross-tenant RAG | — | **M6** |

## Định nghĩa "xong" của M1

- [ ] `make test` xanh; `make lint` xanh
- [ ] 6 cổng §7 đều **có** và đều xanh
- [ ] Xoá `FORCE` khỏi helper ⇒ cổng 3 đỏ. **Đã kiểm tay** (Task 4 Step 9), ghi trong commit
- [ ] Thêm bảng `tenant_data` không gọi helper ⇒ cổng 6 đỏ. **Đã kiểm tay** (Task 9 Step 7), ghi trong commit
- [ ] `derive_tenant_status()` phủ **cả 6 nhánh** bằng unit test, không cần DB
- [ ] Hai worker song song **không nhặt trùng** một job; handler chạy trong `tenant_conn`
- [ ] Một `kind` mới đăng ký được và chạy được **mà không sửa file nào của M1**
- [ ] `docker compose up` + `make migrate` chạy được từ repo sạch
- [ ] `deploy/README.md` ghi 5 ràng buộc production
- [ ] Mọi file migration có header tiếng Việt giải thích **vì sao**
- [ ] Contract spec §8 khớp code thật; `docs/contracts/isolation.md` khớp §5–§7 của spec

## Ba chỗ spec phải sửa sau khi làm plan

Ghi ra để người thực thi cập nhật spec cùng lúc, không để spec và code lệch nhau.

| # | Spec M1 nói | Đúng là | Vì sao |
|---|---|---|---|
| 1 | §4 bảng role: `agent_*` *"không thấy schema `control`"* | Agent **có** `USAGE ON SCHEMA control` + `SELECT/INSERT/UPDATE` trên **đúng `agent_heartbeats`**, zero quyền trên bảng `control` khác | `agent_heartbeats` nằm ở schema `control`. Cổng 5 canh sự hẹp đó bằng danh sách cho phép, thay vì cấm cả schema |
| 2 | §8.1 `create_agent_role` grant *"`INSERT`/`UPDATE` trên `appointments` · `contacts`"* | Mọi quyền của agent cấp cho **role nhóm `agent_all`**; `create_agent_role()` chỉ `CREATE ROLE` + `GRANT agent_all`. M7 gọi `control.grant_agent_write('tenant_data.appointments')` trong migration của nó | Hai bảng đó thuộc M7, chưa tồn tại ở M1. Role nhóm là cách cấp quyền cho cả role đã tạo lẫn role tạo về sau **mà không phải sửa hàm** — đây là chỗ cắm thứ tư, cùng khuôn với `enforce_tenant_isolation` · `require(action)` · handler registry |
| 3 | §6 view `agent_api.units` có `u.tenant_id` trong SELECT | **Không** có `tenant_id` | Agent chỉ phục vụ một tenant; biết id của mình là dư, và cổng 2 canh việc không lộ nó |
| 4 | §5.3 *"schema `control` KHÔNG RLS"* | Đúng, **trừ một ngoại lệ: `control.agent_heartbeats`** có RLS với hai policy theo role (`agent_all` chỉ tenant mình · `portal_api` tất cả) | Nó là bảng control plane **duy nhất** agent được ghi. Cách rẻ hơn — `CHECK (tenant_id = portal.current_tenant())` — làm **`pg_restore` vỡ**: restore nạp lại từng hàng mà không có `app.tenant_id` nào được đặt nên CHECK ra false và mọi hàng bị từ chối. RLS chỉ áp lúc truy vấn, không áp lúc `COPY` |
| 5 | §8.3 *"`.env.example` có mẫu cả hai DSN"* | Chỉ có `DATABASE_URL` | `alembic_url` là **property suy ra**, không phải biến môi trường — hai biến cho một giá trị là hai chỗ để lệch nhau |
