"""Nghiệp vụ M3: suy trạng thái pod, đọc và lưu cấu hình agent theo role.

Từ `0966` KHÔNG còn bản nháp · xem trước · xuất bản · quay lui. Bấm Lưu là ghi thẳng
`tenant_data.agent_config` (một hàng mỗi role) và agent thấy ở hội thoại kế tiếp. Xem
`agent_config.py` cho ba luật của bảng đó.

Từ `0967` tập role là DỮ LIỆU (`tenant_data.role_config`): `customer` luôn có và không xoá
được, các role khác workspace tự thêm/đổi tên/xoá (`tao_role` · `sua_role` · `xoa_role`).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import asyncpg
from pydantic import ValidationError

NGUONG_MAT_KET_NOI = timedelta(seconds=60)
"""Ba lượt nhịp tim lỡ (chu kỳ 20s).

Không phải 20s: một gói tin rớt không được biến thành báo động, vì báo động sai
vài lần là người dùng thôi tin cái chip trạng thái — và lúc mất kết nối thật thì
không ai nhìn nữa.
"""


class TrangThaiAgent(StrEnum):
    """Chip trạng thái của AG_01 §II.3 — SUY TỪ AGENT ĐANG CHẠY, không phải cờ
    trong portal. Một cột `status` trong DB là bản sao thứ hai của sự thật, và
    bản sao thì có ngày lệch mà không ai biết bản nào đúng."""

    DANG_CAP = "dang_cap"
    DANG_AP_DUNG = "dang_ap_dung"
    SAN_SANG = "san_sang"
    MAT_KET_NOI = "mat_ket_noi"


@dataclass(frozen=True)
class Heartbeat:
    running_version: int | None
    bundle_sha: str
    last_seen_at: datetime


def tinh_trang_thai_agent(hb: Heartbeat | None, live_version: int | None, bay_gio: datetime) -> TrangThaiAgent:
    """Trạng thái pod. `bay_gio` là tham số, KHÔNG phải now() bên trong.

    `live_version` là `agent_config.version` hiện tại của tenant (hai hàng cùng số).

    THỨ TỰ KIỂM QUAN TRỌNG: mất kết nối thắng thế đang-áp-dụng. Agent chết ngay
    sau khi lưu thì nhịp tim đứng ở version cũ mãi mãi; hiện Đang áp dụng là hứa
    một thứ sẽ không bao giờ tới.
    """
    if hb is None:
        return TrangThaiAgent.DANG_CAP
    if bay_gio - hb.last_seen_at > NGUONG_MAT_KET_NOI:
        return TrangThaiAgent.MAT_KET_NOI
    if hb.running_version != live_version:
        return TrangThaiAgent.DANG_AP_DUNG
    return TrangThaiAgent.SAN_SANG


# ─── So hai cấu hình — HÀM THUẦN ─────────────────────────────────────────────


def truong_da_doi(moi, cu) -> list[str]:
    """Đường dẫn của những trường khác nhau, ví dụ `danh_tinh.ten_agent`.

    Nhật ký hoạt động ghi danh sách này (BR15). `cu is None` (role chưa từng lưu, hoặc hàng
    cũ không còn đọc được) ⇒ rỗng.
    """
    if cu is None:
        return []
    return sorted(_khac(moi.model_dump(), cu.model_dump()))


def _khac(a: dict, b: dict, tien_to: str = "") -> list[str]:
    ket: list[str] = []
    for khoa in sorted(set(a) | set(b)):
        duong = f"{tien_to}{khoa}"
        va, vb = a.get(khoa), b.get(khoa)
        if isinstance(va, dict) and isinstance(vb, dict):
            ket += _khac(va, vb, f"{duong}.")
        elif va != vb:
            ket.append(duong)
    return ket


def _tom_tat_loi_validate(e: ValidationError) -> str:
    """`ValidationError.errors()` → `"tools.enabled: kỹ năng không tồn tại: x"`."""
    return "; ".join(f"{'.'.join(str(p) for p in loi['loc'])}: {loi['msg']}" for loi in e.errors())


# ─── Đọc ─────────────────────────────────────────────────────────────────────


class CauHinhDaLuuKhongHopLe(Exception):
    """Hàng đã lưu không còn validate được bằng `ConfigPayload` hôm nay — ví dụ
    `skills` còn tên kỹ năng đã gỡ khỏi sổ (sự cố `aina_test` 2026-09-10).

    Router dịch thành 409, KHÔNG trả bộ mặc định: trả mặc định là mời người dùng bấm Lưu
    và GHI ĐÈ dữ liệu thật (danh tính/phạm vi/giọng/TTS) bằng mặc định.
    """

    def __init__(self, role: str, thong_diep: str) -> None:
        super().__init__(f"{role}: {thong_diep}")
        self.role = role
        self.thong_diep = thong_diep


@dataclass(frozen=True)
class RoleDoc:
    key: str
    ten: str
    icon: str | None
    cau_hinh: object  # ConfigPayload
    la_mac_dinh: bool  # True: role này chưa từng lưu, đây là bộ platform sinh


@dataclass(frozen=True)
class CauHinhDoc:
    vai_tro: list[RoleDoc]  # theo thứ tự tab
    version: int | None  # None: tenant chưa lưu lần nào


async def doc_cau_hinh(conn: asyncpg.Connection, tenant_id: str, ten_workspace: str) -> CauHinhDoc:
    """Cấu hình của MỌI role trong `role_config`. Role chưa có hàng ⇒ bộ mặc định (`laMacDinh`).

    LUÔN trả ít nhất `customer` (trigger `0967` tạo nó cùng tenant): workspace mới nào cũng
    gặp ca chưa cấu hình, và một thông báo đỏ ở lần mở đầu là sai (AG_01 bước 2).
    """
    from portal.modules.config import agent_config, role_config
    from portal.modules.config.contracts import SCHEMA_VERSION_HIEN_TAI, ConfigPayload, payload_mac_dinh

    roles = await role_config.liet_ke(conn, tenant_id)
    da_luu = await agent_config.doc(conn, tenant_id, SCHEMA_VERSION_HIEN_TAI)
    vai_tro: list[RoleDoc] = []
    for r in roles:
        h = da_luu.get(r.key)
        if h is None:
            vai_tro.append(RoleDoc(r.key, r.ten, r.icon, payload_mac_dinh(ten_workspace), True))
            continue
        try:
            cfg = ConfigPayload.model_validate(h.payload)
        except ValidationError as e:
            raise CauHinhDaLuuKhongHopLe(r.ten, _tom_tat_loi_validate(e)) from e
        vai_tro.append(RoleDoc(r.key, r.ten, r.icon, cfg, False))

    version = max((h.version for h in da_luu.values()), default=None)
    return CauHinhDoc(vai_tro=vai_tro, version=version)


# ─── Lưu ─────────────────────────────────────────────────────────────────────


class CauHinhSchemaCu(Exception):
    """Payload gửi lên khai `schema_version` khác số hiện hành. Router dịch thành 409.

    Phải kiểm TƯỜNG MINH: `ConfigPayload.schema_version` là int trần, một payload mang
    tên trường v3 mà khai `2` vẫn validate được.
    """

    def __init__(self, role: str, schema_version: int) -> None:
        super().__init__(f"{role}: schema_version {schema_version}")
        self.role = role
        self.schema_version = schema_version


class DanhSachRoleDaDoi(Exception):
    """Tập role trong body khác tập role đang có. Router dịch thành 409 — màn đang mở đã cũ
    (tab khác vừa thêm/xoá role), tải lại rồi Lưu lại."""

    def __init__(self, thieu: list[str], thua: list[str]) -> None:
        super().__init__(f"thiếu {thieu}, thừa {thua}")
        self.thieu = thieu
        self.thua = thua


async def _khoa_tenant(conn: asyncpg.Connection, tenant_id: str) -> None:
    """KHOÁ TƯ VẤN THEO TENANT, dùng chung cho Lưu và mọi thao tác role: cả hai đọc-rồi-ghi
    `version` và tập role. Mang tenant_id nên chỉ xếp hàng các thao tác CỦA CÙNG tenant.
    `_xact_`: tự nhả khi giao dịch kết thúc, kể cả khi vỡ — bản không-xact rò khoá theo
    connection trong pool."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('portal.config_luu'), hashtext($1))", tenant_id)


