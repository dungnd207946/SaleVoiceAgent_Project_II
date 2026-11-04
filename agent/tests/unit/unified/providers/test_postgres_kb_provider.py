"""PostgresKBProvider — roster + list/overview/discover, TDD'd against a fake
asyncpg-like connection (no real DB). Units/get_document are Task 4's scope —
this file only exercises what Task 3 owns.
"""

from __future__ import annotations

import re
from decimal import Decimal

from noble_agent.data.project_matching import fold
from noble_agent.data.providers import base, postgres_kb
from noble_agent.data.providers.postgres_kb import PostgresKBProvider


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows.get("fetch", [])

    async def fetchrow(self, sql, *args):
        return self._rows.get("fetchrow")


class _FakeCtx:
    def __init__(self, conn):
        self._c = conn

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *a):
        return False


class _RecordingConn(_FakeConn):
    """Also records the SQL + args passed to fetch/fetchrow, for assertions."""

    def __init__(self, rows):
        super().__init__(rows)
        self.fetch_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return await super().fetch(sql, *args)

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return await super().fetchrow(sql, *args)


def _provider(rows, conn_cls=_FakeConn):
    p = PostgresKBProvider()
    conn = conn_cls(rows)
    p._acquire = lambda: _FakeCtx(conn)
    return p, conn


# ── roster ────────────────────────────────────────────────────────────────


async def test_warm_and_cached_codes():
    p, _ = _provider(
        {
            "fetch": [
                {
                    "project_code": "NPLB",
                    "name": "Noble Palace Long Biên",
                    "region": "Long Biên",
                    "category": ["biet_thu"],
                },
            ]
        }
    )
    await p.warm()
    assert p.cached_codes() == ["NPLB"]
    assert p.code_to_name()["NPLB"] == "Noble Palace Long Biên"
    assert p.registry_rows()[0].region == "Long Biên"


async def test_warm_excludes_sentinel_and_multiple_rows():
    p, _ = _provider(
        {
            "fetch": [
                {"project_code": "NPLB", "name": "Noble Palace", "region": "Long Biên", "category": ["biet_thu"]},
                {"project_code": "SGR", "name": "Sunshine Green", "region": "Hà Đông", "category": []},
            ]
        }
    )
    await p.warm()
    assert set(p.cached_codes()) == {"NPLB", "SGR"}
    rows = {r.code: r for r in p.registry_rows()}
    assert rows["SGR"].type == ""  # empty category → empty type, no crash


async def test_warm_keeps_prior_cache_on_error():
    p, _ = _provider({"fetch": [{"project_code": "NPLB", "name": "Noble Palace", "region": "LB", "category": []}]})
    await p.warm()
    assert p.cached_codes() == ["NPLB"]

    async def _boom():
        raise RuntimeError("db down")

    class _BoomCtx:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    p._acquire = lambda: _BoomCtx()
    await p.warm()
    assert p.cached_codes() == ["NPLB"]  # unchanged


async def test_warm_if_stale_respects_ttl():
    rows = {"fetch": [{"project_code": "NPLB", "name": "N", "region": "", "category": []}]}
    p, conn = _provider(rows, _RecordingConn)
    await p.warm_if_stale(60.0)
    assert len(conn.fetch_calls) == 1
    await p.warm_if_stale(60.0)  # fresh — should not re-warm
    assert len(conn.fetch_calls) == 1
    await p.warm_if_stale(0.0)  # ttl<=0 → always refresh
    assert len(conn.fetch_calls) == 2


# ── list_projects ────────────────────────────────────────────────────────


async def test_list_projects_maps_summary():
    p, _ = _provider(
        {
            "fetch": [
                {
                    "project_code": "NPLB",
                    "name": "Noble Palace",
                    "region": "Long Biên",
                    "category": ["biet_thu"],
                    "investor": "Noble",
                    "sale_phase": "dang_ban",
                },
            ]
        }
    )
    result = await p.list_projects()
    assert isinstance(result, base.ProjectList)
    assert result.count == 1
    s = result.projects[0]
    assert s.code == "NPLB" and s.name == "Noble Palace" and s.category == ("biet_thu",)
    assert s.investor == "Noble" and s.sale_phase == "dang_ban"


