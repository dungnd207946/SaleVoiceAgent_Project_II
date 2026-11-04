"""Project info tools sau merge 2026-09-07: discover_projects + search_units.

``discover_projects`` hai mode: KHÔNG ``project_code`` → trang khám phá dự án;
CÓ ``project_code`` → overview đầy đủ một dự án (nuốt get_project_overview cũ).
``search_units`` là tool căn DUY NHẤT (nuốt recommend_units): ``scope`` bắt buộc
phân đôi nghĩa của project_code rỗng — 'in_project' (adapter điền từ hồ sơ, vẫn
rỗng → needs_info) vs 'all_projects' (xuyên dự án, bỏ qua hồ sơ). Envelope hội
tụ về dạng NHÓM: ``units`` (đúng ngân sách) + ``upsell_units`` (vượt-trong-biên,
directive pitch mức nhóm) + ``counts``/paging. Provider trả ``None`` (backend
chết / SQL 0 row) → :data:`~noble_agent.data.providers.base.ESCALATE_SIGNAL`.
``code`` là raw ``ma_du_an`` (verbatim case) khớp Qdrant ``project_id``.
"""

from __future__ import annotations

import json
from dataclasses import replace

from noble_agent.agent import feng_shui
from noble_agent.agent.tools import recent_projects, upsell
from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers import _serialize as ser
from noble_agent.data.providers.base import ESCALATE_SIGNAL, DiscoverQuery, UnitQuery

# Priority order for narrowing hints (most useful first); capped to 2.
_NARROW_AXES = ("budget_max", "product_type", "region", "purpose", "investor")

# Khách đưa ngân sách X → filter giá nới thành X + upsell.headroom(X) (sàn
# 500tr, 12% với ngân sách lớn); căn/dự án nằm trong khoảng nới vẫn trả về,
# tách nhóm upsell_units kèm over_budget/price_delta_pct/highlights + directive
# pitch mức nhóm — sống ở MỌI lần gọi (2026-09-04: khách "có căn khác không" →
# gọi lại tool, guard một-lần làm lời chèo kéo biến mất đúng lúc cần); riêng
# discover_projects giữ guard một-lần-mỗi-dự-án.
_NO_PRICE_INSTRUCTION = (
    "Căn này chưa có giá niêm yết — nói giá đang cập nhật, TUYỆT ĐỐI không tự bịa giá, rồi "
    "CHỦ ĐỘNG dẫn khách sang căn có giá gần nhất trong danh sách."
)
# "tầm/khoảng X m²" → dải ±20% quanh X dựng Ở ĐÂY (LLM chỉ truyền X qua
# `area_m2`), không để model dịch "tầm 120" thành min_area=120 (lọc cứng ≥120
# bỏ hết căn 100–119). Dải rỗng thì vẫn trả vài căn gần X nhất kèm nhãn lệch —
# sale không nói "không có" khi kho còn hàng khác tầm.
_AREA_BAND_RATIO = 0.2
_MAX_OFF_AREA_UNITS = 6
# search_units trả theo TRANG (envelope index/has_more/next_index, kiểu
# discover_projects): cùng tham số mà khách chê thì lượt sau gọi index=next_index
# ra các căn KẾ TIẾP thay vì nhận lại y hệt 6 căn cũ.
_UNITS_PAGE = 6
_OFF_AREA_UNIT_INSTRUCTION = (
    "Không có căn nào đúng tầm diện tích khách hỏi; căn này là căn gần nhất. Nói rõ diện tích thật "
    "và mức chênh, hỏi khách có muốn xem không."
)
# Lời chốt cho scope in_project — thiếu nó model tự nghĩ ra bước tiếp và chào
# mời thứ dữ liệu không có ("muốn xem thêm hình ảnh hoặc mặt bằng không ạ?" —
# case PK-05 2026-09-04): dữ liệu căn KHÔNG kèm ảnh/mặt bằng, đừng hứa.
_UNITS_NEXT_STEP_INSTRUCTION = (
    "Trả lời bằng đúng dữ liệu căn ở trên. Chốt bằng MỘT bước tiến: mời khách đặt lịch tham quan "
    "thực tế căn ưng nhất, hoặc gợi ý tìm căn/tiêu chí khác nếu khách chưa ưng. KHÔNG chào mời gửi "
    "hình ảnh hay mặt bằng — dữ liệu căn không kèm ảnh; KHÔNG hỏi xin phép kiểu 'có muốn nghe thêm không'."
)
# Lời chốt cho scope all_projects (văn recommend cũ, đã eval-tune riêng).
_ALL_PROJECTS_INSTRUCTION = (
    "Giới thiệu 3-4 căn nổi bật trong `units` (đúng ngân sách khách): dự án + hướng + giá, "
    "CHỦ ĐỘNG chọn căn hợp nhất và nói ngắn vì sao, chốt bằng một bước tiến (mời xem kỹ căn "
    "đó hoặc đặt lịch tham quan). KHÔNG hỏi xin phép trước khi giới thiệu."
)
# Lời chốt cho mode overview — thiếu nó model tự nghĩ bước tiếp và hỏi xin phép
# ("Anh có muốn em gửi thêm hình ảnh... không ạ?" — quan sát live 2026-09-09).
# Phần send_media chỉ chèn khi tenant có tool đó (gate runtime, cùng tinh thần
# span [TOOL:x] ở schema description).
_OVERVIEW_SEND_MEDIA_INSTRUCTION = (
    "GỌI NGAY send_media với project_code trên và category='tong_quan' để gửi ảnh tổng quan — âm thầm, "
    "không thông báo; nếu đã gửi ảnh tổng quan dự án này trước đó thì bỏ qua. "
)
_OVERVIEW_INSTRUCTION = (
    "Giới thiệu dự án bằng đúng dữ liệu trên. Chốt tin bằng MỘT câu khai thác tiêu chí và tầm ngân sách "
    "(vd 'anh/chị có thể cho em xin những tiêu chí, tầm ngân sách để em tư vấn căn trong dự án này cho "
    "anh/chị ạ'). KHÔNG hỏi xin phép kiểu 'có muốn em gửi hình ảnh / thông tin không'."
)


