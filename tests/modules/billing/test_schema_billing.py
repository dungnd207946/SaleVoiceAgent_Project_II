"""Cổng: 0943 dựng đủ bảng/function/view và cấp quyền ĐÚNG cho từng role.

Bài quan trọng nhất là test_agent_khong_doc_duoc_bang_gia. ⚠️ SỬA (review task 5,
0944): đoạn này từng khẳng định "`portal_api` LÀ thành viên nhóm `agent_all`" như
một sự thật cố định — SAI trên một DB migrate-từ-đầu (đúng cảnh testcontainers
của test suite này). `0003_role_and_isolation_helper.py` tạo `portal_api` TRẦN
(`CREATE ROLE portal_api NOLOGIN`, không `IN ROLE agent_all`), và không migration
nào sau đó cấp tư cách thành viên đó — `GRANT agent_all TO …` chỉ nhắm
`odyssey_agent`/`agent_<tenant>` (`0005`/`0901`/`0911`). DB dev có thể trông như
hai role liên quan chỉ vì ai đó đã gõ tay `GRANT agent_all TO portal_api` ngoài
migration — đó là DRIFT của môi trường đó, không phải bất biến của schema.

Lý do bài test vẫn quan trọng KHÔNG đổi: cấp quyền cho `agent_all` "cho tiện" là
mở bảng giá cho MỌI pod agent NGAY BÂY GIỜ (agent_all đã có nhiều thành viên
runtime khác), và nếu một ngày nào đó ai thêm `portal_api` vào `agent_all` thì
một GRANT nhắm nhầm chiều sẽ mở luôn đường đó — phòng trước bằng cách CHỈ BAO GIỜ
cấp thẳng cho `portal_api`, không bao giờ cho `agent_all`, đúng bất kể tư cách
thành viên của `portal_api` hôm nay là gì.
"""

import asyncpg
import pytest

BANG_MOI = [
    "metric",
    "pricing_basis",
    "purpose",
    "price_version",
    "price_item",
    "tenant_price_version",
    "rated_usage",
    # "invoice"/"invoice_line" (0943) đã DROP ở 0959 — schema "giai đoạn 2"
    # chưa từng có code nào chạm tới.
]
VIEW_MOI = [
    "price_coverage_gap",
    "purpose_unclassified",
    "unbillable_event",
    "cost_by_key_day",
    "cost_by_component_day",
]


async def test_bang_va_view_ton_tai(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for ten in BANG_MOI:
            assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"billing.{ten}"), (
                f"thiếu bảng billing.{ten}"
            )
        for ten in VIEW_MOI:
            assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"billing.{ten}"), (
                f"thiếu view billing.{ten}"
            )


async def test_so_dong_hat_giong(pool: asyncpg.Pool) -> None:
    """Ba bảng danh mục phải có dữ liệu hạt giống, không rỗng."""
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM billing.metric") == 9
        assert await conn.fetchval("SELECT count(*) FROM billing.pricing_basis") == 13
        assert await conn.fetchval("SELECT count(*) FROM billing.purpose") == 12
        assert await conn.fetchval("SELECT count(*) FROM billing.purpose WHERE NOT billable") == 5


async def test_portal_api_doc_duoc(api_dsn: str) -> None:
    """Không có GRANT thì mọi màn hình usage trả 500."""
    conn = await asyncpg.connect(api_dsn)
    try:
        for ten in BANG_MOI + VIEW_MOI:
            await conn.fetchval(f"SELECT count(*) FROM billing.{ten}")
    finally:
        await conn.close()


async def test_agent_khong_doc_duoc_bang_gia(pool: asyncpg.Pool) -> None:
    """`agent_all` KHÔNG được thấy giá. Cấp cho nhóm này là mở cho mọi pod."""
    async with pool.acquire() as conn:
        for ten in ("price_version", "price_item", "rated_usage"):
            co = await conn.fetchval("SELECT has_table_privilege('agent_all', $1, 'SELECT')", f"billing.{ten}")
            assert co is False, f"agent_all đọc được billing.{ten}"


async def test_rls_tren_bang_mang_tenant_id(pool: asyncpg.Pool) -> None:
    """Bảng billing mang tenant_id phải có RLS + policy, giống usage_events."""
    async with pool.acquire() as conn:
        for ten in ("rated_usage", "tenant_price_version"):
            rls = await conn.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE oid = $1::regclass",
                f"billing.{ten}",
            )
            assert rls is True, f"billing.{ten} thiếu RLS"
            so_policy = await conn.fetchval(
                "SELECT count(*) FROM pg_policy WHERE polrelid = $1::regclass",
                f"billing.{ten}",
            )
            assert so_policy > 0, f"billing.{ten} có RLS nhưng KHÔNG policy nào"


