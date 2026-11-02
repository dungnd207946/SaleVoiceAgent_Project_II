"""Job định giá. Cửa sổ re-run 48h là yêu cầu từ §5.4 của bên agent: đường ghi
là fire-and-forget có retry, lô của một phiên có thể landed muộn vài phút nhưng
vẫn mang `occurred_at` đúng lúc phát sinh. Chốt sổ ngay 00:00 ngày 1 là bỏ sót.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from portal.cli.dinh_gia_usage import KHOANG_RE_RUN_GIO, chay
from tests.modules.billing.conftest import TENANT


async def test_cua_so_re_run_la_48h() -> None:
    assert KHOANG_RE_RUN_GIO == 48, "đổi hằng này là đổi một quyết định nghiệp vụ — đọc §5.4 hướng dẫn bên agent"


@pytest.mark.parametrize("kwargs", [{"tu": date(2026, 8, 1)}, {"den": date(2026, 9, 1)}])
async def test_mot_minh_tu_hoac_den_bi_tu_choi(pool, kwargs) -> None:
    """Cho MỘT MÌNH `tu` hoặc MỘT MÌNH `den` phải NÉM, không âm thầm rơi về cửa
    sổ 48h mặc định.

    Trước bản vá: `if tu is None or den is None` coi CẢ HAI ca "thiếu một bên"
    và "thiếu cả hai" như nhau, nên `chay(pool, tu=date(2026,8,1))` (operator
    RÕ RÀNG xin một khoảng cụ thể) lặng lẽ định giá cửa sổ 48h gần đây nhất —
    một cận operator không xin, không một lời báo. Đường ngắn nhất để một kỳ
    billing bị định giá nhầm khoảng.
    """
    with pytest.raises(ValueError, match="CÙNG NHAU"):
        await chay(pool, **kwargs)


async def test_chay_dinh_gia_moi_tenant(pool, workspace_billing, bang_gia_vi_du) -> None:
    so_dong = await chay(pool, tu=date(2026, 8, 1), den=date(2026, 9, 1))
    assert so_dong > 0
    async with pool.acquire() as conn:
        tong = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage")
    assert tong > 0


async def test_thu_kho_khong_ghi_gi(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Diễn tập phải KHÔNG đổi gì cho tenant đang kiểm — nếu không thì không ai dám thử.

    ĐO ĐỘ LỆCH, KHÔNG ĐO `count == 0` (sửa 2026-08-21): từ `0950`, trigger
    `usage_events_dinh_gia` đã định giá usage ngay lúc fixture chèn, nên "không có
    dòng nào" là điều kiện không bao giờ đúng nữa. Thứ bài này thật sự bảo vệ là
    «một lượt thử khô không THÊM và không ĐỔI gì», và đó vốn là một độ lệch.

    Cách đo mới CHẶT HƠN bản cũ: so cả `amount` chứ không chỉ đếm dòng, nên nó bắt
    được cả ca thử khô lỡ commit một bản CẬP NHẬT — số dòng y nguyên, số tiền đổi,
    đúng cái mà `ON CONFLICT DO UPDATE` sẽ làm nếu rollback bị bỏ.

    Cột theo `tenant_id = TENANT` chứ không đếm toàn bảng: fixture là
    function-scoped và tự dọn sau mỗi bài, nên đo toàn bảng CŨNG xanh hôm nay,
    nhưng xanh vì "chưa ai để lại rác" chứ không phải vì "thử khô không ghi gì".
    """

    async def anh(conn) -> list[dict]:
        return [
            dict(r)
            for r in await conn.fetch(
                "SELECT event_id, metric, amount FROM billing.rated_usage "
                "WHERE tenant_id = $1 ORDER BY event_id, metric",
                TENANT,
            )
        ]

    async with pool.acquire() as conn:
        truoc = await anh(conn)
    await chay(pool, tu=date(2026, 8, 1), den=date(2026, 9, 1), thu_kho=True)
    async with pool.acquire() as conn:
        sau = await anh(conn)
    assert truoc == sau, "thử khô đã ghi thật — rollback trong `chay()` không có tác dụng"


