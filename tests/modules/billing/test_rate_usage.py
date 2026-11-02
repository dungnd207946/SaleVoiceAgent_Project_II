"""Từng quy tắc định giá một. Task 3 kiểm tổng; đây kiểm cơ chế."""

from datetime import UTC, datetime
from decimal import Decimal

import asyncpg

from tests.modules.billing.conftest import TENANT, TENANT_KHAC

_TENANT_GATE = "bil_gate_metric"
_COT_MAC_DINH = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_write_tokens": 0,
    "cache_read_tokens": 0,
    "audio_sec": 0,
    "wall_ms": 0,
    "units": 0,
    "text_units": 0,
}


async def _rate(conn: asyncpg.Connection, tenant: str = TENANT) -> int:
    return await conn.fetchval(
        "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
        tenant,
    )


async def test_chay_lai_khong_nhan_ban(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Cron chạy trùng, hoặc re-run cửa sổ 48h, không được nhân đôi hoá đơn."""
    async with pool.acquire() as conn, conn.transaction():
        lan1 = await _rate(conn)
        tong1 = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        lan2 = await _rate(conn)
        tong2 = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        so_dong = await conn.fetchval("SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
    assert lan1 == lan2, "số dòng xử lý phải như nhau"
    assert tong1 == tong2, f"chạy lại làm tiền đổi: {tong1} → {tong2}"
    assert so_dong == lan1


async def test_nhan_gia_von_khong_tinh_tien(pool, workspace_billing, bang_gia_vi_du) -> None:
    """warm_cache là tối ưu nội bộ — khách không yêu cầu, không trả tiền.

    Cờ billable lọc TRƯỚC khi khớp giá. Đây là lý do không thể thay nó bằng
    'dòng giá = 0': dòng giá cụ-thể-theo-model (điểm 6) thắng dòng
    cụ-thể-theo-purpose (điểm 1), nên nhãn giá vốn vẫn bị tính đủ tiền.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, output_tokens, occurred_at)
               VALUES ($1, 'bil-sess-voice-1', 'voice', 99, 'llm', 'warm_cache',
                       'gemini', 'gemini-2.5-flash', 50000, 100, '2026-08-19T09:52Z')""",
            TENANT,
        )
        await _rate(conn)
        tien_warm = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1 AND purpose = 'warm_cache'",
            TENANT,
        )
    assert tien_warm == 0, "warm_cache bị tính tiền — cờ billable không có tác dụng"


async def test_nhan_chua_khai_van_tinh_tien(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Nhãn purpose mới agent thêm ⇒ MẶC ĐỊNH TÍNH TIỀN, và hiện ở view cảnh báo.

    Chiều ngược lại (mặc định không tính) là mất doanh thu ÂM THẦM — không ai
    phát hiện. Mặc định tính thì sai lệch sẽ có người khiếu nại.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, output_tokens, occurred_at)
               VALUES ($1, 'bil-sess-voice-1', 'voice', 98, 'llm', 'nhan_moi_la',
                       'gemini', 'gemini-2.5-flash', 1000000, 0, '2026-08-19T09:52Z')""",
            TENANT,
        )
        await _rate(conn)
        tien = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1 AND purpose = 'nhan_moi_la'",
            TENANT,
        )
        canh_bao = await conn.fetchval(
            "SELECT count(*) FROM billing.purpose_unclassified WHERE purpose = 'nhan_moi_la'"
        )
    assert tien == Decimal("2500.0000000000"), f"nhãn mới không được tính tiền: {tien}"
    assert canh_bao == 1, "nhãn mới không hiện ở purpose_unclassified"


async def test_gia_cu_the_thang_gia_wildcard(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Đặt giá chung cho mọi model rồi ghi đè riêng một model."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO billing.price_item (price_version_id, component, metric, "
            "unit_price, per_units) VALUES ($1, 'llm', 'input_tokens', 99999, 1000000)",
            bang_gia_vi_du,
        )
        await _rate(conn)
        gia_da_dung = await conn.fetchval(
            "SELECT DISTINCT unit_price FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND component = 'llm' AND metric = 'input_tokens'",
            TENANT,
        )
    assert gia_da_dung == Decimal("2500.0000000000"), f"dùng giá wildcard {gia_da_dung} thay vì giá theo model"


