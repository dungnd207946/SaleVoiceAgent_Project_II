"""Ba view cổng. Chúng là cơ chế chống MẤT DOANH THU ÂM THẦM, nên bài quan trọng
nhất không phải "view rỗng khi đủ giá" mà "view KÊU khi thiếu giá".

Một cổng chưa bao giờ thấy đỏ là một cổng chưa biết có hoạt động không.
"""

from tests.modules.billing.conftest import TENANT


async def test_du_gia_thi_ba_view_rong(pool, workspace_billing, bang_gia_vi_du) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )
        assert await conn.fetchval("SELECT count(*) FROM billing.price_coverage_gap") == 0
        assert await conn.fetchval("SELECT count(*) FROM billing.purpose_unclassified") == 0
        assert await conn.fetchval("SELECT count(*) FROM billing.unbillable_event") == 0


async def test_thieu_gia_thi_view_keu(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bỏ giá cache_read — đúng cái §1.1 hướng dẫn bên agent nói "luôn 0" (SAI).

    Data thật có cache_read_tokens = 35.548 cho gemini-2.5-flash. Ai tin §1.1 rồi
    bỏ dòng giá này sẽ mất tiền, và mất IM LẶNG vì không có dòng giá nào để đối chiếu.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM billing.price_item WHERE price_version_id = $1 AND metric = 'cache_read_tokens'",
            bang_gia_vi_du,
        )
        # ⚠️ PHẢI XOÁ `rated_usage` TRƯỚC KHI ĐỊNH GIÁ LẠI (thêm 2026-08-21). Từ
        # `0950`, trigger đã định giá usage ngay lúc `workspace_billing` chèn — lúc
        # đó `bang_gia_vi_du` chưa tồn tại nên tiền được tính bằng bảng giá SEED,
        # vốn CÓ dòng `cache_read_tokens`. Chạy lại `rate_usage()` KHÔNG xoá hàng
        # đó (`ON CONFLICT DO UPDATE` chỉ chạm hàng còn khớp giá), nên hàng cũ ở
        # lại và `price_coverage_gap` thấy metric này «đã có tiền» ⇒ im.
        #
        # Đây là một cạnh sắc THẬT của thiết kế, không phải trò của test: đổi bảng
        # giá cho một tenant rồi định giá lại KHÔNG dọn hàng của metric vừa mất
        # giá. Không chạm tới cấu hình hiện tại (một bảng giá `is_default` duy
        # nhất, không ai gán per-tenant), nhưng ngày nào gán per-tenant thì phải
        # xoá `rated_usage` của kỳ đó trước — đúng câu mà lỗi
        # `MOC_QUA_KHU_DA_DINH_GIA` đang chỉ dẫn.
        await conn.execute("DELETE FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )
        gap = await conn.fetch("SELECT * FROM billing.price_coverage_gap")
    assert len(gap) == 1, "thiếu giá cache_read mà price_coverage_gap không kêu"
    assert gap[0]["metric"] == "cache_read_tokens"
    assert gap[0]["quantity"] > 0


async def test_gia_0_khong_bi_coi_la_thieu(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Miễn phí TƯỜNG MINH (giá 0) khác với thiếu giá. Không phân biệt được thì
    view kêu mãi và người trực học cách bỏ qua nó."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )
        # cache_write có giá 0 và có dòng giá ⇒ không được coi là gap
        gap = await conn.fetchval("SELECT count(*) FROM billing.price_coverage_gap WHERE metric = 'cache_write_tokens'")
    assert gap == 0