async def test_list_projects_region_filter_forwarded():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.list_projects(region="Long Biên")
    sql, args = conn.fetch_calls[0]
    assert any("Long Biên" in str(a) for a in args)


# ── get_overview ─────────────────────────────────────────────────────────


async def test_get_overview_maps_fields():
    p, _ = _provider(
        {
            "fetchrow": {
                "project_code": "NPLB",
                "name": "Noble Palace",
                "region": "Long Biên",
                "address": "Số 1",
                "investor": "Noble",
                "developer": "Noble Dev",
                "total_land_area_m2": 120000,
                "floor_area_m2": 450000,
                "build_density_pct": 21,
                "product_scale": "2400 sp",
                "amenities": "Bể bơi",
                "ownership_form": "Lâu dài",
                "handover_standard": "Thô",
                "total_investment_vnd": 35000000000000,
                "sale_phase": "dang_ban",
                "overview": "Đại đô thị",
                "link_360": "kuula.co/x",
            }
        }
    )
    ov = await p.get_overview("NPLB")
    assert ov.total_land_area_m2 == 120000
    assert ov.sale_phase == "dang_ban"
    assert ov.investor == "Noble"
    assert ov.code == "NPLB" and ov.name == "Noble Palace"
    assert ov.link_360 == "kuula.co/x"


async def test_get_overview_casts_decimal_to_native():
    # asyncpg returns Postgres `numeric` columns as Decimal — the DTO declares
    # float/int, and a Decimal would blow up json.dumps() downstream.
    p, _ = _provider(
        {
            "fetchrow": {
                "project_code": "NPLB",
                "name": "Noble Palace",
                "region": None,
                "address": None,
                "investor": None,
                "developer": None,
                "total_land_area_m2": Decimal("120000.5"),
                "floor_area_m2": Decimal("450000"),
                "build_density_pct": Decimal("21"),
                "product_scale": None,
                "amenities": None,
                "ownership_form": None,
                "handover_standard": None,
                "total_investment_vnd": 35000000000000,
                "sale_phase": None,
                "overview": None,
                "link_360": None,
            }
        }
    )
    ov = await p.get_overview("NPLB")
    assert isinstance(ov.total_land_area_m2, float) and ov.total_land_area_m2 == 120000.5
    assert isinstance(ov.floor_area_m2, float)
    assert isinstance(ov.build_density_pct, float)
    assert isinstance(ov.total_investment_vnd, int)


async def test_discover_projects_casts_price_from_decimal_to_int():
    p, _ = _provider(
        {
            "fetch": [
                {
                    "project_code": "NPLB",
                    "name": "Noble Palace",
                    "region": "",
                    "category": [],
                    "investor": "",
                    "sale_phase": "dang_ban",
                    "amenities": None,
                    "pf": Decimal("5000000000"),
                },
            ]
        }
    )
    disc = await p.discover_projects(base.DiscoverQuery())
    assert isinstance(disc.projects[0].price_from_vnd, int)
    assert disc.projects[0].price_from_vnd == 5_000_000_000


async def test_get_overview_none_when_missing():
    p, _ = _provider({"fetchrow": None})
    assert await p.get_overview("NOPE") is None


async def test_get_overview_passes_project_code_arg():
    p, conn = _provider({"fetchrow": None}, _RecordingConn)
    await p.get_overview("NPLB")
    _, args = conn.fetchrow_calls[0]
    assert "NPLB" in args


# ── discover_projects ────────────────────────────────────────────────────


async def test_discover_projects_basic_shape():
    p, _ = _provider(
        {
            "fetch": [
                {
                    "project_code": "NPLB",
                    "name": "Noble Palace",
                    "region": "Long Biên",
                    "category": ["biet_thu"],
                    "investor": "Noble",
                    "sale_phase": "dang_ban",
                    "amenities": "Bể bơi; Gym",
                    "pf": 5_000_000_000,
                },
            ]
        }
    )
    result = await p.discover_projects(base.DiscoverQuery())
    assert isinstance(result, base.ProjectDiscovery)
    assert result.total == 1
    assert result.projects[0].price_from_vnd == 5_000_000_000
    # amenities đi kèm summary — nguyên liệu cho pitch vượt-ngân-sách (upsell).
    assert result.projects[0].amenities == "Bể bơi; Gym"


