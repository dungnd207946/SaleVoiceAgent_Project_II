"""PostgresKBProvider — native reader of the SP1 KB schema (tenant_data.*).

Reads projects/zones/units/documents/media directly and maps rows 1:1 onto the
canonical DTOs — no translation shim. Every read is scoped to the current tenant
by an EXPLICIT `tenant_id = current_tenant()` predicate on each query (works with
RLS off), backed by `tenant_conn` setting `app.current_tenant` so the RLS
`agent_runtime` policy still binds if/when the backend re-enables RLS. Roster (warm/cached_codes/
registry_rows) comes from `projects` (published, minus the `__ALL__` sentinel).

Units / documents map their SQL rows the same way. `search_units` là method căn
DUY NHẤT (nuốt recommend_units 2026-09-07): project_code rỗng = xuyên dự án,
region rank như discover, trả RAW candidates (cap 200) cho tool sort rồi cắt trang.
"""

from __future__ import annotations

import logging
import re
import time
from fractions import Fraction

from noble_agent.data.project_matching import fold
from noble_agent.data.providers import base
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("noble_agent.data.providers.postgres_kb")

_SENTINEL = "__ALL__"

# Ranking order for sale_phase — earlier = shown first.
_SALE_PHASE_ORDER = ["dang_ban", "sap_mo_ban", "ban_giao", "dong_gio_hang"]


# Bảng fold dấu cho `translate()` phía SQL — phải khớp `fold.strip_tones` ở
# phía query. Dùng translate (built-in) thay vì `unaccent` để không phải cài
# extension / đụng schema; kèm cả bản chữ HOA nên không phụ thuộc `lower()` có
# hạ được ký tự có dấu theo collation của DB hay không.
_VN_FOLD_LOWER = "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ"
_VN_FOLD_FROM = _VN_FOLD_LOWER + _VN_FOLD_LOWER.upper()
# Sinh từ chính `fold.strip_tones` — bảng gõ tay lệch 1 ký tự là đủ để Postgres
# XOÁ ký tự thay vì fold nó (translate bỏ phần `from` dài hơn `to`), và unit
# test mức SQL-text không thấy gì cả.
_VN_FOLD_TO = "".join(fold.strip_tones(c) for c in _VN_FOLD_FROM)

# Độ dài cụm tối đa = tên địa danh dài nhất cần khớp nguyên cụm ("Thành phố Hồ
# Chí Minh" = 5; "Bà Rịa Vũng Tàu" = 4; "Nam Từ Liêm" = 3). Cụm dài hơn thế không
# bao giờ khớp gì, nên sinh chúng là trả chi phí n(n-1)/2 cho pattern vô dụng —
# chặn ở ĐÂY thì chi phí thành tuyến tính và KHÔNG phải cắt lời khách.
#
# Trần này hỏng MỀM: đặt thấp quá thì cụm dài nhất khớp được ngắn đi, vài dòng
# hoà bậc thay vì một dòng thắng — rộng hơn, không mất kết quả. Trần trên SỐ
# TOKEN thì ngược lại, hỏng CỨNG: cắt mất "Nam Từ Liêm" là dự án đó biến mất
# khỏi câu trả lời mà không ai biết (finding IMPORTANT của MR !44).
_MAX_REGION_GROUP = 5
# Chỉ còn chặn payload rác (LLM tuồn nguyên đoạn văn), đặt ở mức không đời nào
# chạm tới khi khách đọc địa chỉ thật.
_MAX_REGION_TOKENS = 50
_REGION_SANITIZE = re.compile(r"[^a-z0-9]+")

# Các cách gọi KHÁC NHAU của CÙNG một địa danh. Chỉ THÊM câu truy vấn, không thay
# câu gốc — thiếu một alias thì tệ nhất là không khớp (như khi chưa có bảng này),
# không bao giờ biến một khớp đúng thành khớp sai. Khai báo có dấu cho dễ đọc.
_REGION_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("hồ tây", "tây hồ"),
    ("hồ chí minh", "sài gòn", "tp hcm", "tphcm", "hcm"),
)
_REGION_ALIASES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {}
for _group in _REGION_ALIAS_GROUPS:
    _folded = tuple(tuple(fold.strip_tones(name).split()) for name in _group)
    for _name in _folded:
        _REGION_ALIASES[_name] = tuple(alt for alt in _folded if alt != _name)


