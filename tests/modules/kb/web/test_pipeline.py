"""pipeline — nối discover → fetch → tag → lưu, bản tin, làm mới hồ sơ dự án.

Postgres thật (`web_pool`) + Qdrant thật (collection riêng mỗi test); fetch/LLM/grounding/discover là lớp giả.
"""

import asyncio
import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from qdrant_client import AsyncQdrantClient

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web import pipeline, repo
from portal.modules.kb.web.compose import card_id, digest_ids, dossier_ids, near_id
from portal.modules.kb.web.config import SourceSite, Topic
from portal.modules.kb.web.contracts import (
    DIGEST_REGION,
    MODE_INIT,
    MODE_NIGHTLY,
    MODE_REBUILD,
    MODE_WEEKLY,
    PROFILE_CARD,
    PROFILE_DIGEST,
    PROFILE_DOSSIER,
    Item,
    Page,
    Source,
    Tags,
)
from portal.modules.kb.web.discover import VN, Entry, parse_when
from portal.modules.kb.web.fetch import Fetched
from portal.modules.kb.web.grounding import Grounding, GroundingBudget, GroundingUnreachable, TemporaryGroundingError
from portal.modules.kb.web.index import WebIndex
from portal.modules.kb.web.llm import TruncatedLlmError, WebLlm
from portal.modules.kb.web.normalize import content_hash
from portal.modules.kb.web.pipeline import (
    Deps,
    build_digest,
    crawl_day,
    ingest_urls,
    recheck_living,
    refresh_project,
    topic_counts,
)
from portal.modules.kb.web.signal import ProjectRow

from . import mac_dinh
from .conftest import TENANT

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 29, 19, 0, tzinfo=UTC)
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
BASE = "https://test.kbweb"
PROJ = ProjectRow(
    1,
    "NPTTL",
    "Noble Palace Tây Thăng Long",
    "Hà Nội",
    "xã Tân Lập, huyện Đan Phượng, Hà Nội",
    "Địa chỉ: xã Tân Lập, huyện Đan Phượng",
    (),
)
PROJ2 = ProjectRow(2, "DAB", "Dự án Bê", "Hà Nội", "huyện Đan Phượng, Hà Nội", "", ())
LOC = ["Đan Phượng", "Hà Nội", "Tây Hà Nội"]
PROJ_LABEL = "noble palace tây thăng long"


class FakeEmbed:
    async def dense(self, texts):
        return [[0.01 * (i + 1)] * 1024 for i, _ in enumerate(texts)]

    async def sparse(self, texts):
        return [{"indices": [1, 2], "values": [1.0, 0.5]} for _ in texts]


@pytest.fixture
async def web_index(qdrant_url):
    client = AsyncQdrantClient(url=qdrant_url, check_compatibility=False, timeout=60)
    idx = WebIndex(client=client, embed=FakeEmbed(), collection=f"test_web_{uuid.uuid4().hex[:8]}")
    await idx.ensure()
    yield idx
    await client.delete_collection(idx.collection)
    await client.close()


class FakeFetcher:
    def __init__(self, pages=None, fallback=None):
        self.pages = dict(pages or {})
        self.fallback = fallback
        self.calls = []
        self.modes = []

    async def fetch(self, url, mode="http"):
        self.calls.append(url)
        self.modes.append(mode)
        if url in self.pages:
            return self.pages[url]
        if self.fallback is not None:
            return self.fallback(url)
        return Fetched(url, "fetch_failed")


def _card_name(prompt):
    return prompt.split("DỰ ÁN: ")[1].split("\n")[0]


def _card_answer(prompt):
    return {"text": f"Thẻ dự án {_card_name(prompt)} ở Đan Phượng [1].", "cites": [1], "location": ["huyện Đan Phượng"]}


class FakeLlm:
    def __init__(self, answers=None):
        self.asked = []
        self.tagged = []
        self.answers = {
            PROFILE_DOSSIER: {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]},
            PROFILE_DIGEST: {"items": [{"text": "Giá tăng [1].", "cites": [1]}]},
            PROFILE_CARD: _card_answer,
            **(answers or {}),
        }

    async def tag(self, title, text):
        self.tagged.append(text)
        if "JSON HỎNG" in text:
            raise ValueError("không thấy JSON")
        if "QUÁ TẢI" in text:
            raise TemporaryError("LLM 429")
        if "bóng đá" in text:
            return Tags(False, (), ())
        projects = tuple(n for n in (PROJ.name, "Wonder City") if n.split()[0] in text)
        return Tags(True, projects, ("huyện Đan Phượng",))

    async def ask(self, profile, text):
        self.asked.append((profile, text))
        a = self.answers[profile]
        return a(text) if callable(a) else a

    def prompts(self, profile):
        return [t for p, t in self.asked if p == profile]


class FakeDiscover:
    def __init__(self, by_domain=None, broken=()):
        self.by_domain = by_domain or {}
        self.broken = set(broken)

    async def day_entries(self, source, day, keywords):
        if source.domain in self.broken:
            raise RuntimeError("sitemap đổi định dạng")
        return list(self.by_domain.get(source.domain, []))


class FakeGrounding:
    def __init__(self, answer=()):
        self.answer = answer
        self.queries = []

    async def search(self, q):
        self.queries.append(q)
        return list(self.answer(q) if callable(self.answer) else self.answer)


class NoGrounding:
    async def search(self, q):
        raise AssertionError(f"lượt đêm không được gọi grounding: {q}")


def _ok(url, text, title="tiêu đề"):
    return Fetched(url, "ok", title, text, NOW)


def _site(domain, fetch_mode="http", kind="news"):
    return SourceSite(domain, domain, True, fetch_mode, kind, (), "", "", (), (), "", ())


def _deps(web_pool, web_index, *, pages=None, fallback=None, cfg=None, llm=None, discover=None, grounding=None):
    return Deps(
        pool=web_pool,
        tenant=TENANT,
        cfg=cfg or mac_dinh.defaults(),
        discover=discover or FakeDiscover(),
        fetcher=FakeFetcher(pages, fallback),
        llm=llm or FakeLlm(),
        index=web_index,
        grounding=grounding,
    )


async def _seed(
    web_pool,
    url,
    text,
    *,
    projects=(),
    location=LOC,
    age=None,
    status="ok",
    h=None,
    fetched=None,
    published=None,
    found_via="sitemap",
):
    async with tenant_conn(web_pool, TENANT) as c:
        await repo.save_page(
            c,
            url=url,
            source_url=url,
            domain="test.kbweb",
            title="t",
            published_at=published,
            content_text=text,
            content_hash=h or f"seed:{url}",
            found_via=found_via,
            status=status,
            projects=list(projects),
            location=list(location),
        )
        if age is not None:
            await c.execute(
                "UPDATE tenant_data.web_pages SET fetched_at = now() - $2::text::interval, "
                "last_checked_at = now() - $2::text::interval WHERE url = $1",
                url,
                age,
            )
        if fetched is not None:
            await c.execute("UPDATE tenant_data.web_pages SET fetched_at = $2 WHERE url = $1", url, fetched)


async def _row(web_pool, url):
    async with tenant_conn(web_pool, TENANT) as c:
        return await c.fetchrow("SELECT * FROM tenant_data.web_pages WHERE url = $1", url)


@pytest.fixture
def logs(caplog, monkeypatch):
    # alembic `fileConfig` ở fixture phiên tắt các logger đã tồn tại — bật lại cho caplog
    monkeypatch.setattr(logging.getLogger("portal.modules.kb.web.pipeline"), "disabled", False)
    caplog.set_level("WARNING", logger="portal.modules.kb.web.pipeline")
    return caplog


# ─── ingest ──────────────────────────────────────────────────────────────────


async def test_ingest_bo_url_da_co_bai_chep_lai_va_luu_dau_bai_khong_lien_quan(web_pool, web_index):
    a, b, c, d = (f"{BASE}/{x}" for x in "abcd")
    deps = _deps(
        web_pool,
        web_index,
        pages={a: _ok(a, "Noble Palace có đại lộ"), b: _ok(b, "Noble Palace có đại lộ"), c: _ok(c, "tin bóng đá")},
    )
    got = await ingest_urls(deps, [a, b, c, d], found_via="sitemap")
    assert [p.url for p in got] == [a]
    assert got[0].projects == (PROJ_LABEL,)
    assert got[0].location == ("đan phượng",)
    async with tenant_conn(web_pool, TENANT) as conn:
        assert await repo.known_urls(conn, [a, b, c, d]) == {a, c}
    assert (await _row(web_pool, c))["status"] == "irrelevant"
    assert (await _row(web_pool, d))["status"] == "fetch_failed"
    await ingest_urls(deps, [a, c, d], found_via="sitemap")
    assert deps.fetcher.calls.count(a) == deps.fetcher.calls.count(c) == 1
    assert deps.fetcher.calls.count(d) == 2, "fetch_failed phải được tải lại"


async def test_ingest_bai_tai_hong_lan_sau_tai_duoc_thi_nang_len_ok(web_pool, web_index):
    url = f"{BASE}/hong-roi-ok"
    deps = _deps(web_pool, web_index)
    assert await ingest_urls(deps, [url], found_via="grounding") == []
    assert (await _row(web_pool, url))["status"] == "fetch_failed"
    deps.fetcher.pages[url] = _ok(url, "Noble Palace đã tải được")
    assert [p.url for p in await ingest_urls(deps, [url], found_via="sitemap")] == [url]
    row = await _row(web_pool, url)
    assert row["status"] == "ok" and row["content_text"] == "Noble Palace đã tải được"
    assert row["found_via"] == "grounding"


async def test_ingest_bai_chep_lai_da_co_trong_kho_tu_truoc_thi_khong_luu(web_pool, web_index):
    a, b = f"{BASE}/goc", f"{BASE}/chep"
    deps = _deps(web_pool, web_index, pages={a: _ok(a, "Noble Palace khởi công"), b: _ok(b, "Noble  palace KHỞI CÔNG")})
    assert len(await ingest_urls(deps, [a], found_via="sitemap")) == 1
    assert await ingest_urls(deps, [b], found_via="grounding") == []
    assert await _row(web_pool, b) is None


async def test_ingest_hai_ban_chep_tai_song_song_chi_luu_mot(web_pool, web_index):
    class SlowLlm(FakeLlm):
        async def tag(self, title, text):
            await asyncio.sleep(0.05)
            return await super().tag(title, text)

    urls = [f"{BASE}/song-song/{i}" for i in range(4)]
    deps = _deps(web_pool, web_index, pages={u: _ok(u, "Noble Palace cùng một bài") for u in urls}, llm=SlowLlm())
    got = await ingest_urls(deps, urls, found_via="sitemap")
    assert len(got) == 1
    async with tenant_conn(web_pool, TENANT) as conn:
        assert len(await repo.known_urls(conn, urls)) == 1


async def test_ingest_chuan_hoa_url_truoc_khi_tai(web_pool, web_index):
    url = f"{BASE}/x"
    deps = _deps(web_pool, web_index, pages={url: _ok(url, "Noble Palace")})
    got = await ingest_urls(deps, [f"{url}?utm_source=fb", f"{url}/", url], found_via="sitemap")
    assert [p.url for p in got] == [url]
    assert deps.fetcher.calls == [url]


async def test_ingest_llm_tra_json_hong_thi_bo_qua_va_lan_sau_thu_lai(web_pool, web_index):
    bad, good = f"{BASE}/hong", f"{BASE}/tot"
    deps = _deps(web_pool, web_index, pages={bad: _ok(bad, "JSON HỎNG"), good: _ok(good, "Noble Palace")})
    got = await ingest_urls(deps, [bad, good], found_via="sitemap")
    assert [p.url for p in got] == [good]
    assert await _row(web_pool, bad) is None
    await ingest_urls(deps, [bad], found_via="sitemap")
    assert deps.fetcher.calls.count(bad) == 2


async def test_ingest_loi_tam_thoi_cua_llm_van_luu_trang_khac_roi_nem(web_pool, web_index):
    busy, good = f"{BASE}/ban", f"{BASE}/tot"
    deps = _deps(web_pool, web_index, pages={busy: _ok(busy, "QUÁ TẢI"), good: _ok(good, "Noble Palace")})
    with pytest.raises(TemporaryError):
        await ingest_urls(deps, [busy, good], found_via="sitemap")
    assert (await _row(web_pool, good))["status"] == "ok"
    assert await _row(web_pool, busy) is None