async def luu_cau_hinh(conn: asyncpg.Connection, tenant_id: str, moi: dict, actor: str) -> tuple[int, dict]:
    """Ghi MỌI role trong MỘT giao dịch. Trả `(version, {role: trường đã đổi})`.

    `moi` là `{key: ConfigPayload}`; tập khoá phải trùng ĐÚNG tập role đang có — kiểm SAU
    khi giữ khoá, để một lần thêm/xoá role song song không lọt vào giữa.

    Một giao dịch cho mọi hàng: FE đặt chung một số trường cho mọi tab; lưu được role này mà
    role kia lỗi là các hàng lệch nhau ở đúng những trường người dùng tin là "chung".
    """
    from portal.core import nhat_ky
    from portal.modules.config import agent_config, role_config
    from portal.modules.config.contracts import SCHEMA_VERSION_HIEN_TAI, ConfigPayload

    for key, cfg in moi.items():
        if cfg.schema_version != SCHEMA_VERSION_HIEN_TAI:
            raise CauHinhSchemaCu(key, cfg.schema_version)

    async with conn.transaction():
        await _khoa_tenant(conn, tenant_id)

        dang_co = [r.key for r in await role_config.liet_ke(conn, tenant_id)]
        if set(moi) != set(dang_co):
            raise DanhSachRoleDaDoi(sorted(set(dang_co) - set(moi)), sorted(set(moi) - set(dang_co)))

        cu = await agent_config.doc(conn, tenant_id, SCHEMA_VERSION_HIEN_TAI)
        da_doi: dict = {}
        for key in dang_co:
            ban_cu = None
            if key in cu:
                # Hàng cũ không đọc được (kỹ năng đã gỡ…) ⇒ coi như chưa có: lần Lưu này
                # CHÍNH LÀ cách sửa nó, không được chặn bằng 409.
                try:
                    ban_cu = ConfigPayload.model_validate(cu[key].payload)
                except ValidationError:
                    ban_cu = None
            da_doi[key] = truong_da_doi(moi[key], ban_cu)

        version = await agent_config.version_tiep_theo(conn, tenant_id)
        for key in dang_co:
            await agent_config.luu(conn, tenant_id, key, moi[key], version)

        # Cùng giao dịch: lưu hỏng thì không có dòng nhật ký nói là đã lưu.
        await nhat_ky.ghi(conn, tenant_id, "agent_config.luu", actor, {"version": version, "truong_da_doi": da_doi})
    return version, da_doi


