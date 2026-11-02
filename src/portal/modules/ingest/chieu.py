"""Projector — `ingest_records` → 5 bảng KB.

Chạy TRONG `tenant_conn()`, nên mọi câu SQL ở đây có hai lớp cách ly như
`repo.py` đã ghi: RLS của `0913` và vị từ `portal.current_tenant()` viết tay.

── MỘT KHOÁ XUNG ĐỘT CHO CẢ NĂM BẢNG ───────────────────────────────────────
`(tenant_id, external_id)` — index một phần dựng ở `0927`.

Đã cân nhắc dùng khoá nghiệp vụ sẵn có (`projects` có `(tenant_id, project_code)`,
`zones` có bộ ba) và BỎ: `units`/`documents`/`media` KHÔNG có khoá nghiệp vụ duy
nhất nào (`unit_code` chỉ được đánh index, không unique — `02a §4.3` cố ý). Dùng
khoá khác nhau cho từng bảng nghĩa là năm nhánh `ON CONFLICT` khác nhau, và cái
thứ năm sẽ là cái sai.

── THỨ TỰ TỚI KHÔNG ĐẢM BẢO ────────────────────────────────────────────────
Căn tới trước phân khu cha là chuyện BÌNH THƯỜNG của đẩy bất đồng bộ, không phải
lỗi của khách. Bản ghi chưa giải được cha thì ghi địa chỉ cha còn thiếu vào
`cho_cha_entity`/`cho_cha_ma` và nằm chờ — KHÔNG ghi vào `ingest_errors` («cha
chưa tới» không có gì để khách sửa). Đúng lúc cha đó chiếu xong, service nhặt
con theo index một phần và chiếu lan truyền (zone mở khoá unit). Chỉ khi bản kê
đối soát cho thấy cha không bao giờ tới thì nó mới thành lỗi — việc của §7.
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.core.ma_ban_ghi import next_project_code, next_zone_code, slug_code
from portal.core.public_url import public_url_of
from portal.modules.ingest import repo
from portal.modules.ingest.contracts import Entity
from portal.modules.ingest.hop_dong import HOP_DONG, QUAN_HE, kiem
from portal.modules.kb.contracts import (
    KIND_DELETE_INDEX,
    KIND_PROVISION,
    dat_viec_nap,
    dat_viec_provision,
    dat_viec_thumb,
    enqueue_web_project,
    enqueue_web_purge,
)

_BANG: dict[Entity, str] = {
    "project": "projects",
    "zone": "zones",
    "unit": "units",
    "document": "documents",
    "media": "media",
}

_COT_HOP_DONG: dict[Entity, tuple[str, ...]] = {e: tuple(dict.fromkeys(t.cot for t in HOP_DONG[e])) for e in _BANG}

_COT_CHA_TUY_CHON: dict[Entity, tuple[str, ...]] = {
    "project": (), "zone": (), "unit": ("zone_code",), "document": (), "media": ("zone_code", "unit_code"),
}  # fmt: skip


class ChuaGiaiDuocCha(Exception):
    """Cha chưa tới. KHÔNG phải lỗi — xem docstring đầu tệp.

    Mang theo ĐỊA CHỈ cha còn thiếu để service ghi vào `cho_cha_*`: bản ghi chờ
    một cha CỤ THỂ, và được nhặt lại đúng lúc cha đó chiếu xong."""

    def __init__(self, truong: str, cha_entity: str, cha_ma: str) -> None:
        super().__init__(f"chưa giải được {truong} ({cha_entity}={cha_ma!r})")
        self.truong = truong
        self.cha_entity = cha_entity
        self.cha_ma = cha_ma


async def _giai_cha(conn: asyncpg.Connection, entity: Entity, data: dict) -> dict[str, object]:
    """Khoá ngoài của khách → cột khoá của mình. Ném `ChuaGiaiDuocCha` nếu chưa có."""
    ra: dict[str, object] = {}
    for ten, cha, bat_buoc in QUAN_HE[entity]:
        ma_ngoai = data.get(ten)
        if ma_ngoai is None or not str(ma_ngoai).strip():
            if bat_buoc:
                raise RuntimeError(f"payload đã lưu thiếu khoá cha {ten}")
            continue
        ma_ngoai = str(ma_ngoai)
        if ten == "projectExternalId":
            ma = await repo.project_code_theo_ma_ngoai(conn, ma_ngoai)
            if ma is None:
                raise ChuaGiaiDuocCha(ten, cha, ma_ngoai)
            ra["project_code"] = ma
        elif ten == "zoneExternalId":
            hang = await repo.zone_theo_ma_ngoai(conn, ma_ngoai)
            if hang is None:
                raise ChuaGiaiDuocCha(ten, cha, ma_ngoai)
            ra["project_code"] = hang["project_code"]
            ra["zone_code"] = hang["zone_code"]
        else:  # unitExternalId — chỉ `media` có, và tuỳ chọn
            hang = await repo.unit_theo_ma_ngoai(conn, ma_ngoai)
            if hang is None:
                raise ChuaGiaiDuocCha(ten, cha, ma_ngoai)
            ra["project_code"] = hang["project_code"]
            ra["zone_code"] = hang["zone_code"]
            ra["unit_code"] = hang["unit_code"]
    return ra


async def _upsert(
    conn: asyncpg.Connection,
    *,
    bang: str,
    tenant_id: str,
    external_id: str,
    cot: dict[str, object],
    ve_mac_dinh: tuple[str, ...] = (),
) -> int:
    """`ON CONFLICT (tenant_id, external_id)` — xem docstring đầu tệp. Trả `id` hàng vừa ghi.

    KHÔNG có `WHERE external_id IS NOT NULL`: `0927` dựng constraint `UNIQUE`
    THƯỜNG chứ không index một phần, đúng để mệnh đề này không phải mang theo một
    vị từ mà quên là hỏng lúc chạy. Lý do đầy đủ ở migration đó.

    `ve_mac_dinh` — cột hợp đồng VẮNG MẶT trong payload lần này (`_COT_HOP_DONG` /
    `_COT_CHA_TUY_CHON` trừ đi cột đã có trong `cot`). THAY-THẾ-TRỌN-BẢN-GHI nghĩa
    là bản ghi sau upsert phải Y HỆT một INSERT MỚI từ cùng payload, nên các cột
    này phải quay về DEFAULT CỦA CHÍNH CỘT — `NULL` nếu cột nullable, giá trị
    nghiệp vụ nếu cột có default riêng (`sale_phase` về lại `'sap_mo_ban'`, các
    cột text mô tả về lại `''`). Dùng cú pháp `SET col = DEFAULT` của Postgres
    thay vì chép giá trị default vào code: Postgres tự tra đúng default hiện hành
    trong catalog, không tạo thêm một nguồn có thể lệch khỏi migration khi ai đó
    đổi default sau này. Đường INSERT-mới KHÔNG đổi — cột vắng mặt vẫn omit khỏi
    câu INSERT như trước, default áp tự nhiên; chỉ đường UPDATE có thêm vế reset
    này (review finding #6 — merge-từng-cột cũ để giá trị vắng mặt GIỮ NGUYÊN
    thay vì quay về default, nên giá đã rút không bao giờ xoá được).
    """
    day_du = {"tenant_id": tenant_id, "external_id": external_id, **cot}
    ten_cot = list(day_du)
    tham_so = ", ".join(f"${i}" for i in range(1, len(ten_cot) + 1))
    dat = ", ".join(
        [
            *(f"{c} = EXCLUDED.{c}" for c in ten_cot if c not in ("tenant_id", "external_id")),
            *(f"{c} = DEFAULT" for c in ve_mac_dinh),
        ]
    )
    return int(
        await conn.fetchval(
            f"""
            INSERT INTO tenant_data.{bang} ({", ".join(ten_cot)})
            VALUES ({tham_so})
            ON CONFLICT (tenant_id, external_id) DO UPDATE SET {dat}, updated_at = now()
            RETURNING id
            """,  # noqa: S608 — tên bảng từ `_BANG`, tên cột từ `hop_dong.HOP_DONG`/`_COT_CHA_TUY_CHON`; không có gì từ request
            *day_du.values(),
        )
    )


async def _xep_purge(
    conn: asyncpg.Connection,
    tenant_id: str,
    *,
    entity: Entity,
    record_id: int,
    project_code: str,
    zone_code: str | None = None,
) -> None:
    """Bản ghi RỜI `published` ⇒ point Qdrant của nó phải chết theo — cùng luật và
    cùng khuôn payload với đường manual (`realestate/router.py`, `_enqueue_purge_*`).
    `unit` không lên RAG (spec §6.4) nên không có gì để purge.

    `zone` CASCADE sang media neo vào nó (`zone_code` là zone_code CỦA CHÍNH nó,
    không phải khoá cha): worker KB chỉ tự cascade theo `anchor_code` (project),
    KHÔNG theo zone — đường manual (`_enqueue_purge_zone`) đã tự liệt kê media rồi
    purge riêng từng cái, thiếu bước này thì media archived (ẩn khỏi agent) nhưng
    point Qdrant của nó sống sót, cùng lớp NT2-1408."""
    if entity == "unit":
        return
    if entity == "zone":
        await dat_viec_nap(
            conn,
            tenant_id=tenant_id,
            actor="ingest",
            entity="zones",
            record_id=record_id,
            project_code=project_code,
        )
    else:
        if entity == "project":
            payload: dict = {"vertical": "real_estate", "anchor_code": project_code}
        else:
            payload = {"vertical": "real_estate", "entity": _BANG[entity], "record_id": record_id}
        await enqueue(conn, tenant_id=tenant_id, kind=KIND_DELETE_INDEX, actor="ingest", payload=payload)

    if entity == "zone":
        if zone_code is None:
            raise RuntimeError("zone rời published mà thiếu zone_code — bug ở caller")
        for media_id in await repo.media_id_theo_zone(conn, project_code, zone_code):
            await enqueue(
                conn,
                tenant_id=tenant_id,
                kind=KIND_DELETE_INDEX,
                actor="ingest",
                payload={"vertical": "real_estate", "entity": "media", "record_id": media_id},
            )


async def _xoa_mem(conn: asyncpg.Connection, tenant_id: str, entity: Entity, external_id: str) -> None:
    """`op: delete` ⇒ `status = 'archived'`, KHÔNG `DELETE` — bản ghi có thể đã lên
    Qdrant và cần đường gỡ. Gỡ NGAY tại đây: đang-published-mà-rời là xếp job purge.
    """
    bang = _BANG[entity]
    them_cot_sub = {"zone": ", zone_code", "project": ", name"}.get(entity, "")
    them_cot_ra = {"zone": ", cu.zone_code", "project": ", cu.name"}.get(entity, "")
    hang = await conn.fetchrow(
        f"""UPDATE tenant_data.{bang} t
               SET status = 'archived', updated_at = now()
              FROM (SELECT id, status, project_code{them_cot_sub} FROM tenant_data.{bang}
                     WHERE tenant_id = portal.current_tenant() AND external_id = $1
                       FOR UPDATE) cu
             WHERE t.id = cu.id
         RETURNING t.id, cu.status AS status_cu, cu.project_code{them_cot_ra}""",  # noqa: S608 — bảng từ _BANG
        external_id,
    )
    if hang is not None and hang["status_cu"] == "published":
        await _xep_purge(
            conn,
            tenant_id,
            entity=entity,
            record_id=hang["id"],
            project_code=hang["project_code"],
            zone_code=hang["zone_code"] if entity == "zone" else None,
        )
        if entity == "project":
            await enqueue_web_purge(conn, tenant_id=tenant_id, actor="ingest", project_name=str(hang["name"] or ""))


async def _sync_tour_360(conn: asyncpg.Connection, tenant_id: str, *, external_id: str) -> None:
    """`link_360` → một hàng `media` tour_360, đọc TỪ hàng vừa ghi chứ không từ payload.

    Đọc lại từ DB vì payload có thể là upsert một phần: thiếu `link_360` trong lô này không
    có nghĩa là khách muốn xoá tour. Trước 2026-08-17 đường này không tồn tại — chỉ hai route
    giao diện gọi sync, nên 25 dự án về bằng cổng API có link mà không hàng nào (D16 câm).

    Chạy MỖI lượt upsert project, nên `sync_tour_360` chỉ được đụng hàng tour do nền tảng
    sinh (`external_id IS NULL`) — hàng `tour_360` adapter tự đẩy phải sống sót (2026-08-25).
    """
    from portal.modules.realestate.contracts import sync_tour_360

    row = await conn.fetchrow(
        "SELECT project_code, name, coalesce(link_360, '') AS link FROM tenant_data.projects "
        " WHERE tenant_id = portal.current_tenant() AND external_id = $1",
        external_id,
    )
    if row is None:
        return
    ma_du_an = str(row["project_code"])
    moi, da_xoa = await sync_tour_360(
        conn,
        tenant_id,
        project_code=ma_du_an,
        link=str(row["link"]),
        ten_du_an=str(row["name"] or ""),
    )
    if moi is not None:
        await dat_viec_nap(
            conn, tenant_id=tenant_id, actor="ingest", entity="media", record_id=moi, project_code=ma_du_an
        )
    if da_xoa is not None:
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_DELETE_INDEX,
            actor="ingest",
            payload={"vertical": "real_estate", "entity": "media", "record_id": da_xoa},
        )


def _qua_viec_thumb(entity: Entity, cot: dict[str, object]) -> bool:
    """Bản ghi còn một chặng trước khi nạp được, nên đi qua việc thumb.

    Ảnh/video cần bản nhỏ; tài liệu chỉ có tệp cần bóc chữ. Việc thumb TỰ nối sang việc
    nạp khi xong — đặt song song thì nạp có thể chạy trước và point mang khoá thumb rỗng.
    """
    if entity == "media":
        return cot.get("content_type") in ("image", "video")
    if entity == "document":
        # Có tệp là qua chặng bóc, BẤT KỂ `body`: adapter của khách hay đặt siêu dữ liệu
        # («Phạm vi… Hiệu lực…») vào `body`, và luật cũ đọc nó thành «khách đã gửi nội
        # dung» rồi bỏ qua PDF. `handle_enrich` mới là chỗ quyết định có bóc thật không.
        return bool(str(cot.get("file_url") or "").strip())
    return False


async def dam_bao_collection(conn: asyncpg.Connection, tenant_id: str) -> int | None:
    """Xếp việc dựng 2 collection Qdrant nếu workspace này chưa từng được dựng.

    VÌ SAO Ở ĐÂY chứ không ở `workspace.tao()`: `core.jobs.enqueue` đòi tenant của job
    khớp tenant HIỆU LỰC của kết nối, và giao dịch tạo workspace không scope vào tenant
    nó vừa sinh ra — gọi ở đó nổ `RuntimeError`. Đường nạp thì đã nằm sẵn trong
    `tenant_conn(pool, tenant_id)`, nên chuỗi tin cậy giữ nguyên.

    Đặt ở đây còn vá được workspace CŨ: những tenant tạo trước 2026-08-18 chưa hề có
    collection, và trước bản này đường duy nhất dựng chúng là nút «Đồng bộ tri thức».

    MỘT LẦN MỖI WORKSPACE: dò theo `kind` bất kể trạng thái, không chỉ `queued`. Khách
    đẩy delta mỗi 5 phút mà xếp mỗi lô là rác hàng đợi. `control.jobs` KHÔNG có RLS nên
    vị từ `tenant_id` phải viết tay — thiếu nó là đọc nhầm job của tenant khác rồi im
    lặng bỏ qua việc dựng.
    """
    if await conn.fetchval(
        "SELECT 1 FROM control.jobs WHERE tenant_id = $1 AND kind = $2 LIMIT 1", tenant_id, KIND_PROVISION
    ):
        return None
    return await dat_viec_provision(conn, tenant_id=tenant_id, actor="ingest")


async def _xep_nap(
    conn: asyncpg.Connection, tenant_id: str, *, entity: Entity, record_id: int, cot: dict[str, object]
) -> None:
    """Bản ghi vừa chiếu ⇒ đặt việc nạp — cùng luật đường giao diện.

    `units` không nhúng (`verticals/real_estate.py`) nên không có gì để đặt. `entity`
    truyền đi là TÊN BẢNG: `modules/kb` dùng `documents`/`media`, không phải số ít.
    """
    if entity == "unit":
        return
    ma_du_an = str(cot.get("project_code") or "")
    if _qua_viec_thumb(entity, cot):
        await dat_viec_thumb(
            conn,
            tenant_id=tenant_id,
            actor="ingest",
            entity=_BANG[entity],
            record_id=record_id,
            project_code=ma_du_an,
            tu_duyet=entity == "document",
        )
        return
    await dat_viec_nap(
        conn,
        tenant_id=tenant_id,
        actor="ingest",
        entity=_BANG[entity],
        record_id=record_id,
        project_code=ma_du_an,
    )


async def chieu_mot(
    conn: asyncpg.Connection, tenant_id: str, *, entity: Entity, external_id: str, op: str, data: dict
) -> None:
    """Chiếu MỘT bản ghi. Ném `ChuaGiaiDuocCha` nếu còn nợ cha.

    Gọi từ HAI đường: đường nóng (payload vừa qua `kiem()` ở service) và đường
    nhặt-con-đang-chờ (payload đọc lại từ bản thô). KIỂM LẠI cho cả hai: bản thô
    lưu đúng như khách gửi, nên chiếu lại sau khi sửa projector cũng chạy đúng
    phép kiểm hiện hành; `kiem()` là hàm thuần trên dict nhỏ — rẻ."""
    bang = _BANG[entity]

    if op == "delete":
        await _xoa_mem(conn, tenant_id, entity, external_id)
        return

    cot, loi = kiem(entity, data)
    if loi:
        raise RuntimeError(f"payload đã lưu không qua được phép kiểm: {[e.truong for e in loi]}")

    cot.update(await _giai_cha(conn, entity, data))

    if entity == "media":
        cot["public_url"] = public_url_of(str(cot.get("media_url") or ""))

    if entity == "project":
        ma = await repo.project_code_theo_ma_ngoai(conn, external_id)
        goi_y = str(data.get("code") or "").strip()
        cot["project_code"] = ma if ma is not None else await next_project_code(conn, slug_code(goi_y or external_id))
    elif entity == "zone":
        hien = await repo.zone_theo_ma_ngoai(conn, external_id)
        cot["zone_code"] = (
            hien["zone_code"]
            if hien is not None
            else await next_zone_code(conn, str(cot["project_code"]), slug_code(external_id))
        )

    ve_mac_dinh = tuple(c for c in _COT_HOP_DONG[entity] + _COT_CHA_TUY_CHON[entity] if c not in cot)

    them_cot = {"zone": ", zone_code", "project": ", name"}.get(entity, "")
    hien_trang = await conn.fetchrow(
        f"SELECT id, status, project_code{them_cot} FROM tenant_data.{bang} "  # noqa: S608 — bảng từ _BANG
        f"WHERE tenant_id = portal.current_tenant() AND external_id = $1",
        external_id,
    )
    record_id = await _upsert(
        conn, bang=bang, tenant_id=tenant_id, external_id=external_id, cot=cot, ve_mac_dinh=ve_mac_dinh
    )
    if entity == "project":
        await _sync_tour_360(conn, tenant_id, external_id=external_id)
        if cot.get("status") == "published" and (hien_trang is None or hien_trang["status"] != "published"):
            await enqueue_web_project(conn, tenant_id=tenant_id, actor="ingest", project_code=cot["project_code"])
        if hien_trang is not None and hien_trang["status"] == "published":
            ten_cu = str(hien_trang["name"] or "")
            doi_ten = bool(cot.get("name")) and cot["name"] != ten_cu
            if cot.get("status") != "published" or doi_ten:
                # Hồ sơ dữ liệu ngoài khoá theo TÊN — gỡ công bố hay đổi tên đều phải dọn bản cũ.
                await enqueue_web_purge(conn, tenant_id=tenant_id, actor="ingest", project_name=ten_cu)
            if doi_ten and cot.get("status") == "published":
                await enqueue_web_project(conn, tenant_id=tenant_id, actor="ingest", project_code=cot["project_code"])
    if hien_trang is not None and hien_trang["status"] == "published" and cot.get("status") != "published":
        await _xep_purge(
            conn,
            tenant_id,
            entity=entity,
            record_id=hien_trang["id"],
            project_code=hien_trang["project_code"],
            zone_code=hien_trang["zone_code"] if entity == "zone" else None,
        )
        return

    await _xep_nap(conn, tenant_id, entity=entity, record_id=record_id, cot=cot)