# ─── crawl_day ───────────────────────────────────────────────────────────────


async def test_crawl_day_bo_url_da_co_va_dem_bai_moi(web_pool, web_index):
    a, b, c = f"{BASE}/cd/a", f"{BASE}/cd/b", f"{BASE}/cd/c"
    await _seed(web_pool, a, "đã có")
    cfg = replace(mac_dinh.defaults(), sources=(_site("one.kbweb"),))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={a: _ok(a, "Noble mới"), b: _ok(b, "Noble Palace đại lộ"), c: _ok(c, "tin bóng đá")},
        discover=FakeDiscover({"one.kbweb": [Entry(a, NOW), Entry(b, NOW), Entry(c, NOW)]}),
    )
    assert await crawl_day(deps, date(2026, 9, 28)) == 1
    assert deps.fetcher.calls == [b, c]
    assert (await _row(web_pool, c))["status"] == "irrelevant"
    assert (await _row(web_pool, a))["content_text"] == "đã có"


async def test_crawl_day_bai_chep_lai_giua_hai_bao_chi_luu_mot(web_pool, web_index):
    a, b = f"{BASE}/cd/bao1", f"{BASE}/cd/bao2"
    cfg = replace(mac_dinh.defaults(), sources=(_site("one.kbweb"), _site("two.kbweb")))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={a: _ok(a, "Noble Palace mở bán"), b: _ok(b, "Noble Palace mở bán")},
        discover=FakeDiscover({"one.kbweb": [Entry(a, NOW)], "two.kbweb": [Entry(b, NOW)]}),
    )
    assert await crawl_day(deps, date(2026, 9, 28)) == 1
    rows = [await _row(web_pool, u) for u in (a, b)]
    assert sum(r is not None for r in rows) == 1
    assert len(deps.llm.tagged) == 1


async def test_crawl_day_nguon_trinh_duyet_tai_bang_mode_browser(web_pool, web_index):
    """Nguồn `fetch_mode=browser` đi thẳng tầng trình duyệt; tầng đó không có thì dấu `needs_browser` ở lại."""
    ld, hb = f"{BASE}/cd/browser", f"{BASE}/cd/challenge"
    cfg = replace(mac_dinh.defaults(), sources=(_site("browser.kbweb", fetch_mode="browser"), _site("one.kbweb")))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={hb: Fetched(hb, "needs_browser"), ld: Fetched(ld, "needs_browser")},
        discover=FakeDiscover({"browser.kbweb": [Entry(ld, NOW)], "one.kbweb": [Entry(hb, NOW)]}),
    )
    assert await crawl_day(deps, date(2026, 9, 28)) == 0
    assert dict(zip(deps.fetcher.calls, deps.fetcher.modes, strict=True)) == {ld: "browser", hb: "http"}
    assert (await _row(web_pool, ld))["status"] == "needs_browser"
    assert (await _row(web_pool, hb))["status"] == "needs_browser"
    await crawl_day(deps, date(2026, 9, 28))
    assert deps.fetcher.calls == [ld, hb], "URL đã có dấu không tải lại ở lượt crawl ngày"


async def test_retry_needs_browser_tai_lai_bang_trinh_duyet_trong_hai_ngay(web_pool, web_index):
    new, old = f"{BASE}/nb/moi", f"{BASE}/nb/cu"
    await _seed(web_pool, new, None, status="needs_browser")
    await _seed(web_pool, old, None, status="needs_browser", age="5 days")
    deps = _deps(web_pool, web_index, pages={new: _ok(new, "Noble Palace sau challenge")})
    assert await pipeline.retry_needs_browser(deps, datetime.now(UTC)) == 1
    assert deps.fetcher.calls == [new] and deps.fetcher.modes == ["browser"]
    assert (await _row(web_pool, new))["status"] == "ok"
    assert (await _row(web_pool, old))["status"] == "needs_browser"


async def test_crawl_day_mot_nguon_hong_khong_lam_hong_ca_ngay(web_pool, web_index):
    b = f"{BASE}/cd/ok"
    cfg = replace(mac_dinh.defaults(), sources=(_site("bad.kbweb"), _site("one.kbweb")))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={b: _ok(b, "Noble Palace")},
        discover=FakeDiscover({"one.kbweb": [Entry(b, NOW)]}, broken={"bad.kbweb"}),
    )
    assert await crawl_day(deps, date(2026, 9, 28)) == 1


async def test_crawl_day_loi_tam_thoi_nem_sau_khi_xong_nguon_khac(web_pool, web_index):
    busy, b = f"{BASE}/cd/ban", f"{BASE}/cd/tot"
    cfg = replace(mac_dinh.defaults(), sources=(_site("busy.kbweb"), _site("one.kbweb")))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={busy: _ok(busy, "QUÁ TẢI"), b: _ok(b, "Noble Palace")},
        discover=FakeDiscover({"busy.kbweb": [Entry(busy, NOW)], "one.kbweb": [Entry(b, NOW)]}),
    )
    with pytest.raises(TemporaryError):
        await crawl_day(deps, date(2026, 9, 28))
    assert (await _row(web_pool, b))["status"] == "ok"


# ─── recheck_living ──────────────────────────────────────────────────────────


async def test_recheck_living_tai_lai_trang_den_han(web_pool, web_index):
    due, fresh = f"{BASE}/living/cu", f"{BASE}/living/moi"
    await _seed(web_pool, due, "nội dung cũ", age="40 days")
    await _seed(web_pool, fresh, "vừa kiểm", age="2 days")
    cfg = replace(mac_dinh.defaults(), sources=(_site("test.kbweb", kind="living"),))
    deps = _deps(web_pool, web_index, cfg=cfg, pages={due: _ok(due, "Noble Palace quy hoạch mới")})
    assert await recheck_living(deps, datetime.now(UTC)) == 1
    assert deps.fetcher.calls == [due]
    row = await _row(web_pool, due)
    assert row["content_text"] == "Noble Palace quy hoạch mới"
    assert row["last_checked_at"] > datetime.now(UTC) - timedelta(minutes=5)
    assert list(row["location"]) == ["đan phượng"]


# ─── build_digest ────────────────────────────────────────────────────────────


async def test_ban_tin_ghi_muc_khong_gan_du_an(web_pool, web_index):
    a = f"{BASE}/digest"
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    deps = _deps(
        web_pool, web_index, pages={a: Fetched(a, "ok", "tiêu đề", "Noble giá chung cư Hà Nội tăng", hour_ago)}
    )
    await ingest_urls(deps, [a], found_via="sitemap")
    assert await build_digest(deps, datetime.now(UTC)) == 1
    (item,) = await web_index.get(digest_ids(DIGEST_REGION))
    assert item.projects == ()
    assert item.text == "Giá tăng [1]."
    assert [s.url for s in item.sources] == [a]
    assert item.location == ("đan phượng",)


async def test_ban_tin_moi_ghi_de_ban_hom_truoc(web_pool, web_index):
    a = f"{BASE}/digest2"
    await _seed(web_pool, a, "tin giá", published=datetime.now(UTC) - timedelta(hours=2))
    two = {"items": [{"text": "Tin một [1].", "cites": [1]}, {"text": "Tin hai [1].", "cites": [1]}]}
    one = {"items": [{"text": "Tin hôm nay [1].", "cites": [1]}]}
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DIGEST: two}))
    assert await build_digest(deps, datetime.now(UTC) - timedelta(hours=1)) == 2
    deps.llm.answers[PROFILE_DIGEST] = one
    assert await build_digest(deps, datetime.now(UTC)) == 1
    got = await web_index.get(digest_ids(DIGEST_REGION))
    assert [i.text for i in got] == ["Tin hôm nay [1]."]


async def test_ban_tin_khong_co_bai_thi_khong_goi_llm(web_pool, web_index):
    deps = _deps(web_pool, web_index)
    assert await build_digest(deps, FUTURE) == 0
    assert deps.llm.asked == []


# ─── refresh_project: lượt đêm ───────────────────────────────────────────────


async def test_luot_dem_khong_goi_grounding_chi_dung_bai_48h(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/n/cu", "BÀI CŨ Noble", projects=[PROJ.name], age="3 days")
    await _seed(web_pool, f"{BASE}/n/moi", "BÀI MỚI Noble", projects=[PROJ.name])
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "BÀI MỚI" in prompt and "BÀI CŨ" not in prompt
    assert deps.llm.prompts(PROFILE_CARD) == []
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.projects == (PROJ_LABEL,)
    assert [s.url for s in item.sources] == [f"{BASE}/n/moi"]
    assert item.location == ("tân lập", "đan phượng")


async def test_bai_chi_cung_vung_khong_vao_ho_so(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/n/hd", "BÀI HOÀI ĐỨC", location=["Hoài Đức", "Hà Nội", "Tây Hà Nội"])
    await _seed(web_pool, f"{BASE}/n/dp", "BÀI ĐAN PHƯỢNG")
    deps = _deps(web_pool, web_index, grounding=None)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "BÀI ĐAN PHƯỢNG" in prompt and "BÀI HOÀI ĐỨC" not in prompt


async def test_luot_dem_khong_co_bai_moi_thi_khong_goi_llm_va_giu_nguyen_chi_muc(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/n/cu", "BÀI CŨ Noble", projects=[PROJ.name], age="6 days")
    old = Item("cũ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ("Đan Phượng",))
    written = datetime.now(UTC) - timedelta(days=5)
    await web_index.replace(dossier_ids(PROJ.name), [old], written)
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    assert deps.llm.asked == []
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.text == "cũ [1]" and item.updated_at == written


async def test_luot_dem_bo_qua_bai_da_dung_cho_ho_so(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/n/moi", "BÀI MỚI Noble", projects=[PROJ.name])
    old = Item("cũ [1]", (Source(f"{BASE}/n/moi", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC) + timedelta(minutes=1))
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    assert deps.llm.asked == []


async def test_llm_tra_rong_thi_giu_ho_so_cu(web_pool, web_index):
    old = Item("cũ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC) - timedelta(days=1))
    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: {"items": []}}))
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.text == "cũ [1]"


async def test_mode_sai_thi_nem(web_pool, web_index):
    with pytest.raises(ValueError):
        await refresh_project(_deps(web_pool, web_index), PROJ, "hourly", datetime.now(UTC))


# ─── refresh_project: cập nhật tăng dần ──────────────────────────────────────


async def test_cap_nhat_tang_dan_so_nguon_tro_dung_url_va_xoa_muc_thua(web_pool, web_index):
    s1, s2, s3 = (Source(f"{BASE}/old{i}", f"Báo {i}", NOW) for i in (1, 2, 3))
    old = [
        Item("Cũ A [1]. Cũ B [2].", (s1, s2), (PROJ.name,), ()),
        Item("Cũ C [1].", (s3,), (PROJ.name,), ()),
        Item("Cũ D [1].", (s1,), (PROJ.name,), ()),
    ]
    await web_index.replace(dossier_ids(PROJ.name), old, datetime.now(UTC) - timedelta(days=1))
    new_url = f"{BASE}/moi"
    await _seed(web_pool, new_url, "BÀI MỚI Noble", projects=[PROJ.name])
    answer = {
        "items": [
            {"text": "Giữ ý cũ [2]. Tin mới [4].", "cites": [2, 4]},
            {"text": "Bịa nguồn [9].", "cites": [9]},
            {"text": "Không trích dẫn gì."},
        ]
    }
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: answer}))
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "Cũ A [1]. Cũ B [2]." in prompt and "Cũ C [3]." in prompt and "Cũ D [1]." in prompt
    assert "[4] test.kbweb" in prompt and "BÀI MỚI" in prompt
    got = await web_index.get(dossier_ids(PROJ.name))
    assert len(got) == 1
    assert got[0].text == "Giữ ý cũ [1]. Tin mới [2]."
    assert [s.url for s in got[0].sources] == [s2.url, new_url]


async def test_rebuild_bo_qua_ho_so_cu(web_pool, web_index):
    old = Item("CŨ KHÔNG ĐƯỢC ĐƯA LẠI [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC))
    await _seed(web_pool, f"{BASE}/cu", "Noble bài cũ", projects=[PROJ.name], age="30 days")
    deps = _deps(web_pool, web_index)
    assert (await refresh_project(deps, PROJ, MODE_REBUILD, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "CŨ KHÔNG ĐƯỢC ĐƯA LẠI" not in prompt and "Noble bài cũ" in prompt
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert [s.url for s in item.sources] == [f"{BASE}/cu"]


async def test_loi_tam_thoi_llm_lan_ra_ngoai(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])

    def busy(text):
        raise TemporaryError("LLM 503")

    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: busy}))
    with pytest.raises(TemporaryError):
        await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))


