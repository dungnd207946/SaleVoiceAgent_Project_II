"""Trigger `usage_events_dinh_gia` (`0950`) — tiền sinh ra TRONG câu INSERT.

Hợp đồng người dùng chốt 2026-08-21: «khi có 1 dòng `usage_events` thì có 1 hoặc
nhiều dòng `rated_usage` được tạo ra để lưu giá tiền của usage đó». Cả file này
canh đúng câu đó, và **không bài nào ở đây được gọi `billing.rate_usage()`** —
gọi nó là kiểm mất đường cron, không phải kiểm trigger.
"""

from decimal import Decimal

import asyncpg

# `MOC` của conftest là một `datetime` tz-aware — asyncpg TỪ CHỐI chuỗi ISO cho
# tham số bind kiểu timestamptz (`DataError`), nên đừng viết lại thành literal.
from tests.modules.billing.conftest import MOC, TENANT


async def _chen(conn: asyncpg.Connection, seq: int, **cot) -> int:
    """Chèn MỘT event, trả `event_id`. Không gọi `rate_usage` ở đâu cả."""
    mac_dinh = {
        "component": "llm",
        "purpose": "conversation",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "audio_sec": 0,
        "text_units": 0,
        "wall_ms": 0,
        "units": 0,
    }
    mac_dinh.update(cot)
    ten = ", ".join(mac_dinh)
    tham = ", ".join(f"${i + 4}" for i in range(len(mac_dinh)))
    return await conn.fetchval(
        f"""INSERT INTO billing.usage_events
            (tenant_id, session_id, channel, seq, {ten}, occurred_at)
            VALUES ($1, 'bil-sess-voice-1', 'voice', $2, {tham}, $3)
            RETURNING event_id""",
        TENANT,
        seq,
        MOC,
        *mac_dinh.values(),
    )


async def test_insert_sinh_tien_ngay_khong_can_goi_gi(pool: asyncpg.Pool, workspace_billing) -> None:
    """Bài trung tâm của cả file: INSERT xong là CÓ TIỀN, không ai gọi hàm nào.

    Đỏ ở đây nghĩa là hệ thống quay về trạng thái trước `0950` — tiền chỉ có khi
    cron chạy, và portal hiện `0 ₫` giữa hai lượt cron.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            eid = await _chen(conn, 201, input_tokens=1_000_000)
            hang = await conn.fetch(
                "SELECT metric, quantity, unit_price, amount, currency FROM billing.rated_usage WHERE event_id = $1",
                eid,
            )
        finally:
            await tx.rollback()

    assert hang, "INSERT usage_events KHÔNG sinh dòng rated_usage nào — trigger không chạy"
    assert len(hang) == 1, f"1M input token phải ra ĐÚNG 1 dòng (metric input_tokens), nhận {len(hang)}"
    r = hang[0]
    assert r["metric"] == "input_tokens"
    assert r["quantity"] == Decimal("1000000")
    # Bảng giá mặc định `0954` (`vendor-vnd-2026-08`): 19.500 đ / 1M input token
    # ($0,75/1M ×26.000). Trước `0954` con số này là 78.000 (bản seed `0949`) —
    # đổi ở đây vì `0954` chuyển cờ `is_default`, không phải vì trigger đổi.
    assert r["unit_price"] == Decimal("19500")
    assert r["amount"] == Decimal("19500")
    assert r["currency"] == "VND"


async def test_mot_event_ra_NHIEU_dong_theo_so_metric(pool: asyncpg.Pool, workspace_billing) -> None:
    """«1 hoặc NHIỀU» — N = số metric có `qty > 0` VÀ khớp được dòng giá.

    Đây là chỗ khoá `(event_id, metric)` của `rated_usage` phát huy: bốn đồng hồ
    token của một lượt LLM là bốn dòng, không phải một dòng tổng. Gộp lại là mất
    khả năng trả lời «tiền đi vào input hay output», tức mất cả mục ② của `/usage`.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            eid = await _chen(
                conn,
                202,
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_tokens=1_000_000,
                cache_write_tokens=1_000_000,
            )
            theo_metric = {
                r["metric"]: r["amount"]
                for r in await conn.fetch("SELECT metric, amount FROM billing.rated_usage WHERE event_id = $1", eid)
            }
        finally:
            await tx.rollback()

    # Giá bản `0954`: $0,75 / $3,75 / $0,075 / $0,075 mỗi 1M token, ×26.000 đ/USD.
    assert theo_metric == {
        "input_tokens": Decimal("19500"),
        "output_tokens": Decimal("97500"),
        "cache_read_tokens": Decimal("1950"),
        "cache_write_tokens": Decimal("1950"),
    }, f"bốn đồng hồ token phải ra bốn dòng đúng giá bản 0954, nhận {theo_metric}"