async def test_discover_projects_filters_forwarded_to_sql():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(
        base.DiscoverQuery(
            region="Long Biên",
            investor="Noble",
            sale_phase="dang_ban",
            product_type="biet_thu",
            budget_max_vnd=5_000_000_000,
        )
    )
    sql, args = conn.fetch_calls[0]
    assert [r"\mlong[^a-z0-9]+bien\M"] in args  # region → mảng pattern của một bậc
    assert any("Noble" in str(a) for a in args)
    assert "dang_ban" in args
    assert "biet_thu" in args
    assert 5_000_000_000 in args


# ── region matching (fold dấu + cụm liên tiếp; khớp region + address + name) ─


def test_vn_fold_table_matches_python_fold():
    """Bảng `translate()` phía SQL phải fold Y HỆT `fold.strip_tones` phía query,
    và hai vế phải BẰNG ĐỘ DÀI — `from` dài hơn `to` thì Postgres XOÁ ký tự thừa
    thay vì fold nó (đã sập một lần: 'đ' map thành 'y', "Đình" không ra "dinh").
    """
    assert len(postgres_kb._VN_FOLD_FROM) == len(postgres_kb._VN_FOLD_TO)
    for src, dst in zip(postgres_kb._VN_FOLD_FROM, postgres_kb._VN_FOLD_TO, strict=True):
        assert dst == fold.strip_tones(src)
    assert postgres_kb._VN_FOLD_TO[postgres_kb._VN_FOLD_FROM.index("đ")] == "d"


def test_region_tokens_folds_tones():
    """STT tiếng Việt thường ra chữ KHÔNG dấu — token phải fold về ascii để so
    được với cột đã fold trong SQL."""
    assert postgres_kb._region_tokens("Mỹ Đình") == ["my", "dinh"]
    assert postgres_kb._region_tokens("my dinh") == ["my", "dinh"]
    assert postgres_kb._region_tokens("MỸ ĐÌNH") == ["my", "dinh"]


def test_region_tokens_keeps_every_word():
    """KHÔNG có danh sách stopword: mọi từ hành chính tiếng Việt đều trùng một
    tên địa danh thật khi bỏ dấu (đường↔Dương, trấn↔Trần, thành↔Thanh,
    tỉnh↔Tĩnh), nên lọc theo từ điển sẽ ăn mất âm tiết của "Bình Dương",
    "Trần Phú", "Hà Tĩnh". Từ hành chính thừa được xử lý ở tầng cụm."""
    assert postgres_kb._region_tokens("Quận Tây Hồ") == ["quan", "tay", "ho"]
    assert postgres_kb._region_tokens("Bình Dương") == ["binh", "duong"]
    assert postgres_kb._region_tokens("Hà Tĩnh") == ["ha", "tinh"]
    assert postgres_kb._region_tokens("Quận 7") == ["quan", "7"]


def test_region_tokens_strips_punctuation():
    assert postgres_kb._region_tokens("Tây Hồ, Hà Nội.") == ["tay", "ho", "ha", "noi"]


def test_region_tokens_empty_for_junk():
    assert postgres_kb._region_tokens("") == []
    assert postgres_kb._region_tokens("...") == []


def test_region_tokens_keeps_the_whole_address():
    """KHÔNG cắt lời khách. Cắt token là hỏng CỨNG — mất "Nam Từ Liêm" là dự án
    đó biến mất khỏi câu trả lời, im lặng. Chi phí được chặn ở độ dài CỤM
    (`_MAX_REGION_GROUP`) chứ không phải ở số token."""
    assert postgres_kb._region_tokens("Thành phố Hà Nội, Quận Nam Từ Liêm, Phường Mỹ Đình 2") == [
        "thanh",
        "pho",
        "ha",
        "noi",
        "quan",
        "nam",
        "tu",
        "liem",
        "phuong",
        "my",
        "dinh",
        "2",
    ]


def test_region_tokens_still_guards_against_a_junk_payload():
    """Trần còn lại chỉ chặn LLM tuồn nguyên đoạn văn, đặt ở mức không đời nào
    chạm tới khi nói địa chỉ thật."""
    assert len(postgres_kb._region_tokens(" ".join(f"tu{i}" for i in range(200)))) == postgres_kb._MAX_REGION_TOKENS
    assert postgres_kb._MAX_REGION_TOKENS >= 40