# ─── refresh_project: grounding ở lượt tuần / dựng ban đầu ───────────────────


def _cfg_topics(topics, target=100):
    return replace(mac_dinh.defaults(), topics=tuple(topics), target_per_topic=target)


def _topic(code, n, keywords=("khongkhopbaogio",)):
    return Topic(code, code, tuple(keywords), tuple(f"{code} {i} {{project}}" for i in range(n)))


def _unique_ok(url):
    return _ok(url, f"Noble trang {url}")


async def test_luot_tuan_chi_goi_grounding_cho_chu_de_thieu(web_pool, web_index):
    for i in range(5):
        await _seed(web_pool, f"{BASE}/road{i}", f"Noble Palace có đại lộ số {i}", projects=[PROJ.name])
    grounding = FakeGrounding()
    deps = _deps(web_pool, web_index, grounding=grounding)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    cfg = mac_dinh.defaults()
    fmt = {"project": PROJ.name, "location": "xã Tân Lập, huyện Đan Phượng, Hà Nội"}
    expected = [q.format(**fmt) for t in cfg.topics if t.code != "road" for q in t.queries[:2]]
    assert grounding.queries == expected
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.projects == (PROJ_LABEL,)


def _project(address, region, name="Dự án Địa Danh"):
    return ProjectRow(9, "DDD", name, region, address, "", ())


def _templates(cfg, *, with_location):
    # câu bị bỏ vì thiếu địa danh không tính vào chuỗi rỗng — mỗi chủ đề chạy tới EMPTY_STREAK_STOP câu còn lại
    return [
        q
        for t in cfg.topics
        for q in [q for q in t.queries if ("{location}" in q) == with_location][: pipeline.EMPTY_STREAK_STOP]
    ]


async def test_luot_tuan_cau_tim_dung_dia_danh_tu_dia_chi(web_pool, web_index):
    grounding = FakeGrounding()
    deps = _deps(web_pool, web_index, grounding=grounding)
    proj = _project("Số 88 đường Nguyễn Văn Linh, Quận 7, TP.HCM", "mien_nam")
    await refresh_project(deps, proj, MODE_WEEKLY, datetime.now(UTC))
    cfg = mac_dinh.defaults()
    loc = "đường Nguyễn Văn Linh, Quận 7, TP.HCM"
    expected = [q.format(project=proj.name, location=loc) for t in cfg.topics for q in t.queries[:2]]
    assert grounding.queries == expected
    assert "metro đường sắt đô thị đường Nguyễn Văn Linh, Quận 7, TP.HCM" in grounding.queries


async def test_du_an_khong_co_dia_chi_dung_region(web_pool, web_index):
    grounding = FakeGrounding()
    deps = _deps(web_pool, web_index, grounding=grounding)
    proj = _project("", "Hà Nội")
    await refresh_project(deps, proj, MODE_WEEKLY, datetime.now(UTC))
    assert "trường học gần Hà Nội" in grounding.queries


async def test_du_an_khong_co_dia_danh_chi_chay_cau_ten_du_an(web_pool, web_index):
    """Địa chỉ rỗng và region là `mien_*` ⇒ không có địa danh: bỏ mọi câu có `{location}`,
    câu chỉ có `{project}` vẫn chạy; hồ sơ không mang location và không tìm dự án lân cận."""
    await _seed(web_pool, f"{BASE}/nd/1", "Dự án Địa Danh mở bán", projects=["Dự án Địa Danh"], location=[])
    await _seed(web_pool, f"{BASE}/nd/2", "BÀI ĐAN PHƯỢNG có Wonder City", projects=["Wonder City"])
    grounding = FakeGrounding()
    deps = _deps(web_pool, web_index, grounding=grounding)
    proj = _project("", "mien_bac")
    assert (await refresh_project(deps, proj, MODE_WEEKLY, datetime.now(UTC))).count == 1
    cfg = mac_dinh.defaults()
    assert grounding.queries == [q.format(project=proj.name) for q in _templates(cfg, with_location=False)]
    assert all("{" not in q for q in grounding.queries)
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "BÀI ĐAN PHƯỢNG" not in prompt
    assert deps.llm.prompts(PROFILE_CARD) == []
    (item,) = await web_index.get(dossier_ids(proj.name))
    assert item.location == ()


async def test_ho_so_lay_bai_cung_xa_khong_lay_bai_chi_cung_tinh(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/xa/1", "BÀI TÂN LẬP", location=["Xã Tân Lập"])
    await _seed(web_pool, f"{BASE}/xa/2", "BÀI CHỈ HÀ NỘI", location=["Thành phố Hà Nội"])
    deps = _deps(web_pool, web_index, grounding=None)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "BÀI TÂN LẬP" in prompt and "BÀI CHỈ HÀ NỘI" not in prompt


def _card_names(llm):
    return sorted(p.split("DỰ ÁN: ")[1].split("\n")[0] for p in llm.prompts(PROFILE_CARD))


async def test_lan_can_du_o_cap_hep_thi_khong_mo_cap_rong(web_pool, web_index):
    for i in range(3):
        for k in range(2):
            await _seed(
                web_pool, f"{BASE}/lc/x{i}/{k}", f"Gần {i} mở bán", projects=[f"Gần {i}"], location=["xã Tân Lập"]
            )
    for k in range(2):
        await _seed(web_pool, f"{BASE}/lc/h/{k}", "Xa mở bán", projects=["Xa"], location=["huyện Đan Phượng"])
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert _card_names(deps.llm) == ["gần 0", "gần 1", "gần 2"]


async def test_lan_can_thieu_o_cap_hep_thi_mo_sang_cap_sau(web_pool, web_index):
    for k in range(2):
        await _seed(web_pool, f"{BASE}/lc/x/{k}", "Gần mở bán", projects=["Gần"], location=["Tân Lập"])
        await _seed(web_pool, f"{BASE}/lc/h/{k}", "Xa mở bán", projects=["Xa"], location=["Đan Phượng"])
        await _seed(web_pool, f"{BASE}/lc/t/{k}", "Tỉnh mở bán", projects=["Tỉnh"], location=["Hà Nội"])
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert _card_names(deps.llm) == ["gần", "xa"]


async def test_luot_tuan_moi_chu_de_toi_da_2_truy_van(web_pool, web_index):
    n = iter(range(10_000))

    def answer(q):
        return [f"{BASE}/g/{next(n)}"] if q.startswith("full") else []

    grounding = FakeGrounding(answer)
    cfg = _cfg_topics([_topic("full", 10), _topic("empty", 10)])
    deps = _deps(web_pool, web_index, cfg=cfg, fallback=_unique_ok, grounding=grounding)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    assert [q.split()[0] for q in grounding.queries] == ["full"] * pipeline.MAX_QUERIES_PER_TOPIC + ["empty"] * 2
    assert pipeline.MAX_QUERIES_PER_TOPIC == 2


async def test_luot_tuan_url_da_co_tinh_la_luot_rong(web_pool, web_index):
    known = f"{BASE}/g/known"
    await _seed(web_pool, known, "Noble đã có")
    grounding = FakeGrounding([known])
    deps = _deps(web_pool, web_index, cfg=_cfg_topics([_topic("a", 4)]), grounding=grounding)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert len(grounding.queries) == 2
    assert deps.fetcher.calls == []


async def test_luot_tuan_dung_khi_du_bai_cho_chu_de(web_pool, web_index):
    n = iter(range(10_000))
    grounding = FakeGrounding(lambda q: [f"{BASE}/g/{next(n)}"])
    cfg = _cfg_topics([_topic("a", 4, keywords=("trang",)), _topic("b", 4, keywords=("trang",))], target=2)
    deps = _deps(web_pool, web_index, cfg=cfg, fallback=_unique_ok, grounding=grounding)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    # hai bài của "a" cũng khớp từ khoá "b" nên "b" đã đủ, không truy vấn thêm
    assert [q.split()[0] for q in grounding.queries] == ["a", "a"]


async def test_luot_tuan_tran_60_truy_van_moi_du_an(web_pool, web_index):
    n = iter(range(10_000))
    grounding = FakeGrounding(lambda q: [f"{BASE}/g/{next(n)}"])
    cfg = _cfg_topics([_topic(f"t{i}", 4) for i in range(40)])
    deps = _deps(web_pool, web_index, cfg=cfg, fallback=_unique_ok, grounding=grounding)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert len(grounding.queries) == pipeline.MAX_QUERIES_PER_PROJECT == 60


async def test_luot_tuan_tran_150_trang_va_5_url_moi_truy_van(web_pool, web_index):
    n = iter(range(10_000))
    grounding = FakeGrounding(lambda q: [f"{BASE}/g/{next(n)}" for _ in range(8)])
    cfg = _cfg_topics([_topic(f"t{i}", 4) for i in range(20)])
    deps = _deps(web_pool, web_index, cfg=cfg, fallback=_unique_ok, grounding=grounding)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert len(deps.fetcher.calls) == pipeline.MAX_PAGES_PER_PROJECT == 150
    assert len(grounding.queries) == 30


async def test_het_ngan_sach_grounding_van_viet_ho_so(web_pool, web_index, logs):
    posts = []
    searched = []

    class CountingGrounding(Grounding):
        async def search(self, query):
            searched.append(query)
            return await super().search(query)

    def handler(request):
        posts.append(request)
        uri = f"{BASE}/gb/{len(posts)}"
        chunks = [{"web": {"uri": uri}}]
        return httpx.Response(200, json={"candidates": [{"groundingMetadata": {"groundingChunks": chunks}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        grounding = CountingGrounding(
            api_key="k", http=http, budget=GroundingBudget(None, cap=3), model="gemini-2.5-flash"
        )
        deps = _deps(web_pool, web_index, fallback=_unique_ok, grounding=grounding)
        assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    assert len(posts) == 3
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert f"{BASE}/gb/3" in deps.fetcher.calls and "trang https://test.kbweb/gb/1" in prompt
    assert len(searched) == 4, "hết trần thì dừng tìm cho dự án này, không lặp qua mọi chủ đề"
    exhausted = [r for r in logs.records if "hết trần grounding" in r.getMessage()]
    assert len(exhausted) == 1


async def test_grounding_loi_4xx_hay_json_hong_thi_bo_truy_van_do(web_pool, web_index, logs):
    n = iter(range(10_000))

    def answer(q):
        if q.startswith("a 0"):
            raise httpx.HTTPStatusError("400", request=httpx.Request("POST", "https://g"), response=httpx.Response(400))
        if q.startswith("b 0"):
            raise ValueError("JSON hỏng")
        return [f"{BASE}/g/{next(n)}"]

    grounding = FakeGrounding(answer)
    cfg = _cfg_topics([_topic("a", 3), _topic("b", 3)])
    deps = _deps(web_pool, web_index, cfg=cfg, fallback=_unique_ok, grounding=grounding)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    assert [q.split()[:2] for q in grounding.queries] == [["a", "0"], ["a", "1"], ["b", "0"], ["b", "1"]]
    assert len(deps.fetcher.calls) == 2
    assert sum("grounding" in r.getMessage() for r in logs.records) == 2


async def test_grounding_429_thi_dung_grounding_va_van_viet_ho_so(web_pool, web_index, logs):
    class Busy:
        def __init__(self):
            self.queries = []

        async def search(self, q):
            self.queries.append(q)
            raise TemporaryGroundingError("Gemini 429")

    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])
    grounding = Busy()
    deps = _deps(web_pool, web_index, grounding=grounding)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    assert len(grounding.queries) == 1, "429 thì dừng grounding cả lượt, không thử từng chủ đề"
    assert sum("429" in r.getMessage() for r in logs.records) == 1
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 1


async def test_grounding_mat_mang_thi_khong_viet_ho_so_de_job_chay_lai(web_pool, web_index):
    class Offline:
        def __init__(self):
            self.queries = []

        async def search(self, q):
            self.queries.append(q)
            raise GroundingUnreachable("ConnectError: Temporary failure in name resolution")

    grounding = Offline()
    deps = _deps(web_pool, web_index, grounding=grounding)
    with pytest.raises(GroundingUnreachable):
        await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert len(grounding.queries) == 1
    assert deps.llm.prompts(PROFILE_DOSSIER) == []
    assert await web_index.get(dossier_ids(PROJ.name)) == []


async def test_loi_tam_thoi_llm_khi_nap_bai_grounding_van_lan_ra_ngoai(web_pool, web_index):
    g = f"{BASE}/g/ban"
    deps = _deps(web_pool, web_index, pages={g: _ok(g, "QUÁ TẢI")}, grounding=FakeGrounding([g]))
    with pytest.raises(TemporaryError):
        await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))


async def test_khong_co_grounding_thi_luot_tuan_van_chay(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])
    deps = _deps(web_pool, web_index, grounding=None)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1


