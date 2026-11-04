"""Trả góp: đối tác tài chính · gói trả góp + đối tượng áp dụng · báo giá ước tính.

Route tĩnh (`/installment-plans/quote`, `/quotes`) đăng ký TRƯỚC `/installment-plans/{id}`.
"""

import math
from decimal import Decimal
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api.loi import du_lieu_khong_hop_le, khong_tim_thay
from portal.core.ban_hang import (
    TargetIn,
    TargetOut,
    dang_ky_crud_le,
    dk_ap_dung,
    doc_targets,
    lam_tron,
    lay_bien_the,
    thay_targets,
    them_dk,
    trang,
)
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, dang_ky_crud, lay, liet_ke
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.modules.finance.contracts import (
    BaoGiaTraGopOut,
    FinancePartnerIn,
    FinancePartnerOut,
    InstallmentPlanIn,
    InstallmentPlanOut,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

BANG = "installment_plans"
BANG_DT = "installment_plan_targets"
TEN = "gói trả góp"


def dang_chay(a: str = "") -> str:
    """Gói bật + now() trong cửa sổ — cùng định nghĩa `has_installment_0` của agent_products_v."""
    return f"({a}is_active AND now() >= {a}starts_at AND ({a}ends_at IS NULL OR now() < {a}ends_at))"


dang_ky_crud(
    ROUTER,
    duong_dan="/finance-partners",
    bang="finance_partners",
    ten="đối tác tài chính",
    model_in=FinancePartnerIn,
    model_out=FinancePartnerOut,
    tim_kiem=("name", "code"),
)


@ROUTER.get("/installment-plans", summary="Danh sách gói trả góp")
async def liet_ke_goi(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    partner_id: Annotated[int | None, Query(alias="partnerId")] = None,
    active: bool | None = None,
) -> Trang[InstallmentPlanOut]:
    dk: list[str] = []
    ts: list[Any] = []
    if partner_id is not None:
        them_dk(dk, ts, "partner_id = {}", partner_id)
    if active is not None:
        dk.append(dang_chay() if active else f"NOT {dang_chay()}")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, BANG, dieu_kien=dk, tham_so=ts, sap_xep="partner_id, tenor_months, id", limit=limit, offset=offset
        )
    return trang(InstallmentPlanOut, rows, total, limit, offset)


_SQL_GOI = f"""
    SELECT ip.*, fp.name AS partner_name, fp.is_active AND {dang_chay("ip.")} AS dang_chay,
           EXISTS (SELECT 1 FROM shop.installment_plan_targets t
                   WHERE t.plan_id = ip.id AND {dk_ap_dung("t", "$1", "$2", "$3", "$4")}) AS ap_dung
    FROM shop.installment_plans ip JOIN shop.finance_partners fp ON fp.id = ip.partner_id
"""


def tinh_bao_gia(goi: asyncpg.Record, bt: asyncpg.Record, phan_tram: Decimal) -> BaoGiaTraGopOut:
    """Ước tính lãi PHẲNG theo tháng (đơn giản hoá — hợp đồng thật do công ty tài chính quyết):

        giá        = giá bán hiện tại của SKU (coalesce(sale_price_vnd, list_price_vnd))
        trả trước  = round(giá × %trả trước / 100)        (làm tròn nửa lên)
        khoản vay  = giá − trả trước
        góp/tháng  = ceil(vay / kỳ hạn + vay × lãi%/tháng / 100)
        tổng trả   = trả trước + góp/tháng × kỳ hạn + phí cố định
        chênh lệch = tổng trả − giá

    Tính bằng Decimal: float làm `ceil` nhảy thêm 1đ khi phép chia đáng lẽ chẵn.
    """
    gia = int(bt["price_vnd"])
    ky_han = int(goi["tenor_months"])
    lai = Decimal(goi["interest_rate_monthly"])
    tra_truoc = lam_tron(Decimal(gia) * phan_tram / 100)
    vay = gia - tra_truoc
    gop = math.ceil(Decimal(vay) / ky_han + Decimal(vay) * lai / 100)
    tong = tra_truoc + gop * ky_han + int(goi["fixed_fee_vnd"])
    return BaoGiaTraGopOut(
        plan_id=goi["id"],
        plan_name=goi["name"],
        partner_id=goi["partner_id"],
        partner_name=goi["partner_name"],
        variant_id=bt["variant_id"],
        tenor_months=ky_han,
        interest_rate_monthly=float(lai),
        price_vnd=gia,
        down_payment_percent=float(phan_tram),
        down_payment_vnd=tra_truoc,
        loan_vnd=vay,
        monthly_payment_vnd=gop,
        fixed_fee_vnd=int(goi["fixed_fee_vnd"]),
        total_payment_vnd=tong,
        extra_cost_vnd=tong - gia,
    )


