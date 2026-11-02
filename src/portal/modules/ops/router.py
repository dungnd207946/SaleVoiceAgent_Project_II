"""Endpoint của M7 — màn Hội thoại + hộp thư sale.
Nguồn: docs/superpowers/specs/2026-08-06-m7-man-hoi-thoai-design.md

MÀN HỘI THOẠI CHỈ GET: không tiếp quản, không nhắn cho khách, không đặt lịch.

HỘP THƯ SALE CÓ MỘT ĐƯỜNG GHI — `PATCH /escalations/{id}`, đường ghi đầu tiên của
M7. Nó hiện thực đúng nửa "đánh dấu đã xử lý" của `convos.handle`; nửa "tiếp quản
hội thoại" vẫn chưa có gì phía sau.

CẢ BA ENDPOINT DÙNG `CONVOS_READ`, kể cả endpoint transcript. `CONVOS_TRANSCRIPT_READ`
có trong catalog (migration 0104) nhưng cố ý không gắn vào đâu — quyết định của chủ
sản phẩm 06/08: ai xem được hội thoại thì xem được cả nội dung. Ghi ở đây để lần
sau ai thấy action lơ lửng thì biết là chủ ý.
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.avatar import avatar_data_uri
from portal.core.db.session import tenant_conn
from portal.modules.config.contracts import TEN_KY_NANG
from portal.modules.ops import repo
from portal.modules.ops.contracts import (
    GIOI_HAN_TRANG,
    PHONE_TRONG,
    SO_NGAY,
    TRANG_CA,
    TRANG_MAC_DINH,
    CaOut,
    ChanDungOut,
    ChiTietPhienOut,
    ChuyenSaleOut,
    DanhGiaOut,
    GhiChuOut,
    HoiThoaiOut,
    KenhOut,
    KhachOut,
    KienThucOut,
    LuotOut,
    MocOut,
    MucDuAn,
    MucKienThucOut,
    NgayOut,
    NhanCaIn,
    OverviewOut,
    PhienOut,
    TrangCa,
    TrangKhach,
)

ROUTER = APIRouter(tags=["ops"])
"""KHÔNG có prefix chung — `api/app.py` gắn `/api/v1`."""

_MUI_GIO = ZoneInfo("Asia/Ho_Chi_Minh")

_KIEN_THUC = (
    ("duAn", "du_an"),
    ("phanKhu", "phan_khu"),
    ("can", "can"),
    ("taiLieuTraCuu", "tai_lieu_tra_cuu"),
)
"""Bốn mục cùng HÌNH `<cot>_thay`/`<cot>_tong` nên đọc được bằng một vòng lặp
— chú ý là cùng hình, KHÔNG cùng luật: ba mục đầu lọc `status = 'published'`,
`taiLieuTraCuu` lọc `state = 'san_sang'` trên một bảng khác (xem
`repo.kien_thuc`). Thứ tự là hợp đồng trình bày — FE vẽ theo đúng thứ tự nhận
được, không tự sắp lại. Đi từ thô tới tinh: dự án → phân khu → căn → tài liệu.