async def test_metric_qty_0_khong_sinh_dong(pool: asyncpg.Pool, workspace_billing) -> None:
    """`qty = 0` KHÔNG được sinh dòng — nếu không, mỗi event ra 8 dòng, 6 dòng 0 đồng.

    Đó không chỉ là rác: `theo_component` của `/usage` đếm `so_event` từ
    `usage_events` nhưng tiền từ `rated_usage`, và một bảng đầy dòng 0 làm mọi
    truy vấn tổng hợp nặng lên mà không thêm một thông tin nào.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            eid = await _chen(conn, 203, input_tokens=1000)
            metric = [
                r["metric"] for r in await conn.fetch("SELECT metric FROM billing.rated_usage WHERE event_id = $1", eid)
            ]
        finally:
            await tx.rollback()
    assert metric == ["input_tokens"], f"chỉ metric có lượng mới được sinh dòng, nhận {metric}"


async def test_lo_nhieu_dong_mot_cau_insert(pool: asyncpg.Pool, workspace_billing) -> None:
    """Agent ghi theo LÔ, và cả lô phải được định giá trong đúng một lượt trigger.

    Bài này cũng là bài canh chống hồi quy về hiệu năng: trigger là
    `FOR EACH STATEMENT` + `REFERENCING NEW TABLE`. Ai đổi sang `FOR EACH ROW` thì
    bài vẫn XANH nhưng một lô 500 dòng sẽ tốn 500 lượt — nên docstring của `0950`
    nói rõ lý do, còn bài này chỉ chốt phần ĐÚNG ĐẮN: không dòng nào bị bỏ sót.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                """INSERT INTO billing.usage_events
                   (tenant_id, session_id, channel, seq, component, purpose, provider,
                    model, input_tokens, occurred_at)
                   SELECT $1, 'bil-sess-voice-1', 'voice', 300 + g, 'llm', 'conversation',
                          'gemini', 'gemini-2.5-flash', 1000, $2
                     FROM generate_series(1, 50) g""",
                TENANT,
                MOC,
            )
            so = await conn.fetchval(
                """SELECT count(*) FROM billing.rated_usage r
                     JOIN billing.usage_events e ON e.event_id = r.event_id
                    WHERE e.tenant_id = $1 AND e.seq BETWEEN 301 AND 350""",
                TENANT,
            )
        finally:
            await tx.rollback()
    assert so == 50, f"lô 50 event phải ra 50 dòng tiền, nhận {so}"


async def test_dinh_gia_hong_KHONG_lam_vo_insert(pool: asyncpg.Pool, workspace_billing) -> None:
    """SỔ GỐC bất khả xâm phạm: định giá hỏng thì usage VẪN được ghi.

    Bài quan trọng nhất về mặt rủi ro. `usage_events` mất một hàng là mất vĩnh
    viễn; `rated_usage` tính lại được. Dựng cảnh hỏng bằng cách thay
    `billing.dinh_gia_events` bằng một bản luôn ném, rồi INSERT.

    Đỏ ở đây nghĩa là khối `EXCEPTION WHEN OTHERS` trong `dinh_gia_sau_insert()`
    đã bị ai gỡ, và từ giây đó một lỗi bảng giá sẽ làm agent mất số đo.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("""
                CREATE OR REPLACE FUNCTION billing.dinh_gia_events(p_event_ids bigint[])
                 RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER AS $$
                BEGIN
                  RAISE EXCEPTION 'hong co y de test';
                END $$;
            """)
            eid = await _chen(conn, 204, input_tokens=1000)
            tien = await conn.fetchval("SELECT count(*) FROM billing.rated_usage WHERE event_id = $1", eid)
        finally:
            # Rollback trả LUÔN hàm thật về — DDL trong Postgres có giao dịch.
            await tx.rollback()

    assert eid is not None, "định giá hỏng đã làm vỡ câu INSERT — MẤT SỔ GỐC"
    assert tien == 0, "định giá hỏng mà vẫn ghi được tiền?"


async def test_ham_that_da_tro_lai_sau_rollback(pool: asyncpg.Pool, workspace_billing) -> None:
    """Chốt rằng bài trên KHÔNG rò một `dinh_gia_events` giả sang bài chạy sau.

    `CREATE OR REPLACE FUNCTION` là DDL và Postgres có giao dịch cho DDL, nên
    rollback là đủ — nhưng «đủ về lý thuyết» và «đúng trên container này» là hai
    câu khác nhau, và một hàm định giá giả rò rỉ sẽ làm mọi bài sau đỏ theo cách
    không ai truy được về đây.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            eid = await _chen(conn, 205, input_tokens=1_000_000)
            tien = await conn.fetchval(
                "SELECT amount FROM billing.rated_usage WHERE event_id = $1 AND metric = 'input_tokens'",
                eid,
            )
        finally:
            await tx.rollback()
    assert tien == Decimal("19500"), f"hàm định giá thật chưa trở lại: {tien}"