async def test_luot_tuan_khong_co_bai_nao_thi_khong_goi_llm(web_pool, web_index):
    deps = _deps(web_pool, web_index, grounding=FakeGrounding())
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 0
    assert deps.llm.asked == []


# ─── thẻ dự án lân cận ───────────────────────────────────────────────────────


async def test_the_lan_can_moi_ten_mot_the_dung_chung_giua_cac_du_an(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/wc1", "Wonder City bàn giao", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/wc2", "Wonder City mở bán", projects=["Wonder City"], fetched=NOW)
    await _seed(web_pool, f"{BASE}/np1", "Noble Palace mở bán", projects=[PROJ.name])
    await _seed(web_pool, f"{BASE}/np2", "Noble Palace bàn giao", projects=[PROJ.name])
    # location của thẻ do LLM trả (vị trí của chính dự án), không còn gộp từ nhãn bài nguồn
    llm = FakeLlm({PROFILE_CARD: lambda p: {**_card_answer(p), "location": ["huyện Đan Phượng"]}})
    deps = _deps(web_pool, web_index, llm=llm)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    card_prompts = llm.prompts(PROFILE_CARD)
    assert len(card_prompts) == 1 and "DỰ ÁN: wonder city" in card_prompts[0]
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.projects == ("wonder city",)
    assert [s.url for s in card.sources] == [f"{BASE}/wc2"]
    assert await web_index.get([card_id(PROJ.name)]) == []
    (prompt,) = llm.prompts(PROFILE_DOSSIER)
    assert "THẺ DỰ ÁN LÂN CẬN" not in prompt, "thẻ lân cận không vào prompt hồ sơ"
    (near,) = await web_index.get([near_id(PROJ.name)])
    assert "Wonder City" in near.text

    await refresh_project(deps, PROJ2, MODE_WEEKLY, datetime.now(UTC))
    names = [p.split("DỰ ÁN: ")[1].split("\n")[0] for p in llm.prompts(PROFILE_CARD)]
    assert names == ["wonder city", PROJ_LABEL]
    assert len(await web_index.get([card_id("Wonder City")])) == 1


async def test_ho_so_khong_lay_the_cua_chinh_du_an(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/np1", "Noble Palace mở bán", projects=[PROJ.name])
    src = (Source(f"{BASE}/x", "X", NOW),)
    await web_index.replace(
        [card_id(PROJ.name)], [Item("THẺ CỦA CHÍNH NÓ ở Đan Phượng [1]", src, (PROJ.name,), LOC)], NOW
    )
    await web_index.replace(
        [card_id("Wonder City")], [Item("THẺ WONDER ở Đan Phượng [1]", src, ("Wonder City",), LOC)], NOW
    )
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    (near,) = await web_index.get([near_id(PROJ.name)])
    assert "THẺ WONDER" in near.text and "THẺ CỦA CHÍNH NÓ" not in near.text
    assert deps.llm.prompts(PROFILE_CARD) == []


async def test_luot_dem_khong_dung_the_lan_can(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/np1", "Noble Palace mở bán", projects=[PROJ.name])
    src = (Source(f"{BASE}/x", "X", NOW),)
    await web_index.replace([card_id("Wonder City")], [Item("THẺ WONDER [1]", src, ("Wonder City",), LOC)], NOW)
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "THẺ WONDER" not in prompt


# ─── topic_counts ────────────────────────────────────────────────────────────


def _page(text):
    return Page(f"{BASE}/p", "test.kbweb", "", None, None, text, (), ())


def test_topic_counts_dem_theo_tu_khoa_nguyen_tu():
    leisure = Topic("leisure", "", ("hồ", "công viên"), ())
    road = Topic("road", "", ("đại lộ",), ())
    pages = [_page("thị trường hồi phục"), _page("Công Viên hồ điều hoà"), _page("ĐẠI LỘ Thăng Long")]
    assert topic_counts(pages, [leisure, road]) == {"leisure": 1, "road": 1}


# ─── open_deps ───────────────────────────────────────────────────────────────


@pytest.mark.filterwarnings("ignore:Qdrant client version")
async def test_open_deps_dung_tu_env(monkeypatch, api_dsn, qdrant_url, redis_url, web_tenant):
    monkeypatch.setenv("DATABASE_URL", api_dsn)
    monkeypatch.setenv("QDRANT_URL", qdrant_url)
    monkeypatch.setenv("QDRANT_API_KEY", "")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("KB_VLM_API_KEY", "khoa-gia")
    monkeypatch.setenv("KB_SANTA_MODELS_TOKEN", "khoa-gia")
    monkeypatch.setenv("KB_GEMINI_API_KEY", "")
    async with pipeline.open_deps() as rt:
        deps = await rt.for_tenant(TENANT)
        assert deps.grounding is None and deps.tenant == TENANT
        assert isinstance(deps.llm, WebLlm)
        assert deps.index.collection == f"{TENANT}_public_web"
        assert {s.domain for s in deps.cfg.sources} == {s.domain for s in mac_dinh.defaults().sources}
        async with deps.conn() as c:
            assert await c.fetchval("SELECT count(*) >= 0 FROM tenant_data.web_pages")
        assert await deps.index._c.collection_exists(deps.index.collection)
    monkeypatch.setenv("KB_GEMINI_API_KEY", "khoa-gia")
    async with pipeline.open_deps() as rt:
        deps = await rt.for_tenant(TENANT)
        assert isinstance(deps.grounding, Grounding)
        assert deps.grounding._budget._monthly_cap == 1000
    client = AsyncQdrantClient(url=qdrant_url, check_compatibility=False, timeout=60)
    await client.delete_collection(deps.index.collection)
    await client.close()


# ─── Fix round 1 ─────────────────────────────────────────────────────────────


async def test_bai_nap_trong_luot_tuan_khong_bi_gui_lai_o_luot_sau(web_pool, web_index):
    g = f"{BASE}/wm/g1"
    await _seed(web_pool, f"{BASE}/wm/wc", "Wonder City bàn giao", projects=["Wonder City"])
    grounding = FakeGrounding([g])
    deps = _deps(web_pool, web_index, pages={g: _ok(g, "Noble Palace cạnh Wonder City")}, grounding=grounding)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    assert len(deps.llm.prompts(PROFILE_CARD)) == 1
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.updated_at >= (await _row(web_pool, g))["fetched_at"]
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    deps.grounding = NoGrounding()
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, tomorrow)).count == 0
    deps.grounding = grounding
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, tomorrow)).count == 0
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 1
    assert len(deps.llm.prompts(PROFILE_CARD)) == 1


def _markers(prompt, tag):
    block = prompt.split("NGUỒN:\n", 1)[1]
    return sorted({int(m) for m in re.findall(rf"#{tag}(\d+)#", block)})


async def test_ho_so_gui_bai_theo_thu_tu_nap_va_khong_bo_sot(web_pool, web_index):
    for i in range(60):
        await _seed(web_pool, f"{BASE}/cap/{i}", f"#P{i:02d}# Noble", projects=[PROJ.name], age=f"{i} minutes")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    first, second = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(first, "P") == list(range(20, 60)), "40 bài nạp sớm nhất trước"
    assert _markers(second, "P") == list(range(20)), "phần còn lại ở lượt sau"
    assert len(first.split("NGUỒN:\n", 1)[1].split("#P")) - 1 == pipeline.MAX_PROMPT_PAGES == 40


async def test_ho_so_khong_cat_giua_nhom_cung_moc_nap(web_pool, web_index):
    t0 = datetime.now(UTC) - timedelta(hours=1)
    for i in range(38):
        await _seed(
            web_pool, f"{BASE}/tie/{i}", f"#T{i:02d}# Noble", projects=[PROJ.name], fetched=t0 + timedelta(seconds=i)
        )
    for i in range(38, 41):
        await _seed(
            web_pool, f"{BASE}/tie/{i}", f"#T{i:02d}# Noble", projects=[PROJ.name], fetched=t0 + timedelta(minutes=5)
        )
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    first, second = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(first, "T") == list(range(38)), "nhóm 3 bài cùng mốc không vừa trọn thì để cả nhóm cho lượt sau"
    assert _markers(second, "T") == [38, 39, 40]


async def test_nhom_cung_moc_lon_hon_tran_van_tien_len_va_canh_bao(web_pool, web_index, logs):
    same = datetime.now(UTC) - timedelta(hours=1)
    for i in range(45):
        await _seed(web_pool, f"{BASE}/tie/{i}", f"#T{i:02d}# Noble", projects=[PROJ.name], fetched=same)
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert len(_markers(prompt, "T")) == 40
    assert any("cùng mốc" in r.getMessage() for r in logs.records)


async def test_prompt_ho_so_giu_tran_ky_tu_nguon(web_pool, web_index):
    for i in range(40):
        await _seed(web_pool, f"{BASE}/cap/{i}", f"#C{i:02d}# " + "x" * 5000, projects=[PROJ.name], age=f"{i} minutes")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    first, second = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(first, "C") == list(range(10, 40))
    assert 30 * 4000 <= pipeline.MAX_PROMPT_CHARS == 120_000
    assert len(first.split("NGUỒN:\n", 1)[1]) < pipeline.MAX_PROMPT_CHARS + 30 * 200
    assert _markers(second, "C") == list(range(10))


async def test_the_lan_can_cung_gui_bai_theo_thu_tu_nap(web_pool, web_index):
    for i in range(45):
        await _seed(web_pool, f"{BASE}/wcap/{i}", f"#W{i:02d}# Wonder", projects=["Wonder City"], age=f"{i} minutes")
    await _seed(web_pool, f"{BASE}/np1", "Noble Palace", projects=[PROJ.name])
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    first, second = deps.llm.prompts(PROFILE_CARD)
    assert _markers(first, "W") == list(range(5, 45))
    assert _markers(second, "W") == list(range(5))


async def test_prompt_ban_tin_cung_bi_gioi_han(web_pool, web_index):
    for i in range(60):
        await _seed(
            web_pool, f"{BASE}/dg/{i}", f"#D{i:02d}# tin", published=datetime.now(UTC) - timedelta(minutes=i + 1)
        )
    deps = _deps(web_pool, web_index)
    await build_digest(deps, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DIGEST)
    assert _markers(prompt, "D") == list(range(40))


async def test_recheck_living_trang_loi_van_danh_dau_da_kiem(web_pool, web_index, logs):
    bad, same, gone, good = (f"{BASE}/living/{x}" for x in ("hong", "giu", "mat", "tot"))
    for u in (bad, same, gone, good):
        await _seed(web_pool, u, "nội dung cũ", age="40 days", h=content_hash("nội dung cũ"))
    cfg = replace(mac_dinh.defaults(), sources=(_site("test.kbweb", kind="living"),))
    pages = {bad: _ok(bad, "JSON HỎNG"), same: _ok(same, "nội dung cũ"), good: _ok(good, "Noble mới")}
    deps = _deps(web_pool, web_index, cfg=cfg, pages=pages)
    now = datetime.now(UTC)
    assert await recheck_living(deps, now) == 1
    assert deps.llm.tagged == ["JSON HỎNG", "Noble mới"], "nội dung không đổi thì không gắn nhãn lại"
    for u in (bad, same, gone, good):
        assert (await _row(web_pool, u))["last_checked_at"] > now - timedelta(minutes=5), u
    assert (await _row(web_pool, bad))["content_text"] == "nội dung cũ"
    assert (await _row(web_pool, gone))["status"] == "ok"
    assert any("JSON" in r.getMessage() for r in logs.records)
    async with tenant_conn(web_pool, TENANT) as c:
        assert await repo.living_due(c, ["test.kbweb"], now - timedelta(days=30)) == []