def _region_tokens(raw: str) -> list[str]:
    """Tách lời khách thành token khu vực đã fold dấu.

    KHÔNG lọc stopword: mọi từ hành chính tiếng Việt đều trùng một tên địa danh
    thật khi bỏ dấu (đường↔Dương, trấn↔Trần, thành↔Thanh, tỉnh↔Tĩnh, xã↔Xã Đàn),
    nên lọc theo từ điển ăn mất âm tiết của "Bình Dương" / "Trần Phú" / "Hà Tĩnh"
    và biến filter thành một âm tiết khớp bừa. Từ hành chính thừa được xử lý ở
    tầng cụm — cụm chứa nó đơn giản là không có trong dữ liệu.
    """
    return [t for t in _REGION_SANITIZE.sub(" ", fold.strip_tones(raw)).split() if t][:_MAX_REGION_TOKENS]


def _region_queries(tokens: list[str]) -> list[tuple[list[str], list[Fraction]]]:
    """Câu GỐC (luôn đứng đầu) + các câu sinh từ bảng alias, kèm trọng số mỗi token.

    Trọng số = số token GỐC mà token đó đại diện; các token của một alias chia đều
    ``len(gốc)`` cho nhau. Nhờ vậy cụm sinh từ alias được chấm theo lời khách chứ
    không theo độ dài của chính nó — nếu không, "ho chi minh" (3 từ) đè "sai gon"
    (2 từ) và query "Sài Gòn" đánh mất dự án ghi region="Sài Gòn".
    """
    out: list[tuple[list[str], list[Fraction]]] = [(tokens, [Fraction(1)] * len(tokens))]
    for key, alts in _REGION_ALIASES.items():
        for i in range(len(tokens) - len(key) + 1):
            if tuple(tokens[i : i + len(key)]) != key:
                continue
            for alt in alts:
                w = Fraction(len(key), len(alt))
                out.append(
                    (
                        [*tokens[:i], *alt, *tokens[i + len(key) :]],
                        [Fraction(1)] * i + [w] * len(alt) + [Fraction(1)] * (len(tokens) - i - len(key)),
                    )
                )
    return out


def _region_haystack() -> str:
    """BA cột gộp làm một chuỗi rồi fold dấu, so với token đã fold ở phía query.

    `region` thường chỉ ghi cấp tỉnh/thành ("Thành phố Hà Nội") nên tên phường/đường
    khách nói ("Mỹ Đình", "Tố Hữu") chỉ có trong `address`.

    `name` vào từ 2026-08-25, và nó KHÔNG phải "cho chắc" — đo trên tenant thật:
    khách hỏi "dự án ở Tây Hồ", agent trả "chưa có dự án nào". Nhưng tenant có HAI
    dự án tên NOBLE PALACE TÂY HỒ và NOBLE CRYSTAL TÂY HỒ, và cả hai đều ghi
    `region='Thành phố Hà Nội'`, `address='… Phường Phú Thượng, Thành phố Hà Nội'`.
    Chuỗi "tây hồ" khớp **0/35** dòng trên haystack hai cột — nó chỉ nằm trong TÊN.

    Nguyên nhân gốc là hành chính: phường Tây Hồ đã sáp nhập nên nó biến mất khỏi
    địa chỉ, trong khi khách vẫn gọi theo tên cũ và chủ đầu tư vẫn đặt tên dự án
    theo nó. Địa danh cũ vì thế sống sót ở đúng một chỗ — cột `name` — và bất kỳ
    lần sáp nhập nào sau này cũng sẽ tạo lại đúng tình huống ấy.

    ⚠️ Đánh đổi: tên thương hiệu trong `name` giờ khớp được như địa danh, nên khách
    nói "Vinhomes" (1 token) sẽ ra mọi dự án Vinhomes thay vì rỗng. Chấp nhận —
    tệ nhất là trả về đúng thứ khách vừa nhắc tên, và luật cụm (từ phải LIỀN NHAU,
    sàn 2 token khi khách nói từ 2 từ trở lên) vẫn chặn khớp bừa theo âm tiết lẻ.
    """
    return (
        f"translate(lower(coalesce(p.region,'') || ' ' || coalesce(p.address,'') "
        f"|| ' ' || coalesce(p.name,'')), "
        f"'{_VN_FOLD_FROM}', '{_VN_FOLD_TO}')"
    )


