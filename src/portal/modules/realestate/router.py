"""Endpoint của module realestate — CRUD 5 thực thể theo cây anchor (Task 4).

Nguồn sự thật: `docs/build_module_knowledgebase/mau-form-cms.html` (hình dạng form,
6 tab) + `02-knowledge-base.md` §2/§3 (anchor, `__ALL__`, cascade status) +
`02a-real-estate-template.md` §4 (field từng bảng). `repo.py`/`contracts.py`
(Task 3) đã đóng — module này CHỈ gọi hàm đã có, không viết lại SQL ghi (whitelist
cột, ON CONFLICT, RETURNING đã ở `repo.py`).

HAI LUẬT UX TỪ FORM QUYẾT ĐỊNH HÌNH DẠNG ĐƯỜNG DẪN:
  1. Con (`zones`/`units`/`documents`/`media`) KẾ THỪA `project_code` từ dự án
     đang mở trên CMS — người dùng không nhập lại. Vì vậy `project_code` nằm
     TRÊN ĐƯỜNG DẪN (`/projects/{project_code}/...`), không trong thân request:
     các `*In`/`*Patch` bên dưới KHÔNG có field `projectCode`.
  2. Ảnh cover/mặt bằng (`projects`/`zones`): user upload 1 ảnh → hệ tạo 1 row
     `media` đúng `category` rồi gán `cover_media_id`/`map_media_id` = id row đó.
     MỘT thao tác người dùng, HAI lần ghi, MỘT giao dịch — `tenant_conn()` đã mở
     transaction cho cả khối `async with` (xem `core/db/session.py`), nên chỉ
     cần cả hai lần ghi nằm trong CÙNG một khối là đủ, không cần tự quản thêm.

ĐƯỜNG DẪN THEO CODE VS THEO ID — quyết định có chủ ý, khác brief gốc ở 1 chỗ:
  - `projects`/`zones` định danh bằng BUSINESS CODE trên URL (`project_code`/
    `zone_code`) vì cả hai có UNIQUE constraint thật ở DB — path đọc được, thân
    thiện agent/CMS. Router tự tra `id` (`_tim_du_an`/`_tim_phan_khu`) rồi mới
    gọi `repo.sua_*`/`xoa_*` (hai hàm đó CHỈ nhận `id`, xem `repo.py`).
  - `units`/`documents`/`media` định danh bằng `id` (surrogate) trên URL, KHÔNG
    dùng `unit_code`: `contracts.py` ghi rõ lý do — `units.unit_code` KHÔNG
    unique (`02a §4.3`, dữ liệu nhập tay có thể trùng mã giữa đợt nhập), nên
    "sửa/xoá căn có mã X" là một câu hỏi mơ hồ (căn nào trong nhiều căn trùng
    mã?). `id` là định danh DUY NHẤT không mơ hồ cho cả 3 bảng này — FE dùng
    `id` trả về ở GET/list để gọi PATCH/DELETE, đúng như `contracts.py` đã dặn.

KHÔNG lưu trường nội bộ nhạy cảm (`02 §1`) — module này không có cơ chế che
field nào, và không nên có: field nhạy cảm đơn giản không có mặt trong `COT_*`
của `contracts.py`, nên không đường ghi nào ở đây chèn được chúng vào request.
"""

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any, Literal

import asyncpg
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue
from portal.core.ma_ban_ghi import can_derive_code, candidate_code, next_project_code, next_zone_code
from portal.modules.kb.contracts import (
    DEFAULT_DOC_TYPE,
    KIND_CAPTION_PREVIEW,
    KIND_DELETE_INDEX,
    KIND_ENRICH,
    KIND_SYNC_PROJECT,
    dat_viec_doi_co,
    dat_viec_doi_nhan,
    dat_viec_nap,
    dat_viec_thumb,
    enqueue_web_project,
    enqueue_web_purge,
    join_title,
    split_caption,
    split_title,
)
from portal.modules.realestate import repo
from portal.modules.realestate.completeness import cot_cua, thieu_truong
from portal.modules.realestate.contracts import (
    GIOI_HAN_OFFSET,
    GIOI_HAN_TRANG,
    SENTINEL_TENANT,
    TRANG_MAC_DINH,
    CanOut,
    DuAnOut,
    FacetCan,
    HangMucBanGiao,
    KbStatusOut,
    LoiConTro,
    MediaOut,
    PhanKhuOut,
    TaiLieuOut,
    ToaOut,
    TrangCan,
    TrangDuAn,
    TrangMedia,
    TrangPhanKhu,
    TrangTaiLieu,
    TrangToa,
    ma_con_tro,
)

ROUTER = APIRouter(tags=["realestate"])
"""KHÔNG có prefix chung — `api/app.py` gắn `/api/v1`, xem `TIEN_TO`."""


# ─── Lỗi module ──────────────────────────────────────────────────────────────


def _du_an_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("PROJECT_NOT_FOUND", 404, "Không tìm thấy dự án")


def _phan_khu_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("ZONE_NOT_FOUND", 404, "Không tìm thấy phân khu")


def _can_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("UNIT_NOT_FOUND", 404, "Không tìm thấy căn")


def _toa_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("BUILDING_NOT_FOUND", 404, "Không tìm thấy toà")


def _toa_con_can(so_can: int) -> loi.LoiPortal:
    return loi.LoiPortal(
        "BUILDING_HAS_UNITS", 409, f"Toà còn {so_can} căn — chuyển các căn sang toà khác trước khi xoá"
    )


def _media_khong_hop_le() -> loi.LoiPortal:
    return loi.LoiPortal("MEDIA_NOT_FOUND", 422, "Ảnh mặt bằng không thuộc workspace này")


def _tai_lieu_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("DOCUMENT_NOT_FOUND", 404, "Không tìm thấy tài liệu")


def _media_khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("MEDIA_NOT_FOUND", 404, "Không tìm thấy media")


def _thieu_ten_du_an() -> loi.LoiPortal:
    """Không có `projectCode` tường minh VÀ `name` không sinh ra được mã.

    KHÔNG tự đúc `DA_1`: mã là bất biến, nên một mã vô nghĩa là thứ người dùng
    phải mang vĩnh viễn. Frontend hỏi đúng một ô «Dự án này tên gì?» ở đúng lúc.
    """
    return loi.LoiPortal("PROJECT_NAME_REQUIRED", 422, "Cần tên dự án để sinh mã — hoặc gửi projectCode tường minh")


def _thieu_ten_phan_khu() -> loi.LoiPortal:
    return loi.LoiPortal("ZONE_NAME_REQUIRED", 422, "Cần tên phân khu để sinh mã — hoặc gửi zoneCode tường minh")


def _trung_ma(ten: str) -> loi.LoiPortal:
    return loi.LoiPortal("DUPLICATE_CODE", 409, f"Mã {ten} đã tồn tại trong dự án này")


def _con_tro_khong_hop_le() -> loi.LoiPortal:
    return loi.LoiPortal("INVALID_CURSOR", 422, "Con trỏ phân trang không hợp lệ")


def _sentinel_duoc_bao_ve(viec: str) -> loi.LoiPortal:
    """`__ALL__` là ROW HỆ THỐNG, không phải dự án — ba thao tác dưới đây phải bị
    TỪ CHỐI, không phải "tình cờ không ai làm" (review vòng cuối, Critical A).

    Sáu task trước đều COI `__ALL__` là "row luôn `published`" và PHỤ THUỘC vào
    điều đó — `_bo_qua_completeness_du_an` (miễn completeness vì nó không bao giờ
    đủ trường), `scripts/seed_bds.py` (seed `status='published'`),
    `0401_agent_doc_kb.py` (bốn view con cascade tài liệu/media chung QUA nó), và
    `repo.liet_ke_tai_lieu_cho_agent`/`liet_ke_media_cho_agent` (JOIN qua nó,
    không có nhánh SQL riêng cho sentinel). KHÔNG chỗ nào cưỡng chế, nên ba
    request HTTP hoàn toàn bình thường phá được toàn bộ tri thức cấp tenant:
      - `PATCH /projects/__ALL__ {"status":"draft"}` → cascade `status` ẩn SẠCH
        tài liệu + media chung khỏi mọi câu trả lời của agent (cascade lẽ ra bảo
        vệ cây, ở đây thành vũ khí).
      - `DELETE /projects/__ALL__` → `ON DELETE CASCADE` XOÁ HẲN tài liệu chung,
        và anchor mất nên `POST /projects/__ALL__/documents` 404 vĩnh viễn tới
        khi ai đó chạy lại `make seed-bds`.
      - `POST /projects {"projectCode":"__ALL__"}` → bất kỳ ai có `CATALOG_WRITE`
        cũng chiếm/tạo lại được row hệ thống với dữ liệu tuỳ ý.
    Cả ba tới được DO VÔ TÌNH: `GET /projects` (trước bản sửa này) liệt kê
    `__ALL__` như một dự án bình thường, tên "Chung / toàn tenant", có nút Xoá
    ngay bên cạnh — nên nó cũng bị ẩn khỏi `liet_ke_du_an` (xem `repo.py`).

    409 (KHÔNG 403, KHÔNG 500): đây không phải chuyện thiếu quyền — không role
    nào, kể cả admin, được làm ba việc này qua API; nó là XUNG ĐỘT với một bất
    biến của hệ thống ("`__ALL__` tồn tại và luôn published"), cùng họ với
    `DUPLICATE_CODE` 409. Mã riêng `SENTINEL_PROTECTED` để FE hiện được đúng
    thông điệp thay vì một 500 không đọc nổi.

    Đường ghi DUY NHẤT cho row này là provisioning (`scripts/seed_bds.py`).
    """
    return loi.LoiPortal(
        "SENTINEL_PROTECTED",
        409,
        f"{SENTINEL_TENANT!r} là dự án hệ thống (tài liệu/media dùng chung toàn tenant neo vào nó) — "
        f"không {viec} được qua API",
    )


def _thieu_du_lieu(truong: list[str]) -> loi.LoiPortal:
    """`02 §3`: *"chặn publish + badge UI"*. Kèm TÊN TRƯỜNG còn thiếu trong thông
    điệp — người biên tập phải biết THIẾU GÌ để sửa, không chỉ "không được"."""
    return loi.LoiPortal("INCOMPLETE_DATA", 422, f"Thiếu dữ liệu bắt buộc để publish: {', '.join(truong)}")


def _kiem_completeness(entity: str, ban_ghi: dict) -> None:
    """Lõi DÙNG CHUNG cho CẢ hai đường ghi (POST tạo mới lẫn PATCH sửa) — MỘT
    luật, không hai bản lệch nhau.

    Review vòng 3 (Finding Important): bản trước chỉ áp completeness ở PATCH,
    brief viết *"PATCH .../{code} với status=published"* — nhưng đó là brief
    viết THIẾU, không phải quyết định thiết kế. `02 §3` nói *"chặn publish +
    badge UI"* KHÔNG kèm điều kiện đường vào nào, và `POST /projects
    {"status":"published"}` (đường tạo phổ biến nhất) tái hiện được lỗ này
    100%: 201, dự án sinh ra đã `published` mà `region`/`overview` rỗng. Tài
    liệu là nguồn sự thật, brief chỉ diễn giải nó — chỗ lệch thì tài liệu
    thắng, nên gate phải áp CẢ HAI đường, cùng một hàm, để không có nguy cơ
    một đường được sửa mà đường kia bị quên."""
    thieu = thieu_truong(entity, ban_ghi)
    if thieu:
        raise _thieu_du_lieu(thieu)