async def test_recheck_living_loi_tam_thoi_lan_ra_ngoai(web_pool, web_index):
    url = f"{BASE}/living/ban"
    await _seed(web_pool, url, "cũ", age="40 days")
    cfg = replace(mac_dinh.defaults(), sources=(_site("test.kbweb", kind="living"),))
    deps = _deps(web_pool, web_index, cfg=cfg, pages={url: _ok(url, "QUÁ TẢI")})
    with pytest.raises(TemporaryError):
        await recheck_living(deps, datetime.now(UTC))


async def test_the_lan_can_khong_co_ten_du_an_bi_bo_qua(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/np1", "Noble Palace mở bán", projects=[PROJ.name])
    src = (Source(f"{BASE}/x", "X", NOW),)
    orig = web_index.cards_near

    async def with_blank(location, exclude, limit=20, **kw):
        return [Item("THẺ KHÔNG TÊN [1]", src, (), LOC), *await orig(location, exclude, limit, **kw)]

    web_index.cards_near = with_blank
    deps = _deps(web_pool, web_index)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "THẺ KHÔNG TÊN" not in prompt


# ─── Fix round 2 ─────────────────────────────────────────────────────────────


async def test_cap_nhat_bo_muc_cu_cua_chu_de_da_tat_hoac_da_xoa(web_pool, web_index):
    src = (Source(f"{BASE}/old", "Báo", NOW),)
    old = [
        Item("Tiện ích – Y tế: Bệnh viện Thu Cúc [1].", src, (PROJ.name,), ()),
        Item("Phong thủy: Hướng Đông Nam [1].", src, (PROJ.name,), ()),
        Item("Pháp lý: Đã có giấy phép xây dựng [1].", src, (PROJ.name,), ()),
        Item("Cách Mỹ Đình 15 phút [1].", src, (PROJ.name,), ()),
    ]
    await web_index.replace(dossier_ids(PROJ.name), old, datetime.now(UTC) - timedelta(days=1))
    await _seed(web_pool, f"{BASE}/moi", "BÀI MỚI Noble", projects=[PROJ.name])
    cfg = mac_dinh.defaults()
    cfg = replace(cfg, topics=tuple(t for t in cfg.topics if t.code != "healthcare"))
    deps = _deps(web_pool, web_index, cfg=cfg, llm=FakeLlm({PROFILE_DOSSIER: {"items": []}}))
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "Bệnh viện Thu Cúc" not in prompt and "Hướng Đông Nam" not in prompt
    assert "Đã có giấy phép xây dựng" in prompt and "Cách Mỹ Đình 15 phút" in prompt


async def test_ho_so_toi_da_25_muc(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])
    many = {"items": [{"text": f"Mục {i} [1].", "cites": [1]} for i in range(30)]}
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: many}))
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 25
    assert len(await web_index.get(dossier_ids(PROJ.name))) == 25


@pytest.mark.parametrize("code", [401, 403])
async def test_grounding_sai_khoa_thi_dung_ngay(web_pool, web_index, logs, code):
    def answer(q):
        raise httpx.HTTPStatusError(
            str(code), request=httpx.Request("POST", "https://g"), response=httpx.Response(code)
        )

    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])
    grounding = FakeGrounding(answer)
    deps = _deps(web_pool, web_index, grounding=grounding)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))).count == 1
    assert len(grounding.queries) == 1
    assert sum(str(code) in r.getMessage() for r in logs.records) == 1


# ─── Fix round 3 ─────────────────────────────────────────────────────────────


async def _seed_backlog(web_pool, n, *, start_days=10, span_days=5):
    t0 = datetime.now(UTC) - timedelta(days=start_days)
    step = timedelta(days=span_days) / n
    for i in range(n):
        await _seed(web_pool, f"{BASE}/bk/{i}", f"#B{i:03d}# Noble", projects=[PROJ.name], fetched=t0 + step * i)


async def test_init_dung_nhieu_luot_cu_truoc_moi_sau(web_pool, web_index):
    await _seed_backlog(web_pool, 100)
    deps = _deps(web_pool, web_index)
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 1
    prompts = deps.llm.prompts(PROFILE_DOSSIER)
    chunks = [_markers(p, "B") for p in prompts]
    assert chunks == [list(range(0, 20)), list(range(20, 60)), list(range(60, 100))], "bài mới nhất ở lượt cuối"
    assert "HỒ SƠ HIỆN CÓ:\n(chưa có)" in prompts[0] and "Đại lộ thông xe" in prompts[1], "lượt sau mang mục lượt trước"
    deps.grounding = NoGrounding()
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC) + timedelta(days=1))).count == 0
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 3


async def test_init_chi_dung_200_bai_moi_nhat_va_bo_qua_ton_dong_cu(web_pool, web_index):
    await _seed_backlog(web_pool, 250)
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    chunks = [_markers(p, "B") for p in deps.llm.prompts(PROFILE_DOSSIER)]
    assert len(chunks) == pipeline.MAX_BUILD_PASSES == 5
    assert chunks[0] == list(range(50, 90)) and chunks[-1] == list(range(210, 250))
    async with tenant_conn(web_pool, TENANT) as c:
        newest = await c.fetchval(
            "SELECT max(fetched_at) FROM tenant_data.web_pages WHERE $1 = ANY(projects)", PROJ_LABEL
        )
    assert {it.updated_at for it in await web_index.get(dossier_ids(PROJ.name))} == {newest}
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 5, "tồn đọng cũ bị bỏ có chủ ý, lượt tuần không nhặt lại"


async def test_init_chon_theo_ngay_dang_va_watermark_la_bai_nap_moi_nhat(web_pool, web_index):
    t0 = datetime.now(UTC) - timedelta(days=30)
    for i in range(205):
        await _seed(
            web_pool,
            f"{BASE}/pub/{i:03d}",
            f"#Q{i:03d}# Noble",
            projects=[PROJ.name],
            published=t0 + timedelta(hours=i),
            fetched=datetime.now(UTC) - timedelta(minutes=i + 1),
        )
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    prompts = deps.llm.prompts(PROFILE_DOSSIER)
    assert [_markers(p, "Q") for p in prompts] == [list(range(k, k + 40)) for k in range(5, 205, 40)]
    order = [int(m) for m in re.findall(r"#Q(\d+)#", prompts[0].split("NGUỒN:\n", 1)[1])]
    assert order == sorted(order), "trong một lượt, bài cũ trước bài mới"
    (first, *_) = await web_index.get(dossier_ids(PROJ.name))
    assert first.updated_at == (await _row(web_pool, f"{BASE}/pub/000"))["fetched_at"]
    deps.grounding = NoGrounding()
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0


async def test_rebuild_cung_dung_nhieu_luot_tu_dau(web_pool, web_index):
    await _seed_backlog(web_pool, 50)
    old = Item("CŨ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC))
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_REBUILD, datetime.now(UTC))
    chunks = [_markers(p, "B") for p in deps.llm.prompts(PROFILE_DOSSIER)]
    assert chunks == [list(range(10)), list(range(10, 50))]


async def test_luot_dem_sau_5_ngay_gian_doan_gui_tu_watermark(web_pool, web_index):
    old = Item("cũ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC) - timedelta(days=5))
    await _seed(web_pool, f"{BASE}/gap/cu", "#G01# Noble", projects=[PROJ.name], age="4 days")
    await _seed(web_pool, f"{BASE}/gap/moi", "#G02# Noble", projects=[PROJ.name], age="1 hour")
    await _seed(web_pool, f"{BASE}/gap/da-dung", "#G00# Noble", projects=[PROJ.name], age="6 days")
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(prompt, "G") == [1, 2]


async def test_nhom_cung_moc_bi_tach_ghi_loi_kem_url(web_pool, web_index, logs):
    same = datetime.now(UTC) - timedelta(hours=1)
    for i in range(45):
        await _seed(web_pool, f"{BASE}/tie/{i:02d}", f"#T{i:02d}# Noble", projects=[PROJ.name], fetched=same)
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    (rec,) = [r for r in logs.records if "cùng mốc" in r.getMessage()]
    assert rec.levelname == "ERROR"
    assert "5 bài" in rec.getMessage() and f"{BASE}/tie/40" in rec.getMessage()


# ─── Final review fixes ──────────────────────────────────────────────────────


@pytest.mark.parametrize("error", [TruncatedLlmError("bị cắt"), ValueError("JSON hỏng")])
async def test_ho_so_bi_cat_hay_json_hong_thi_giu_ho_so_cu_khong_nem(web_pool, web_index, logs, error):
    old = Item("cũ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    written = datetime.now(UTC) - timedelta(days=1)
    await web_index.replace(dossier_ids(PROJ.name), [old], written)
    await _seed(web_pool, f"{BASE}/moi", "Noble tin mới", projects=[PROJ.name])

    def broken(text):
        raise error

    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: broken}))
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.text == "cũ [1]" and item.updated_at == written
    (rec,) = [r for r in logs.records if r.levelname == "ERROR"]
    assert PROJ.name in rec.getMessage()


async def test_init_bi_cat_giua_chung_thi_dung_giu_luot_da_ghi(web_pool, web_index, logs):
    await _seed_backlog(web_pool, 100)
    calls = iter(range(100))

    def second_cut(text):
        if next(calls) == 1:
            raise TruncatedLlmError("bị cắt")
        return {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]}

    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: second_cut}))
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 1
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 2
    assert len(await web_index.get(dossier_ids(PROJ.name))) == 1


async def test_ban_tin_bi_cat_thi_giu_ban_cu_khong_nem(web_pool, web_index, logs):
    now = datetime.now(UTC)
    await _seed(web_pool, f"{BASE}/dg-cut", "tin giá", published=now - timedelta(hours=1))
    src = (Source(f"{BASE}/x", "X", NOW),)
    await web_index.replace(digest_ids(DIGEST_REGION), [Item("BẢN CŨ [1]", src, (), ())], now - timedelta(days=1))

    def cut(text):
        raise TruncatedLlmError("bị cắt")

    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DIGEST: cut}))
    assert await build_digest(deps, now) == 0
    assert [i.text for i in await web_index.get(digest_ids(DIGEST_REGION))] == ["BẢN CŨ [1]"]
    assert any(r.levelname == "ERROR" for r in logs.records)


async def test_ban_tin_chi_lay_bai_sitemap_rss_dang_trong_24h(web_pool, web_index):
    now = datetime.now(UTC)
    await _seed(web_pool, f"{BASE}/bt/a", "#E1# tin", published=now - timedelta(minutes=20))
    await _seed(web_pool, f"{BASE}/bt/b", "#E2# tin", published=now - timedelta(minutes=30), found_via="rss")
    await _seed(web_pool, f"{BASE}/bt/c", "#E3# tin", published=now - timedelta(hours=1), found_via="grounding")
    await _seed(web_pool, f"{BASE}/bt/d", "#E4# tin")
    await _seed(web_pool, f"{BASE}/bt/e", "#E5# tin", published=now - timedelta(days=3))
    deps = _deps(web_pool, web_index)
    await build_digest(deps, now)
    (prompt,) = deps.llm.prompts(PROFILE_DIGEST)
    assert _markers(prompt, "E") == [1, 2]


async def test_crawl_day_trang_khong_co_ngay_thi_lay_ngay_cua_sitemap(web_pool, web_index):
    a, b = f"{BASE}/cdw/a", f"{BASE}/cdw/b"
    when_a = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
    own_b = datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
    cfg = replace(mac_dinh.defaults(), sources=(_site("one.kbweb"),))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={a: Fetched(a, "ok", "t", "Noble Palace a", None), b: Fetched(b, "ok", "t", "Noble Palace b", own_b)},
        discover=FakeDiscover({"one.kbweb": [Entry(a, when_a), Entry(b, when_a)]}),
    )
    assert await crawl_day(deps, date(2026, 9, 28)) == 2
    assert (await _row(web_pool, a))["published_at"] == when_a
    assert (await _row(web_pool, b))["published_at"] == own_b, "ngày trong trang thắng ngày sitemap"


async def test_ingest_urls_nhan_ngay_du_phong_theo_url(web_pool, web_index):
    url = f"{BASE}/when/x"
    when = datetime(2026, 9, 1, tzinfo=UTC)
    deps = _deps(web_pool, web_index, pages={url: Fetched(url, "ok", "t", "Noble Palace", None)})
    (page,) = await ingest_urls(deps, [f"{url}?utm_source=x"], found_via="sitemap", when={f"{url}?utm_source=x": when})
    assert page.published_at == when
    assert (await _row(web_pool, url))["published_at"] == when