def test_region_rank_expr_never_builds_groups_longer_than_any_real_place_name():
    """Cụm dài hơn mọi địa danh có thật thì không bao giờ khớp — sinh chúng là
    trả chi phí bậc 2 cho pattern vô dụng. Trần 5 = "Thành phố Hồ Chí Minh",
    tên dài nhất cần khớp nguyên cụm."""
    tokens = postgres_kb._region_tokens("Thành phố Hà Nội, Quận Nam Từ Liêm, Phường Mỹ Đình 2")
    args: list = []
    postgres_kb._region_rank_expr(tokens, args)
    longest = max(len(p.split("[^a-z0-9]+")) for group in args for p in group)
    assert longest == postgres_kb._MAX_REGION_GROUP == 5
    # số pattern tuyến tính theo độ dài query, không còn n(n-1)/2
    assert sum(len(g) for g in args) < 4 * len(tokens)


def test_region_rank_expr_keeps_the_district_of_a_long_query():
    """Chính ca của finding IMPORTANT, ở query dài hơn: tên quận vẫn phải có
    cụm riêng dù nó nằm giữa câu."""
    tokens = postgres_kb._region_tokens("Thành phố Hà Nội, Quận Nam Từ Liêm, Phường Mỹ Đình 2")
    args: list = []
    postgres_kb._region_rank_expr(tokens, args)
    flat = [p for group in args for p in group]
    assert r"\mnam[^a-z0-9]+tu[^a-z0-9]+liem\M" in flat
    assert r"\mmy[^a-z0-9]+dinh\M" in flat


def test_region_queries_keeps_the_original_and_only_adds_aliases():
    """Bảng alias THÊM câu, không thay câu chính: câu gốc luôn đứng đầu và giữ
    nguyên trọng số, alias chỉ mở rộng cơ hội khớp."""
    qs = postgres_kb._region_queries(["ho", "tay"])
    assert qs[0][0] == ["ho", "tay"]  # gốc, nguyên vẹn
    assert ["tay", "ho"] in [toks for toks, _w in qs]  # alias thêm vào


def test_region_queries_weights_alias_by_original_token_count():
    """Câu alias được chấm theo SỐ TOKEN GỐC nó đại diện, không theo độ dài của
    chính nó — nếu không, "ho chi minh" (3 từ) đè "sai gon" (2 từ) và query
    "Sài Gòn" đánh mất dự án ghi region="Sài Gòn"."""
    qs = dict((" ".join(t), w) for t, w in postgres_kb._region_queries(["sai", "gon"]))
    assert qs["sai gon"] == [1, 1]
    # 3 token alias cùng đại diện 2 token gốc → mỗi token 2/3
    assert sum(qs["ho chi minh"]) == 2
    assert len(qs["ho chi minh"]) == 3


def test_region_rank_expr_ranks_by_original_tokens_covered():
    args: list = []
    expr = postgres_kb._region_rank_expr(["tran", "phu", "ha"], args)
    assert expr.startswith("CASE WHEN ") and expr.endswith(" ELSE 0 END")
    assert expr.count("WHEN ") == 2  # bậc 3 và bậc 2, KHÔNG có bậc 1
    assert [r"\mtran[^a-z0-9]+phu[^a-z0-9]+ha\M"] in args
    assert sorted(args[1]) == sorted([r"\mphu[^a-z0-9]+ha\M", r"\mtran[^a-z0-9]+phu\M"])


def test_region_rank_expr_never_ranks_a_lone_syllable():
    """Một âm tiết đơn lẻ khớp bừa ("binh" ăn Bình Tân/Bình Thạnh) → sàn 2 token."""
    args: list = []
    postgres_kb._region_rank_expr(["binh", "duong"], args)
    assert all(all("[^a-z0-9]+" in p for p in group) for group in args)


def test_region_rank_expr_allows_single_token_query_via_alias():
    """ "TPHCM" chỉ 1 token → sàn hạ xuống 1, nếu không alias 1-token vô dụng."""
    args: list = []
    expr = postgres_kb._region_rank_expr(["tphcm"], args)
    assert expr  # có filter
    flat = [p for group in args for p in group]
    assert any("ho[^a-z0-9]+chi[^a-z0-9]+minh" in p for p in flat)