def _trong_khoang_gia(goi: asyncpg.Record, gia: int) -> bool:
    return (goi["min_price_vnd"] is None or gia >= goi["min_price_vnd"]) and (
        goi["max_price_vnd"] is None or gia <= goi["max_price_vnd"]
    )


def _khoa_bt(bt: asyncpg.Record) -> tuple[int, int, int, int]:
    return bt["variant_id"], bt["product_id"], bt["brand_id"], bt["category_id"]


@ROUTER.get("/installment-plans/quote", summary="Báo giá trả góp ước tính cho một SKU theo một gói")
async def bao_gia(
    pool: Pool,
    variant_id: Annotated[int, Query(alias="variantId")],
    plan_id: Annotated[int, Query(alias="planId")],
    down_payment_percent: Annotated[float | None, Query(alias="downPaymentPercent", ge=0, le=100)] = None,
) -> BaoGiaTraGopOut:
    """Từ chối (422) khi gói không chạy, không áp cho SKU, giá ngoài khoảng của gói, hoặc
    % trả trước dưới mức tối thiểu. Bỏ trống `downPaymentPercent` ⇒ dùng mức tối thiểu của gói.
    Công thức: xem `tinh_bao_gia`."""
    async with pool.acquire() as conn:
        bt = await lay_bien_the(conn, variant_id)
        goi = await conn.fetchrow(_SQL_GOI + " WHERE ip.id = $5", *_khoa_bt(bt), plan_id)
    if goi is None:
        raise khong_tim_thay(TEN, plan_id)
    if not goi["dang_chay"]:
        raise du_lieu_khong_hop_le(f"Gói trả góp #{plan_id} không còn hiệu lực")
    if not goi["ap_dung"]:
        raise du_lieu_khong_hop_le(f"Gói trả góp #{plan_id} không áp dụng cho biến thể #{variant_id}")
    if not _trong_khoang_gia(goi, int(bt["price_vnd"])):
        raise du_lieu_khong_hop_le(f"Giá {bt['price_vnd']}đ nằm ngoài khoảng giá của gói #{plan_id}")
    toi_thieu = Decimal(goi["min_down_payment_percent"])
    phan_tram = toi_thieu if down_payment_percent is None else Decimal(str(down_payment_percent))
    if phan_tram < toi_thieu:
        raise du_lieu_khong_hop_le(f"Trả trước tối thiểu {toi_thieu}% với gói #{plan_id}")
    return tinh_bao_gia(goi, bt, phan_tram)


@ROUTER.get("/installment-plans/quotes", summary="Báo giá mọi gói trả góp áp được cho một SKU")
async def bao_gia_moi_goi(pool: Pool, variant_id: Annotated[int, Query(alias="variantId")]) -> list[BaoGiaTraGopOut]:
    """Mỗi gói đang chạy, áp được, giá trong khoảng — tính ở % trả trước TỐI THIỂU của gói.
    Sắp theo góp/tháng tăng dần (cái khách hỏi đầu tiên)."""
    async with pool.acquire() as conn:
        bt = await lay_bien_the(conn, variant_id)
        goi = await conn.fetch(_SQL_GOI + " ORDER BY ip.id", *_khoa_bt(bt))
    gia = int(bt["price_vnd"])
    bao = [
        tinh_bao_gia(g, bt, Decimal(g["min_down_payment_percent"]))
        for g in goi
        if g["dang_chay"] and g["ap_dung"] and _trong_khoang_gia(g, gia)
    ]
    return sorted(bao, key=lambda b: (b.monthly_payment_vnd, b.plan_id))


async def _phai_co(conn: asyncpg.Connection, id_: int) -> None:
    if await lay(conn, BANG, id_) is None:
        raise khong_tim_thay(TEN, id_)


@ROUTER.get("/installment-plans/{id}/targets", summary="Đối tượng áp dụng của gói trả góp")
async def doc_dt(id: int, pool: Pool) -> list[TargetOut]:
    async with pool.acquire() as conn:
        await _phai_co(conn, id)
        return await doc_targets(conn, BANG_DT, "plan_id", id)


@ROUTER.put("/installment-plans/{id}/targets", summary="Thay toàn bộ đối tượng áp dụng")
async def thay_dt(id: int, body: list[TargetIn], pool: Pool) -> list[TargetOut]:
    async with tx(pool) as conn:
        await _phai_co(conn, id)
        return await thay_targets(conn, BANG_DT, "plan_id", id, body)


dang_ky_crud_le(
    ROUTER, duong_dan="/installment-plans", bang=BANG, ten=TEN, model_in=InstallmentPlanIn, model_out=InstallmentPlanOut
)