# ─── Role ────────────────────────────────────────────────────────────────────


class RoleKhongTonTai(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class RoleTenDaDung(Exception):
    def __init__(self, ten: str) -> None:
        super().__init__(ten)
        self.ten = ten


class RoleQuaGioiHan(Exception):
    pass


class RoleMacDinhKhongXoa(Exception):
    pass


@dataclass(frozen=True)
class RoleDaGhi:
    key: str
    ten: str
    icon: str | None


async def tao_role(
    conn: asyncpg.Connection,
    tenant_id: str,
    ten: str,
    sao_chep_tu: str | None,
    actor: str,
    icon: str | None = None,
) -> RoleDaGhi:
    """Thêm role. `key` sinh từ `ten` (bất biến sau đó). `sao_chep_tu` ⇒ chép hàng cấu hình
    của role đó (nguồn chưa lưu lần nào thì role mới cũng dùng bộ mặc định như nguồn)."""
    from portal.core import nhat_ky
    from portal.modules.config import agent_config, role_config
    from portal.modules.config.contracts import SO_ROLE_TOI_DA

    async with conn.transaction():
        await _khoa_tenant(conn, tenant_id)
        roles = await role_config.liet_ke(conn, tenant_id)
        if len(roles) >= SO_ROLE_TOI_DA:
            raise RoleQuaGioiHan()
        if sao_chep_tu is not None and sao_chep_tu not in {r.key for r in roles}:
            raise RoleKhongTonTai(sao_chep_tu)
        if ten.casefold() in {r.ten.strip().casefold() for r in roles}:
            raise RoleTenDaDung(ten)

        key = role_config.key_tu_ten(ten, {r.key for r in roles})
        thu_tu = max((r.thu_tu for r in roles), default=-1) + 1
        try:
            async with conn.transaction():
                await role_config.them(conn, tenant_id, key, ten, icon, thu_tu)
        except asyncpg.UniqueViolationError:
            # `lower()` của Postgres và `casefold()` của Python lệch nhau ở vài ký tự hiếm —
            # index là trọng tài cuối.
            raise RoleTenDaDung(ten) from None

        if sao_chep_tu is not None:
            await agent_config.chep_hang(conn, tenant_id, sao_chep_tu, key)
        version = await agent_config.tang_version(conn, tenant_id)
        await nhat_ky.ghi(
            conn,
            tenant_id,
            "role_config.tao",
            actor,
            {"key": key, "ten": ten, "icon": icon, "sao_chep_tu": sao_chep_tu, "version": version},
        )
    return RoleDaGhi(key, ten, icon)


async def sua_role(
    conn: asyncpg.Connection, tenant_id: str, key: str, ten: str | None, icon: str | None, actor: str
) -> RoleDaGhi:
    """Đổi tên và/hoặc icon. `key` không đổi, hàng cấu hình không bị chạm."""
    from portal.core import nhat_ky
    from portal.modules.config import agent_config, role_config

    async with conn.transaction():
        await _khoa_tenant(conn, tenant_id)
        try:
            async with conn.transaction():
                cu = await role_config.sua(conn, tenant_id, key, ten, icon)
        except asyncpg.UniqueViolationError:
            raise RoleTenDaDung(ten or "") from None
        if cu is None:
            raise RoleKhongTonTai(key)
        moi = RoleDaGhi(key, ten if ten is not None else cu.ten, icon if icon is not None else cu.icon)
        if (moi.ten, moi.icon) != (cu.ten, cu.icon):
            # Tên là thứ agent có thể đọc (nó nhận role qua hội thoại) ⇒ tăng version như
            # mọi thay đổi tập role. Icon chỉ là của màn hình nhưng đi cùng một lần lưu.
            version = await agent_config.tang_version(conn, tenant_id) if moi.ten != cu.ten else None
            await nhat_ky.ghi(
                conn,
                tenant_id,
                "role_config.sua",
                actor,
                {"key": key, "ten": [cu.ten, moi.ten], "icon": [cu.icon, moi.icon], "version": version},
            )
    return moi


async def xoa_role(conn: asyncpg.Connection, tenant_id: str, key: str, actor: str) -> None:
    """Xoá role + hàng cấu hình của nó (FK cascade). `customer` không xoá được — trigger
    `0967` cũng chặn, kiểm ở đây để trả 409 có nghĩa thay vì 500."""
    from portal.core import nhat_ky
    from portal.modules.config import agent_config, role_config
    from portal.modules.config.contracts import KEY_ROLE_MAC_DINH

    if key == KEY_ROLE_MAC_DINH:
        raise RoleMacDinhKhongXoa()
    async with conn.transaction():
        await _khoa_tenant(conn, tenant_id)
        ten = await role_config.xoa(conn, tenant_id, key)
        if ten is None:
            raise RoleKhongTonTai(key)
        version = await agent_config.tang_version(conn, tenant_id)
        await nhat_ky.ghi(conn, tenant_id, "role_config.xoa", actor, {"key": key, "ten": ten, "version": version})