def test_region_rank_expr_empty_without_tokens():
    args: list = []
    assert postgres_kb._region_rank_expr([], args) == ""
    assert args == []


async def test_discover_projects_uses_a_single_query():
    """Mọi bậc cụm nằm trong MỘT CASE → một round-trip, kể cả query 8 token."""
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(base.DiscoverQuery(region="Phường Mỹ Đình 2, Quận Nam Từ Liêm"))
    assert len(conn.fetch_calls) == 1
    sql, _args = conn.fetch_calls[0]
    assert sql.startswith("WITH c AS (")
    assert "ILIKE" not in sql  # region không còn ILIKE thô


async def test_discover_and_search_units_share_the_same_region_expression():
    """Hai hàm phải khớp khu vực y hệt nhau — lệch nhau thì cùng một lời khách ra
    dự án ở discover nhưng rỗng ở search_units rồi escalate oan."""
    p1, c1 = _provider({"fetch": []}, _RecordingConn)
    await p1.discover_projects(base.DiscoverQuery(region="Quận Tây Hồ"))
    p2, c2 = _provider({"fetch": []}, _RecordingConn)
    await p2.search_units(base.UnitQuery(project_code="", region="Quận Tây Hồ"))
    expr = postgres_kb._region_rank_expr(["quan", "tay", "ho"], [])
    skeleton = expr.split(" ~ ANY(")[0]  # phần haystack, không phụ thuộc số param
    assert skeleton in c1.fetch_calls[0][0]
    assert skeleton in c2.fetch_calls[0][0]
    # cùng tập pattern khu vực, chỉ khác vị trí bound param
    pats = lambda c: sorted(p for a in c.fetch_calls[0][1] if isinstance(a, list) for p in a)  # noqa: E731
    assert pats(c1) == pats(c2)


async def test_search_units_caps_after_ranking_not_before():
    """LIMIT 200 phải nằm NGOÀI CTE: cắt 200 dòng TRƯỚC khi chấm điểm sẽ vứt
    mất căn đúng — chính cái mà comment "safety cap" cảnh báo."""
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="", region="Tây Hồ"))
    sql, _ = conn.fetch_calls[0]
    assert sql.index("LIMIT 200") > sql.index("SELECT max(_m)")


async def test_discover_projects_orders_outside_the_cte():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(base.DiscoverQuery(region="Tây Hồ"))
    sql, _ = conn.fetch_calls[0]
    assert sql.index("ORDER BY") > sql.index("SELECT max(_m)")


async def test_discover_projects_region_alias_adds_a_query():
    """ "Hồ Tây" (khách đảo từ) vẫn tìm ra dự án ghi "Tây Hồ" — và pattern của câu
    GỐC vẫn có mặt."""
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(base.DiscoverQuery(region="Hồ Tây"))
    flat = [pat for a in conn.fetch_calls[0][1] if isinstance(a, list) for pat in a]
    assert r"\mho[^a-z0-9]+tay\M" in flat  # gốc
    assert r"\mtay[^a-z0-9]+ho\M" in flat  # alias


async def test_discover_projects_region_skipped_when_no_tokens():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(base.DiscoverQuery(region="..."))
    sql, args = conn.fetch_calls[0]
    assert len(conn.fetch_calls) == 1
    assert "translate(" not in sql
    assert len(args) == 2  # sentinel + tenant_id, không có arg region nào


def _bare_rows(n: int) -> list[dict]:
    return [
        {
            "project_code": f"P{i}",
            "name": f"Project {i}",
            "region": "",
            "category": [],
            "investor": "",
            "sale_phase": "dang_ban",
            "amenities": None,
            "pf": None,
        }
        for i in range(n)
    ]


async def test_discover_projects_total_before_slice():
    p, _ = _provider({"fetch": _bare_rows(8)})
    result = await p.discover_projects(base.DiscoverQuery(offset=0, limit=5))
    assert result.total == 8
    assert len(result.projects) == 5


async def test_discover_projects_offset_slice():
    p, _ = _provider({"fetch": _bare_rows(8)})
    result = await p.discover_projects(base.DiscoverQuery(offset=5, limit=5))
    assert len(result.projects) == 3
    assert result.projects[0].code == "P5"