Mục thứ NĂM (`kyNang`) cố ý ĐỨNG NGOÀI bảng này, không phải quên: mẫu số của
nó không đến từ một truy vấn (`repo.kien_thuc` không trả `ky_nang_tong`) mà từ
sổ kỹ năng `TEN_KY_NANG`. Nhét nó vào đây thì vòng lặp phải mọc một nhánh
đặc biệt — đắt hơn hẳn một dòng viết thẳng."""


def _phien_khong_thay() -> loi.LoiPortal:
    """404, KHÔNG 403 — xem docstring `doc_phien` dưới đây và `repo.doc_phien`:
    403 nói cho người ngoài biết session ấy có tồn tại ở tenant khác hay không."""
    return loi.LoiPortal("SESSION_NOT_FOUND", 404, "Không tìm thấy phiên hội thoại này")


def _avatar(ten: str | None) -> str | None:
    """NULL khi chưa có tên — cùng luật `noiDungAvatar(null)` bên FE: không đoán
    một avatar không có căn cứ. Seed = TÊN để cùng một khách ra cùng một avatar
    ở mọi màn (khách · phiên · ca cùng đi qua đây)."""
    return avatar_data_uri(ten) if ten else None


def _ra_khach(r: asyncpg.Record) -> KhachOut:
    ten = None if r["phone"] == "" else r["ten"]
    return KhachOut(
        phone=r["phone"],
        ten=ten,
        avatar=_avatar(ten),
        soPhien=r["so_phien"],
        ganNhat=r["gan_nhat"],
        dauTien=r["dau_tien"],
        daChuyen=r["da_chuyen"],
        summaryCuoi=r["summary_cuoi"],
        duAn=r["du_an"],
        tenDuAn=r["ten_du_an"],
        leadStage=r["lead_stage"],
        leadScore=r["lead_score"],
        audience=r["audience"],
    )


def _ca_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("ESCALATION_NOT_FOUND", 404, "Không tìm thấy ca chuyển sale này")


def _ra_ca(r: asyncpg.Record) -> CaOut:
    return CaOut(
        id=r["id"],
        sessionId=r["session_id"],
        phone=r["phone"],
        ten=r["ten"],
        avatar=_avatar(r["ten"]),
        duAn=r["du_an"],
        tenDuAn=r["ten_du_an"],
        toolThieuDuLieu=r["missing_data_tool"],
        summary=r["summary"],
        summaryLuc=r["summary_at"],
        messageSeq=r["message_seq"],
        trangThai=r["status"],
        nguoiXuLy=r["nguoi_xu_ly"],
        xuLyLuc=r["handled_at"],
        ghiChu=r["handled_note"],
        kenh=r["kenh"],
        soLuot=r["so_luot"] or 0,
        taoLuc=r["created_at"],
    )


def _ra_phien(r: asyncpg.Record) -> PhienOut:
    return PhienOut(
        sessionId=r["session_id"],
        ten=r["customer_name"],
        avatar=_avatar(r["customer_name"]),
        batDau=r["started_at"],
        ketThuc=r["ended_at"],
        soLuot=r["so_luot"],
        tinNhanDau=r["tin_nhan_dau"],
        summary=r["summary"],
        duAn=r["project"],
        tenDuAn=r["ten_du_an"],
        daChuyen=r["transferred_to_sales"],
        runningVersion=r["running_version"],
        source=r["source"],
        phone=r["phone"],
        leadStage=r["lead_stage"],
        leadScore=r["lead_score"],
        audience=r["audience"],
    )


def _json(gia_tri: object, khi_hong: object) -> object:
    """`jsonb` do hệ khác ghi. asyncpg trả chuỗi JSON nếu chưa đăng ký codec, nên
    parse ở đây; parse hỏng thì trả `khi_hong` — một `meta` méo của MỘT lượt không
    được làm 500 cả phiên."""
    if isinstance(gia_tri, str):
        try:
            gia_tri = json.loads(gia_tri)
        except ValueError:
            return khi_hong
    return gia_tri if type(gia_tri) is type(khi_hong) else khi_hong


def _ra_luot(r: asyncpg.Record) -> LuotOut:
    meta = _json(r["meta"], {})
    return LuotOut(
        seq=r["seq"],
        role=r["role"],
        content=r["content"],
        taoLuc=r["created_at"],
        meta=meta,
    )


@ROUTER.get("/convos/khach", response_model=TrangKhach)
async def liet_ke_khach(
    q: str = "",
    tu_ngay: str = Query("30", pattern="^(7|30|all)$"),
    da_chuyen: bool = False,
    lead_stage: str = Query("", pattern="^(|lead|mql|sql|hen_gap|none)$"),
    limit: int = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG),
    offset: int = Query(0, ge=0),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangKhach:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_khach(
            conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen, lead_stage=lead_stage, limit=limit, offset=offset
        )
        so_khach, so_phien = await repo.dem_tong(
            conn, tim=q, tu_ngay=tu_ngay, da_chuyen=da_chuyen, lead_stage=lead_stage
        )
    return TrangKhach(items=[_ra_khach(r) for r in hang], tongKhach=so_khach, tongPhien=so_phien)


@ROUTER.get("/escalations", response_model=TrangCa)
async def liet_ke_ca(
    q: str = "",
    trang_thai: str = Query("all", pattern="^(new|contacted|done|handled|all)$"),
    du_an: str = "",
    sap_xep: str = Query("moi", pattern="^(moi|cu)$"),
    limit: int = Query(TRANG_CA, ge=1, le=GIOI_HAN_TRANG),
    offset: int = Query(0, ge=0),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangCa:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_ca(
            conn, tim=q, trang_thai=trang_thai, du_an=du_an, sap_xep=sap_xep, limit=limit, offset=offset
        )
        tong = await repo.dem_ca(conn, tim=q, trang_thai=trang_thai, du_an=du_an)
        du_an_co = await repo.du_an_co_ca(conn)
    return TrangCa(
        items=[_ra_ca(r) for r in hang], tongCa=tong, duAnCo=[MucDuAn(ma=r["ma"], ten=r["ten"]) for r in du_an_co]
    )


@ROUTER.get("/escalations/{ca_id}/notes", response_model=list[GhiChuOut])
async def lich_su_ghi_chu(
    ca_id: int,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[GhiChuOut]:
    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.doc_ca(conn, ca_id) is None:
            raise _ca_khong_thay()
        hang = await repo.doc_ghi_chu(conn, ca_id=ca_id)
    return [GhiChuOut.model_validate(dict(r)) for r in hang]


@ROUTER.get("/escalations/{ca_id}/trich", response_model=list[LuotOut])
async def trich_hoi_thoai(
    ca_id: int,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[LuotOut]:
    """Mấy lượt thoại ngay trước lúc agent chuyển ca.

    Mảng RỖNG chứ không 404 khi phiên chưa có lượt nào: bên agent ghi transcript
    fire-and-forget nên lượt cuối có thể chưa xuống Postgres, và một ca có thật
    mà chưa có thoại là chuyện bình thường, không phải ca không tồn tại.
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        ca = await repo.doc_ca(conn, ca_id)
        if ca is None:
            raise _ca_khong_thay()
        hang = await repo.doc_trich(conn, session_id=ca["session_id"], truoc_seq=ca["message_seq"])
    return [_ra_luot(r) for r in hang]


