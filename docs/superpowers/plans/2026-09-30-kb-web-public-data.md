# Gói `kb/web` (dữ liệu BĐS công khai) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawl tin BĐS công khai mỗi đêm vào `public_data.web_pages`, rồi viết hồ sơ dự án, thẻ dự án lân cận và bản tin vào collection Qdrant dùng chung `public_web`.

**Architecture:** Gói con `src/portal/modules/kb/web/` trong repo portal backend, chạy ở một container riêng (`crawl`). Phần dùng chung cho mọi tenant (crawl theo ngày, bản tin) chạy thẳng trong CLI, vì `control.jobs` bắt buộc phải có tenant. Phần theo từng dự án (lượt đêm, lượt tuần, dựng lại, dựng ban đầu) là job của tenant loại `kbweb_project`, do một worker riêng trong container `crawl` xử lý. Worker chính không nhặt các job này, vì `kb/jobs.py` không import `kb/web/jobs.py`.

**Tech Stack:** Python 3.13, asyncpg, httpx, trafilatura, qdrant-client, DashScope qwen3.7-flash (OpenAI-compat), Gemini 2.5 Flash grounding, pytest + testcontainers.

Spec: `docs/superpowers/specs/2026-09-29-public-data-crawl-design.md`.

**Ngoài phạm vi plan này (plan riêng, viết sau):**
- Plan B: tích hợp `kb_search` bên `odyssey-agent` để đọc `public_web`.
- Plan C: tầng tải bằng trình duyệt (Crawl4AI) và unlocker. Trong plan này, domain có `fetch_mode: browser` và trang bị challenge chỉ được lưu dấu `needs_browser`.

## Global Constraints