def _region_rank_expr(tokens: list[str], args: list) -> str:
    """`CASE` chấm mỗi dòng bằng ĐỘ DÀI CỤM DÀI NHẤT nó khớp được (0 = không khớp).

    Các từ trong cụm phải LIỀN NHAU (`[^a-z0-9]+` giữa chúng) — AND từng từ rời
    thì "Bình Dương" khớp cả dự án region "Bình Tân" + address "Kinh Dương Vương".
    Biên từ `\\m…\\M` để "hồ" không ăn "hoàng mai". Sàn 2 token (1 khi khách chỉ
    nói đúng một từ): một âm tiết đơn lẻ khớp bừa, thà `total=0` để agent nói
    "khu này chưa có dự án" hơn là gợi ý sai khu vực.

    Mỗi bậc là MỘT bound param `text[]` nên toàn bộ nằm gọn trong một câu SQL —
    không phải một query cho mỗi độ dài cụm. Token đã sanitize còn ``[a-z0-9]``
    nên pattern không thể mang metachar regex.
    """
    if not tokens:
        return ""
    floor = min(2, len(tokens))
    by_rank: dict[int, set[str]] = {}
    for toks, weights in _region_queries(tokens):
        for size in range(min(len(toks), _MAX_REGION_GROUP), 0, -1):
            for i in range(len(toks) - size + 1):
                rank = int(sum(weights[i : i + size]))  # số token gốc được bao phủ
                if rank < floor:
                    continue
                by_rank.setdefault(rank, set()).add(r"\m" + r"[^a-z0-9]+".join(toks[i : i + size]) + r"\M")
    if not by_rank:
        return ""
    haystack = _region_haystack()
    whens = []
    for rank in sorted(by_rank, reverse=True):
        args.append(sorted(by_rank[rank]))
        whens.append(f"WHEN {haystack} ~ ANY(${len(args)}::text[]) THEN {rank}")
    return "CASE " + " ".join(whens) + " ELSE 0 END"


def _region_scoped(select_sql: str, tail: str) -> str:
    """Bọc query trong CTE và chỉ giữ các dòng khớp CỤM DÀI NHẤT tìm được trên
    toàn bảng. `tail` (ORDER BY / LIMIT) phải nằm NGOÀI CTE: cắt trước khi chấm
    điểm là vứt mất dòng đúng."""
    return f"WITH c AS ({select_sql}) SELECT * FROM c WHERE _m > 0 AND _m = (SELECT max(_m) FROM c){tail}"


def _f(x) -> float | None:
    """Cast a Postgres numeric (asyncpg → Decimal) to native float; keep None."""
    return float(x) if x is not None else None


def _i(x) -> int | None:
    """Cast a Postgres numeric/bigint (asyncpg → Decimal/int) to native int; keep None."""
    return int(x) if x is not None else None


class _LazyCtx:
    """Adapts a coroutine that resolves to an async CM into a directly-usable
    async CM, so `_acquire()` can stay a plain sync method usable in
    `async with self._acquire() as conn:`.
    """

    def __init__(self, coro) -> None:
        self._coro = coro
        self._cm = None

    async def __aenter__(self):
        self._cm = await self._coro
        return await self._cm.__aenter__()

    async def __aexit__(self, *exc_info):
        return await self._cm.__aexit__(*exc_info)


