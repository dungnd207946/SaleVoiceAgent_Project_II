"""Tầng HTTP. Bài quan trọng nhất là test_khong_co_action_thi_403 — endpoint quên
require() vẫn chạy và không lỗi nào phát ra, chỉ là ai cũng xem được hoá đơn.

⚠️ `billing/contracts.py` KHÔNG dùng `alias_generator` camelCase (khác khuôn
`ops/contracts.py`) — field Python đã là tên JSON thật (`so_phien`, `chi_phi_tong`,
`canh_bao`, `ghi_chu_turn`, …). Assertion ở đây dùng đúng những tên đó, đo được
bằng `TongQuanOut(...).model_dump_json()`.
"""

from datetime import timedelta
from decimal import Decimal

import asyncpg
import httpx

from tests.modules.billing.conftest import KEY_LABEL, MAT_KHAU, MOC, SESSION, TENANT

BASE = "/api/v1/billing"


async def _dang_nhap(client: httpx.AsyncClient) -> None:
    """Đăng nhập RỒI chuyển sang đúng `TENANT` ("bilw").

    `workspace_billing` dựng membership ở CẢ HAI tenant (`TENANT`/`TENANT_KHAC`)
    cho cùng user — `dang_nhap()` chọn `ws[0]` sắp theo TÊN ("Billing Khac" <
    "Billing WS" theo alphabet), tức mặc định rơi vào `TENANT_KHAC`. Không đổi
    workspace tường minh thì mọi truy vấn chạy trên tenant SAI — `so_phien`/
    tổng chi phí ra 0 và `sessions/{id}` báo 404, không phải lỗi router.
    """
    r = await client.post("/api/v1/auth/login", json={"email": "bil@noblex.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r2 = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r2.status_code == 200, r2.text


async def _da_dinh_gia(pool: asyncpg.Pool) -> None:
    """Chạy `billing.rate_usage()` thật — cùng khuôn `test_repo.py::_da_dinh_gia`.

    `bang_gia_vi_du` chỉ dựng BẢNG GIÁ; nó không tự chạy định giá. Không gọi hàm
    này thì `billing.rated_usage` rỗng, và `canh_bao.thieu_gia` (đọc view
    `billing.price_coverage_gap`, đối chiếu `usage_events` với `rated_usage`)
    báo THIẾU GIÁ cho mọi event dù bảng giá đã đủ — vì chưa ai định giá, không
    phải vì giá thiếu.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )


async def test_summary(app_client, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/summary", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["so_phien"] == 1
    assert d["currency"] == "VND"
    assert "canh_bao" in d
    assert d["canh_bao"]["thieu_gia"] == 0


async def test_by_key_giu_nhom_chua_phan_loai(app_client, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/by-key", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    tong_dong = sum(float(x["chi_phi"]) for x in d["items"])
    assert abs(tong_dong - float(d["chi_phi_tong"])) < 0.01, (
        "tổng các dòng lệch tổng hoá đơn — nhóm chưa phân loại bị ẩn?"
    )


async def test_by_owner_tra_bay_cot_component(app_client, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """`DongOwnerOut` (2026-08-27) phải THẬT SỰ mang bảy trường `chi_phi_
    <component>` qua tầng HTTP — router dựng model bằng liệt kê từng field
    (không unpack dict), nên thêm field vào contract không tự động nối dây ở
    đây; quên nối là `ValidationError` lúc serialize (endpoint 500), không
    phải trường rỗng lặng lẽ. Đối chiếu tổng bảy cột == `chi_phi` của hàng,
    cùng công thức đã neo ở `test_theo_owner_tach_tien_theo_component`.
    """
    await _da_dinh_gia(api_pool)
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/by-owner", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    dong = next(x for x in d if x["user_id"] is not None)
    ma_bay_cot = ("llm", "tts", "stt", "embed", "call", "vad", "speaker_verify")
    for ma in ma_bay_cot:
        assert f"chi_phi_{ma}" in dong
    tong_bay_cot = sum(Decimal(dong[f"chi_phi_{ma}"]) for ma in ma_bay_cot)
    assert tong_bay_cot == Decimal(dong["chi_phi"])


async def test_sessions_tra_bay_cot_component(app_client, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """`PhienUsageOut` (2026-08-27) phải THẬT SỰ mang bảy trường `chi_phi_
    <component>` qua tầng HTTP — `_phien_out()` dựng model bằng liệt kê từng
    field (không unpack dict), dùng CHUNG cho `/billing/sessions` VÀ endpoint
    chi tiết phiên; quên nối một trong bảy field là `ValidationError` (500)
    cho CẢ HAI endpoint cùng lúc, không phải trường rỗng lặng lẽ.
    """
    await _da_dinh_gia(api_pool)
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/sessions", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    dong = next(x for x in d["items"] if x["session_id"] == SESSION)
    ma_bay_cot = ("llm", "tts", "stt", "embed", "call", "vad", "speaker_verify")
    for ma in ma_bay_cot:
        assert f"chi_phi_{ma}" in dong
    tong_bay_cot = sum(Decimal(dong[f"chi_phi_{ma}"]) for ma in ma_bay_cot)
    assert tong_bay_cot == Decimal(dong["chi_phi"])


async def test_chi_tiet_phien(app_client, workspace_billing, bang_gia_vi_du) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/sessions/{SESSION}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["events"]) == 13
    assert "xấp xỉ" in d["ghi_chu_turn"]


async def test_chi_tiet_phien_dung_phien_khong_phai_moi_nhat(
    app_client, pool: asyncpg.Pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Correction 1: `chi_tiet_phien` từng lấy `hang[0]` của
    `liet_ke_phien(conn, tu_ngay, den_ngay, 1, 0)` — hàng đó là phiên MỚI NHẤT
    trong khoảng suy từ event đầu/cuối, không phải phiên được hỏi. Seed một
    phiên THỨ HAI của CÙNG tenant, khởi động MUỘN HƠN `SESSION`, rồi mở
    `SESSION` (phiên CŨ hơn) và khẳng định vẫn trả đúng tóm tắt của `SESSION`.

    ⚠️ `moc_moi` PHẢI nằm CÙNG NGÀY LỊCH với `MOC` (vài giờ sau, KHÔNG `+ 1
    ngày`). Code lỗi suy khoảng từ `min`/`max(occurred_at)` của CHÍNH phiên
    được hỏi rồi cắt theo NGÀY TRÒN — hai phiên khác ngày lịch thì khoảng suy
    ra của mỗi phiên tự nhiên KHÔNG chứa phiên kia, nên kể cả câu truy vấn hỏng
    cũng vô tình trả đúng hàng và bài test không bắt được gì (đã đo thật: phiên
    bản `+ timedelta(days=1)` xanh cả với code lỗi phục dựng — xem báo cáo).
    Cùng ngày thì khoảng suy từ `SESSION` phủ luôn `session_moi`, và
    `ORDER BY bat_dau DESC LIMIT 1` của code lỗi chọn nhầm phiên MỚI hơn.
    """
    session_moi = "bil-sess-moi-hon"
    moc_moi = MOC + timedelta(hours=3)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations "
            "(tenant_id, session_id, source, agent_key_id, customer_name, phone, started_at) "
            "VALUES ($1, $2, 'voice', $3, 'Khách Mới Hơn', '0900000000', $4)",
            TENANT,
            session_moi,
            workspace_billing["key_id"],
            moc_moi,
        )
        await conn.execute(
            "INSERT INTO billing.usage_events "
            "(tenant_id, session_id, channel, seq, turn_idx, component, purpose, "
            " provider, model, input_tokens, output_tokens, cache_write_tokens, "
            " cache_read_tokens, audio_sec, wall_ms, units, exact, occurred_at) "
            "VALUES ($1, $2, 'voice', 0, 0, 'llm', 'conversation', 'gemini', "
            " 'gemini-2.5-flash', 100, 10, 0, 0, 0.0, 500.0, 1, true, $3)",
            TENANT,
            session_moi,
            moc_moi,
        )

    try:
        await _dang_nhap(app_client)
        r = await app_client.get(f"{BASE}/sessions/{SESSION}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["phien"]["session_id"] == SESSION
        assert d["phien"]["customer_name"] != "Khách Mới Hơn"
        assert d["phien"]["key_label"] == KEY_LABEL

        r2 = await app_client.get(f"{BASE}/sessions/{session_moi}")
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["phien"]["session_id"] == session_moi
        assert d2["phien"]["customer_name"] == "Khách Mới Hơn"
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM billing.usage_events WHERE session_id = $1", session_moi)
            await conn.execute(
                "DELETE FROM tenant_data.conversations WHERE tenant_id = $1 AND session_id = $2",
                TENANT,
                session_moi,
            )


async def test_phien_khong_ton_tai_404(app_client, workspace_billing) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/sessions/khong-co-that")
    assert r.status_code == 404


async def test_breakdown(app_client, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Mục ② `/usage`: hai chiều gộp, cùng một `chi_phi_tong` với `/by-key`."""
    await _da_dinh_gia(api_pool)
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/breakdown", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()

    # 31 ngày của tháng 8 — NGÀY RỖNG CŨNG CÓ HÀNG. Đây là bất biến chính của
    # `repo.theo_ngay()`: trả thưa thì chart nối thẳng qua chỗ trũng.
    assert len(d["theo_ngay"]) == 31
    co_usage = [x for x in d["theo_ngay"] if x["ngay"] == "2026-08-19"]
    assert co_usage, "thiếu ngày có usage"
    # Tách theo component TRONG TỪNG NGÀY — nguồn của tooltip chart. Tổng `phan`
    # phải bằng `chi_phi` của chính ngày đó (router cộng từ cùng những hàng ấy).
    ngay19 = co_usage[0]
    assert {p["component"] for p in ngay19["phan"]} >= {"llm", "stt"}
    assert sum(Decimal(p["chi_phi"]) for p in ngay19["phan"]) == Decimal(ngay19["chi_phi"])
    # Ngày rỗng: `phan` RỖNG, không phải thiếu khoá.
    ngay_rong = next(x for x in d["theo_ngay"] if x["ngay"] == "2026-08-01")
    assert ngay_rong["phan"] == []
    assert all(Decimal(x["chi_phi"]) == 0 for x in d["theo_ngay"] if x["ngay"] != "2026-08-19"), (
        "ngày không có usage phải là 0, không phải bị bỏ khỏi danh sách"
    )

    # Cột tiền cộng được và PHẢI bằng tổng — cả hai chiều lẫn `chi_phi_tong`
    # đều suy từ cùng một `rated_usage`; lệch là bug, không phải làm tròn.
    tong = Decimal(d["chi_phi_tong"])
    assert sum(Decimal(x["chi_phi"]) for x in d["theo_ngay"]) == tong
    assert sum(Decimal(x["chi_phi"]) for x in d["theo_component"]) == tong
    assert d["currency"] == "VND"

    comp = {x["component"]: x for x in d["theo_component"]}
    assert "llm" in comp and "stt" in comp
    # Số đo lấy từ `usage_events`, KHÔNG nhân bản theo số metric có giá: 7 event
    # llm trong fixture (6 conversation + 1 summary), không phải 7 × số metric.
    assert comp["llm"]["so_event"] == 7
    assert comp["llm"]["input_tokens"] == 113674


async def test_breakdown_giu_component_chua_co_gia(app_client, api_pool, pool, workspace_billing) -> None:
    """Component ĐO ĐƯỢC nhưng KHÔNG có dòng giá vẫn phải hiện với `chi_phi = 0` —
    ẩn nó là giấu đúng phần đang mất doanh thu.

    ⚠️ VIẾT LẠI 2026-08-21. Bản cũ dựng cảnh đó bằng cách bỏ fixture
    `bang_gia_vi_du` («tenant chưa có bảng giá nào»). Cảnh ĐÓ KHÔNG CÒN TỒN TẠI:
    migration `0949` seed một bảng giá `is_default` phủ MỌI tenant, và `0950` định
    giá ngay lúc insert — nên mọi component nằm trong `pricing_basis` luôn có tiền.
    Bản cũ vì thế không còn kiểm được gì; nó chỉ đỏ.

    Cảnh thật còn lại là một component KHÔNG nằm trong bảng giá (agent gửi lên một
    `component` mới mà chưa ai đặt giá). `usage_events.component` là `text` không
    CHECK, nên dựng được trực tiếp — và đó chính là ca đáng lo, vì nó là đường mất
    doanh thu ÂM THẦM.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, units, occurred_at)
               VALUES ($1, 'bil-sess-voice-1', 'voice', 91, 'component_chua_co_gia',
                       'conversation', 'x', 'y', 5, '2026-08-19T09:52Z')""",
            TENANT,
        )
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/breakdown", params={"from": "2026-08-01", "to": "2026-09-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["theo_component"], "vế trái phải là usage_events, không phải rated_usage"
    khong_gia = [x for x in d["theo_component"] if x["component"] == "component_chua_co_gia"]
    assert khong_gia, "component chưa có giá bị ẨN — vế trái đang là rated_usage"
    assert Decimal(khong_gia[0]["chi_phi"]) == 0
    assert khong_gia[0]["so_event"] == 1, "số ĐO phải vẫn đúng dù không có tiền"


async def test_khong_dang_nhap_thi_401(app_client, workspace_billing) -> None:
    r = await app_client.get(f"{BASE}/summary")
    assert r.status_code == 401


async def test_moi_route_khai_action() -> None:
    """Cổng chung đã có ở tests/api — bài này chỉ neo cho module billing."""
    from portal.core.auth.actions import ACTIONS
    from portal.modules.billing.router import ROUTER

    for route in ROUTER.routes:
        deps = getattr(route, "dependencies", [])
        assert deps or route.dependant.dependencies, f"{route.path} không khai dependency nào — thiếu require()?"
    assert ACTIONS.BILLING_READ  # tránh import thừa bị ruff gỡ