- Tên hàm, biến, cột và khoá payload bằng tiếng Anh. Tiếng Việt chỉ dùng ở comment, docstring, tên test và nội dung prompt. Comment viết ít.
- **Không tự chạy `git commit`.** Mỗi bước "Checkpoint" là dừng lại và báo user để user tự commit.
- Mọi I/O đều async. Việc tốn CPU (`trafilatura.extract`) chạy qua `asyncio.to_thread`.
- SQL trên `public_data` viết thẳng tên `public_data.web_pages`, không ghép tên bảng qua biến. SQL chạm `tenant_data.*` phải có chữ `portal.current_tenant()` ngay trong literal (cổng `tests/isolation/test_loc_tenant_o_tang_app.py::test_moi_cau_sql_cham_tenant_data_deu_mang_vi_tu_tenant`).
- `src/portal/modules/kb/jobs.py` **không được** import `portal.modules.kb.web.jobs`. Gói web cũng không được import `portal.modules.kb.jobs`.
- Gói nào `src/portal` import thẳng thì phải có trong `[project].dependencies` (`tests/unit/test_khai_bao_phu_thuoc.py`).
- Migration mới: `revision = "0969_public_data_web_pages"`, `down_revision = "0968_escalations_lead"`.
- LLM là `qwen3.7-flash` qua `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, tắt thinking, key `KB_WEB_LLM_API_KEY`. Grounding là `gemini-2.5-flash`, key `KB_WEB_GEMINI_API_KEY` (thuộc Google project riêng), trần mặc định `KB_WEB_GROUNDING_DAILY_CAP=1200` lượt/ngày.
- Payload mỗi point trong `public_web` có **đúng 6 khoá**: `text`, `location`, `projects`, `sources`, `published_at`, `updated_at`.
- **Lệch so với spec (ghi lại trong spec ở Task 15):** lượt đêm theo dự án chỉ lọc kho 48 giờ, không gọi Gemini. Gemini chỉ chạy ở lượt tuần, lượt dựng ban đầu và lượt dựng lại. Lý do: mức miễn phí của Gemini 2.5 Flash grounding là 1.500 lượt/ngày; nếu mỗi đêm mỗi dự án gọi tới 60 lượt thì 100 dự án đã vượt xa mức đó.
- Chạy test: `uv run pytest <path> -v`. Lint: `uv run ruff check . && uv run ruff format --check .`.

## Bản đồ file

| File | Trách nhiệm |
|---|---|
| `migrations/versions/0969_public_data_web_pages.py` | Schema `public_data`, bảng `web_pages`, index, GRANT |
| `src/portal/modules/kb/web/contracts.py` | Hằng số và dataclass dùng chung trong gói |
| `src/portal/modules/kb/web/config.py` + `data/*.yaml` | Whitelist, chủ đề, vùng, đơn vị hành chính |
| `src/portal/modules/kb/web/normalize.py` | Chuẩn hoá URL, băm nội dung, làm sạch nhãn |
| `src/portal/modules/kb/web/locate.py` | Mở rộng địa danh nhiều cấp, dò địa danh trong địa chỉ |
| `src/portal/modules/kb/web/repo.py` | SQL trên `public_data.web_pages` |
| `src/portal/modules/kb/web/discover.py` | Đọc sitemap, RSS, trang mục; chọn bài theo ngày |
| `src/portal/modules/kb/web/fetch.py` | Tải trang tầng 1 và bóc nội dung |
| `src/portal/modules/kb/web/llm.py` | Client qwen: gắn nhãn, gọi prompt viết |
| `src/portal/modules/kb/web/compose.py` | Đánh số nguồn, kiểm [n], dựng payload, sinh id |
| `src/portal/modules/kb/web/index.py` | Ghi, đọc, xoá point trong `public_web` |
| `src/portal/modules/kb/web/grounding.py` | Gemini grounding, lấy URL gốc, trần theo ngày |
| `src/portal/modules/kb/web/signal.py` | Đọc dự án và tín hiệu "có người hỏi" từ log hội thoại |
| `src/portal/modules/kb/web/pipeline.py` | Các bước: crawl ngày, bản tin, làm mới dự án |
| `src/portal/modules/kb/web/enqueue.py` + `fanout.py` + `jobs.py` | Xếp job, fan-out theo tenant, handler |
| `src/portal/cli/kb_web_night.py`, `src/portal/cli/kb_web_worker.py` | Lệnh cron và worker riêng |
| `deploy/*`, `docker-compose*.yml` | Vai `crawl`, `crawl-worker`, timer systemd |
| `docs/contracts/public-web.md` | Hợp đồng payload cho bên đọc |

---

### Task 1: Migration `public_data.web_pages`

**Files:**
- Create: `migrations/versions/0969_public_data_web_pages.py`
- Create: `tests/modules/kb/web/__init__.py` (rỗng)
- Test: `tests/modules/kb/web/test_migration.py`

**Interfaces:**
- Produces: bảng `public_data.web_pages(url, source_url, domain, title, published_at, fetched_at, last_checked_at, content_text, content_hash, found_via, status, projects text[], location text[])`. `found_via ∈ {sitemap, rss, grounding}`, `status ∈ {ok, irrelevant, fetch_failed, needs_browser}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/kb/web/test_migration.py
import asyncpg
import pytest

from portal.core.db.pool import create_pool

pytestmark = pytest.mark.integration


async def test_portal_api_ghi_doc_xoa_duoc(api_dsn):
    p = await create_pool(api_dsn, min_size=1, max_size=1)
    try:
        async with p.acquire() as c:
            await c.execute(
                """INSERT INTO public_data.web_pages (url, domain, found_via, status, projects, location)
                   VALUES ('https://test.kbweb/mig', 'test.kbweb', 'sitemap', 'ok', '{NPTTL}', '{Hà Nội}')"""
            )
            row = await c.fetchrow("SELECT projects, location FROM public_data.web_pages WHERE url = 'https://test.kbweb/mig'")
            assert row["projects"] == ["NPTTL"]
            assert row["location"] == ["Hà Nội"]
            await c.execute("DELETE FROM public_data.web_pages WHERE url = 'https://test.kbweb/mig'")
    finally:
        await p.close()


async def test_status_la_mien_dong(api_dsn):
    p = await create_pool(api_dsn, min_size=1, max_size=1)
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await p.execute(
                """INSERT INTO public_data.web_pages (url, domain, found_via, status)
                   VALUES ('https://test.kbweb/x', 'test.kbweb', 'sitemap', 'la')"""
            )
    finally:
        await p.close()


async def test_public_data_khong_co_cot_tenant_id(pool):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'public_data' AND column_name = 'tenant_id'"""
    )
    assert n == 0, "public_data là dữ liệu công khai dùng chung; dữ liệu theo tenant thuộc tenant_data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/web/test_migration.py -v`
Expected: FAIL. `asyncpg.exceptions.UndefinedTableError: relation "public_data.web_pages" does not exist`.

- [ ] **Step 3: Write the migration**

```python
# migrations/versions/0969_public_data_web_pages.py
"""public_data.web_pages — bài web công khai do gói kb/web crawl về, dùng chung mọi tenant.

Không có tenant_id nên không có RLS: đây là dữ liệu công khai. Chỉ container crawl
đọc và ghi, bằng role portal_api.

Revision ID: 0969_public_data_web_pages
Revises: 0968_escalations_lead
"""

from alembic import op

revision = "0969_public_data_web_pages"
down_revision = "0968_escalations_lead"
branch_labels = None
depends_on = None

_DDL = """
CREATE SCHEMA IF NOT EXISTS public_data;

CREATE TABLE IF NOT EXISTS public_data.web_pages (
    url             text PRIMARY KEY CHECK (url <> ''),
    source_url      text NOT NULL DEFAULT '',
    domain          text NOT NULL CHECK (domain <> ''),
    title           text NOT NULL DEFAULT '',
    published_at    timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    last_checked_at timestamptz NOT NULL DEFAULT now(),
    content_text    text,
    content_hash    text NOT NULL DEFAULT '',
    found_via       text NOT NULL CHECK (found_via IN ('sitemap', 'rss', 'grounding')),
    status          text NOT NULL CHECK (status IN ('ok', 'irrelevant', 'fetch_failed', 'needs_browser')),
    projects        text[] NOT NULL DEFAULT '{}',
    location        text[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS web_pages_projects_gin ON public_data.web_pages USING gin (projects);
CREATE INDEX IF NOT EXISTS web_pages_location_gin ON public_data.web_pages USING gin (location);
CREATE INDEX IF NOT EXISTS web_pages_published_idx ON public_data.web_pages (published_at);
CREATE INDEX IF NOT EXISTS web_pages_fetched_idx ON public_data.web_pages (fetched_at);
CREATE INDEX IF NOT EXISTS web_pages_hash_idx ON public_data.web_pages (content_hash) WHERE content_hash <> '';

GRANT USAGE ON SCHEMA public_data TO portal_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON public_data.web_pages TO portal_api;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS public_data CASCADE")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/web/test_migration.py tests/unit/test_alembic_mot_head.py -v`
Expected: PASS (4 test).

- [ ] **Step 5: Áp migration lên DB dev**

Run: `make migrate`
Expected: `Running upgrade 0968_escalations_lead -> 0969_public_data_web_pages`.

- [ ] **Step 6: Checkpoint** — dừng, báo user tự commit (`migrations/versions/0969_public_data_web_pages.py`, `tests/modules/kb/web/`).

---

### Task 2: Contracts, cấu hình YAML, biến env, prompt

**Files:**
- Create: `src/portal/modules/kb/web/__init__.py` (rỗng), `src/portal/modules/kb/web/data/__init__.py` (rỗng)
- Create: `src/portal/modules/kb/web/contracts.py`
- Create: `src/portal/modules/kb/web/config.py`
- Create: `src/portal/modules/kb/web/data/sources.yaml`, `topics.yaml`, `regions.yaml`, `admin_units.yaml`
- Modify: `src/portal/modules/kb/settings.py` (thêm trường vào `KbEnv`)
- Modify: `src/portal/modules/kb/prompts.yaml` (thêm 5 profile)
- Test: `tests/unit/test_kb_web_config.py`

**Interfaces:**
- Produces (`contracts.py`): `COLLECTION = "public_web"`, `KIND_PROJECT = "kbweb_project"`, `MODE_NIGHTLY/MODE_WEEKLY/MODE_REBUILD/MODE_INIT`, `MODES`, `MAX_DOSSIER_ITEMS = 100`, `MAX_DIGEST_ITEMS = 30`, `DIGEST_REGION = "toan_quoc"`, `PROFILE_TAG/PROFILE_DOSSIER/PROFILE_CARD/PROFILE_DIGEST/PROFILE_GROUNDING`, dataclass `Source(url, name, published_at)`, `Page(url, domain, title, published_at, fetched_at, content_text, projects, location)`, `Tags(relevant, projects, location)`, `Item(text, sources, projects, location, updated_at=None)`.
- Produces (`config.py`): `load() -> WebConfig`, cùng các dataclass `SourceSite`, `Topic`, `Region`, `Commune`, `Unit`, `WebConfig`.
- Produces (`KbEnv`): `web_llm_api_key`, `web_llm_base_url`, `web_llm_concurrency`, `web_gemini_api_key`, `web_grounding_daily_cap`, `web_fetch_per_domain`, `web_fetch_delay_sec`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_config.py
from portal.modules.kb import prompts
from portal.modules.kb.settings import KbEnv
from portal.modules.kb.web import config
from portal.modules.kb.web.contracts import (
    PROFILE_CARD,
    PROFILE_DIGEST,
    PROFILE_DOSSIER,
    PROFILE_GROUNDING,
    PROFILE_TAG,
)

MA_CHU_DE = {
    "road", "bridge", "transit", "travel_time", "education", "healthcare", "retail", "leisure",
    "employment", "zoning", "area_development", "nearby_projects", "price_trend", "project_news",
    "onsite_amenities",
}


def test_nap_duoc_va_domain_khong_trung():
    cfg = config.load()
    domains = [s.domain for s in cfg.sources]
    assert len(domains) == len(set(domains))
    assert "cafef.vn" in domains


def test_du_15_chu_de_moi_chu_de_toi_da_4_truy_van():
    cfg = config.load()
    assert {t.code for t in cfg.topics} == MA_CHU_DE
    for t in cfg.topics:
        assert 1 <= len(t.queries) <= 4
        assert t.keywords
        for q in t.queries:
            q.format(project="X", locality="Y", province="Z")


def test_laodong_tai_bang_trinh_duyet():
    cfg = config.load()
    assert cfg.source_of("laodong.vn").fetch_mode == "browser"


def test_vung_tay_ha_noi_chua_dan_phuong():
    cfg = config.load()
    tay = next(r for r in cfg.regions if r.name == "Tây Hà Nội")
    assert "Đan Phượng" in tay.districts


def test_prompt_web_dung_qwen37_va_grounding_dung_gemini():
    for name in (PROFILE_TAG, PROFILE_DOSSIER, PROFILE_CARD, PROFILE_DIGEST):
        assert prompts.get(name).model == "qwen3.7-flash"
    assert prompts.get(PROFILE_GROUNDING).model == "gemini-2.5-flash"


def test_mac_dinh_env(monkeypatch):
    for k in ("KB_WEB_LLM_API_KEY", "KB_WEB_GEMINI_API_KEY", "KB_WEB_GROUNDING_DAILY_CAP"):
        monkeypatch.delenv(k, raising=False)
    env = KbEnv(_env_file=None)
    assert env.web_grounding_daily_cap == 1200
    assert env.web_llm_base_url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_config.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web'`.

- [ ] **Step 3: Viết `contracts.py`**

```python
# src/portal/modules/kb/web/contracts.py
"""Hằng số và kiểu dùng chung của gói kb/web. Không logic."""

from dataclasses import dataclass
from datetime import datetime

COLLECTION = "public_web"
KIND_PROJECT = "kbweb_project"

MODE_NIGHTLY = "nightly"
MODE_WEEKLY = "weekly"
MODE_REBUILD = "rebuild"
MODE_INIT = "init"
MODES = (MODE_NIGHTLY, MODE_WEEKLY, MODE_REBUILD, MODE_INIT)

MAX_DOSSIER_ITEMS = 100
MAX_DIGEST_ITEMS = 30
DIGEST_REGION = "toan_quoc"

PROFILE_TAG = "web_tag"
PROFILE_DOSSIER = "web_dossier"
PROFILE_CARD = "web_card"
PROFILE_DIGEST = "web_digest"
PROFILE_GROUNDING = "web_grounding"

FOUND_SITEMAP = "sitemap"
FOUND_RSS = "rss"
FOUND_GROUNDING = "grounding"

STATUS_OK = "ok"
STATUS_IRRELEVANT = "irrelevant"
STATUS_FAILED = "fetch_failed"
STATUS_NEEDS_BROWSER = "needs_browser"


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    name: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    domain: str
    title: str
    published_at: datetime | None
    fetched_at: datetime | None
    content_text: str
    projects: tuple[str, ...]
    location: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Tags:
    relevant: bool
    projects: tuple[str, ...]
    location: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Item:
    text: str
    sources: tuple[Source, ...]
    projects: tuple[str, ...]
    location: tuple[str, ...]
    updated_at: datetime | None = None
```

- [ ] **Step 4: Viết `config.py`**

```python
# src/portal/modules/kb/web/config.py
"""Nạp cấu hình YAML của gói kb/web: whitelist, chủ đề, vùng, đơn vị hành chính."""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import yaml

FETCH_MODES = ("http", "browser", "unlocker")
SOURCE_KINDS = ("news", "living")


@dataclass(frozen=True, slots=True)
class SourceSite:
    domain: str
    name: str
    whitelisted: bool
    fetch_mode: str
    kind: str
    rss: tuple[str, ...]
    sitemap_index: str
    child_hint: str
    news_sitemaps: tuple[str, ...]
    category_pages: tuple[str, ...]
    article_pattern: str
    category_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Topic:
    code: str
    label: str
    keywords: tuple[str, ...]
    queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Region:
    name: str
    districts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Commune:
    name: str
    former: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Unit:
    province: str
    district: str
    aliases: tuple[str, ...]
    communes: tuple[Commune, ...]


@dataclass(frozen=True, slots=True)
class WebConfig:
    sources: tuple[SourceSite, ...]
    topics: tuple[Topic, ...]
    target_per_topic: int
    bds_keywords: tuple[str, ...]
    regions: tuple[Region, ...]
    units: tuple[Unit, ...]

    def source_of(self, domain: str) -> SourceSite | None:
        return next((s for s in self.sources if s.domain == domain), None)

    def names_of(self) -> dict[str, str]:
        return {s.domain: s.name for s in self.sources}


def _read(name: str) -> dict:
    text = files("portal.modules.kb.web").joinpath("data", name).read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _tup(v) -> tuple[str, ...]:
    return tuple(str(x) for x in (v or []))


def _source(d: dict) -> SourceSite:
    s = SourceSite(
        domain=str(d["domain"]),
        name=str(d["name"]),
        whitelisted=bool(d.get("whitelisted", True)),
        fetch_mode=str(d.get("fetch_mode", "http")),
        kind=str(d.get("kind", "news")),
        rss=_tup(d.get("rss")),
        sitemap_index=str(d.get("sitemap_index", "")),
        child_hint=str(d.get("child_hint", "")),
        news_sitemaps=_tup(d.get("news_sitemaps")),
        category_pages=_tup(d.get("category_pages")),
        article_pattern=str(d.get("article_pattern", "")),
        category_paths=_tup(d.get("category_paths")),
    )
    if s.fetch_mode not in FETCH_MODES:
        raise ValueError(f"{s.domain}: fetch_mode {s.fetch_mode!r} không hợp lệ")
    if s.kind not in SOURCE_KINDS:
        raise ValueError(f"{s.domain}: kind {s.kind!r} không hợp lệ")
    return s


@cache
def load() -> WebConfig:
    src = _read("sources.yaml")
    top = _read("topics.yaml")
    reg = _read("regions.yaml")
    adm = _read("admin_units.yaml")
    sources = tuple(_source(d) for d in src.get("sources", []))
    domains = [s.domain for s in sources]
    if len(domains) != len(set(domains)):
        raise ValueError("sources.yaml có domain trùng")
    topics = tuple(
        Topic(code=str(t["code"]), label=str(t["label"]), keywords=_tup(t["keywords"]), queries=_tup(t["queries"]))
        for t in top.get("topics", [])
    )
    units = tuple(
        Unit(
            province=str(u["province"]),
            district=str(u["district"]),
            aliases=_tup(u.get("aliases")),
            communes=tuple(Commune(name=str(c["name"]), former=_tup(c.get("former"))) for c in u.get("communes") or []),
        )
        for u in adm.get("units", [])
    )
    return WebConfig(
        sources=sources,
        topics=topics,
        target_per_topic=int(top.get("target_per_topic", 5)),
        bds_keywords=_tup(top.get("bds_keywords")),
        regions=tuple(Region(name=str(r["name"]), districts=_tup(r["districts"])) for r in reg.get("regions", [])),
        units=units,
    )
```

- [ ] **Step 5: Viết `data/sources.yaml`**

```yaml
# Whitelist đo ngày 29/09/2026. child_hint: chuỗi phải có trong URL sitemap con khi sitemap
# index không ghi lastmod; {y}=năm, {m}=tháng không đệm, {mm}=tháng 2 chữ số.
sources:
  - {domain: cafef.vn, name: CafeF, fetch_mode: http, kind: news,
     rss: [https://cafef.vn/bat-dong-san.rss], sitemap_index: https://cafef.vn/sitemap.xml,
     child_hint: "-{y}-{m}-", news_sitemaps: [https://cafef.vn/google-news-sitemap.xml]}
  - {domain: vnexpress.net, name: VnExpress, fetch_mode: http, kind: news,
     rss: [https://vnexpress.net/rss/bat-dong-san.rss], news_sitemaps: [https://vnexpress.net/google-news-sitemap.xml],
     category_paths: [/bat-dong-san]}
  - {domain: dantri.com.vn, name: Dân trí, fetch_mode: http, kind: news,
     rss: [https://dantri.com.vn/rss/bat-dong-san.rss], news_sitemaps: [https://dantri.com.vn/google-news-sitemap.xml],
     category_paths: [/bat-dong-san]}
  - {domain: baoxaydung.vn, name: Báo Xây dựng, fetch_mode: http, kind: news,
     rss: [https://baoxaydung.vn/rss/bat-dong-san.rss], sitemap_index: https://baoxaydung.vn/sitemap.xml,
     child_hint: "-{y}-{m}-"}
  - {domain: vneconomy.vn, name: VnEconomy, fetch_mode: http, kind: news,
     rss: [https://vneconomy.vn/dia-oc.rss], news_sitemaps: [https://vneconomy.vn/sitemap/google-news.xml]}
  - {domain: thanhnien.vn, name: Thanh Niên, fetch_mode: http, kind: news,
     rss: [https://thanhnien.vn/rss/kinh-te/dia-oc.rss], sitemap_index: https://thanhnien.vn/sitemap.xml,
     child_hint: "-{y}-{m}-"}
  - {domain: tuoitre.vn, name: Tuổi Trẻ, fetch_mode: http, kind: news,
     rss: [https://tuoitre.vn/rss/nha-dat.rss, https://tuoitre.vn/sitemaps/latest-news.rss]}
  - {domain: vietnamnet.vn, name: VietNamNet, fetch_mode: http, kind: news,
     rss: [https://vietnamnet.vn/bat-dong-san.rss], news_sitemaps: [https://vietnamnet.vn/sitemap-news.xml]}
  - {domain: cafeland.vn, name: CafeLand, fetch_mode: http, kind: news,
     category_pages: [https://cafeland.vn/tin-tuc/], article_pattern: '^https://cafeland\.vn/tin-tuc/.+-\d+\.html$'}
  - {domain: batdongsan.com.vn, name: Batdongsan, fetch_mode: http, kind: news,
     category_pages: [https://batdongsan.com.vn/tin-tuc], article_pattern: '^https://batdongsan\.com\.vn/tin-tuc/.+'}
  - {domain: reatimes.vn, name: Reatimes, fetch_mode: http, kind: news,
     news_sitemaps: [https://reatimes.vn/sitemaps/googlenews.ashx]}
  - {domain: nhipsongkinhdoanh.vn, name: Nhịp sống kinh doanh, fetch_mode: http, kind: news,
     category_pages: [https://nhipsongkinhdoanh.vn/bat-dong-san], article_pattern: '^https://nhipsongkinhdoanh\.vn/.+-post\d+\.html$'}
  - {domain: baochinhphu.vn, name: Báo Chính phủ, fetch_mode: http, kind: news,
     category_pages: [https://baochinhphu.vn/kinh-te.htm], article_pattern: '^https://baochinhphu\.vn/.+-\d+\.htm$'}
  - {domain: hanoi.gov.vn, name: Cổng thông tin Hà Nội, fetch_mode: http, kind: living}
  - {domain: quyhoach.hanoi.vn, name: Quy hoạch Hà Nội, fetch_mode: http, kind: living}
  - {domain: savills.com.vn, name: Savills, fetch_mode: http, kind: living}
  - {domain: tienphong.vn, name: Tiền Phong, fetch_mode: http, kind: news,
     news_sitemaps: [https://tienphong.vn/sitemaps/google-news.xml], category_paths: [/dia-oc]}
  - {domain: laodong.vn, name: Lao Động, fetch_mode: browser, kind: news,
     rss: [https://laodong.vn/rss/bat-dong-san.rss]}
```

- [ ] **Step 6: Viết `data/topics.yaml`**

```yaml
target_per_topic: 5
# Từ khoá lọc thô bài BĐS khi báo không có chuyên mục trong URL (so trên URL + tiêu đề, không dấu và có dấu).
bds_keywords: [bat-dong-san, nha-dat, du-an, chung-cu, can-ho, biet-thu, lien-ke, dat-nen, quy-hoach, ha-tang,
  vanh-dai, cao-toc, metro, khu-do-thi, nha-o, gia-nha, dia-oc, bất động sản, nhà đất, dự án, chung cư, căn hộ,
  biệt thự, liền kề, đất nền, quy hoạch, hạ tầng, vành đai, cao tốc, khu đô thị, nhà ở, giá nhà, địa ốc]
topics:
  - {code: road, label: Đường bộ, keywords: [đường, đại lộ, cao tốc, vành đai, quốc lộ, nút giao],
     queries: ["hạ tầng giao thông đường bộ quanh {project}", "{locality} {province} đường vành đai cao tốc tiến độ"]}
  - {code: bridge, label: Cầu và vượt sông, keywords: [cầu, vượt sông],
     queries: ["cầu mới gần {locality} {province} tiến độ", "{project} cầu kết nối"]}
  - {code: transit, label: Giao thông công cộng, keywords: [metro, đường sắt đô thị, brt, xe buýt],
     queries: ["metro đường sắt đô thị {locality} {province}", "tuyến xe buýt {locality} {province}"]}
  - {code: travel_time, label: Thời gian di chuyển, keywords: [phút, km, trung tâm, sân bay],
     queries: ["{project} cách trung tâm bao nhiêu km", "từ {locality} đến sân bay Nội Bài mất bao lâu"]}
  - {code: education, label: Giáo dục, keywords: [trường, mầm non, tiểu học, thcs, thpt, đại học],
     queries: ["trường học gần {locality} {province}", "trường quốc tế {locality} {province}"]}
  - {code: healthcare, label: Y tế, keywords: [bệnh viện, phòng khám, trạm y tế],
     queries: ["bệnh viện gần {locality} {province}", "bệnh viện đa khoa {locality}"]}
  - {code: retail, label: Thương mại, keywords: [trung tâm thương mại, siêu thị, chợ, aeon, vincom],
     queries: ["trung tâm thương mại siêu thị gần {locality} {province}"]}
  - {code: leisure, label: Cảnh quan và giải trí, keywords: [công viên, hồ, sân golf, khu vui chơi],
     queries: ["công viên hồ sân golf gần {locality} {province}"]}
  - {code: employment, label: Việc làm và hành chính, keywords: [khu công nghiệp, khu công nghệ cao, trụ sở, hành chính],
     queries: ["khu công nghiệp khu công nghệ cao gần {locality} {province}"]}
  - {code: zoning, label: Quy hoạch, keywords: [quy hoạch, phân khu, lên quận, đô thị vệ tinh, sáp nhập],
     queries: ["quy hoạch {locality} {province} mới nhất", "{locality} lên quận quy hoạch đô thị"]}
  - {code: area_development, label: Dự án lớn trong khu vực, keywords: [khởi công, đầu tư, dự án lớn, động lực],
     queries: ["dự án hạ tầng lớn khởi công {locality} {province}"]}
  - {code: nearby_projects, label: Dự án lân cận, keywords: [dự án, khu đô thị, chủ đầu tư],
     queries: ["dự án bất động sản gần {project}", "dự án khu đô thị {locality} {province}"]}
  - {code: price_trend, label: Mặt bằng giá, keywords: [giá, triệu/m2, tỷ, tăng giá, thanh khoản],
     queries: ["giá nhà đất {locality} {province} hiện nay", "giá bán {project}"]}
  - {code: project_news, label: Tin về dự án, keywords: [mở bán, bàn giao, tiến độ, ra mắt, giải thưởng],
     queries: ["{project} tin tức mới nhất", "{project} tiến độ bàn giao"]}
  - {code: onsite_amenities, label: Tiện ích nội khu, keywords: [tiện ích, bể bơi, clubhouse, công viên nội khu],
     queries: ["{project} tiện ích nội khu"]}
```

- [ ] **Step 7: Viết `data/regions.yaml` và `data/admin_units.yaml`**

```yaml
# data/regions.yaml — vùng tự định nghĩa để tìm dự án lân cận. Một huyện được thuộc nhiều vùng.
regions:
  - {name: Tây Hà Nội, districts: [Đan Phượng, Hoài Đức, Bắc Từ Liêm, Nam Từ Liêm, Phúc Thọ, Quốc Oai, Thạch Thất, Sơn Tây]}
  - {name: Bắc Hà Nội, districts: [Đông Anh, Mê Linh, Sóc Sơn, Tây Hồ]}
  - {name: Đông Hà Nội, districts: [Long Biên, Gia Lâm, Văn Giang]}
  - {name: Nam Hà Nội, districts: [Hoàng Mai, Thanh Trì, Hà Đông, Thanh Oai, Thường Tín]}
  - {name: Nội đô Hà Nội, districts: [Hoàn Kiếm, Ba Đình, Đống Đa, Hai Bà Trưng, Cầu Giấy, Thanh Xuân, Tây Hồ]}
```

```yaml
# data/admin_units.yaml — huyện/quận CŨ (trước 07/2025) của Hà Nội. communes: xã/phường MỚI và các xã cũ gộp vào.
# communes để trống cho tới khi điền từ nghị quyết sắp xếp đơn vị hành chính cấp xã 2025 của Hà Nội;
# khi trống, việc tìm lân cận bắt đầu từ cấp huyện.
units:
  - {province: Hà Nội, district: Ba Đình}
  - {province: Hà Nội, district: Hoàn Kiếm}
  - {province: Hà Nội, district: Tây Hồ}
  - {province: Hà Nội, district: Long Biên}
  - {province: Hà Nội, district: Cầu Giấy}
  - {province: Hà Nội, district: Đống Đa}
  - {province: Hà Nội, district: Hai Bà Trưng}
  - {province: Hà Nội, district: Hoàng Mai}
  - {province: Hà Nội, district: Thanh Xuân}
  - {province: Hà Nội, district: Hà Đông}
  - {province: Hà Nội, district: Bắc Từ Liêm}
  - {province: Hà Nội, district: Nam Từ Liêm}
  - {province: Hà Nội, district: Sơn Tây}
  - {province: Hà Nội, district: Ba Vì}
  - {province: Hà Nội, district: Chương Mỹ}
  - {province: Hà Nội, district: Đan Phượng, aliases: [Tây Thăng Long]}
  - {province: Hà Nội, district: Đông Anh}
  - {province: Hà Nội, district: Gia Lâm}
  - {province: Hà Nội, district: Hoài Đức}
  - {province: Hà Nội, district: Mê Linh}
  - {province: Hà Nội, district: Mỹ Đức}
  - {province: Hà Nội, district: Phú Xuyên}
  - {province: Hà Nội, district: Phúc Thọ}
  - {province: Hà Nội, district: Quốc Oai}
  - {province: Hà Nội, district: Sóc Sơn}
  - {province: Hà Nội, district: Thạch Thất}
  - {province: Hà Nội, district: Thanh Oai}
  - {province: Hà Nội, district: Thanh Trì}
  - {province: Hà Nội, district: Thường Tín}
  - {province: Hà Nội, district: Ứng Hòa}
  - {province: Hưng Yên, district: Văn Giang}
```

- [ ] **Step 8: Thêm trường vào `KbEnv`** (`src/portal/modules/kb/settings.py`, ngay dưới dòng `hippo_enabled: bool = False`)

```python
    web_llm_api_key: str = ""
    web_llm_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    web_llm_concurrency: int = 4
    web_gemini_api_key: str = ""
    web_grounding_daily_cap: int = 1200
    web_fetch_per_domain: int = 2
    web_fetch_delay_sec: float = 1.0
```

- [ ] **Step 9: Thêm 5 profile vào cuối `src/portal/modules/kb/prompts.yaml`**

```yaml
web_tag:
  model: qwen3.7-flash
  max_tokens: 400
  temperature: 0
  prompt: |
    Đọc bài báo và trả về đúng một JSON: {"relevant": true|false, "projects": [...], "location": [...]}.
    relevant = true khi bài nói về bất động sản, thị trường nhà đất, hạ tầng giao thông, quy hoạch,
    hoặc tiện ích khu vực (trường học, bệnh viện, trung tâm thương mại, công viên).
    projects: tên đầy đủ các DỰ ÁN BẤT ĐỘNG SẢN cụ thể được nhắc tới. Không đưa tên đường, cầu,
    sân bay, công trình công cộng vào đây.
    location: tỉnh/thành, quận/huyện, xã/phường được nhắc tới, viết đúng như trong bài.
    Không có thì để mảng rỗng. Chỉ trả JSON.

web_dossier:
  model: qwen3.7-flash
  max_tokens: 6000
  temperature: 0.2
  prompt: |
    Bạn viết hồ sơ "điểm cộng" của một dự án bất động sản từ các nguồn được đánh số [1], [2], ...
    Trả về đúng một JSON: {"items": [{"text": "...", "cites": [1, 2]}]}.
    Mỗi item nói về MỘT đối tượng (một công trình, một nhóm tiện ích, một chủ đề), dài 150–400 từ,
    đủ ý: số liệu, khoảng cách, quy mô, tiến độ hiện tại, lịch sử các mốc, ý nghĩa với dự án.
    Sau mỗi vế câu ghi số nguồn dạng [n]. Chỉ dùng số có trong danh sách nguồn.
    Luật bắt buộc:
    1. Dữ liệu chính thức của chủ đầu tư được cho sẵn là đúng nhất. Không viết điều trái với nó;
       chỉ bổ sung phần nó chưa có.
    2. Hai nguồn khác thời điểm nói khác nhau thì dùng nguồn mới nhất, ghi thêm mốc cũ đã thay đổi thế nào.
    3. Mốc "dự kiến" đã qua so với ngày hôm nay mà không có tin mới: ghi rõ "chưa có cập nhật".
    4. Cùng thời điểm mà khác số: ghi cả hai hoặc gộp thành khoảng, kèm nguồn của từng số.
    5. Hai nguồn trái ngược hoàn toàn: ghi cả hai; nguồn chính thống thắng nếu có.
    6. Khác đơn vị, khác đoạn tuyến, khác khái niệm (thông xe kỹ thuật và khai thác) không phải mâu thuẫn: giữ nguyên định ngữ.
    7. Không thêm nhận định, đánh giá hay suy đoán không có trong nguồn. Giữ nguyên tên hành chính như trong nguồn.
    Hồ sơ hiện có: giữ các item vẫn đúng (giữ số nguồn của chúng), sửa item có tin mới, thêm item mới.
    Nếu có thẻ dự án lân cận, viết thêm một item "Dự án lân cận" so sánh ngắn với dự án này.

web_card:
  model: qwen3.7-flash
  max_tokens: 1500
  temperature: 0.2
  prompt: |
    Viết thẻ thông tin của MỘT dự án bất động sản từ các nguồn được đánh số [1], [2], ...
    Trả về đúng một JSON: {"text": "...", "cites": [1, 2]}. Dài 120–300 từ gồm: chủ đầu tư, vị trí,
    quy mô, loại hình, giá rao (ghi rõ theo nguồn nào, ngày nào), pháp lý, tiến độ.
    Sau mỗi vế câu ghi số nguồn [n]. Không thêm nhận định không có trong nguồn.
    Có thẻ cũ thì cập nhật nó theo nguồn mới, giữ phần vẫn đúng.

web_digest:
  model: qwen3.7-flash
  max_tokens: 5000
  temperature: 0.2
  prompt: |
    Chọn tối đa 10 tin bất động sản quan trọng nhất từ các nguồn được đánh số [1], [2], ...
    Trả về đúng một JSON: {"items": [{"text": "...", "cites": [1]}]}. Mỗi item là một tin, dài
    80–200 từ, đủ ý: chuyện gì, ở đâu, số liệu, ảnh hưởng tới thị trường. Sau mỗi vế câu ghi [n].
    Gộp các nguồn cùng nói một tin vào một item. Không thêm nhận định không có trong nguồn.

web_grounding:
  model: gemini-2.5-flash
  max_tokens: 800
  temperature: 0
  prompt: ""
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_kb_web_config.py tests/modules/kb/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 11: Checkpoint** — báo user tự commit.

---

### Task 3: Chuẩn hoá và địa danh

**Files:**
- Create: `src/portal/modules/kb/web/normalize.py`
- Create: `src/portal/modules/kb/web/locate.py`
- Test: `tests/unit/test_kb_web_normalize.py`

**Interfaces:**
- Consumes: `config.WebConfig`, `config.Unit`, `config.Region` (Task 2).
- Produces: `canonical_url(url) -> str`, `domain_of(url) -> str`, `content_hash(text) -> str`, `clean_labels(values) -> tuple[str, ...]`, `fold(text) -> str`, `contains_word(hay_folded, needle) -> bool`. Trong `locate.py`: `strip_admin_prefix(name) -> str`, `expand(labels, cfg) -> tuple[str, ...]`, `locate_text(text, cfg) -> tuple[str, ...]`, `levels(location, cfg) -> list[tuple[str, ...]]` (thứ tự: xã, huyện, vùng; bỏ cấp rỗng).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_normalize.py
from portal.modules.kb.web import config
from portal.modules.kb.web.locate import expand, levels, locate_text, strip_admin_prefix
from portal.modules.kb.web.normalize import canonical_url, clean_labels, content_hash, domain_of


def test_bo_tham_so_theo_doi_va_neo():
    u = "https://CafeF.vn/bai-viet.chn/?utm_source=fb&id=3&fbclid=x#top"
    assert canonical_url(u) == "https://cafef.vn/bai-viet.chn?id=3"


def test_domain_bo_www():
    assert domain_of("https://www.savills.com.vn/research") == "savills.com.vn"


def test_bam_khong_phu_thuoc_khoang_trang_va_hoa_thuong():
    assert content_hash("Cầu  Hồng Hà\nkhởi công") == content_hash("cầu hồng hà khởi công")
    assert content_hash("   ") == ""


def test_lam_sach_nhan_nhu_qwen_tra_ve():
    assert clean_labels(["Hà Nội", "Cầu Giấy", "Cầu Giấy", None, "", "null", " Tây Hà Nội "]) == (
        "Hà Nội",
        "Cầu Giấy",
        "Tây Hà Nội",
    )


def test_bo_tien_to_hanh_chinh():
    assert strip_admin_prefix("huyện Đan Phượng") == "Đan Phượng"
    assert strip_admin_prefix("TP. Hà Nội") == "Hà Nội"


def test_mo_rong_huyen_ra_tinh_va_vung():
    loc = expand(["huyện Đan Phượng"], config.load())
    assert {"Đan Phượng", "Hà Nội", "Tây Hà Nội"} <= set(loc)


def test_do_dia_danh_trong_dia_chi():
    loc = locate_text("xã Tân Lập, huyện Đan Phượng, Hà Nội", config.load())
    assert "Đan Phượng" in loc and "Hà Nội" in loc


def test_cap_tu_hep_ra_rong():
    cfg = config.load()
    lv = levels(expand(["Đan Phượng"], cfg), cfg)
    assert lv[0] == ("Đan Phượng",)
    assert "Tây Hà Nội" in lv[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_normalize.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.normalize'`.

- [ ] **Step 3: Viết `normalize.py`**

```python
# src/portal/modules/kb/web/normalize.py
import hashlib
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS = {"fbclid", "gclid", "zarsrc", "zaloapp", "_ga"}
_BLANK = {"", "null", "none", "n/a", "-"}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def contains_word(hay_folded: str, needle: str) -> bool:
    n = fold(needle)
    return bool(n) and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", hay_folded) is not None


def content_hash(text: str) -> str:
    norm = fold(text)
    return hashlib.sha256(norm.encode()).hexdigest() if norm else ""


def clean_labels(values: Iterable | None) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        if not isinstance(v, str):
            continue
        s = " ".join(unicodedata.normalize("NFC", v).split()).strip(" ,.;")
        if s.casefold() in _BLANK or s.casefold() in seen:
            continue
        seen.add(s.casefold())
        out.append(s)
    return tuple(out)
```

- [ ] **Step 4: Viết `locate.py`**

```python
# src/portal/modules/kb/web/locate.py
import re

from portal.modules.kb.web.config import Commune, Unit, WebConfig
from portal.modules.kb.web.normalize import clean_labels, contains_word, fold

_PREFIX = re.compile(r"^(thành phố|tp\.?|tỉnh|quận|huyện|thị xã|tx\.?|h\.|q\.|xã|phường|thị trấn)\s+", re.IGNORECASE)


def strip_admin_prefix(name: str) -> str:
    return _PREFIX.sub("", name.strip()).strip()


def _find(base: str, cfg: WebConfig) -> tuple[Unit | None, Commune | None]:
    key = fold(base)
    for u in cfg.units:
        if key in {fold(u.district), *(fold(a) for a in u.aliases)}:
            return u, None
        for c in u.communes:
            if key in {fold(c.name), *(fold(f) for f in c.former)}:
                return u, c
    return None, None


def _regions_of(district: str, cfg: WebConfig) -> list[str]:
    return [r.name for r in cfg.regions if district in r.districts]


def expand(labels, cfg: WebConfig) -> tuple[str, ...]:
    names: list[str] = []
    for label in clean_labels(labels):
        base = strip_admin_prefix(label)
        names.append(base)
        unit, commune = _find(base, cfg)
        if commune is not None:
            names += [commune.name, *commune.former]
        if unit is not None:
            names += [unit.district, unit.province, *_regions_of(unit.district, cfg)]
    return clean_labels(names)


def locate_text(text: str, cfg: WebConfig) -> tuple[str, ...]:
    hay = fold(text)
    hits: list[str] = []
    for u in cfg.units:
        for c in u.communes:
            if any(contains_word(hay, n) for n in (c.name, *c.former)):
                hits.append(c.name)
        if any(contains_word(hay, n) for n in (u.district, *u.aliases)):
            hits.append(u.district)
    provinces = {u.province for u in cfg.units}
    hits += [p for p in provinces if contains_word(hay, p)]
    return expand(hits, cfg)


def levels(location, cfg: WebConfig) -> list[tuple[str, ...]]:
    loc = set(location)
    communes = tuple(c.name for u in cfg.units for c in u.communes if c.name in loc)
    districts = tuple(u.district for u in cfg.units if u.district in loc)
    regions = tuple(r.name for r in cfg.regions if r.name in loc)
    return [lv for lv in (communes, districts, regions) if lv]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_kb_web_normalize.py -v`
Expected: PASS (8 test).

- [ ] **Step 6: Checkpoint** — báo user tự commit.

---

### Task 4: Repo `public_data.web_pages`

**Files:**
- Create: `src/portal/modules/kb/web/repo.py`
- Create: `tests/modules/kb/web/conftest.py`
- Test: `tests/modules/kb/web/test_repo.py`

**Interfaces:**
- Consumes: `contracts.Page` (Task 2).
- Produces (mọi hàm nhận `conn: asyncpg.Connection`, không cần tenant):
  - `known_urls(conn, urls: list[str]) -> set[str]`
  - `hash_taken(conn, content_hash: str, url: str) -> bool`
  - `save_page(conn, *, url, source_url, domain, title, published_at, content_text, content_hash, found_via, status, projects, location) -> None`
  - `pages_for(conn, *, projects, location, since=None, limit=200) -> list[Page]`
  - `pages_fetched_since(conn, since, limit=60) -> list[Page]`
  - `names_near(conn, location, exclude, limit=20) -> list[str]`
  - `living_due(conn, domains, older_than, limit=200) -> list[str]`
  - `purge(conn, *, now, keep_days=730, marker_days=90) -> int`
- Produces (conftest): fixture `web_pool` (pool `portal_api`, tự dọn URL `https://test.kbweb/%`), `web_tenant` (tenant `kbw_a` có dự án published `NPTTL`).

- [ ] **Step 1: Viết conftest**

```python
# tests/modules/kb/web/conftest.py
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

TENANT = "kbw_a"
OTHER = "kbw_b"
NPTTL = "Noble Palace Tây Thăng Long"


@pytest.fixture
async def web_pool(api_dsn, pool):
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    await p.execute("DELETE FROM public_data.web_pages WHERE url LIKE 'https://test.kbweb/%'")
    yield p
    await p.execute("DELETE FROM public_data.web_pages WHERE url LIKE 'https://test.kbweb/%'")
    await p.close()


@pytest.fixture
async def web_tenant(pool):
    await pool.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, OTHER])
    for tid in (TENANT, OTHER):
        await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tid)
        async with tenant_conn(pool, tid) as conn:
            await conn.execute(
                """INSERT INTO tenant_data.projects (tenant_id, project_code, name, address, region, status)
                   VALUES ($1, 'NPTTL', $2, 'xã Tân Lập, huyện Đan Phượng, Hà Nội', 'Hà Nội', 'published')""",
                tid,
                NPTTL,
            )
    yield TENANT
    await pool.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, OTHER])
```

- [ ] **Step 2: Write the failing test**

```python
# tests/modules/kb/web/test_repo.py
from datetime import UTC, datetime, timedelta

import pytest

from portal.modules.kb.web import repo

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 29, 20, 0, tzinfo=UTC)


async def _save(c, url, *, projects=(), location=(), status="ok", published=NOW, text="nội dung", h=""):
    await repo.save_page(
        c,
        url=url,
        source_url=url,
        domain="test.kbweb",
        title="t",
        published_at=published,
        content_text=text if status == "ok" else None,
        content_hash=h,
        found_via="sitemap",
        status=status,
        projects=list(projects),
        location=list(location),
    )


async def test_known_urls_va_ghi_de(web_pool):
    async with web_pool.acquire() as c:
        await _save(c, "https://test.kbweb/a", projects=["A"])
        await _save(c, "https://test.kbweb/a", projects=["B"])
        assert await repo.known_urls(c, ["https://test.kbweb/a", "https://test.kbweb/z"]) == {"https://test.kbweb/a"}
        (p,) = await repo.pages_for(c, projects=["B"], location=[])
        assert p.projects == ("B",)


async def test_hash_taken_bo_qua_chinh_no(web_pool):
    async with web_pool.acquire() as c:
        await _save(c, "https://test.kbweb/goc", h="h1")
        assert await repo.hash_taken(c, "h1", "https://test.kbweb/chep")
        assert not await repo.hash_taken(c, "h1", "https://test.kbweb/goc")


async def test_pages_for_loc_theo_du_an_hoac_dia_danh_va_bo_dau_loai(web_pool):
    async with web_pool.acquire() as c:
        await _save(c, "https://test.kbweb/1", projects=["NPTTL"])
        await _save(c, "https://test.kbweb/2", location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/3", location=["Đan Phượng"], status="irrelevant")
        got = {p.url for p in await repo.pages_for(c, projects=["NPTTL"], location=["Đan Phượng"])}
        assert got == {"https://test.kbweb/1", "https://test.kbweb/2"}


async def test_names_near_dem_theo_so_bai_va_bo_chinh_minh(web_pool):
    async with web_pool.acquire() as c:
        await _save(c, "https://test.kbweb/n1", projects=["NPTTL", "Wonder City"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n2", projects=["Wonder City"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n3", projects=["Riverside"], location=["Đan Phượng"])
        assert await repo.names_near(c, ["Đan Phượng"], ["NPTTL"]) == ["Wonder City", "Riverside"]


async def test_purge_xoa_bai_qua_han_va_dau_cu(web_pool):
    async with web_pool.acquire() as c:
        await _save(c, "https://test.kbweb/cu", published=NOW - timedelta(days=800))
        await _save(c, "https://test.kbweb/moi", published=NOW)
        await c.execute(
            """UPDATE public_data.web_pages SET last_checked_at = $1
                WHERE url = 'https://test.kbweb/moi'""",
            NOW,
        )
        await _save(c, "https://test.kbweb/dau", status="fetch_failed")
        await c.execute(
            "UPDATE public_data.web_pages SET last_checked_at = $1 WHERE url = 'https://test.kbweb/dau'",
            NOW - timedelta(days=100),
        )
        assert await repo.purge(c, now=NOW) >= 2
        assert await repo.known_urls(c, ["https://test.kbweb/cu", "https://test.kbweb/dau", "https://test.kbweb/moi"]) == {
            "https://test.kbweb/moi"
        }
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/web/test_repo.py -v`
Expected: FAIL với `ImportError: cannot import name 'repo'`.

- [ ] **Step 4: Viết `repo.py`**

```python
# src/portal/modules/kb/web/repo.py
"""SQL trên public_data.web_pages. Dữ liệu công khai, không lọc tenant."""

from datetime import datetime

import asyncpg

from portal.modules.kb.web.contracts import Page

_COLS = "url, domain, title, published_at, fetched_at, coalesce(content_text, '') AS content_text, projects, location"


def _page(r: asyncpg.Record) -> Page:
    return Page(
        url=r["url"],
        domain=r["domain"],
        title=r["title"],
        published_at=r["published_at"],
        fetched_at=r["fetched_at"],
        content_text=r["content_text"],
        projects=tuple(r["projects"]),
        location=tuple(r["location"]),
    )


async def known_urls(conn: asyncpg.Connection, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    rows = await conn.fetch("SELECT url FROM public_data.web_pages WHERE url = ANY($1::text[])", urls)
    return {r["url"] for r in rows}


async def hash_taken(conn: asyncpg.Connection, content_hash: str, url: str) -> bool:
    if not content_hash:
        return False
    return bool(
        await conn.fetchval(
            """SELECT 1 FROM public_data.web_pages
                WHERE content_hash = $1 AND url <> $2 AND status = 'ok' LIMIT 1""",
            content_hash,
            url,
        )
    )


async def save_page(
    conn: asyncpg.Connection,
    *,
    url: str,
    source_url: str,
    domain: str,
    title: str,
    published_at: datetime | None,
    content_text: str | None,
    content_hash: str,
    found_via: str,
    status: str,
    projects: list[str],
    location: list[str],
) -> None:
    await conn.execute(
        """INSERT INTO public_data.web_pages
               (url, source_url, domain, title, published_at, content_text, content_hash,
                found_via, status, projects, location)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text[], $11::text[])
           ON CONFLICT (url) DO UPDATE SET
               title = EXCLUDED.title,
               published_at = coalesce(EXCLUDED.published_at, public_data.web_pages.published_at),
               fetched_at = CASE WHEN public_data.web_pages.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                                 THEN now() ELSE public_data.web_pages.fetched_at END,
               last_checked_at = now(),
               content_text = EXCLUDED.content_text,
               content_hash = EXCLUDED.content_hash,
               status = EXCLUDED.status,
               projects = EXCLUDED.projects,
               location = EXCLUDED.location""",
        url,
        source_url,
        domain,
        title,
        published_at,
        content_text,
        content_hash,
        found_via,
        status,
        projects,
        location,
    )


async def pages_for(
    conn: asyncpg.Connection,
    *,
    projects: list[str],
    location: list[str],
    since: datetime | None = None,
    limit: int = 200,
) -> list[Page]:
    rows = await conn.fetch(
        f"""SELECT {_COLS} FROM public_data.web_pages
             WHERE status = 'ok'
               AND (projects && $1::text[] OR location && $2::text[])
               AND ($3::timestamptz IS NULL OR fetched_at > $3)
             ORDER BY coalesce(published_at, fetched_at) DESC
             LIMIT $4""",
        projects,
        location,
        since,
        limit,
    )
    return [_page(r) for r in rows]


async def pages_fetched_since(conn: asyncpg.Connection, since: datetime, limit: int = 60) -> list[Page]:
    rows = await conn.fetch(
        f"""SELECT {_COLS} FROM public_data.web_pages
             WHERE status = 'ok' AND fetched_at > $1
             ORDER BY coalesce(published_at, fetched_at) DESC
             LIMIT $2""",
        since,
        limit,
    )
    return [_page(r) for r in rows]


async def names_near(conn: asyncpg.Connection, location: list[str], exclude: list[str], limit: int = 20) -> list[str]:
    rows = await conn.fetch(
        """SELECT name, count(*) AS n
             FROM public_data.web_pages, unnest(projects) AS name
            WHERE status = 'ok' AND location && $1::text[] AND NOT (name = ANY($2::text[]))
            GROUP BY name
            ORDER BY n DESC, name
            LIMIT $3""",
        location,
        exclude,
        limit,
    )
    return [r["name"] for r in rows]


async def living_due(conn: asyncpg.Connection, domains: list[str], older_than: datetime, limit: int = 200) -> list[str]:
    rows = await conn.fetch(
        """SELECT url FROM public_data.web_pages
            WHERE domain = ANY($1::text[]) AND status = 'ok' AND last_checked_at < $2
            ORDER BY last_checked_at
            LIMIT $3""",
        domains,
        older_than,
        limit,
    )
    return [r["url"] for r in rows]


async def purge(conn: asyncpg.Connection, *, now: datetime, keep_days: int = 730, marker_days: int = 90) -> int:
    result = await conn.execute(
        """DELETE FROM public_data.web_pages
            WHERE (status = 'ok' AND coalesce(published_at, fetched_at) < $1 - make_interval(days => $2))
               OR (status <> 'ok' AND last_checked_at < $1 - make_interval(days => $3))""",
        now,
        keep_days,
        marker_days,
    )
    return int(result.split()[-1])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/modules/kb/web/test_repo.py -v`
Expected: PASS (5 test).

- [ ] **Step 6: Chạy cổng cách ly**

Run: `uv run pytest tests/isolation -v`
Expected: PASS (không có câu SQL mới nào chạm `tenant_data`).

- [ ] **Step 7: Checkpoint** — báo user tự commit.

---

### Task 5: Tìm bài theo ngày (sitemap, RSS, trang mục)

**Files:**
- Create: `src/portal/modules/kb/web/discover.py`
- Test: `tests/unit/test_kb_web_discover.py`

**Interfaces:**
- Consumes: `config.SourceSite` (Task 2); `normalize.canonical_url`, `normalize.fold` (Task 3).
- Produces: `VN` (ZoneInfo), dataclass `Entry(url, when, title="")`, `parse_when(s) -> datetime | None`, `parse_sitemap(xml: bytes) -> tuple[list[Entry], list[Entry]]` (sitemap con, url), `parse_rss(xml) -> list[Entry]`, `day_bounds(day) -> tuple[datetime, datetime]`, `pick_children(children, day, hint) -> list[str]`, `looks_bds(entry, source, keywords) -> bool`, `category_links(html, base_url, pattern) -> list[str]`, class `Discoverer(http)` với `async day_entries(source, day, keywords) -> list[Entry]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_discover.py
from datetime import date

import httpx

from portal.modules.kb.web.config import SourceSite
from portal.modules.kb.web.discover import (
    Discoverer,
    Entry,
    category_links,
    day_bounds,
    looks_bds,
    parse_rss,
    parse_sitemap,
    parse_when,
    pick_children,
)

DAY = date(2026, 9, 28)

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://ex.vn/sitemaps-2026-9-26-30.xml</loc></sitemap>
<sitemap><loc>https://ex.vn/sitemaps-2026-8-26-31.xml</loc></sitemap></sitemapindex>"""

URLSET = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://ex.vn/bat-dong-san/cau-hong-ha-1.html</loc><lastmod>2026-09-28T10:00:00+07:00</lastmod></url>
<url><loc>https://ex.vn/the-thao/bong-da-2.html</loc><lastmod>2026-09-28T11:00:00+07:00</lastmod></url>
<url><loc>https://ex.vn/bat-dong-san/cu-3.html</loc><lastmod>2026-09-27T23:59:00+07:00</lastmod></url>
<url><loc>https://ex.vn/x-4.html</loc><news:news><news:publication_date>2026-09-28T08:00:00+07:00</news:publication_date>
<news:title>Giá chung cư Hà Nội tăng</news:title></news:news></url></urlset>"""

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Tin A</title><link>https://ex.vn/bat-dong-san/a-5.html</link><pubDate>Sun, 28 Sep 2026 03:00:00 +0000</pubDate></item>
</channel></rss>"""

SRC = SourceSite(
    domain="ex.vn", name="Ex", whitelisted=True, fetch_mode="http", kind="news",
    rss=("https://ex.vn/rss.rss",), sitemap_index="https://ex.vn/sitemap.xml", child_hint="-{y}-{m}-",
    news_sitemaps=(), category_pages=(), article_pattern="", category_paths=("/bat-dong-san",),
)


def test_parse_when_gan_mui_gio_vn_cho_ngay_tran():
    assert parse_when("2026-09-28").utcoffset().total_seconds() == 7 * 3600
    assert parse_when("khong phai ngay") is None


def test_parse_sitemap_index_va_urlset():
    children, urls = parse_sitemap(INDEX)
    assert len(children) == 2 and urls == []
    _, urls = parse_sitemap(URLSET)
    assert urls[3].title == "Giá chung cư Hà Nội tăng"
    assert urls[3].when is not None


def test_chon_sitemap_con_theo_goi_y_khi_khong_co_lastmod():
    children, _ = parse_sitemap(INDEX)
    assert pick_children(children, DAY, "-{y}-{m}-") == ["https://ex.vn/sitemaps-2026-9-26-30.xml"]


def test_ranh_gioi_ngay_theo_gio_vn():
    start, end = day_bounds(DAY)
    assert start.isoformat() == "2026-09-28T00:00:00+07:00"
    assert (end - start).days == 1


def test_loc_bai_bds_theo_chuyen_muc_hoac_tu_khoa():
    assert looks_bds(Entry("https://ex.vn/bat-dong-san/a.html", None), SRC, ())
    assert not looks_bds(Entry("https://ex.vn/the-thao/a.html", None), SRC, ())
    src2 = SourceSite(**{f: getattr(SRC, f) for f in SRC.__slots__ if f != "category_paths"}, category_paths=())
    assert looks_bds(Entry("https://ex.vn/x-4.html", None, "Giá chung cư Hà Nội tăng"), src2, ("chung cư",))


def test_lay_link_bai_tu_trang_muc():
    html = '<a href="/tin-tuc/abc-123.html">x</a><a href="https://khac.vn/y">y</a><a href="/lien-he">z</a>'
    assert category_links(html, "https://cafeland.vn/tin-tuc/", r"^https://cafeland\.vn/tin-tuc/.+-\d+\.html$") == [
        "https://cafeland.vn/tin-tuc/abc-123.html"
    ]


def test_parse_rss():
    (e,) = parse_rss(RSS)
    assert e.url == "https://ex.vn/bat-dong-san/a-5.html"
    assert e.when.date() == DAY


async def test_day_entries_gom_sitemap_va_rss_dung_ngay_dung_chuyen_muc():
    routes = {
        "https://ex.vn/sitemap.xml": INDEX,
        "https://ex.vn/sitemaps-2026-9-26-30.xml": URLSET,
        "https://ex.vn/rss.rss": RSS,
    }

    def handler(req: httpx.Request) -> httpx.Response:
        body = routes.get(str(req.url))
        return httpx.Response(200, content=body) if body else httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        got = {e.url for e in await Discoverer(http).day_entries(SRC, DAY, ("chung cư",))}
    assert got == {"https://ex.vn/bat-dong-san/cau-hong-ha-1.html", "https://ex.vn/bat-dong-san/a-5.html"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_discover.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.discover'`.

- [ ] **Step 3: Viết `discover.py`**

```python
# src/portal/modules/kb/web/discover.py
import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from portal.modules.kb.web.config import SourceSite
from portal.modules.kb.web.normalize import canonical_url, fold

log = logging.getLogger(__name__)

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_XML_BYTES = 20_000_000
MAX_CHILDREN = 12
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Entry:
    url: str
    when: datetime | None
    title: str = ""


def parse_when(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = email.utils.parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=VN)


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_sitemap(xml: bytes) -> tuple[list[Entry], list[Entry]]:
    root = ET.fromstring(xml)
    children = [
        Entry(_text(el.find(f"{_SM}loc")), parse_when(_text(el.find(f"{_SM}lastmod"))))
        for el in root.iter(f"{_SM}sitemap")
    ]
    urls = []
    for el in root.iter(f"{_SM}url"):
        news = el.find(f"{_NEWS}news")
        when = parse_when(_text(news.find(f"{_NEWS}publication_date"))) if news is not None else None
        title = _text(news.find(f"{_NEWS}title")) if news is not None else ""
        urls.append(Entry(_text(el.find(f"{_SM}loc")), when or parse_when(_text(el.find(f"{_SM}lastmod"))), title))
    return [c for c in children if c.url], [u for u in urls if u.url]


def parse_rss(xml: bytes) -> list[Entry]:
    root = ET.fromstring(xml)
    out = [
        Entry(_text(it.find("link")), parse_when(_text(it.find("pubDate"))), _text(it.find("title")))
        for it in root.iter("item")
    ]
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter(f"{atom}entry"):
        link = it.find(f"{atom}link")
        when = _text(it.find(f"{atom}published")) or _text(it.find(f"{atom}updated"))
        out.append(Entry(link.get("href", "") if link is not None else "", parse_when(when), _text(it.find(f"{atom}title"))))
    return [e for e in out if e.url]


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=VN)
    return start, start + timedelta(days=1)


def pick_children(children: list[Entry], day: date, hint: str) -> list[str]:
    start, end = day_bounds(day)
    dated = [c for c in children if c.when is not None]
    if dated:
        chosen = [c.url for c in dated if start - timedelta(days=1) <= c.when <= end + timedelta(days=40)]
    elif hint:
        token = hint.format(y=day.year, m=day.month, mm=f"{day.month:02d}", d=day.day, dd=f"{day.day:02d}")
        chosen = [c.url for c in children if token in c.url]
    else:
        chosen = []
    return chosen[:MAX_CHILDREN]


def _in_day(entry: Entry, day: date) -> bool:
    start, end = day_bounds(day)
    return entry.when is not None and start <= entry.when < end


def looks_bds(entry: Entry, source: SourceSite, keywords: tuple[str, ...]) -> bool:
    if source.category_paths:
        path = urlsplit(entry.url).path
        return any(path.startswith(p) for p in source.category_paths)
    hay = fold(f"{entry.url} {entry.title}")
    return any(fold(k) in hay for k in keywords)


def category_links(html: str, base_url: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    out: list[str] = []
    for href in _HREF.findall(html):
        u = urljoin(base_url, href)
        if rx.match(u) and u not in out:
            out.append(u)
    return out


class Discoverer:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _get(self, url: str) -> bytes | None:
        try:
            r = await self._http.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("không tải được %s: %s", url, exc)
            return None
        if r.status_code != 200 or len(r.content) > MAX_XML_BYTES:
            return None
        return r.content

    async def _sitemap(self, url: str) -> tuple[list[Entry], list[Entry]]:
        body = await self._get(url)
        if body is None:
            return [], []
        try:
            return parse_sitemap(body)
        except ET.ParseError:
            log.warning("sitemap hỏng: %s", url)
            return [], []

    async def day_entries(self, source: SourceSite, day: date, keywords: tuple[str, ...]) -> list[Entry]:
        dated: list[Entry] = []
        if source.sitemap_index:
            children, urls = await self._sitemap(source.sitemap_index)
            dated += urls
            for child in pick_children(children, day, source.child_hint):
                dated += (await self._sitemap(child))[1]
        for url in source.news_sitemaps:
            dated += (await self._sitemap(url))[1]
        for url in source.rss:
            body = await self._get(url)
            if body is not None:
                try:
                    dated += parse_rss(body)
                except ET.ParseError:
                    log.warning("rss hỏng: %s", url)
        undated: list[Entry] = []
        for page in source.category_pages:
            body = await self._get(page)
            if body is not None:
                undated += [Entry(u, None) for u in category_links(body.decode("utf-8", "ignore"), page, source.article_pattern)]
        keep = [e for e in dated if _in_day(e, day)] + undated
        seen: set[str] = set()
        out: list[Entry] = []
        for e in keep:
            key = canonical_url(e.url)
            if key not in seen and looks_bds(e, source, keywords):
                seen.add(key)
                out.append(Entry(key, e.when, e.title))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_kb_web_discover.py -v`
Expected: PASS (8 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 6: Tải trang tầng 1 và bóc nội dung

**Files:**
- Modify: `pyproject.toml` (thêm `trafilatura>=2.0` vào `[project].dependencies`, cạnh `httpx>=0.28`)
- Create: `src/portal/modules/kb/web/fetch.py`
- Test: `tests/unit/test_kb_web_fetch.py`

**Interfaces:**
- Consumes: `discover.parse_when` (Task 5), `normalize.domain_of` (Task 3), `contracts.STATUS_*` (Task 2).
- Produces: dataclass `Fetched(url, status, title="", text="", published_at=None)`, `looks_challenged(status_code, html) -> bool`, `extract(html, url) -> tuple[str, str, datetime | None]`, class `Fetcher(http, *, per_domain=2, delay_sec=1.0)` với `async fetch(url) -> Fetched`. Hằng `USER_AGENT`, `TIMEOUT_SEC = 20.0`, `MAX_BYTES = 3_000_000`.

- [ ] **Step 1: Thêm dependency**

Run: `uv add "trafilatura>=2.0"`
Expected: `pyproject.toml` có thêm dòng `"trafilatura>=2.0"`; `uv.lock` được cập nhật.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_kb_web_fetch.py
import httpx

from portal.modules.kb.web.fetch import Fetcher, looks_challenged

DOAN = (
    "Đại lộ Thăng Long mở rộng đoạn qua huyện Đan Phượng đã hoàn thành phần mặt đường "
    "với mười làn xe, giúp thời gian di chuyển từ khu vực phía tây vào trung tâm Hà Nội giảm đáng kể. "
)
BAI = (
    "<html><head><title>Đại lộ mở rộng</title>"
    '<meta property="article:published_time" content="2026-09-28T08:00:00+07:00"></head>'
    "<body><article><h1>Đại lộ mở rộng</h1>" + "".join(f"<p>{DOAN * 3}</p>" for _ in range(6)) + "</article></body></html>"
)


def _fetcher(handler) -> Fetcher:
    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), delay_sec=0)


def test_nhan_ra_trang_challenge():
    assert looks_challenged(200, '<html><body><script>document.cookie="D1N=1";window.location.reload(true);</script>')
    assert looks_challenged(403, "<title>Just a moment...</title>")
    assert not looks_challenged(200, BAI)


async def test_bai_binh_thuong_ra_ok_co_noi_dung():
    f = await _fetcher(lambda r: httpx.Response(200, text=BAI)).fetch("https://ex.vn/a.html")
    assert f.status == "ok"
    assert "mười làn xe" in f.text


async def test_trang_chan_bot_ra_needs_browser():
    f = await _fetcher(lambda r: httpx.Response(403, text="<title>Just a moment...</title>")).fetch("https://ex.vn/b")
    assert f.status == "needs_browser"


async def test_404_va_loi_mang_ra_fetch_failed():
    assert (await _fetcher(lambda r: httpx.Response(404)).fetch("https://ex.vn/c")).status == "fetch_failed"

    def hong(r):
        raise httpx.ConnectError("x")

    assert (await _fetcher(hong).fetch("https://ex.vn/d")).status == "fetch_failed"


async def test_trang_qua_lon_ra_fetch_failed():
    big = "a" * 3_100_000
    assert (await _fetcher(lambda r: httpx.Response(200, text=big)).fetch("https://ex.vn/e")).status == "fetch_failed"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_fetch.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.fetch'`.

- [ ] **Step 4: Viết `fetch.py`**

```python
# src/portal/modules/kb/web/fetch.py
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

import httpx
import trafilatura

from portal.modules.kb.web.contracts import STATUS_FAILED, STATUS_NEEDS_BROWSER, STATUS_OK
from portal.modules.kb.web.discover import parse_when
from portal.modules.kb.web.normalize import domain_of

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
TIMEOUT_SEC = 20.0
MAX_BYTES = 3_000_000
CHALLENGE_MARKERS = ("just a moment", "cf-chl-", "attention required", "enable javascript and cookies", "document.cookie=")


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    status: str
    title: str = ""
    text: str = ""
    published_at: datetime | None = None


def looks_challenged(status_code: int, html: str) -> bool:
    head = html[:5000].lower()
    if any(m in head for m in CHALLENGE_MARKERS):
        return True
    return status_code in (403, 503) and len(html) < 20_000


def extract(html: str, url: str) -> tuple[str, str, datetime | None]:
    raw = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True, include_comments=False, include_tables=True
    )
    if not raw:
        return "", "", None
    d = json.loads(raw)
    return str(d.get("title") or ""), str(d.get("text") or ""), parse_when(d.get("date"))


class Fetcher:
    def __init__(self, http: httpx.AsyncClient, *, per_domain: int = 2, delay_sec: float = 1.0) -> None:
        self._http = http
        self._per_domain = per_domain
        self._delay = delay_sec
        self._gates: dict[str, asyncio.Semaphore] = {}

    def _gate(self, domain: str) -> asyncio.Semaphore:
        return self._gates.setdefault(domain, asyncio.Semaphore(self._per_domain))

    async def fetch(self, url: str) -> Fetched:
        async with self._gate(domain_of(url)):
            try:
                html, code = await self._download(url)
            except (httpx.HTTPError, ValueError):
                return Fetched(url, STATUS_FAILED)
            finally:
                if self._delay:
                    await asyncio.sleep(self._delay)
        if looks_challenged(code, html):
            return Fetched(url, STATUS_NEEDS_BROWSER)
        if code != 200:
            return Fetched(url, STATUS_FAILED)
        title, text, when = await asyncio.to_thread(extract, html, url)
        if not text.strip():
            return Fetched(url, STATUS_FAILED)
        return Fetched(url, STATUS_OK, title, text, when)

    async def _download(self, url: str) -> tuple[str, int]:
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"}
        async with self._http.stream("GET", url, headers=headers, follow_redirects=True) as r:
            buf = bytearray()
            async for part in r.aiter_bytes():
                buf.extend(part)
                if len(buf) > MAX_BYTES:
                    raise ValueError("trang vượt trần kích thước")
            return buf.decode(r.encoding or "utf-8", errors="ignore"), r.status_code
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_kb_web_fetch.py tests/unit/test_khai_bao_phu_thuoc.py tests/unit/test_khong_keo_torch.py -v`
Expected: PASS.

- [ ] **Step 6: Checkpoint** — báo user tự commit (`pyproject.toml`, `uv.lock`, file mới).

---

### Task 7: Client qwen (gắn nhãn và prompt viết)

**Files:**
- Create: `src/portal/modules/kb/web/llm.py`
- Test: `tests/unit/test_kb_web_llm.py`

**Interfaces:**
- Consumes: `kb.prompts.get`, `kb.settings.HTTP_TIMEOUT_SEC`, `kb.contracts.TemporaryError`; `contracts.Tags`, `PROFILE_TAG`; `normalize.clean_labels`.
- Produces: `class TemporaryLlmError(TemporaryError)`, `parse_json(content) -> dict`, `tags_from(raw) -> Tags`, class `WebLlm(*, base_url, api_key, concurrency=4, http=None)` với `async ask(profile, user_text) -> dict`, `async tag(title, text) -> Tags`, `async aclose()`. Hằng `MAX_TAG_CHARS = 6000`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_llm.py
import json

import httpx
import pytest

from portal.modules.kb.web.llm import TemporaryLlmError, WebLlm, parse_json


def _llm(handler) -> WebLlm:
    return WebLlm(base_url="https://llm.test/v1", api_key="k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_parse_json_bo_fence_va_chu_thua():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Đây: {"a": 2} xong') == {"a": 2}
    with pytest.raises(ValueError):
        parse_json("không có json")


async def test_tag_lam_sach_nhan_va_gui_dung_model():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return _reply('{"relevant": true, "projects": ["Wonder City", "Wonder City", null],'
                      ' "location": ["Hà Nội", "", "Đan Phượng"]}')

    tags = await _llm(handler).tag("tiêu đề", "nội dung")
    assert tags.relevant
    assert tags.projects == ("Wonder City",)
    assert tags.location == ("Hà Nội", "Đan Phượng")
    assert seen["model"] == "qwen3.7-flash"
    assert seen["enable_thinking"] is False
    assert seen["response_format"] == {"type": "json_object"}


async def test_429_la_loi_tam_thoi():
    with pytest.raises(TemporaryLlmError):
        await _llm(lambda r: httpx.Response(429)).tag("t", "x")


def test_thieu_key_thi_khong_dung():
    with pytest.raises(ValueError):
        WebLlm(base_url="https://x", api_key="")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_llm.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.llm'`.

- [ ] **Step 3: Viết `llm.py`**

```python
# src/portal/modules/kb/web/llm.py
import asyncio
import json
import re

import httpx

from portal.modules.kb import prompts, settings
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.contracts import PROFILE_TAG, Tags
from portal.modules.kb.web.normalize import clean_labels

MAX_TAG_CHARS = 6000
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.DOTALL)


class TemporaryLlmError(TemporaryError):
    """429/5xx/timeout: job phải thử lại."""


def parse_json(content: str) -> dict:
    s = _FENCE.sub("", content.strip())
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"không thấy JSON trong trả lời: {content[:200]!r}")
    value = json.loads(s[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON trả về không phải object")
    return value


def tags_from(raw: dict) -> Tags:
    def labels(key: str) -> tuple[str, ...]:
        v = raw.get(key)
        return clean_labels(v if isinstance(v, list) else [])

    return Tags(relevant=bool(raw.get("relevant")), projects=labels("projects"), location=labels("location"))


class WebLlm:
    def __init__(self, *, base_url: str, api_key: str, concurrency: int = 4, http: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ValueError("thiếu KB_WEB_LLM_API_KEY")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._gate = asyncio.Semaphore(concurrency)
        self._http = http or httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ask(self, profile: str, user_text: str) -> dict:
        spec = prompts.get(profile)
        body = {
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "temperature": spec.temperature,
            "enable_thinking": False,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": spec.prompt}, {"role": "user", "content": user_text}],
        }
        async with self._gate:
            try:
                r = await self._http.post(
                    f"{self._base}/chat/completions", headers={"Authorization": f"Bearer {self._key}"}, json=body
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TemporaryLlmError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryLlmError(f"LLM {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"trả lời LLM thiếu choices/message/content: {r.text[:200]}") from exc
        return parse_json(str(content))

    async def tag(self, title: str, text: str) -> Tags:
        return tags_from(await self.ask(PROFILE_TAG, f"TIÊU ĐỀ: {title}\n\n{text[:MAX_TAG_CHARS]}"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_kb_web_llm.py -v`
Expected: PASS (4 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 8: Đánh số nguồn, kiểm [n], payload và id

**Files:**
- Create: `src/portal/modules/kb/web/compose.py`
- Test: `tests/unit/test_kb_web_compose.py`

**Interfaces:**
- Consumes: `contracts.Item`, `Page`, `Source`, `MAX_DOSSIER_ITEMS`, `MAX_DIGEST_ITEMS` (Task 2).
- Produces:
  - `dossier_ids(project_name) -> list[str]`, `card_id(project_name) -> str`, `digest_ids(region) -> list[str]` (uuid5, không trùng nhau giữa ba loại)
  - `source_of(page, names) -> Source`
  - `number_sources(pages, carried, names) -> tuple[str, list[Source], list[str]]` (khối nguồn, danh sách nguồn, text của các item `carried` đã đánh số lại)
  - `renumber(text, own_sources, index) -> str`
  - `parse_items(raw, sources, *, projects, location, limit) -> list[Item]`
  - `payload_of(item, updated_at) -> dict` (đúng 6 khoá), `item_from_payload(payload) -> Item`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_compose.py
from datetime import UTC, datetime

from portal.modules.kb.web.compose import (
    card_id,
    digest_ids,
    dossier_ids,
    item_from_payload,
    number_sources,
    parse_items,
    payload_of,
    renumber,
)
from portal.modules.kb.web.contracts import Item, Page, Source

T1 = datetime(2026, 1, 13, tzinfo=UTC)
T2 = datetime(2026, 9, 15, tzinfo=UTC)
A = Source("https://cafef.vn/a", "CafeF", T1)
B = Source("https://vnexpress.net/b", "VnExpress", T2)


def _page(url, domain, when, text="nội dung"):
    return Page(url, domain, "tiêu đề", when, when, text, (), ())


def test_id_tat_dinh_va_khong_trung_giua_cac_loai():
    assert dossier_ids("X")[0] == dossier_ids("X")[0]
    assert len(set(dossier_ids("X")) | {card_id("X")} | set(digest_ids("toan_quoc"))) == len(dossier_ids("X")) + 1 + len(
        digest_ids("toan_quoc")
    )


def test_danh_so_lai_item_cu_theo_danh_sach_moi():
    cu = Item("Đại lộ 10 làn [1], đã thông xe [2].", (A, B), ("X",), ())
    moi = _page("https://baoxaydung.vn/c", "baoxaydung.vn", T2)
    block, sources, texts = number_sources([moi], [cu], {"baoxaydung.vn": "Báo Xây dựng"})
    assert [s.url for s in sources] == [A.url, B.url, moi.url]
    assert texts == ["Đại lộ 10 làn [1], đã thông xe [2]."]
    assert "[3] Báo Xây dựng" in block


def test_renumber_bo_so_khong_hop_le():
    assert renumber("a [2] b [9]", (A, B), {B.url: 1}) == "a [1] b"


def test_loai_item_trich_so_ngoai_danh_sach_hoac_khong_trich():
    raw = {"items": [{"text": "đúng [1] [2]", "cites": [1, 2]}, {"text": "bịa [7]", "cites": [7]}, {"text": "trống"}]}
    items = parse_items(raw, [A, B], projects=("X",), location=("Hà Nội",), limit=10)
    assert [i.text for i in items] == ["đúng [1] [2]"]
    assert items[0].sources == (A, B)


def test_payload_dung_6_khoa_va_published_at_la_nguon_moi_nhat():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    p = payload_of(Item("x [1]", (A, B), ("X",), ("Hà Nội",)), now)
    assert set(p) == {"text", "location", "projects", "sources", "published_at", "updated_at"}
    assert p["published_at"] == T2.isoformat()
    back = item_from_payload(p)
    assert back.sources == (A, B) and back.updated_at == now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_compose.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.compose'`.

- [ ] **Step 3: Viết `compose.py`**

```python
# src/portal/modules/kb/web/compose.py
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from portal.modules.kb.web.contracts import MAX_DIGEST_ITEMS, MAX_DOSSIER_ITEMS, Item, Page, Source

_NS = uuid.NAMESPACE_URL
_CITE = re.compile(r"\[(\d{1,3})\]")
MAX_SOURCE_CHARS = 4000


def _id(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


def dossier_ids(project_name: str) -> list[str]:
    return [_id(f"kbweb:dossier:{project_name}:{i}") for i in range(MAX_DOSSIER_ITEMS)]


def card_id(project_name: str) -> str:
    return _id(f"kbweb:card:{project_name}")


def digest_ids(region: str) -> list[str]:
    return [_id(f"kbweb:digest:{region}:{i}") for i in range(MAX_DIGEST_ITEMS)]


def source_of(page: Page, names: Mapping[str, str]) -> Source:
    return Source(url=page.url, name=names.get(page.domain, page.domain), published_at=page.published_at)


def renumber(text: str, own_sources: Sequence[Source], index: Mapping[str, int]) -> str:
    def sub(m: re.Match) -> str:
        k = int(m.group(1))
        if 1 <= k <= len(own_sources) and own_sources[k - 1].url in index:
            return f"[{index[own_sources[k - 1].url]}]"
        return ""

    return re.sub(r"\s+([.,;])", r"\1", " ".join(_CITE.sub(sub, text).split()))


def number_sources(
    pages: Sequence[Page], carried: Sequence[Item], names: Mapping[str, str]
) -> tuple[str, list[Source], list[str]]:
    index: dict[str, int] = {}
    sources: list[Source] = []

    def add(src: Source) -> None:
        if src.url not in index:
            sources.append(src)
            index[src.url] = len(sources)

    for it in carried:
        for s in it.sources:
            add(s)
    by_url: dict[str, Page] = {}
    for p in pages:
        add(source_of(p, names))
        by_url[p.url] = p
    texts = [renumber(it.text, it.sources, index) for it in carried]
    lines = []
    for n, s in enumerate(sources, 1):
        page = by_url.get(s.url)
        day = s.published_at.date().isoformat() if s.published_at else "không rõ ngày"
        body = page.content_text[:MAX_SOURCE_CHARS] if page else "(nguồn đã dùng trong nội dung hiện có)"
        lines.append(f"[{n}] {s.name} · {day} · {page.title if page else ''}\n{body}")
    return "\n\n".join(lines), sources, texts


def parse_items(
    raw: dict, sources: Sequence[Source], *, projects: Sequence[str], location: Sequence[str], limit: int
) -> list[Item]:
    rows = raw.get("items") if isinstance(raw.get("items"), list) else [raw]
    out: list[Item] = []
    for r in rows[:limit]:
        if not isinstance(r, dict):
            continue
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        cited = {int(x) for x in _CITE.findall(text)}
        cited |= {int(x) for x in (r.get("cites") or []) if str(x).isdigit()}
        if not cited or any(n < 1 or n > len(sources) for n in cited):
            continue
        out.append(Item(text, tuple(sources[n - 1] for n in sorted(cited)), tuple(projects), tuple(location)))
    return out


def payload_of(item: Item, updated_at: datetime) -> dict:
    dates = [s.published_at for s in item.sources if s.published_at]
    return {
        "text": item.text,
        "location": list(item.location),
        "projects": list(item.projects),
        "sources": [
            {"url": s.url, "name": s.name, "published_at": s.published_at.isoformat() if s.published_at else None}
            for s in item.sources
        ],
        "published_at": max(dates).isoformat() if dates else None,
        "updated_at": updated_at.isoformat(),
    }


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def item_from_payload(p: dict) -> Item:
    return Item(
        text=str(p.get("text") or ""),
        sources=tuple(Source(s["url"], s["name"], _dt(s.get("published_at"))) for s in p.get("sources") or []),
        projects=tuple(p.get("projects") or []),
        location=tuple(p.get("location") or []),
        updated_at=_dt(p.get("updated_at")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_kb_web_compose.py -v`
Expected: PASS (5 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 9: Ghi và đọc collection `public_web`

**Files:**
- Create: `src/portal/modules/kb/web/index.py`
- Test: `tests/modules/kb/web/test_index.py`

**Interfaces:**
- Consumes: `kb.index.store.DENSE_SIZE`, `SPARSE_NAME`; `compose.payload_of`, `item_from_payload`, `card_id` (Task 8); `contracts.COLLECTION`, `Item`.
- Produces: class `WebIndex(*, client: AsyncQdrantClient, embed, collection=COLLECTION)` với:
  - `async ensure() -> None`
  - `async get(ids) -> list[Item]` (giữ thứ tự `ids`, bỏ id không có)
  - `async replace(id_space, items, now) -> int` (upsert `items` vào `id_space[:len(items)]`, xoá point còn lại trong `id_space`)
  - `async cards_near(location, exclude, limit=20) -> list[Item]`
- `embed` là object bất kỳ có `async dense(texts)` và `async sparse(texts)`, như `kb.clients.embed.EmbedClient`.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/kb/web/test_index.py
import uuid
from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient

from portal.modules.kb.web.compose import card_id, dossier_ids
from portal.modules.kb.web.contracts import Item, Source
from portal.modules.kb.web.index import WebIndex

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 29, tzinfo=UTC)
SRC = (Source("https://cafef.vn/a", "CafeF", NOW),)


class FakeEmbed:
    async def dense(self, texts):
        return [[0.01 * (i + 1)] * 1024 for i, _ in enumerate(texts)]

    async def sparse(self, texts):
        return [{"indices": [1, 2], "values": [1.0, 0.5]} for _ in texts]


@pytest.fixture
async def web_index(qdrant_url):
    client = AsyncQdrantClient(url=qdrant_url)
    idx = WebIndex(client=client, embed=FakeEmbed(), collection=f"test_web_{uuid.uuid4().hex[:8]}")
    await idx.ensure()
    await idx.ensure()
    yield idx
    await client.delete_collection(idx.collection)
    await client.close()


def _item(text, project="NPTTL", location=("Đan Phượng",)):
    return Item(text, SRC, (project,), location)


async def test_replace_ghi_de_va_xoa_muc_thua(web_index):
    ids = dossier_ids("NPTTL")
    await web_index.replace(ids, [_item("a [1]"), _item("b [1]"), _item("c [1]")], NOW)
    await web_index.replace(ids, [_item("a2 [1]"), _item("b2 [1]")], NOW)
    got = await web_index.get(ids)
    assert [i.text for i in got] == ["a2 [1]", "b2 [1]"]
    assert got[0].updated_at == NOW


async def test_cards_near_chi_lay_the_va_bo_chinh_minh(web_index):
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City")], NOW)
    await web_index.replace([card_id("NPTTL")], [_item("thẻ NPTTL [1]", "NPTTL")], NOW)
    await web_index.replace(dossier_ids("Riverside"), [_item("hồ sơ RS [1]", "Riverside")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="NPTTL")
    assert [i.projects[0] for i in got] == ["Wonder City"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/web/test_index.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.index'`.

- [ ] **Step 3: Viết `index.py`**

```python
# src/portal/modules/kb/web/index.py
from collections.abc import Sequence
from datetime import datetime

from qdrant_client import AsyncQdrantClient, models

from portal.modules.kb.index.store import DENSE_SIZE, SPARSE_NAME
from portal.modules.kb.web.compose import card_id, item_from_payload, payload_of
from portal.modules.kb.web.contracts import COLLECTION, Item

_INDEXES = (
    ("location", models.PayloadSchemaType.KEYWORD),
    ("projects", models.PayloadSchemaType.KEYWORD),
    ("published_at", models.PayloadSchemaType.DATETIME),
    ("updated_at", models.PayloadSchemaType.DATETIME),
)


class WebIndex:
    def __init__(self, *, client: AsyncQdrantClient, embed, collection: str = COLLECTION) -> None:
        self._c = client
        self._embed = embed
        self.collection = collection

    async def ensure(self) -> None:
        if not await self._c.collection_exists(self.collection):
            await self._c.create_collection(
                self.collection,
                vectors_config={"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)},
                sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
        for key, schema in _INDEXES:
            try:
                await self._c.create_payload_index(self.collection, field_name=key, field_schema=schema, wait=True)
            except Exception as exc:  # noqa: BLE001 — Qdrant không có kiểu lỗi riêng cho "đã có"
                if "already exists" not in str(exc).lower():
                    raise

    async def get(self, ids: Sequence[str]) -> list[Item]:
        points = await self._c.retrieve(self.collection, ids=list(ids), with_payload=True)
        by_id = {str(p.id): item_from_payload(p.payload or {}) for p in points}
        return [by_id[i] for i in ids if i in by_id]

    async def replace(self, id_space: Sequence[str], items: Sequence[Item], now: datetime) -> int:
        items = list(items)[: len(id_space)]
        if items:
            texts = [i.text for i in items]
            dense = await self._embed.dense(texts)
            sparse = await self._embed.sparse(texts)
            if len(dense) != len(items) or len(sparse) != len(items):
                raise ValueError(f"embed trả thiếu: {len(items)} mục, {len(dense)} dense, {len(sparse)} sparse")
            await self._c.upsert(
                self.collection,
                points=[
                    models.PointStruct(
                        id=id_space[i],
                        vector={"dense": dense[i], SPARSE_NAME: models.SparseVector(**sparse[i])},
                        payload=payload_of(item, now),
                    )
                    for i, item in enumerate(items)
                ],
                wait=True,
            )
        stale = list(id_space[len(items) :])
        if stale:
            existing = [str(p.id) for p in await self._c.retrieve(self.collection, ids=stale, with_payload=False)]
            if existing:
                await self._c.delete(
                    self.collection, points_selector=models.PointIdsList(points=existing), wait=True
                )
        return len(items)

    async def cards_near(self, location: Sequence[str], exclude: str, limit: int = 20) -> list[Item]:
        if not location:
            return []
        points, _ = await self._c.scroll(
            self.collection,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="location", match=models.MatchAny(any=list(location)))]
            ),
            limit=500,
            with_payload=True,
        )
        out: list[Item] = []
        for p in points:
            it = item_from_payload(p.payload or {})
            name = it.projects[0] if it.projects else ""
            if name and name != exclude and str(p.id) == card_id(name):
                out.append(it)
        return out[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/modules/kb/web/test_index.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 10: Gemini grounding và trần theo ngày

**Files:**
- Create: `src/portal/modules/kb/web/grounding.py`
- Test: `tests/unit/test_kb_web_grounding.py`

**Interfaces:**
- Consumes: `kb.contracts.TemporaryError`.
- Produces: class `GroundingBudget(redis=None, *, cap)` với `async take(n=1) -> bool`; class `Grounding(*, api_key, http, budget, model)` với `async search(query) -> list[str]` (trả URL gốc, bỏ link không lấy được).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_web_grounding.py
import httpx
import pytest

from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.grounding import Grounding, GroundingBudget

REDIR = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA"


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.host == "generativelanguage.googleapis.com":
        return httpx.Response(
            200,
            json={"candidates": [{"groundingMetadata": {"groundingChunks": [
                {"web": {"uri": REDIR, "title": "mytour.vn"}},
                {"web": {"uri": "https://thang.vn/x", "title": "thang.vn"}},
            ]}}]},
        )
    if str(req.url) == REDIR:
        return httpx.Response(302, headers={"location": "https://mytour.vn/bai-viet/truong-dan-phuong"})
    return httpx.Response(404)


def _g(handler, cap=10) -> Grounding:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Grounding(api_key="k", http=http, budget=GroundingBudget(cap=cap), model="gemini-2.5-flash")


async def test_tra_url_goc_tu_header_location():
    assert await _g(_handler).search("trường học Đan Phượng") == [
        "https://mytour.vn/bai-viet/truong-dan-phuong",
        "https://thang.vn/x",
    ]


async def test_het_tran_ngay_thi_khong_goi():
    g = _g(_handler, cap=1)
    assert await g.search("q1")
    assert await g.search("q2") == []


async def test_429_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _g(lambda r: httpx.Response(429)).search("q")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_kb_web_grounding.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.grounding'`.

- [ ] **Step 3: Viết `grounding.py`**

```python
# src/portal/modules/kb/web/grounding.py
import asyncio
from datetime import date

import httpx

from portal.modules.kb.contracts import TemporaryError

_API = "https://generativelanguage.googleapis.com/v1beta/models"
_REDIRECT_MARK = "grounding-api-redirect"


class GroundingBudget:
    def __init__(self, redis=None, *, cap: int) -> None:
        self._redis = redis
        self._cap = cap
        self._local = 0

    async def take(self, n: int = 1) -> bool:
        if self._redis is None:
            if self._local + n > self._cap:
                return False
            self._local += n
            return True
        key = f"kbweb:grounding:{date.today():%Y%m%d}"
        used = await self._redis.incrby(key, n)
        await self._redis.expire(key, 2 * 86400)
        return used <= self._cap


class Grounding:
    def __init__(self, *, api_key: str, http: httpx.AsyncClient, budget: GroundingBudget, model: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_WEB_GEMINI_API_KEY")
        self._key = api_key
        self._http = http
        self._budget = budget
        self._model = model

    async def search(self, query: str) -> list[str]:
        if not await self._budget.take():
            return []
        try:
            r = await self._http.post(
                f"{_API}/{self._model}:generateContent",
                headers={"x-goog-api-key": self._key},
                json={"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TemporaryError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryError(f"Gemini {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        candidates = r.json().get("candidates") or [{}]
        chunks = (candidates[0].get("groundingMetadata") or {}).get("groundingChunks") or []
        uris = [c["web"]["uri"] for c in chunks if (c.get("web") or {}).get("uri")]
        resolved = await asyncio.gather(*(self._resolve(u) for u in uris))
        out: list[str] = []
        for u in resolved:
            if u and u not in out:
                out.append(u)
        return out

    async def _resolve(self, uri: str) -> str:
        if _REDIRECT_MARK not in uri:
            return uri
        try:
            r = await self._http.get(uri, follow_redirects=False)
        except httpx.HTTPError:
            return ""
        location = r.headers.get("location", "")
        return location if location.startswith("http") else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_kb_web_grounding.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 11: Đọc dự án và tín hiệu "có người hỏi"

**Files:**
- Create: `src/portal/modules/kb/web/signal.py`
- Test: `tests/modules/kb/web/test_signal.py`

**Interfaces:**
- Consumes: `normalize.fold`, `normalize.contains_word` (Task 3). Fixture `web_tenant` (Task 4).
- Produces: dataclass `ProjectRow(id, code, name, region, address, facts, hot_words)`, `ASK_TOOLS`, `async load_projects(conn) -> list[ProjectRow]` (chỉ dự án published, bỏ `__ALL__`), `async asked_codes(conn, projects, *, days=28) -> set[str]`. Cả hai nhận `conn` đang ở trong `tenant_conn()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/kb/web/test_signal.py
import json
from datetime import UTC, datetime

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.web.signal import asked_codes, load_projects

from .conftest import NPTTL, OTHER, TENANT

pytestmark = pytest.mark.integration


async def _msg(pool, tenant, seq, *, role="assistant", content="", tool=None, args=None):
    meta = {"tool_calls": [{"function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]} if tool else {}
    async with tenant_conn(pool, tenant) as c:
        await c.execute(
            """INSERT INTO tenant_data.conversation_messages (tenant_id, session_id, seq, role, content, created_at, meta)
               VALUES ($1, 's1', $2, $3, $4, $5, $6::jsonb)""",
            tenant,
            seq,
            role,
            content,
            datetime.now(UTC),
            json.dumps(meta),
        )


async def test_load_projects_chi_published_cua_tenant(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        rows = await load_projects(c)
    assert [(r.code, r.name) for r in rows] == [("NPTTL", NPTTL)]
    assert "Đan Phượng" in rows[0].facts


async def test_khong_co_log_thi_coi_moi_du_an_la_duoc_hoi(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


async def test_nhan_tu_tham_so_tool_va_khong_lan_tenant_khac(web_tenant, api_pool, pool):
    await _msg(pool, OTHER, 0, tool="find_project", args={"name": "Noble Palace Tây Thăng Long"})
    await _msg(pool, TENANT, 0, tool="find_project", args={"name": "Vinhomes Smart City"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()
    await _msg(pool, TENANT, 1, tool="kb_search", args={"query": "hạ tầng", "project_filter": "NPTTL"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


async def test_nhan_tu_cau_cua_khach(web_tenant, api_pool, pool):
    await _msg(pool, TENANT, 0, role="user", content="cho mình hỏi về noble palace tây thăng long")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/web/test_signal.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.signal'`.

- [ ] **Step 3: Viết `signal.py`**

```python
# src/portal/modules/kb/web/signal.py
from dataclasses import dataclass

import asyncpg

from portal.modules.kb.web.normalize import contains_word, fold

ASK_TOOLS = ("find_project", "discover_projects", "search_units", "kb_search")
MIN_HOT_WORD = 5
MAX_USER_MESSAGES = 5000

_FACT_COLUMNS = (
    ("Địa chỉ", "address"),
    ("Khu vực", "region"),
    ("Chủ đầu tư", "investor"),
    ("Đơn vị phát triển", "developer"),
    ("Quy mô", "product_scale"),
    ("Tiện ích", "amenities"),
    ("Giai đoạn bán", "sale_phase"),
    ("Tổng quan", "overview"),
)


@dataclass(frozen=True, slots=True)
class ProjectRow:
    id: int
    code: str
    name: str
    region: str
    address: str
    facts: str
    hot_words: tuple[str, ...]


async def load_projects(conn: asyncpg.Connection) -> list[ProjectRow]:
    rows = await conn.fetch(
        """SELECT p.id, p.project_code, p.name, p.region, p.address, p.investor, p.developer,
                  p.product_scale, p.amenities, p.sale_phase, p.overview,
                  coalesce(array_agg(h.hot_word) FILTER (WHERE h.hot_word IS NOT NULL), '{}') AS hot_words
             FROM tenant_data.projects p
             LEFT JOIN tenant_data.project_hot_words h ON h.project_id = p.id AND h.tenant_id = p.tenant_id
            WHERE p.tenant_id = portal.current_tenant() AND p.status = 'published' AND p.project_code <> '__ALL__'
            GROUP BY p.id
            ORDER BY p.project_code"""
    )
    return [
        ProjectRow(
            id=int(r["id"]),
            code=r["project_code"],
            name=r["name"],
            region=r["region"],
            address=r["address"],
            facts="\n".join(f"{label}: {r[col]}" for label, col in _FACT_COLUMNS if r[col]),
            hot_words=tuple(r["hot_words"]),
        )
        for r in rows
    ]


def _mentioned(p: ProjectRow, hay: str) -> bool:
    needles = [p.code, p.name, *(w for w in p.hot_words if len(w) >= MIN_HOT_WORD)]
    return any(contains_word(hay, n) for n in needles if len(n) >= 3)


async def asked_codes(conn: asyncpg.Connection, projects: list[ProjectRow], *, days: int = 28) -> set[str]:
    total = await conn.fetchval(
        """SELECT count(*) FROM tenant_data.conversation_messages
            WHERE tenant_id = portal.current_tenant() AND created_at >= now() - make_interval(days => $1)""",
        days,
    )
    if not total:
        return {p.code for p in projects}
    args = await conn.fetch(
        """SELECT tc->'function'->>'arguments' AS a
             FROM tenant_data.conversation_messages m
             CROSS JOIN LATERAL jsonb_array_elements(
                 CASE WHEN jsonb_typeof(m.meta->'tool_calls') = 'array' THEN m.meta->'tool_calls' ELSE '[]'::jsonb END
             ) AS tc
            WHERE m.tenant_id = portal.current_tenant()
              AND m.created_at >= now() - make_interval(days => $1)
              AND tc->'function'->>'name' = ANY($2::text[])""",
        days,
        list(ASK_TOOLS),
    )
    said = await conn.fetch(
        """SELECT content FROM tenant_data.conversation_messages
            WHERE tenant_id = portal.current_tenant() AND role = 'user'
              AND created_at >= now() - make_interval(days => $1)
            ORDER BY created_at DESC
            LIMIT $2""",
        days,
        MAX_USER_MESSAGES,
    )
    hay = fold("\n".join([r["a"] or "" for r in args] + [r["content"] or "" for r in said]))
    return {p.code for p in projects if _mentioned(p, hay)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/web/test_signal.py tests/isolation -v`
Expected: PASS. Cổng quét tĩnh chấp nhận cả ba câu SQL vì đều có `portal.current_tenant()`.

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 12: Pipeline (crawl ngày, bản tin, làm mới dự án)

**Files:**
- Create: `src/portal/modules/kb/web/pipeline.py`
- Test: `tests/modules/kb/web/test_pipeline.py`

**Interfaces:**
- Consumes: mọi module ở Task 2–11.
- Produces:
  - dataclass `Deps(pool, cfg, discover, fetcher, llm, index, grounding)`; `open_deps()` là async context manager dựng từ env
  - `async ingest_urls(deps, urls, *, found_via) -> list[Page]`
  - `async crawl_day(deps, day) -> int`
  - `async recheck_living(deps, now) -> int`
  - `async build_digest(deps, now) -> int`
  - `async refresh_project(deps, project, mode, now) -> int`
  - `topic_counts(pages, topics) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/kb/web/test_pipeline.py
from datetime import UTC, date, datetime

import pytest

from portal.modules.kb.web import config, repo
from portal.modules.kb.web.compose import dossier_ids
from portal.modules.kb.web.contracts import MODE_NIGHTLY, MODE_WEEKLY, Item, Source, Tags
from portal.modules.kb.web.discover import Entry
from portal.modules.kb.web.fetch import Fetched
from portal.modules.kb.web.pipeline import Deps, build_digest, crawl_day, ingest_urls, refresh_project
from portal.modules.kb.web.signal import ProjectRow

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 29, 19, 0, tzinfo=UTC)
PROJ = ProjectRow(1, "NPTTL", "Noble Palace Tây Thăng Long", "Hà Nội", "xã Tân Lập, huyện Đan Phượng, Hà Nội",
                  "Địa chỉ: xã Tân Lập, huyện Đan Phượng", ())


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        return self.pages.get(url, Fetched(url, "fetch_failed"))


class FakeLlm:
    def __init__(self):
        self.asked = []

    async def tag(self, title, text):
        if "bóng đá" in text:
            return Tags(False, (), ())
        return Tags(True, ("Noble Palace Tây Thăng Long",) if "Noble" in text else (), ("huyện Đan Phượng",))

    async def ask(self, profile, text):
        self.asked.append(profile)
        return {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]}


class FakeIndex:
    def __init__(self):
        self.store = {}

    async def get(self, ids):
        return [self.store[i] for i in ids if i in self.store]

    async def replace(self, id_space, items, now):
        for i in id_space:
            self.store.pop(i, None)
        for i, it in zip(id_space, items, strict=False):
            self.store[i] = Item(it.text, it.sources, it.projects, it.location, now)
        return len(items)

    async def cards_near(self, location, exclude, limit=20):
        return []


class FakeDiscover:
    def __init__(self, entries):
        self.entries = entries

    async def day_entries(self, source, day, keywords):
        return [e for e in self.entries if source.domain in e.url]


class FakeGrounding:
    def __init__(self, urls):
        self.urls = urls
        self.queries = []

    async def search(self, q):
        self.queries.append(q)
        return self.urls


def _ok(url, text):
    return Fetched(url, "ok", "tiêu đề", text, NOW)


def _deps(web_pool, *, pages, entries=(), grounding=None):
    return Deps(
        pool=web_pool,
        cfg=config.load(),
        discover=FakeDiscover(list(entries)),
        fetcher=FakeFetcher(pages),
        llm=FakeLlm(),
        index=FakeIndex(),
        grounding=grounding,
    )


async def test_ingest_bo_url_da_co_bai_chep_lai_va_luu_dau_bai_khong_lien_quan(web_pool):
    a, b, c, d = (f"https://test.kbweb/{x}" for x in "abcd")
    deps = _deps(web_pool, pages={
        a: _ok(a, "Noble Palace có đại lộ"), b: _ok(b, "Noble Palace có đại lộ"), c: _ok(c, "tin bóng đá"),
    })
    got = await ingest_urls(deps, [a, b, c, d], found_via="sitemap")
    assert [p.url for p in got] == [a]
    assert "Đan Phượng" in got[0].location and "Tây Hà Nội" in got[0].location
    async with web_pool.acquire() as conn:
        assert await repo.known_urls(conn, [a, b, c, d]) == {a, c, d}
    await ingest_urls(deps, [a], found_via="sitemap")
    assert deps.fetcher.calls.count(a) == 1


async def test_crawl_day_danh_dau_nguon_can_trinh_duyet_khong_tai(web_pool):
    ld = "https://laodong.vn/bat-dong-san/test.kbweb-1"
    deps = _deps(web_pool, pages={}, entries=[Entry(ld, NOW)])
    await crawl_day(deps, date(2026, 9, 28))
    assert ld not in deps.fetcher.calls
    async with web_pool.acquire() as conn:
        await conn.execute("DELETE FROM public_data.web_pages WHERE url = $1", ld)


async def test_ban_tin_ghi_muc_khong_gan_du_an(web_pool):
    a = "https://test.kbweb/digest"
    deps = _deps(web_pool, pages={a: _ok(a, "giá chung cư Hà Nội tăng")})
    await ingest_urls(deps, [a], found_via="sitemap")
    assert await build_digest(deps, NOW) == 1
    (item,) = deps.index.store.values()
    assert item.projects == ()


async def test_luot_dem_khong_co_bai_moi_thi_khong_goi_llm(web_pool):
    deps = _deps(web_pool, pages={})
    assert await refresh_project(deps, PROJ, MODE_NIGHTLY, NOW) == 0
    assert deps.llm.asked == []


async def test_luot_tuan_goi_grounding_cho_chu_de_thieu_va_viet_ho_so(web_pool):
    g = "https://test.kbweb/g1"
    grounding = FakeGrounding([g])
    deps = _deps(web_pool, pages={g: _ok(g, "Noble Palace gần trường học mới")}, grounding=grounding)
    n = await refresh_project(deps, PROJ, MODE_WEEKLY, NOW)
    assert n == 1
    assert grounding.queries
    assert len(grounding.queries) <= 60
    items = await deps.index.get(dossier_ids(PROJ.name))
    assert items[0].projects == (PROJ.name,)


async def test_llm_tra_rong_thi_giu_ho_so_cu(web_pool):
    deps = _deps(web_pool, pages={})
    old = Item("cũ [1]", (Source("https://test.kbweb/old", "X", NOW),), (PROJ.name,), (), NOW)
    deps.index.store[dossier_ids(PROJ.name)[0]] = old
    a = "https://test.kbweb/moi"
    deps.fetcher.pages[a] = _ok(a, "Noble Palace tin mới")
    await ingest_urls(deps, [a], found_via="sitemap")

    async def rong(profile, text):
        return {"items": []}

    deps.llm.ask = rong
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    assert deps.index.store[dossier_ids(PROJ.name)[0]].text == "cũ [1]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/kb/web/test_pipeline.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'portal.modules.kb.web.pipeline'`.

- [ ] **Step 3: Viết `pipeline.py`**

```python
# src/portal/modules/kb/web/pipeline.py
import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from itertools import chain

import asyncpg
import httpx

from portal.modules.kb.web import repo
from portal.modules.kb.web.compose import card_id, digest_ids, dossier_ids, number_sources, parse_items
from portal.modules.kb.web.config import Topic, WebConfig
from portal.modules.kb.web.contracts import (
    DIGEST_REGION,
    FOUND_GROUNDING,
    MAX_DIGEST_ITEMS,
    MAX_DOSSIER_ITEMS,
    MODE_NIGHTLY,
    MODE_REBUILD,
    PROFILE_CARD,
    PROFILE_DIGEST,
    PROFILE_DOSSIER,
    STATUS_IRRELEVANT,
    STATUS_NEEDS_BROWSER,
    STATUS_OK,
    Item,
    Page,
)
from portal.modules.kb.web.locate import expand, levels, locate_text
from portal.modules.kb.web.normalize import canonical_url, clean_labels, content_hash, domain_of, fold
from portal.modules.kb.web.signal import ProjectRow

log = logging.getLogger(__name__)

NIGHTLY_WINDOW = timedelta(hours=48)
DIGEST_WINDOW = timedelta(hours=24)
MAX_QUERIES_PER_TOPIC = 4
MAX_QUERIES_PER_PROJECT = 60
MAX_PAGES_PER_PROJECT = 150
URLS_PER_QUERY = 5
EMPTY_STREAK_STOP = 2
MIN_NEIGHBORS = 3
MAX_NEIGHBORS = 8
LIVING_RECHECK = timedelta(days=30)


@dataclass
class Deps:
    pool: asyncpg.Pool
    cfg: WebConfig
    discover: object
    fetcher: object
    llm: object
    index: object
    grounding: object | None


@asynccontextmanager
async def open_deps() -> AsyncIterator[Deps]:
    from qdrant_client import AsyncQdrantClient
    from redis.asyncio import Redis

    from portal.core.config import get_settings
    from portal.core.db.pool import create_pool
    from portal.modules.kb import prompts
    from portal.modules.kb.clients.embed import EmbedClient
    from portal.modules.kb.settings import get_env
    from portal.modules.kb.web import config
    from portal.modules.kb.web.contracts import PROFILE_GROUNDING
    from portal.modules.kb.web.discover import Discoverer
    from portal.modules.kb.web.fetch import TIMEOUT_SEC, Fetcher
    from portal.modules.kb.web.grounding import Grounding, GroundingBudget
    from portal.modules.kb.web.index import WebIndex
    from portal.modules.kb.web.llm import WebLlm

    s, env = get_settings(), get_env()
    pool = await create_pool(s.database_url, min_size=1, max_size=4)
    http = httpx.AsyncClient(timeout=TIMEOUT_SEC)
    qdrant = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
    embed = EmbedClient(base_url=env.embed_url, token=env.santa_models_token)
    llm = WebLlm(base_url=env.web_llm_base_url, api_key=env.web_llm_api_key, concurrency=env.web_llm_concurrency)
    redis = Redis.from_url(s.redis_url) if s.redis_url else None
    grounding = None
    if env.web_gemini_api_key:
        grounding = Grounding(
            api_key=env.web_gemini_api_key,
            http=http,
            budget=GroundingBudget(redis, cap=env.web_grounding_daily_cap),
            model=prompts.get(PROFILE_GROUNDING).model,
        )
    index = WebIndex(client=qdrant, embed=embed)
    await index.ensure()
    try:
        yield Deps(
            pool=pool,
            cfg=config.load(),
            discover=Discoverer(http),
            fetcher=Fetcher(http, per_domain=env.web_fetch_per_domain, delay_sec=env.web_fetch_delay_sec),
            llm=llm,
            index=index,
            grounding=grounding,
        )
    finally:
        await llm.aclose()
        await embed.aclose()
        await qdrant.close()
        await http.aclose()
        if redis is not None:
            await redis.aclose()
        await pool.close()


async def _save_marker(deps: Deps, url: str, found_via: str, status: str) -> None:
    async with deps.pool.acquire() as c:
        await repo.save_page(
            c, url=url, source_url=url, domain=domain_of(url), title="", published_at=None, content_text=None,
            content_hash="", found_via=found_via, status=status, projects=[], location=[],
        )


async def _ingest_one(deps: Deps, url: str, found_via: str) -> Page | None:
    fetched = await deps.fetcher.fetch(url)
    if fetched.status != STATUS_OK:
        await _save_marker(deps, url, found_via, fetched.status)
        return None
    digest = content_hash(fetched.text)
    async with deps.pool.acquire() as c:
        if await repo.hash_taken(c, digest, url):
            return None
    tags = await deps.llm.tag(fetched.title, fetched.text)
    if not tags.relevant:
        await _save_marker(deps, url, found_via, STATUS_IRRELEVANT)
        return None
    location = expand(tags.location, deps.cfg)
    async with deps.pool.acquire() as c:
        await repo.save_page(
            c, url=url, source_url=url, domain=domain_of(url), title=fetched.title,
            published_at=fetched.published_at, content_text=fetched.text, content_hash=digest,
            found_via=found_via, status=STATUS_OK, projects=list(tags.projects), location=list(location),
        )
    return Page(url, domain_of(url), fetched.title, fetched.published_at, None, fetched.text, tags.projects, location)


async def ingest_urls(deps: Deps, urls: Sequence[str], *, found_via: str) -> list[Page]:
    todo: list[str] = []
    for u in urls:
        key = canonical_url(u)
        if key not in todo:
            todo.append(key)
    async with deps.pool.acquire() as c:
        known = await repo.known_urls(c, todo)
    results = await asyncio.gather(*(_ingest_one(deps, u, found_via) for u in todo if u not in known))
    return [p for p in results if p is not None]


async def crawl_day(deps: Deps, day: date) -> int:
    http_urls: list[str] = []
    for source in deps.cfg.sources:
        try:
            entries = await deps.discover.day_entries(source, day, deps.cfg.bds_keywords)
        except httpx.HTTPError as exc:
            log.warning("tìm bài %s lỗi: %s", source.domain, exc)
            continue
        if not entries:
            log.warning("nguồn %s không có bài nào ngày %s", source.domain, day)
        if source.fetch_mode == "http":
            http_urls += [e.url for e in entries]
            continue
        async with deps.pool.acquire() as c:
            known = await repo.known_urls(c, [e.url for e in entries])
        for e in entries:
            if e.url not in known:
                await _save_marker(deps, e.url, "sitemap", STATUS_NEEDS_BROWSER)
    return len(await ingest_urls(deps, http_urls, found_via="sitemap"))


async def recheck_living(deps: Deps, now: datetime) -> int:
    domains = [s.domain for s in deps.cfg.sources if s.kind == "living"]
    async with deps.pool.acquire() as c:
        due = await repo.living_due(c, domains, now - LIVING_RECHECK)
    for url in due:
        fetched = await deps.fetcher.fetch(url)
        if fetched.status != STATUS_OK:
            continue
        tags = await deps.llm.tag(fetched.title, fetched.text)
        async with deps.pool.acquire() as c:
            await repo.save_page(
                c, url=url, source_url=url, domain=domain_of(url), title=fetched.title,
                published_at=fetched.published_at, content_text=fetched.text, content_hash=content_hash(fetched.text),
                found_via="sitemap", status=STATUS_OK if tags.relevant else STATUS_IRRELEVANT,
                projects=list(tags.projects), location=list(expand(tags.location, deps.cfg)),
            )
    return len(due)


def _location_of_items(items: list[Item], pages: Sequence[Page]) -> list[Item]:
    by_url = {p.url: p.location for p in pages}
    return [replace(it, location=clean_labels(chain.from_iterable(by_url.get(s.url, ()) for s in it.sources))) for it in items]


async def build_digest(deps: Deps, now: datetime) -> int:
    async with deps.pool.acquire() as c:
        pages = await repo.pages_fetched_since(c, now - DIGEST_WINDOW)
    if not pages:
        return 0
    block, sources, _ = number_sources(pages, [], deps.cfg.names_of())
    raw = await deps.llm.ask(PROFILE_DIGEST, f"Hôm nay: {now:%d/%m/%Y}\n\nNGUỒN:\n{block}")
    items = parse_items(raw, sources, projects=(), location=(), limit=MAX_DIGEST_ITEMS)
    if not items:
        return 0
    return await deps.index.replace(digest_ids(DIGEST_REGION), _location_of_items(items, pages), now)


def _matches(page: Page, topic: Topic) -> bool:
    hay = fold(f"{page.title} {page.content_text[:3000]}")
    return any(fold(k) in hay for k in topic.keywords)


def topic_counts(pages: Sequence[Page], topics: Sequence[Topic]) -> dict[str, int]:
    return {t.code: sum(1 for p in pages if _matches(p, t)) for t in topics}


async def _fill_topics(deps: Deps, project: ProjectRow, location: Sequence[str], related: list[Page]) -> None:
    if deps.grounding is None:
        return
    counts = topic_counts(related, deps.cfg.topics)
    districts = [u.district for u in deps.cfg.units if u.district in location]
    provinces = [u.province for u in deps.cfg.units if u.province in location]
    locality = districts[0] if districts else project.region
    province = provinces[0] if provinces else project.region
    queries = pages = 0
    for topic in deps.cfg.topics:
        if counts[topic.code] >= deps.cfg.target_per_topic:
            continue
        streak = 0
        for template in topic.queries[:MAX_QUERIES_PER_TOPIC]:
            if queries >= MAX_QUERIES_PER_PROJECT or pages >= MAX_PAGES_PER_PROJECT:
                return
            urls = (await deps.grounding.search(template.format(project=project.name, locality=locality, province=province)))[
                :URLS_PER_QUERY
            ]
            queries += 1
            new = await ingest_urls(deps, urls, found_via=FOUND_GROUNDING)
            pages += len(urls)
            counts[topic.code] += sum(1 for p in new if _matches(p, topic))
            streak = 0 if new else streak + 1
            if counts[topic.code] >= deps.cfg.target_per_topic or streak >= EMPTY_STREAK_STOP:
                break


def _narrow(location: Sequence[str], cfg: WebConfig) -> list[str]:
    lv = levels(location, cfg)
    return list(chain.from_iterable(lv[:2])) if lv else []


async def _refresh_cards(deps: Deps, project: ProjectRow, location: Sequence[str], now: datetime) -> None:
    names: list[str] = []
    for level in levels(location, deps.cfg):
        async with deps.pool.acquire() as c:
            for n in await repo.names_near(c, list(level), [project.name]):
                if n not in names:
                    names.append(n)
        if len(names) >= MIN_NEIGHBORS:
            break
    for name in names[:MAX_NEIGHBORS]:
        async with deps.pool.acquire() as c:
            pages = await repo.pages_for(c, projects=[name], location=[], limit=30)
        if not pages:
            continue
        old = await deps.index.get([card_id(name)])
        block, sources, carried = number_sources(pages, old, deps.cfg.names_of())
        raw = await deps.llm.ask(
            PROFILE_CARD, f"Hôm nay: {now:%d/%m/%Y}\nDỰ ÁN: {name}\n\nTHẺ HIỆN CÓ:\n{''.join(carried)}\n\nNGUỒN:\n{block}"
        )
        card_location = clean_labels(chain.from_iterable(p.location for p in pages))
        items = parse_items(raw, sources, projects=(name,), location=card_location, limit=1)
        if items:
            await deps.index.replace([card_id(name)], items, now)


async def _neighbor_cards(deps: Deps, project: ProjectRow, location: Sequence[str]) -> list[Item]:
    found: list[Item] = []
    for level in levels(location, deps.cfg):
        for card in await deps.index.cards_near(list(level), exclude=project.name):
            if all(card.projects != f.projects for f in found):
                found.append(card)
        if len(found) >= MIN_NEIGHBORS:
            break
    return found[:MAX_NEIGHBORS]


async def refresh_project(deps: Deps, project: ProjectRow, mode: str, now: datetime) -> int:
    location = locate_text(f"{project.address} {project.region}", deps.cfg)
    ids = dossier_ids(project.name)
    old = [] if mode == MODE_REBUILD else await deps.index.get(ids)
    watermark = max((it.updated_at for it in old if it.updated_at), default=None)
    if mode == MODE_NIGHTLY:
        since = max(watermark, now - NIGHTLY_WINDOW) if watermark else now - NIGHTLY_WINDOW
    else:
        since = watermark if old else None
    narrow = _narrow(location, deps.cfg)
    async with deps.pool.acquire() as c:
        related = await repo.pages_for(c, projects=[project.name], location=narrow)
    if mode != MODE_NIGHTLY:
        if not location:
            location = clean_labels(chain.from_iterable(p.location for p in related))
            narrow = _narrow(location, deps.cfg)
        await _fill_topics(deps, project, location, related)
        await _refresh_cards(deps, project, location, now)
        async with deps.pool.acquire() as c:
            related = await repo.pages_for(c, projects=[project.name], location=narrow)
    fresh = [p for p in related if since is None or (p.fetched_at or now) > since]
    if not fresh and (mode == MODE_NIGHTLY or old):
        return 0
    cards = [] if mode == MODE_NIGHTLY else await _neighbor_cards(deps, project, location)
    block, sources, carried = number_sources(fresh, [*old, *cards], deps.cfg.names_of())
    old_texts, card_texts = carried[: len(old)], carried[len(old) :]
    prompt = (
        f"Hôm nay: {now:%d/%m/%Y}\nDỰ ÁN: {project.name}\n\n"
        f"DỮ LIỆU CHÍNH THỨC CỦA CHỦ ĐẦU TƯ (ưu tiên cao nhất):\n{project.facts or '(không có)'}\n\n"
        f"HỒ SƠ HIỆN CÓ:\n" + ("\n\n".join(old_texts) or "(chưa có)") + "\n\n"
        f"THẺ DỰ ÁN LÂN CẬN:\n" + ("\n\n".join(card_texts) or "(không có)") + f"\n\nNGUỒN:\n{block}"
    )
    raw = await deps.llm.ask(PROFILE_DOSSIER, prompt)
    items = parse_items(raw, sources, projects=(project.name,), location=location, limit=MAX_DOSSIER_ITEMS)
    if not items:
        return 0
    return await deps.index.replace(ids, items, now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/modules/kb/web/test_pipeline.py -v`
Expected: PASS (6 test).

- [ ] **Step 5: Checkpoint** — báo user tự commit.

---

### Task 13: Job, xếp việc, móc lúc publish, CLI, worker riêng

**Files:**
- Create: `src/portal/modules/kb/web/enqueue.py`, `src/portal/modules/kb/web/fanout.py`, `src/portal/modules/kb/web/jobs.py`
- Create: `src/portal/cli/kb_web_night.py`, `src/portal/cli/kb_web_worker.py`
- Modify: `src/portal/modules/kb/contracts.py` (thêm mặt tiền `dat_viec_ho_so_web`)
- Modify: `src/portal/modules/realestate/router.py` (`tao_du_an`, `_enqueue_project_change`)
- Modify: `src/portal/modules/ingest/chieu.py` (`chieu_mot`)
- Test: `tests/modules/kb/web/test_jobs.py`, `tests/unit/test_kb_web_worker_rieng.py`

**Interfaces:**
- Consumes: `signal.load_projects`, `signal.asked_codes`, `pipeline.*`, `contracts.KIND_PROJECT`, `MODES`.
- Produces:
  - `enqueue.dat_viec_ho_so_web(conn, *, tenant_id, actor, project_code, mode=MODE_INIT) -> int | None` (gọi được qua `portal.modules.kb.contracts`)
  - `fanout.queue_projects(pool, mode) -> int`
  - `jobs.handle_project(conn, payload) -> JobResult`, đăng ký kind `kbweb_project`
  - CLI `python -m portal.cli.kb_web_night [--weekly | --rebuild | --backfill FROM TO | --discover-only --day D]`
  - Worker `python -m portal.cli.kb_web_worker`

- [ ] **Step 1: Write the failing tests**

```python
# tests/modules/kb/web/test_jobs.py
import json
from types import SimpleNamespace

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import dat_viec_ho_so_web
from portal.modules.kb.web.contracts import MODE_INIT, MODE_REBUILD
from portal.modules.kb.web.fanout import queue_projects
from portal.modules.realestate import router

from .conftest import OTHER, TENANT

pytestmark = pytest.mark.integration


async def _jobs(pool, tenant):
    rows = await pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kbweb_project' ORDER BY id", tenant
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


async def test_xep_viec_va_gop_viec_trung(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        assert await dat_viec_ho_so_web(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is not None
        assert await dat_viec_ho_so_web(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is None
    assert await _jobs(pool, TENANT) == [{"project_code": "NPTTL", "mode": MODE_INIT}]


async def test_mode_sai_thi_nem(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(ValueError):
            await dat_viec_ho_so_web(c, tenant_id=TENANT, actor="t", project_code="NPTTL", mode="x")


async def test_fanout_dung_lai_moi_du_an_cho_tung_tenant(web_tenant, api_pool, pool):
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])
    assert await queue_projects(api_pool, MODE_REBUILD) >= 2
    assert await _jobs(pool, TENANT) == [{"project_code": "NPTTL", "mode": MODE_REBUILD}]
    assert await _jobs(pool, OTHER) == [{"project_code": "NPTTL", "mode": MODE_REBUILD}]


async def test_doi_sang_published_o_realestate_thi_xep_viec(web_tenant, api_pool, pool):
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1", TENANT)
    p = SimpleNamespace(tenant_id=TENANT, user_id="u_seed_test")
    async with tenant_conn(api_pool, TENANT) as c:
        hang = await c.fetchrow(
            "SELECT * FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = 'NPTTL'"
        )
        fake = dict(hang) | {"status": "draft"}
        await router._enqueue_project_change(c, p, hang=fake, payload={"status": "published"}, project_code="NPTTL")
    assert {"project_code": "NPTTL", "mode": MODE_INIT} in await _jobs(pool, TENANT)
```

```python
# tests/unit/test_kb_web_worker_rieng.py
"""Worker chính không được nhặt job kb/web; worker riêng chỉ nhặt đúng loại đó."""

import subprocess
import sys

_CHINH = """
from portal.worker.__main__ import load_handlers
load_handlers()
from portal.core import jobs
raise SystemExit(1 if "kbweb_project" in jobs._HANDLERS else 0)
"""

_RIENG = """
import portal.cli.kb_web_worker  # noqa: F401
from portal.core import jobs
raise SystemExit(0 if set(jobs._HANDLERS) == {"kbweb_project"} else 1)
"""


def _chay(code: str) -> int:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, check=False).returncode


def test_worker_chinh_khong_dang_ky_job_web():
    assert _chay(_CHINH) == 0


def test_worker_rieng_chi_dang_ky_job_web():
    assert _chay(_RIENG) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/kb/web/test_jobs.py tests/unit/test_kb_web_worker_rieng.py -v`
Expected: FAIL với `ImportError: cannot import name 'dat_viec_ho_so_web'`, cùng `ModuleNotFoundError: portal.cli.kb_web_worker`.

- [ ] **Step 3: Viết `enqueue.py`**

```python
# src/portal/modules/kb/web/enqueue.py
import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.web.contracts import KIND_PROJECT, MODE_INIT, MODES

_QUEUED = """SELECT 1 FROM control.jobs
              WHERE tenant_id = portal.current_tenant() AND kind = $1 AND state = 'queued'
                AND payload->>'project_code' = $2 AND payload->>'mode' = $3
              LIMIT 1"""


async def dat_viec_ho_so_web(
    conn: asyncpg.Connection, *, tenant_id: str, actor: str, project_code: str, mode: str = MODE_INIT
) -> int | None:
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ")
    if await conn.fetchval(_QUEUED, KIND_PROJECT, project_code, mode):
        return None
    return await enqueue(
        conn, tenant_id=tenant_id, kind=KIND_PROJECT, actor=actor, payload={"project_code": project_code, "mode": mode}
    )
```

- [ ] **Step 4: Thêm mặt tiền vào `src/portal/modules/kb/contracts.py`**

Ngay dưới dòng `_TEARDOWN_FACADE = frozenset({"xoa_kho_cua_workspace"})`:

```python
_WEB_FACADE = frozenset({"dat_viec_ho_so_web"})
```

Trong `def __getattr__(name: str):`, thêm nhánh này trước dòng `raise AttributeError(...)`:

```python
    if name in _WEB_FACADE:
        from portal.modules.kb.web import enqueue as _web

        return getattr(_web, name)
```

- [ ] **Step 5: Viết `fanout.py` và `jobs.py`**

```python
# src/portal/modules/kb/web/fanout.py
import asyncpg

from portal.core.db.session import tenant_conn
from portal.modules.kb.web.contracts import MODE_REBUILD
from portal.modules.kb.web.enqueue import dat_viec_ho_so_web
from portal.modules.kb.web.signal import asked_codes, load_projects


async def queue_projects(pool: asyncpg.Pool, mode: str) -> int:
    async with pool.acquire() as conn:
        tenants = await conn.fetch("SELECT id FROM control.tenants WHERE lifecycle = 'active' ORDER BY id")
    queued = 0
    for row in tenants:
        async with tenant_conn(pool, row["id"]) as conn:
            projects = await load_projects(conn)
            codes = {p.code for p in projects} if mode == MODE_REBUILD else await asked_codes(conn, projects)
            for code in sorted(codes):
                if await dat_viec_ho_so_web(conn, tenant_id=row["id"], actor="cron", project_code=code, mode=mode):
                    queued += 1
    return queued
```

```python
# src/portal/modules/kb/web/jobs.py
"""Job kb/web. CHỈ container crawl import file này (portal.cli.kb_web_worker).

kb/jobs.py cố ý không import nó, nên worker chính không bao giờ nhặt kind kbweb_project.
"""

from datetime import UTC, datetime

import asyncpg

from portal.core.jobs import JobResult, register
from portal.modules.kb.web import pipeline
from portal.modules.kb.web.contracts import KIND_PROJECT, MODE_INIT
from portal.modules.kb.web.signal import load_projects


async def handle_project(conn: asyncpg.Connection, payload: dict) -> JobResult:
    code = str(payload.get("project_code") or "")
    mode = str(payload.get("mode") or MODE_INIT)
    project = next((p for p in await load_projects(conn) if p.code == code), None)
    if project is None:
        return JobResult(0, f"bỏ qua {code}: không có hoặc chưa published")
    async with pipeline.open_deps() as deps:
        n = await pipeline.refresh_project(deps, project, mode, datetime.now(UTC))
    return JobResult(count=n, message=f"{code} {mode}: {n} mục")


register(KIND_PROJECT, handle_project, retries=2, max_concurrency=2)
```

- [ ] **Step 6: Viết hai CLI**

```python
# src/portal/cli/kb_web_worker.py
"""Worker riêng của container crawl: chỉ chạy job kb/web.

    python -m portal.cli.kb_web_worker
"""

import asyncio
import logging

import portal.modules.kb.web.jobs  # noqa: F401 — đăng ký kbweb_project
from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.jobs import thu_hoi_viec_ket
from portal.worker.__main__ import reclaim_loop, run_lane

LANES = 2


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pool = await create_pool(get_settings().database_url, max_size=LANES + 2)
    try:
        await thu_hoi_viec_ket(pool)
        await asyncio.gather(reclaim_loop(pool), *[run_lane(pool) for _ in range(LANES)])
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

```python
# src/portal/cli/kb_web_night.py
"""Chuỗi đêm của kb/web.

    10 1 * * *   python -m portal.cli.kb_web_night              crawl hôm qua → bản tin → xếp lượt đêm
    0 4 * * 0    python -m portal.cli.kb_web_night --weekly     xếp lượt sâu
    0 5 1 */3 *  python -m portal.cli.kb_web_night --rebuild    xếp lượt dựng lại
    python -m portal.cli.kb_web_night --backfill 2024-10-01 2026-09-28
    python -m portal.cli.kb_web_night --discover-only --day 2026-09-29
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta

