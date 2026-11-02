# src/portal/modules/playbook/router.py
"""Màn Kịch bản: định nghĩa nút + số đo G1 (G3), bản riêng của workspace (đợt 2)."""

from __future__ import annotations

import json
import logging
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.config.contracts import bao_agent_doi
from portal.modules.playbook import kich_ban, kiem, nut, repo
from portal.modules.playbook.contracts import (
    ApDungIn,
    KichBanOut,
    LuotNutItemOut,
    LuotNutOut,
    LuuKichBanIn,
    MucDemOut,
    PlaybookOut,
    RoleDungIn,
    SoDoNutOut,
    TemplateOut,
)

logger = logging.getLogger(__name__)
ROUTER = APIRouter(tags=["playbook"])


def _ngay_hop_le(v: int) -> int:
    # Literal[7, 30, 90] từ chuỗi query bị pydantic (lax) từ chối → 422 cả giá trị hợp lệ; kiểm tay.
    if v not in (7, 30, 90):
        raise ValueError("ngay phải là 7, 30 hoặc 90")
    return v


Ngay = Annotated[int, Query(), AfterValidator(_ngay_hop_le)]
_NGUON_Q = Query(None)
_DAT_Q = Query(None)
_LIMIT_Q = Query(20, ge=1, le=50)


def _bo_nut() -> dict:
    try:
        return nut.doc()
    except RuntimeError:
        logger.error("playbook.json không đọc được", exc_info=True)
        raise loi.LoiPortal("PLAYBOOK_DATA", 500, "Dữ liệu kịch bản hỏng — lỗi deploy") from None


def _ti_le(tu: int, mau: int) -> float | None:
    return round(tu / mau, 4) if mau else None


def _muc(ds) -> list[MucDemOut]:
    return [MucDemOut(ten=t, so=s) for t, s in ds]


_DA_DOI = ("PLAYBOOK_DA_DOI", 409, "Kịch bản vừa thay đổi ở nơi khác — tải lại rồi lưu lại")


def _json(v):
    return json.loads(v) if isinstance(v, str) else v


def _nut_sale(hang) -> list[dict]:
    """Lớp sale đang chạy, khuôn lưu: bản riêng hoặc template."""
    if hang is None or hang["nut"] is None:
        return [nut.chuan_hoa(j) for j in nut.template_sale()]
    return _json(hang["nut"])


def _nodes_hien(bo: dict, hang) -> list[dict]:
    """Bộ nút workspace đang chạy, hình dạng playbook.json: hệ thống (JSON) ∪ sale (DB hoặc JSON)."""
    if hang is None or hang["nut"] is None:
        return bo["nodes"]
    return [nut.tuong_thich(d) for d in _json(hang["nut"])] + nut.he_thong()


def _kich_ban_out(hang, bo: dict) -> KichBanOut:
    tv = bo["templateVersion"]
    if hang is None:
        return KichBanOut(
            trangThai="mau",
            version=0,
            tuTemplate=None,
            templateVersion=tv,
            coTemplateMoi=False,
            roleDung=["customer"],
            capNhatLuc=None,
            capNhatBoi=None,
        )
    rieng = hang["nut"] is not None
    return KichBanOut(
        trangThai="rieng" if rieng else "mau",
        version=hang["version"],
        tuTemplate=hang["tu_template"],
        templateVersion=tv,
        coTemplateMoi=rieng and hang["tu_template"] != tv,
        roleDung=list(hang["role_dung"]),
        capNhatLuc=hang["updated_at"],
        capNhatBoi=hang["updated_by"],
    )


