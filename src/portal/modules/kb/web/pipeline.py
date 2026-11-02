"""Nối các bước của gói kb/web: crawl ngày, kiểm lại trang living, bản tin, làm mới hồ sơ dự án.

Chính sách lỗi: `TemporaryError` của LLM luôn lan ra để job thử lại; 429/5xx của grounding chỉ
dừng grounding lượt đó; trả lời LLM hỏng/bị cắt khi viết thì giữ bản cũ; lỗi tải từng trang được
ghi thành trạng thái rồi bỏ qua; một nguồn hỏng không làm hỏng cả ngày crawl.
"""

import asyncio
import logging
import re
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import chain, groupby
from typing import Any

import asyncpg
import httpx
from qdrant_client import AsyncQdrantClient

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.core.redis import create_redis
from portal.core.ten_tai_nguyen import ten_kho_web
from portal.modules.kb import prompts
from portal.modules.kb import settings as kb_settings
from portal.modules.kb.clients.embed import EmbedClient
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.settings import get_env
from portal.modules.kb.web import config, fanout, repo
from portal.modules.kb.web.browser import BrowserBudget, BrowserFetcher, TieredFetcher
from portal.modules.kb.web.compose import (
    MAX_CARD_LOCATION,
    MAX_SOURCE_CHARS,
    card_id,
    card_location,
    carry_dropped,
    digest_ids,
    dossier_ids,
    heading_of,
    is_near_item,
    merge_same_heading,
    near_id,
    near_item,
    number_sources,
    parse_items,
    split_near,
    with_near,
    without_negative,
)
from portal.modules.kb.web.config import SourceSite, Topic, WebConfig
from portal.modules.kb.web.contracts import (
    DIGEST_REGION,
    FOUND_GROUNDING,
    FOUND_RSS,
    FOUND_SITEMAP,
    MAX_DIGEST_ITEMS,
    MAX_DOSSIER_ITEMS,
    MODE_INIT,
    MODE_NIGHTLY,
    MODE_REBUILD,
    MODES,
    PROFILE_CARD,
    PROFILE_DIGEST,
    PROFILE_DOSSIER,
    PROFILE_GROUNDING,
    STATUS_IRRELEVANT,
    STATUS_OK,
    Item,
    Page,
)
from portal.modules.kb.web.discover import VN, Discoverer
from portal.modules.kb.web.fetch import Fetcher
from portal.modules.kb.web.grounding import (
    Grounding,
    GroundingBudget,
    GroundingUnreachable,
    TemporaryGroundingError,
)
from portal.modules.kb.web.index import WebIndex
from portal.modules.kb.web.llm import TruncatedLlmError, WebLlm
from portal.modules.kb.web.locate import (
    address_parts,
    levels,
    location_text,
    match_labels,
    old_names,
    place_labels,
)
from portal.modules.kb.web.normalize import (
    alias_of,
    canonical_url,
    contains_word,
    content_hash,
    display_project,
    domain_of,
    fold,
    is_non_project,
    mentions_project,
    project_matches,
    project_names,
    same_project,
    tag_projects,
    twin_names,
)
from portal.modules.kb.web.signal import ProjectRow

log = logging.getLogger(__name__)

NIGHTLY_WINDOW = timedelta(hours=48)
LIVING_RECHECK = timedelta(days=30)
MAX_QUERIES_PER_TOPIC = 2
MAX_QUERIES_PER_PROJECT = 60
MAX_PAGES_PER_PROJECT = 150
URLS_PER_QUERY = 5
EMPTY_STREAK_STOP = 2
MIN_NEIGHBORS = 3
MAX_NEIGHBORS = 8
MAX_PROMPT_PAGES = 40
MAX_PROMPT_CHARS = 120_000
MAX_BUILD_PASSES = 5
MAX_CARD_CANDIDATES = 5
BUILD_PAGES = 200
FRESH_DAYS = 730
"""Dựng hồ sơ ưu tiên bài đăng trong `FRESH_DAYS`; chủ đề còn thiếu bài thì lùi dần về bài cũ hơn."""
NIGHTLY_MIN_AREA_PAGES = 5
MAX_DIGEST_LOCATION = 5
MIN_SHARED_PAGES = 2
_OLDEST = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Refreshed:
    """`kept_old` khác rỗng = lượt viết dừng vì trả lời LLM hỏng/bị cắt, hồ sơ cũ được giữ."""

    count: int
    kept_old: str = ""