from portal.modules.kb.web import pipeline, repo
from portal.modules.kb.web.contracts import MODE_NIGHTLY, MODE_REBUILD, MODE_WEEKLY
from portal.modules.kb.web.discover import VN
from portal.modules.kb.web.fanout import queue_projects


def _args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="kb_web_night")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--weekly", action="store_true")
    g.add_argument("--rebuild", action="store_true")
    g.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"), type=date.fromisoformat)
    g.add_argument("--discover-only", action="store_true")
    p.add_argument("--day", type=date.fromisoformat)
    return p.parse_args(argv)


async def main_async(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    a = _args(argv)
    now = datetime.now(UTC)
    yesterday = a.day or (now.astimezone(VN).date() - timedelta(days=1))
    async with pipeline.open_deps() as deps:
        if a.discover_only:
            for s in deps.cfg.sources:
                entries = await deps.discover.day_entries(s, yesterday, deps.cfg.bds_keywords)
                print(f"{s.domain}: {len(entries)} bài ngày {yesterday}")
            return 0
        if a.backfill:
            day, end = a.backfill
            while day <= end:
                print(f"{day}: {await pipeline.crawl_day(deps, day)} bài")
                day += timedelta(days=1)
            return 0
        mode = MODE_WEEKLY if a.weekly else MODE_REBUILD if a.rebuild else MODE_NIGHTLY
        if mode == MODE_NIGHTLY:
            print(f"crawl {yesterday}: {await pipeline.crawl_day(deps, yesterday)} bài mới")
            print(f"kiểm lại trang living: {await pipeline.recheck_living(deps, now)}")
            print(f"bản tin: {await pipeline.build_digest(deps, now)} mục")
            async with deps.pool.acquire() as c:
                print(f"dọn: {await repo.purge(c, now=now)} hàng")
        print(f"xếp {await queue_projects(deps.pool, mode)} việc {mode}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async(sys.argv[1:])))


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Móc vào realestate**

Trong `src/portal/modules/realestate/router.py`, thêm `dat_viec_ho_so_web` vào khối `from portal.modules.kb.contracts import (...)` (dòng 54).

Trong `tao_du_an`, ngay sau `await _enqueue_thumb(conn, p, ids=new_media_ids, project_code=project_code)`:

```python
        if tao["status"] == "published":
            await dat_viec_ho_so_web(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
```

Trong `_enqueue_project_change`, thay khối `if _status_changed(hang, payload):` bằng:

```python
    if _status_changed(hang, payload):
        await dat_viec_doi_co(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
        if payload.get("status") == "published":
            await dat_viec_ho_so_web(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
```

- [ ] **Step 8: Móc vào ingest**

Trong `src/portal/modules/ingest/chieu.py`, thêm `dat_viec_ho_so_web` vào khối `from portal.modules.kb.contracts import (...)` (dòng 32). Trong `chieu_mot`, thay:

```python
    if entity == "project":
        await _sync_tour_360(conn, tenant_id, external_id=external_id)
```

bằng:

```python
    if entity == "project":
        await _sync_tour_360(conn, tenant_id, external_id=external_id)
        if cot.get("status") == "published" and (hien_trang is None or hien_trang["status"] != "published"):
            await dat_viec_ho_so_web(conn, tenant_id=tenant_id, actor="ingest", project_code=cot["project_code"])
```

Kiểm trường `status` có trong hợp đồng dự án của cổng nạp: `grep -n '"status"' src/portal/modules/ingest/hop_dong.py`. Nếu không có, `cot.get("status")` luôn là `None` và nhánh này không bao giờ chạy. Khi đó báo lại user trước khi đi tiếp.

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/modules/kb/web/test_jobs.py tests/unit/test_kb_web_worker_rieng.py tests/test_module_boundaries.py tests/isolation tests/modules/realestate tests/modules/ingest -v`
Expected: PASS.

- [ ] **Step 10: Chạy thử tìm bài trên dữ liệu thật** (chỉ đọc, không gọi LLM)

Run: `uv run python -m portal.cli.kb_web_night --discover-only --day 2026-09-29`
Expected: mỗi domain một dòng `<domain>: N bài ngày 2026-09-29`. Domain nào ra 0 thì sửa `child_hint`, `news_sitemaps` hoặc `category_paths` của nó trong `data/sources.yaml` rồi chạy lại. Ghi lại kết quả cuối cùng để báo user.

- [ ] **Step 11: Checkpoint** — báo user tự commit.

---

### Task 14: Deploy — vai container, timer, env

**Files:**
- Modify: `deploy/entrypoint.sh`
- Modify: `docker-compose.dev.yml`, `docker-compose.local.yml`
- Create: `deploy/odyssey-portal-crawl.env.example`
- Create: `deploy/systemd/odyssey-kb-web-{night,weekly,quarterly}@.{service,timer}` (6 file)
- Modify: `deploy/systemd/README.md`

- [ ] **Step 1: Thêm hai vai vào `deploy/entrypoint.sh`** (trước nhánh `*)`)

```sh
  crawl-worker)
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'crawl-worker' KHÔNG được nhận MIGRATOR_URL."
    [ -n "${DATABASE_URL:-}" ] || chet "vai 'crawl-worker' cần DATABASE_URL (DSN của role portal_api)."
    exec python -m portal.cli.kb_web_worker
    ;;

  crawl)
    [ -z "${MIGRATOR_URL:-}" ] || chet "vai 'crawl' KHÔNG được nhận MIGRATOR_URL."
    [ -n "${DATABASE_URL:-}" ] || chet "vai 'crawl' cần DATABASE_URL (DSN của role portal_api)."
    shift
    exec python -m portal.cli.kb_web_night "$@"
    ;;