@ROUTER.get("/playbook", response_model=PlaybookOut)
async def xem_playbook(
    ngay: Ngay = 7,
    nguon: str | None = _NGUON_Q,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> PlaybookOut:
    bo = _bo_nut()
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await kich_ban.doc(conn)
        nodes = _nodes_hien(bo, hang)
        r = await repo.so_do(
            conn, ngay=ngay, nguon=nguon, v=bo["promptVersion"], hash_nut={n["id"]: n["hash"] for n in nodes}
        )
    ids = {n["id"] for n in nodes}
    so_do, nut_cu = {}, {}
    for k, t in r["theo_nut"].items():
        if k not in ids:
            nut_cu[k] = t["so_luot"]
            continue
        so_do[k] = SoDoNutOut(
            soLuot=t["so_luot"],
            daCham=t["da_cham"],
            dat=t["dat"],
            tiLeDat=_ti_le(t["dat"], t["da_cham"]),
            thieuDuLieu=_ti_le(t["thieu_du_lieu"], t["so_luot"]) or 0.0,
            hayThieu=_muc(r["hay_thieu"].get(k, [])),
            hayPham=_muc(r["hay_pham"].get(k, [])),
            jevSo=t["jev_so"],
            jevKhop=_ti_le(t["jev_khop"], t["jev_so"]),
        )
    return PlaybookOut(
        version=bo["version"],
        promptVersion=bo["promptVersion"],
        nodes=nodes,
        soDo=so_do,
        nutCu=nut_cu,
        phienBanCu=r["phien_ban_cu"],
        nguon=r["nguon"],
        coDuLieu=r["co_du_lieu"],
        kichBan=_kich_ban_out(hang, bo),
    )


def _ds(p: dict, k: str) -> list[str]:
    v = p.get(k)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


@ROUTER.get("/playbook/{ma_nut}/luot", response_model=LuotNutOut)
async def luot_cua_nut(
    ma_nut: str,
    ngay: Ngay = 7,
    nguon: str | None = _NGUON_Q,
    dat: bool | None = _DAT_Q,
    limit: int = _LIMIT_Q,
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> LuotNutOut:
    bo = _bo_nut()
    async with tenant_conn(pool, p.tenant_id) as conn:
        h = {n["id"]: n["hash"] for n in _nodes_hien(bo, await kich_ban.doc(conn))}.get(ma_nut)
        if h is None:
            return LuotNutOut(luot=[])
        rows = await repo.luot_cua_nut(
            conn,
            nut=ma_nut,
            ngay=ngay,
            nguon=nguon,
            v=bo["promptVersion"],
            h=h,
            chi_khong_dat=dat is False,
            limit=limit,
        )
    out = []
    for r in rows:
        pb = r["p"] if isinstance(r["p"], dict) else json.loads(r["p"])
        out.append(
            LuotNutItemOut(
                sessionId=r["session_id"],
                seq=r["seq"],
                phone=r["phone"],
                taoLuc=r["created_at"],
                khach=r["khach"],
                agent=r["agent"],
                dat=pb.get("dat") if isinstance(pb.get("dat"), bool) else None,
                thieu=_ds(pb, "thieu"),
                viPhamCam=_ds(pb, "vi_pham_cam"),
                thieuDuLieu=pb.get("thieu_du_lieu") is True,
                buoc=pb.get("buoc") if isinstance(pb.get("buoc"), str) else None,
                jevNut=pb.get("jev_nut") if isinstance(pb.get("jev_nut"), str) else None,
            )
        )
    return LuotNutOut(luot=out)


@ROUTER.get("/playbook/template", response_model=TemplateOut)
async def xem_template(p: Principal = require(ACTIONS.AGENT_CONFIG_READ)) -> TemplateOut:
    bo = _bo_nut()
    return TemplateOut(templateVersion=bo["templateVersion"], nodes=nut.template_sale(), gioiHan=nut.gioi_han())


@ROUTER.post("/playbook/ap-dung", response_model=KichBanOut)
async def ap_dung(
    body: ApDungIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> KichBanOut:
    """Chép lớp sale template thành bản riêng — lần đầu hay áp lại (ghi đè) cùng một đường."""
    bo = _bo_nut()
    mau = [nut.chuan_hoa(j) for j in nut.template_sale()]
    async with tenant_conn(pool, p.tenant_id) as conn:
        cu = await kich_ban.doc(conn)
        try:
            hang = await kich_ban.ghi(
                conn,
                p.tenant_id,
                version=body.version,
                actor=p.user_id,
                nut=mau,
                tu_template=bo["templateVersion"],
                ghi_de_template=True,
            )
        except kich_ban.DaDoi:
            raise loi.LoiPortal(*_DA_DOI) from None
        await bao_agent_doi(conn, p.tenant_id)
        await nhat_ky.ghi(
            conn,
            p.tenant_id,
            "playbook.ap_dung",
            p.user_id,
            {
                "version": hang["version"],
                "tuTemplate": bo["templateVersion"],
                "apLai": cu is not None and cu["nut"] is not None,
            },
        )
    return _kich_ban_out(hang, bo)


@ROUTER.put("/playbook", response_model=KichBanOut)
async def luu_kich_ban(
    body: LuuKichBanIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> KichBanOut:
    """Lưu cả lớp sale. Chưa áp dụng ⇒ coi như áp dụng (tu_template = template hiện tại)."""
    bo = _bo_nut()
    moi = [n.model_dump() for n in body.nut]
    sai = kiem.kiem_bo(moi)
    if sai:
        raise RequestValidationError(
            [{"loc": ("body", "nut", *loc), "msg": msg, "type": "value_error"} for loc, msg in sai]
        )
    async with tenant_conn(pool, p.tenant_id) as conn:
        cu = {d["id"]: nut.bam_nut(d) for d in _nut_sale(await kich_ban.doc(conn))}
        try:
            hang = await kich_ban.ghi(
                conn, p.tenant_id, version=body.version, actor=p.user_id, nut=moi, tu_template=bo["templateVersion"]
            )
        except kich_ban.DaDoi:
            raise loi.LoiPortal(*_DA_DOI) from None
        await bao_agent_doi(conn, p.tenant_id)
        sau = {d["id"]: nut.bam_nut(d) for d in moi}
        await nhat_ky.ghi(
            conn,
            p.tenant_id,
            "playbook.luu",
            p.user_id,
            {
                "version": hang["version"],
                "them": sorted(sau.keys() - cu.keys()),
                "sua": sorted(k for k in sau.keys() & cu.keys() if sau[k] != cu[k]),
                "xoa": sorted(cu.keys() - sau.keys()),
            },
        )
    return _kich_ban_out(hang, bo)


@ROUTER.put("/playbook/role-dung", response_model=KichBanOut)
async def dat_role_dung(
    body: RoleDungIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> KichBanOut:
    bo = _bo_nut()
    roles = list(dict.fromkeys(body.roles))
    async with tenant_conn(pool, p.tenant_id) as conn:
        la = sorted(set(roles) - await kich_ban.role_co(conn))
        if la:
            raise loi.LoiPortal("PLAYBOOK_ROLE_KHONG_CO", 422, f"Role không có trong workspace: {', '.join(la)}")
        try:
            hang = await kich_ban.ghi(conn, p.tenant_id, version=body.version, actor=p.user_id, role_dung=roles)
        except kich_ban.DaDoi:
            raise loi.LoiPortal(*_DA_DOI) from None
        await bao_agent_doi(conn, p.tenant_id)
        await nhat_ky.ghi(
            conn, p.tenant_id, "playbook.role_dung", p.user_id, {"version": hang["version"], "roles": roles}
        )
    return _kich_ban_out(hang, bo)