def _to_m2(value) -> float:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def _area_bounds(args: dict) -> tuple[float, float, float]:
    """(min, max, target). ``area_m2`` = "tầm X" → dải ±_AREA_BAND_RATIO; ``min_area``
    / ``max_area`` khách nói rõ ("từ X" / "dưới X") thắng cạnh dải tương ứng."""
    target = _to_m2(args.get("area_m2"))
    lo = _to_m2(args.get("min_area"))
    hi = _to_m2(args.get("max_area"))
    if target:
        lo = lo or round(target * (1 - _AREA_BAND_RATIO), 2)
        hi = hi or round(target * (1 + _AREA_BAND_RATIO), 2)
    return lo, hi, target


def _over_budget_fields(uj: dict, u, budget_vnd: int) -> None:
    """Dữ liệu vượt-ngân-sách tường minh cho MỘT căn trong khoảng nới —
    over_budget/delta/highlights, KHÔNG kèm lời pitch (pitch ở mức nhóm)."""
    uj["over_budget"] = True
    uj["price_delta_pct"] = upsell.delta_pct(u.price_vnd, budget_vnd)
    hl = upsell.highlights(u.amenities)
    if hl:
        uj["highlights"] = hl


def _to_vnd(value) -> int:
    """Chuẩn hoá giá LLM truyền về VNĐ thực. Schema khai VNĐ nhưng model thỉnh
    thoảng vẫn truyền số tắt theo lời khách ("20 tỷ" → 20, "700 triệu" → 700).
    Chia dải theo mức hợp lý của ngân sách BĐS bán lẻ: < 1000 là tỷ (0.5–999 tỷ),
    1000–99 999 là triệu (5000 → 5 tỷ), còn lại VNĐ thực."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    if v < 1000:
        v *= 1e9
    elif v < 100_000:
        v *= 1e6
    return int(v)


async def discover_projects(args: dict, *, state=None) -> str:
    settings = get_settings()
    provider = providers.get_provider(settings)

    # Mode overview (nuốt get_project_overview 2026-09-07): có mã → chi tiết MỘT
    # dự án, bỏ qua mọi filter khám phá. Model lấy mã từ find_project / hồ sơ.
    code = args.get("project_code", "") or ""
    if code:
        result = await provider.get_overview(code)
        if result is None:
            return ESCALATE_SIGNAL
        from noble_agent.tenant.loader import get_tenant_context

        try:
            _tools = get_tenant_context().enabled_tools
        except Exception:
            _tools = ("send_media",)
        media_part = _OVERVIEW_SEND_MEDIA_INSTRUCTION if "send_media" in _tools else ""
        payload = ser.overview_json(result)
        payload["instruction"] = media_part + _OVERVIEW_INSTRUCTION
        return json.dumps(payload, ensure_ascii=False)

    limit = settings.discover_page_size
    index = int(args.get("index") or 0)
    budget_vnd = _to_vnd(args.get("budget_max"))
    result = await provider.discover_projects(
        DiscoverQuery(
            region=args.get("region", "") or "",
            budget_max_vnd=budget_vnd + upsell.headroom(budget_vnd) if budget_vnd else 0,
            product_type=args.get("product_type", "") or "",
            purpose=args.get("purpose", "") or "",
            investor=args.get("investor", "") or "",
            # HOTFIX: bỏ lọc sale_phase — luôn tìm tất cả giai đoạn, mặc kệ LLM truyền gì.
            sale_phase="",
            offset=index,
            limit=limit,
        )
    )
    if result is None:
        return ESCALATE_SIGNAL

    count = len(result.projects)
    has_more = index + count < result.total
    given = {a for a in _NARROW_AXES if (args.get(a) or 0) not in ("", 0, None)}
    suggested = [a for a in _NARROW_AXES if a not in given][:2]

    if result.total == 0:
        instruction = "Không có dự án khớp tiêu chí. Hãy gợi ý khách đổi khu vực hoặc nới tiêu chí, đừng bịa."
    elif count == 0:
        instruction = "Đã hết dự án để hiển thị. Hãy hỏi khách thêm tiêu chí hoặc chốt một dự án đã giới thiệu."
    else:
        # Kịch bản sale (chỉnh vòng 2, 2026-09-04): tổng số → 4-5 dự án nổi bật
        # → MỘT lời chốt duy nhất. Còn thiếu tiêu chí thì lời chốt là câu khai
        # thác; đủ cả rồi mới chèo kéo sang quỹ căn — hai lời chốt trong cùng
        # một tin (vừa hỏi tiêu chí vừa mời xem căn) nghe máy móc, đo thật /chat.
        missing = [
            label
            for arg, label in (
                # ("region", "khu vực khách muốn mua"),
                ("budget_max", "tầm ngân sách"),
                # ("purpose", "mục đích mua để ở hay đầu tư"),
            )
            if not args.get(arg)
        ]
        instruction = (
            f"Nói bên em đang có tổng cộng {result.total} dự án, rồi giới thiệu 4-5 dự án nổi bật "
            "trong danh sách (ít hơn thì giới thiệu hết), mỗi dự án một câu vì sao đáng chú ý. "
        )
        if missing:
            instruction += (
                "Chốt tin bằng đúng MỘT câu khai thác " + "; ".join(missing) + " kèm ý "
                "'cho em xin thêm thông tin để tư vấn sát nhất' — sau câu hỏi này KHÔNG mời chào gì "
                "thêm. Không hỏi xin phép kiểu 'có muốn em gửi thông tin không / có muốn nghe không'."
            )
        else:
            instruction += (
                "Đủ tiêu chí rồi — chốt tin bằng lời mời tìm hiểu các căn đang bán trong dự án nổi "
                "bật nhất, nhấn mạnh rằng 'đang có nhiều căn rất hấp dẫn trong dự án đấy ạ'. KHÔNG hỏi xin phép kiểu "
                "'có muốn em gửi thông tin không / có muốn nghe không'."
            )

    projects_json: list[dict] = []
    for s in result.projects:
        pj = ser.discover_project_json(s)
        if budget_vnd and s.price_from_vnd is not None and s.price_from_vnd > budget_vnd:
            pj["over_budget"] = True
            pj["price_delta_pct"] = upsell.delta_pct(s.price_from_vnd, budget_vnd)
            hl = upsell.highlights(s.amenities)
            if hl:
                pj["highlights"] = hl
            if not upsell.already_pitched(state, s.code):
                pj["instruction"] = upsell.project_pitch(pj["price_delta_pct"])
                upsell.remember_pitched(state, s.code)
        projects_json.append(pj)
    if state is not None:
        recent_projects.remember(state, [pj["code"] for pj in projects_json])

    payload: dict = {
        "total": result.total,
        "index": index,
        "count": count,
        "projects": projects_json,
        "has_more": has_more,
        "suggested_narrow": suggested,
        "instruction": instruction,
    }
    if has_more:
        payload["next_index"] = index + count
    return json.dumps(payload, ensure_ascii=False)


_FS_GUARD_KEY = "fengshui_guard_attempts"
_FS_GUARD_MAX = 2


def _fs_block(fs: feng_shui.FengShuiResult) -> dict:
    return {
        "applied": True,
        "method": fs.method,
        "menh": fs.menh,
        "cung_phi": fs.cung_phi,
        "group": fs.group,
        "good_directions": sorted(fs.good_directions),
        "note": fs.note,
    }


async def search_units(args: dict, *, state=None, customer=None) -> str:
    """Tool căn DUY NHẤT (nuốt recommend_units 2026-09-07): union filter cứng
    (loại căn / giá / hướng / tầng / block / mã căn / diện tích / phòng ngủ /
    khu vực) + phong thủy soft-rank ở CẢ hai scope + nhóm upsell + trang 6 căn.
    """
    from noble_agent.tenant.loader import get_tenant_context

    # scope phân đôi nghĩa của project_code rỗng (trước merge: search = "dùng dự
    # án đang quan tâm", recommend = "xuyên tất cả dự án"). Model quên scope
    # (schema required nhưng provider không ép được) → suy theo nghĩa cũ.
    scope = args.get("scope") or ("in_project" if args.get("project_code") else "all_projects")
    project_code = args.get("project_code", "") or ""
    if scope == "in_project" and not project_code:
        # Adapter đã thử điền từ hồ sơ mà vẫn rỗng — chưa biết dự án nào; đừng
        # xổ xuyên dự án oan, cũng đừng escalate.
        return json.dumps(
            {
                "ok": False,
                "needs_info": True,
                "message": (
                    "Chưa xác định được dự án. Gọi find_project với tên dự án khách nói; "
                    "khách muốn tư vấn chung không theo dự án → gọi lại với scope='all_projects'."
                ),
            },
            ensure_ascii=False,
        )

    try:
        _rankers = get_tenant_context().rankers
    except Exception:
        _rankers = frozenset({"feng_shui"})
    feng_shui_on = "feng_shui" in _rankers

    birth_year = args.get("birth_year") if feng_shui_on else None
    gender = (args.get("gender") or getattr(customer, "gender", None)) if feng_shui_on else None
    menh, zodiac = (args.get("menh"), args.get("zodiac")) if feng_shui_on else (None, None)

    # Con-giáp guard: only a zodiac (no year, no menh) → prefer a real birth
    # year before the weaker địa-chi estimate. Ask at most twice (mirrors the
    # booking guard); the 3rd call falls through to compute() using the zodiac.
    if zodiac and not birth_year and not menh and state is not None:
        attempts = int(state.scratchpad.get(_FS_GUARD_KEY, 0))
        if attempts < _FS_GUARD_MAX:
            state.scratchpad[_FS_GUARD_KEY] = attempts + 1
            return json.dumps(
                {
                    "ok": False,
                    "needs_info": True,
                    "message": (
                        "Khách mới cho con giáp, chưa có năm sinh. Hãy hỏi năm sinh dương lịch để "
                        "tư vấn hướng hợp mệnh chính xác (vd 'anh tuổi Tị là sinh năm nào ạ?'). "
                        "Nếu khách không nhớ, cứ tư vấn theo tiêu chí khác."
                    ),
                },
                ensure_ascii=False,
            )

    fs = None
    if birth_year or menh or zodiac:
        fs = feng_shui.compute(birth_year=birth_year, gender=gender, menh=menh, zodiac=zodiac)
        if (birth_year or menh) and state is not None:
            state.scratchpad[_FS_GUARD_KEY] = 0  # real data arrived → reset the ask counter
    good = fs.good_directions if (fs and fs.applied) else frozenset()

    provider = providers.get_provider(get_settings())
    try:
        floor = int(args.get("floor") or 0)
    except (TypeError, ValueError):
        floor = 0
    try:
        bedrooms = int(args.get("bedrooms") or 0)
    except (TypeError, ValueError):
        bedrooms = 0
    # `budget_max` là tên cũ của recommend_units — config/eval cũ còn chở nó.
    budget_vnd = _to_vnd(args.get("max_price") or args.get("budget_max"))
    area_lo, area_hi, area_target = _area_bounds(args)
    # Dự án đã chốt thì khu vực do dự án quyết định — giữ region chỉ tạo cơ hội
    # 0-row oan (dự án ghi region khác lời khách vừa nói).
    region = (args.get("region", "") or "") if scope == "all_projects" else ""
    query = UnitQuery(
        project_code=project_code,
        product_type=args.get("product_type", "") or "",
        max_price_vnd=budget_vnd + upsell.headroom(budget_vnd) if budget_vnd else 0,
        direction=args.get("direction", "") or "",
        floor=floor,
        block=args.get("block") or args.get("tower", "") or "",
        unit_code=args.get("unit_code", "") or "",
        sale_status=args.get("sale_status", "available") or "available",
        min_area_built_m2=area_lo,
        max_area_built_m2=area_hi,
        bedrooms=bedrooms,
        region=region,
    )
    result = await provider.search_units(query)
    off_target = False
    if not result and area_target:
        # Dải quanh X rỗng → bỏ chặn diện tích, giữ mọi tiêu chí khác, lấy vài
        # căn gần X nhất. CHỈ cho "tầm X"; "từ X trở lên" rỗng là rỗng thật.
        result = await provider.search_units(replace(query, min_area_built_m2=0.0, max_area_built_m2=0.0))
        off_target = bool(result)
    if result and budget_vnd:
        # Căn chưa có giá (0/None) không thể khẳng định nằm trong ngân sách —
        # loại khi khách lọc theo giá (provider pg_kb cũng đã loại ở SQL; giữ
        # thêm ở đây cho provider/test fake).
        result = [u for u in result if (u.price_vnd or 0) > 0]
    if not result:
        return ESCALATE_SIGNAL

    # Provider trả RAW (unsorted, cap 200). Sort TRƯỚC khi cắt trang. Tiebreak
    # unit_code: SQL không có ORDER BY nên thứ tự row giữa hai lần gọi không
    # đảm bảo — thiếu tiebreak thì trang 2 có thể trùng/sót căn trang 1.
    def _fs_mismatch(u) -> bool:
        return not feng_shui.direction_matches(u.direction or "", good) if good else False

    def _area_dist(u) -> float:
        return abs((u.area_built_m2 or 0.0) - area_target) if area_target else 0.0

    within = [u for u in result if not (budget_vnd and (u.price_vnd or 0) > budget_vnd)]
    over = [u for u in result if budget_vnd and (u.price_vnd or 0) > budget_vnd]
    # Trong ngân sách: phong thủy trước → chưa-có-giá xếp cuối → gần tầm diện
    # tích khách hỏi → giá GIẢM dần.
    within.sort(
        key=lambda u: (_fs_mismatch(u), (u.price_vnd or 0) <= 0, _area_dist(u), -(u.price_vnd or 0), u.unit_code or "")
    )
    # Vượt-trong-biên: phong thủy trước → giá TĂNG dần — căn SÁT ngân sách nhất
    # (delta nhỏ nhất, dễ lý giải nhất) là ứng viên chèo kéo số một.
    over.sort(key=lambda u: (_fs_mismatch(u), _area_dist(u), u.price_vnd or 0, u.unit_code or ""))
    if off_target:
        within = within[:_MAX_OFF_AREA_UNITS]
        over = over[: max(0, _MAX_OFF_AREA_UNITS - len(within))]
    total = len(within) + len(over)

    # Mỗi trang 6 slot, phân bổ within/upsell theo ĐỘ LIÊN QUAN GIÁ, không phải
    # "within lấp đầy trước" (sort-trước-slice cũ cắt rơi MỌI căn upsell khi kho
    # dày ≥6 — bug VINHOMES_GLOBAL_GATE 2026-09-03). Căn "đúng tầm" = giá ≥
    # NEAR_BUDGET_RATIO ngân sách; within toàn căn xa tầm (khách hỏi 10 tỷ mà
    # chỉ có căn 4-5 tỷ) thì chỉ giữ 2 căn sát giá nhất, KHÔNG pad khi upsell
    # mỏng (thà trả 4 căn liên quan còn hơn 6 căn có 4 căn lạc đề).
    def _alloc(w: list, o: list) -> tuple[int, int]:
        if not o:
            return min(len(w), _UNITS_PAGE), 0
        near_n = sum(1 for u in w if (u.price_vnd or 0) >= budget_vnd * upsell.NEAR_BUDGET_RATIO)
        cap = max(2, min(near_n, _UNITS_PAGE - 1))
        n_o = min(len(o), _UNITS_PAGE - cap)
        return min(len(w), cap, _UNITS_PAGE - n_o), n_o

    # Paging kiểu discover_projects (index/has_more/next_index): khách chê 6 căn
    # đầu → lượt sau gọi index=next_index ra các căn KẾ TIẾP, không nhận lại y
    # hệt. Nhảy tới index bằng cách tiêu từng trang (mỗi trang ≥1 căn khi còn
    # hàng nên luôn tiến); index lệch mốc trang thì làm tròn về trang kế.
    index = max(0, int(args.get("index") or 0))
    start = 0
    while start < index and (within or over):
        n_w, n_o = _alloc(within, over)
        within, over = within[n_w:], over[n_o:]
        start += n_w + n_o
    n_within, n_over = _alloc(within, over)

    def _unit_json(u) -> dict:
        uj = ser.unit_json(u)
        if good:
            fs_match = feng_shui.direction_matches(u.direction or "", good)
            uj["feng_shui_match"] = fs_match
            uj["direction_label"] = "hợp hướng" if fs_match else ""
        if off_target:
            uj["instruction"] = _OFF_AREA_UNIT_INSTRUCTION
        if (u.price_vnd or 0) <= 0:
            uj["price_vnd"] = None
            uj["price_per_m2_vnd"] = None
            uj["instruction"] = _NO_PRICE_INSTRUCTION
        return uj

    units: list[dict] = [_unit_json(u) for u in within[:n_within]]
    upsell_units: list[dict] = []
    for u in over[:n_over]:
        uj = _unit_json(u)
        _over_budget_fields(uj, u, budget_vnd)
        upsell_units.append(uj)
    all_shown = units + upsell_units
    if state is not None:
        recent_projects.remember(state, [u["project_code"] for u in all_shown])

    shown_n = len(all_shown)
    has_more = start + shown_n < total
    fs_match_n = sum(1 for u in all_shown if u.get("feng_shui_match"))
    payload: dict = {
        "units": units,
        "counts": {"total": total, "shown": shown_n, "feng_shui_match": fs_match_n},
        "index": start,
        "has_more": has_more,
        "criteria": {
            "scope": scope,
            "project_code": project_code or None,
            "budget_max_vnd": budget_vnd or None,
            "region": args.get("region", ""),
            "bedrooms": args.get("bedrooms"),
            "purpose": args.get("purpose", ""),
        },
        "instruction": _UNITS_NEXT_STEP_INSTRUCTION if scope == "in_project" else _ALL_PROJECTS_INSTRUCTION,
    }
    if has_more:
        payload["next_index"] = start + shown_n
    if upsell_units:
        payload["upsell_units"] = upsell_units
        # Directive chèo kéo mức NHÓM (số liệu của căn dẫn đầu — sát ngân sách
        # nhất), gắn ở MỌI lần gọi có upsell_units: khách "có căn khác không"
        # → gọi lại / lật trang là lúc cần pitch nhất.
        top = upsell_units[0]
        payload["upsell_instruction"] = upsell.group_pitch(top["price_delta_pct"], top["price_vnd"], top["unit_code"])
    if fs and fs.applied:
        payload["feng_shui"] = _fs_block(fs)
    if not all_shown:
        # Lật quá trang cuối: hết hàng để xem thêm ≠ không có hàng — nói thật,
        # đừng escalate và đừng lặp lại các căn đã chê.
        relax = (
            "(giá / diện tích / hướng / tầng)"
            if scope == "in_project"
            else "(nới ngân sách / đổi khu vực / đổi số phòng ngủ)"
        )
        payload["instruction"] = (
            f"Đã giới thiệu hết {total} căn khớp tiêu chí — nói thật với khách, rồi gợi ý nới tiêu chí "
            f"{relax}, hoặc mời đặt lịch tham quan căn khách ưng nhất trong các căn đã xem. Đừng bịa thêm căn."
        )
    elif not units:
        payload["instruction"] = (
            "Không có căn nào trong đúng ngân sách — nói thẳng điều này với khách, rồi CHỦ ĐỘNG "
            "giới thiệu các căn vượt nhẹ trong `upsell_units` kèm mức chênh. KHÔNG hỏi xin phép."
        )
    elif fs and fs.applied and fs_match_n == 0:
        payload["note"] = (
            "Không có căn nào hợp hướng mệnh của khách. Hãy nói rõ điều này, gợi ý vài căn hợp "
            "ngân sách để tham khảo, và mời khách chuyển chuyên viên tư vấn chuyên sâu nếu muốn."
        )
    if has_more and all_shown:
        payload["instruction"] += (
            f" Còn {total - start - shown_n} căn khác khớp tiêu chí chưa giới thiệu — khách chê hoặc muốn "
            f"xem CĂN KHÁC thì gọi lại search_units với index={start + shown_n} (đừng lặp căn cũ)."
        )
    if off_target:
        payload["note"] = "no_units_in_area_band"
        payload["area_band"] = {"target_m2": area_target, "min_m2": area_lo, "max_m2": area_hi}
    return json.dumps(payload, ensure_ascii=False)
