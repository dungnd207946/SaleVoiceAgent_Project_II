"""Quy tắc nghiệp vụ bảng giá. Router không chạm SQL trực tiếp ở đường admin.

`kich_hoat` là chỗ duy nhất được đặt `status='active'`, và nó KIỂM TRƯỚC KHI ĐẶT:
một bảng giá active mà thiếu dòng giá là mất doanh thu im lặng cho mọi tenant dùng nó.

⚠️ Hai cạnh CỐ Ý bỏ so với bản nháp đầu (task-9-brief.md §Step 4/5), cả hai vì
cùng một lý do — `billing.price_version.status` là NHÃN VẬN HÀNH cho UI, KHÔNG
phải nguồn sự thật khi định giá (xem docstring `billing.resolve_price_version` ở
`0943_billing_pricing.py`: hàm đó CỐ Ý không đọc `status`):

  1. `gan_cho_tenant` KHÔNG đòi `price_version.status == 'active'` trước khi gán.
     Bảng giá brief tự viết trong test của chính nó (Step 5:
     `test_gan_bo_gia_dong_khoang_cu_khong_ho_khong_chong`) không hề gọi
     `/activate` trước khi gán — với 0 dòng giá, gọi `kich_hoat()` cho các bảng
     giá đó sẽ ném `BANG_GIA_CON_LO` ngay. Đòi "đã active" ở đây là mâu thuẫn
     với chính kịch bản DoD yêu cầu phải xanh. Hàng rào chống mất-doanh-thu-im-
     lặng thật sự của bảng giá thiếu phủ không nằm ở đây — nó nằm ở
     `billing.price_coverage_gap` (cổng cảnh báo, xem `test_cong_canh_bao.py`):
     gán một bảng giá thiếu giá thì ngay sau `rate_usage()` chạy, view đó KÊU.
  2. Không có bước "đặt các price_version khác về `status='inactive'`" ở cuối.
     Bản nháp brief tính lại điều này bằng một `NOT EXISTS` con trỏ vào
     `billing.tenant_price_version` — bảng đó có RLS (`0943`, policy
     `tenant_id = portal.current_tenant()`), nên chạy trong `tenant_conn(pool,
     tenant)` của MỘT tenant thì subquery đó chỉ thấy đúng tenant đó, không thấy
     các tenant khác đang dùng cùng price_version — một UPDATE hàng loạt dựa
     trên phép đếm bị RLS bóp méo là tự tạo ra đúng loại lỗi âm thầm mà module
     này được viết ra để chống. `status` vẫn đổi được tay qua SQL nếu cần nhãn
     UI đúng; không đáng đánh đổi lấy một UPDATE sai phạm vi.
"""

from datetime import datetime
from decimal import Decimal

import asyncpg

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.quan_tri_nen_tang import ACTOR_QUAN_TRI