@ROUTER.patch("/escalations/{ca_id}", response_model=CaOut)
async def nhan_ca(
    ca_id: int,
    body: NhanCaIn,
    p: Principal = require(ACTIONS.CONVOS_HANDLE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CaOut:
    """404 chứ KHÔNG 403 khi ca thuộc tenant khác — cùng lý lẽ `doc_phien`."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        ok = await repo.cap_nhat_ca(
            conn, ca_id=ca_id, trang_thai=body.trangThai, nguoi=p.user_id, ghi_chu=body.ghiChu or None
        )
        if not ok:
            raise _ca_khong_thay()
        hang = await repo.doc_ca(conn, ca_id)
    if hang is None:
        raise _ca_khong_thay()
    return _ra_ca(hang)


@ROUTER.get("/convos/khach/{phone}/phien", response_model=list[PhienOut])
async def liet_ke_phien(
    phone: str,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[PhienOut]:
    """Số không có phiên nào trả MẢNG RỖNG, không 404 — một URL đã gửi cho đồng
    nghiệp vẫn phải mở được."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_phien(conn, phone=None if phone == PHONE_TRONG else phone)
    return [_ra_phien(r) for r in hang]


@ROUTER.get("/convos/khach/{phone}/chan-dung", response_model=ChanDungOut)
async def doc_chan_dung(
    phone: str,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChanDungOut:
    """Khách chưa có gì ⇒ chân dung RỖNG, không 404 (cùng lý lẽ `liet_ke_phien`).

    «Chưa có số» không truy vấn gì: agent chỉ ghi `contacts` khi biết số, và nhóm đó là
    nhiều người ẩn danh — một chân dung cho cả nhóm là nói sai.
    """
    if phone == PHONE_TRONG:
        return ChanDungOut(hoSo={}, ghiNho=None, tinHieu=[], capNhatLuc=None)
    async with tenant_conn(pool, p.tenant_id) as conn:
        r = await repo.doc_chan_dung(conn, phone=phone)
    tin_hieu = _json(r["lead_signals"], [])
    return ChanDungOut(
        hoSo=_json(r["profile"], {}),
        ghiNho=r["snapshot"] or None,
        tinHieu=[s for s in tin_hieu if isinstance(s, str)],
        capNhatLuc=r["updated_at"],
    )


@ROUTER.get("/convos/phien/{session_id}", response_model=ChiTietPhienOut)
async def doc_phien(
    session_id: str,
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChiTietPhienOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        phien = await repo.doc_phien(conn, session_id)
        if phien is None:
            raise _phien_khong_thay()
        luot = await repo.doc_luot(conn, session_id)
    # Phiên có thật nhưng chưa có lượt nào ⇒ `luot: []`, KHÔNG 404.
    return ChiTietPhienOut(
        phien=_ra_phien(phien),
        luot=[_ra_luot(r) for r in luot],
        skillCalls=_json(phien["skill_calls"], []),
    )


@ROUTER.get("/overview", response_model=OverviewOut)
async def doc_overview(
    p: Principal = require(ACTIONS.OVERVIEW_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> OverviewOut:
    """MỘT endpoint cho cả màn — xem docstring khối Overview ở `contracts.py`.

    **Mốc thời gian tính Ở ĐÂY, không ở SQL.** `now()` gọi bảy lần trong bảy
    câu SQL có thể rơi qua nửa đêm giữa chừng — khi đó ô Hội thoại và ô Đánh
    giá nói về hai cửa sổ khác nhau mà không có dấu hiệu nào. Tính một lần rồi
    truyền xuống thì mọi ô nói về đúng một khoảng.

    Bảy truy vấn KHÔNG dùng chung một cửa sổ — chúng chia làm ba hạng, và đó
    là ngữ nghĩa của cả endpoint:

    ┌ kỳ NÀY `(tu_ngay, tinh_den)` = `SO_NGAY` ngày gần nhất, tính đến hôm nay
    │   · `hoi_thoai_theo_kenh`  · `dem_chuyen_sale`
    │   (`hoi_thoai_theo_ngay` cũng phủ đúng cửa sổ này nhưng nhận `tinh_den`
    │    rồi tự lùi `so_ngay` — nó phải sinh đủ `SO_NGAY` hàng qua
    │    `generate_series`, kể cả ngày rỗng, nên nó cầm độ dài chứ không cầm
    │    mốc đầu)
    ├ kỳ TRƯỚC `(tu_ngay_truoc, tinh_den_truoc)` = `SO_NGAY` ngày liền kề
    │  phía trước — MẪU SỐ của badge delta ô ①, không phải số hiển thị
    │   · `dem_hoi_thoai`
    └ KHÔNG có cửa sổ nào — hai loại, vì hai lý do khác nhau:
      · `kien_thuc` đếm TỒN KHO tại thời điểm hiện tại (bao nhiêu dự án/căn/
        tài liệu agent đọc được, agent đang bật mấy kỹ năng) — một đại lượng
        trạng thái, chưa bao giờ theo kỳ;
      · `danh_gia` đếm TÍCH LUỸ (đổi 2026-08-14, trước đây theo kỳ) để ô ③ in
        ra ĐÚNG con số mà dải thống kê màn `/quality` in — xem docstring
        `repo.danh_gia`. Lượt gọi thứ hai (`dg_truoc`) dùng `truoc_ngay=`,
        tức cũng tích luỹ nhưng cắt ở đầu kỳ này: badge delta vì thế đọc là
        «điểm tích luỹ đã nhích bao nhiêu sau bảy ngày vừa rồi», không phải
        so hai kỳ rời nhau.
    """
    tinh_den = datetime.now(_MUI_GIO).date()
    tu_ngay = tinh_den - timedelta(days=SO_NGAY - 1)
    tu_ngay_truoc = tu_ngay - timedelta(days=SO_NGAY)
    tinh_den_truoc = tu_ngay - timedelta(days=1)

    async with tenant_conn(pool, p.tenant_id) as conn:
        ngay = await repo.hoi_thoai_theo_ngay(conn, tinh_den=tinh_den)
        kenh = await repo.hoi_thoai_theo_kenh(conn, tu_ngay=tu_ngay, tinh_den=tinh_den)
        truoc = await repo.dem_hoi_thoai(conn, tu_ngay=tu_ngay_truoc, tinh_den=tinh_den_truoc)
        cs = await repo.dem_chuyen_sale(conn, tu_ngay=tu_ngay, tinh_den=tinh_den)
        dg = await repo.danh_gia(conn)
        dg_truoc = await repo.danh_gia(conn, truoc_ngay=tu_ngay)
        kt = await repo.kien_thuc(conn)

    theo_ngay = [NgayOut(ngay=r["ngay"], chat=r["chat"], voice=r["voice"], khac=r["khac"]) for r in ngay]
    return OverviewOut(
        moc=MocOut(tuNgay=tu_ngay, tinhDen=tinh_den),
        hoiThoai=HoiThoaiOut(
            tong=sum(n.tong for n in theo_ngay),
            truoc=truoc,
            theoNgay=theo_ngay,
            theoKenh=[KenhOut(kenh=r["kenh"], n=r["n"]) for r in kenh],
        ),
        chuyenSale=ChuyenSaleOut(chuyen=cs["chuyen"], tuXuLy=max(0, cs["tong"] - cs["chuyen"])),
        danhGia=DanhGiaOut(
            trungBinh=round(dg["trung_binh"] or 0.0, 2),
            truoc=round(dg_truoc["trung_binh"], 2) if dg_truoc["trung_binh"] is not None else None,
            tong=dg["tong"],
            theoSao={str(n): dg[f"sao{n}"] for n in range(1, 6)},
        ),
        kienThuc=KienThucOut(
            muc=[
                *(
                    MucKienThucOut(khoa=khoa, thay=kt[f"{cot}_thay"], tong=kt[f"{cot}_tong"])
                    for khoa, cot in _KIEN_THUC
                ),
                MucKienThucOut(khoa="kyNang", thay=kt["ky_nang_thay"], tong=len(TEN_KY_NANG)),
            ]
        ),
    )
