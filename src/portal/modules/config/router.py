"""Endpoint của M3. Mọi route khai `require(action)` — cổng 1 của M2a.

`tenant_id` LUÔN lấy từ `Principal` (đã xác thực qua membership), KHÔNG từ path
param hay body. `tenant_data.agent_config` có RLS + FORCE (`0956`) nên mọi route mở
`tenant_conn()` — vẫn không thay được việc lấy `tenant_id` đúng chỗ.

Từ `0966`: không còn `/draft` · `/preview` · `/publish` · `/versions` · `/rollback` — bấm
Lưu (`PUT /config`) là áp dụng ngay cho MỌI role. Từ `0967`: role là dữ liệu của tenant,
thêm/đổi tên/xoá qua `/config/roles` (`customer` không xoá được).
"""

from datetime import UTC, datetime

import asyncpg
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.config import repo, service
from portal.modules.config.contracts import (
    KEY_ROLE_MAC_DINH,
    SO_ROLE_TOI_DA,
    LuuCauHinhIn,
    SuaRoleIn,
    TaoRoleIn,
)

ROUTER = APIRouter(prefix="/config", tags=["config"])
"""KHÔNG có `/api/v1` ở đây — `create_app()` thêm tiền tố đó lúc include_router."""


def _schema_cu(role: str, so: int) -> loi.LoiPortal:
    return loi.LoiPortal(
        "CONFIG_SCHEMA_CU",
        409,
        f"Cấu hình {role} khai schema_version {so}, khác bản hiện hành — tải lại màn hình rồi Lưu lại",
    )


def _da_luu_khong_hop_le(role: str, chi_tiet: str) -> loi.LoiPortal:
    """409, KHÔNG trả bộ mặc định — xem `service.CauHinhDaLuuKhongHopLe`."""
    return loi.LoiPortal(
        "CONFIG_DA_LUU_KHONG_HOP_LE",
        409,
        f"Cấu hình {role} đang lưu không còn hợp lệ — cần dọn dữ liệu ({chi_tiet})",
    )


class VaiTroOut(BaseModel):
    key: str
    """Bất biến — là thứ `agent_config.role` lưu. Dùng làm khoá của `PUT /config`."""
    ten: str
    """Tên hiển thị (tab), đổi được."""
    icon: str | None
    """Mã icon của tab (FE giữ bảng mã → hình). None = FE tự chọn theo `key`."""
    macDinh: bool
    """True = role mặc định (`customer`): luôn có, không xoá được."""
    cauHinh: dict
    laMacDinh: bool
    """True = role này chưa từng được lưu, `cauHinh` là bộ platform sinh."""


class CauHinhOut(BaseModel):
    """Cấu hình của MỌI role, theo thứ tự tab. LUÔN có ít nhất role mặc định."""

    vaiTro: list[VaiTroOut]
    version: int | None
    """`agent_config.version` hiện tại (mọi role cùng số). None = chưa lưu lần nào."""
    soRoleToiDa: int


class RoleOut(BaseModel):
    key: str
    ten: str
    icon: str | None
    macDinh: bool


class LuuOut(BaseModel):
    version: int
    """Số vừa ghi — agent dựng lại runner khi thấy số này đổi."""
    truongDaDoi: dict[str, list[str]]
    """Theo role: trường nào khác so với bản đang lưu trước đó."""


class TrangThaiOut(BaseModel):
    trangThaiAgent: str
    """Chip 4 giá trị của AG_01 §II.3, SUY từ nhịp tim agent gửi lên."""
    version: int | None


async def _ten_workspace(conn: asyncpg.Connection, tenant_id: str) -> str:
    return await conn.fetchval("SELECT name FROM control.tenants WHERE id = $1", tenant_id) or tenant_id


def _cau_hinh_out(d: service.CauHinhDoc) -> CauHinhOut:
    return CauHinhOut(
        vaiTro=[
            VaiTroOut(
                key=r.key,
                ten=r.ten,
                icon=r.icon,
                macDinh=r.key == KEY_ROLE_MAC_DINH,
                cauHinh=r.cau_hinh.model_dump(),
                laMacDinh=r.la_mac_dinh,
            )
            for r in d.vai_tro
        ],
        version=d.version,
        soRoleToiDa=SO_ROLE_TOI_DA,
    )


def _role_out(r: service.RoleDaGhi) -> RoleOut:
    return RoleOut(key=r.key, ten=r.ten, icon=r.icon, macDinh=r.key == KEY_ROLE_MAC_DINH)


