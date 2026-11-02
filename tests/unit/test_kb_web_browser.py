"""Tầng trình duyệt: `TieredFetcher` leo tầng đúng lúc, `BrowserBudget` chặn đúng trần, thiếu playwright thì tắt êm."""

import pytest

from portal.modules.kb.web.browser import BrowserBudget, BrowserFetcher, TieredFetcher
from portal.modules.kb.web.fetch import Fetched

U = "https://ex.vn/a"


class FakeHttp:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        return self.result


class FakeBrowser:
    available = True

    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        return self.result


def _tier(http, browser, cap=10):
    return TieredFetcher(http, browser, BrowserBudget(None, tenant="t", cap=cap))


OK = Fetched(U, "ok", "t", "nội dung")


async def test_http_ok_khong_mo_trinh_duyet():
    b = FakeBrowser(OK)
    assert (await _tier(FakeHttp(OK), b).fetch(U)).status == "ok"
    assert b.calls == 0


@pytest.mark.parametrize(
    "first",
    [
        Fetched(U, "needs_browser", reason="challenge"),
        Fetched(U, "fetch_failed", reason="empty"),
        Fetched(U, "fetch_failed", reason="status"),
    ],
)
async def test_http_bi_chan_hoac_rong_thi_leo_tang_trinh_duyet(first):
    b = FakeBrowser(OK)
    assert (await _tier(FakeHttp(first), b).fetch(U)).status == "ok"
    assert b.calls == 1


@pytest.mark.parametrize("first", [Fetched(U, "fetch_failed", reason="network"), Fetched(U, "irrelevant")])
async def test_loi_mang_khong_leo_tang(first):
    b = FakeBrowser(OK)
    assert (await _tier(FakeHttp(first), b).fetch(U)) == first
    assert b.calls == 0


async def test_mode_browser_di_thang_trinh_duyet():
    h, b = FakeHttp(OK), FakeBrowser(Fetched(U, "fetch_failed", reason="network"))
    got = await _tier(h, b).fetch(U, mode="browser")
    assert (h.calls, b.calls, got.status) == (0, 1, "fetch_failed")


async def test_khong_co_trinh_duyet_thi_giu_dau_needs_browser():
    first = Fetched(U, "fetch_failed", reason="empty")
    got = await _tier(FakeHttp(first), None).fetch(U)
    assert got.status == "needs_browser" and got.reason == "empty"
    b = FakeBrowser(OK)
    b.available = False
    assert (await _tier(FakeHttp(first), b).fetch(U)).status == "needs_browser"


async def test_het_tran_ngay_thi_giu_dau_needs_browser():
    first = Fetched(U, "needs_browser", reason="challenge")
    b = FakeBrowser(OK)
    t = _tier(FakeHttp(first), b, cap=1)
    assert (await t.fetch(U)).status == "ok"
    got = await t.fetch(U)
    assert (got.status, got.reason, b.calls) == ("needs_browser", "budget", 1)


async def test_ca_hai_tang_hong_giu_needs_browser_neu_mot_tang_bi_chan():
    first = Fetched(U, "needs_browser", reason="challenge")
    got = await _tier(FakeHttp(first), FakeBrowser(Fetched(U, "fetch_failed", reason="network"))).fetch(U)
    assert got.status == "needs_browser"
    first = Fetched(U, "fetch_failed", reason="empty")
    got = await _tier(FakeHttp(first), FakeBrowser(Fetched(U, "fetch_failed", reason="network"))).fetch(U)
    assert got.status == "fetch_failed"


async def test_budget_redis_dem_theo_tenant_va_ngay(monkeypatch):
    class R:
        def __init__(self):
            self.n = {}
            self.exp = []

        async def incrby(self, k, n):
            self.n[k] = self.n.get(k, 0) + n
            return self.n[k]

        async def ttl(self, k):
            return 100

        async def expire(self, k, s):
            self.exp.append(k)

    r = R()
    b = BrowserBudget(r, tenant="anphu", cap=2)
    assert [await b.take() for _ in range(3)] == [True, True, False]
    (key,) = r.n
    assert key.startswith("kbweb:browser:anphu:") and r.exp == [key]


async def test_browser_fetcher_thieu_playwright_thi_tat_em(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pw(name, *a, **kw):
        if name.startswith("playwright"):
            raise ImportError(name)
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_pw)

    async def public(host):
        return ["93.184.216.34"]

    f = BrowserFetcher(resolve=public)
    got = await f.fetch(U)
    assert (got.status, got.reason, f.available) == ("needs_browser", "unavailable", False)
    assert (await f.fetch("http://127.0.0.1/x")).reason == "private"
    await f.aclose()