# ── search_units (Task 4) ────────────────────────────────────────────────


def _unit_row(**overrides) -> dict:
    row = {
        "project_code": "NPLB",
        "project_name": "Noble Palace",
        "zone_code": "Z1",
        "unit_code": "A-101",
        "product_type": "biet_thu",
        "bedrooms": 3,
        "block": "A",
        "floor": 1,
        "num_floors": 3,
        "direction": "Đông Nam",
        "area_built_m2": 120.5,
        "area_wall_m2": 135.0,
        "area_land_m2": 200.0,
        "price_vnd": 5_000_000_000,
        "price_per_m2_vnd": 41_000_000,
        "sale_status": "available",
        "image_url": "https://x/y.jpg",
    }
    row.update(overrides)
    return row


async def test_search_units_maps_fields():
    p, _ = _provider({"fetch": [_unit_row()]})
    units = await p.search_units(base.UnitQuery(project_code="NPLB"))
    assert units is not None
    u = units[0]
    assert isinstance(u, base.Unit)
    assert u.product_type == "biet_thu"
    assert u.area_built_m2 == 120.5
    assert u.sale_status == "available"
    assert u.block == "A"
    assert u.project_name == "Noble Palace"
    assert u.unit_code == "A-101"


async def test_search_units_casts_decimal_to_native():
    p, _ = _provider(
        {
            "fetch": [
                _unit_row(
                    area_built_m2=Decimal("120.5"),
                    area_wall_m2=Decimal("135"),
                    area_land_m2=Decimal("200"),
                    price_vnd=Decimal("5000000000"),
                    price_per_m2_vnd=Decimal("41000000"),
                )
            ]
        }
    )
    units = await p.search_units(base.UnitQuery(project_code="NPLB"))
    u = units[0]
    assert isinstance(u.price_vnd, int) and u.price_vnd == 5_000_000_000
    assert isinstance(u.price_per_m2_vnd, int)
    assert isinstance(u.area_built_m2, float) and u.area_built_m2 == 120.5
    assert isinstance(u.area_wall_m2, float)
    assert isinstance(u.area_land_m2, float)


async def test_search_units_filters_forwarded_to_sql():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(
        base.UnitQuery(
            project_code="NPLB",
            product_type="biet_thu",
            max_price_vnd=5_000_000_000,
            direction="Đông Nam",
            floor=2,
            block="A",
            unit_code="A-101",
            sale_status="available",
            min_area_built_m2=100.0,
        )
    )
    _, args = conn.fetch_calls[0]
    assert "NPLB" in args
    assert "biet_thu" in args
    assert 5_000_000_000 in args
    assert "Đông Nam" in args
    assert 2 in args
    assert "A" in args
    assert "A-101" in args
    assert "available" in args
    assert 100.0 in args


async def test_search_units_area_band_forwarded_as_floor_and_ceiling():
    # "tầm 120 m²" arrives as min+max (the tool derives the band); the SQL must
    # bound area_built_m2 on BOTH sides, not just the >= floor it used to have.
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB", min_area_built_m2=96.0, max_area_built_m2=144.0))
    sql, args = conn.fetch_calls[0]
    assert 96.0 in args and 144.0 in args
    assert "u.area_built_m2 >= $" in sql and "u.area_built_m2 <= $" in sql


async def test_search_units_max_area_alone_is_a_ceiling_only():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB", max_area_built_m2=80.0))
    sql, args = conn.fetch_calls[0]
    assert 80.0 in args
    assert "u.area_built_m2 <= $" in sql and "u.area_built_m2 >= $" not in sql


async def test_search_units_empty_returns_none():
    p, _ = _provider({"fetch": []})
    result = await p.search_units(base.UnitQuery(project_code="NPLB"))
    assert result is None


# ── search_units hợp nhất (nuốt recommend_units, merge 2026-09-07) ───────


async def test_search_units_returns_raw_unsorted():
    rows = [
        _unit_row(unit_code="B-2", price_vnd=6_000_000_000),
        _unit_row(unit_code="A-1", price_vnd=4_000_000_000),
    ]
    p, _ = _provider({"fetch": rows})
    units = await p.search_units(base.UnitQuery(project_code="", max_price_vnd=7_000_000_000))
    # raw order preserved — no feng-shui sort here (that's the tool's job)
    assert [u.unit_code for u in units] == ["B-2", "A-1"]