class _KeptOld(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Deps:
    """Mọi thứ một lượt việc của MỘT tenant cần. `cfg`/`index`/`grounding` là của tenant đó;
    `pool`/`discover`/`fetcher`/`llm` dùng chung tiến trình. Mọi câu SQL đi qua `conn()`."""

    pool: asyncpg.Pool
    tenant: str
    cfg: WebConfig
    discover: Any
    fetcher: Any
    llm: Any
    index: Any
    grounding: Any | None

    def conn(self):
        return tenant_conn(self.pool, self.tenant)


@dataclass(frozen=True, slots=True)
class Limits:
    grounding_monthly: int = 1000
    browser_daily: int = 300
    asked_days: int = 28


async def load_limits(conn: asyncpg.Connection) -> Limits:
    r = await conn.fetchrow(
        """SELECT grounding_monthly, browser_daily, asked_days FROM tenant_data.kbweb_limits
            WHERE tenant_id = portal.current_tenant()"""
    )
    return Limits(**dict(r)) if r else Limits()


@dataclass
class Runtime:
    """Tài nguyên mở một lần cho cả tiến trình; `for_tenant()` dựng `Deps` theo tenant (cấu hình đọc
    lại từ DB mỗi lần gọi — mỗi job là một lượt, tenant vừa sửa nguồn thì lượt sau thấy ngay)."""

    pool: asyncpg.Pool
    http: httpx.AsyncClient
    qdrant: AsyncQdrantClient
    embed: Any
    llm: Any
    discover: Any
    fetcher: Any
    redis: Any | None
    gemini_api_key: str
    grounding_daily_cap: int
    browser: BrowserFetcher | None = None
    _ensured: set[str] = field(default_factory=set)

    async def for_tenant(self, tenant: str) -> Deps:
        async with tenant_conn(self.pool, tenant) as c:
            cfg = await config.load_for_tenant(c)
            limits = await load_limits(c)
        index = WebIndex(client=self.qdrant, embed=self.embed, collection=ten_kho_web(tenant))
        if tenant not in self._ensured:
            await index.ensure()
            self._ensured.add(tenant)
        grounding = None
        if self.gemini_api_key:
            budget = GroundingBudget(
                self.redis, cap=self.grounding_daily_cap, tenant=tenant, monthly_cap=limits.grounding_monthly
            )
            grounding = Grounding(
                api_key=self.gemini_api_key, http=self.http, budget=budget, model=prompts.get(PROFILE_GROUNDING).model
            )
        fetcher = TieredFetcher(
            self.fetcher, self.browser, BrowserBudget(self.redis, tenant=tenant, cap=limits.browser_daily)
        )
        return Deps(
            pool=self.pool,
            tenant=tenant,
            cfg=cfg,
            discover=self.discover,
            fetcher=fetcher,
            llm=self.llm,
            index=index,
            grounding=grounding,
        )


@asynccontextmanager
async def open_deps() -> AsyncIterator[Runtime]:
    s, env = get_settings(), get_env()
    async with AsyncExitStack() as stack:
        pool = await create_pool(s.database_url, min_size=1, max_size=4)
        stack.push_async_callback(pool.close)
        # timeout mặc định dài cho Gemini/sitemap lớn; Fetcher tự đặt timeout ngắn cho từng trang
        http = httpx.AsyncClient(timeout=kb_settings.HTTP_TIMEOUT_SEC)
        stack.push_async_callback(http.aclose)
        qdrant = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
        stack.push_async_callback(qdrant.close)
        embed = EmbedClient(base_url=env.embed_url, token=env.santa_models_token)
        stack.push_async_callback(embed.aclose)
        llm = WebLlm(base_url=env.vlm_base_url, api_key=env.vlm_api_key, concurrency=env.web_llm_concurrency)
        stack.push_async_callback(llm.aclose)
        redis = None
        if s.redis_url:
            redis = create_redis(s.redis_url)
            stack.push_async_callback(redis.aclose)
        browser = None
        if env.web_browser_enabled:
            browser = BrowserFetcher()
            stack.push_async_callback(browser.aclose)
        yield Runtime(
            pool=pool,
            http=http,
            qdrant=qdrant,
            embed=embed,
            llm=llm,
            discover=Discoverer(http),
            fetcher=Fetcher(http, per_domain=env.web_fetch_per_domain, delay_sec=env.web_fetch_delay_sec),
            redis=redis,
            gemini_api_key=env.gemini_api_key,
            grounding_daily_cap=env.web_grounding_daily_cap,
            browser=browser,
        )


# ─── nạp trang ───────────────────────────────────────────────────────────────


def _raise_first(results: Sequence[object]) -> None:
    """Lỗi không tạm thời (bug) được ưu tiên nêu ra trước lỗi tạm thời."""
    errors = [r for r in results if isinstance(r, BaseException)]
    for e in errors:
        if not isinstance(e, TemporaryError):
            raise e
    if errors:
        raise errors[0]


async def _save_marker(deps: Deps, url: str, found_via: str, status: str) -> None:
    async with deps.conn() as c:
        await repo.save_page(
            c,
            url=url,
            source_url=url,
            domain=domain_of(url),
            title="",
            published_at=None,
            content_text=None,
            content_hash="",
            found_via=found_via,
            status=status,
            projects=[],
            location=[],
        )


def _pick_published(own: datetime | None, listed: datetime | None) -> datetime | None:
    """trafilatura thường chỉ ra NGÀY (00:00 giờ VN); cùng ngày thì giờ chính xác của sitemap/RSS thắng."""
    if own is None or listed is None:
        return own or listed
    local = own.astimezone(VN)
    if local.time() == time(0) and local.date() == listed.astimezone(VN).date():
        return listed
    return own


async def _ingest_one(
    deps: Deps, url: str, found_via: str, claimed: set[str], when: datetime | None = None, mode: str = "http"
) -> Page | None:
    fetched = await deps.fetcher.fetch(url, mode=mode)
    if fetched.status != STATUS_OK:
        await _save_marker(deps, url, found_via, fetched.status)
        return None
    published = _pick_published(fetched.published_at, when)
    digest = content_hash(fetched.text)
    # `claimed` chặn hai bản chép cùng lô chạy song song: cả hai đều qua `hash_taken` trước khi bên nào kịp lưu
    if digest in claimed:
        return None
    claimed.add(digest)
    async with deps.conn() as c:
        if await repo.hash_taken(c, digest, url):
            return None
    try:
        tags = await deps.llm.tag(fetched.title, fetched.text)
    except TemporaryError:
        claimed.discard(digest)
        raise
    except (ValueError, httpx.HTTPStatusError) as exc:
        # không ghi dấu: lượt sau tải và gắn nhãn lại
        claimed.discard(digest)
        log.warning("gắn nhãn %s lỗi, bỏ qua: %s", url, exc)
        return None
    if not tags.relevant:
        await _save_marker(deps, url, found_via, STATUS_IRRELEVANT)
        return None
    domain = domain_of(url)
    projects = tag_projects(tags.projects)
    location = place_labels(tags.location)
    async with deps.conn() as c:
        await repo.save_page(
            c,
            url=url,
            source_url=url,
            domain=domain,
            title=fetched.title,
            published_at=published,
            content_text=fetched.text,
            content_hash=digest,
            found_via=found_via,
            status=STATUS_OK,
            projects=list(projects),
            location=list(location),
        )
    return Page(url, domain, fetched.title, published, None, fetched.text, projects, location)


async def _ingest_many(
    deps: Deps,
    urls: Sequence[str],
    found_via: str,
    claimed: set[str],
    when: Mapping[str, datetime | None] | None = None,
    *,
    mode: str = "http",
    skip_known: bool = True,
) -> list[Page]:
    todo = list(dict.fromkeys(canonical_url(u) for u in urls if u))
    fallback = {canonical_url(u): w for u, w in (when or {}).items() if u}
    known: set[str] = set()
    if skip_known:
        async with deps.conn() as c:
            known = await repo.known_urls(c, todo)
    results = await asyncio.gather(
        *(_ingest_one(deps, u, found_via, claimed, fallback.get(u), mode) for u in todo if u not in known),
        return_exceptions=True,
    )
    _raise_first(results)
    return [p for p in results if isinstance(p, Page)]


async def ingest_urls(
    deps: Deps,
    urls: Sequence[str],
    *,
    found_via: str,
    when: Mapping[str, datetime | None] | None = None,
    mode: str = "http",
    skip_known: bool = True,
) -> list[Page]:
    """Tải + gắn nhãn + lưu các URL chưa có trong kho. Trả các trang MỚI liên quan đã lưu.

    `when` = ngày đăng dự phòng theo URL (từ sitemap/RSS) khi trang không tự khai ngày.
    `mode="browser"` đi thẳng tầng trình duyệt; `skip_known=False` tải lại cả URL đã có dấu."""
    return await _ingest_many(deps, urls, found_via, set(), when, mode=mode, skip_known=skip_known)


async def _crawl_source(deps: Deps, source: SourceSite, day: date, claimed: set[str]) -> int:
    entries = await deps.discover.day_entries(source, day, deps.cfg.bds_keywords)
    if not entries:
        log.warning("nguồn %s không có bài nào ngày %s", source.domain, day)
        return 0
    urls = [e.url for e in entries]
    when = {e.url: e.when for e in entries}
    return len(await _ingest_many(deps, urls, FOUND_SITEMAP, claimed, when, mode=source.fetch_mode))


async def crawl_day(deps: Deps, day: date) -> int:
    """Mọi nguồn chạy song song. Nguồn hỏng chỉ ghi log; lỗi tạm thời được nêu lại SAU khi các nguồn khác xong."""
    claimed: set[str] = set()
    sources = deps.cfg.sources
    results = await asyncio.gather(*(_crawl_source(deps, s, day, claimed) for s in sources), return_exceptions=True)
    total = 0
    temporary: TemporaryError | None = None
    for source, r in zip(sources, results, strict=True):
        if isinstance(r, TemporaryError):
            log.warning("nguồn %s gặp lỗi tạm thời: %s", source.domain, r)
            temporary = temporary or r
        elif isinstance(r, Exception):
            log.error("nguồn %s hỏng", source.domain, exc_info=r)
        elif isinstance(r, BaseException):
            raise r
        else:
            total += r
    if temporary is not None:
        raise temporary
    return total


async def recheck_living(deps: Deps, now: datetime) -> int:
    """Tải lại trang `living` quá hạn kiểm. Trả số trang có nội dung mới đã lưu.

    Trang nào cũng được đóng dấu `last_checked_at` dù tải/gắn nhãn hỏng hay nội dung không đổi —
    không thì nó đứng mãi đầu hàng `living_due` và chặn các trang khác."""
    domains = [s.domain for s in deps.cfg.sources if s.kind == "living"]
    if not domains:
        return 0
    async with deps.conn() as c:
        due = await repo.living_due(c, domains, now - LIVING_RECHECK)
        stored = await repo.stored_hashes(c, due)
    done = 0
    for url in due:
        if await _recheck_one(deps, url, stored.get(url, "")):
            done += 1
        else:
            async with deps.conn() as c:
                await repo.mark_checked(c, url)
    return done


async def _recheck_one(deps: Deps, url: str, stored_hash: str) -> bool:
    fetched = await deps.fetcher.fetch(url)
    if fetched.status != STATUS_OK:
        return False
    digest = content_hash(fetched.text)
    if digest == stored_hash:
        return False
    try:
        tags = await deps.llm.tag(fetched.title, fetched.text)
    except (ValueError, httpx.HTTPStatusError) as exc:
        log.warning("gắn nhãn trang living %s lỗi, bỏ qua: %s", url, exc)
        return False
    relevant = tags.relevant
    async with deps.conn() as c:
        await repo.save_page(
            c,
            url=url,
            source_url=url,
            domain=domain_of(url),
            title=fetched.title,
            published_at=fetched.published_at,
            content_text=fetched.text if relevant else None,
            content_hash=digest,
            found_via=FOUND_SITEMAP,
            status=STATUS_OK if relevant else STATUS_IRRELEVANT,
            projects=list(tags.projects) if relevant else [],
            location=list(place_labels(tags.location)) if relevant else [],
        )
    return True


# ─── prompt ──────────────────────────────────────────────────────────────────


def _size(page: Page) -> int:
    return min(len(page.content_text), MAX_SOURCE_CHARS)


def _newest_within_budget(pages: Sequence[Page]) -> list[Page]:
    """Bản tin: bài mới nhất trước, tối đa `MAX_PROMPT_PAGES` bài và `MAX_PROMPT_CHARS` ký tự nguồn."""
    newest = sorted(pages, key=lambda p: p.published_at or p.fetched_at or _OLDEST, reverse=True)
    out: list[Page] = []
    used = 0
    for p in newest[:MAX_PROMPT_PAGES]:
        if used + _size(p) > MAX_PROMPT_CHARS:
            break
        out.append(p)
        used += _size(p)
    return out


def _oldest_within_budget(pages: Sequence[Page]) -> list[Page]:
    """Hồ sơ/thẻ: tiền tố theo thứ tự NẠP vừa trần; phần còn lại có `fetched_at` sau watermark
    nên lượt sau tự nhặt. Không cắt giữa một nhóm cùng `fetched_at` — cắt thì phần bị bỏ của nhóm
    nằm đúng bằng watermark và lọt vĩnh viễn (lọc `fetched_at > since`)."""
    ordered = sorted(pages, key=lambda p: (p.fetched_at or _OLDEST, p.url))
    out: list[Page] = []
    used = 0
    for _, group in groupby(ordered, key=lambda p: p.fetched_at):
        group = list(group)
        size = sum(_size(p) for p in group)
        if len(out) + len(group) <= MAX_PROMPT_PAGES and used + size <= MAX_PROMPT_CHARS:
            out += group
            used += size
            continue
        if not out:
            for p in group:
                if len(out) >= MAX_PROMPT_PAGES or used + _size(p) > MAX_PROMPT_CHARS:
                    break
                out.append(p)
                used += _size(p)
            unsent = [p.url for p in group[len(out) :]]
            log.error(
                "%d bài cùng mốc nạp vượt trần prompt, %d bài sẽ không bao giờ được gửi: %s",
                len(group),
                len(unsent),
                unsent[:5],
            )
        break
    return out


def _stamp(now: datetime, sent: Sequence[Page]) -> datetime:
    """Watermark = `fetched_at` (giờ DB) mới nhất của bài ĐÃ GỬI — không phải `now`, để bài chưa
    gửi (vượt trần) vẫn còn sau watermark cho lượt sau."""
    return max((p.fetched_at for p in sent if p.fetched_at), default=now)


# ─── bản tin ─────────────────────────────────────────────────────────────────


def _shared_location(labels_per_page: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    """Nhãn có ở ≥ `MIN_SHARED_PAGES` trang, nhiều trang trước (hoà thì theo thứ tự gặp), tối đa
    `MAX_DIGEST_LOCATION`; chỉ một trang thì lấy các nhãn đầu của trang đó."""
    if len(labels_per_page) <= 1:
        return tuple(chain.from_iterable(labels_per_page))[:MAX_DIGEST_LOCATION]
    counts = Counter(chain.from_iterable(labels_per_page))  # Counter giữ thứ tự gặp đầu tiên
    shared = [label for label, n in counts.items() if n >= MIN_SHARED_PAGES]
    return tuple(sorted(shared, key=lambda label: -counts[label]))[:MAX_DIGEST_LOCATION]


def _location_of_items(items: list[Item], pages: Sequence[Page]) -> list[Item]:
    by_url = {p.url: place_labels(p.location) for p in pages}
    return [
        replace(it, location=_shared_location([by_url[s.url] for s in it.sources if s.url in by_url])) for it in items
    ]


async def build_digest(deps: Deps, now: datetime) -> int:
    """Bài báo (sitemap/RSS) đăng từ 00:00 giờ VN hôm qua tới `now` — theo NGÀY LỊCH, vì nhiều trang
    chỉ có ngày đăng (00:00) và chuỗi đêm chạy lúc ~1h. Bài grounding/không rõ ngày không phải tin mới."""
    start = datetime.combine(now.astimezone(VN).date() - timedelta(days=1), time(0), tzinfo=VN)
    async with deps.conn() as c:
        recent = await repo.pages_published_since(c, start, now, found_via=[FOUND_SITEMAP, FOUND_RSS])
    pages = _newest_within_budget(recent)
    if not pages:
        return 0
    block, sources, _ = number_sources(pages, [], deps.cfg.names_of())
    try:
        raw = await deps.llm.ask(PROFILE_DIGEST, f"Hôm nay: {now:%d/%m/%Y}\n\nNGUỒN:\n{block}")
    except ValueError as exc:
        log.error("bản tin: trả lời LLM hỏng hoặc bị cắt, giữ bản cũ: %s", exc)
        return 0
    items = parse_items(raw, sources, projects=(), location=(), limit=MAX_DIGEST_ITEMS)
    if not items:
        return 0
    header = f"Tin thị trường bất động sản ngày {now.astimezone(VN):%d/%m/%Y}"
    return await deps.index.replace(digest_ids(DIGEST_REGION), _location_of_items(items, pages), now, header=header)


# ─── hồ sơ dự án ─────────────────────────────────────────────────────────────


def _matches(page: Page, topic: Topic) -> bool:
    hay = fold(f"{page.title} {page.content_text[:3000]}")
    return any(contains_word(hay, k) for k in topic.keywords)


def topic_counts(pages: Sequence[Page], topics: Sequence[Topic]) -> dict[str, int]:
    return {t.code: sum(1 for p in pages if _matches(p, t)) for t in topics}


async def _related(
    deps: Deps,
    project: ProjectRow,
    location: Sequence[str],
    since: datetime | None,
    *,
    oldest_first: bool = False,
    published_since: datetime | None = None,
    published_before: datetime | None = None,
    limit: int = BUILD_PAGES,
) -> list[Page]:
    async with deps.conn() as c:
        excluded = await repo.excluded_urls(c, project.code)
        pages = await repo.pages_for(
            c,
            projects=list(project_names(project.name)),
            location=list(location),
            since=since,
            limit=limit,
            oldest_first=oldest_first,
            others=project.more_specific,
            published_since=published_since,
            published_before=published_before,
        )
    return [p for p in pages if p.url not in excluded]


async def _pick_pages(deps: Deps, project: ProjectRow, location: Sequence[str], now: datetime) -> list[Page]:
    """Bài dựng hồ sơ: bài đăng trong `FRESH_DAYS` (mới nhất trước); rồi lùi về bài cũ hơn, mới → cũ,
    lấy bài gắn tên dự án hoặc khớp một chủ đề còn dưới `target_per_topic`."""
    cutoff = now - timedelta(days=FRESH_DAYS)
    pages = await _related(deps, project, location, None, published_since=cutoff)
    if len(pages) >= BUILD_PAGES:
        return pages
    topics, target = deps.cfg.topics, deps.cfg.target_per_topic
    counts = topic_counts(pages, topics)
    older = await _related(deps, project, location, None, published_before=cutoff, limit=10 * BUILD_PAGES)
    for page in older:
        if len(pages) >= BUILD_PAGES:
            break
        short = [t for t in topics if counts[t.code] < target and _matches(page, t)]
        if short or any(_tags_project(label, project) for label in page.projects):
            pages.append(page)
            for t in topics:
                counts[t.code] += _matches(page, t)
    return pages


def location_labels(project: ProjectRow) -> tuple[str, ...]:
    """Nhãn so khớp của dự án — từ hẹp ra rộng, không có tỉnh/thành. Rỗng khi dự án không có địa danh."""
    own = match_labels(address_parts(project.address, project.region))
    return own + tuple(lb for lb in old_names(project.address) if lb not in own)


async def _fill_topics(deps: Deps, project: ProjectRow, related: list[Page]) -> None:
    if deps.grounding is None:
        return
    topics = deps.cfg.topics
    target = deps.cfg.target_per_topic
    counts = topic_counts(related, topics)
    fmt = {"project": display_project(project.name), "location": location_text(project.address, project.region)}
    queries = pages = 0
    for topic in topics:
        streak = 0
        usable = [t for t in topic.queries if fmt["location"] or "{location}" not in t]
        for template in usable[:MAX_QUERIES_PER_TOPIC]:
            if counts[topic.code] >= target or streak >= EMPTY_STREAK_STOP:
                break
            if queries >= MAX_QUERIES_PER_PROJECT or pages >= MAX_PAGES_PER_PROJECT:
                return
            query = template.format(**fmt)
            queries += 1
            try:
                found = await deps.grounding.search(query)
            except GroundingUnreachable:
                # mạng phía mình hỏng: viết hồ sơ lúc này là thiếu bài — để job chạy lại
                raise
            except TemporaryGroundingError as exc:
                log.warning("grounding lỗi tạm thời (%s) — dừng grounding cho lượt này, vẫn viết hồ sơ", exc)
                return
            except (httpx.HTTPStatusError, ValueError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
                    log.warning(
                        "grounding bị từ chối (%d) — sai khoá? dừng grounding cho lượt này", exc.response.status_code
                    )
                    return
                log.warning("grounding %r lỗi, bỏ qua truy vấn: %s", query, exc)
                streak += 1
                continue
            if not found and getattr(deps.grounding, "exhausted", False):
                log.warning("hết trần grounding trong ngày, dừng tìm thêm cho dự án %s", project.name)
                return
            urls = found[: min(URLS_PER_QUERY, MAX_PAGES_PER_PROJECT - pages)]
            pages += len(urls)
            new = await ingest_urls(deps, urls, found_via=FOUND_GROUNDING)
            for t in topics:
                counts[t.code] += sum(1 for p in new if _matches(p, t))
            streak = 0 if new else streak + 1


async def _refresh_card(deps: Deps, name: str, now: datetime, *, about: str = "") -> None:
    """Viết/cập nhật thẻ của `name`. `about` = dự án đang xét: thẻ hoá ra là tên khác/một phần của nó
    thì xoá thẻ thay vì ghi — không phải dự án lân cận."""
    old = await deps.index.get([card_id(name)])
    near, old = (split_near(old[0].text)[0], [replace(old[0], text=split_near(old[0].text)[1])]) if old else ((), [])
    since = old[0].updated_at if old else None
    async with deps.conn() as c:
        fresh = await repo.pages_for(c, projects=[name], location=[], since=since, oldest_first=True)
    sent = _oldest_within_budget(fresh)
    if not sent:
        return
    block, sources, carried = number_sources(sent, old, deps.cfg.names_of())
    existing = "\n\n".join(carried) or "(chưa có)"
    prompt = f"Hôm nay: {now:%d/%m/%Y}\nDỰ ÁN: {name}\n\nTHẺ HIỆN CÓ:\n{existing}\n\nNGUỒN:\n{block}"
    try:
        raw = await deps.llm.ask(PROFILE_CARD, prompt)
    except (ValueError, httpx.HTTPStatusError) as exc:
        log.warning("viết thẻ %s lỗi, bỏ qua: %s", name, exc)
        return
    if raw.get("residential") is False:
        log.info("thẻ %s không phải dự án nhà ở — xoá", name)
        await deps.index.replace([card_id(name)], [], now)
        return
    location = card_location(raw) or place_labels(old[0].location if old else ())[:MAX_CARD_LOCATION]
    if not location:
        log.info("thẻ %s không có vị trí — không ghi", name)
        return
    # thẻ phải nói về đúng dự án của nó — LLM hay lấy nhầm dự án khác cùng bài nguồn
    items = parse_items(raw, sources, projects=(name,), location=location, limit=MAX_CARD_CANDIDATES)
    items = without_negative([it for it in items if mentions_project(it.text, name)])[:1]
    if items and about and alias_of(items[0].text, about, name):
        log.info("thẻ %s là tên khác/một phần của %s — không ghi", name, about)
        await deps.index.replace([card_id(name)], [], now)
        return
    if items:
        # chỉ giữ địa danh chính thẻ nhắc tới — LLM đôi khi gắn địa danh của dự án khác cùng bài nguồn
        hay = fold(items[0].text)
        location = tuple(lb for lb in location if contains_word(hay, lb))
        if not location:
            log.info("thẻ %s không nhắc địa danh nào của nó — không ghi", name)
            return
        items = [replace(items[0], text=with_near(items[0].text, near), location=location)]
        await deps.index.replace(
            [card_id(name)], items, _stamp(now, sent), written_at=now, header=_card_header(name, location)
        )


def _card_header(name: str, location: Sequence[str]) -> str:
    return f"Dự án {name}" + (f" — {', '.join(location)}" if location else "")


async def _mark_near(deps: Deps, project: ProjectRow, cards: Sequence[Item], now: datetime) -> None:
    """Search "dự án nào gần X" chỉ theo text: ghi point "Các dự án gần X" (rỗng thì xoá) và ghi X vào dòng
    "Gần các dự án" của mỗi thẻ lân cận."""
    me = display_project(project.name)
    place = location_text(project.address, project.region)
    near = near_item(me, place, cards, location_labels(project), project.name)
    await deps.index.replace(
        [near_id(project.name)],
        [near] if near else [],
        now,
        written_at=now,
        header=f"Các dự án gần {me}" + (f" — {place}" if place else ""),
    )
    for card in cards:
        names, body = split_near(card.text)
        if not card.projects or any(same_project(n, me) for n in names):
            continue
        name = card.projects[0]
        await deps.index.replace(
            [card_id(name)],
            [replace(card, text=with_near(body, (*names, me)))],
            card.updated_at or now,
            written_at=now,
            header=_card_header(name, card.location),
        )


async def _refresh_cards(deps: Deps, project: ProjectRow, location: Sequence[str], now: datetime) -> None:
    own = card_id(project.name)
    chosen: list[str] = []
    for level in levels(location):
        async with deps.conn() as c:
            found = await repo.names_near(c, list(level), list(project_names(project.name)))
        for n in found:
            if card_id(n) == own or is_non_project(n):
                continue
            k = next((i for i, kept in enumerate(chosen) if same_project(kept, n)), None)
            if k is None:
                chosen.append(n)
            elif len(n) < len(chosen[k]):
                chosen[k] = n  # giữ tên gốc ngắn hơn, bỏ biến thể có đuôi
        if len(chosen) >= MIN_NEIGHBORS:
            break
    for name in chosen[:MAX_NEIGHBORS]:
        await _refresh_card(deps, name, now, about=project.name)


def _placed_in(card: Item, level: Sequence[str]) -> bool:
    """Chính nội dung thẻ nhắc địa danh chung — nhãn `location` của thẻ đôi khi lẫn nơi khác."""
    hay = fold(split_near(card.text)[1])
    return any(contains_word(hay, lb) for lb in set(card.location) & set(place_labels(level)))


def _same_card(a: Item, b: Item) -> bool:
    """Hai thẻ cùng một dự án: biến thể tên, thẻ này nói mình là tên khác/tên pháp lý của thẻ kia, hoặc tên
    sinh đôi (`twin_names`) mà cùng xã/phường."""
    x, y = a.projects[0], b.projects[0]
    if same_project(x, y) or alias_of(a.text, y, x) or alias_of(b.text, x, y):
        return True
    return twin_names(x, y) and bool(set(a.location) & set(b.location))


async def _neighbor_cards(deps: Deps, project: ProjectRow, location: Sequence[str]) -> list[Item]:
    by_id: dict[str, Item] = {}
    for level in levels(location):
        for card in await deps.index.cards_near(list(level), exclude=project.name):
            name = card.projects[0] if card.projects else ""
            if not name or is_non_project(name) or not _placed_in(card, level):
                continue
            if any(same_project(name, n) or alias_of(card.text, n, name) for n in project_names(project.name)):
                continue
            if twin_names(name, project.name) and set(card.location) & set(location):
                continue  # cùng phần đầu tên + cùng xã/phường: chính dự án dưới tên khác
            if not any(_same_card(card, kept) for kept in by_id.values()):
                by_id.setdefault(card_id(name), card)
        if len(by_id) >= MIN_NEIGHBORS:
            break
    return list(by_id.values())[:MAX_NEIGHBORS]


async def _write_dossier(
    deps: Deps,
    project: ProjectRow,
    location: Sequence[str],
    old: list[Item],
    cards: list[Item],
    sent: list[Page],
    now: datetime,
    stamp: datetime,
) -> list[Item] | None:
    """Một lượt viết: `sent` + hồ sơ cũ → ghi đè hồ sơ với watermark `stamp` (`cards` không vào prompt).

    Trả lời hỏng/bị cắt thì giữ nguyên hồ sơ cũ và watermark, ném `_KeptOld` (không phải lỗi job):
    thử lại cùng dữ liệu cũng bị cắt y hệt. `None` = không có gì để viết."""
    async with deps.conn() as c:
        hidden = await repo.hidden_headings(c, project.code)
    old = _dossier_only(deps.cfg, [it for it in old if not is_near_item(it)], hidden)
    block, sources, carried = number_sources(sent, old, deps.cfg.names_of())
    if not sources:
        return None
    old_block = "\n\n".join(carried) or "(chưa có)"
    headings = tuple(h for h in deps.cfg.headings() if h not in hidden)
    prompt = _dossier_prompt(project, now, headings, old_block, block)
    try:
        raw = await deps.llm.ask(PROFILE_DOSSIER, prompt)
    except ValueError as exc:
        log.error("hồ sơ %s: trả lời LLM hỏng hoặc bị cắt, giữ hồ sơ cũ: %s", project.name, exc)
        raise _KeptOld(
            "trả lời LLM bị cắt" if isinstance(exc, TruncatedLlmError) else "trả lời LLM không đọc được"
        ) from exc
    parsed = parse_items(raw, sources, projects=(project.name,), location=location, limit=MAX_DOSSIER_ITEMS)
    items = _dossier_only(deps.cfg, without_negative(parsed), hidden)
    if not items:
        return None
    items = merge_same_heading(items, deps.cfg.headings())
    items = carry_dropped(old, items, MAX_DOSSIER_ITEMS)
    await deps.index.replace(dossier_ids(project.name), items, stamp, written_at=now, header=_dossier_header(project))
    return [replace(it, updated_at=stamp) for it in items]


def _dossier_prompt(
    project: ProjectRow,
    now: datetime,
    headings: Sequence[str],
    old_block: str,
    block: str,
    note: str = "",
) -> str:
    return (
        f"Hôm nay: {now:%d/%m/%Y}\nDỰ ÁN: {project.name}\n\n"
        f"DỮ LIỆU CHÍNH THỨC CỦA CHỦ ĐẦU TƯ (ưu tiên cao nhất):\n{project.facts or '(không có)'}\n\n"
        f"CHỦ ĐỀ (nhãn mở đầu mỗi item): {'; '.join(headings)}\n{note}\n"
        f"HỒ SƠ HIỆN CÓ:\n{old_block}\n\nNGUỒN:\n{block}"
    )


MIN_TOPIC_PAGES = 2


def _missing_topics(cfg: WebConfig, items: Sequence[Item], pages: Sequence[Page]) -> list[Topic]:
    """Chủ đề có ≥ `MIN_TOPIC_PAGES` bài nguồn mà hồ sơ chưa có mục mang nhãn của nó."""
    present = {heading_of(it.text, cfg.headings()) for it in items}
    counts = topic_counts(pages, cfg.topics)
    return [
        t
        for t in cfg.topics
        if t.dossier and (t.heading or t.label) not in present and counts[t.code] >= MIN_TOPIC_PAGES
    ]


_LABEL = re.compile(r"([^\n:.\[\]]{2,80}):\s")


def _dossier_only(cfg: WebConfig, items: Sequence[Item], hidden: frozenset[str] = frozenset()) -> list[Item]:
    """Bỏ mục mở đầu bằng nhãn không phải «Tổng quan» hay một chủ đề đang bật thuộc hồ sơ: chủ đề đã tắt/đã xoá,
    nhãn người dùng đã ẩn cho dự án này (`kbweb_hidden_items`), và "Dự án lân cận" (danh sách lân cận đã ở point
    "Các dự án gần X", mục hồ sơ tả dự án khác là quảng bá hộ đối thủ). Mục không mở đầu bằng nhãn thì giữ."""
    allowed = tuple(h for h in cfg.headings() if h not in hidden)
    return [it for it in items if heading_of(it.text, allowed) or not _LABEL.match(it.text)]


async def _fill_missing(
    deps: Deps,
    project: ProjectRow,
    location: Sequence[str],
    items: list[Item],
    pages: Sequence[Page],
    now: datetime,
    stamp: datetime,
) -> list[Item]:
    """Viết một lượt bù cho các chủ đề LLM bỏ sót — viết cả hồ sơ một lần thì nó hay tự cắt bớt chủ đề."""
    async with deps.conn() as c:
        hidden = await repo.hidden_headings(c, project.code)
    missing = [t for t in _missing_topics(deps.cfg, items, pages) if (t.heading or t.label) not in hidden]
    chunks, _ = _build_chunks([p for p in pages if any(_matches(p, t) for t in missing)]) if missing else ([], 0)
    if not chunks:
        return items
    heads = [t.heading or t.label for t in missing]
    block, sources, carried = number_sources(chunks[-1], items, deps.cfg.names_of())
    note = "CHỈ viết item cho các chủ đề trên; hồ sơ hiện có đã có các chủ đề khác, không viết lại chúng.\n"
    prompt = _dossier_prompt(project, now, heads, "\n\n".join(carried) or "(chưa có)", block, note)
    try:
        raw = await deps.llm.ask(PROFILE_DOSSIER, prompt)
    except ValueError as exc:
        log.warning("hồ sơ %s: lượt bù chủ đề thiếu hỏng, giữ bản đã viết: %s", project.name, exc)
        return items
    parsed = without_negative(
        parse_items(raw, sources, projects=(project.name,), location=location, limit=MAX_DOSSIER_ITEMS)
    )
    new = [it for it in parsed if heading_of(it.text, heads)]
    if not new:
        return items
    log.info("hồ sơ %s: bù %d chủ đề thiếu", project.name, len(new))
    merged = merge_same_heading([*items, *new], deps.cfg.headings())[:MAX_DOSSIER_ITEMS]
    await deps.index.replace(dossier_ids(project.name), merged, stamp, written_at=now, header=_dossier_header(project))
    return [replace(it, updated_at=stamp) for it in merged]


def _dossier_header(project: ProjectRow) -> str:
    place = location_text(project.address, project.region)
    return f"Dự án {display_project(project.name)}" + (f" — {place}" if place else "")


def _published_key(page: Page) -> tuple[datetime, str]:
    return page.published_at or page.fetched_at or _OLDEST, page.url


def _build_chunks(pages: Sequence[Page]) -> tuple[list[list[Page]], int]:
    """Chia bài thành ≤ `MAX_BUILD_PASSES` lượt, mỗi lượt vừa trần prompt, lấy từ bài MỚI NHẤT lùi
    về (thiếu chỗ thì bỏ bài cũ nhất), rồi trả theo thứ tự cũ → mới để tin mới được viết sau cùng.
    Trả (các lượt, số bài bị bỏ)."""
    chunks: list[list[Page]] = []
    cur: list[Page] = []
    used = taken = 0
    for p in sorted(pages, key=_published_key, reverse=True):
        if cur and (len(cur) >= MAX_PROMPT_PAGES or used + _size(p) > MAX_PROMPT_CHARS):
            chunks.append(cur)
            cur, used = [], 0
            if len(chunks) == MAX_BUILD_PASSES:
                break
        cur.append(p)
        used += _size(p)
        taken += 1
    if cur:
        chunks.append(cur)
    return [c[::-1] for c in reversed(chunks)], len(pages) - taken


def _worth_nightly(project: ProjectRow, fresh: Sequence[Page]) -> bool:
    """Lượt đêm chỉ viết lại khi có bài gắn tên dự án, hoặc đủ nhiều bài cùng vùng — một bài
    vùng lẻ không đáng một lượt viết lại toàn hồ sơ."""
    tagged = sum(1 for p in fresh if any(_tags_project(label, project) for label in p.projects))
    return tagged > 0 or len(fresh) - tagged >= NIGHTLY_MIN_AREA_PAGES


def _tags_project(label: str, project: ProjectRow) -> bool:
    return any(project_matches(label, n) for n in project_names(project.name)) and not any(
        project_matches(label, o) for o in project.more_specific
    )


def _resume_stamp(unsent: Sequence[Page], prev: datetime | None) -> datetime | None:
    """Watermark khi còn lượt chưa gửi: ngay trước bài nạp sớm nhất chưa gửi, không thấp hơn `prev`
    (watermark hồ sơ cũ khi mục cũ được mang theo — dựng ban đầu; dựng lại truyền `None`)."""
    times = [p.fetched_at for p in unsent if p.fetched_at]
    if not times:
        return None
    stamp = min(times) - timedelta(microseconds=1)
    return max(stamp, prev) if prev else stamp


async def _build(
    deps: Deps,
    project: ProjectRow,
    location: Sequence[str],
    old: list[Item],
    prev: datetime | None,
    now: datetime,
) -> Refreshed:
    """Dựng ban đầu/dựng lại: tối đa `BUILD_PAGES` bài chọn bởi `_pick_pages`, viết cũ → mới qua tối
    đa `MAX_BUILD_PASSES` lượt. Chỉ lượt CUỐI thành công mới đặt watermark = mốc nạp mới nhất của MỌI bài
    liên quan (tồn đọng cũ hơn tập đó bị bỏ có chủ ý); các lượt trước đặt watermark ngay trước bài chưa
    gửi, để dừng giữa chừng thì lượt đêm/tuần sau vẫn thấy phần còn lại."""
    fresh = now - timedelta(days=FRESH_DAYS)
    await _fill_topics(deps, project, await _related(deps, project, location, None, published_since=fresh))
    await _refresh_cards(deps, project, location, now)
    async with deps.conn() as c:
        mark = await repo.latest_fetched(
            c, projects=list(project_names(project.name)), location=list(location), others=project.more_specific
        )
    pages = await _pick_pages(deps, project, location, now)
    chunks, dropped = _build_chunks(pages)
    if dropped or len(pages) == BUILD_PAGES:
        log.info("hồ sơ %s: dựng từ %d bài mới nhất, bài cũ hơn bỏ qua", project.name, len(pages) - dropped)
    if not chunks and old:
        return Refreshed(0)
    cards = await _neighbor_cards(deps, project, location)
    await _mark_near(deps, project, cards, now)
    plan = chunks or [[]]
    written = 0
    for k, sent in enumerate(plan):
        unsent = [p for later in plan[k + 1 :] for p in later]
        stamp = (_resume_stamp(unsent, prev) if unsent else None) or mark or now
        try:
            result = await _write_dossier(deps, project, location, old, cards, sent, now, stamp)
        except _KeptOld as kept:
            return Refreshed(written, kept.reason)
        if result is None:
            break
        old, written, last = result, len(result), stamp
    if written:
        written = len(await _fill_missing(deps, project, location, old, pages, now, last))
    return Refreshed(written)


async def refresh_project(deps: Deps, project: ProjectRow, mode: str, now: datetime) -> Refreshed:
    """Cập nhật hồ sơ dự án.

    - Lượt đêm: không Gemini, không thẻ lân cận; bài nạp sau watermark (cửa sổ 48 giờ khi chưa có
      hồ sơ), chỉ viết khi `_worth_nightly`.
    - Lượt tuần: Gemini cho chủ đề thiếu + làm mới thẻ lân cận, một lượt viết từ watermark.
    - Dựng ban đầu/dựng lại: xem `_build`.

    Trả số mục của lần ghi cuối (0 nếu không ghi gì) + lý do nếu giữ hồ sơ cũ vì trả lời LLM hỏng."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} không hợp lệ, phải là một trong {MODES}")
    existing = await deps.index.get(dossier_ids(project.name))
    since = max((it.updated_at for it in existing if it.updated_at), default=None)
    old = [] if mode == MODE_REBUILD else existing
    location = location_labels(project)
    if mode in (MODE_INIT, MODE_REBUILD):
        # dựng lại ghi đè từ con số 0 nên không có sàn watermark; dựng ban đầu mang mục cũ theo thì có
        return await _build(deps, project, location, old, None if mode == MODE_REBUILD else since, now)
    cards: list[Item] = []
    if mode == MODE_NIGHTLY:
        since = since or now - NIGHTLY_WINDOW
    else:
        await _fill_topics(
            deps,
            project,
            await _related(deps, project, location, None, published_since=now - timedelta(days=FRESH_DAYS)),
        )
        await _refresh_cards(deps, project, location, now)
        cards = await _neighbor_cards(deps, project, location)
        await _mark_near(deps, project, cards, now)
    fresh = await _related(deps, project, location, since, oldest_first=True)
    if mode == MODE_NIGHTLY and not _worth_nightly(project, fresh):
        log.info("hồ sơ %s: lượt đêm không đủ bài mới (%d), bỏ qua", project.name, len(fresh))
        return Refreshed(0)
    if not fresh and old:
        return Refreshed(0)
    sent = _oldest_within_budget(fresh)
    try:
        result = await _write_dossier(deps, project, location, old, cards, sent, now, _stamp(now, sent))
    except _KeptOld as kept:
        return Refreshed(0, kept.reason)
    return Refreshed(len(result) if result else 0)


# ─── chuỗi đêm ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    count: int = 0
    error: str = ""


async def run_step(name: str, work) -> Step:
    try:
        return Step(name, await work)
    except Exception as exc:
        log.exception("bước %s hỏng", name)
        return Step(name, 0, f"{type(exc).__name__}: {exc}")


async def purge(deps: Deps, now: datetime) -> int:
    async with deps.conn() as c:
        return await repo.purge(c, now=now)


RETRY_BROWSER_WINDOW = timedelta(days=2)


async def retry_needs_browser(deps: Deps, now: datetime) -> int:
    """Thử lại bằng trình duyệt các URL mang dấu `needs_browser` trong hai ngày gần nhất. Trả số bài lưu được."""
    async with deps.conn() as c:
        urls = await repo.needs_browser_due(c, now - RETRY_BROWSER_WINDOW)
    if not urls:
        return 0
    return len(await ingest_urls(deps, urls, found_via=FOUND_SITEMAP, mode="browser", skip_known=False))


async def run_nightly(deps: Deps, now: datetime, *, target: date | None = None, queue: bool = True) -> list[Step]:
    """Chuỗi đêm của một tenant: crawl hôm kia + hôm qua (URL `fetch_failed` được thử lại một lần, URL đã có
    thì bỏ qua nên rẻ) → thử lại trang `needs_browser` bằng trình duyệt → kiểm lại trang living → bản tin →
    dọn → xếp việc hồ sơ (dự án đang được hỏi + dự án chưa có hồ sơ). Một bước hỏng không
    dừng các bước sau; kết quả từng bước trả về để bên gọi ghi log/thông điệp job."""
    target = target or now.astimezone(VN).date() - timedelta(days=1)
    steps = [await run_step(f"crawl {d}", crawl_day(deps, d)) for d in (target - timedelta(days=1), target)]
    steps.append(await run_step("thử lại bằng trình duyệt", retry_needs_browser(deps, now)))
    steps.append(await run_step("kiểm lại trang living", recheck_living(deps, now)))
    steps.append(await run_step("bản tin", build_digest(deps, now)))
    steps.append(await run_step("dọn", purge(deps, now)))
    if queue:
        steps.append(
            await run_step(
                f"xếp việc {MODE_NIGHTLY}", fanout.queue_projects(deps.pool, MODE_NIGHTLY, tenant_id=deps.tenant)
            )
        )
        steps.append(
            await run_step(
                "xếp hồ sơ cho dự án chưa có", fanout.queue_missing(deps.pool, deps.index, tenant_id=deps.tenant)
            )
        )
    return steps