class PostgresKBProvider:
    name = "pg_kb"
    capabilities = frozenset(
        {
            base.Capability.LISTING,
            base.Capability.OVERVIEW,
            base.Capability.UNIT_SEARCH,
        }
    )

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._last_warm = 0.0

    def _acquire(self):
        """Async CM yielding a tenant-scoped connection. Overridden in tests."""
        from noble_agent.storage import postgres_client

        async def _ctx():
            tid = current_tenant()
            pool = await postgres_client.pool_for_tenant(tid)
            return postgres_client.tenant_conn(pool, tid)

        return _LazyCtx(_ctx())

    # ---- roster ----
    async def warm(self) -> None:
        try:
            async with self._acquire() as conn:
                rows = await conn.fetch(
                    "SELECT project_code, name, region, category FROM tenant_data.projects "
                    "WHERE status='published' AND project_code <> $1 AND tenant_id = $2",
                    _SENTINEL,
                    current_tenant(),
                )
            self._rows = {
                r["project_code"]: {
                    "code": r["project_code"],
                    "name": r["name"] or "",
                    "region": r["region"] or "",
                    "type": (r["category"][0] if r["category"] else ""),
                }
                for r in rows
            }
        except Exception:
            logger.warning("pg_kb warm failed", exc_info=True)  # keep prior cache; best-effort
        self._last_warm = time.monotonic()

    async def warm_if_stale(self, ttl_sec: float) -> None:
        if ttl_sec <= 0 or (time.monotonic() - self._last_warm) > ttl_sec:
            await self.warm()

    def cached_codes(self) -> list[str]:
        return list(self._rows)

    def code_to_name(self) -> dict[str, str]:
        return {c: v["name"] for c, v in self._rows.items()}

    def registry_rows(self) -> list[base.ProjectRegistryRow]:
        return [
            base.ProjectRegistryRow(code=v["code"], name=v["name"], region=v["region"], type=v["type"])
            for v in self._rows.values()
        ]

    # ---- projects ----
    async def list_projects(self, *, region: str = "") -> base.ProjectList | None:
        sql = (
            "SELECT project_code, name, region, category, investor, sale_phase "
            "FROM tenant_data.projects WHERE status='published' AND project_code <> $1"
        )
        args: list = [_SENTINEL]
        if region:
            sql += f" AND region ILIKE ${len(args) + 1}"
            args.append(f"%{region}%")
        sql += f" AND tenant_id = ${len(args) + 1}"
        args.append(current_tenant())
        sql += " ORDER BY name"
        async with self._acquire() as conn:
            rows = await conn.fetch(sql, *args)
        projects = [_row_to_summary(r, price_from=None) for r in rows]
        return base.ProjectList(count=len(projects), projects=projects, region=region)

    async def get_overview(self, project_code: str) -> base.ProjectOverview | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT project_code, name, region, address, investor, developer, "
                "total_land_area_m2, floor_area_m2, build_density_pct, product_scale, "
                "amenities, ownership_form, handover_standard, total_investment_vnd, "
                "sale_phase, overview, link_360 "
                "FROM tenant_data.projects WHERE project_code=$1 AND status='published' AND tenant_id=$2",
                project_code,
                current_tenant(),
            )
        if row is None:
            return None
        return base.ProjectOverview(
            code=row["project_code"],
            name=row["name"],
            region=row["region"],
            address=row["address"],
            investor=row["investor"],
            developer=row["developer"],
            total_land_area_m2=_f(row["total_land_area_m2"]),
            floor_area_m2=_f(row["floor_area_m2"]),
            build_density_pct=_f(row["build_density_pct"]),
            product_scale=row["product_scale"],
            amenities=row["amenities"],
            ownership_form=row["ownership_form"],
            handover_standard=row["handover_standard"],
            total_investment_vnd=_i(row["total_investment_vnd"]),
            sale_phase=row["sale_phase"],
            overview=row["overview"],
            link_360=row["link_360"],
        )

    async def discover_projects(self, query: base.DiscoverQuery) -> base.ProjectDiscovery | None:
        args: list = [_SENTINEL]
        where = ["p.status='published'", "p.project_code <> $1"]
        rank_expr = _region_rank_expr(_region_tokens(query.region), args)
        if query.investor:
            args.append(f"%{query.investor}%")
            where.append(f"p.investor ILIKE ${len(args)}")
        if query.sale_phase:
            args.append(query.sale_phase)
            where.append(f"p.sale_phase = ${len(args)}")
        if query.product_type:
            args.append(query.product_type)
            where.append(f"${len(args)} = ANY(p.category)")
        if query.budget_max_vnd > 0:
            args.append(query.budget_max_vnd)
            where.append(f"pf.pf <= ${len(args)}")
        args.append(current_tenant())
        tid_ph = f"${len(args)}"
        where.append(f"p.tenant_id = {tid_ph}")

        phase_array = "ARRAY[" + ",".join(f"'{p}'" for p in _SALE_PHASE_ORDER) + "]"
        # Ngoài CTE các cột đã mất tiền tố `p.` (SELECT * FROM c).
        order_col = "sale_phase" if rank_expr else "p.sale_phase"
        name_col = "name" if rank_expr else "p.name"
        order_by = f" ORDER BY array_position({phase_array}, {order_col}) NULLS LAST, {name_col}"
        sql = (
            "SELECT p.project_code, p.name, p.region, p.category, p.investor, p.sale_phase, "
            "p.amenities, pf.pf"
            f"{', ' + rank_expr + ' AS _m' if rank_expr else ''} "
            "FROM tenant_data.projects p "
            "LEFT JOIN (SELECT project_code, min(price_vnd) FILTER (WHERE price_vnd > 0) AS pf "
            "FROM tenant_data.units "
            f"WHERE status='published' AND tenant_id = {tid_ph} GROUP BY project_code) pf "
            "ON pf.project_code = p.project_code "
            f"WHERE {' AND '.join(where)}"
        )
        # ORDER BY ra ngoài CTE — sắp xếp trước khi lọc theo bậc là vô nghĩa.
        sql = _region_scoped(sql, order_by) if rank_expr else sql + order_by
        async with self._acquire() as conn:
            rows = await conn.fetch(sql, *args)
        total = len(rows)
        page = rows[query.offset : query.offset + query.limit]
        projects = [_row_to_summary(r, price_from=_i(r["pf"]), amenities=r["amenities"]) for r in page]
        return base.ProjectDiscovery(total=total, projects=projects)

    # ---- units / documents ----
    async def search_units(self, query: base.UnitQuery) -> list[base.Unit] | None:
        # project_code rỗng = tìm trên TẤT CẢ dự án (đúng lời hứa trong RULES).
        # Trước đây hardcode u.project_code=$1 nên ''= không khớp gì →
        # ESCALATE_SIGNAL oan. Hợp nhất recommend_units (2026-09-07): thêm
        # bedrooms + region rank, trả RAW candidates cap 200 — tool sort
        # (phong thủy / giá) TRƯỚC khi cắt trang.
        args: list = []
        where = ["p.status='published'", "u.status='published'"]
        if query.project_code:
            args.append(query.project_code)
            where.append(f"u.project_code = ${len(args)}")
        # Khớp khu vực y như discover_projects — lệch nhau thì cùng một lời khách
        # ra dự án ở discover nhưng rỗng ở đây rồi escalate oan.
        rank_expr = _region_rank_expr(_region_tokens(query.region), args)
        if query.product_type:
            args.append(query.product_type)
            where.append(f"u.product_type = ${len(args)}")
        if query.max_price_vnd > 0:
            args.append(query.max_price_vnd)
            # price_vnd = 0/NULL nghĩa là CHƯA CÓ GIÁ — không thể khẳng định căn
            # đó nằm trong ngân sách, loại khỏi kết quả khi khách lọc theo giá.
            where.append(f"u.price_vnd > 0 AND u.price_vnd <= ${len(args)}")
        if query.direction:
            args.append(query.direction)
            where.append(f"u.direction = ${len(args)}")
        if query.floor > 0:
            args.append(query.floor)
            where.append(f"u.floor = ${len(args)}")
        if query.block:
            args.append(query.block)
            where.append(f"u.block = ${len(args)}")
        if query.unit_code:
            args.append(query.unit_code)
            where.append(f"u.unit_code = ${len(args)}")
        if query.bedrooms > 0:
            args.append(query.bedrooms)
            where.append(f"u.bedrooms = ${len(args)}")
        args.append(query.sale_status or "available")
        where.append(f"u.sale_status = ${len(args)}")
        if query.min_area_built_m2 > 0:
            args.append(query.min_area_built_m2)
            where.append(f"u.area_built_m2 >= ${len(args)}")
        if query.max_area_built_m2 > 0:
            args.append(query.max_area_built_m2)
            where.append(f"u.area_built_m2 <= ${len(args)}")
        args.append(current_tenant())
        where.append(f"u.tenant_id = ${len(args)}")

        sql = (
            f"SELECT u.*, p.name project_name, p.amenities amenities"
            f"{', ' + rank_expr + ' AS _m' if rank_expr else ''} "
            "FROM tenant_data.units u "
            "JOIN tenant_data.projects p USING (tenant_id, project_code) "
            f"WHERE {' AND '.join(where)}"
        )
        # LIMIT ra ngoài CTE: cắt 200 dòng TRƯỚC khi chấm bậc là vứt mất căn đúng.
        sql = _region_scoped(sql, " LIMIT 200") if rank_expr else sql + " LIMIT 200"
        async with self._acquire() as conn:
            rows = await conn.fetch(sql, *args)
        if not rows:
            return None
        return [_row_to_unit(r) for r in rows]

    async def get_document(self, project_code: str, query: str = "") -> list[base.Document] | None:
        # JOIN projects p.status='published' — cùng luật parent với search_units:
        # dự án đã archived (op:delete từ cổng nạp Portal) thì tài liệu của nó
        # phải ẩn theo. Doc neo sentinel __ALL__ vẫn trả: row hệ thống luôn
        # published (quy ước Portal).
        args: list = [[project_code, _SENTINEL]]
        sql = (
            "SELECT d.project_code, d.title, d.body, d.file_url FROM tenant_data.documents d "
            "JOIN tenant_data.projects p USING (tenant_id, project_code) "
            "WHERE p.status='published' AND d.status='published' AND d.project_code = ANY($1)"
        )
        if query:
            args.append(f"%{query}%")
            sql += f" AND (d.title ILIKE ${len(args)} OR d.body ILIKE ${len(args)})"
        args.append(current_tenant())
        sql += f" AND d.tenant_id = ${len(args)}"
        async with self._acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [
            base.Document(project_code=r["project_code"], title=r["title"], body=r["body"], file_url=r["file_url"])
            for r in rows
        ]