def _role_khong_ton_tai(key: str) -> loi.LoiPortal:
    return loi.LoiPortal("ROLE_KHONG_TON_TAI", 404, f"Không có role «{key}» — có thể vừa bị xoá ở tab khác")


def _role_ten_da_dung(ten: str) -> loi.LoiPortal:
    return loi.LoiPortal("ROLE_TEN_DA_DUNG", 409, f"Đã có role tên «{ten}»")


@ROUTER.get("", response_model=CauHinhOut)
async def doc_cau_hinh(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CauHinhOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            d = await service.doc_cau_hinh(conn, p.tenant_id, await _ten_workspace(conn, p.tenant_id))
        except service.CauHinhDaLuuKhongHopLe as e:
            raise _da_luu_khong_hop_le(e.role, e.thong_diep) from None
    return _cau_hinh_out(d)


@ROUTER.put("", response_model=LuuOut)
async def luu_cau_hinh(
    body: LuuCauHinhIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> LuuOut:
    """Lưu = áp dụng ngay. FastAPI validate bằng `LuuCauHinhIn` — 422 cho payload sai.

    Validate Ở ĐÂY chứ không chỉ ở FE: cảnh báo phụ thuộc kỹ năng chỉ có ở FE là cảnh
    báo bỏ qua được bằng một `curl` (AG_01, cổng 6 của M5).
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            version, da_doi = await service.luu_cau_hinh(conn, p.tenant_id, body.cauHinh, actor=p.user_id)
        except service.CauHinhSchemaCu as e:
            raise _schema_cu(e.role, e.schema_version) from None
        except service.DanhSachRoleDaDoi:
            raise loi.LoiPortal(
                "CONFIG_ROLE_DA_DOI",
                409,
                "Danh sách role vừa thay đổi ở nơi khác — tải lại màn hình rồi Lưu lại",
            ) from None
    return LuuOut(version=version, truongDaDoi=da_doi)


@ROUTER.get("/status", response_model=TrangThaiOut)
async def doc_trang_thai(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangThaiOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hb = await repo.doc_heartbeat(conn, p.tenant_id)
        version = await repo.version_hien_tai(conn, p.tenant_id)
    return TrangThaiOut(
        trangThaiAgent=service.tinh_trang_thai_agent(hb, live_version=version, bay_gio=datetime.now(UTC)),
        version=version,
    )


@ROUTER.post("/roles", response_model=RoleOut, status_code=201)
async def tao_role(
    body: TaoRoleIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> RoleOut:
    """Thêm role. Áp dụng ngay (agent thấy role mới ở hội thoại kế tiếp)."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            r = await service.tao_role(conn, p.tenant_id, body.ten, body.saoChepTu, actor=p.user_id, icon=body.icon)
        except service.RoleQuaGioiHan:
            raise loi.LoiPortal(
                "ROLE_QUA_GIOI_HAN", 409, f"Mỗi workspace tối đa {SO_ROLE_TOI_DA} role — xoá bớt role không dùng"
            ) from None
        except service.RoleKhongTonTai as e:
            raise _role_khong_ton_tai(e.key) from None
        except service.RoleTenDaDung as e:
            raise _role_ten_da_dung(e.ten) from None
    return _role_out(r)


@ROUTER.patch("/roles/{key}", response_model=RoleOut)
async def sua_role(
    key: str,
    body: SuaRoleIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> RoleOut:
    """Đổi tên và/hoặc icon. `key` không đổi — hàng cấu hình không bị chạm."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            r = await service.sua_role(conn, p.tenant_id, key, body.ten, body.icon, actor=p.user_id)
        except service.RoleKhongTonTai as e:
            raise _role_khong_ton_tai(e.key) from None
        except service.RoleTenDaDung as e:
            raise _role_ten_da_dung(e.ten) from None
    return _role_out(r)


@ROUTER.delete("/roles/{key}", status_code=204)
async def xoa_role(
    key: str,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """Xoá role CÙNG cấu hình của nó. Role mặc định (`customer`) ⇒ 409."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            await service.xoa_role(conn, p.tenant_id, key, actor=p.user_id)
        except service.RoleMacDinhKhongXoa:
            raise loi.LoiPortal("ROLE_MAC_DINH", 409, "Role mặc định (Khách hàng) không xoá được") from None
        except service.RoleKhongTonTai as e:
            raise _role_khong_ton_tai(e.key) from None
    return Response(status_code=204)