async def test_luot_dem_duoi_5_bai_cung_vung_khong_gan_ten_thi_khong_viet_lai(web_pool, web_index):
    old = Item("cũ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    written = datetime.now(UTC) - timedelta(days=1)
    await web_index.replace(dossier_ids(PROJ.name), [old], written)
    for i in range(pipeline.NIGHTLY_MIN_AREA_PAGES - 1):
        await _seed(web_pool, f"{BASE}/vung/{i}", f"bài vùng {i}")
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    assert deps.llm.asked == []
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.updated_at == written


async def test_luot_dem_du_5_bai_cung_vung_thi_viet_lai(web_pool, web_index):
    assert pipeline.NIGHTLY_MIN_AREA_PAGES == 5
    for i in range(5):
        await _seed(web_pool, f"{BASE}/vung/{i}", f"bài vùng {i}")
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    assert len(deps.llm.prompts(PROFILE_DOSSIER)) == 1


async def test_luot_dem_mot_bai_gan_ten_cung_bai_vung_thi_viet_lai(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/vung/0", "bài vùng")
    await _seed(web_pool, f"{BASE}/ten/0", "Noble mới", projects=[PROJ.name])
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1


async def test_bai_dang_cu_hon_han_giu_van_duoc_gan_nhan_va_luu(web_pool, web_index):
    url = f"{BASE}/cu-qua/x"
    stale = datetime.now(UTC) - timedelta(days=repo.KEEP_DAYS + 5)
    deps = _deps(web_pool, web_index, pages={url: Fetched(url, "ok", "t", "Noble Palace năm xưa", stale)})
    assert [p.url for p in await ingest_urls(deps, [url], found_via="grounding")] == [url]
    row = await _row(web_pool, url)
    assert row["status"] == "ok" and row["content_text"] == "Noble Palace năm xưa"


async def test_bai_ngay_gan_han_giu_van_duoc_gan_nhan(web_pool, web_index):
    url = f"{BASE}/cu-qua/y"
    edge = datetime.now(UTC) - timedelta(days=repo.KEEP_DAYS - 5)
    deps = _deps(web_pool, web_index, pages={url: Fetched(url, "ok", "t", "Noble Palace", edge)})
    assert [p.url for p in await ingest_urls(deps, [url], found_via="grounding")] == [url]


async def test_recheck_living_thanh_khong_lien_quan_thi_bo_noi_dung(web_pool, web_index):
    url = f"{BASE}/living/lac-de"
    await _seed(web_pool, url, "Noble cũ", projects=[PROJ.name], age="40 days")
    cfg = replace(mac_dinh.defaults(), sources=(_site("test.kbweb", kind="living"),))
    deps = _deps(web_pool, web_index, cfg=cfg, pages={url: _ok(url, "tin bóng đá")})
    assert await recheck_living(deps, datetime.now(UTC)) == 1
    row = await _row(web_pool, url)
    assert row["status"] == "irrelevant"
    assert row["content_text"] is None
    assert list(row["projects"]) == [] and list(row["location"]) == []


# ─── Fix round 2 (re-review) ─────────────────────────────────────────────────


async def test_ngay_chi_co_ngay_cua_trang_nhuong_gio_chinh_xac_cua_sitemap(web_pool, web_index):
    same, other = f"{BASE}/ngay/cung", f"{BASE}/ngay/khac"
    precise = datetime(2026, 9, 28, 14, 19, tzinfo=VN)
    cfg = replace(mac_dinh.defaults(), sources=(_site("one.kbweb"),))
    deps = _deps(
        web_pool,
        web_index,
        cfg=cfg,
        pages={
            same: Fetched(same, "ok", "t", "Noble Palace cùng ngày", parse_when("2026-09-28")),
            other: Fetched(other, "ok", "t", "Noble Palace khác ngày", parse_when("2026-09-20")),
        },
        discover=FakeDiscover({"one.kbweb": [Entry(same, precise), Entry(other, precise)]}),
    )
    await crawl_day(deps, date(2026, 9, 28))
    assert (await _row(web_pool, same))["published_at"] == precise
    assert (await _row(web_pool, other))["published_at"] == parse_when("2026-09-20"), "khác ngày thì giữ ngày trang"


async def test_ban_tin_luc_1h10_lay_bai_hom_qua_chi_co_ngay(web_pool, web_index):
    today = datetime.now(VN).date()
    now = datetime.combine(today, time(1, 10), tzinfo=VN)
    yesterday = today - timedelta(days=1)
    await _seed(web_pool, f"{BASE}/bt1/a", "#H1# tin", published=parse_when(yesterday.isoformat()))
    await _seed(web_pool, f"{BASE}/bt1/b", "#H2# tin", published=datetime.combine(yesterday, time(21), tzinfo=VN))
    await _seed(
        web_pool, f"{BASE}/bt1/c", "#H3# tin", published=parse_when((yesterday - timedelta(days=1)).isoformat())
    )
    await _seed(web_pool, f"{BASE}/bt1/d", "#H4# tin", published=now + timedelta(hours=2))
    deps = _deps(web_pool, web_index)
    await build_digest(deps, now.astimezone(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DIGEST)
    assert _markers(prompt, "H") == [1, 2]


def _cut_on(call_no):
    calls = iter(range(1000))

    def answer(text):
        if next(calls) == call_no:
            raise TruncatedLlmError("bị cắt")
        return {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]}

    return answer


async def test_init_bi_cat_luot_cuoi_thi_luot_sau_gui_lai_phan_chua_gui(web_pool, web_index):
    await _seed_backlog(web_pool, 100)
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: _cut_on(2)}))
    r = await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    assert (r.count, r.kept_old) == (1, "trả lời LLM bị cắt")
    first_unsent = (await _row(web_pool, f"{BASE}/bk/60"))["fetched_at"]
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.updated_at == first_unsent - timedelta(microseconds=1)
    deps.llm.answers[PROFILE_DOSSIER] = {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]}
    deps.grounding = NoGrounding()
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    assert _markers(deps.llm.prompts(PROFILE_DOSSIER)[-1], "B") == list(range(60, 100))


async def test_rebuild_bi_cat_thi_luot_sau_gui_lai_du_watermark_cu_cao_hon(web_pool, web_index):
    await _seed_backlog(web_pool, 100)
    old = Item("CŨ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], datetime.now(UTC) - timedelta(days=1))
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: _cut_on(1)}))
    assert (await refresh_project(deps, PROJ, MODE_REBUILD, datetime.now(UTC))).count == 1
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.updated_at == (await _row(web_pool, f"{BASE}/bk/20"))["fetched_at"] - timedelta(microseconds=1)
    deps.llm.answers[PROFILE_DOSSIER] = {"items": [{"text": "Đại lộ thông xe [1].", "cites": [1]}]}
    deps.grounding = NoGrounding()
    await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    assert _markers(deps.llm.prompts(PROFILE_DOSSIER)[-1], "B") == list(range(20, 60))


async def test_init_tren_ho_so_co_san_khong_ha_watermark_duoi_ho_so_cu(web_pool, web_index):
    await _seed_backlog(web_pool, 100)
    prev = datetime.now(UTC) - timedelta(days=1)
    old = Item("CŨ [1]", (Source(f"{BASE}/old", "X", NOW),), (PROJ.name,), ())
    await web_index.replace(dossier_ids(PROJ.name), [old], prev)
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: _cut_on(1)}))
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 1
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.updated_at == prev


async def test_ket_qua_phan_biet_giu_ho_so_cu_va_khong_co_gi_de_viet(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/kq/1", "Noble mới", projects=[PROJ.name])

    def bad_json(text):
        raise ValueError("JSON hỏng")

    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: bad_json}))
    r = await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    assert (r.count, r.kept_old) == (0, "trả lời LLM không đọc được")
    deps.llm.answers[PROFILE_DOSSIER] = {"items": []}
    r = await refresh_project(deps, PROJ, MODE_NIGHTLY, datetime.now(UTC))
    assert (r.count, r.kept_old) == (0, "")


# ─── dòng "(Cập nhật dd/mm/yyyy)" ────────────────────────────────────────────

EVE = datetime(2026, 9, 29, 17, 30, tzinfo=UTC)  # 30/09 giờ VN
PREFIX_EVE = "(Cập nhật 30/09/2026)\n"


async def _raw_texts(web_index, ids):
    points = await web_index._c.retrieve(web_index.collection, ids=list(ids), with_payload=True)
    return [p.payload["text"] for p in points]


async def test_moi_loai_point_mang_dong_cap_nhat_ngay_vn_cua_lan_ghi(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/pf/wc", "Wonder City bàn giao", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/pf/wc0", "Wonder City mở bán", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/pf/np", "Noble Palace mở bán", projects=[PROJ.name])
    await _seed(web_pool, f"{BASE}/pf/dg", "tin giá", published=EVE - timedelta(hours=1))
    deps = _deps(web_pool, web_index)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, EVE)).count == 1
    assert await build_digest(deps, EVE) == 1
    texts = {
        "dossier": await _raw_texts(web_index, dossier_ids(PROJ.name)),
        "card": await _raw_texts(web_index, [card_id("Wonder City")]),
        "digest": await _raw_texts(web_index, digest_ids(DIGEST_REGION)),
    }
    for kind, got in texts.items():
        assert got, kind
        for t in got:
            assert t.startswith(PREFIX_EVE), (kind, t)
            assert t.count("(Cập nhật") == 1, (kind, t)
    (item,) = await web_index.get(dossier_ids(PROJ.name))
    assert item.text == "Đại lộ thông xe [1]."
    assert item.updated_at != EVE  # watermark (mốc nạp), không phải giờ ghi