async def test_search_units_bedrooms_and_region_scope_filter():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB", region="Long Biên", bedrooms=2))
    _, args = conn.fetch_calls[0]
    assert "NPLB" in args
    assert [r"\mlong[^a-z0-9]+bien\M"] in args  # region → mảng pattern của một bậc
    assert 2 in args


async def test_search_units_region_matches_like_discover():
    """Phải khớp khu vực y như discover_projects — lệch nhau thì khách nói "Mỹ
    Đình" sẽ ra dự án ở discover nhưng search_units rỗng → escalate oan."""
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="", region="quận Mỹ Đình"))
    assert len(conn.fetch_calls) == 1  # mọi bậc cụm nằm trong một CASE
    sql, args = conn.fetch_calls[0]
    flat = [pat for a in args if isinstance(a, list) for pat in a]
    assert r"\mquan[^a-z0-9]+my[^a-z0-9]+dinh\M" in flat  # bậc 3
    assert r"\mmy[^a-z0-9]+dinh\M" in flat  # bậc 2
    assert "translate(" in sql and "p.region" in sql and "p.address" in sql
    assert "ILIKE" not in sql


async def test_search_units_always_caps_at_200_raw():
    """Tool sort trước rồi mới cắt trang, nên provider chỉ cap thô LIMIT 200
    (an toàn bộ nhớ) — KHÔNG bound-param LIMIT theo trang."""
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB"))
    sql, args = conn.fetch_calls[0]
    assert sql.rstrip().endswith("LIMIT 200")
    assert 6 not in args and 200 not in args


# ── get_document (Task 4) ────────────────────────────────────────────────


async def test_get_document_maps_rows_scope_all():
    p, conn = _provider(
        {
            "fetch": [
                {
                    "project_code": "NPLB",
                    "title": "Chính sách bán hàng",
                    "body": "Nội dung...",
                    "file_url": "https://x/pol.pdf",
                }
            ]
        },
        _RecordingConn,
    )
    docs = await p.get_document("NPLB")
    assert docs == [
        base.Document(
            project_code="NPLB", title="Chính sách bán hàng", body="Nội dung...", file_url="https://x/pol.pdf"
        )
    ]
    _, args = conn.fetch_calls[0]
    assert list(args[0]) == ["NPLB", "__ALL__"]


async def test_get_document_empty_list_not_none():
    p, _ = _provider({"fetch": []})
    docs = await p.get_document("NPLB")
    assert docs == []
    assert docs is not None


async def test_get_document_query_filter_forwarded():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.get_document("NPLB", query="chính sách")
    _, args = conn.fetch_calls[0]
    assert any("chính sách" in str(a) for a in args)


async def test_get_document_all_scope_keeps_own_project_code():
    """A tenant-wide '__ALL__' doc matched under a specific project query must
    keep project_code == '__ALL__' (the row's own value), not the queried
    project code that happened to include it in scope."""
    p, _ = _provider(
        {
            "fetch": [
                {
                    "project_code": "__ALL__",
                    "title": "Chính sách chung",
                    "body": "Áp dụng toàn hệ thống...",
                    "file_url": "https://x/global.pdf",
                }
            ]
        }
    )
    docs = await p.get_document("NPLB")
    assert docs[0].project_code == "__ALL__"


# ── price filter vs căn chưa có giá (price_vnd = 0/NULL) ─────────────────


async def test_search_units_price_filter_excludes_unpriced():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB", max_price_vnd=5_000_000_000))
    sql, _ = conn.fetch_calls[0]
    assert "u.price_vnd > 0" in sql


async def test_discover_min_price_ignores_unpriced_units():
    p, conn = _provider({"fetch": []}, _RecordingConn)
    await p.discover_projects(base.DiscoverQuery())
    sql, _ = conn.fetch_calls[0]
    assert "min(price_vnd) FILTER (WHERE price_vnd > 0)" in sql