def _get(row, key):
    """Cột tuỳ-truy-vấn: dict (test fake) và asyncpg Record đều raise KeyError
    khi cột không được SELECT — trả None thay vì bắt caller nhớ shape."""
    try:
        return row[key]
    except KeyError:
        return None


def _row_to_unit(row) -> base.Unit:
    return base.Unit(
        project_code=row["project_code"],
        project_name=row["project_name"] or "",
        zone_code=row["zone_code"],
        unit_code=row["unit_code"],
        product_type=row["product_type"],
        bedrooms=row["bedrooms"],
        block=row["block"],
        floor=row["floor"],
        num_floors=row["num_floors"],
        direction=row["direction"],
        area_built_m2=_f(row["area_built_m2"]),
        area_wall_m2=_f(row["area_wall_m2"]),
        area_land_m2=_f(row["area_land_m2"]),
        price_vnd=_i(row["price_vnd"]),
        price_per_m2_vnd=_i(row["price_per_m2_vnd"]),
        sale_status=row["sale_status"],
        image_url=row["image_url"],
        amenities=_get(row, "amenities"),
    )


def _row_to_summary(row, *, price_from: int | None, amenities: str | None = None) -> base.ProjectSummary:
    category = row["category"] or []
    return base.ProjectSummary(
        code=row["project_code"],
        name=row["name"] or "",
        region=row["region"] or "",
        category=tuple(category),
        investor=row["investor"] or "",
        price_from_vnd=price_from,
        sale_phase=row["sale_phase"] or "",
        amenities=amenities,
    )