async def test_ghi_lan_hai_llm_khong_thay_dong_cap_nhat_va_khong_lap_dong(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/pf2/wc", "Wonder City bàn giao", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/pf2/wc0", "Wonder City mở bán", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/pf2/np", "Noble Palace mở bán", projects=[PROJ.name])
    copied = {"items": [{"text": "(Cập nhật 30/09/2026)\nĐại lộ thông xe [1].", "cites": [1]}]}
    llm = FakeLlm()
    deps = _deps(web_pool, web_index, llm=llm)
    await refresh_project(deps, PROJ, MODE_WEEKLY, EVE)
    await _seed(web_pool, f"{BASE}/pf2/wc2", "Wonder City tin mới", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/pf2/np2", "Noble Palace tin mới", projects=[PROJ.name])
    llm.answers[PROFILE_DOSSIER] = copied
    next_day = EVE + timedelta(days=1)
    assert (await refresh_project(deps, PROJ, MODE_WEEKLY, next_day)).count == 1
    dossier_prompt = llm.prompts(PROFILE_DOSSIER)[-1]
    card_prompt = llm.prompts(PROFILE_CARD)[-1]
    assert "HỒ SƠ HIỆN CÓ:\nĐại lộ thông xe [" in dossier_prompt
    assert "THẺ HIỆN CÓ:\nThẻ dự án wonder city ở Đan Phượng [" in card_prompt
    assert "(Cập nhật" not in dossier_prompt and "(Cập nhật" not in card_prompt
    for t in [
        *await _raw_texts(web_index, dossier_ids(PROJ.name)),
        *await _raw_texts(web_index, [card_id("Wonder City")]),
    ]:
        assert t.startswith("(Cập nhật 01/10/2026)\n") and t.count("(Cập nhật") == 1, t


# ─── sau lượt chạy thật 2026-10-01: tên dự án chuẩn hoá, thẻ lân cận sạch hơn ──

GOLDEN = ProjectRow(
    31, "VGC", "VINHOMES GOLDEN CITY", "Hải Phòng", "Phường Dương Kinh & 1 phần xã Kiến Minh  TP. Hải Phòng", "", ()
)
ROYAL = ProjectRow(32, "VRI", "Vinhomes Royal Island", "Hải Phòng", "Xã Vũ Yên, Hải Phòng", "", ())
VY = ["Vũ Yên"]


async def test_ten_du_an_in_hoa_lay_bai_gan_nhan_bien_the_co_duoi(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/vgc/1", "BÀI DƯƠNG KINH", projects=["Vinhomes Golden City Dương Kinh"], location=[])
    await _seed(web_pool, f"{BASE}/vgc/2", "BÀI GỐC", projects=["Vinhomes Golden City"], location=[])
    await _seed(web_pool, f"{BASE}/vgc/3", "BÀI KHÁC", projects=["Vinhomes Golden Cityx"], location=[])
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    assert (await refresh_project(deps, GOLDEN, MODE_NIGHTLY, datetime.now(UTC))).count == 1
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert "BÀI DƯƠNG KINH" in prompt and "BÀI GỐC" in prompt and "BÀI KHÁC" not in prompt
    (item,) = await web_index.get(dossier_ids("Vinhomes Golden City"))
    assert item.projects == ("vinhomes golden city",)
    assert item.location == ("dương kinh",)


async def test_luot_dem_bai_gan_bien_the_tinh_la_bai_gan_ten(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/vop3/1", "BÀI CROWN", projects=["Vinhomes Ocean Park 3 - The Crown"], location=[])
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    proj = _project("", "mien_bac", name="VINHOMES OCEAN PARK 3")
    assert (await refresh_project(deps, proj, MODE_NIGHTLY, datetime.now(UTC))).count == 1


async def test_vop_khong_lay_bai_vop2(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/vop2/1", "BÀI VOP2", projects=["Vinhomes Ocean Park 2"], location=[])
    deps = _deps(web_pool, web_index, grounding=NoGrounding())
    proj = _project("", "mien_bac", name="Vinhomes Ocean Park")
    assert (await refresh_project(deps, proj, MODE_NIGHTLY, datetime.now(UTC))).count == 0
    assert deps.llm.prompts(PROFILE_DOSSIER) == []


async def _seed_near(web_pool, name, n=2, key="nb"):
    for i in range(n):
        await _seed(web_pool, f"{BASE}/{key}/{name}/{i}", f"{name} mở bán đợt {i}", projects=[name], location=VY)


async def test_the_lan_can_bo_ten_cung_du_an_va_ten_chi_mot_bai(web_pool, web_index):
    await _seed_near(web_pool, "Royal Island")
    await _seed_near(web_pool, "Vinhomes Royal Island Phân Khu Đảo Vua")
    await _seed_near(web_pool, "Một Bài", n=1)
    await _seed_near(web_pool, "Wonder City")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    assert _card_names(deps.llm) == ["wonder city"]


async def test_the_khong_nhac_ten_du_an_thi_khong_ghi(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    llm = FakeLlm({PROFILE_CARD: {"text": "Vinhomes Royal Island có bến du thuyền [1].", "cites": [1]}})
    deps = _deps(web_pool, web_index, llm=llm)
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    assert len(llm.prompts(PROFILE_CARD)) == 1
    assert await web_index.get([card_id("Wonder City")]) == []


async def test_the_chi_giu_muc_nhac_ten_du_an(web_pool, web_index):
    await _seed_near(web_pool, "Vinhomes Golden City")
    answer = {
        "items": [
            {"text": "Royal Island có bến du thuyền [1].", "cites": [1]},
            {"text": "Golden City có 2.000 căn ở Hải Phòng [1].", "cites": [1]},
        ],
        "location": ["Hải Phòng"],
    }
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_CARD: answer}))
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    (card,) = await web_index.get([card_id("Vinhomes Golden City")])
    assert card.text == "Golden City có 2.000 căn ở Hải Phòng [1]."
    assert card.projects == ("vinhomes golden city",)


async def test_the_llm_tra_items_rong_thi_khong_ghi(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_CARD: {"items": []}}))
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    assert await web_index.get([card_id("Wonder City")]) == []
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert await web_index.get([near_id(ROYAL.name)]) == []


async def test_ho_so_khong_lay_the_bien_the_cua_chinh_du_an(web_pool, web_index):
    await _seed_near(web_pool, "Vinhomes Royal Island")
    src = (Source(f"{BASE}/x", "X", NOW),)
    await web_index.replace(
        [card_id("Royal Island")], [Item("THẺ ROYAL ở Vũ Yên [1]", src, ("Royal Island",), VY)], NOW
    )
    await web_index.replace([card_id("Wonder City")], [Item("THẺ WONDER ở Vũ Yên [1]", src, ("Wonder City",), VY)], NOW)
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    (near,) = await web_index.get([near_id(ROYAL.name)])
    assert "THẺ WONDER" in near.text and "THẺ ROYAL" not in near.text


async def test_the_lan_can_bo_trung_bien_the_giu_ten_goc(web_pool, web_index):
    for name in ("Vinhomes Golden City Dương Kinh", "Vinhomes Golden City", "Wonder City"):
        await _seed_near(web_pool, name, n=3 if "Dương Kinh" in name else 2)
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, ROYAL, MODE_WEEKLY, datetime.now(UTC))
    assert _card_names(deps.llm) == ["vinhomes golden city", "wonder city"]


async def test_cau_grounding_dung_ten_bo_ngoac_giu_hoa_thuong(web_pool, web_index):
    grounding = FakeGrounding()
    deps = _deps(web_pool, web_index, grounding=grounding)
    proj = _project("", "Hà Nội", name="VINHOMES GLOBAL GATE (TMDV)")
    await refresh_project(deps, proj, MODE_WEEKLY, datetime.now(UTC))
    assert grounding.queries
    assert all("(TMDV)" not in q for q in grounding.queries)
    assert any("VINHOMES GLOBAL GATE" in q for q in grounding.queries)


# ─── location của thẻ = vị trí dự án; của bản tin = nhãn chung các nguồn ────


async def test_the_lay_location_llm_tra_khong_gop_nhan_bai_nguon(web_pool, web_index):
    await _seed_near(web_pool, "Vinhomes Royal Island")
    answer = {
        "text": "Vinhomes Royal Island nằm trên đảo Vũ Yên, Thủy Nguyên, Hải Phòng [1].",
        "cites": [1],
        "location": ["Xã Vũ Yên", "Thành phố Thủy Nguyên", "Hải Phòng"],
    }
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_CARD: answer}))
    await pipeline._refresh_card(deps, "Vinhomes Royal Island", datetime.now(UTC))
    (card,) = await web_index.get([card_id("Vinhomes Royal Island")])
    assert card.location == ("vũ yên", "thủy nguyên", "hải phòng")


async def test_the_llm_khong_tra_location_thi_giu_location_the_cu_toi_da_4(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    src = (Source(f"{BASE}/x", "X", NOW),)
    old_loc = ("Tân Lập", "Đan Phượng", "Hà Nội", "Tây Hà Nội", "Hoài Đức", "Vũ Yên")
    await web_index.replace([card_id("Wonder City")], [Item("Wonder City cũ [1]", src, ("Wonder City",), old_loc)], NOW)
    no_loc = {"text": "Thẻ dự án Wonder City ở Tân Lập, Đan Phượng, Hà Nội, Tây Hà Nội [1].", "cites": [1]}
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_CARD: no_loc}))
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.text == "Thẻ dự án Wonder City ở Tân Lập, Đan Phượng, Hà Nội, Tây Hà Nội [1]."
    assert card.location == ("tân lập", "đan phượng", "hà nội", "tây hà nội")


async def test_the_moi_khong_co_vi_tri_thi_khong_ghi(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    llm = FakeLlm({PROFILE_CARD: lambda p: {**_card_answer(p), "location": []}})
    deps = _deps(web_pool, web_index, llm=llm)
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    assert await web_index.get([card_id("Wonder City")]) == []


async def test_the_khong_phai_du_an_nha_o_thi_xoa(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    deps = _deps(web_pool, web_index)
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    assert len(await web_index.get([card_id("Wonder City")])) == 1
    await _seed(web_pool, f"{BASE}/wc-moi", "Wonder City tin mới", projects=["Wonder City"])
    deps.llm = FakeLlm({PROFILE_CARD: lambda p: {**_card_answer(p), "residential": False}})
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    assert await web_index.get([card_id("Wonder City")]) == []


def _src_page(url, location):
    return Page(url, "test.kbweb", "t", NOW, NOW, "nội dung", (), tuple(location))


def _digest_item(*urls):
    return Item("tin [1]", tuple(Source(u, "X", NOW) for u in urls), (), ())


def test_ban_tin_chi_giu_nhan_chung_it_nhat_2_nguon():
    pages = [
        _src_page(f"{BASE}/a", ["thủy nguyên", "vũ yên", "hải phòng", "hà nội"]),
        _src_page(f"{BASE}/b", ["vũ yên", "hải phòng", "dương kinh"]),
        _src_page(f"{BASE}/c", ["hải phòng", "vũ yên", "dương kinh", "hà nội"]),
    ]
    (item,) = pipeline._location_of_items([_digest_item(f"{BASE}/a", f"{BASE}/b", f"{BASE}/c")], pages)
    assert item.location == ("vũ yên", "hải phòng", "hà nội", "dương kinh")


def test_ban_tin_nhan_chung_toi_da_5_hoa_theo_thu_tu_gap():
    labels = ["tân lập", "đan phượng", "hoài đức", "nam từ liêm", "cầu giấy", "long biên", "gia lâm"]
    pages = [_src_page(f"{BASE}/a", labels), _src_page(f"{BASE}/b", labels[::-1])]
    (item,) = pipeline._location_of_items([_digest_item(f"{BASE}/a", f"{BASE}/b")], pages)
    assert item.location == tuple(labels[:5])


def test_ban_tin_nhieu_nguon_khong_nhan_chung_thi_rong():
    pages = [_src_page(f"{BASE}/a", ["thủy nguyên"]), _src_page(f"{BASE}/b", ["đan phượng"])]
    (item,) = pipeline._location_of_items([_digest_item(f"{BASE}/a", f"{BASE}/b")], pages)
    assert item.location == ()


def test_ban_tin_mot_nguon_giu_5_nhan_dau():
    labels = ["tân lập", "đan phượng", "hoài đức", "nam từ liêm", "cầu giấy", "long biên", "gia lâm"]
    (item,) = pipeline._location_of_items([_digest_item(f"{BASE}/a")], [_src_page(f"{BASE}/a", labels)])
    assert item.location == tuple(labels[:5])


async def _text_and_kind(web_index, pid):
    (p,) = await web_index._c.retrieve(web_index.collection, ids=[pid], with_payload=True)  # type: ignore[attr-defined]
    return p.payload["text"].splitlines(), p.payload["kind"]


async def test_moi_loai_point_co_tieu_de_va_kind_dung(web_pool, web_index):
    """Bên đọc chỉ search theo text: tiêu đề mang tên + địa danh (hồ sơ, thẻ) hoặc ngày (bản tin)."""
    await _seed(web_pool, f"{BASE}/hd1", "Wonder City bàn giao", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/hd2", "Wonder City mở bán", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/hd3", "Noble Palace mở bán", projects=[PROJ.name])
    llm = FakeLlm(
        {
            PROFILE_CARD: lambda p: {
                **_card_answer(p),
                "text": f"Thẻ dự án {_card_name(p)} ở Đan Phượng, Hà Nội [1].",
                "location": ["huyện Đan Phượng", "Hà Nội"],
            }
        }
    )
    deps = _deps(web_pool, web_index, llm=llm)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))

    lines, kind = await _text_and_kind(web_index, dossier_ids(PROJ.name)[0])
    assert kind == "ho_so_du_an"
    assert lines[1] == "[Dự án Noble Palace Tây Thăng Long — xã Tân Lập, huyện Đan Phượng, Hà Nội]"
    lines, kind = await _text_and_kind(web_index, card_id("Wonder City"))
    assert kind == "du_an_lan_can"
    assert lines[1] == "[Dự án wonder city — đan phượng, hà nội]"

    a = f"{BASE}/hd-digest"
    deps = _deps(web_pool, web_index, pages={a: Fetched(a, "ok", "t", "Noble giá tăng", datetime.now(UTC))})
    await ingest_urls(deps, [a], found_via="sitemap")
    now = datetime.now(UTC)
    await build_digest(deps, now)
    lines, kind = await _text_and_kind(web_index, digest_ids(DIGEST_REGION)[0])
    assert kind == "ban_tin_thi_truong"
    assert lines[1] == f"[Tin thị trường bất động sản ngày {now.astimezone(VN):%d/%m/%Y}]"