async def test_search_units_empty_project_code_searches_all_projects():
    # RULES hứa "bỏ trống project_code = tìm trên TẤT CẢ dự án" nhưng SQL từng
    # hardcode u.project_code=$1 → ''= không khớp gì → ESCALATE_SIGNAL oan
    # (qwen3.7-flash dẫm trúng 2026-08-24: "5 tỷ mua căn nào" → escalate).
    p, conn = _provider({"fetch": [_unit_row()]}, conn_cls=_RecordingConn)
    units = await p.search_units(base.UnitQuery(project_code="", max_price_vnd=5_000_000_000))
    assert units is not None and len(units) == 1
    sql, args = conn.fetch_calls[0]
    assert "u.project_code" not in sql
    assert "" not in args


async def test_search_units_with_project_code_still_filters():
    p, conn = _provider({"fetch": [_unit_row()]}, conn_cls=_RecordingConn)
    await p.search_units(base.UnitQuery(project_code="NPLB"))
    sql, args = conn.fetch_calls[0]
    assert "u.project_code = $1" in sql
    assert args[0] == "NPLB"


# ── name vào haystack (2026-08-25) ───────────────────────────────────────────


def _khop(haystack_row: str, region_query: str) -> bool:
    r"""Chạy đúng luật khớp của SQL bằng Python, trên MỘT dòng giả lập.

    `_region_rank_expr` sinh regex Postgres; `\m…\M` (biên từ của Postgres) đổi
    thành `\b` để `re` hiểu. Không mô phỏng gì khác — pattern, thứ tự bậc và phép
    fold đều lấy thẳng từ code thật.
    """
    args: list = []
    expr = postgres_kb._region_rank_expr(postgres_kb._region_tokens(region_query), args)
    if not expr:
        return False
    hay = fold.strip_tones(haystack_row).lower()
    return any(re.search(pat.replace(r"\m", r"\b").replace(r"\M", r"\b"), hay) for group in args for pat in group)


def test_haystack_gom_ca_ba_cot():
    """Thiếu `p.name` là bỏ sót đúng lớp dự án mang địa danh trong TÊN."""
    hs = postgres_kb._region_haystack()
    assert "p.region" in hs
    assert "p.address" in hs
    assert "p.name" in hs


def test_dia_danh_chi_nam_trong_TEN_van_tim_duoc():
    """Ca thật trên tenant `aina_test` (2026-08-25), lý do của cả thay đổi này.

    Khách hỏi "dự án ở Tây Hồ" → agent trả "chưa có dự án nào", trong khi tenant có
    NOBLE CRYSTAL TÂY HỒ. Phường Tây Hồ đã sáp nhập nên địa chỉ ghi "Phú Thượng";
    chuỗi "tây hồ" khớp 0/35 dòng nếu haystack chỉ có region + address.
    """
    region = "Thành phố Hà Nội"
    address = "Ô đất CTO1, Khu đô thị Nam Thăng Long giai đoạn III, Phường Phú Thượng, Thành phố Hà Nội"
    name = "NOBLE CRYSTAL TÂY HỒ"

    assert not _khop(f"{region} {address}", "Tây Hồ"), "tiền đề: hai cột cũ KHÔNG chứa Tây Hồ"
    assert _khop(f"{region} {address} {name}", "Tây Hồ")


def test_ten_khong_pha_luat_cum_lien_nhau():
    """`name` không được nới luật: các từ vẫn phải LIỀN NHAU trong chuỗi."""
    assert not _khop("Thành phố Hà Nội, Phường Phú Thượng NOBLE CRYSTAL TÂY HỒ", "Tây Ninh")
    assert not _khop("Tỉnh Hưng Yên ECOPARK GRAND THE ISLAND", "Hưng Hà")


def test_ten_thuong_hieu_mot_tu_van_khop_duoc():
    """Đánh đổi đã biết: sàn là 1 khi khách chỉ nói MỘT từ, nên "Vinhomes" giờ ra
    mọi dự án Vinhomes thay vì rỗng. Ghi lại làm quyết định, không phải tai nạn."""
    assert _khop("Thành phố Hà Nội, Đông Anh VINHOMES GLOBAL GATE", "Vinhomes")


def test_hai_ham_van_dung_chung_haystack_ba_cot():
    """`discover_projects` và `recommend_units` phải khớp y hệt — lệch là cùng một
    lời khách ra dự án ở bên này và rỗng ở bên kia."""
    hs = postgres_kb._region_haystack()
    assert hs.count("p.name") == 1
