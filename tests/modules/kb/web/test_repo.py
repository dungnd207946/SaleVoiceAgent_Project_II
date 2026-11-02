from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.web import repo

from .conftest import TENANT

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
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/a", projects=["A"])
        await _save(c, "https://test.kbweb/a", projects=["B"])
        assert await repo.known_urls(c, ["https://test.kbweb/a", "https://test.kbweb/z"]) == {"https://test.kbweb/a"}
        (p,) = await repo.pages_for(c, projects=["B"], location=[])
        assert p.projects == ("b",)


async def test_known_urls_rong_khong_query(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        assert await repo.known_urls(c, []) == set()


async def test_hash_taken_bo_qua_chinh_no(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/goc", h="h1")
        assert await repo.hash_taken(c, "h1", "https://test.kbweb/chep")
        assert not await repo.hash_taken(c, "h1", "https://test.kbweb/goc")


async def test_hash_taken_chuoi_rong_luon_false(web_pool):
    """`content_hash` rỗng là giá trị mặc định của trang chưa băm được — không phải
    một hash thật, nên hai trang cùng rỗng không được coi là trùng nội dung."""
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/e1", h="")
        assert not await repo.hash_taken(c, "", "https://test.kbweb/e2")


async def test_save_page_giu_fetched_at_khi_hash_khong_doi_nhung_luon_cham_last_checked(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/f", h="hh")
        r1 = await c.fetchrow(
            "SELECT fetched_at, last_checked_at FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/f'"
        )
        await _save(c, "https://test.kbweb/f", h="hh")
        r2 = await c.fetchrow(
            "SELECT fetched_at, last_checked_at FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/f'"
        )
        assert r2["fetched_at"] == r1["fetched_at"]
        assert r2["last_checked_at"] >= r1["last_checked_at"]

        await _save(c, "https://test.kbweb/f", h="hh2")
        r3 = await c.fetchrow(
            "SELECT fetched_at, content_hash FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/f'"
        )
        assert r3["fetched_at"] > r1["fetched_at"]
        assert r3["content_hash"] == "hh2"


async def test_save_page_giu_provenance_dau_tien_chi_thay_noi_dung(web_pool):
    """`domain`/`source_url`/`found_via` là chuyện "tìm thấy thế nào" — đông cứng ở lần
    ghi đầu; `title`/`status` (nội dung/phân loại) thì bị THAY bởi lần ghi sau."""
    url = "https://test.kbweb/prov"
    async with tenant_conn(web_pool, TENANT) as c:
        await repo.save_page(
            c,
            url=url,
            source_url="https://goc.example/bai-1",
            domain="goc.example",
            title="tiêu đề cũ",
            published_at=NOW,
            content_text="nội dung",
            content_hash="h1",
            found_via="sitemap",
            status="ok",
            projects=[],
            location=[],
        )
        await repo.save_page(
            c,
            url=url,
            source_url="https://khac.example/bai-1-lai",
            domain="khac.example",
            title="tiêu đề mới",
            published_at=NOW,
            content_text=None,
            content_hash="h2",
            found_via="grounding",
            status="irrelevant",
            projects=[],
            location=[],
        )
        row = await c.fetchrow(
            "SELECT source_url, domain, found_via, title, status FROM tenant_data.web_pages WHERE url = $1", url
        )
    assert row["source_url"] == "https://goc.example/bai-1"
    assert row["domain"] == "goc.example"
    assert row["found_via"] == "sitemap"
    assert row["title"] == "tiêu đề mới"
    assert row["status"] == "irrelevant"


async def test_pages_for_loc_theo_du_an_hoac_dia_danh_va_bo_dau_loai(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/1", projects=["NPTTL"])
        await _save(c, "https://test.kbweb/2", location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/3", location=["Đan Phượng"], status="irrelevant")
        got = {p.url for p in await repo.pages_for(c, projects=["NPTTL"], location=["Đan Phượng"])}
        assert got == {"https://test.kbweb/1", "https://test.kbweb/2"}


async def test_pages_for_ton_trong_limit(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        for i in range(3):
            await _save(c, f"https://test.kbweb/lim{i}", projects=["NPTTL"], published=NOW - timedelta(minutes=i))
        got = await repo.pages_for(c, projects=["NPTTL"], location=[], limit=2)
        assert len(got) == 2
        # mới nhất trước (published_at DESC)
        assert [p.url for p in got] == ["https://test.kbweb/lim0", "https://test.kbweb/lim1"]


async def test_pages_for_since_chi_lay_fetched_sau_moc_khong_bao_gom_moc(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/s1", projects=["NPTTL"])
        moc = await c.fetchval("SELECT fetched_at FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/s1'")
        assert await repo.pages_for(c, projects=["NPTTL"], location=[], since=moc) == []
        assert len(await repo.pages_for(c, projects=["NPTTL"], location=[], since=moc - timedelta(seconds=1))) == 1


async def test_pages_for_loc_theo_ngay_dang(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/d_moi", projects=["NPTTL"], published=NOW - timedelta(days=10))
        await _save(c, "https://test.kbweb/d_cu", projects=["NPTTL"], published=NOW - timedelta(days=900))
        cutoff = NOW - timedelta(days=730)
        fresh = await repo.pages_for(c, projects=["NPTTL"], location=[], published_since=cutoff)
        older = await repo.pages_for(c, projects=["NPTTL"], location=[], published_before=cutoff)
        assert [p.url for p in fresh] == ["https://test.kbweb/d_moi"]
        assert [p.url for p in older] == ["https://test.kbweb/d_cu"]


async def test_pages_for_khop_ten_khong_phan_biet_dau(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/kd1", projects=["noble palace tay thang long"])
        await _save(c, "https://test.kbweb/kd2", projects=["sunshine bay retreat vũng tàu"])
        got = await repo.pages_for(c, projects=["Noble Palace Tây Thăng Long"], location=[])
        assert [p.url for p in got] == ["https://test.kbweb/kd1"]
        got = await repo.pages_for(c, projects=["SUNSHINE BAY RETREAT VUNG TAU"], location=[])
        assert [p.url for p in got] == ["https://test.kbweb/kd2"]


async def test_pages_for_ten_cu_the_hon_khong_dau_van_bi_loai(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/kd3", projects=["vinhomes global gate ha long"])
        got = await repo.pages_for(
            c, projects=["Vinhomes Global Gate"], location=[], others=("Vinhomes Global Gate Hạ Long",)
        )
        assert got == []


async def _save_via(c, url, found_via, published):
    await repo.save_page(
        c,
        url=url,
        source_url=url,
        domain="test.kbweb",
        title="t",
        published_at=published,
        content_text="x",
        content_hash="",
        found_via=found_via,
        status="ok",
        projects=[],
        location=[],
    )


async def test_pages_published_since_loc_theo_ngay_dang_kenh_va_limit(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save_via(c, "https://test.kbweb/pp1", "sitemap", NOW)
        await _save_via(c, "https://test.kbweb/pp2", "rss", NOW - timedelta(hours=1))
        await _save_via(c, "https://test.kbweb/pp3", "grounding", NOW)
        await _save_via(c, "https://test.kbweb/pp4", "sitemap", None)
        await _save_via(c, "https://test.kbweb/pp5", "sitemap", NOW - timedelta(days=2))
        await _save(c, "https://test.kbweb/pp6", status="irrelevant")
        got = await repo.pages_published_since(c, NOW - timedelta(days=1), NOW, found_via=["sitemap", "rss"])
        urls = [p.url for p in got]
        assert urls[:2] == ["https://test.kbweb/pp1", "https://test.kbweb/pp2"]
        assert not {"https://test.kbweb/pp3", "https://test.kbweb/pp4", "https://test.kbweb/pp5"} & set(urls)
        assert (
            len(await repo.pages_published_since(c, NOW - timedelta(days=1), NOW, found_via=["sitemap"], limit=1)) == 1
        )
        later = await repo.pages_published_since(
            c, NOW - timedelta(days=1), NOW - timedelta(minutes=30), found_via=["rss"]
        )
        assert [p.url for p in later] == ["https://test.kbweb/pp2"], "hai đầu đều bao gồm, sau `until` bị loại"
        assert [p.url for p in await repo.pages_published_since(c, NOW, NOW, found_via=["sitemap"])][:1] == [
            "https://test.kbweb/pp1"
        ]


async def test_latest_fetched_theo_du_an_hoac_dia_danh(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/lf1", projects=["LFX"])
        await _save(c, "https://test.kbweb/lf2", location=["Vùng LF"])
        await c.execute(
            "UPDATE tenant_data.web_pages SET fetched_at = $2 WHERE url = $1", "https://test.kbweb/lf2", NOW
        )
        assert await repo.latest_fetched(c, projects=["LFX"], location=["Vùng LF"]) >= NOW
        assert await repo.latest_fetched(c, projects=["không có"], location=[]) is None


async def test_names_near_dem_theo_so_bai_va_bo_chinh_minh(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/n1", projects=["NPTTL", "Wonder City"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n2", projects=["Wonder City", "NPTTL"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n4", projects=["Wonder City"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n3", projects=["Riverside"], location=["Đan Phượng"])
        await _save(c, "https://test.kbweb/n5", projects=["Riverside"], location=["Đan Phượng"])
        assert await repo.names_near(c, ["Đan Phượng"], ["NPTTL"]) == ["wonder city", "riverside"]


async def test_names_near_bo_qua_dia_danh_khac_va_ton_trong_limit(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        for i in range(2):
            await _save(c, f"https://test.kbweb/nn1{i}", projects=["Ở Xa"], location=["Ba Vì"])
            await _save(c, f"https://test.kbweb/nn2{i}", projects=["Gần", "Gần Hai"], location=["Đan Phượng"])
        got = await repo.names_near(c, ["Đan Phượng"], [], limit=1)
        assert got == ["gần"]


async def test_living_due_loc_theo_domain(web_pool):
    """Cả hai bài đều cũ như nhau — chỉ domain đúng danh sách mới được trả về."""
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/liv_a")
        await _save(c, "https://test.kbweb/liv_b")
        await c.execute(
            "UPDATE tenant_data.web_pages SET domain = 'other.kbweb' WHERE url = 'https://test.kbweb/liv_b'"
        )
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1 WHERE url LIKE 'https://test.kbweb/liv\\_%'",
            NOW - timedelta(days=10),
        )
        assert await repo.living_due(c, ["test.kbweb"], NOW) == ["https://test.kbweb/liv_a"]


async def test_living_due_khong_bao_gom_dung_moc(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/liv_moc")
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1 WHERE url = 'https://test.kbweb/liv_moc'", NOW
        )
        # đúng bằng mốc thì KHÔNG quá hạn (so sánh nghiêm ngặt <)
        assert await repo.living_due(c, ["test.kbweb"], NOW) == []
        assert await repo.living_due(c, ["test.kbweb"], NOW + timedelta(seconds=1)) == ["https://test.kbweb/liv_moc"]


async def test_living_due_bo_qua_trang_khong_ok(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/liv3", status="fetch_failed")
        assert await repo.living_due(c, ["test.kbweb"], NOW + timedelta(days=1)) == []


async def test_purge_xoa_bai_qua_han_va_dau_cu(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/cu", published=NOW - timedelta(days=800))
        await c.execute(
            "UPDATE tenant_data.web_pages SET fetched_at = $1 WHERE url = 'https://test.kbweb/cu'",
            NOW - timedelta(days=800),
        )
        await _save(c, "https://test.kbweb/moi", published=NOW)
        await c.execute(
            """UPDATE tenant_data.web_pages SET last_checked_at = $1
                WHERE url = 'https://test.kbweb/moi'""",
            NOW,
        )
        await _save(c, "https://test.kbweb/dau", status="fetch_failed")
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1 WHERE url = 'https://test.kbweb/dau'",
            NOW - timedelta(days=100),
        )
        assert await repo.purge(c, now=NOW) >= 2
        urls = ["https://test.kbweb/cu", "https://test.kbweb/dau", "https://test.kbweb/moi"]
        assert await repo.known_urls(c, urls) == {"https://test.kbweb/moi"}


async def test_purge_giu_bai_dang_lau_nhung_moi_nap(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/cu_moi_nap", published=NOW - timedelta(days=2000))
        await repo.purge(c, now=NOW)
        assert await repo.known_urls(c, ["https://test.kbweb/cu_moi_nap"]) == {"https://test.kbweb/cu_moi_nap"}


async def test_purge_giu_bai_chua_qua_han_va_tra_dem_dung(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        # ok, đúng ngay mép keep_days=730 (chưa vượt) — phải được GIỮ.
        await _save(c, "https://test.kbweb/mep_ok", published=NOW - timedelta(days=730))
        # not-ok, đúng ngay mép marker_days=90 (chưa vượt) — phải được GIỮ.
        await _save(c, "https://test.kbweb/mep_marker", status="needs_browser")
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1 WHERE url = 'https://test.kbweb/mep_marker'",
            NOW - timedelta(days=90),
        )
        # not-ok nhưng đã quá marker_days — phải bị XOÁ, không lẫn vào hai cái trên.
        await _save(c, "https://test.kbweb/qua_marker", status="irrelevant")
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1 WHERE url = 'https://test.kbweb/qua_marker'",
            NOW - timedelta(days=91),
        )
        n = await repo.purge(c, now=NOW)
        assert n == 1
        assert await repo.known_urls(
            c, ["https://test.kbweb/mep_ok", "https://test.kbweb/mep_marker", "https://test.kbweb/qua_marker"]
        ) == {"https://test.kbweb/mep_ok", "https://test.kbweb/mep_marker"}


async def test_web_tenant_fixture_dung_du_an_published(pool, web_tenant):
    """Sanity cho fixture của các task sau: `web_tenant` phải dựng đúng một dự án
    NPTTL, published, cho CẢ hai tenant (`kbw_a`/`kbw_b`) — không chỉ tenant trả về."""
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, web_tenant) as conn:
        row = await conn.fetchrow(
            "SELECT project_code, status FROM tenant_data.projects WHERE tenant_id = portal.current_tenant()"
        )
    assert row["project_code"] == "NPTTL"
    assert row["status"] == "published"

    async with tenant_conn(pool, "kbw_b") as conn:
        other = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.projects WHERE tenant_id = portal.current_tenant()"
        )
    assert other == 1


async def test_known_urls_khong_tinh_bai_tai_hong(web_pool):
    """`fetch_failed` phải tải lại được; các dấu khác (irrelevant/needs_browser) vẫn là "đã biết"."""
    async with tenant_conn(web_pool, TENANT) as c:
        for s in ("ok", "irrelevant", "needs_browser", "fetch_failed"):
            await _save(c, f"https://test.kbweb/kn_{s}", status=s)
        got = await repo.known_urls(
            c, [f"https://test.kbweb/kn_{s}" for s in ("ok", "irrelevant", "needs_browser", "fetch_failed")]
        )
        assert got == {f"https://test.kbweb/kn_{s}" for s in ("ok", "irrelevant", "needs_browser")}


async def test_stored_hashes_va_mark_checked(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/mc", h="h9")
        await c.execute(
            "UPDATE tenant_data.web_pages SET last_checked_at = $1, fetched_at = $1 WHERE url = 'https://test.kbweb/mc'",
            NOW - timedelta(days=40),
        )
        assert await repo.stored_hashes(c, ["https://test.kbweb/mc", "https://test.kbweb/khong"]) == {
            "https://test.kbweb/mc": "h9"
        }
        await repo.mark_checked(c, "https://test.kbweb/mc")
        row = await c.fetchrow(
            "SELECT last_checked_at, fetched_at FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/mc'"
        )
        assert row["last_checked_at"] > NOW - timedelta(days=1)
        assert row["fetched_at"] == NOW - timedelta(days=40), "chỉ chạm last_checked_at, không đổi mốc nội dung"


async def test_save_page_luu_location_da_chuan_hoa(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/norm1", location=["Huyện Đan Phượng", "Đan Phượng", "TP. Hà Nội", " "])
        row = await c.fetchrow("SELECT location FROM tenant_data.web_pages WHERE url = 'https://test.kbweb/norm1'")
        assert list(row["location"]) == ["đan phượng", "hà nội"]


async def test_tra_theo_location_chua_chuan_hoa_van_khop(web_pool):
    """Bên hỏi đưa nhãn còn tiền tố/hoa thường vẫn khớp nhãn đã lưu — hai phía so cùng một dạng."""
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/norm2", projects=["Gần"], location=["Lê Văn Lương"])
        await _save(
            c,
            "https://test.kbweb/norm3",
            projects=["Gần"],
            location=["Lê Văn Lương"],
            published=NOW - timedelta(days=1),
        )
        got = await repo.pages_for(c, projects=[], location=["đường Lê Văn Lương"])
        assert [p.url for p in got] == ["https://test.kbweb/norm2", "https://test.kbweb/norm3"]
        assert got[0].location == ("lê văn lương",)
        assert await repo.names_near(c, ["ĐƯỜNG LÊ VĂN LƯƠNG"], []) == ["gần"]
        assert await repo.latest_fetched(c, projects=[], location=["Đường Lê Văn Lương"]) is not None


# ─── tên dự án chuẩn hoá + luật khớp có đuôi (ví dụ thật lượt chạy 2026-10-01) ──


async def _projects_of(c, url):
    return list(await c.fetchval("SELECT projects FROM tenant_data.web_pages WHERE url = $1", url))


async def test_save_page_luu_projects_da_chuan_hoa(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(
            c,
            "https://test.kbweb/pn1",
            projects=["VINHOMES GLOBAL GATE (TMDV)", "Vinhomes Global Gate", "Vinhomes Golden City Dương Kinh", " "],
        )
        assert await _projects_of(c, "https://test.kbweb/pn1") == [
            "vinhomes global gate",
            "vinhomes golden city dương kinh",
        ]


async def test_pages_for_ten_in_hoa_khop_nhan_va_bien_the_co_duoi(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/gc1", projects=["Vinhomes Golden City"])
        await _save(c, "https://test.kbweb/gc2", projects=["Vinhomes Golden City Dương Kinh"])
        await _save(c, "https://test.kbweb/gc3", projects=["Vinhomes Golden Cityx"])
        await _save(c, "https://test.kbweb/op3", projects=["Vinhomes Ocean Park 3 - The Crown"])
        await _save(c, "https://test.kbweb/op2", projects=["Vinhomes Ocean Park 2"])
        await _save(c, "https://test.kbweb/op1", projects=["Vinhomes Ocean Park"])
        gc = {p.url for p in await repo.pages_for(c, projects=["VINHOMES GOLDEN CITY"], location=[])}
        assert gc == {"https://test.kbweb/gc1", "https://test.kbweb/gc2"}
        op3 = {p.url for p in await repo.pages_for(c, projects=["VINHOMES OCEAN PARK 3"], location=[])}
        assert op3 == {"https://test.kbweb/op3"}
        op = {p.url for p in await repo.pages_for(c, projects=["Vinhomes Ocean Park"], location=[])}
        assert op == {"https://test.kbweb/op1"}, "VOP2/VOP3 là dự án khác"
        gg = await repo.pages_for(c, projects=["VINHOMES GLOBAL GATE (TMDV)"], location=[])
        assert gg == []


async def test_pages_for_ten_co_ky_tu_like_khong_thanh_wildcard(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/lk1", projects=["Sun_Group Tower"])
        await _save(c, "https://test.kbweb/lk2", projects=["SunxGroup Tower"])
        await _save(c, "https://test.kbweb/lk3", projects=["Khu 100% Xanh"])
        await _save(c, "https://test.kbweb/lk4", projects=["Khu 100abc Xanh"])
        assert [p.url for p in await repo.pages_for(c, projects=["Sun_Group"], location=[])] == [
            "https://test.kbweb/lk1"
        ]
        assert [p.url for p in await repo.pages_for(c, projects=["Khu 100%"], location=[])] == [
            "https://test.kbweb/lk3"
        ]


async def test_latest_fetched_dung_luat_khop_co_duoi(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/lfv", projects=["Vinhomes Golden City Dương Kinh"])
        assert await repo.latest_fetched(c, projects=["VINHOMES GOLDEN CITY"], location=[]) is not None
        assert await repo.latest_fetched(c, projects=["Vinhomes Gold"], location=[]) is None
        assert await repo.latest_fetched(c, projects=["Vinhomes Golden City Dương Kinh 2"], location=[]) is None


async def test_names_near_bo_ten_cung_du_an_va_ten_chi_o_mot_bai(web_pool):
    loc = ["Dương Kinh"]
    async with tenant_conn(web_pool, TENANT) as c:
        for i in range(2):
            await _save(
                c,
                f"https://test.kbweb/nb{i}",
                projects=["Vinhomes Golden City Dương Kinh", "Royal Island", "Vinhomes Ocean Park 2", "Wonder City"],
                location=loc,
            )
        await _save(c, "https://test.kbweb/nb_le", projects=["Một Bài"], location=loc)
        await _save(c, "https://test.kbweb/nb_x", projects=["Ngoài Vùng"], location=["Ba Vì"])
        await _save(c, "https://test.kbweb/nb_y", projects=["Ngoài Vùng"], location=["Ba Vì"])
        got = await repo.names_near(c, loc, ["VINHOMES GOLDEN CITY", "Vinhomes Royal Island", "Vinhomes Ocean Park"])
        assert got == ["vinhomes ocean park 2", "wonder city"]


async def test_names_near_so_bai_dem_theo_bai_ok(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/nk1", projects=["Gần"], location=["Tân Lập"])
        await _save(c, "https://test.kbweb/nk2", projects=["Gần"], location=["Tân Lập"], status="irrelevant")
        assert await repo.names_near(c, ["Tân Lập"], []) == []


async def _location_of(c, url):
    return list(await c.fetchval("SELECT location FROM tenant_data.web_pages WHERE url = $1", url))


async def test_save_page_bo_nhan_ha_tang_khoi_projects(web_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(
            c,
            "https://test.kbweb/nh1",
            projects=[
                "Tuyến metro số 1",
                "Vinhomes Royal Island",
                "Vinmec Royal Island",
                "Khu công nghiệp Thủy Nguyên",
            ],
        )
        assert await _projects_of(c, "https://test.kbweb/nh1") == ["vinhomes royal island"]


async def test_pages_for_ten_cu_the_hon_cung_tenant_thang(web_pool):
    """Bài "Vinhomes Global Gate Hạ Long" không vào hồ sơ "VINHOMES GLOBAL GATE (TMDV)" khi tenant có cả hai."""
    async with tenant_conn(web_pool, TENANT) as c:
        await _save(c, "https://test.kbweb/gg-cl", projects=["Vinhomes Global Gate"])
        await _save(c, "https://test.kbweb/gg-cl2", projects=["Vinhomes Global Gate Cổ Loa"])
        await _save(c, "https://test.kbweb/gg-hl", projects=["Vinhomes Global Gate Hạ Long"])
        await _save(c, "https://test.kbweb/gg-hl2", projects=["Vinhomes Global Gate Hạ Long Xanh"])
        got = await repo.pages_for(
            c, projects=["VINHOMES GLOBAL GATE (TMDV)"], location=[], others=("vinhomes global gate hạ long",)
        )
        assert sorted(p.url for p in got) == ["https://test.kbweb/gg-cl", "https://test.kbweb/gg-cl2"]
        assert (
            await repo.latest_fetched(
                c, projects=["VINHOMES GLOBAL GATE (TMDV)"], location=[], others=("vinhomes global gate hạ long",)
            )
            is not None
        )
        # không truyền others thì luật đuôi cũ vẫn lấy cả bài Hạ Long
        assert len(await repo.pages_for(c, projects=["VINHOMES GLOBAL GATE (TMDV)"], location=[])) == 4
        hl = await repo.pages_for(c, projects=["VINHOMES GLOBAL GATE HẠ LONG"], location=[])
        assert sorted(p.url for p in hl) == ["https://test.kbweb/gg-hl", "https://test.kbweb/gg-hl2"]