async def test_the_la_ten_khac_cua_du_an_dang_xet_thi_khong_ghi_va_khong_dung(web_pool, web_index):
    """ "Green City (tên thương mại của Noble Palace Tây Thăng Long)" không phải dự án lân cận."""
    for i in (1, 2):
        await _seed(web_pool, f"{BASE}/al{i}", "Green City", projects=["Green City"])
    await _seed(web_pool, f"{BASE}/al-np", "Noble Palace mở bán", projects=[PROJ.name])
    src = (Source(f"{BASE}/x", "X", NOW),)
    alias_text = f"Green City (tên thương mại {PROJ.name}) là khu đô thị [1]."
    await web_index.replace([card_id("Green City")], [Item(alias_text, src, ("Green City",), LOC)], NOW)
    llm = FakeLlm(
        {
            PROFILE_CARD: lambda p: {
                "text": f"Green City, còn gọi là {PROJ.name}, là khu đô thị [1].",
                "cites": [1],
                "location": ["huyện Đan Phượng"],
            }
        }
    )
    deps = _deps(web_pool, web_index, llm=llm)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    assert await web_index.get([card_id("Green City")]) == []
    near = await web_index.get([near_id(PROJ.name)])
    assert all("Green City" not in it.text for it in near)


# ─── dựng hồ sơ: ưu tiên bài 24 tháng, lùi về bài cũ khi chủ đề còn thiếu ───────


def _old(days=1000):
    return datetime.now(UTC) - timedelta(days=days)


async def test_dung_ho_so_lui_ve_bai_cu_cho_chu_de_con_thieu(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/lui/moi", "#L1# bài vùng mới", published=datetime.now(UTC))
    await _seed(web_pool, f"{BASE}/lui/be-boi", "#L2# bể bơi rộng", published=_old())
    await _seed(web_pool, f"{BASE}/lui/khac", "#L3# chuyện khác", published=_old())
    await _seed(web_pool, f"{BASE}/lui/ten", "#L4# Noble cũ", projects=[PROJ.name], published=_old())
    cfg = _cfg_topics([_topic("tien_ich", 1, keywords=("bể bơi",))], target=2)
    deps = _deps(web_pool, web_index, cfg=cfg)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(prompt, "L") == [1, 2, 4], "bài cũ khớp chủ đề thiếu hoặc gắn tên dự án; bài cũ khác thì bỏ"


async def test_dung_ho_so_khong_lui_khi_chu_de_da_du(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/du/moi", "#D1# bể bơi mới", published=datetime.now(UTC))
    await _seed(web_pool, f"{BASE}/du/cu", "#D2# bể bơi cũ", published=_old())
    cfg = _cfg_topics([_topic("tien_ich", 1, keywords=("bể bơi",))], target=1)
    deps = _deps(web_pool, web_index, cfg=cfg)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(prompt, "D") == [1]


async def test_grounding_chi_dem_bai_trong_24_thang(web_pool, web_index):
    await _seed(web_pool, f"{BASE}/gd/cu", "bể bơi cũ", published=_old())
    grounding = FakeGrounding([])
    cfg = _cfg_topics([_topic("tien_ich", 2, keywords=("bể bơi",))], target=1)
    deps = _deps(web_pool, web_index, cfg=cfg, grounding=grounding)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    assert len(grounding.queries) == 2, "bài cũ không làm chủ đề thành đủ — vẫn tìm tin mới"


async def test_bai_gan_ten_khong_dau_van_vao_ho_so(web_pool, web_index):
    await _seed(
        web_pool,
        f"{BASE}/kd/1",
        "#K1# Noble không dấu",
        projects=["noble palace tay thang long"],
        location=["Hải Phòng"],
    )
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))
    (prompt,) = deps.llm.prompts(PROFILE_DOSSIER)
    assert _markers(prompt, "K") == [1]


# ─── "dự án nào gần X": mục dựng sẵn trong hồ sơ + dòng "Gần các dự án" trên thẻ ────


async def _seed_wonder(web_pool, key):
    await _seed(web_pool, f"{BASE}/{key}/wc1", "Wonder City bàn giao", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/{key}/wc2", "Wonder City mở bán", projects=["Wonder City"])
    await _seed(web_pool, f"{BASE}/{key}/np", "Noble Palace mở bán", projects=[PROJ.name])


async def test_point_du_an_gan_va_the_ghi_ten_du_an_dang_xet(web_pool, web_index):
    await _seed_wonder(web_pool, "gan")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    (near,) = await web_index.get([near_id(PROJ.name)])
    assert near.text.startswith("Các dự án gần Noble Palace Tây Thăng Long (")
    (raw,) = await _raw_texts(web_index, [near_id(PROJ.name)])
    assert raw.split("\n")[1].startswith("[Các dự án gần Noble Palace Tây Thăng Long — ")
    hit = await web_index._c.retrieve(web_index.collection, [near_id(PROJ.name)], with_payload=True)
    assert hit[0].payload["kind"] == "du_an_lan_can"
    assert await web_index.cards_near(["đan phượng"], exclude="Dự án Bê") != []
    assert all(c.projects[0] == "wonder city" for c in await web_index.cards_near(["đan phượng"], exclude="x"))
    assert (
        "\n- Wonder City (gần Noble Palace Tây Thăng Long, đan phượng): Thẻ dự án wonder city ở Đan Phượng [1]."
        in near.text
    )
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.text.startswith("Gần các dự án: Noble Palace Tây Thăng Long.\n")
    (raw,) = await _raw_texts(web_index, [card_id("Wonder City")])
    assert "Gần các dự án: Noble Palace Tây Thăng Long." in raw

    await refresh_project(deps, PROJ2, MODE_WEEKLY, datetime.now(UTC))
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.text.startswith("Gần các dự án: Noble Palace Tây Thăng Long, Dự án Bê.\n")


async def test_viet_lai_the_giu_dong_gan_va_khong_gui_cho_llm(web_pool, web_index):
    await _seed_wonder(web_pool, "giu")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    await _seed(web_pool, f"{BASE}/giu/wc3", "Wonder City tin mới", projects=["Wonder City"])
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    assert "Gần các dự án" not in deps.llm.prompts(PROFILE_CARD)[-1]
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.text.startswith("Gần các dự án: Noble Palace Tây Thăng Long.\n")


async def test_luot_dem_giu_point_du_an_gan(web_pool, web_index):
    await _seed_wonder(web_pool, "dem")
    deps = _deps(web_pool, web_index)
    await refresh_project(deps, PROJ, MODE_WEEKLY, datetime.now(UTC))
    await _seed(web_pool, f"{BASE}/dem/np2", "Noble Palace tin mới", projects=[PROJ.name])
    deps.grounding = NoGrounding()
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert (await refresh_project(deps, PROJ, MODE_NIGHTLY, tomorrow)).count == 1
    assert len(await web_index.get([near_id(PROJ.name)])) == 1, "lượt đêm không xoá point dự án gần"


async def test_luot_sau_lam_roi_muc_thi_giu_muc_cu(web_pool, web_index):
    await _seed_backlog(web_pool, 100)
    passes = iter(
        [
            {
                "items": [
                    {"text": "Vị trí trên đại lộ Thăng Long [1].", "cites": [1]},
                    {"text": "Mặt bằng giá biệt thự 150 triệu/m² [1].", "cites": [1]},
                ]
            },
            {"items": [{"text": "Vị trí trên đại lộ Thăng Long, cách Mỹ Đình 15 phút [1].", "cites": [1]}]},
            {"items": [{"text": "Vị trí trên đại lộ Thăng Long, cách Mỹ Đình 15 phút [1].", "cites": [1]}]},
        ]
    )
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_DOSSIER: lambda p: next(passes)}))
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 2
    texts = [it.text for it in await web_index.get(dossier_ids(PROJ.name))]
    assert texts == [
        "Vị trí trên đại lộ Thăng Long, cách Mỹ Đình 15 phút [1].",
        "Mặt bằng giá biệt thự 150 triệu/m² [1].",
    ]


async def test_the_chi_giu_dia_danh_noi_dung_nhac_toi(web_pool, web_index):
    await _seed_near(web_pool, "Wonder City")
    answer = {"text": "Wonder City ở Đan Phượng [1].", "cites": [1], "location": ["Đan Phượng", "Nghĩa Trụ"]}
    deps = _deps(web_pool, web_index, llm=FakeLlm({PROFILE_CARD: answer}))
    await pipeline._refresh_card(deps, "Wonder City", datetime.now(UTC))
    (card,) = await web_index.get([card_id("Wonder City")])
    assert card.location == ("đan phượng",)


async def test_the_lan_can_bo_the_lech_vi_tri_va_the_ten_khac(web_pool, web_index):
    src = (Source(f"{BASE}/x", "X", NOW),)
    cards = {
        "Wonder City": Item("Wonder City ở Đan Phượng [1].", src, ("wonder city",), ("đan phượng",)),
        "Green City": Item(
            "Green City (tên thương mại Wonder City) ở Đan Phượng [1].", src, ("green city",), ("đan phượng",)
        ),
        "Sun Riverpolis": Item("Sun Riverpolis ở Đà Nẵng [1].", src, ("sun riverpolis",), ("đan phượng", "đà nẵng")),
    }
    for name, it in cards.items():
        await web_index.replace([card_id(name)], [it], NOW)
    deps = _deps(web_pool, web_index)
    got = await pipeline._neighbor_cards(deps, PROJ, ("tân lập", "đan phượng"))
    assert [c.projects[0] for c in got] in (["wonder city"], ["green city"])


async def test_dung_ho_so_bu_chu_de_nguon_co_ma_llm_bo_sot(web_pool, web_index):
    for i in range(2):
        await _seed(web_pool, f"{BASE}/bu/gia{i}", f"#G{i}# Noble giá 100 triệu/m2", projects=[PROJ.name])
    first = {"items": [{"text": "Tổng quan: Noble Palace rộng 77 ha [1].", "cites": [1]}]}
    fill = {
        "items": [
            {"text": "Mặt bằng giá: 100 triệu/m² [1].", "cites": [1]},
            {"text": "Tổng quan: lặp [1].", "cites": [1]},
        ]
    }
    answers = iter([first, fill])
    cfg = _cfg_topics([Topic("price_trend", "Mặt bằng giá", ("triệu/m2",), ())], target=1)
    deps = _deps(web_pool, web_index, cfg=cfg, llm=FakeLlm({PROFILE_DOSSIER: lambda p: next(answers)}))
    assert (await refresh_project(deps, PROJ, MODE_INIT, datetime.now(UTC))).count == 2
    texts = [it.text for it in await web_index.get(dossier_ids(PROJ.name))]
    assert texts == ["Tổng quan: Noble Palace rộng 77 ha [1].", "Mặt bằng giá: 100 triệu/m² [1]."]
    second = deps.llm.prompts(PROFILE_DOSSIER)[1]
    assert "CHỦ ĐỀ (nhãn mở đầu mỗi item): Mặt bằng giá\nCHỈ viết item cho các chủ đề trên" in second


async def test_khong_viet_the_cho_ten_khong_phai_du_an(web_pool, web_index):
    for i in range(2):
        await _seed(web_pool, f"{BASE}/vw/{i}", f"VinWonders Wave Park mở cửa {i}", projects=["VinWonders Wave Park"])
    deps = _deps(web_pool, web_index)
    await pipeline._refresh_cards(deps, PROJ, pipeline.location_labels(PROJ), datetime.now(UTC))
    assert "vinwonders wave park" not in _card_names(deps.llm)


async def test_ten_sinh_doi_cung_xa_la_chinh_du_an_khong_la_lan_can(web_pool, web_index):
    src = (Source(f"{BASE}/x", "X", NOW),)
    sunrise = ProjectRow(40, "SRH", "NOXH Sunrise Home Ngọc Hồi", "Hà Nội", "Km14 QL1A, Xã Ngọc Hồi, Hà Nội", "", ())
    await web_index.replace(
        [card_id("Sunrise Home Thanh Trì")],
        [Item("Sunrise Home Thanh Trì ở Ngọc Hồi [1].", src, ("sunrise home thanh trì",), ("ngọc hồi", "thanh trì"))],
        NOW,
    )
    await web_index.replace(
        [card_id("Hồng Hà Eco City")],
        [Item("Hồng Hà Eco City ở Ngọc Hồi [1].", src, ("hồng hà eco city",), ("ngọc hồi",))],
        NOW,
    )
    deps = _deps(web_pool, web_index)
    got = await pipeline._neighbor_cards(deps, sunrise, pipeline.location_labels(sunrise))
    assert [c.projects[0] for c in got] == ["hồng hà eco city"]