async def test_tinh_lai_ky_cu_khi_version_da_inactive(pool, workspace_billing, bang_gia_vi_du) -> None:
    """BÀI CANH QUAN TRỌNG NHẤT của việc siết status còn active|inactive.

    Kịch bản: tháng 8 dùng bộ v1; sang tháng 9 chuyển v2, v1 thành 'inactive'.
    Rồi có người tính lại tháng 8 — re-run cửa sổ 48h, hay tính lại sau khi sửa
    dữ liệu.

    Nếu `resolve_price_version()` đòi `status = 'active'` thì nó KHÔNG tìm thấy v1,
    rơi về `is_default`, và tháng 8 ra MỘT SỐ TIỀN KHÁC — một kỳ đã chốt bị viết
    lại, không lỗi nào phát ra, và số mới trông hoàn toàn hợp lý.

    Nên hàm đó cố ý chỉ đọc KHOẢNG HIỆU LỰC trong tenant_price_version.
    Bài này đỏ ngay nếu ai "sửa cho hợp lý" bằng cách thêm điều kiện status.

    ⚠️ DỌN `pv2` ở CUỐI: bản trước để rơi một `price_version` với
    `is_default = true` — chiếc default DUY NHẤT được phép tồn tại toàn cục
    (`price_version_single_default`), và `resolve_price_version()` FALLBACK về
    ĐÚNG nó cho MỌI tenant chưa có `tenant_price_version` che phủ. Rò một default
    là biến bài này thành máy sinh flake THEO THỨ TỰ CHẠY cho chính bộ test mà cả
    tính năng định giá dựa vào — bài chạy sau nếu gặp một tenant/khoảng chưa gán
    bảng giá sẽ ăn `unit_price = 99999` của default rò rỉ này, không phải default
    thật của môi trường đó.

    ⚠️ PHẢI NHƯỜNG CỜ MẶC ĐỊNH TRƯỚC (thêm 2026-08-21): từ migration `0949`,
    mọi DB đã có SẴN một bảng giá seed giữ `is_default`, và
    `price_version_single_default` chỉ cho phép MỘT. Cắm thẳng
    `is_default = true` cho `pv2` như bản trước nay ném `UniqueViolationError`
    ngay tại câu INSERT. Nhường bằng cách tắt cờ của bảng đang giữ, ghi lại id
    của nó, và bật lại ở `finally` SAU khi đã xoá `pv2` — làm ngược thứ tự đó là
    hai dòng cùng giữ cờ, tức đúng lỗi vừa nói.
    """
    pv2 = None
    mac_dinh_cu = None
    try:
        async with pool.acquire() as conn, conn.transaction():
            # LUÔN `_rate` trước, KHÔNG chỉ khi `truoc == 0` (sửa 2026-08-21): từ
            # `0950`, trigger đã định giá usage NGAY lúc `workspace_billing` chèn —
            # tức TRƯỚC khi `bang_gia_vi_du` kịp gán bảng giá của nó, nên số có sẵn
            # là số theo bảng giá SEED. Lấy nó làm mốc `truoc` là so hai bảng giá
            # khác nhau rồi kết luận `resolve_price_version()` đọc `status`.
            await _rate(conn)
            truoc = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)

            # nhường cờ mặc định của bảng giá seed (0949) — xem docstring
            mac_dinh_cu = await conn.fetchval(
                "UPDATE billing.price_version SET is_default = false WHERE is_default RETURNING id"
            )

            # dựng một bộ giá khác làm default, rồi cho bộ đang dùng về inactive
            pv2 = await conn.fetchval(
                "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
                "VALUES ('pv_t_khac', 'khac', 'VND', 'active', true) RETURNING id"
            )
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, provider, "
                "model, metric, unit_price, per_units) VALUES "
                "($1, 'llm', 'gemini', 'gemini-2.5-flash', 'input_tokens', 99999, 1000000)",
                pv2,
            )
            await conn.execute(
                "UPDATE billing.price_version SET status = 'inactive', is_default = false WHERE id = $1",
                bang_gia_vi_du,
            )
            await conn.execute("DELETE FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
            await _rate(conn)
            sau = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
    finally:
        async with pool.acquire() as conn, conn.transaction():
            if pv2 is not None:
                await conn.execute("DELETE FROM billing.rated_usage WHERE price_version_id = $1", pv2)
                await conn.execute("DELETE FROM billing.tenant_price_version WHERE price_version_id = $1", pv2)
                await conn.execute("DELETE FROM billing.price_version WHERE id = $1", pv2)
            # SAU khi pv2 đi rồi mới trả cờ — xem docstring về thứ tự
            if mac_dinh_cu is not None:
                await conn.execute("UPDATE billing.price_version SET is_default = true WHERE id = $1", mac_dinh_cu)

    assert sau == truoc, (
        f"tính lại kỳ cũ ra {sau} thay vì {truoc} — resolve_price_version() đang đọc "
        "`status`, và điều đó viết lại hoá đơn của một kỳ đã chốt"
    )


async def test_khong_dinh_gia_cheo_tenant(pool, workspace_billing, bang_gia_vi_du) -> None:
    """rate_usage là SECURITY DEFINER (bỏ qua RLS) nên tham số tenant PHẢI chặn.

    Không có vế này thì một lời gọi cho tenant A định giá luôn usage của B bằng
    bảng giá của A — sai tiền của cả hai, không lỗi nào phát ra.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, 'sess-khac', 'chat', 0, 'llm', 'conversation', 'gemini',
                       'gemini-2.5-flash', 500000, '2026-08-19T09:52Z')""",
            TENANT_KHAC,
        )
        # Trigger `usage_events_dinh_gia` (0950) đã định giá hàng vừa chèn NGAY
        # trong câu INSERT trên. Xoá đi để câu hỏi của bài này còn nguyên nghĩa:
        # nó hỏi «`rate_usage(tenant=A)` có chạm usage của B không», không hỏi
        # «B có tiền không» — B LUÔN có tiền từ 0950, và đó là chủ đích.
        await conn.execute("DELETE FROM billing.rated_usage WHERE tenant_id = $1", TENANT_KHAC)
        await _rate(conn, TENANT)
        ro_ri = await conn.fetchval("SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1", TENANT_KHAC)
    assert ro_ri == 0, "định giá cho tenant A đã chạm usage của tenant B"