async def test_status_chi_hai_gia_tri(pool: asyncpg.Pool) -> None:
    """`status` chỉ còn active|inactive, default inactive.

    Bộ giá mới PHẢI ra đời ở trạng thái không áp cho ai — mặc định 'active' nghĩa
    là vừa tạo xong đã tính tiền khách bằng một bộ giá chưa ai nhập đủ ô.
    """
    async with pool.acquire() as conn:
        ck = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'billing.price_version'::regclass AND contype = 'c' "
            "AND pg_get_constraintdef(oid) LIKE '%status%'"
        )
        assert "'active'" in ck and "'inactive'" in ck
        assert "draft" not in ck and "archived" not in ck
        mac_dinh = await conn.fetchval(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'billing' AND table_name = 'price_version' "
            "AND column_name = 'status'"
        )
        assert "inactive" in mac_dinh


async def test_gia_da_sinh_ra_tien_thi_bat_bien(pool: asyncpg.Pool) -> None:
    """Sửa được giá của bộ đang dùng là VIẾT LẠI hoá đơn các kỳ đã chốt.

    Cùng lệ với `control.config_versions` (0200 REVOKE UPDATE, DELETE). Khác ở chỗ
    điều kiện ở đây là ĐỘNG ("đã sinh ra tiền chưa") nên dùng trigger thay vì REVOKE.
    """
    async with pool.acquire() as conn, conn.transaction():
        pv = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency) VALUES ('pv_t_frozen', 't', 'VND') RETURNING id"
        )
        it = await conn.fetchval(
            "INSERT INTO billing.price_item (price_version_id, component, metric, "
            "unit_price, per_units) VALUES ($1, 'tts', 'units', 2, 1) RETURNING id",
            pv,
        )
        # chưa sinh ra tiền ⇒ sửa được
        await conn.execute("UPDATE billing.price_item SET unit_price = 3 WHERE id = $1", it)

        ev = await conn.fetchval(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, units)
               VALUES ('t_frozen', 's', 'chat', 0, 'tts', 'conversation', 10)
               RETURNING event_id"""
        )
        await conn.execute(
            """INSERT INTO billing.rated_usage
               (event_id, metric, tenant_id, occurred_at, component, purpose,
                provider, model, price_version_id, quantity, unit_price, per_units,
                amount, currency)
               VALUES ($1, 'units', 't_frozen', now(), 'tts', 'conversation',
                       '', '', $2, 10, 3, 1, 30, 'VND')""",
            ev,
            pv,
        )
        with pytest.raises(asyncpg.PostgresError, match="da sinh ra tien"):
            await conn.execute("UPDATE billing.price_item SET unit_price = 9999 WHERE id = $1", it)


async def test_stt_chi_mot_co_so_tinh_tien(pool: asyncpg.Pool) -> None:
    """Đặt giá cả hai cơ sở STT là tính tiền STT hai lần. DB phải chặn."""
    async with pool.acquire() as conn, conn.transaction():
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status) "
            "VALUES ('pv_t_stt', 't', 'VND', 'inactive') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO billing.price_item "
            "(price_version_id, component, purpose, metric, unit_price, per_units) "
            "VALUES ($1, 'stt', 'conversation', 'audio_sec', 10, 1)",
            pb,
        )
        # INSERT thứ hai được kỳ vọng ném UniqueViolationError, và ở Postgres một
        # lệnh lỗi làm ABORT cả giao dịch bao quanh — mọi lệnh sau đó (kể cả DELETE
        # dọn rác) sẽ ăn `InFailedSQLTransactionError` nếu cùng một giao dịch. Bọc
        # trong `conn.transaction()` LỒNG (asyncpg tự hiểu là SAVEPOINT) để chỉ mỗi
        # lệnh lỗi bị cuốn, còn giao dịch ngoài vẫn dùng được cho câu DELETE dọn dẹp.
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO billing.price_item "
                    "(price_version_id, component, purpose, metric, unit_price, per_units) "
                    "VALUES ($1, 'stt', 'stream', 'wall_ms', 99, 60000)",
                    pb,
                )
        await conn.execute("DELETE FROM billing.price_version WHERE code = 'pv_t_stt'")
