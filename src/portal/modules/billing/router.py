"""Endpoint module Usage & Billing.

Tầng TENANT chỉ GET — không có đường ghi nào ở đó. Định giá là job (Task 8).
Tầng ADMIN (Task 9, tiền tố `/admin/billing/*`) là màn quản trị bảng giá của
NobleX: tạo/nạp/kích hoạt bảng giá, xem trước (preview) và gán cho tenant. Xác
thực bằng token quản trị nền tảng (`X-Platform-Admin-Token`), KHÔNG bằng phiên
— đặt giá là việc của NobleX, không của khách. Router không chạm SQL trực tiếp
ở đường admin có quy tắc nghiệp vụ — xem `service.py`.

Mọi endpoint TENANT dùng `ACTIONS.BILLING_READ`. Tách khỏi `WORKSPACE_ADMIN` để
kế toán xem được hoá đơn mà không cần quyền quản trị thành viên.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.quan_tri_nen_tang import require_quan_tri_nen_tang
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.billing import repo, service
from portal.modules.billing.contracts import (
    TRANG_MAC_DINH,
    TRANG_TOI_DA,
    CanhBaoOut,
    ChiTietPhienOut,
    DanhSachKeyOut,
    DanhSachPhienOut,
    DongComponentOut,
    DongGiaIn,
    DongKeyOut,
    DongNgayOut,
    DongOwnerOut,
    EventOut,
    GanBoGiaIn,
    PhanNgayOut,
    PhanTichOut,
    PhanUsageNgayOut,
    PhienBanGiaIn,
    PhienUsageOut,
    TongQuanOut,
    UsageNgayOut,
    UsageTheoNgayOut,
)

ROUTER = APIRouter(tags=["billing"])
"""KHÔNG prefix chung — `api/app.py` gắn `/api/v1`."""

_MAC_DINH_NGAY = 30

_LY_DO_ADMIN = "xác thực bằng token quản trị nền tảng, không phải phiên workspace"
_PREVIEW_NGAY = 30
"""Cửa sổ preview: usage 30 ngày gần nhất — đủ để thấy đơn giá mới ảnh hưởng bao
nhiêu tiền mà không quét toàn bộ lịch sử usage của tenant."""


def _khoang(tu: date | None, den: date | None) -> tuple[date, date]:
    """Mặc định 30 ngày gần nhất. `den` là cận TRÊN MỞ — `< den`, không `<=`.

    Dùng `<=` thì một dòng landed lúc 00:00:00.5 ngày cuối rơi ra ngoài, và cùng
    một kỳ đếm ra hai số khác nhau tuỳ ai gọi.
    """
    den_ = den or (date.today() + timedelta(days=1))
    tu_ = tu or (den_ - timedelta(days=_MAC_DINH_NGAY))
    if tu_ >= den_:
        raise loi.LoiPortal("KHOANG_KHONG_HOP_LE", 422, "`from` phải trước `to`")
    return tu_, den_


def _phien_out(r: asyncpg.Record) -> PhienUsageOut:
    return PhienUsageOut(
        session_id=r["session_id"],
        agent_key_id=r["agent_key_id"],
        key_label=r["key_label"],
        customer_name=r["customer_name"],
        phone=r["phone"],
        channel=r["channel"],
        bat_dau=r["bat_dau"],
        so_turn=r["so_turn"],
        input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"],
        voice_sec=r["voice_sec"],
        chi_phi=r["chi_phi"],
        chi_phi_llm=r["chi_phi_llm"],
        chi_phi_tts=r["chi_phi_tts"],
        chi_phi_stt=r["chi_phi_stt"],
        chi_phi_embed=r["chi_phi_embed"],
        chi_phi_search=r["chi_phi_search"],
        chi_phi_call=r["chi_phi_call"],
        chi_phi_vad=r["chi_phi_vad"],
        chi_phi_speaker_verify=r["chi_phi_speaker_verify"],
        exact=r["exact"],
    )


def _gom_ngay(hang: list[asyncpg.Record]) -> list[DongNgayOut]:
    """Gộp các hàng (ngày, component) của `repo.theo_ngay()` thành một mảng ngày.

    Dựa vào việc SQL đã `ORDER BY k.ngay` — mỗi ngày là một khối liên tiếp, nên
    một lượt quét là đủ, không cần dict trung gian. Ngày rỗng tới đây dưới dạng
    MỘT hàng `component IS NULL`; nó vẫn phải sinh ra một `DongNgayOut` (chi phí
    0, `phan` rỗng), đó là cả lý do `generate_series` tồn tại ở tầng SQL.
    """
    ra: list[DongNgayOut] = []
    for r in hang:
        if not ra or ra[-1].ngay != r["ngay"]:
            ra.append(DongNgayOut(ngay=r["ngay"], chi_phi=Decimal(0), phan=[]))
        if r["component"] is None:
            continue
        ra[-1].phan.append(PhanNgayOut(component=r["component"], chi_phi=r["chi_phi"]))
        ra[-1].chi_phi += r["chi_phi"]
    return ra


def _gom_usage_ngay(hang: list[asyncpg.Record]) -> list[UsageNgayOut]:
    """Gộp các hàng (ngày, component) của `repo.usage_theo_ngay()` thành mảng ngày.

    Cùng khuôn `_gom_ngay()` và cùng bất biến quan trọng nhất của nó: ngày rỗng
    tới đây dưới dạng MỘT hàng `component IS NULL` và vẫn phải sinh ra một
    `UsageNgayOut` (`phan` rỗng, `so_phien` 0) — đó là cả lý do
    `generate_series` tồn tại ở tầng SQL. Bỏ qua hàng đó là để FE nối thẳng qua
    ngày agent không chạy.

    Dựa vào `ORDER BY k.ngay` của SQL nên một lượt quét là đủ, không cần dict.
    `so_phien` lặp lại ở mọi hàng của cùng một ngày (nó là thuộc tính của NGÀY,
    không của component) — lấy ở hàng đầu của khối, các hàng sau không ghi lại.
    """
    ra: list[UsageNgayOut] = []
    for r in hang:
        if not ra or ra[-1].ngay != r["ngay"]:
            ra.append(UsageNgayOut(ngay=r["ngay"], so_phien=r["so_phien"], phan=[]))
        if r["component"] is None:
            continue
        ra[-1].phan.append(
            PhanUsageNgayOut(
                component=r["component"],
                so_event=r["so_event"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                cache_read_tokens=r["cache_read_tokens"],
                audio_sec=r["audio_sec"],
                text_units=r["text_units"],
                units=r["units"],
                wall_ms_stream=r["wall_ms_stream"],
                text_units_hoi_thoai=r["text_units_hoi_thoai"],
                token_du_lieu_ngoai=r["token_du_lieu_ngoai"],
                text_units_du_lieu_ngoai=r["text_units_du_lieu_ngoai"],
            )
        )
    return ra


@ROUTER.get("/billing/summary", response_model=TongQuanOut)
async def summary(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TongQuanOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        r = await repo.tong_quan(conn, tu_, den_)
        cb = await repo.canh_bao(conn)
    return TongQuanOut(
        input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"],
        cache_read_tokens=r["cache_read_tokens"],
        voice_sec=r["voice_sec"],
        so_phien=r["so_phien"],
        so_key=r["so_key"],
        chi_phi=r["chi_phi"],
        chi_phi_du_lieu_ngoai=r["chi_phi_du_lieu_ngoai"],
        currency=r["currency"],
        canh_bao=CanhBaoOut(
            thieu_gia=cb["thieu_gia"],
            nhan_chua_phan_loai=cb["nhan_chua_phan_loai"],
            event_khong_so_do=cb["event_khong_so_do"],
            llm_khong_chinh_xac=cb["llm_khong_chinh_xac"],
        ),
    )


@ROUTER.get("/billing/breakdown", response_model=PhanTichOut)
async def breakdown(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> PhanTichOut:
    """Mục ② màn `/usage` — cùng kỳ với `/billing/summary`, khác chiều gộp.

    `chi_phi_tong` lấy từ CHÍNH `repo.tien_tenant()` mà `/by-key` dùng, không
    tự cộng lại từ hai danh sách trên: hai con số "tổng" tính bằng hai đường
    khác nhau sẽ lệch nhau vào đúng ngày một trong hai đường có bug, và lệch
    im lặng. `tien_tenant()` cũng là chỗ DUY NHẤT ném `NHIEU_DON_VI_TIEN` —
    endpoint này thừa hưởng phép kiểm đó thay vì bịa một `currency` khác.
    """
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        chi_phi_tong, currency = await repo.tien_tenant(conn, tu_, den_)
        ngay = await repo.theo_ngay(conn, tu_, den_)
        comp = await repo.theo_component(conn, tu_, den_)
    return PhanTichOut(
        theo_ngay=_gom_ngay(ngay),
        theo_component=[
            DongComponentOut(
                component=r["component"],
                so_event=r["so_event"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                cache_read_tokens=r["cache_read_tokens"],
                audio_sec=r["audio_sec"],
                text_units=r["text_units"],
                units=r["units"],
                chi_phi=r["chi_phi"],
                chi_phi_du_lieu_ngoai=r["chi_phi_du_lieu_ngoai"],
            )
            for r in comp
        ],
        chi_phi_tong=chi_phi_tong,
        currency=currency,
    )


@ROUTER.get("/billing/usage-by-day", response_model=UsageTheoNgayOut)
async def usage_by_day(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> UsageTheoNgayOut:
    """Thẻ biểu đồ màn `/usage` — SỐ ĐO theo ngày, tách theo component.

    Nguồn DUY NHẤT của cả thẻ đó: client suy tổng kỳ · đỉnh · số ngày hoạt động
    từ chính chuỗi ngày này. `/billing/breakdown` cũng trả đúng bộ số đo tổng kỳ
    ở `theo_component[]`, nhưng lấy tổng từ đó là HAI NGUỒN cho MỘT con số — hai
    câu SQL khác nhau (một gộp theo component, một gộp theo ngày+component) thì
    ngày nào lệch sẽ lệch âm thầm, rail nói một số còn biểu đồ vẽ một số khác.

    KHÔNG trả `chi_phi`/`currency` ở bất kỳ tầng nào (xem
    `contracts.UsageTheoNgayOut`) — và vì thế cũng KHÔNG gọi `repo.tien_tenant()`
    như `breakdown` phải làm.
    """
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.usage_theo_ngay(conn, tu_, den_)
    return UsageTheoNgayOut(theo_ngay=_gom_usage_ngay(hang))


@ROUTER.get("/billing/by-key", response_model=DanhSachKeyOut)
async def by_key(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DanhSachKeyOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        chi_phi_tong, currency = await repo.tien_tenant(conn, tu_, den_)
        hang = await repo.theo_key(conn, tu_, den_)
    items = [
        DongKeyOut(
            agent_key_id=r["agent_key_id"],
            du_lieu_ngoai=r["du_lieu_ngoai"],
            label=r["label"],
            key_prefix=r["key_prefix"],
            nguoi_tao=r["nguoi_tao"],
            nguoi_tao_ten=r["nguoi_tao_ten"],
            da_thu_hoi=r["da_thu_hoi"],
            so_phien=r["so_phien"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            voice_sec=r["voice_sec"],
            so_event=r["so_event"],
            chi_phi=r["chi_phi"],
            chi_phi_llm=r["chi_phi_llm"],
            chi_phi_tts=r["chi_phi_tts"],
            chi_phi_stt=r["chi_phi_stt"],
            chi_phi_embed=r["chi_phi_embed"],
            chi_phi_search=r["chi_phi_search"],
            chi_phi_call=r["chi_phi_call"],
            chi_phi_vad=r["chi_phi_vad"],
            chi_phi_speaker_verify=r["chi_phi_speaker_verify"],
        )
        for r in hang
    ]
    return DanhSachKeyOut(
        items=items,
        total=len(items),
        # `chi_phi_tong`/`currency` đọc TỪ DỮ LIỆU (`repo.tien_tenant`, có kiểm
        # trộn đơn vị tiền — xem docstring hàm đó), KHÔNG hardcode "VND": amount
        # trong `billing.rated_usage` mang đơn vị của bảng giá đã áp cho từng
        # event, và bảng giá đó có thể không phải VND.
        chi_phi_tong=chi_phi_tong,
        currency=currency,
    )


@ROUTER.get("/billing/by-owner", response_model=list[DongOwnerOut])
async def by_owner(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[DongOwnerOut]:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.theo_owner(conn, tu_, den_)
    return [
        DongOwnerOut(
            user_id=r["user_id"],
            ten=r["ten"],
            email=r["email"],
            du_lieu_ngoai=r["du_lieu_ngoai"],
            so_key=r["so_key"],
            so_phien=r["so_phien"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            cache_read_tokens=r["cache_read_tokens"],
            voice_sec=r["voice_sec"],
            so_event=r["so_event"],
            chi_phi=r["chi_phi"],
            chi_phi_llm=r["chi_phi_llm"],
            chi_phi_tts=r["chi_phi_tts"],
            chi_phi_stt=r["chi_phi_stt"],
            chi_phi_embed=r["chi_phi_embed"],
            chi_phi_search=r["chi_phi_search"],
            chi_phi_call=r["chi_phi_call"],
            chi_phi_vad=r["chi_phi_vad"],
            chi_phi_speaker_verify=r["chi_phi_speaker_verify"],
        )
        for r in hang
    ]


@ROUTER.get("/billing/sessions", response_model=DanhSachPhienOut)
async def sessions(
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    limit: int = Query(TRANG_MAC_DINH, ge=1, le=TRANG_TOI_DA),
    offset: int = Query(0, ge=0),
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DanhSachPhienOut:
    tu_, den_ = _khoang(tu, den)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_phien(conn, tu_, den_, limit, offset)
    return DanhSachPhienOut(
        items=[_phien_out(r) for r in hang],
        total=hang[0]["total"] if hang else 0,
    )


@ROUTER.get("/billing/sessions/{session_id}", response_model=ChiTietPhienOut)
async def chi_tiet_phien(
    session_id: str,
    p: Principal = require(ACTIONS.BILLING_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChiTietPhienOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        phien = await repo.doc_phien(conn, session_id)
        if phien is None:
            raise loi.LoiPortal("PHIEN_KHONG_TON_TAI", 404, f"không có usage cho phiên `{session_id}`")
        ev = await repo.event_cua_phien(conn, session_id)
    return ChiTietPhienOut(
        phien=_phien_out(phien),
        events=[
            EventOut(
                event_id=r["event_id"],
                seq=r["seq"],
                turn_idx=r["turn_idx"],
                component=r["component"],
                purpose=r["purpose"],
                provider=r["provider"],
                model=r["model"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                cache_read_tokens=r["cache_read_tokens"],
                audio_sec=r["audio_sec"],
                units=r["units"],
                text_units=r["text_units"],
                exact=r["exact"],
                chi_phi=r["chi_phi"],
                occurred_at=r["occurred_at"],
            )
            for r in ev
        ],
    )


# ─── Màn admin bảng giá (Task 9) ────────────────────────────────────────────
# Mỗi route khai CẢ HAI: `require(None, ly_do=...)` (để qua cổng M2a
# test_moi_route_khai_action.py — mọi endpoint HTTP phải khai action, và
# `require(None)` trần nói "cố ý không dùng 13 nhóm PQ_01") VÀ
# `require_quan_tri_nen_tang()` (cổng THẬT — kiểm header X-Platform-Admin-Token).
# Hai thứ khác nhau: cái đầu là lời khai ý định, cái sau là cửa thật. Đúng khuôn
# `modules/enrollment/router.py` đã dùng cho `/agent/admin/*`.


@ROUTER.get("/admin/billing/price-versions")
async def liet_ke_bang_gia(
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[dict[str, object]]:
    async with pool.acquire() as conn:
        hang = await conn.fetch(
            "SELECT id, code, name, currency, status, is_default, created_at "
            "FROM billing.price_version ORDER BY id DESC"
        )
    return [dict(r) for r in hang]


@ROUTER.post("/admin/billing/price-versions", status_code=201)
async def tao_bang_gia(
    body: PhienBanGiaIn,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int]:
    """Tạo bảng giá NHÁP — `status` luôn khởi đầu `'inactive'`.

    `billing.price_version` không mang `tenant_id` (nó là danh mục dùng chung),
    nên không có RLS ở đây và một kết nối trần từ `pool` là đủ.
    """
    async with pool.acquire() as conn:
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status, created_by) "
            "VALUES ($1, $2, $3, 'inactive', 'platform_admin') RETURNING id",
            body.code,
            body.name,
            body.currency,
        )
    return {"id": pb}


@ROUTER.post("/admin/billing/price-versions/{pb}/items", status_code=201)
async def tao_dong_gia(
    pb: int,
    body: DongGiaIn,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int]:
    async with pool.acquire() as conn:
        return {"id": await service.them_dong_gia(conn, pb, **body.model_dump())}


@ROUTER.post("/admin/billing/price-versions/{pb}/activate")
async def kich_hoat_bang_gia(
    pb: int,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, str]:
    async with pool.acquire() as conn, conn.transaction():
        await service.kich_hoat(conn, pb)
    return {"status": "active"}


@ROUTER.get("/admin/billing/price-versions/{pb}/preview")
async def preview_bang_gia(
    pb: int,
    tenant: str = Query(...),
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, object]:
    """Áp bảng giá `pb` (kể cả còn NHÁP) lên usage 30 ngày gần nhất của `tenant`.

    THUẦN SELECT qua `billing.preview_price_version()` (migration
    `0947_billing_preview`) — KHÔNG nạp/xoá/ROLLBACK như bản nháp đầu của
    task-9-brief.md: `portal_api` chỉ có quyền SELECT trên `billing.rated_usage`
    (`0943_billing_pricing` cố ý không cấp DELETE — đường ghi duy nhất là
    `billing.rate_usage()`, chạy dưới `SECURITY DEFINER`), nên một `DELETE` ở
    tầng ứng dụng sẽ ném `InsufficientPrivilegeError` và endpoint không bao giờ
    chạy được. Hàm SQL mirror đúng khuôn khớp giá của `rate_usage()` (CROSS JOIN
    `billing.metric` + LATERAL khớp giá cụ thể nhất + lọc `billing.purpose`
    billable) nhưng chỉ SELECT tổng tiền, không INSERT — không có gì để rollback.

    `tenant_conn(pool, tenant)` chứ không phải `pool.acquire()` trần:
    `billing.usage_events` có RLS (`tenant_id = portal.current_tenant()`) — đọc
    ngoài giao dịch có đặt biến phiên sẽ trả 0 hàng cho MỌI tenant, không phải
    lỗi quyền, và preview sẽ luôn ra 0 một cách im lặng.
    """
    den = datetime.now(UTC)
    tu = den - timedelta(days=_PREVIEW_NGAY)
    async with tenant_conn(pool, tenant) as conn:
        chi_phi = await conn.fetchval("SELECT billing.preview_price_version($1, $2, $3, $4)", pb, tenant, tu, den)
        currency = await conn.fetchval("SELECT currency FROM billing.price_version WHERE id = $1", pb)
    return {"chiPhi": str(chi_phi or 0), "currency": currency or "VND"}


@ROUTER.post("/admin/billing/tenants/{tenant_id}/price-version")
async def gan_bo_gia(
    tenant_id: str,
    body: GanBoGiaIn,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, str]:
    async with tenant_conn(pool, tenant_id) as conn:
        await service.gan_cho_tenant(conn, tenant_id, body.price_version_id, body.effective_from)
    return {"status": "ok"}