async def them_dong_gia(
    conn: asyncpg.Connection,
    pb: int,
    *,
    component: str,
    metric: str,
    purpose: str = "",
    provider: str = "",
    model: str = "",
    unit_price: Decimal,
    per_units: int = 1,
    note: str = "",
) -> int:
    """Thêm một dòng giá. Hai ràng buộc DB dịch thành 409 đọc được, không phải
    500 `UniqueViolationError` thô:

    - `price_item_stt_single_basis` — STT chỉ được tính tiền theo MỘT cơ sở.
    - `UNIQUE(price_version_id, component, purpose, provider, model, metric)`
      — trùng đúng một tổ hợp đã có dòng giá.
    """
    try:
        return await conn.fetchval(
            """INSERT INTO billing.price_item
               (price_version_id, component, purpose, provider, model, metric,
                unit_price, per_units, note)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
            pb,
            component,
            purpose,
            provider,
            model,
            metric,
            unit_price,
            per_units,
            note,
        )
    except asyncpg.UniqueViolationError as e:
        if e.constraint_name == "price_item_stt_single_basis":
            raise loi.LoiPortal(
                "STT_HAI_CO_SO",
                409,
                "STT chỉ được tính tiền theo MỘT cơ sở. `(stt,'conversation')/audio_sec` "
                "và `(stt,'stream')/wall_ms` là hai cách đo cùng một dịch vụ — đặt giá "
                "cả hai là tính tiền STT hai lần. Đặt cơ sở không dùng về 0.",
            ) from e
        raise loi.LoiPortal(
            "DONG_GIA_TRUNG",
            409,
            "đã có dòng giá cho cùng bộ (component, purpose, provider, model, metric)",
        ) from e


async def kich_hoat(conn: asyncpg.Connection, pb: int) -> None:
    """Chặn kích hoạt bảng giá còn lỗ. Đây là cửa cuối trước khi tiền chạy sai."""
    thieu = await conn.fetch(
        """SELECT cs.component, cs.purpose, cs.metric
             FROM billing.pricing_basis cs
            WHERE NOT EXISTS (
                  SELECT 1 FROM billing.price_item pi
                   WHERE pi.price_version_id = $1
                     AND pi.component = cs.component
                     AND pi.metric = cs.metric
                     AND (pi.purpose = '' OR pi.purpose = cs.purpose))""",
        pb,
    )
    if thieu:
        ds = ", ".join(f"{r['component']}/{r['metric']}" for r in thieu)
        raise loi.LoiPortal(
            "BANG_GIA_CON_LO",
            409,
            f"chưa có dòng giá cho: {ds}. Muốn miễn phí thì tạo dòng giá 0 — "
            "để trống nghĩa là âm thầm miễn phí và không cảnh báo nào kêu.",
        )
    await conn.execute("UPDATE billing.price_version SET status = 'active' WHERE id = $1", pb)
    await nhat_ky.ghi_he_thong(conn, "billing.price_version_kich_hoat", ACTOR_QUAN_TRI, {"price_version_id": pb})


async def gan_cho_tenant(conn: asyncpg.Connection, tenant: str, pv: int, tu: datetime) -> None:
    """Đóng khoảng đang chạy tại `tu` rồi mở khoảng mới cũng tại `tu`.

    Dùng CÙNG MỘT giá trị cho `effective_to` của dòng cũ và `effective_from` của
    dòng mới. `tstzrange` là nửa mở `[from, to)` nên hai khoảng khít nhau mà không
    chồng — EXCLUDE constraint chấp nhận, và không có giây nào không bộ giá nào phủ.

    KHÔNG cho gán lùi vào kỳ đã định giá: `rated_usage` của kỳ đó đã chốt đơn giá,
    gán lùi rồi tính lại là ra một số tiền khác cho một kỳ đã phát hành.

    KHÔNG cho đóng một khoảng đang mở mà `effective_from` của nó lại SAU `tu`:
    câu UPDATE đóng khoảng cũ không hỏi khoảng đó bắt đầu từ đâu, nó chỉ đóng
    BẤT KỲ khoảng nào còn `effective_to IS NULL`. Nếu khoảng đang mở đó bắt đầu
    ở một mốc SAU `tu` (vd ai đã gán một bảng giá hiệu lực từ tương lai), đặt
    `effective_to = tu` sẽ vi phạm CHECK `effective_to > effective_from` và
    ném `CheckViolationError` thô (500) thay vì một lỗi nghiệp vụ đọc được.
    """
    if await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM billing.rated_usage WHERE tenant_id = $1 AND occurred_at >= $2)",
        tenant,
        tu,
    ):
        raise loi.LoiPortal(
            "MOC_QUA_KHU_DA_DINH_GIA",
            409,
            f"đã có usage được định giá từ {tu:%d/%m/%Y} trở đi. Chọn một mốc sau "
            "kỳ đã chốt, hoặc xoá rated_usage của kỳ đó trước nếu thật sự muốn tính lại.",
        )
    dang_mo_tu = await conn.fetchval(
        "SELECT effective_from FROM billing.tenant_price_version WHERE tenant_id = $1 AND effective_to IS NULL",
        tenant,
    )
    if dang_mo_tu is not None and tu <= dang_mo_tu:
        raise loi.LoiPortal(
            "MOC_TRUOC_KHOANG_DANG_MO",
            409,
            f"khoảng đang chạy hiện tại mở từ {dang_mo_tu:%d/%m/%Y %H:%M}, sau mốc gán mới "
            f"({tu:%d/%m/%Y %H:%M}). Chọn một mốc SAU {dang_mo_tu:%d/%m/%Y %H:%M}.",
        )
    await conn.execute(
        "UPDATE billing.tenant_price_version SET effective_to = $2 WHERE tenant_id = $1 AND effective_to IS NULL",
        tenant,
        tu,
    )
    await conn.execute(
        "INSERT INTO billing.tenant_price_version (tenant_id, price_version_id, effective_from) VALUES ($1, $2, $3)",
        tenant,
        pv,
        tu,
    )