async def test_mac_dinh_phu_cua_so_re_run(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Gọi không tham số phải phủ lùi 48h, không chỉ hôm nay."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ('bilw', 'bil-sess-voice-1', 'voice', 77, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 1000, $1)""",
            datetime.now(UTC) - timedelta(hours=30),
        )
    await chay(pool)
    async with pool.acquire() as conn:
        co = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage r JOIN billing.usage_events e "
            "ON e.event_id = r.event_id WHERE e.seq = 77"
        )
    assert co > 0, "event 30h trước không được định giá — cửa sổ re-run không hoạt động"


# ── `--gio`: cửa sổ NÓNG cho timer 2 phút (2026-08-21) ───────────────────────


@pytest.mark.parametrize("gio", [0, -1])
async def test_gio_khong_duong_bi_tu_choi(pool, gio) -> None:
    """Cửa sổ rỗng hoặc âm không định giá gì — thà ném hơn báo `0 dòng` như thật."""
    with pytest.raises(ValueError, match="phải > 0"):
        await chay(pool, gio=gio)


@pytest.mark.parametrize(
    "kwargs",
    [{"gio": 1, "tu": date(2026, 8, 1)}, {"gio": 1, "den": date(2026, 9, 1)}],
)
async def test_gio_loai_tru_tu_den(pool, kwargs) -> None:
    """Hai cách khai cửa sổ cùng lúc thì một cái phải thắng IM LẶNG, và operator
    đọc lệnh sẽ tin cái còn lại. Cùng lý lẽ với bài `--tu`/`--den` ở trên."""
    with pytest.raises(ValueError, match="loại trừ nhau"):
        await chay(pool, **kwargs)


async def test_gio_cat_dung_cua_so(pool, workspace_billing, bang_gia_vi_du) -> None:
    """`--gio 1` phải THẤY event 10 phút trước và BỎ event 3 giờ trước.

    Đây là bài canh chính của lượt nóng: một cửa sổ rộng hơn khai báo thì timer
    2 phút biến thành 720 lượt quét toàn bộ mỗi ngày (không sai tiền, chỉ đốt
    CPU); một cửa sổ hẹp hơn thì tiền trên portal đứng im mà không lỗi nào phát ra.
    """
    async with pool.acquire() as conn, conn.transaction():
        for seq, tre in ((78, timedelta(minutes=10)), (79, timedelta(hours=3))):
            await conn.execute(
                """INSERT INTO billing.usage_events
                   (tenant_id, session_id, channel, seq, component, purpose, provider,
                    model, input_tokens, occurred_at)
                   VALUES ($1, 'bil-sess-voice-1', 'voice', $2, 'llm', 'conversation',
                           'gemini', 'gemini-2.5-flash', 1000, $3)""",
                TENANT,
                seq,
                datetime.now(UTC) - tre,
            )
        # Trigger `usage_events_dinh_gia` (0950) đã định giá CẢ HAI ngay lúc chèn.
        # Xoá để bài này còn đo được đúng thứ nó hỏi: CỬA SỔ của `--gio 1` cắt ở
        # đâu. Không xoá thì cả hai đều có tiền và bài không thể đỏ.
        await conn.execute(
            "DELETE FROM billing.rated_usage r USING billing.usage_events e "
            "WHERE e.event_id = r.event_id AND e.seq = ANY($1::bigint[])",
            [78, 79],
        )
    await chay(pool, gio=1)
    async with pool.acquire() as conn:
        trong = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage r JOIN billing.usage_events e "
            "ON e.event_id = r.event_id WHERE e.seq = 78"
        )
        ngoai = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage r JOIN billing.usage_events e "
            "ON e.event_id = r.event_id WHERE e.seq = 79"
        )
    assert trong > 0, "event 10 phút trước KHÔNG được định giá — cửa sổ nóng hẹp quá"
    assert ngoai == 0, "event 3 giờ trước bị định giá — `--gio 1` không cắt cận dưới"
