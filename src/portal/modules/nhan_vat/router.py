"""Endpoint «Người dẫn» của tab Voice — nhân vật lip sync do workspace tự tạo.

    GET    /nhan-vat                      danh sách + nhân vật đang dùng + cấu hình (tạo từ ảnh?)
    GET    /nhan-vat/dang-dung            nhân vật tab Voice dùng (None = người dẫn mặc định)
    PUT    /nhan-vat/dang-dung            {"id": "<id>" | null} — đổi người dẫn
    POST   /nhan-vat                      multipart: ten, nguon=video|anh, dongY=true, tep, tepTay?, moTa?
    GET    /nhan-vat/{id}                 một nhân vật (FE thăm dò tiến độ)
    POST   /nhan-vat/{id}/thu-lai         dựng lại sau lỗi (giữ video/ảnh đã gửi)
    POST   /nhan-vat/{id}/xem-truoc       {"cau"} → mp4 nhân vật nói câu đó (không lưu)
    GET    /nhan-vat/{id}/poster          ảnh chờ PNG (RGBA)
    GET    /nhan-vat/{id}/xem-truoc/{i}   video xem trước câu demo thứ i
    DELETE /nhan-vat/{id}

Dựng chạy NỀN (job `nhan_vat.buoc`, xem jobs.py). Quyền: đọc `AGENT_CONFIG_READ`, sửa
`AGENT_CONFIG_WRITE` — người dẫn là một phần cấu hình trải nghiệm agent.

ĐỒNG Ý: `dongY` bắt buộc true — khách xác nhận có quyền dùng hình ảnh/giọng người trong
video/ảnh (chân dung là dữ liệu cá nhân). Thời điểm đồng ý lưu ở `dong_y_luc` + nhật ký.
"""

import secrets
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue
from portal.core.storage import KhongTimThay, kho_tep_dung_chung, kho_tep_tu_cai_dat
from portal.modules.nhan_vat import jobs, repo, so
from portal.modules.nhan_vat import nha_cung_cap as ncc_mod
from portal.modules.nhan_vat.contracts import (
    ChonIn,
    DangDungOut,
    DanhSachNhanVatOut,
    LoiNhanVat,
    NhanVatOut,
    XemTruocIn,
    XemTruocOut,
)
from portal.modules.nhan_vat.lipsync import LipsyncClient, LoiLipsync
from portal.modules.nhan_vat.settings import get_env

ROUTER = APIRouter(prefix="/nhan-vat", tags=["nhan-vat"])

_GOC = "/api/v1/nhan-vat"
# Tham số form khai bằng `Annotated[..., Form()]` — MỖI tham số một `Form()` riêng. Bản đầu
# dùng chung một hằng `_CHU = Form(...)` cho cả `ten`/`nguon`/`dongY` (né B008) và FastAPI
# gắn kiểu `bool` của `dongY` lên cả `ten` ⇒ mọi lần tạo nhân vật 422 «ten: valid boolean».
# Test gọi thẳng handler không đi qua FastAPI nên không thấy — bài HTTP ở test_router_http.


def _khong_co() -> loi.LoiPortal:
    return loi.LoiPortal("NHAN_VAT_KHONG_TON_TAI", 404, "Không có nhân vật này")


def _out(nv: dict) -> NhanVatOut:
    ma = nv["loi_ma"]
    return NhanVatOut(
        id=nv["id"],
        ten=nv["ten"],
        nguon=nv["nguon"],
        trangThai=nv["trang_thai"],
        buoc=nv["buoc"],
        tienDo=float(nv["tien_do"]),
        loi=(
            LoiNhanVat(
                ma=ma, huongDan=so.HUONG_DAN_LOI.get(ma, so.HUONG_DAN_LOI["LOI_HE_THONG"]), chiTiet=nv["loi_chi_tiet"]
            )
            if nv["trang_thai"] == "loi" and ma
            else None
        ),
        dangDung=bool(nv["dang_dung"]),
        avatarId=nv["avatar_id"] if nv["trang_thai"] == "san_sang" else None,
        posterUrl=f"{_GOC}/{nv['id']}/poster" if nv["poster_key"] else None,
        xemTruoc=[
            XemTruocOut(cau=x["cau"], url=f"{_GOC}/{nv['id']}/xem-truoc/{i}") for i, x in enumerate(nv["xem_truoc"])
        ],
        videoUrl=f"{_GOC}/{nv['id']}/video/chinh" if nv["video_key"] else None,
        videoTayUrl=f"{_GOC}/{nv['id']}/video/tay" if nv["video_tay_key"] else None,
        taoLuc=nv["created_at"].isoformat(),
    )