def _chan_publish_thieu(entity: str, hang: asyncpg.Record, payload: dict) -> None:
    """PATCH — `02 §3` + `02a §7` (luật ở `completeness.py`): PATCH đưa `status`
    thành `published` mà bản ghi thiếu trường bắt buộc thì CHẶN.

    Kiểm trên bản ghi ĐÃ GỘP (`hang` cũ + `payload` mới), KHÔNG chỉ riêng
    `payload`: PATCH có thể chỉ gửi `{"status": "published"}` trong khi các
    trường bắt buộc đã có giá trị từ TRƯỚC đó (một PATCH riêng), hoặc ngược lại
    gửi đủ field bắt buộc CÙNG lúc với `status` — cả hai trường hợp phải cho
    cùng một kết quả đúng, nên phải xét trạng thái CUỐI CÙNG của bản ghi, không
    phải mỗi phần vừa gửi.

    CHỈ áp khi bản ghi SẮP thành `published` — `02a §7` chỉ định nghĩa "đủ để
    publish", draft/archived không bị ràng buộc completeness (một dự án nháp
    thiếu `overview` là bình thường, đang soạn dở).

    ⚠️ VÀ CHỈ ÁP KHI PATCH THẬT SỰ CHẠM TỚI VIỆC PHÁT HÀNH (spec 2026-08-21
    §3.5.2). Bản trước chặn theo trạng thái CUỐI, nên với một bản ghi ĐÃ
    `published` thì **mọi** PATCH đi qua cổng — kể cả PATCH chỉ sửa một ô không
    thuộc cổng. Với luật hai trường điều đó chưa nổ; lượt siết lên năm trường làm
    20/94 dự án published trên Aurora dev trả 422 ở MỌI lần sửa, tức người biên
    tập bị khoá ngoài đúng dự án họ cần điền nốt. Cùng chế độ hỏng mà
    `_bo_qua_completeness_du_an` đã ghi cho `__ALL__`.

    Hai vế, thiếu vế nào cũng hở một chiều:
      · `status` đang chuyển THÀNH `published` ⇒ kiểm. Đây là hành động phát hành.
      · bản ghi đã `published` và payload CHẠM một trường của cổng ⇒ kiểm. Không
        có vế này thì một PATCH xoá trắng `overview` của dự án đang published đi
        lọt, và cổng thành thứ chỉ gác lúc vào cửa.
    """
    trang_thai_cu = hang["status"]
    trang_thai_moi = payload.get("status", trang_thai_cu)
    if trang_thai_moi != "published":
        return
    dang_phat_hanh = trang_thai_cu != "published"
    # `cot_cua` chứ không `BAT_BUOC`: nhóm một-trong (diện tích) là tuple, và đem tuple
    # đi so với khoá chuỗi của payload thì luôn sai mà không lỗi nào phát ra.
    cham_cong = any(truong in payload for truong in cot_cua(entity))
    if not (dang_phat_hanh or cham_cong):
        return
    gop = {**dict(hang), **payload}
    _kiem_completeness(entity, gop)


def _chan_tao_moi_thieu(entity: str, ban_ghi_moi: dict) -> None:
    """POST — cùng luật `_chan_publish_thieu`, khác chỗ KHÔNG có hàng cũ để
    gộp: bản ghi cuối cùng chính là `body.model_dump()` (đầy đủ, KHÔNG
    `exclude_unset`) — Pydantic đã điền default TRÙNG KHỚP default của DB cho
    field vắng mặt (`ProjectIn`/`UnitIn` tự khai rõ: *"Field dưới đây là NOT
    NULL DEFAULT '' ở DB... default ở đây CHỈ để field được phép vắng mặt"*),
    nên `body.model_dump()` phản ánh ĐÚNG giá trị sẽ được INSERT mà không cần
    đọc lại DB.

    CHỈ áp khi bản ghi MỚI ngay từ đầu đã `published` — tạo `draft` thiếu dữ
    liệu vẫn là chuyện bình thường (`02a §7` chỉ định nghĩa "đủ để publish")."""
    if ban_ghi_moi.get("status") != "published":
        return
    _kiem_completeness(entity, ban_ghi_moi)


def _bo_qua_completeness_du_an(project_code: str) -> bool:
    """`__ALL__` (`SENTINEL_TENANT`) là 1 ROW HỆ THỐNG (`02 §2`/`02a §4b`), không
    phải một dự án thật — nó KHÔNG có `region`/`overview` (chỉ là điểm neo FK cho
    tài liệu/media cấp tenant) và LUÔN `published` kể từ lúc seed provisioning
    (`scripts/seed_bds.py`). Nếu áp `_chan_publish_thieu` như một dự án bình
    thường, MỌI PATCH sau đó lên `__ALL__` (kể cả chỉ sửa một field không liên
    quan) sẽ bị 422 vĩnh viễn — vì `status` hiện tại của nó đã là `published`
    trong khi `region`/`overview` không bao giờ được điền. Thoát KHỎI luật
    completeness một cách tường minh ở đây, không phải vì nó "tình cờ" luôn đủ."""
    return project_code == SENTINEL_TENANT


_FK_KHONG_TON_TAI: dict[str, loi.LoiPortal] = {
    "zones_tenant_project_fk": _du_an_khong_thay(),
    "units_tenant_project_fk": _du_an_khong_thay(),
    "units_tenant_zone_fk": _phan_khu_khong_thay(),
    "documents_tenant_project_fk": _du_an_khong_thay(),
    "media_tenant_project_fk": _du_an_khong_thay(),
    "media_tenant_zone_fk": _phan_khu_khong_thay(),
    "buildings_tenant_project_fk": _du_an_khong_thay(),
    "buildings_tenant_zone_fk": _phan_khu_khong_thay(),
    "units_layout_media_fk": _media_khong_hop_le(),
}


def _loi_fk(e: asyncpg.ForeignKeyViolationError) -> loi.LoiPortal:
    """`chen_*` của con (zone/unit/document/media) raise lỗi này khi `project_code`
    (hoặc `zone_code` với unit/media) trên đường dẫn không khớp hàng cha nào —
    kiểm tra "cha có tồn tại" xảy ra Ở CHÍNH constraint FK, TRONG CÙNG câu INSERT,
    nên KHÔNG có khoảng hở giữa "kiểm tra" và "ghi" (không cần SELECT riêng rồi
    tin nó vẫn đúng lúc INSERT chạy)."""
    return _FK_KHONG_TON_TAI.get(e.constraint_name or "", _du_an_khong_thay())


# ─── Nhật ký ─────────────────────────────────────────────────────────────────


async def _nhat_ky(conn: asyncpg.Connection, p: Principal, hanh_dong: str, chi_tiet: dict) -> None:
    """BR13 — cổng `test_nhat_ky_day_du.py` quét AST đòi MỌI route ghi gọi hàm
    này SAU KHI việc đã xong (không ghi trước, xem docstring `core/nhat_ky.py`)."""
    await nhat_ky.ghi(conn, p.tenant_id, hanh_dong, p.user_id, chi_tiet)


def _status_changed(hang: asyncpg.Record, payload: dict) -> bool:
    """Đổi `status` sang giá trị khác. Cả hai chiều: công bố cũng phải đổi cờ point."""
    moi = payload.get("status")
    return bool(moi) and moi != hang["status"]


async def _enqueue_index(
    conn: asyncpg.Connection, p: Principal, *, entity: str, record_id: int, project_code: str
) -> None:
    await dat_viec_nap(
        conn, tenant_id=p.tenant_id, actor=p.user_id, entity=entity, record_id=record_id, project_code=project_code
    )


_FIELDS_NO_REINDEX = frozenset({"status", "name", "cover_media_id", "map_media_id"})