```

Sửa thông báo của nhánh `*)` để liệt kê thêm `'crawl'` và `'crawl-worker'`.

- [ ] **Step 2: Kiểm cú pháp và test sẵn có của entrypoint**

Run: `sh -n deploy/entrypoint.sh && grep -rln "entrypoint" tests`
Expected: `sh -n` không in gì. Nếu grep ra file test nào liệt kê các vai, thêm `crawl` và `crawl-worker` vào danh sách trong test đó rồi chạy lại nó.

- [ ] **Step 3: Service trong `docker-compose.dev.yml`** (cạnh service `dinh-gia`)

```yaml
  crawl-worker:
    image: 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-backend:${IMAGE_TAG:-dev-latest}
    command: ["crawl-worker"]
    env_file:
      - deploy/odyssey-portal-crawl.env
    cpus: "1.0"
    mem_limit: 1g
    healthcheck:
      disable: true
    restart: unless-stopped

  crawl:
    profiles: ["crawl"]
    image: 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-backend:${IMAGE_TAG:-dev-latest}
    command: ["crawl"]
    env_file:
      - deploy/odyssey-portal-crawl.env
    cpus: "1.0"
    mem_limit: 1g
    restart: "no"
```

- [ ] **Step 4: Service trong `docker-compose.local.yml`** (cạnh service `worker`, dùng cùng khối `environment` của `worker` và thêm các biến `KB_WEB_*`)

```yaml
  crawl-worker:
    profiles: ["app"]
    build: .
    command: ["crawl-worker"]
    environment:
      DATABASE_URL: postgresql://${PORTAL_API_DB_USER:-portal_api}:${PORTAL_API_DB_PASSWORD:-apidev}@postgres:5432/${PORTAL_PG_DB:-portal}
      REDIS_URL: redis://:${PORTAL_REDIS_PASSWORD:-}@redis:6379/${PORTAL_REDIS_DB:-0}
      QDRANT_URL: http://qdrant:6333
      QDRANT_API_KEY: ${QDRANT_API_KEY:-}
      KB_EMBED_URL: ${KB_EMBED_URL:-}
      KB_SANTA_MODELS_TOKEN: ${KB_SANTA_MODELS_TOKEN:-}
      KB_WEB_LLM_API_KEY: ${KB_WEB_LLM_API_KEY:-}
      KB_WEB_GEMINI_API_KEY: ${KB_WEB_GEMINI_API_KEY:-}
      KB_WEB_GROUNDING_DAILY_CAP: ${KB_WEB_GROUNDING_DAILY_CAP:-1200}
    cpus: "1.0"
    mem_limit: 1g
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
```

Trước khi thêm, đối chiếu dòng `REDIS_URL` với cách service `backend` trong cùng file ghép URL Redis, và chép đúng khuôn đó.

- [ ] **Step 5: `deploy/odyssey-portal-crawl.env.example`**

```sh
# Env của container crawl và crawl-worker. KHÔNG khai MIGRATOR_URL: entrypoint từ chối.
DATABASE_URL=postgresql://portal_api:<mật khẩu>@<host>:5432/portal
REDIS_URL=redis://:<mật khẩu>@<host>:6379/0
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
KB_EMBED_URL=http://embed:8013
KB_SANTA_MODELS_TOKEN=
# Key DashScope RIÊNG cho crawl, không dùng chung key của agent (giới hạn tốc độ tính theo tài khoản).
KB_WEB_LLM_API_KEY=
# Key Gemini thuộc Google project RIÊNG, không tranh quota miễn phí với phần khác.
KB_WEB_GEMINI_API_KEY=
KB_WEB_GROUNDING_DAILY_CAP=1200
```

- [ ] **Step 6: Unit systemd**

Mỗi lượt một cặp service + timer, cùng khuôn với `odyssey-dinh-gia-nguoi@`:

```ini
# deploy/systemd/odyssey-kb-web-night@.service
[Unit]
Description=Odyssey — kb/web chuỗi đêm
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=%f
ExecStart=/usr/bin/docker compose -f docker-compose.dev.yml run --rm crawl
TimeoutStartSec=3h
```

```ini
# deploy/systemd/odyssey-kb-web-night@.timer
[Unit]
Description=Nhịp hằng đêm — kb/web