def _ncc_ten() -> str | None:
    """Nhà cung cấp tạo-từ-ảnh DÙNG ĐƯỢC (đã cấu hình đủ khoá), hoặc None."""
    try:
        n = ncc_mod.tao(get_env())
    except ncc_mod.LoiNhaCungCap:
        return None
    return n.ten if n else None


@ROUTER.get("", response_model=DanhSachNhanVatOut)
async def liet_ke(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DanhSachNhanVatOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        ds = await repo.liet_ke(conn)
    ten = _ncc_ten()
    return DanhSachNhanVatOut(
        nhanVat=[_out(x) for x in ds],
        dangDung=next((x["id"] for x in ds if x["dang_dung"]), None),
        taoTuAnh=ten is not None,
        nhaCungCap=ten,
        toiDa=so.TOI_DA_MOI_WORKSPACE,
        cauDemo=list(so.CAU_DEMO),
    )


@ROUTER.get("/dang-dung", response_model=DangDungOut)
async def dang_dung(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DangDungOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc_dang_dung(conn)
    if nv is None or nv["trang_thai"] != "san_sang":
        return DangDungOut(id=None, ten=None, avatarId=None, posterUrl=None)
    o = _out(nv)
    return DangDungOut(id=o.id, ten=o.ten, avatarId=o.avatarId, posterUrl=o.posterUrl)


@ROUTER.put("/dang-dung", response_model=DangDungOut)
async def chon(
    body: ChonIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DangDungOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        if body.id is not None:
            nv = await repo.doc(conn, body.id, khoa=True)
            if nv is None:
                raise _khong_co()
            if nv["trang_thai"] != "san_sang":
                raise loi.LoiPortal("NHAN_VAT_CHUA_SAN_SANG", 409, "Nhân vật chưa dựng xong")
        await repo.chon(conn, body.id)
        await nhat_ky.ghi(conn, p.tenant_id, "nhan_vat.chon", p.user_id, {"id": body.id})
    return await dang_dung(p, pool)


def _duoi(ten: str | None) -> str:
    ten = ten or ""
    return ten.rsplit(".", 1)[-1].lower() if "." in ten else ""


async def _doc_tep(tep: UploadFile, loai: dict[str, str], tran: int, nhan: str) -> tuple[bytes, str]:
    duoi = _duoi(tep.filename)
    if duoi not in loai:
        raise loi.LoiPortal("NHAN_VAT_LOAI_TEP", 415, f"{nhan}: chỉ nhận {', '.join(sorted(set(loai)))}")
    noi_dung = await tep.read()
    if not noi_dung:
        raise loi.LoiPortal("NHAN_VAT_TEP_RONG", 400, f"{nhan}: tệp rỗng")
    if len(noi_dung) > tran:
        raise loi.LoiPortal("NHAN_VAT_TEP_QUA_LON", 413, f"{nhan}: tối đa {tran >> 20} MB")
    return noi_dung, duoi


@ROUTER.post("", response_model=NhanVatOut, status_code=status.HTTP_201_CREATED)
async def tao(
    ten: Annotated[str, Form()],
    nguon: Annotated[str, Form()],
    dongY: Annotated[bool, Form()],  # noqa: N803 — tên trường form FE gửi
    tep: Annotated[UploadFile, File()],
    tepTay: Annotated[UploadFile | None, File()] = None,  # noqa: N803
    moTa: Annotated[str | None, Form()] = None,  # noqa: N803
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> NhanVatOut:
    ten = ten.strip()
    if not ten or len(ten) > 60:
        raise loi.LoiPortal("NHAN_VAT_TEN", 422, "Tên nhân vật 1–60 ký tự")
    if not dongY:
        raise loi.LoiPortal(
            "NHAN_VAT_CHUA_DONG_Y", 422, "Cần xác nhận bạn có quyền dùng hình ảnh của người trong video/ảnh"
        )
    if nguon not in ("video", "anh"):
        raise loi.LoiPortal("NHAN_VAT_NGUON", 422, "nguon phải là 'video' hoặc 'anh'")
    if nguon == "anh" and _ncc_ten() is None:
        raise loi.LoiPortal("NHAN_VAT_CHUA_CAU_HINH_AI", 409, so.HUONG_DAN_LOI["CHUA_CAU_HINH_AI"])
    mo_ta = (moTa or "").strip()[:500] or None

    if nguon == "video":
        chinh, duoi = await _doc_tep(tep, so.LOAI_VIDEO, so.VIDEO_MAX_BYTE, "Video")
        tay = await _doc_tep(tepTay, so.LOAI_VIDEO, so.VIDEO_MAX_BYTE, "Video đưa tay") if tepTay else None
    else:
        chinh, duoi = await _doc_tep(tep, so.LOAI_ANH, so.ANH_MAX_BYTE, "Ảnh")
        tay = None

    async with tenant_conn(pool, p.tenant_id) as conn:
        if await repo.dem(conn) >= so.TOI_DA_MOI_WORKSPACE:
            raise loi.LoiPortal(
                "NHAN_VAT_QUA_SO_LUONG", 409, f"Tối đa {so.TOI_DA_MOI_WORKSPACE} nhân vật — xoá bớt nhân vật cũ"
            )
        avatar_id = f"nv-{secrets.token_hex(16)}"
        nv_id = await repo.tao(
            conn,
            ten=ten,
            nguon=nguon,
            trang_thai="dung" if nguon == "video" else "tao_video",
            avatar_id=avatar_id,
            mo_ta=mo_ta,
            anh_key=None,
            video_key=None,
            video_tay_key=None,
            tao_boi=p.user_id,
        )
        kho = kho_tep_tu_cai_dat()
        if nguon == "video":
            k_chinh = jobs.khoa_tep(p.tenant_id, nv_id, f"chinh.{duoi}")
            await kho.ghi(k_chinh, chinh, content_type=so.LOAI_VIDEO[duoi])
            k_tay = None
            if tay:
                k_tay = jobs.khoa_tep(p.tenant_id, nv_id, f"tay.{tay[1]}")
                await kho.ghi(k_tay, tay[0], content_type=so.LOAI_VIDEO[tay[1]])
            await repo.cap_nhat(conn, nv_id, video_key=k_chinh, video_tay_key=k_tay)
        else:
            k_anh = jobs.khoa_tep(p.tenant_id, nv_id, f"anh.{duoi}")
            await kho.ghi(k_anh, chinh, content_type=so.LOAI_ANH[duoi])
            await repo.cap_nhat(conn, nv_id, anh_key=k_anh)
        await jobs.xep_buoc(conn, p.tenant_id, nv_id)
        await nhat_ky.ghi(
            conn,
            p.tenant_id,
            "nhan_vat.tao",
            p.user_id,
            {"id": nv_id, "ten": ten, "nguon": nguon, "dong_y": True, "so_byte": len(chinh)},
        )
        nv = await repo.doc(conn, nv_id)
    return _out(nv)


@ROUTER.get("/{nv_id}", response_model=NhanVatOut)
async def doc(
    nv_id: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> NhanVatOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id)
    if nv is None:
        raise _khong_co()
    return _out(nv)


@ROUTER.post("/{nv_id}/thu-lai", response_model=NhanVatOut)
async def thu_lai(
    nv_id: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> NhanVatOut:
    """Dựng lại sau lỗi. Đã có video (upload, hoặc nhà cung cấp đã sinh xong) ⇒ dựng lại từ
    video đó; nguồn ảnh chưa có video ⇒ gửi lại nhà cung cấp (tốn thêm một lượt API)."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id, khoa=True)
        if nv is None:
            raise _khong_co()
        if nv["trang_thai"] != "loi":
            raise loi.LoiPortal("NHAN_VAT_DANG_DUNG", 409, "Nhân vật không ở trạng thái lỗi")
        if nv["video_key"]:
            tv = {k: v for k, v in nv["tac_vu"].items() if k != "da_gui_lipsync"}
            await repo.cap_nhat(
                conn,
                nv_id,
                tac_vu=tv,
                trang_thai="dung",
                buoc=None,
                tien_do=0.3,
                loi_ma=None,
                loi_chi_tiet=None,
                xem_truoc=[],
                poster_key=None,
            )
        else:
            await repo.cap_nhat(
                conn,
                nv_id,
                trang_thai="tao_video",
                buoc=None,
                tien_do=0.0,
                loi_ma=None,
                loi_chi_tiet=None,
                tac_vu={},
            )
        await jobs.xep_buoc(conn, p.tenant_id, nv_id)
        await nhat_ky.ghi(conn, p.tenant_id, "nhan_vat.thu_lai", p.user_id, {"id": nv_id})
        nv = await repo.doc(conn, nv_id)
    return _out(nv)


@ROUTER.post("/{nv_id}/xem-truoc")
async def xem_truoc_cau(
    nv_id: str,
    body: XemTruocIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """Nhân vật nói thử một câu tuỳ ý — mp4 trả thẳng, không lưu (vài giây GPU)."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id)
    if nv is None:
        raise _khong_co()
    if nv["trang_thai"] not in ("xem_truoc", "san_sang"):
        raise loi.LoiPortal("NHAN_VAT_CHUA_SAN_SANG", 409, "Nhân vật chưa dựng xong")
    try:
        mp4 = await LipsyncClient(get_env()).xem_truoc(nv["avatar_id"], body.cau.strip(), so.NEN_XEM_TRUOC)
    except LoiLipsync as e:
        raise loi.LoiPortal("NHAN_VAT_XEM_TRUOC_LOI", 502, "Không tạo được video xem trước — thử lại sau") from e
    return Response(content=mp4, media_type="video/mp4", headers={"Cache-Control": "no-store"})


async def _phat(khoa: str | None, media_type: str) -> Response:
    if not khoa:
        raise _khong_co()
    try:
        noi_dung = await kho_tep_dung_chung().doc(khoa)
    except KhongTimThay as e:
        raise _khong_co() from e
    return Response(content=noi_dung, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@ROUTER.get("/{nv_id}/poster")
async def poster(
    nv_id: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id)
    if nv is None:
        raise _khong_co()
    return await _phat(nv["poster_key"], "image/png")


@ROUTER.get("/{nv_id}/xem-truoc/{i}")
async def video_xem_truoc(
    nv_id: str,
    i: int,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id)
    if nv is None or not (0 <= i < len(nv["xem_truoc"])):
        raise _khong_co()
    return await _phat(nv["xem_truoc"][i]["key"], "video/mp4")


@ROUTER.get("/{nv_id}/video/{loai}")
async def video_nguon(
    nv_id: str,
    loai: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """Video nguồn (`chinh` | `tay`) — đọc thẳng tệp job đã lưu vào kho lúc tải video AI về
    (bước bắt buộc để gửi sang lipsync), nên không thêm việc gì vào quá trình tạo nhân vật."""
    if loai not in ("chinh", "tay"):
        raise _khong_co()
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id)
    if nv is None:
        raise _khong_co()
    khoa = nv["video_key"] if loai == "chinh" else nv["video_tay_key"]
    return await _phat(khoa, jobs.mime_theo_khoa(khoa) if khoa else "video/mp4")


@ROUTER.delete("/{nv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa(
    nv_id: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """Xoá hàng + tệp trong kho + nhân vật trên lipsync (job dọn — service có thể đang dựng
    nó). Đang được dùng ⇒ tab Voice tự về người dẫn mặc định."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        nv = await repo.doc(conn, nv_id, khoa=True)
        if nv is None:
            raise _khong_co()
        await repo.xoa(conn, nv_id)
        await enqueue(
            conn, tenant_id=p.tenant_id, kind=so.KIND_DON, actor=p.user_id, payload={"avatar_id": nv["avatar_id"]}
        )
        await nhat_ky.ghi(conn, p.tenant_id, "nhan_vat.xoa", p.user_id, {"id": nv_id, "ten": nv["ten"]})
    kho = kho_tep_tu_cai_dat()
    for khoa in await kho.liet_ke(jobs.khoa_tep(p.tenant_id, nv_id, "")):
        await kho.xoa(khoa)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