async def _enqueue_project_change(
    conn: asyncpg.Connection, p: Principal, *, hang: asyncpg.Record, payload: dict, project_code: str
) -> None:
    """Ba nhánh rời nhau: đổi cờ và đổi nhãn KHÔNG nhúng lại gì, chỉ cập nhật payload.

    Field ngoài hai cái đó thì đặt việc nạp mà không cần biết nó có được nhúng hay không —
    dấu tay nội dung là cổng thật, field không nhúng chỉ tốn một lượt đọc rồi thoát sớm.
    """
    ten_cu = str(hang["name"] or "")
    doi_ten = bool(payload.get("name")) and payload["name"] != hang["name"]
    con_published = payload.get("status", hang["status"]) == "published"
    if _status_changed(hang, payload):
        await dat_viec_doi_co(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
        if payload["status"] == "published":
            await enqueue_web_project(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
        elif hang["status"] == "published":
            await enqueue_web_purge(conn, tenant_id=p.tenant_id, actor=p.user_id, project_name=ten_cu)
    if doi_ten:
        # Hồ sơ dữ liệu ngoài khoá theo TÊN: dọn bản của tên cũ, dựng bản mới theo tên mới.
        await enqueue_web_purge(conn, tenant_id=p.tenant_id, actor=p.user_id, project_name=ten_cu)
        if con_published:
            await enqueue_web_project(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
    if payload.get("name") and payload["name"] != hang["name"]:
        await dat_viec_doi_nhan(
            conn,
            tenant_id=p.tenant_id,
            actor=p.user_id,
            project_code=project_code,
            ten_cu=str(hang["name"] or ""),
        )
    if set(payload) - _FIELDS_NO_REINDEX:
        await _enqueue_index(conn, p, entity="projects", record_id=int(hang["id"]), project_code=project_code)


async def _enqueue_document_change(
    conn: asyncpg.Connection,
    p: Principal,
    *,
    record_id: int,
    project_code: str,
    file_moi: bool,
    ghi_de: bool = False,
    tu_duyet: bool = False,
) -> None:
    """Có tệp ⇒ thumb → bóc chữ → nạp, nối tuần tự. Không tệp thì nạp thẳng."""
    if file_moi:
        await dat_viec_thumb(
            conn,
            tenant_id=p.tenant_id,
            actor=p.user_id,
            entity="documents",
            record_id=record_id,
            project_code=project_code,
            ghi_de=ghi_de,
            tu_duyet=tu_duyet,
        )
        return
    await _enqueue_index(conn, p, entity="documents", record_id=record_id, project_code=project_code)


async def _sync_tour_360(
    conn: asyncpg.Connection, p: Principal, *, project_code: str, link: str, ten_du_an: str
) -> None:
    """`projects.link_360` thành một hàng `media` `tour_360`, rồi đặt việc cho nó."""
    moi, da_xoa = await repo.sync_tour_360(conn, p.tenant_id, project_code=project_code, link=link, ten_du_an=ten_du_an)
    if moi is not None:
        await _enqueue_index(conn, p, entity="media", record_id=moi, project_code=project_code)
    if da_xoa is not None:
        await _enqueue_purge_record(conn, p, entity="media", record_id=da_xoa)


async def _enqueue_thumb(conn: asyncpg.Connection, p: Principal, *, ids: list[int], project_code: str) -> None:
    """Việc thumb TỰ nối sang việc nạp khi xong — đặt song song thì nạp có thể chạy
    trước và point mang khoá thumb rỗng."""
    for mid in ids:
        await dat_viec_thumb(
            conn, tenant_id=p.tenant_id, actor=p.user_id, entity="media", record_id=mid, project_code=project_code
        )


async def _enqueue_purge_project(conn: asyncpg.Connection, p: Principal, *, project_code: str) -> None:
    """Worker đọc sổ theo `project_code` nên xếp job SAU khi row đã bị cascade xoá
    vẫn đúng."""
    await enqueue(
        conn,
        tenant_id=p.tenant_id,
        kind=KIND_DELETE_INDEX,
        actor=p.user_id,
        payload={"vertical": "real_estate", "anchor_code": project_code},
    )


async def _enqueue_purge_record(conn: asyncpg.Connection, p: Principal, *, entity: str, record_id: int) -> None:
    """KHÔNG khai `doc_type`: row đã xoá nên không suy được loại từ nội dung. Bỏ trống
    thì worker tra sổ và xoá đúng những loại đang tồn tại."""
    await enqueue(
        conn,
        tenant_id=p.tenant_id,
        kind=KIND_DELETE_INDEX,
        actor=p.user_id,
        payload={"vertical": "real_estate", "entity": entity, "record_id": record_id},
    )


async def _enqueue_purge_zone(
    conn: asyncpg.Connection, p: Principal, *, project_code: str, zone_id: int, media_ids: list[int]
) -> None:
    """Phân khu không còn point riêng — xoá nó là NẠP LẠI dự án. Media neo vào nó vẫn phải
    purge từng cái: worker chỉ cascade theo `anchor_code`, không theo zone.

    `record_id=0` ở lời gọi nạp là cố ý: `dat_viec_nap` tra id dự án từ `project_code` rồi
    thay cả hai.

    VẪN purge point `phan_khu` của chính phân khu này: workspace chưa chạy
    `portal.cli.drop_zone_points` còn point loại đó, và nạp lại dự án không chạm chúng —
    thiếu vế này thì phân khu đã xoá vẫn sống trong KB. Vô hại khi không còn point: worker
    tra `kb_index_state`, không có dòng thì không xoá gì.
    """
    await _enqueue_index(conn, p, entity="zones", record_id=0, project_code=project_code)
    await _enqueue_purge_record(conn, p, entity="zones", record_id=zone_id)
    for mid in media_ids:
        await _enqueue_purge_record(conn, p, entity="media", record_id=mid)


# ─── Phân trang keyset — `repo.py` KHÔNG sinh `nextCursor`, dựng ở đây ─────

_LIMIT_Q = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG)
"""Singleton mức module — `Query(...)` gọi trong default là B008 (ruff); đây là
default TÍNH MỘT LẦN lúc import rồi dùng lại, không phải mutable state dùng
chung giữa các request."""

_OFFSET_Q = Query(0, ge=0, le=GIOI_HAN_OFFSET)
"""Singleton mức module, cùng lý do `_LIMIT_Q`. Dùng chung cho cả năm endpoint
danh sách (`/projects`, `/zones`, `/units`, `/documents`, `/media`).

`le=GIOI_HAN_OFFSET` (I-1, review vòng cuối): trước đây chỉ `ge=0`, kẹp DƯỚI mà
không kẹp TRÊN — khác hẳn `_LIMIT_Q` kẹp cả hai đầu. `?offset=99999999999999999999`
qua lọt Pydantic (Python int không tràn), rồi vỡ ở `asyncpg` khi bind tham số
`bigint` (`DataError: value out of int64 range`) — và vì `api/loi.py` không có
handler catch-all, lỗi đó nổi lên thành 500 kèm stack trace thay vì 422 có cấu
trúc. `le` chặn NGAY ở biên HTTP, trước khi câu SQL nào chạy."""


def _cursor_neu_offset(cursor: str | None, offset: int) -> str | None:
    """`offset` (điều hướng theo trang số) ghi đè `cursor` (điều hướng theo con
    trỏ) khi cả hai được truyền cùng lúc — dùng chung cho bốn endpoint danh sách
    không có điều kiện huỷ cursor nào khác ngoài `offset` (`/units` có thêm
    `sort` nên tự xử lý riêng, không dùng hàm này)."""
    return None if offset else cursor


def _xin_du_phong(lim: int) -> int:
    """Số hàng router XIN repo cho một trang `lim` hàng — `lim + 1` (dư 1 để
    biết còn trang sau), trừ khi `lim` đã chạm trần `GIOI_HAN_TRANG`, lúc đó
    xin đúng trần (không xin dư được nữa, xem docstring phía trên)."""
    return min(lim + 1, GIOI_HAN_TRANG)


def _trang(hang: list[asyncpg.Record], lim: int, xin: int) -> tuple[list[asyncpg.Record], str | None]:
    """`hang` là kết quả repo trả cho `LIMIT xin`. `len(hang) >= xin` (nhận ĐỦ
    số đã xin — không thể nhiều hơn, SQL `LIMIT xin` đảm bảo) ⇒ có thể còn
    trang sau: cắt về đúng `lim` phần tử, `nextCursor` mã hoá từ `id` của phần
    tử thứ `lim` (0-index `lim - 1`) — cùng một công thức đúng cho cả hai
    trường hợp `xin == lim + 1` (chính xác tuyệt đối) lẫn `xin == lim ==
    GIOI_HAN_TRANG` (bảo thủ, xem docstring phía trên)."""
    if len(hang) >= xin:
        return list(hang[:lim]), ma_con_tro(hang[lim - 1]["id"])
    return list(hang), None


# ─── Tra cứu theo business code (path dùng code, `repo.sua_*`/`xoa_*` cần id) ──


async def _tim_du_an(conn: asyncpg.Connection, project_code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = $1",
        project_code,
    )


async def _tim_phan_khu(conn: asyncpg.Connection, project_code: str, zone_code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT z.*, {repo.SO_CAN_CUA_PHAN_KHU} FROM tenant_data.zones z "
        "WHERE z.tenant_id = portal.current_tenant() AND z.project_code = $1 AND z.zone_code = $2",
        project_code,
        zone_code,
    )


# ─── DTO → response (Record snake_case → *Out camelCase, xem contracts.py) ──


def _ra_du_an(r: asyncpg.Record) -> DuAnOut:
    return DuAnOut(
        id=r["id"],
        projectCode=r["project_code"],
        name=r["name"],
        category=list(r["category"]),
        region=r["region"],
        address=r["address"],
        investor=r["investor"],
        developer=r["developer"],
        totalLandAreaM2=r["total_land_area_m2"],
        floorAreaM2=r["floor_area_m2"],
        buildDensityPct=r["build_density_pct"],
        productScale=r["product_scale"],
        amenities=r["amenities"],
        ownershipForm=r["ownership_form"],
        handoverStandard=_doc_ban_giao(r["handover_standard"]),
        totalInvestmentVnd=r["total_investment_vnd"],
        salePhase=r["sale_phase"],
        overview=r["overview"],
        link360=r["link_360"],
        coverMediaId=r["cover_media_id"],
        mapMediaId=r["map_media_id"],
        status=r["status"],
        createdAt=r["created_at"],
        updatedAt=r["updated_at"],
        totalUnits=r["total_units"],
        numBuildings=r["num_buildings"],
        managementFeeVndM2=r["management_fee_vnd_m2"],
        parkingCarFeeVnd=r["parking_car_fee_vnd"],
        parkingMotoFeeVnd=r["parking_moto_fee_vnd"],
    )


def _doc_ban_giao(v: str | list | None) -> list[HangMucBanGiao]:
    """jsonb tới dạng chuỗi (pool không đăng ký codec json)."""
    if v is None:
        return []
    return [HangMucBanGiao.model_validate(h) for h in (json.loads(v) if isinstance(v, str) else v)]


def _ghi_ban_giao(payload: dict) -> None:
    """Danh sách hạng mục → jsonb. Chuỗi (FE cũ) có chữ thì thành một hạng mục, rỗng thì NULL."""
    if "handover_standard" not in payload:
        return
    v = payload["handover_standard"]
    if isinstance(v, str):
        v = [{"item": "Tiêu chuẩn chung", "note": v.strip()}] if v.strip() else []
    payload["handover_standard"] = json.dumps(v, ensure_ascii=False) if v else None


def _ra_phan_khu(r: Mapping[str, Any]) -> PhanKhuOut:
    return PhanKhuOut.model_validate(dict(r))


def _ra_can(r: asyncpg.Record) -> CanOut:
    return CanOut.model_validate(dict(r))


def _ra_toa(r: asyncpg.Record) -> ToaOut:
    return ToaOut.model_validate(dict(r))


def _ra_tai_lieu(r: asyncpg.Record) -> TaiLieuOut:
    loai, tieu_de = split_title(r["title"])
    return TaiLieuOut(
        id=r["id"],
        projectCode=r["project_code"],
        loai=loai,
        title=tieu_de,
        body=r["body"] or r["body_auto"],
        fileUrl=r["file_url"],
        bodyChoDuyet=bool(r["body_cho_duyet"]),
        status=r["status"],
        createdAt=r["created_at"],
        updatedAt=r["updated_at"],
    )


def _ra_media(r: asyncpg.Record) -> MediaOut:
    return MediaOut(
        id=r["id"],
        projectCode=r["project_code"],
        zoneCode=r["zone_code"],
        unitCode=r["unit_code"],
        contentType=r["content_type"],
        category=r["category"],
        caption=r["caption"] or split_caption(r["caption_auto"] or "")[0],
        fileName=r["file_name"],
        mediaUrl=r["media_url"],
        thumbUrl=r["thumb_url"],
        contentHash=r["content_hash"],
        uploadedBy=r["uploaded_by"],
        status=r["status"],
        createdAt=r["created_at"],
        updatedAt=r["updated_at"],
    )


_Status = Literal["draft", "published", "archived"]
_LoaiHinhDuAn = Literal["chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong"]
"""`projects.category`/`zones.category` — cùng danh sách giá trị (`02a §3`),
khác số lượng chọn: project là `list[_LoaiHinhDuAn]` ([N]), zone là một giá trị
([1])."""
_SalePhase = Literal["sap_mo_ban", "dang_ban", "ban_giao", "dong_gio_hang"]
_ProductType = Literal[
    "chung_cu",
    "studio",
    "duplex",
    "penthouse",
    "officetel",
    "condotel",
    "biet_thu",
    "lien_ke",
    "shophouse",
    "nha_pho",
    "dat_nen",
    "van_phong",
]
_Direction = Literal["dong", "tay", "nam", "bac", "dong_bac", "dong_nam", "tay_bac", "tay_nam"]
_SaleStatus = Literal["available", "booked", "sold"]
_UnitView = Literal[
    "song", "ho", "bien", "cong_vien", "san_golf", "noi_khu", "be_boi", "duong", "thanh_pho", "toa_doi_dien"
]
_HandoverCondition = Literal["tho", "co_ban", "hoan_thien", "full_noi_that"]
_MediaContentType = Literal["image", "video", "tour_360"]
_MediaCategory = Literal["tong_quan", "ngoai_that", "noi_that", "tien_ich", "mat_bang", "vi_tri", "tien_do"]
_LoaiTaiLieu = Literal["csbh", "phap_ly", "huong_dan", "khac"]

# ─── Enum ở ĐƯỜNG ĐỌC — cùng `Literal`, thêm `""` ("không lọc") ─────────────
_LocProductType = _ProductType | Literal[""]
_LocSaleStatus = _SaleStatus | Literal[""]
_LocDirection = _Direction | Literal[""]
_LocStatus = _Status | Literal[""]
_SapXepCan = Literal["", "price_vnd", "bedrooms", "area_built_m2"]
"""Cột sắp xếp được của bảng quỹ căn — `""` = thứ tự mặc định (mới nhất trước).

`Literal` chứ không `str`: FastAPI từ chối 422 ngay ở biên giá trị lạ, nên
whitelist `repo.COT_SAP_XEP_CAN` là lưới thứ hai chứ không phải lưới duy nhất.
Hai danh sách phải khớp nhau."""
_LocMediaCategory = _MediaCategory | Literal[""]
_LocMediaContentType = _MediaContentType | Literal[""]


class MediaUploadIn(BaseModel):
    """Ảnh cover/mặt bằng gửi KÈM form cha (`project`/`zone`) — KHÔNG phải một
    request tới `/media` riêng. `category` KHÔNG phải field ở đây: nó do router
    tự gán theo Ô nào (`coverMedia` → `tong_quan`, `mapMedia` → `mat_bang`, xem
    `02a §3`), không phải điều user chọn — tránh user gán nhầm category qua ô
    cover mà thật ra là ảnh mặt bằng."""

    model_config = ConfigDict(extra="forbid")

    media_url: str = Field(alias="mediaUrl", min_length=1)
    caption: str = Field(default="", alias="caption")
    file_name: str = Field(default="", alias="fileName")
    content_type: _MediaContentType = Field(default="image", alias="contentType")
    thumb_url: str | None = Field(default=None, alias="thumbUrl")
    content_hash: str = Field(default="", alias="contentHash")
    uploaded_by: str | None = Field(default=None, alias="uploadedBy")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_code: str | None = Field(default=None, alias="projectCode")
    """Vắng ⇒ suy từ `name` (spec 2026-08-21 §3.1). Còn nhận tường minh nên
    đường nạp ngoài và mọi client cũ không đổi gì — additive, không breaking."""
    name: str = Field(default="", alias="name")
    category: list[_LoaiHinhDuAn] = Field(default_factory=list, alias="category")
    region: str = Field(default="", alias="region")
    address: str = Field(default="", alias="address")
    investor: str = Field(default="", alias="investor")
    developer: str = Field(default="", alias="developer")
    total_land_area_m2: float | None = Field(default=None, alias="totalLandAreaM2")  # nullable thật ở DB
    floor_area_m2: float | None = Field(default=None, alias="floorAreaM2")
    build_density_pct: float | None = Field(default=None, alias="buildDensityPct")
    product_scale: str = Field(default="", alias="productScale")
    amenities: str = Field(default="", alias="amenities")
    ownership_form: str = Field(default="", alias="ownershipForm")
    handover_standard: list[HangMucBanGiao] | str | None = Field(default=None, alias="handoverStandard")
    total_investment_vnd: int | None = Field(default=None, alias="totalInvestmentVnd")  # nullable thật ở DB
    sale_phase: _SalePhase = Field(default="sap_mo_ban", alias="salePhase")
    overview: str = Field(default="", alias="overview")
    link_360: str = Field(default="", alias="link360")
    status: _Status = Field(default="draft", alias="status")
    total_units: int | None = Field(default=None, alias="totalUnits", ge=0)
    num_buildings: int | None = Field(default=None, alias="numBuildings", ge=0, le=1000)
    management_fee_vnd_m2: float | None = Field(default=None, alias="managementFeeVndM2", ge=0)
    parking_car_fee_vnd: float | None = Field(default=None, alias="parkingCarFeeVnd", ge=0)
    parking_moto_fee_vnd: float | None = Field(default=None, alias="parkingMotoFeeVnd", ge=0)
    cover_media: MediaUploadIn | None = Field(default=None, alias="coverMedia")
    map_media: MediaUploadIn | None = Field(default=None, alias="mapMedia")


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", alias="name")
    category: list[_LoaiHinhDuAn] = Field(default_factory=list, alias="category")
    region: str = Field(default="", alias="region")
    address: str = Field(default="", alias="address")
    investor: str = Field(default="", alias="investor")
    developer: str = Field(default="", alias="developer")
    total_land_area_m2: float | None = Field(default=None, alias="totalLandAreaM2")
    floor_area_m2: float | None = Field(default=None, alias="floorAreaM2")
    build_density_pct: float | None = Field(default=None, alias="buildDensityPct")
    product_scale: str = Field(default="", alias="productScale")
    amenities: str = Field(default="", alias="amenities")
    ownership_form: str = Field(default="", alias="ownershipForm")
    handover_standard: list[HangMucBanGiao] | str | None = Field(default=None, alias="handoverStandard")
    total_investment_vnd: int | None = Field(default=None, alias="totalInvestmentVnd")
    sale_phase: _SalePhase = Field(default="sap_mo_ban", alias="salePhase")
    overview: str = Field(default="", alias="overview")
    link_360: str = Field(default="", alias="link360")
    status: _Status = Field(default="draft", alias="status")
    total_units: int | None = Field(default=None, alias="totalUnits", ge=0)
    num_buildings: int | None = Field(default=None, alias="numBuildings", ge=0, le=1000)
    management_fee_vnd_m2: float | None = Field(default=None, alias="managementFeeVndM2", ge=0)
    parking_car_fee_vnd: float | None = Field(default=None, alias="parkingCarFeeVnd", ge=0)
    parking_moto_fee_vnd: float | None = Field(default=None, alias="parkingMotoFeeVnd", ge=0)
    cover_media: MediaUploadIn | None = Field(default=None, alias="coverMedia")
    map_media: MediaUploadIn | None = Field(default=None, alias="mapMedia")


class ZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_code: str | None = Field(default=None, alias="zoneCode")
    name: str = Field(default="", alias="name")
    category: _LoaiHinhDuAn | None = Field(default=None, alias="category")  # nullable thật ở DB (zones)
    product_scale: str = Field(default="", alias="productScale")
    overview: str = Field(default="", alias="overview")
    status: _Status = Field(default="draft", alias="status")
    sale_phase: _SalePhase | None = Field(default=None, alias="salePhase")
    note: str = Field(default="", alias="note")
    amenities: str = Field(default="", alias="amenities")
    num_buildings: int | None = Field(default=None, alias="numBuildings", ge=0, le=1000)
    total_units: int | None = Field(default=None, alias="totalUnits", ge=0)
    cover_media: MediaUploadIn | None = Field(default=None, alias="coverMedia")
    map_media: MediaUploadIn | None = Field(default=None, alias="mapMedia")


class ZonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", alias="name")
    category: _LoaiHinhDuAn | None = Field(default=None, alias="category")
    product_scale: str = Field(default="", alias="productScale")
    overview: str = Field(default="", alias="overview")
    status: _Status = Field(default="draft", alias="status")
    sale_phase: _SalePhase | None = Field(default=None, alias="salePhase")
    note: str = Field(default="", alias="note")
    amenities: str = Field(default="", alias="amenities")
    num_buildings: int | None = Field(default=None, alias="numBuildings", ge=0, le=1000)
    total_units: int | None = Field(default=None, alias="totalUnits", ge=0)
    cover_media: MediaUploadIn | None = Field(default=None, alias="coverMedia")
    map_media: MediaUploadIn | None = Field(default=None, alias="mapMedia")


class UnitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_code: str = Field(alias="zoneCode", min_length=1)
    unit_code: str = Field(alias="unitCode", min_length=1)
    product_type: _ProductType = Field(alias="productType")
    bedrooms: int | None = Field(default=None, alias="bedrooms", ge=0, le=50)
    block: str | None = Field(default=None, alias="block")
    floor: int | None = Field(default=None, alias="floor", ge=-50, le=300)
    num_floors: int | None = Field(default=None, alias="numFloors", ge=0, le=300)
    direction: _Direction | None = Field(default=None, alias="direction")  # nullable thật ở DB
    area_built_m2: float | None = Field(default=None, alias="areaBuiltM2", ge=0)
    area_wall_m2: float | None = Field(default=None, alias="areaWallM2", ge=0)
    area_land_m2: float | None = Field(default=None, alias="areaLandM2", ge=0)
    price_vnd: float | None = Field(default=None, alias="priceVnd", ge=0)
    price_per_m2_vnd: float | None = Field(default=None, alias="pricePerM2Vnd", ge=0)
    sale_status: _SaleStatus = Field(default="available", alias="saleStatus")
    image_url: str | None = Field(default=None, alias="imageUrl")
    status: _Status = Field(default="draft", alias="status")
    views: list[_UnitView] = Field(default_factory=list, alias="views")
    is_corner: bool | None = Field(default=None, alias="isCorner")
    open_sides: int | None = Field(default=None, alias="openSides", ge=1, le=4)
    bathrooms: int | None = Field(default=None, alias="bathrooms", ge=0, le=50)
    handover_condition: _HandoverCondition | None = Field(default=None, alias="handoverCondition")
    layout_media_id: int | None = Field(default=None, alias="layoutMediaId")
    hr_balcony_m2: float | None = Field(default=None, alias="hrBalconyM2", ge=0)
    hr_loggia_m2: float | None = Field(default=None, alias="hrLoggiaM2", ge=0)
    lr_frontage_m: float | None = Field(default=None, alias="lrFrontageM", ge=0)
    lr_depth_m: float | None = Field(default=None, alias="lrDepthM", ge=0)
    lr_road_width_m: float | None = Field(default=None, alias="lrRoadWidthM", ge=0)


class UnitPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bedrooms: int | None = Field(default=None, alias="bedrooms", ge=0, le=50)
    block: str | None = Field(default=None, alias="block")
    floor: int | None = Field(default=None, alias="floor", ge=-50, le=300)
    num_floors: int | None = Field(default=None, alias="numFloors", ge=0, le=300)
    direction: _Direction | None = Field(default=None, alias="direction")
    area_built_m2: float | None = Field(default=None, alias="areaBuiltM2", ge=0)
    area_wall_m2: float | None = Field(default=None, alias="areaWallM2", ge=0)
    area_land_m2: float | None = Field(default=None, alias="areaLandM2", ge=0)
    price_vnd: float | None = Field(default=None, alias="priceVnd", ge=0)
    price_per_m2_vnd: float | None = Field(default=None, alias="pricePerM2Vnd", ge=0)
    sale_status: _SaleStatus = Field(default="available", alias="saleStatus")
    image_url: str | None = Field(default=None, alias="imageUrl")
    status: _Status = Field(default="draft", alias="status")
    views: list[_UnitView] = Field(default_factory=list, alias="views")
    is_corner: bool | None = Field(default=None, alias="isCorner")
    open_sides: int | None = Field(default=None, alias="openSides", ge=1, le=4)
    bathrooms: int | None = Field(default=None, alias="bathrooms", ge=0, le=50)
    handover_condition: _HandoverCondition | None = Field(default=None, alias="handoverCondition")
    layout_media_id: int | None = Field(default=None, alias="layoutMediaId")
    hr_balcony_m2: float | None = Field(default=None, alias="hrBalconyM2", ge=0)
    hr_loggia_m2: float | None = Field(default=None, alias="hrLoggiaM2", ge=0)
    lr_frontage_m: float | None = Field(default=None, alias="lrFrontageM", ge=0)
    lr_depth_m: float | None = Field(default=None, alias="lrDepthM", ge=0)
    lr_road_width_m: float | None = Field(default=None, alias="lrRoadWidthM", ge=0)


class _BuildingFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_code: str | None = Field(default=None, alias="zoneCode")
    name: str = Field(default="", alias="name")
    num_floors: int | None = Field(default=None, alias="numFloors", ge=0, le=300)
    num_basements: int | None = Field(default=None, alias="numBasements", ge=0, le=20)
    units_per_floor: int | None = Field(default=None, alias="unitsPerFloor", ge=0, le=200)
    elevators_passenger: int | None = Field(default=None, alias="elevatorsPassenger", ge=0, le=100)
    elevators_service: int | None = Field(default=None, alias="elevatorsService", ge=0, le=100)
    car_slots: int | None = Field(default=None, alias="carSlots", ge=0)
    moto_slots: int | None = Field(default=None, alias="motoSlots", ge=0)
    ceiling_height_m: float | None = Field(default=None, alias="ceilingHeightM", gt=0, le=20)
    facing: _Direction | None = Field(default=None, alias="facing")
    sale_phase: _SalePhase | None = Field(default=None, alias="salePhase")
    amenities: str = Field(default="", alias="amenities")
    overview: str = Field(default="", alias="overview")
    status: _Status = Field(default="published", alias="status")


class BuildingIn(_BuildingFields):
    # Phải trùng `units.block` của các căn thuộc toà.
    building_code: str = Field(alias="buildingCode", min_length=1, max_length=50)


class BuildingPatch(_BuildingFields):
    pass


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(alias="title", min_length=1)
    loai: _LoaiTaiLieu = Field(default="khac", alias="loai")
    body: str = Field(default="", alias="body")
    file_url: str | None = Field(default=None, alias="fileUrl")  # nullable thật ở DB
    status: _Status = Field(default="draft", alias="status")
    auto_approve: bool = Field(default=False, alias="autoApprove")


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", alias="title", min_length=1)
    loai: _LoaiTaiLieu = Field(default="khac", alias="loai")
    body: str = Field(default="", alias="body")
    file_url: str | None = Field(default=None, alias="fileUrl")
    status: _Status = Field(default="draft", alias="status")
    auto_approve: bool = Field(default=False, alias="autoApprove")


class MediaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: _MediaContentType = Field(alias="contentType")
    category: _MediaCategory = Field(alias="category")
    media_url: str = Field(alias="mediaUrl", min_length=1)
    zone_code: str | None = Field(default=None, alias="zoneCode")  # nullable thật ở DB
    unit_code: str | None = Field(default=None, alias="unitCode")  # nullable thật ở DB (tham chiếu mềm)
    caption: str = Field(default="", alias="caption")
    file_name: str = Field(default="", alias="fileName")
    thumb_url: str | None = Field(default=None, alias="thumbUrl")
    content_hash: str = Field(default="", alias="contentHash")
    uploaded_by: str | None = Field(default=None, alias="uploadedBy")
    status: _Status = Field(default="draft", alias="status")


class MediaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: _MediaContentType = Field(default="image", alias="contentType")
    category: _MediaCategory = Field(default="tong_quan", alias="category")
    media_url: str = Field(default="", alias="mediaUrl", min_length=1)
    zone_code: str | None = Field(default=None, alias="zoneCode")
    unit_code: str | None = Field(default=None, alias="unitCode")
    caption: str = Field(default="", alias="caption")
    file_name: str = Field(default="", alias="fileName")
    thumb_url: str | None = Field(default=None, alias="thumbUrl")
    content_hash: str = Field(default="", alias="contentHash")
    uploaded_by: str | None = Field(default=None, alias="uploadedBy")
    status: _Status = Field(default="draft", alias="status")


def _tach_payload(body: BaseModel) -> dict:
    """`model_dump(exclude_unset=True)` NHƯNG loại `cover_media`/`map_media` (nếu
    model có hai field đó) — chúng KHÔNG phải cột của bảng cha, xử lý riêng ở
    `_gan_anh_cover_map()`. `auto_approve` cũng vậy — nó là ý định của lời gọi, không phải
    dữ liệu (D22)."""
    return body.model_dump(exclude_unset=True, exclude={"cover_media", "map_media", "auto_approve"})


def _payload_tai_lieu(body: "DocumentIn | DocumentPatch", *, current_title: str | None = None) -> dict:
    """`loai` KHÔNG phải cột — nó nhập vào `title` thành tiền tố trước khi xuống DB.

    PATCH gửi thiếu một trong hai thì lấy nốt phần kia từ hàng hiện có: gửi mỗi
    `title` mà bỏ `loai` cũ sẽ xoá phân loại, gửi mỗi `loai` mà không ghép vào
    `title` thì không còn gì để ghi.
    """
    payload = _tach_payload(body)
    if "loai" not in payload and "title" not in payload:
        return payload
    loai_cu, duoi_cu = split_title(current_title) if current_title is not None else (DEFAULT_DOC_TYPE, "")
    loai = payload.pop("loai", loai_cu)
    payload["title"] = join_title(loai, payload.get("title", duoi_cu))
    return payload


def _payload_media_con(upload: "MediaUploadIn", *, project_code: str, category: str, zone_code: str = "") -> dict:
    """Payload cho `repo.chen_media` từ MỘT ô upload cover/mặt bằng.

    DÙNG `model_dump()` ĐẦY ĐỦ (KHÔNG `exclude_unset`) trên `upload` — khác
    payload của bảng cha: đây là TẠO MỚI một row `media` hoàn chỉnh, không phải
    sửa một phần row có sẵn, nên field user không gửi (vd `contentType`) phải
    lấy ĐÚNG default của `MediaUploadIn` (`"image"`) chứ không được vắng mặt —
    `media.content_type` NOT NULL và KHÔNG có DEFAULT ở DB (migration `0400`),
    vắng mặt sẽ vỡ ở INSERT (`NotNullViolationError`, 500) thay vì dùng default
    hợp lý. Lọc `None` sau đó để field nullable thật (`thumb_url`/`uploaded_by`)
    dùng DEFAULT/NULL của DB thay vì ghi đè `NULL` tường minh.

    ⚠️ `status='published'` ĐẶT TƯỜNG MINH, KHÔNG để DEFAULT `'draft'` của DB.
    Phát hiện khi chạy đầu-cuối thật (smoke test 2026-08-03, thời điểm đó qua view
    `agent_api.media` — view đã bỏ từ `0917`, agent nay tự lọc `status` khi đọc thẳng
    bảng `media` trong `tenant_data`, nhưng bài học không đổi — chữ viết liền dạng
    schema-chấm-bảng ở đây từng làm cổng quét tĩnh đọc nhầm docstring này thành một
    câu SQL): row media sinh từ ô cover/mặt bằng
    lấy DEFAULT `'draft'`, và `MediaUploadIn` KHÔNG có field `status` (cộng
    `extra="forbid"`), nên client KHÔNG CÁCH NÀO đặt nó. Thiếu dòng này, ảnh cover của
    một dự án đã published vẫn mang `status='draft'` vĩnh viễn — agent tự lọc theo
    đúng logic của họ cũng sẽ ẩn nó, và đường upload cover thành một tính năng không
    bao giờ tới được người dùng cuối, mà không có lỗi nào ở đâu cả.

    VÌ SAO `'published'` CHỨ KHÔNG PHẢI SAO THEO STATUS CỦA CHA: mệnh đề
    `p.status = 'published'` trong view ĐÃ LÀ cổng cascade theo anchor (`02 §3`:
    "một cột `status` làm cả hai việc, cascade theo anchor"). Ảnh của một dự án
    nháp vẫn ẩn vì cổng đó, nên đặt `'published'` ở row con là để row con KHÔNG
    thêm một cổng thứ hai mà người dùng không có ô nào để mở. Sao theo status của
    cha thì cần đọc lại row cha trong cùng giao dịch cho một kết quả giống hệt.
    Đây cũng đúng bằng thứ FE gửi cho media nhập qua tab Media và ảnh căn
    (`status: 'published'`) — một nếp, không phải hai.
    """
    d: dict = {
        "project_code": project_code,
        "category": category,
        "status": "published",
        **upload.model_dump(),
    }
    if zone_code:
        d["zone_code"] = zone_code
    return {k: v for k, v in d.items() if v is not None}


async def _gan_anh_cover_map(
    conn: asyncpg.Connection,
    tenant_id: str,
    payload: dict,
    *,
    project_code: str,
    cover: MediaUploadIn | None,
    map_: MediaUploadIn | None,
    zone_code: str = "",
) -> list[int]:
    """Luật UX #2 — SỬA `payload` TẠI CHỖ, thêm `cover_media_id`/`map_media_id`
    nếu có ảnh gửi kèm. Gọi TRONG cùng khối `async with tenant_conn(...)` với
    lần ghi entity cha ngay sau đó — `tenant_conn()` đã mở transaction cho cả
    khối (`core/db/session.py`), nên "tạo media" + "ghi entity cha mang FK vừa
    tạo" là MỘT giao dịch mà không cần quản lý gì thêm ở đây.

    TRẢ VỀ id các hàng `media` vừa tạo — nơi gọi cần chúng để đặt việc nạp."""
    created_ids: list[int] = []
    if cover is not None:
        gt = _payload_media_con(cover, project_code=project_code, category="tong_quan", zone_code=zone_code)
        m = await repo.chen_media(conn, tenant_id, gt)
        payload["cover_media_id"] = m["id"]
        created_ids.append(int(m["id"]))
    if map_ is not None:
        gt = _payload_media_con(map_, project_code=project_code, category="mat_bang", zone_code=zone_code)
        m = await repo.chen_media(conn, tenant_id, gt)
        payload["map_media_id"] = m["id"]
        created_ids.append(int(m["id"]))
    return created_ids


# ─── Dự án (`projects` — anchor) ────────────────────────────────────────────


@ROUTER.get("/projects", response_model=TrangDuAn)
async def liet_ke_du_an(
    search: str = "",
    region: str = "",
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangDuAn:
    cursor = _cursor_neu_offset(cursor, offset)
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_du_an(conn, tim=search, region=region, limit=xin, cursor=cursor, offset=offset)
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        tong = await repo.dem_du_an(conn, tim=search, region=region)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangDuAn(items=[_ra_du_an(r) for r in items], nextCursor=ke_tiep, total=tong)


@ROUTER.post("/projects", status_code=status.HTTP_201_CREATED, response_model=DuAnOut)
async def tao_du_an(
    body: ProjectIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    if body.project_code == SENTINEL_TENANT:
        raise _sentinel_duoc_bao_ve("tạo")
    if not body.project_code and not can_derive_code(body.name):
        raise _thieu_ten_du_an()
    payload = _tach_payload(body)
    _ghi_ban_giao(payload)
    _chan_tao_moi_thieu("project", body.model_dump())
    async with tenant_conn(pool, p.tenant_id) as conn:
        project_code = body.project_code or await next_project_code(conn, candidate_code(body.name))
        payload["project_code"] = project_code
        tao = await repo.chen_du_an(conn, p.tenant_id, payload)
        if tao is None:
            raise _trung_ma("dự án")
        await repo.dong_bo_hot_word(conn, p.tenant_id, int(tao["id"]), str(tao["name"]))
        gan: dict = {}
        new_media_ids = await _gan_anh_cover_map(
            conn, p.tenant_id, gan, project_code=project_code, cover=body.cover_media, map_=body.map_media
        )
        if gan:
            tao = await repo.sua_du_an(conn, tao["id"], gan)
            assert tao is not None
        await _enqueue_index(conn, p, entity="projects", record_id=int(tao["id"]), project_code=project_code)
        await _enqueue_thumb(conn, p, ids=new_media_ids, project_code=project_code)
        if tao["status"] == "published":
            await enqueue_web_project(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
        if body.link_360:
            await _sync_tour_360(conn, p, project_code=project_code, link=body.link_360, ten_du_an=str(tao["name"]))
        await _nhat_ky(conn, p, "realestate.project.create", {"project_code": project_code})
    return _ra_du_an(tao)


# ─── Tri thức (nút "Đồng bộ tri thức" + trạng thái enrich/index, Task 12) ────

_SyncMode = Literal["delta", "full"]


@ROUTER.post("/projects/{project_code}/sync-kb", status_code=status.HTTP_202_ACCEPTED)
async def sync_knowledge_base(
    project_code: str,
    mode: _SyncMode = "delta",
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int | str]:
    """`mode='full'` nạp lại MỌI mục kể cả mục không đổi — tốn tiền embed, nên giao
    diện phải hỏi xác nhận trước khi gọi. `delta` bỏ qua mục có content_hash không đổi."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_SYNC_PROJECT,
            actor=p.user_id,
            payload={
                "vertical": "real_estate",
                "project_code": project_code,
                "actor": p.user_id,
                "mode": mode,
            },
        )
        await _nhat_ky(
            conn,
            p,
            "realestate.knowledge.sync",
            {"project_code": project_code, "job_id": job_id, "mode": mode},
        )
    return {"jobId": job_id, "state": "queued"}


class CaptionNhapIn(BaseModel):
    mediaUrl: str
    contentType: str = "image"
    category: str = ""


@ROUTER.post("/media/draft-caption", status_code=status.HTTP_202_ACCEPTED)
async def tao_caption_nhap(
    than: CaptionNhapIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int | str]:
    """Mô tả cho ảnh VỪA tải lên, chưa có hàng `media` — người dùng đọc trước khi lưu."""
    if not than.mediaUrl.strip():
        raise loi.LoiPortal("VALIDATION_ERROR", 422, "Thiếu mediaUrl")
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_CAPTION_PREVIEW,
            actor=p.user_id,
            payload={
                "vertical": "real_estate",
                "media_url": than.mediaUrl,
                "content_type": than.contentType,
                "category": than.category,
            },
        )
        await _nhat_ky(conn, p, "realestate.media.draft_caption", {"key": than.mediaUrl, "job_id": job_id})
    return {"jobId": job_id, "state": "queued"}


@ROUTER.get("/media/draft-caption/{job_id}")
async def doc_caption_nhap(
    job_id: int,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, str]:
    """`caption` chỉ có khi `state = 'success'`. FE dừng poll ở `success`/`failed`."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT state, message FROM control.jobs "
            "WHERE id = $1 AND tenant_id = portal.current_tenant() AND kind = $2",
            job_id,
            KIND_CAPTION_PREVIEW,
        )
    if row is None:
        raise loi.LoiPortal("NO_JOB", 404, "Không tìm thấy yêu cầu tạo mô tả")
    trang_thai = str(row["state"])
    return {
        "state": trang_thai,
        "caption": str(row["message"]) if trang_thai == "success" else "",
    }


@ROUTER.get("/projects/{project_code}/enrich-status")
async def enrich_status(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[dict]:
    """Suy từ `control.jobs` — không cột mới, không bảng mới.

    Lọc tenant bằng `portal.current_tenant()`, không bằng `$n`: giá trị hai bên như nhau
    (`$1` vốn là `p.tenant_id`), nhưng `kb_sync_status` ngay bên dưới dùng hàm đó xuyên
    suốt, và cổng `tests/isolation/test_loc_tenant_o_tang_app.py` quét TĨNH nên nó không
    biết `$1` mang gì. Hai endpoint viết cạnh nhau phải cùng một quy ước.
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT j.payload->>'entity' AS entity,
                   (j.payload->>'record_id')::bigint AS record_id,
                   j.state, j.message
              FROM control.jobs j
             WHERE j.tenant_id = portal.current_tenant() AND j.kind = $1
               AND (
                    (j.payload->>'entity' = 'media' AND EXISTS (
                        SELECT 1 FROM tenant_data.media m
                         WHERE m.tenant_id = portal.current_tenant()
                           AND m.id = (j.payload->>'record_id')::bigint
                           AND m.project_code = $2))
                 OR (j.payload->>'entity' = 'documents' AND EXISTS (
                        SELECT 1 FROM tenant_data.documents d
                         WHERE d.tenant_id = portal.current_tenant()
                           AND d.id = (j.payload->>'record_id')::bigint
                           AND d.project_code = $2))
               )
             ORDER BY j.id DESC
            """,
            KIND_ENRICH,
            project_code,
        )
    return [
        {"entity": r["entity"], "recordId": r["record_id"], "state": r["state"], "message": r["message"]} for r in rows
    ]


@ROUTER.get("/projects/kb-status", response_model=list[KbStatusOut])
async def kb_status(
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[KbStatusOut]:
    """Nguồn duy nhất của chỉ báo — cả trang danh sách dùng một lời gọi này.

    BÁO THỪA CÓ CHỦ Ý ở nhánh lệch: bấm Lưu mà không sửa gì cũng thành lệch trong
    khoảnh khắc trước khi worker so dấu tay rồi ghi `skipped`. Vì thế lệch chỉ thành
    LỖI khi không còn việc nào đang chờ — lúc đó nó là dấu hiệu một việc bị mất.

    PHẢI đứng TRƯỚC `doc_du_an`: `{project_code}` khớp mọi chuỗi.
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.project_status(conn)
    return [KbStatusOut.model_validate(dict(r)) for r in rows]


@ROUTER.get("/projects/{project_code}", response_model=DuAnOut)
async def doc_du_an(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_du_an(conn, project_code)
        if hang is None:
            raise _du_an_khong_thay()
    return _ra_du_an(hang)


@ROUTER.patch("/projects/{project_code}", response_model=DuAnOut)
async def sua_du_an(
    project_code: str,
    body: ProjectPatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DuAnOut:
    payload = _tach_payload(body)
    _ghi_ban_giao(payload)
    if project_code == SENTINEL_TENANT and "status" in payload:
        raise _sentinel_duoc_bao_ve("đổi status")
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_du_an(conn, project_code)
        if hang is None:
            raise _du_an_khong_thay()
        new_media_ids = await _gan_anh_cover_map(
            conn, p.tenant_id, payload, project_code=project_code, cover=body.cover_media, map_=body.map_media
        )
        if not _bo_qua_completeness_du_an(project_code):
            _chan_publish_thieu("project", hang, payload)
        sua = await repo.sua_du_an(conn, hang["id"], payload)
        assert sua is not None  # vừa đọc thấy hàng trong CÙNG giao dịch, RLS cùng tenant — chắc chắn còn
        if "name" in payload:
            await repo.dong_bo_hot_word(conn, p.tenant_id, int(sua["id"]), str(sua["name"]))
        await _enqueue_project_change(conn, p, hang=hang, payload=payload, project_code=project_code)
        await _enqueue_thumb(conn, p, ids=new_media_ids, project_code=project_code)
        if "link_360" in payload or ("name" in payload and hang["link_360"]):
            await _sync_tour_360(
                conn,
                p,
                project_code=project_code,
                link=str(payload.get("link_360", hang["link_360"] or "")),
                ten_du_an=str(sua["name"]),
            )
        await _nhat_ky(conn, p, "realestate.project.update", {"project_code": project_code, "truong": sorted(payload)})
    return _ra_du_an(sua)


@ROUTER.delete("/projects/{project_code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_du_an(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    if project_code == SENTINEL_TENANT:
        raise _sentinel_duoc_bao_ve("xoá")
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_du_an(conn, project_code)
        if hang is None:
            raise _du_an_khong_thay()
        await repo.xoa_du_an(conn, hang["id"])
        await _enqueue_purge_project(conn, p, project_code=project_code)
        await enqueue_web_purge(conn, tenant_id=p.tenant_id, actor=p.user_id, project_name=str(hang["name"] or ""))
        await _nhat_ky(conn, p, "realestate.project.delete", {"project_code": project_code})


# ─── Phân khu (`zones`) ─────────────────────────────────────────────────────


@ROUTER.get("/projects/{project_code}/zones", response_model=TrangPhanKhu)
async def liet_ke_phan_khu(
    project_code: str,
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangPhanKhu:
    cursor = _cursor_neu_offset(cursor, offset)
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_phan_khu(conn, project_code=project_code, limit=xin, cursor=cursor, offset=offset)
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        tong = await repo.dem_phan_khu(conn, project_code=project_code)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangPhanKhu(items=[_ra_phan_khu(r) for r in items], nextCursor=ke_tiep, total=tong)


@ROUTER.post("/projects/{project_code}/zones", status_code=status.HTTP_201_CREATED, response_model=PhanKhuOut)
async def tao_phan_khu(
    project_code: str,
    body: ZoneIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> PhanKhuOut:
    if not body.zone_code and not can_derive_code(body.name):
        raise _thieu_ten_phan_khu()
    payload = _tach_payload(body)
    payload["project_code"] = project_code
    async with tenant_conn(pool, p.tenant_id) as conn:
        zone_code = body.zone_code or await next_zone_code(conn, project_code, candidate_code(body.name))
        payload["zone_code"] = zone_code
        try:
            tao = await repo.chen_phan_khu(conn, p.tenant_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        if tao is None:
            raise _trung_ma("phân khu")
        gan: dict = {}
        new_media_ids = await _gan_anh_cover_map(
            conn,
            p.tenant_id,
            gan,
            project_code=project_code,
            cover=body.cover_media,
            map_=body.map_media,
            zone_code=zone_code,
        )
        if gan:
            tao = await repo.sua_phan_khu(conn, tao["id"], gan)
            assert tao is not None
        await _enqueue_index(conn, p, entity="zones", record_id=int(tao["id"]), project_code=project_code)
        await _enqueue_thumb(conn, p, ids=new_media_ids, project_code=project_code)
        await _nhat_ky(conn, p, "realestate.zone.create", {"project_code": project_code, "zone_code": zone_code})
    return _ra_phan_khu(tao)


@ROUTER.get("/projects/{project_code}/zones/{zone_code}", response_model=PhanKhuOut)
async def doc_phan_khu(
    project_code: str,
    zone_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> PhanKhuOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_phan_khu(conn, project_code, zone_code)
        if hang is None:
            raise _phan_khu_khong_thay()
    return _ra_phan_khu(hang)


@ROUTER.patch("/projects/{project_code}/zones/{zone_code}", response_model=PhanKhuOut)
async def sua_phan_khu(
    project_code: str,
    zone_code: str,
    body: ZonePatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> PhanKhuOut:
    payload = _tach_payload(body)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_phan_khu(conn, project_code, zone_code)
        if hang is None:
            raise _phan_khu_khong_thay()
        new_media_ids = await _gan_anh_cover_map(
            conn,
            p.tenant_id,
            payload,
            project_code=project_code,
            cover=body.cover_media,
            map_=body.map_media,
            zone_code=zone_code,
        )
        sua = await repo.sua_phan_khu(conn, hang["id"], payload)
        assert sua is not None
        await _enqueue_index(conn, p, entity="zones", record_id=int(hang["id"]), project_code=project_code)
        await _enqueue_thumb(conn, p, ids=new_media_ids, project_code=project_code)
        await _nhat_ky(
            conn,
            p,
            "realestate.zone.update",
            {"project_code": project_code, "zone_code": zone_code, "truong": sorted(payload)},
        )
    return _ra_phan_khu({**dict(sua), "unit_count": hang["unit_count"]})


@ROUTER.delete("/projects/{project_code}/zones/{zone_code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_phan_khu(
    project_code: str,
    zone_code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await _tim_phan_khu(conn, project_code, zone_code)
        if hang is None:
            raise _phan_khu_khong_thay()
        # Đọc TRƯỚC khi xoá: FK `zones → media` là ON DELETE CASCADE.
        media_ids = await repo.media_ids_of_zone(conn, project_code=project_code, zone_code=zone_code)
        await repo.xoa_phan_khu(conn, hang["id"])
        await _enqueue_purge_zone(conn, p, project_code=project_code, zone_id=int(hang["id"]), media_ids=media_ids)
        await _nhat_ky(conn, p, "realestate.zone.delete", {"project_code": project_code, "zone_code": zone_code})


# ─── Toà (`buildings`) ──────────────────────────────────────────────────────


@ROUTER.get("/projects/{project_code}/buildings", response_model=TrangToa)
async def liet_ke_toa(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangToa:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke_toa(conn, project_code=project_code)
    return TrangToa(items=[_ra_toa(r) for r in hang], total=len(hang))


@ROUTER.post("/projects/{project_code}/buildings", status_code=status.HTTP_201_CREATED, response_model=ToaOut)
async def tao_toa(
    project_code: str,
    body: BuildingIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ToaOut:
    payload = _tach_payload(body)
    payload["project_code"] = project_code
    payload["building_code"] = body.building_code.strip()
    payload.setdefault("name", payload["building_code"])
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            tao = await repo.chen_toa(conn, p.tenant_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        if tao is None:
            raise _trung_ma("toà")
        await _enqueue_index(conn, p, entity="buildings", record_id=int(tao["id"]), project_code=project_code)
        await _nhat_ky(
            conn,
            p,
            "realestate.building.create",
            {"project_code": project_code, "building_code": tao["building_code"]},
        )
    return _ra_toa(tao)


@ROUTER.patch("/projects/{project_code}/buildings/{building_code}", response_model=ToaOut)
async def sua_toa(
    project_code: str,
    building_code: str,
    body: BuildingPatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ToaOut:
    payload = _tach_payload(body)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_toa(conn, project_code=project_code, building_code=building_code)
        if hang is None:
            raise _toa_khong_thay()
        try:
            sua = await repo.sua_toa(conn, hang["id"], payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        assert sua is not None
        await _enqueue_index(conn, p, entity="buildings", record_id=int(hang["id"]), project_code=project_code)
        await _nhat_ky(
            conn,
            p,
            "realestate.building.update",
            {"project_code": project_code, "building_code": building_code, "truong": sorted(payload)},
        )
    return _ra_toa(sua)


@ROUTER.delete("/projects/{project_code}/buildings/{building_code}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_toa(
    project_code: str,
    building_code: str,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_toa(conn, project_code=project_code, building_code=building_code)
        if hang is None:
            raise _toa_khong_thay()
        if hang["unit_count"]:
            raise _toa_con_can(hang["unit_count"])
        await repo.xoa_toa(conn, hang["id"])
        await _enqueue_index(conn, p, entity="buildings", record_id=int(hang["id"]), project_code=project_code)
        await _nhat_ky(
            conn, p, "realestate.building.delete", {"project_code": project_code, "building_code": building_code}
        )


# ─── Căn (`units`) ──────────────────────────────────────────────────────────


@ROUTER.get("/projects/{project_code}/units", response_model=TrangCan)
async def liet_ke_can(
    project_code: str,
    zone_code: str = "",
    product_type: _LocProductType = "",
    sale_status: _LocSaleStatus = "",
    direction: _LocDirection = "",
    unit_code: str = "",
    status: _LocStatus = "",
    sort: _SapXepCan = "",
    desc: bool = False,
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangCan:
    if offset or sort:
        cursor = None
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_can(
                conn,
                project_code=project_code,
                zone_code=zone_code,
                product_type=product_type,
                sale_status=sale_status,
                direction=direction,
                unit_code=unit_code,
                status=status,
                sap_xep=sort,
                giam=desc,
                limit=xin,
                cursor=cursor,
                offset=offset,
            )
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        tong = await repo.dem_can(
            conn,
            project_code=project_code,
            zone_code=zone_code,
            product_type=product_type,
            sale_status=sale_status,
            direction=direction,
            unit_code=unit_code,
            status=status,
        )
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangCan(items=[_ra_can(r) for r in items], nextCursor=ke_tiep, total=tong)


@ROUTER.get("/projects/{project_code}/units/facets", response_model=FacetCan)
async def facet_can(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> FacetCan:
    """Giá trị loại sản phẩm / hướng CÓ THẬT trong quỹ căn — nguồn của hai ô lọc."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.facet_can(conn, project_code=project_code)
    if hang is None:
        return FacetCan(productType=[], direction=[])
    return FacetCan(productType=list(hang["product_type"]), direction=list(hang["direction"]))


@ROUTER.post("/projects/{project_code}/units", status_code=status.HTTP_201_CREATED, response_model=CanOut)
async def tao_can(
    project_code: str,
    body: UnitIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    payload = _tach_payload(body)
    payload["project_code"] = project_code
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            tao = await repo.chen_can(conn, p.tenant_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        _chan_tao_moi_thieu("unit", body.model_dump())
        if payload.get("block"):
            await _enqueue_index(conn, p, entity="buildings", record_id=0, project_code=project_code)
        chi_tiet = {"project_code": project_code, "unit_code": body.unit_code, "id": tao["id"]}
        await _nhat_ky(conn, p, "realestate.unit.create", chi_tiet)
    return _ra_can(tao)


@ROUTER.get("/projects/{project_code}/units/{unit_id}", response_model=CanOut)
async def doc_can(
    project_code: str,
    unit_id: int,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_can(conn, unit_id)
        if hang is None or hang["project_code"] != project_code:
            raise _can_khong_thay()
    return _ra_can(hang)


@ROUTER.patch("/projects/{project_code}/units/{unit_id}", response_model=CanOut)
async def sua_can(
    project_code: str,
    unit_id: int,
    body: UnitPatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> CanOut:
    payload = _tach_payload(body)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_can(conn, unit_id)
        if hang is None or hang["project_code"] != project_code:
            raise _can_khong_thay()
        _chan_publish_thieu("unit", hang, payload)
        try:
            sua = await repo.sua_can(conn, unit_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        assert sua is not None
        if payload.get("block") and payload["block"] != hang["block"]:
            await _enqueue_index(conn, p, entity="buildings", record_id=0, project_code=project_code)
        await _nhat_ky(conn, p, "realestate.unit.update", {"id": unit_id, "truong": sorted(payload)})
    return _ra_can(sua)


@ROUTER.delete("/projects/{project_code}/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_can(
    project_code: str,
    unit_id: int,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_can(conn, unit_id)
        if hang is None or hang["project_code"] != project_code:
            raise _can_khong_thay()
        await repo.xoa_can(conn, unit_id)
        await _nhat_ky(conn, p, "realestate.unit.delete", {"id": unit_id})


# ─── Tài liệu (`documents`) ─────────────────────────────────────────────────


@ROUTER.get("/projects/{project_code}/documents", response_model=TrangTaiLieu)
async def liet_ke_tai_lieu(
    project_code: str,
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangTaiLieu:
    cursor = _cursor_neu_offset(cursor, offset)
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_tai_lieu(conn, project_code=project_code, limit=xin, cursor=cursor, offset=offset)
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        tong = await repo.dem_tai_lieu(conn, project_code=project_code)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangTaiLieu(items=[_ra_tai_lieu(r) for r in items], nextCursor=ke_tiep, total=tong)


@ROUTER.post("/projects/{project_code}/documents", status_code=status.HTTP_201_CREATED, response_model=TaiLieuOut)
async def tao_tai_lieu(
    project_code: str,
    body: DocumentIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaiLieuOut:
    payload = _payload_tai_lieu(body)
    payload["project_code"] = project_code
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            tao = await repo.chen_tai_lieu(conn, p.tenant_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        await _nhat_ky(conn, p, "realestate.document.create", {"project_code": project_code, "id": tao["id"]})
        await _enqueue_document_change(
            conn,
            p,
            record_id=int(tao["id"]),
            project_code=project_code,
            file_moi=bool(body.file_url),
            tu_duyet=body.auto_approve,
        )
    return _ra_tai_lieu(tao)


@ROUTER.get("/projects/{project_code}/documents/{doc_id}", response_model=TaiLieuOut)
async def doc_tai_lieu(
    project_code: str,
    doc_id: int,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaiLieuOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_tai_lieu(conn, doc_id)
        if hang is None or hang["project_code"] != project_code:
            raise _tai_lieu_khong_thay()
    return _ra_tai_lieu(hang)


@ROUTER.patch("/projects/{project_code}/documents/{doc_id}", response_model=TaiLieuOut)
async def sua_tai_lieu(
    project_code: str,
    doc_id: int,
    body: DocumentPatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaiLieuOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_tai_lieu(conn, doc_id)
        if hang is None or hang["project_code"] != project_code:
            raise _tai_lieu_khong_thay()
        payload = _payload_tai_lieu(body, current_title=hang["title"])
        if payload.get("body"):
            payload["body_cho_duyet"] = False
        loai_cu, _ = split_title(hang["title"])
        sua = await repo.sua_tai_lieu(conn, doc_id, payload)
        assert sua is not None
        loai_moi, _ = split_title(sua["title"])
        if loai_moi != loai_cu:
            await enqueue(
                conn,
                tenant_id=p.tenant_id,
                kind=KIND_DELETE_INDEX,
                actor=p.user_id,
                payload={
                    "vertical": "real_estate",
                    "entity": "documents",
                    "record_id": doc_id,
                    "doc_type": loai_cu,
                },
            )
        file_moi = bool(payload.get("file_url")) and payload["file_url"] != hang["file_url"]
        await _enqueue_document_change(
            conn,
            p,
            record_id=doc_id,
            project_code=project_code,
            file_moi=file_moi,
            ghi_de=file_moi,
            tu_duyet=body.auto_approve,
        )
        await _nhat_ky(conn, p, "realestate.document.update", {"id": doc_id, "truong": sorted(payload)})
    return _ra_tai_lieu(sua)


@ROUTER.post("/projects/{project_code}/documents/{doc_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def duyet_tai_lieu(
    project_code: str,
    doc_id: int,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, bool]:
    """Duyệt chữ do OCR đọc: tắt cờ rồi đặt việc nạp. Hàng không mang cờ thì không đặt gì."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_tai_lieu(conn, doc_id)
        if hang is None or hang["project_code"] != project_code:
            raise _tai_lieu_khong_thay()
        da_duyet = await repo.tat_cho_duyet(conn, doc_id)
        if da_duyet:
            await _enqueue_index(conn, p, entity="documents", record_id=doc_id, project_code=project_code)
        await _nhat_ky(conn, p, "realestate.document.approve", {"id": doc_id, "da_duyet": da_duyet})
    return {"approved": da_duyet}


@ROUTER.delete("/projects/{project_code}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_tai_lieu(
    project_code: str,
    doc_id: int,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_tai_lieu(conn, doc_id)
        if hang is None or hang["project_code"] != project_code:
            raise _tai_lieu_khong_thay()
        await repo.xoa_tai_lieu(conn, doc_id)
        await _enqueue_purge_record(conn, p, entity="documents", record_id=doc_id)
        await _nhat_ky(conn, p, "realestate.document.delete", {"id": doc_id})


# ─── Media (`media`) ────────────────────────────────────────────────────────


@ROUTER.get("/projects/{project_code}/media", response_model=TrangMedia)
async def liet_ke_media(
    project_code: str,
    zone_code: str = "",
    unit_code: str = "",
    category: _LocMediaCategory = "",
    content_type: _LocMediaContentType = "",
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    offset: int = _OFFSET_Q,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangMedia:
    # Xem `liet_ke_du_an`: offset thắng cursor.
    cursor = _cursor_neu_offset(cursor, offset)
    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            hang = await repo.liet_ke_media(
                conn,
                project_code=project_code,
                zone_code=zone_code,
                unit_code=unit_code,
                category=category,
                content_type=content_type,
                limit=xin,
                cursor=cursor,
                offset=offset,
            )
        except LoiConTro as e:
            raise _con_tro_khong_hop_le() from e
        tong = await repo.dem_media(
            conn,
            project_code=project_code,
            zone_code=zone_code,
            unit_code=unit_code,
            category=category,
            content_type=content_type,
        )
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangMedia(items=[_ra_media(r) for r in items], nextCursor=ke_tiep, total=tong)


@ROUTER.post("/projects/{project_code}/media", status_code=status.HTTP_201_CREATED, response_model=MediaOut)
async def tao_media(
    project_code: str,
    body: MediaIn,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MediaOut:
    payload = _tach_payload(body)
    payload["project_code"] = project_code
    async with tenant_conn(pool, p.tenant_id) as conn:
        try:
            tao = await repo.chen_media(conn, p.tenant_id, payload)
        except asyncpg.ForeignKeyViolationError as e:
            raise _loi_fk(e) from e
        await _nhat_ky(conn, p, "realestate.media.create", {"project_code": project_code, "id": tao["id"]})
        await _enqueue_thumb(conn, p, ids=[int(tao["id"])], project_code=project_code)
    return _ra_media(tao)


@ROUTER.get("/projects/{project_code}/media/{media_id}", response_model=MediaOut)
async def doc_media(
    project_code: str,
    media_id: int,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MediaOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_media(conn, media_id)
        if hang is None or hang["project_code"] != project_code:
            raise _media_khong_thay()
    return _ra_media(hang)


@ROUTER.patch("/projects/{project_code}/media/{media_id}", response_model=MediaOut)
async def sua_media(
    project_code: str,
    media_id: int,
    body: MediaPatch,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MediaOut:
    payload = _tach_payload(body)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_media(conn, media_id)
        if hang is None or hang["project_code"] != project_code:
            raise _media_khong_thay()
        sua = await repo.sua_media(conn, media_id, payload)
        assert sua is not None
        anh_moi = bool(payload.get("media_url")) and payload["media_url"] != hang["media_url"]
        await dat_viec_thumb(
            conn,
            tenant_id=p.tenant_id,
            actor=p.user_id,
            entity="media",
            record_id=media_id,
            project_code=project_code,
            ghi_de=anh_moi,
        )
        await _nhat_ky(conn, p, "realestate.media.update", {"id": media_id, "truong": sorted(payload)})
    return _ra_media(sua)


@ROUTER.delete("/projects/{project_code}/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_media(
    project_code: str,
    media_id: int,
    p: Principal = require(ACTIONS.CATALOG_DELETE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.doc_media(conn, media_id)
        if hang is None or hang["project_code"] != project_code:
            raise _media_khong_thay()
        await repo.xoa_media(conn, media_id)
        await _enqueue_purge_record(conn, p, entity="media", record_id=media_id)
        await _nhat_ky(conn, p, "realestate.media.delete", {"id": media_id})


# ─── Kho tệp ────────────────────────────────────────────────────────────────

LOAI_ANH = frozenset({"jpg", "jpeg", "png", "webp"})
LOAI_TAI_LIEU = frozenset({"pdf", "docx", "xlsx"})

GIOI_HAN_ANH_BYTE = 10 * 1024 * 1024
GIOI_HAN_TAI_LIEU_BYTE = 25 * 1024 * 1024
"""⚠️ CON SỐ TẠM: KB_01 BR12 để ngưỡng dung lượng CHƯA CHỐT và ghi rõ nó là đầu
vào của bảng giá, không phải quyết định kỹ thuật. 10 MB đủ cho một ảnh dự án chụp
máy ảnh; 25 MB đủ cho tài liệu chính sách thường gặp.

Trước đây hai con số này phải khớp `modules/kb/router.py:GIOI_HAN_BYTE`. Ràng buộc
đó KHÔNG còn: M6 bỏ hẳn đường upload, nên đây là trần DUY NHẤT — chốt thật thì sửa
ở đây, một chỗ."""

_TEP = File(...)
"""`File(...)` gọi thẳng trong default là B008 của ruff, và ruff đúng: default
được tính MỘT LẦN lúc import nên một lời gọi hàm ở đó dễ gây bất ngờ. Với FastAPI
thì đây là cách khai chủ ý, nên rút ra hằng số mức module."""

_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
"""Content-Type trả về ở đường đọc. TỰ TRA THEO ĐUÔI, không tin
`UploadFile.content_type` của client: client đặt được nó thành bất kỳ chuỗi nào,
và một `text/html` phát lại từ cùng origin với portal là một XSS."""


class TepDaLen(BaseModel):
    """Kết quả một lần tải lên. `key` là thứ FE nhét vào `mediaUrl`/`fileUrl`."""

    key: str
    contentHash: str
    contentType: str


def _loai_tep_khong_ho_tro() -> loi.LoiPortal:
    return loi.LoiPortal(
        "UNSUPPORTED_TYPE",
        422,
        f"Chỉ nhận ảnh ({', '.join(sorted(LOAI_ANH))}) hoặc tài liệu ({', '.join(sorted(LOAI_TAI_LIEU))})",
    )


def _tep_qua_lon(tran_byte: int) -> loi.LoiPortal:
    return loi.LoiPortal("FILE_TOO_LARGE", 422, f"Tệp vượt dung lượng cho phép ({tran_byte // (1024 * 1024)} MB)")


def _khong_co_tep() -> loi.LoiPortal:
    """404 CHO CẢ "không có" LẪN "không thuộc tenant này" — cố ý không phân biệt.

    Trả 403 cho khoá của tenant khác là xác nhận khoá đó TỒN TẠI, và tên khoá
    mang tên dự án của họ. 404 cho cả hai không nói gì thêm ngoài "bạn không có
    tệp này"."""
    return loi.LoiPortal("NO_FILE", 404, "Không tìm thấy tệp")


def _tien_to_tenant(tenant_id: str) -> str:
    """Tiền tố kho tệp của một tenant cho KB BĐS.

    `kb-bds/` tách khỏi `bundles/`/`LIVE` (`core/storage.py`) và khỏi `kb/`
    (`modules/kb`): ba loại nội dung, ba vòng đời khác nhau — bundle bị `publish`
    ghi đè, tài liệu RAG bị xoá cùng `kb_files`, còn ảnh KB BĐS sống theo hàng
    `media`. Trộn một tiền tố thì `liet_ke()` của bên này thấy tệp của bên kia."""
    return f"tenants/{tenant_id}/kb-bds/"


@ROUTER.post("/realestate/uploads", status_code=status.HTTP_201_CREATED, response_model=TepDaLen)
async def tai_tep_len(
    file: UploadFile = _TEP,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TepDaLen:
    """Nhận MỘT tệp, trả khoá kho. KHÔNG ghi DB — hàng `media`/`documents` do
    request kế tiếp của FE tạo (hoặc do form cha tạo qua `coverMedia`).

    VÌ SAO TÁCH LÀM HAI CHẶNG, KHÔNG NHẬN multipart Ở LUÔN `POST /media`: một
    form dự án có 2 ảnh, form căn có tới 6 — gộp nghĩa là mỗi lần bấm Lưu là một
    request nhiều chục MB, và người dùng mất trắng cả form nếu nó đứt. Tải từng
    tệp xong mới Lưu thì lần Lưu chỉ còn vài KB JSON.

    Content-addressed (`sha256`): tải cùng một ảnh hai lần cho cùng một khoá,
    nên không sinh bản sao và FE gửi lại được sau khi mất mạng mà không rác.

    GHI NHẬT KÝ dù route không tạo hàng nghiệp vụ nào (BR13). Đây là chỗ DUY
    NHẤT một tệp mồ côi để lại dấu vết: nếu người dùng tải lên rồi không bấm Lưu,
    không hàng `media`/`documents` nào tồn tại, nên không có `realestate.media.
    create` nào để lần theo — mà byte đã nằm trong kho của tenant. Miễn trừ route
    này khỏi BR13 sẽ biến "ai đưa tệp này vào kho" thành câu không trả lời được.
    """
    import hashlib

    from portal.core.storage import kho_tep_tu_cai_dat

    ten = file.filename or ""
    duoi = ten.rsplit(".", 1)[-1].lower() if "." in ten else ""
    if duoi not in LOAI_ANH and duoi not in LOAI_TAI_LIEU:
        raise _loai_tep_khong_ho_tro()

    tran = GIOI_HAN_ANH_BYTE if duoi in LOAI_ANH else GIOI_HAN_TAI_LIEU_BYTE
    noi_dung = await file.read()
    if not noi_dung or len(noi_dung) > tran:
        raise _tep_qua_lon(tran)

    sha = await asyncio.to_thread(lambda: hashlib.sha256(noi_dung).hexdigest())
    khoa = f"{_tien_to_tenant(p.tenant_id)}{sha}/{_ten_an_toan(ten)}"
    await kho_tep_tu_cai_dat().ghi(khoa, noi_dung)
    async with tenant_conn(pool, p.tenant_id) as conn:
        await _nhat_ky(conn, p, "realestate.upload", {"key": khoa, "ten_file": ten, "so_byte": len(noi_dung)})
    return TepDaLen(key=khoa, contentHash=sha, contentType=_MIME.get(duoi, "application/octet-stream"))


def _ten_an_toan(ten: str) -> str:
    """Tên tệp rút về `[A-Za-z0-9._-]`, tối đa 120 ký tự, không rỗng.

    Chỉ giữ ký tự lành thay vì cấm một danh sách ký tự xấu: danh sách cấm luôn
    thiếu một thứ (`..`, `\\`, byte NUL, ký tự Unicode trông giống `/`), còn danh
    sách cho phép thì không. Tên rỗng sau khi rút (ví dụ tên toàn dấu tiếng Việt)
    ra `tep` — khoá vẫn duy nhất vì `sha` đã nằm trên đường dẫn."""
    sach = "".join(c if (c.isascii() and (c.isalnum() or c in "._-")) else "-" for c in ten).strip("-.")
    return sach[:120] or "tep"


async def _phat_tep(key: str, *, cache: str) -> Response:
    """Phát một tệp trong kho. Hai chế độ, chọn bằng `s3_redirect_enabled`.

    BẬT: 307 tới URL kho có hạn, sinh MỚI mỗi lượt — byte không chạm tiến trình API.
    TẮT (mặc định): tải về rồi gửi tiếp, như trước. Xem `Settings.s3_redirect_enabled`
    về cổng kiểm chứng phải qua trước khi bật.

    Hình dạng đường dẫn KHÔNG đổi ở cả hai chế độ: `public_url_of()` đã sinh ra chuỗi này
    vào payload Qdrant, vào cột `media.public_url`, và vào link đã gửi cho khách.
    """
    from portal.core.config import get_settings
    from portal.core.storage import KhongTimThay, kho_tep_dung_chung

    cfg = get_settings()
    kho = kho_tep_dung_chung()
    duoi = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    try:
        if cfg.s3_redirect_enabled:
            url = await kho.presign_get(key, ttl_sec=cfg.s3_redirect_ttl_sec)
            return RedirectResponse(
                url, status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Cache-Control": cache}
            )
        noi_dung = await kho.doc(key)
    except KhongTimThay as e:
        raise _khong_co_tep() from e
    return Response(
        content=noi_dung,
        media_type=_MIME.get(duoi, "application/octet-stream"),
        headers={"Cache-Control": cache},
    )


@ROUTER.get("/realestate/files")
async def doc_tep(
    key: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
) -> Response:
    """Phát lại một tệp trong kho. Dùng làm `src` của `<img>` ở CMS.

    ⚠️ DÒNG QUAN TRỌNG NHẤT CỦA CẢ HAI ROUTE là phép kiểm tiền tố bên dưới.
    `key` đến TỪ CLIENT — nó không phải dữ liệu nội bộ. Thiếu phép kiểm này thì
    `?key=tenants/<tenant-khác>/kb-bds/...` đọc được tệp của khách khác qua một
    request hợp lệ hoàn toàn, và cả ba lớp cách ly của M1 (RLS, role hẹp, tiền tố
    kho tệp) đều KHÔNG chắn được: RLS bảo vệ hàng trong Postgres, không bảo vệ
    object trong S3; còn access key ở dev/prod có quyền trên cả tiền tố
    `tenants/` chứ không riêng một tenant (`chinh_sach_tien_to` gắn theo pod, và
    tiến trình API phục vụ nhiều tenant).

    Kiểm bằng `startswith` trên tiền tố ĐÃ DỰNG từ `p.tenant_id` (không phải
    bằng cách tìm chuỗi lạ trong `key`): `tenants/reva/kb-bds/` là thứ duy nhất
    được chấp nhận, nên `../`, `//`, hay `tenants/revb/` đều rơi vào cùng một
    nhánh từ chối mà không cần liệt kê chúng.
    """
    if not key.startswith(_tien_to_tenant(p.tenant_id)):
        raise _khong_co_tep()
    return await _phat_tep(key, cache="private, max-age=31536000, immutable")


_KHOA_CONG_KHAI = re.compile(r"^tenants/[A-Za-z0-9_-]+/(?:kb-bds|kb/anh)/[^\\]+$")
"""Tệp KB BĐS (`kb-bds/`) + ảnh Markdown đã mirror về kho mình (`kb/anh/`, xem
`kb/clients/external_images.py::_fetch_one` — cùng thư mục chứa cả ảnh gốc và
thumb của nó, `kb/storage/thumbnail.py::thumb_key`). `bundles/`/`LIVE` (persona,
prompt) và `kb/<sha>/<tên tệp>` (tài liệu THÔ khách tải lên ở M6, riêng tư) nằm
NGOÀI tiền tố này có chủ ý — mở thêm hình dạng nào thì viết hình dạng đó tường
minh, đừng đổi thành `kb/` trần."""


@ROUTER.get("/public/files/{key:path}")
async def doc_tep_cong_khai(
    key: str,
    _: None = require(None, ly_do="Agent gửi ảnh vào cửa sổ chat; khách không có phiên Portal"),
) -> Response:
    """Phát ảnh cho khách cuối; URL nằm trong lịch sử chat nên phải sống lâu.

    KHÔNG lọc `status` (spec §3) — cái chắn là sha256 trong đường dẫn."""
    if ".." in key or not _KHOA_CONG_KHAI.match(key):
        raise _khong_co_tep()
    return await _phat_tep(key, cache="public, max-age=31536000, immutable")