[Timer]
OnCalendar=*-*-* 01:10:00
Persistent=true
RandomizedDelaySec=5min
Unit=odyssey-kb-web-night@%i.service

[Install]
WantedBy=timers.target
```

Lặp lại đúng khuôn cho `odyssey-kb-web-weekly@.{service,timer}` (`ExecStart=... run --rm crawl --weekly`, `OnCalendar=Sun *-*-* 04:00:00`) và `odyssey-kb-web-quarterly@.{service,timer}` (`ExecStart=... run --rm crawl --rebuild`, `OnCalendar=*-01,04,07,10-01 05:00:00`).

- [ ] **Step 7: Cập nhật `deploy/systemd/README.md`**

Thêm một mục "kb/web" gồm ba timer, lệnh cài (cùng khuôn `dinh-gia`: `ĐƯỜNG=$(systemd-escape -p "$PWD")`, rồi copy file, `daemon-reload`, `enable --now odyssey-kb-web-night@$ĐƯỜNG.timer`, tương tự cho weekly và quarterly), và ghi chú rằng `crawl-worker` là service chạy liên tục (`docker compose up -d crawl-worker`).

- [ ] **Step 8: Kiểm compose**

Run: `docker compose -f docker-compose.dev.yml --profile crawl config --quiet && docker compose -f docker-compose.local.yml --profile app config --quiet`
Expected: không in lỗi.

- [ ] **Step 9: Checkpoint** — báo user tự commit.

---

### Task 15: Hợp đồng payload, cập nhật spec, kiểm toàn bộ

**Files:**
- Create: `docs/contracts/public-web.md`
- Modify: `docs/superpowers/specs/2026-09-29-public-data-crawl-design.md`

- [ ] **Step 1: Viết `docs/contracts/public-web.md`**

````markdown
# Collection Qdrant `public_web` — hợp đồng cho bên đọc

Ai ghi: gói `kb/web` của portal (container crawl). Ai đọc: agent (`kb_search`), bên làm kênh Sale.
Dữ liệu công khai, dùng chung mọi tenant. Chép tay sang repo `odyssey-agent`.

## Vector

- `dense`: 1024 chiều, cosine, cùng embed service với `<tenant>_documents`.
- `bm25`: sparse, modifier IDF.

## Payload (đúng 6 khoá)

| Khoá | Kiểu | Nghĩa |
|---|---|---|
| `text` | string | Một mục đủ ý về một đối tượng, có số nguồn `[n]` trỏ vào `sources` (đếm từ 1) |
| `location` | keyword[] | Địa danh nhiều cấp: tỉnh, vùng tự định nghĩa, huyện cũ, xã mới |
| `projects` | keyword[] | Tên dự án mục này nói về. Rỗng nghĩa là tin trong bản tin thị trường |
| `sources` | object[] | `{url, name, published_at}` theo đúng thứ tự `[1]`, `[2]`, … |
| `published_at` | datetime | Ngày đăng của nguồn mới nhất |
| `updated_at` | datetime | Lúc mục được ghi |

## Ba loại nội dung (phân biệt bằng id, không có khoá loại)

| Loại | Id | `projects` |
|---|---|---|
| Mục hồ sơ dự án | `uuid5(NAMESPACE_URL, "kbweb:dossier:<tên dự án>:<i>")`, i < 100 | `[tên dự án]` |
| Thẻ dự án lân cận | `uuid5(NAMESPACE_URL, "kbweb:card:<tên dự án>")` | `[tên dự án]` |
| Tin trong bản tin | `uuid5(NAMESPACE_URL, "kbweb:digest:toan_quoc:<i>")`, i < 30 | `[]` |

## Cách đọc gợi ý

- Hỏi về một dự án: lọc `projects` chứa tên dự án (tên thương mại, không phải mã).
- Bản tin hôm nay: `projects` rỗng, `updated_at` từ 0h hôm nay.
- Luôn đặt kết quả của `public_web` SAU tài liệu của đối tác, và nói rõ là nguồn bên ngoài.

## Độ tươi

Chuỗi đêm chạy khoảng 1h sáng; hồ sơ trễ tối đa khoảng một ngày; lượt sâu chạy Chủ nhật; dựng lại mỗi quý.
````

- [ ] **Step 2: Cập nhật spec cho khớp thi công**

Trong `docs/superpowers/specs/2026-09-29-public-data-crawl-design.md`:
- Mục 4 (bước 2 của chuỗi đêm): đổi thành "lọc kho theo 48 giờ, không gọi Gemini". Thêm câu: Gemini chỉ chạy ở lượt tuần, lượt dựng ban đầu và lượt dựng lại, với trần `KB_WEB_GROUNDING_DAILY_CAP` (mặc định 1.200) vì mức miễn phí của Gemini 2.5 Flash grounding là 1.500 lượt/ngày.
- Mục 4: ghi rõ bước 1 và bước 3 chạy trong CLI `kb_web_night` chứ không phải job, vì `control.jobs.tenant_id` bắt buộc; chỉ phần theo dự án là job `kbweb_project` do worker `crawl-worker` chạy.
- Mục 5.1: đổi tên cột sang tiếng Anh cho khớp migration (`url`, `source_url`, `status` với các giá trị `ok|irrelevant|fetch_failed|needs_browser`).
- Mục 8: bỏ ý sửa `qdrant_jwt.py`. Ghi lại lý do: agent hiện đọc Qdrant bằng key trong env, không dùng token do portal phát; token và tên collection (`kb_<tenant>` so với `<tenant>_documents`) đang lệch từ trước, xem `enrollment/ha_tang.py`.
- Mục 3.3: ghi tầng 2 (trình duyệt) chuyển sang plan C; trong đợt này domain `browser` chỉ được lưu dấu `needs_browser`.

- [ ] **Step 3: Chạy toàn bộ cổng**

Run: `make check`
Expected: lint sạch; test xanh, trừ những test đã đỏ sẵn trên `develop` trước khi bắt đầu. Ghi lại danh sách đỏ và so với lượt chạy baseline; nếu có test đỏ mới thì sửa trước khi báo xong.

- [ ] **Step 4: Chạy thử đầu cuối trên dev** (tốn phí LLM thật nên hỏi user trước khi chạy)

Run: `uv run python -m portal.cli.kb_web_night --day 2026-09-29`
Expected: in số bài mới, số mục bản tin, số việc đã xếp. Sau đó chạy `uv run python -m portal.cli.kb_web_worker` một lúc cho tới khi các job `kbweb_project` xong, rồi kiểm collection `public_web` có point đủ 6 khoá.

- [ ] **Step 5: Báo user các dòng cần ghi vào CLAUDE.md** (không tự sửa CLAUDE.md)

Soạn sẵn cho user: một dòng Change Log (gói `kb/web`, schema `public_data`, collection `public_web`, vai `crawl`/`crawl-worker`, migration `0969`), và một gotcha: "kb/jobs.py không được import kb/web/jobs.py; cổng `tests/unit/test_kb_web_worker_rieng.py`".

- [ ] **Step 6: Checkpoint** — báo user tự commit.