async def test_moi_metric_dinh_gia_duoc(pool: asyncpg.Pool) -> None:
    """Cổng chống điểm mù CASE `source_expr` bị LẶP BA CHỖ (`rate_usage` ở
    `0943`, `price_coverage_gap` ở `0943`, `preview_price_version` ở `0947`).

    Một metric mới thêm vào `billing.metric` mà quên sửa MỘT trong ba CASE đó
    sẽ có `qty = NULL` ở đúng chỗ bị quên, `q.qty > 0` lọc nó ra, và event bị
    miễn phí ÂM THẦM — mà `price_coverage_gap` (view cảnh báo) CHIA SẺ đúng
    điểm mù đó (cùng CASE, cùng metric bị quên) nên cả lưới an toàn cũng im.

    KHÔNG refactor CASE dùng chung ở đây (theo ruling review — đó là việc lớn
    hơn, ghi thành follow-up). Bài này chỉ CANH: enumerate MỌI dòng
    `billing.metric` hiện có, với MỖI dòng seed một event có cột nguồn > 0 +
    một dòng giá khớp, chạy `rate_usage()`, khẳng định có đúng một dòng
    `rated_usage` sinh ra cho metric đó. Nếu một metric HIỆN CÓ fail bài này,
    đó là một phát hiện thật cần báo — không phải lý do để sửa lại bài test.
    """
    async with pool.acquire() as conn:
        metrics = await conn.fetch("SELECT code, source_expr FROM billing.metric ORDER BY code")
    assert metrics, "billing.metric rỗng — 0943 chưa áp?"

    # `tenant_price_version.tenant_id` FK về `control.tenants(id)` (ON DELETE
    # CASCADE) — cần một tenant/user THẬT, không chỉ một chuỗi text trần.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, 'Gate Metric', $2, 'x') "
            "ON CONFLICT (id) DO NOTHING",
            "u_gate_metric",
            "gate_metric@noblex.vn",
        )
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, $2) ON CONFLICT (id) DO NOTHING",
            _TENANT_GATE,
            "u_gate_metric",
        )

    try:
        for i, m in enumerate(metrics):
            comp = f"gate{i}"
            cot = dict(_COT_MAC_DINH)
            if m["source_expr"] != "1":
                cot[m["source_expr"]] = 5
            # Mỗi metric dùng một khoảng hiệu lực RIÊNG, không chồng — một tenant
            # chỉ được một khoảng ĐANG MỞ tại một thời điểm (EXCLUDE constraint
            # `tenant_price_version_no_overlap`), nên 8 lượt lặp không thể cùng
            # mở từ `2000-01-01` mà không đóng lại.
            hieu_luc_tu = datetime(2000 + i, 1, 1, tzinfo=UTC)
            hieu_luc_den = datetime(2001 + i, 1, 1, tzinfo=UTC)
            xay_ra = datetime(2000 + i, 6, 1, tzinfo=UTC)
            async with pool.acquire() as conn, conn.transaction():
                pb = await conn.fetchval(
                    "INSERT INTO billing.price_version (code, name, currency, status) "
                    "VALUES ($1, $1, 'VND', 'active') RETURNING id",
                    f"pv_gate_{comp}",
                )
                await conn.execute(
                    "INSERT INTO billing.price_item (price_version_id, component, metric, unit_price, per_units) "
                    "VALUES ($1, $2, $3, 1, 1)",
                    pb,
                    comp,
                    m["code"],
                )
                await conn.execute(
                    "INSERT INTO billing.tenant_price_version "
                    "(tenant_id, price_version_id, effective_from, effective_to) VALUES ($1, $2, $3, $4)",
                    _TENANT_GATE,
                    pb,
                    hieu_luc_tu,
                    hieu_luc_den,
                )
                # Danh sách cột SINH TỪ `cot`, không viết cứng. Bản trước viết cứng
                # và thiếu `text_units` khi metric đó được thêm ở `0948` — cổng tự
                # lỗi thời, báo "engine thiếu nhánh" trong khi engine đúng.
                ten_cot = list(cot)
                cho = ", ".join(f"${i + 4}" for i in range(len(ten_cot)))
                ev = await conn.fetchval(
                    "INSERT INTO billing.usage_events "
                    "(tenant_id, session_id, channel, seq, component, purpose, provider, model, "
                    f" {', '.join(ten_cot)}, occurred_at) "
                    f"VALUES ($1,$2,'chat',0,$3,'conversation','','', {cho}, ${len(ten_cot) + 4}) "
                    "RETURNING event_id",
                    _TENANT_GATE,
                    f"sess-{comp}",
                    comp,
                    *[cot[c] for c in ten_cot],
                    xay_ra,
                )
                await conn.execute(
                    "SELECT billing.rate_usage('1900-01-01'::timestamptz, '2200-01-01'::timestamptz, $1)",
                    _TENANT_GATE,
                )
                co = await conn.fetchval(
                    "SELECT count(*) FROM billing.rated_usage WHERE event_id = $1 AND metric = $2",
                    ev,
                    m["code"],
                )
            assert co == 1, (
                f"metric '{m['code']}' (source_expr={m['source_expr']}) KHÔNG định giá được — "
                "CASE source_expr thiếu nhánh này ở một trong ba chỗ (rate_usage/"
                "price_coverage_gap/preview_price_version)"
            )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM billing.usage_events WHERE tenant_id = $1", _TENANT_GATE)
            # xoá tenant CASCADE luôn tenant_price_version của nó
            await conn.execute("DELETE FROM control.tenants WHERE id = $1", _TENANT_GATE)
            await conn.execute("DELETE FROM billing.price_version WHERE code LIKE 'pv_gate_%'")
            await conn.execute("DELETE FROM control.users WHERE id = $1", "u_gate_metric")
