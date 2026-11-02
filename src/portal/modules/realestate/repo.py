"""SQL của module realestate — 5 bảng KB BĐS (`docs/build_module_knowledgebase/02a §4`).

Mọi hàm nhận `conn` từ caller. `projects`/`zones`/`units`/`documents`/`media` đều
ở `tenant_data`, nên MỌI truy vấn phải đi qua một kết nối đã ở trong `tenant_conn()`
(`portal.core.db.session`) — đó là điều kiện cách ly, không phải chi tiết cài đặt
của module này.

⚠️ KHÔNG CÒN RLS ĐỠ PHÍA SAU — ĐỌC TRƯỚC KHI THÊM MỘT CÂU SQL VÀO ĐÂY.
Bản trước của file này lọc tenant bằng policy RLS `tenant_isolation` ở tầng DB
(`USING (tenant_id = portal.current_tenant())`), nên SQL ở đây cố ý KHÔNG mang vị
từ tenant nào. Migration `0909_bo_rls_toan_bo` đã dỡ policy đó khỏi TOÀN BỘ
`tenant_data`. Từ đó, một câu `WHERE id = $1` trần đọc/sửa/xoá được hàng của MỌI
khách hàng — không có lớp nào ở DB chặn lại nữa.

Nên bây giờ MỌI câu SQL ở đây tự mang vị từ `_CACH_LY` (`= portal.current_tenant()`)
— chính xác cái vị từ mà policy đã bị dỡ từng áp, chỉ là viết ở tầng app. Đó là lý
do các hàm VẪN không nhận tham số `tenant_id` (trừ `chen_*`): tenant hiệu lực đã
nằm sẵn trong kết nối do `tenant_conn()` đặt và tự kiểm chứng, nên thêm tham số chỉ
tạo thêm một chỗ để truyền sai. Cổng canh: `tests/isolation/test_loc_tenant_o_tang_app.py`.

Hai đường đọc CỐ Ý tách biệt, không gộp (xem `02 §3`, `02 §7`):
  - `liet_ke_*`/`doc_*`   — đọc CHO PORTAL (CMS). KHÔNG lọc `status`: người dùng
    phải thấy bản `draft` của chính mình để sửa tiếp.
  - `*_cho_agent`         — đọc CHO AGENT. JOIN lọc CẢ `project.status` (anchor)
    LẪN `status` của chính bảng — cascade: anchor chưa `published` thì con biến
    mất khỏi mọi kết quả agent, dù bản thân con đã `published`. `documents`/`media`
    (duy nhất có bản cấp-tenant) còn gộp thêm `project_code = "__ALL__"`.

VÌ SAO GHÉP TÊN CỘT VÀO SQL: payload là `dict` động (form CMS gửi vài trường,
form khác gửi nhiều hơn) nên danh sách cột không viết cứng theo lời gọi được.
An toàn nhờ `_kiem_payload()` — tên nào không thuộc danh sách trắng `COT_*` của
`contracts.py` thì raise, không tới được đây. GIÁ TRỊ luôn đi bằng tham số `$n`.
"""

import asyncpg

from portal.modules.realestate.contracts import (
    COT_CAN,
    COT_DU_AN,
    COT_MEDIA,
    COT_PHAN_KHU,
    COT_TAI_LIEU,
    COT_TOA,
    GIOI_HAN_OFFSET,
    GIOI_HAN_TRANG,
    SENTINEL_TENANT,
    TRANG_MAC_DINH,
    Entity,
    LoiTruongLa,
    doc_con_tro,
)
from portal.modules.realestate.hot_words import extract_hot_words

__all__ = [
    "chen_can",
    "chen_du_an",
    "chen_media",
    "chen_phan_khu",
    "chen_toa",
    "chen_tai_lieu",
    "can_cho_agent",
    "dem_anh_theo_danh_muc",
    "dem_can",
    "dem_du_an",
    "dem_media",
    "dem_phan_khu",
    "dem_tai_lieu",
    "doc_can",
    "doc_du_an",
    "doc_media",
    "doc_phan_khu",
    "doc_tai_lieu",
    "doc_toa",
    "dong_bo_hot_word",
    "du_an_cho_agent",
    "facet_can",
    "liet_ke_can",
    "liet_ke_can_cho_agent",
    "liet_ke_du_an",
    "liet_ke_media",
    "liet_ke_media_cho_agent",
    "liet_ke_phan_khu",
    "liet_ke_phan_khu_cho_agent",
    "liet_ke_tai_lieu",
    "liet_ke_tai_lieu_cho_agent",
    "liet_ke_toa",
    "sua_can",
    "sua_du_an",
    "sua_media",
    "sua_phan_khu",
    "sua_tai_lieu",
    "sua_toa",
    "sync_tour_360",
    "tat_cho_duyet",
    "xoa_can",
    "xoa_du_an",
    "xoa_media",
    "xoa_phan_khu",
    "xoa_tai_lieu",
    "xoa_toa",
]

_BANG: dict[Entity, str] = {
    "project": "tenant_data.projects",
    "zone": "tenant_data.zones",
    "building": "tenant_data.buildings",
    "unit": "tenant_data.units",
    "document": "tenant_data.documents",
    "media": "tenant_data.media",
}

_COT_CHO_PHEP: dict[Entity, frozenset[str]] = {
    "project": COT_DU_AN,
    "zone": COT_PHAN_KHU,
    "building": COT_TOA,
    "unit": COT_CAN,
    "document": COT_TAI_LIEU,
    "media": COT_MEDIA,
}

_COT_RA: dict[Entity, str] = {
    "project": (
        "id, project_code, name, category, region, address, investor, developer, "
        "total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities, "
        "ownership_form, handover_standard, total_investment_vnd, sale_phase, overview, "
        "link_360, cover_media_id, map_media_id, status, created_at, updated_at, "
        "total_units, num_buildings, management_fee_vnd_m2, parking_car_fee_vnd, parking_moto_fee_vnd"
    ),
    "zone": (
        "id, project_code, zone_code, name, category, product_scale, overview, "
        "cover_media_id, map_media_id, status, created_at, updated_at, "
        "sale_phase, note, amenities, num_buildings, total_units"
    ),
    "building": (
        "id, project_code, zone_code, building_code, name, num_floors, num_basements, units_per_floor, "
        "elevators_passenger, elevators_service, car_slots, moto_slots, ceiling_height_m, facing, "
        "sale_phase, amenities, overview, status, created_at, updated_at"
    ),
    "unit": (
        "id, project_code, zone_code, unit_code, product_type, bedrooms, block, floor, "
        "num_floors, direction, area_built_m2, area_wall_m2, area_land_m2, price_vnd, "
        "price_per_m2_vnd, sale_status, image_url, status, created_at, updated_at, "
        "views, is_corner, open_sides, bathrooms, handover_condition, layout_media_id, "
        "hr_balcony_m2, hr_loggia_m2, lr_frontage_m, lr_depth_m, lr_road_width_m"
    ),
    "document": "id, project_code, title, body, body_auto, file_url, body_cho_duyet, status, created_at, updated_at",
    "media": (
        "id, project_code, zone_code, unit_code, content_type, category, caption, caption_auto, file_name, "
        "media_url, thumb_url, content_hash, uploaded_by, status, created_at, updated_at"
    ),
}

_KHOA_DUY_NHAT: dict[Entity, tuple[str, ...]] = {
    "project": ("project_code",),
    "zone": ("project_code", "zone_code"),
    "building": ("project_code", "building_code"),
}


def _cach_ly(tien_to: str = "") -> str:
    """Vị từ cách ly tenant — dán vào MỌI câu SQL chạm `tenant_data` ở file này.

    Nội dung y hệt policy RLS `tenant_isolation` mà `0909` đã dỡ, nên hành vi
    không đổi so với thời còn RLS: hàng của tenant khác đơn giản là "không thấy",
    không phải một trường hợp lỗi cần code xử lý riêng.

    Dùng `portal.current_tenant()` chứ KHÔNG thêm tham số `$n`: giá trị đó đã
    được `tenant_conn()` đặt bằng `set_config('app.tenant_id', …, is_local => true)`
    VÀ kiểm chứng lại ngay sau đó. Truyền `tenant_id` xuống đây bằng tham số là
    mở lại đúng lỗ mà `core/db/session.py` cảnh báo — một chỗ để ai đó lỡ nối
    tenant_id lấy từ path/query/body của request.

    `tien_to` là alias bảng khi câu SQL có JOIN (`"z."`, `"p."`) — bắt buộc ở đó,
    vì cả hai bảng đều có cột `tenant_id` và Postgres sẽ báo mơ hồ.
    """
    return f"{tien_to}tenant_id = portal.current_tenant()"


def _menh_de_keyset(tien_to: str, n: int) -> str:
    """Điều kiện "đứng sau hàng có id = `sau`" cho `ORDER BY {tien_to}id DESC`.

    `${n}::bigint IS NULL` xử lý trang ĐẦU (không có cursor) NGAY TRONG CÙNG một
    câu SQL — không tách thành hai nhánh Python, vì hai câu SQL gần-giống-nhau
    sẽ lệch nhau ở lần sửa bộ lọc tiếp theo mà không ai để ý.

    `id` là khoá keyset DUY NHẤT (bigserial, bất biến) — KHÔNG dùng `updated_at`
    (đổi mỗi lần sửa, làm hàng "nhảy" và có thể bị lật qua giữa hai lần lấy trang).
    """
    return f"(${n}::bigint IS NULL OR {tien_to}id < ${n}::bigint)"


def _voi_tien_to(cot_ra: str, tien_to: str) -> str:
    """`"a, b, c"` → `"t.a, t.b, t.c"` — dùng khi JOIN cần alias bảng để hết mơ hồ."""
    return ", ".join(f"{tien_to}{c.strip()}" for c in cot_ra.split(","))


def _sau(cursor: str | None) -> int | None:
    return doc_con_tro(cursor) if cursor else None


def _gioi_han(limit: int) -> int:
    """Kẹp `limit` vào `(0, GIOI_HAN_TRANG]` — trần cứng, xem contracts.py."""
    return max(1, min(limit, GIOI_HAN_TRANG))


def _gioi_han_offset(offset: int) -> int:
    """Kẹp `offset` vào `[0, GIOI_HAN_OFFSET]` — cùng khuôn `_gioi_han()`.

    Router đã kẹp bằng `Query(..., le=GIOI_HAN_OFFSET)` (I-1, review vòng cuối),
    nhưng repo không tin caller đã kẹp đúng — đúng lý do `_gioi_han()` tồn tại
    song song với `_LIMIT_Q` ở router: hai lưới độc lập, một chỗ gọi trực tiếp
    (test, job nội bộ) mà bỏ qua Query vẫn không vỡ `DataError` ở Postgres."""
    return max(0, min(offset, GIOI_HAN_OFFSET))


def _kiem_payload(entity: Entity, payload: dict) -> list[str]:
    """Trả danh sách cột (đã sort — để `$n` trong `_upsert` khớp đúng thứ tự) sẽ ghi.

    RAISE `LoiTruongLa` chứ không lọc-bỏ-âm-thầm: nguồn là payload người dùng vừa
    gửi, và im lặng bỏ một trường họ tưởng đã lưu là mất dữ liệu không ai biết.
    """
    cho_phep = _COT_CHO_PHEP[entity]
    la = [k for k in payload if k not in cho_phep]
    if la:
        raise LoiTruongLa(f"trường không hợp lệ: {sorted(la)}")
    return sorted(payload)


# ─── Ghi — MỘT đường cho chèn lẫn sửa ───────────────────────────────────────


async def _upsert(
    conn: asyncpg.Connection,
    entity: Entity,
    id_: int | None,
    payload: dict,
    *,
    tenant_id: str = "",
) -> asyncpg.Record | None:
    """`id_ is None` → INSERT (`chen_*`). `id_` là số → UPDATE theo `id` (`sua_*`).

    MỘT hàm cho cả hai, không phải hai đường code riêng: hai đường riêng cho hai
    việc gần giống nhau là hai chỗ để lệch nhau, và chỗ lệch điển hình đúng là
    `updated_at` (xem chú thích `clock_timestamp()` dưới đây) — bài học đã trả giá
    ở bản M4a trước (`f2d9d6f`).

    Nhánh UPDATE KHÔNG nhận `tenant_id` như `chen_*`: nó lọc bằng `_cach_ly()`
    ngay trong `WHERE`, nên id của tenant khác khớp 0 hàng và hàm trả `None` —
    không phải một trường hợp lỗi cần code xử lý riêng, chỉ là "không thấy gì để
    sửa". Trước `0909` chính RLS làm việc này ở tầng USING; nay là vị từ ở đây.
    """
    cot = _kiem_payload(entity, payload)
    gia_tri = [payload[c] for c in cot]
    cot_ra = _COT_RA[entity]
    bang = _BANG[entity]

    if id_ is None:
        if not tenant_id:
            raise ValueError("chen_* cần tenant_id — INSERT không có RLS nào tự điền cột này")
        dat_cho = ", ".join(f"${i + 2}" for i in range(len(cot)))
        cot_chen = ", ".join(cot)
        them_cot = f", {cot_chen}" if cot else ""
        them_dat_cho = f", {dat_cho}" if cot else ""
        them_cot += ", updated_at"
        them_dat_cho += ", clock_timestamp()"

        xung_dot = ""
        if entity in _KHOA_DUY_NHAT:
            cac_cot_khoa = ", ".join(("tenant_id", *_KHOA_DUY_NHAT[entity]))
            xung_dot = f"ON CONFLICT ({cac_cot_khoa}) DO NOTHING"

        return await conn.fetchrow(
            f"""INSERT INTO {bang} (tenant_id{them_cot})
                     VALUES ($1{them_dat_cho})
                {xung_dot}
                RETURNING {cot_ra}""",
            tenant_id,
            *gia_tri,
        )

    if not cot:
        return await conn.fetchrow(f"SELECT {cot_ra} FROM {bang} WHERE id = $1 AND {_cach_ly()}", id_)

    set_menh_de = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cot))
    return await conn.fetchrow(
        f"""UPDATE {bang} SET {set_menh_de}, updated_at = clock_timestamp()
             WHERE id = $1 AND {_cach_ly()}
         RETURNING {cot_ra}""",
        id_,
        *gia_tri,
    )


# ─── Dự án (`projects` — anchor) ────────────────────────────────────────────


def _loc_du_an() -> str:
    """Filter (KHÔNG kèm `_cach_ly()`) của danh sách dự án — dùng cho CẢ câu lấy
    hàng lẫn câu đếm, luôn ghép SAU `{_cach_ly()} AND` ở nơi gọi.

    Một hàm chứ hai câu SQL viết rời: `total` đếm theo một mệnh đề khác câu lấy
    hàng là lỗi kinh điển của phân trang có số — người dùng thấy "237 hàng" rồi
    bấm trang cuối ra rỗng. Tham số filter chiếm `$1..$3`; câu lấy hàng nối thêm
    keyset/limit/offset từ `$4`.

    ⚠️ `_cach_ly()` KHÔNG lồng vào bên trong hàm này (I-2, review vòng cuối):
    cổng `test_moi_cau_sql_cham_tenant_data_deu_mang_vi_tu_tenant` quét mã nguồn
    của MỖI mảnh `{...}` trong f-string (`ast.unparse`), không quét chuỗi nó trả
    về lúc chạy — lồng một tầng qua `_loc_du_an()` làm gate thấy `_loc_du_an()`
    trong mã nguồn, không thấy `_cach_ly`/`current_tenant(` ở đâu cả, nên báo
    THIẾU dù SQL thật sự vẫn lọc đúng. Gọi `_cach_ly()` NGAY TRONG literal ở
    `liet_ke_du_an`/`dem_du_an` để gate đọc được nó trực tiếp.
    """
    return """($1 = '' OR name ILIKE '%' || $1 || '%' OR project_code ILIKE '%' || $1 || '%')
               AND ($2 = '' OR region = $2)
               AND project_code <> $3"""


async def liet_ke_du_an(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    region: str = "",
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Đọc CHO PORTAL — KHÔNG lọc `status` (người dùng phải thấy bản `draft` của
    chính mình). Trả TỐI ĐA `limit` hàng; người gọi hỏi thừa 1 hàng để biết còn
    trang sau hay không (cùng nếp bản cũ).

    ẨN `__ALL__` (review vòng cuối, Critical A): row hệ thống này KHÔNG phải một
    dự án — nó chỉ là điểm neo FK cho tài liệu/media cấp tenant (`02 §2`), không
    có `region`/`overview`, không có zones/units. Liệt kê nó chung với dự án thật
    là cách người dùng VÔ TÌNH tới được nút Xoá/đổi `status` của nó (`router.py:
    _sentinel_duoc_bao_ve` giải thích thiệt hại) và là một dòng "Chung / toàn
    tenant" vô nghĩa trong danh sách dự án của CMS.

    Lọc Ở ĐÂY (SQL), KHÔNG lọc sau khi fetch ở router: bỏ hàng sau khi đã lấy
    làm lệch phép đếm phân trang keyset (`router._trang` suy "còn trang sau" từ
    SỐ HÀNG nhận được) — một trang có thể trả ít hơn `limit` hàng dù còn dữ liệu.
    Tab "Tài liệu chung" của CMS vẫn tới được row này bằng ĐÚNG mã
    (`GET/PATCH /projects/__ALL__`, `_tim_du_an`/`doc_du_an` không lọc gì) —
    chỉ DANH SÁCH là chỗ nó không nên xuất hiện.

    `offset` và `cursor` là hai lối phân trang SONG SONG, không trộn: `cursor`
    cho keyset (client cũ), `offset` cho bảng có số trang. Gửi cả hai thì cả hai
    áp — vô nghĩa nhưng không sai, và router không cho ca đó xảy ra.
    """
    return await conn.fetch(
        f"""SELECT {_COT_RA["project"]} FROM tenant_data.projects
             WHERE {_cach_ly()} AND {_loc_du_an()}
               AND {_menh_de_keyset("", 4)}
             ORDER BY id DESC
             LIMIT $5 OFFSET $6""",
        tim,
        region,
        SENTINEL_TENANT,
        _sau(cursor),
        _gioi_han(limit),
        _gioi_han_offset(offset),
    )


async def dem_du_an(conn: asyncpg.Connection, *, tim: str = "", region: str = "") -> int:
    """Tổng số dự án khớp bộ lọc — `total` của `TrangDuAn`.

    KHÔNG nhận `cursor`/`offset`: `total` là tổng của cả tập, không phải của một
    trang. Dùng CÙNG `_loc_du_an()` với câu lấy hàng."""
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.projects WHERE {_cach_ly()} AND {_loc_du_an()}",
        tim,
        region,
        SENTINEL_TENANT,
    )


async def doc_du_an(conn: asyncpg.Connection, id_: int) -> asyncpg.Record | None:
    """Đọc CHO PORTAL 1 dự án theo `id` — không lọc `status`."""
    return await conn.fetchrow(
        f"SELECT {_COT_RA['project']} FROM tenant_data.projects WHERE id = $1 AND {_cach_ly()}", id_
    )


async def du_an_cho_agent(conn: asyncpg.Connection, project_code: str) -> asyncpg.Record | None:
    """Đọc CHO AGENT: `projects` LÀ anchor, không có cha để cascade — chỉ cần
    chính nó `published`."""
    return await conn.fetchrow(
        f"""SELECT {_COT_RA["project"]} FROM tenant_data.projects
             WHERE {_cach_ly()} AND project_code = $1 AND status = 'published'""",
        project_code,
    )


async def chen_du_an(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record | None:
    """`None` nếu `project_code` đã tồn tại (xem `_upsert`, `_KHOA_DUY_NHAT`)."""
    return await _upsert(conn, "project", None, payload, tenant_id=tenant_id)


async def sua_du_an(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    """`None` nếu `id` không thuộc tenant hiện tại (RLS lọc 0 hàng)."""
    return await _upsert(conn, "project", id_, payload)


async def dong_bo_hot_word(conn: asyncpg.Connection, tenant_id: str, project_id: int, name: str) -> None:
    """Xoá hết hot word cũ của `project_id` rồi ghi lại theo `name` hiện tại.

    Xoá-rồi-ghi (không `UPDATE` từng dòng) vì tập hot word suy ra lại HOÀN TOÀN
    từ `name` mỗi lần — không có khái niệm "sửa một hot word", chỉ có "tên đổi
    thì tập hot word đổi theo". `ON CONFLICT (tenant_id, hot_word) DO NOTHING`:
    hot word đã thuộc project KHÁC trong cùng tenant thì project đó giữ quyền
    sở hữu (`project_hot_words_tenant_word_key`, migration `0963`) — project
    tạo/đổi tên trước thắng, xem docstring migration.
    """
    tu = extract_hot_words(name)
    await conn.execute(f"DELETE FROM tenant_data.project_hot_words WHERE project_id = $1 AND {_cach_ly()}", project_id)
    if tu:
        await conn.executemany(
            """
            INSERT INTO tenant_data.project_hot_words (tenant_id, project_id, hot_word)
            VALUES ($1, $2, $3)
            ON CONFLICT (tenant_id, hot_word) DO NOTHING
            """,
            [(tenant_id, project_id, w) for w in tu],
        )


async def xoa_du_an(conn: asyncpg.Connection, id_: int) -> bool:
    """`ON DELETE CASCADE` (migration `0400`) dọn theo cả cây con — zones/units/
    documents/media của dự án này biến mất cùng lượt xoá."""
    kq = await conn.execute(f"DELETE FROM tenant_data.projects WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Phân khu (`zones`) ─────────────────────────────────────────────────────


def _loc_phan_khu() -> str:
    """Filter (KHÔNG kèm `_cach_ly()`, xem docstring `_loc_du_an`) của danh sách
    phân khu — dùng chung với `dem_phan_khu()`. Filter chiếm `$1`."""
    return "($1 = '' OR project_code = $1)"


# Số căn đã nhập của một phân khu; câu ngoài phải đặt bí danh `z` cho `zones`.
SO_CAN_CUA_PHAN_KHU = """(SELECT count(*) FROM tenant_data.units u
                          WHERE u.tenant_id = portal.current_tenant() AND u.project_code = z.project_code
                            AND u.zone_code = z.zone_code) AS unit_count"""


async def liet_ke_phan_khu(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT {_COT_RA["zone"]}, {SO_CAN_CUA_PHAN_KHU} FROM tenant_data.zones z
             WHERE {_cach_ly()} AND {_loc_phan_khu()}
               AND {_menh_de_keyset("", 2)}
             ORDER BY id DESC
             LIMIT $3 OFFSET $4""",
        project_code,
        _sau(cursor),
        _gioi_han(limit),
        _gioi_han_offset(offset),
    )


async def dem_phan_khu(conn: asyncpg.Connection, *, project_code: str = "") -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.zones WHERE {_cach_ly()} AND {_loc_phan_khu()}", project_code
    )


async def doc_phan_khu(conn: asyncpg.Connection, id_: int) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {_COT_RA['zone']} FROM tenant_data.zones WHERE id = $1 AND {_cach_ly()}", id_)


async def liet_ke_phan_khu_cho_agent(
    conn: asyncpg.Connection,
    project_code: str,
    *,
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
) -> list[asyncpg.Record]:
    """CASCADE (`02 §3`): `project` (anchor) VÀ `zone` đều phải `published`. Khác
    `liet_ke_phan_khu` (đọc cho portal) — hàm đó không lọc `status`.

    `_cach_ly("z.")` ghim MỘT bảng là đủ cho cả hai: `ON p.tenant_id = z.tenant_id`
    đã buộc `p` cùng tenant với `z`. Ghim `z` chứ không `p` vì `z` là bảng lái —
    `p` chỉ có mặt để kiểm `status` của anchor.

    KHÔNG bỏ vị từ này vì "JOIN đã khớp tenant rồi": JOIN chỉ buộc hai bảng CÙNG
    một tenant, không buộc tenant đó là tenant đang đăng nhập. Thiếu nó, ai biết
    `project_code` của khách hàng khác là đọc trọn dữ liệu của họ."""
    return await conn.fetch(
        f"""SELECT {_voi_tien_to(_COT_RA["zone"], "z.")}
              FROM tenant_data.zones z
              JOIN tenant_data.projects p
                ON p.tenant_id = z.tenant_id AND p.project_code = z.project_code
             WHERE {_cach_ly("z.")}
               AND z.project_code = $1 AND p.status = 'published' AND z.status = 'published'
               AND {_menh_de_keyset("z.", 3)}
             ORDER BY z.id DESC
             LIMIT $2""",
        project_code,
        _gioi_han(limit),
        _sau(cursor),
    )


async def chen_phan_khu(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record | None:
    """`None` nếu `(project_code, zone_code)` đã tồn tại."""
    return await _upsert(conn, "zone", None, payload, tenant_id=tenant_id)


async def sua_phan_khu(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    return await _upsert(conn, "zone", id_, payload)


async def xoa_phan_khu(conn: asyncpg.Connection, id_: int) -> bool:
    """`ON DELETE CASCADE` dọn theo `units`/`media` gắn `zone_code` này."""
    kq = await conn.execute(f"DELETE FROM tenant_data.zones WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Toà (`buildings`) ──────────────────────────────────────────────────────

# Căn trỏ toà qua `units.block` (khoá ngoại từ `0979`, giá trị đã chuẩn hoá).
_SO_CAN_CUA_TOA = """(SELECT count(*) FROM tenant_data.units u
                      WHERE u.tenant_id = portal.current_tenant() AND u.project_code = b.project_code
                        AND u.block = b.building_code) AS unit_count"""


async def liet_ke_toa(conn: asyncpg.Connection, *, project_code: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT {_voi_tien_to(_COT_RA["building"], "b.")}, {_SO_CAN_CUA_TOA}
              FROM tenant_data.buildings b
             WHERE {_cach_ly("b.")} AND b.project_code = $1
             ORDER BY b.zone_code NULLS LAST, b.building_code""",
        project_code,
    )


async def doc_toa(conn: asyncpg.Connection, *, project_code: str, building_code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""SELECT {_voi_tien_to(_COT_RA["building"], "b.")}, {_SO_CAN_CUA_TOA}
              FROM tenant_data.buildings b
             WHERE {_cach_ly("b.")} AND b.project_code = $1 AND b.building_code = $2""",
        project_code,
        building_code,
    )


async def chen_toa(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record | None:
    """`None` nếu `(project_code, building_code)` đã tồn tại."""
    row = await _upsert(conn, "building", None, payload, tenant_id=tenant_id)
    if row is None:
        return None
    return await doc_toa(conn, project_code=row["project_code"], building_code=row["building_code"])


async def sua_toa(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    row = await _upsert(conn, "building", id_, payload)
    if row is None:
        return None
    return await doc_toa(conn, project_code=row["project_code"], building_code=row["building_code"])


async def xoa_toa(conn: asyncpg.Connection, id_: int) -> bool:
    kq = await conn.execute(f"DELETE FROM tenant_data.buildings WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Căn (`units`) ──────────────────────────────────────────────────────────


def _loc_can() -> str:
    """Filter (KHÔNG kèm `_cach_ly()`, xem docstring `_loc_du_an`) — chiếm `$1..$7`.

    ⚠️ ĐỔI SỐ Ở ĐÂY LÀ ĐỔI SỐ Ở BA CHỖ: `_menh_de_keyset` và `LIMIT/OFFSET` của
    `liet_ke_can` đếm tiếp từ số cuối của hàm này. Lệch một số thì câu vẫn chạy,
    chỉ lọc sai — không lỗi nào phát ra."""
    return """($1 = '' OR project_code = $1)
               AND ($2 = '' OR zone_code    = $2)
               AND ($3 = '' OR product_type = $3)
               AND ($4 = '' OR sale_status  = $4)
               AND ($5 = '' OR direction    = $5)
               AND ($6 = '' OR unit_code ILIKE '%' || $6 || '%')
               AND ($7 = '' OR status       = $7)"""


_TEN_PHAN_KHU = f"""(SELECT z.name FROM tenant_data.zones z
                       WHERE {_cach_ly("z.")} AND z.project_code = units.project_code
                         AND z.zone_code = units.zone_code) AS zone_name"""
"""Tên phân khu của một căn — SUBQUERY chứ không JOIN.

JOIN làm `id` mơ hồ (cả hai bảng đều có), và `_menh_de_keyset`/`_thu_tu_can`/`_loc_can`
đều viết cột trần — sửa chúng để nhận tiền tố là ba chỗ để lệch nhau về sau."""


COT_SAP_XEP_CAN = frozenset({"price_vnd", "bedrooms", "area_built_m2"})
"""Cột người dùng bấm sắp xếp được trên bảng quỹ căn (3 cột số)."""


def _thu_tu_can(sap_xep: str, giam: bool) -> str:
    """`ORDER BY` của danh sách căn.

    ⚠️ TÊN CỘT ĐI THẲNG VÀO SQL — không tham số hoá được (`ORDER BY $1` sắp xếp
    theo một hằng chuỗi, không theo cột). `COT_SAP_XEP_CAN` là thứ DUY NHẤT chặn
    injection ở đây: giá trị lạ rơi về thứ tự mặc định thay vì được ghép vào câu.

    `NULLS LAST` cho CẢ hai chiều, không phải mặc định của Postgres (`NULLS LAST`
    cho ASC, `NULLS FIRST` cho DESC): căn chưa nhập giá không phải căn rẻ nhất,
    và cũng không phải căn đắt nhất — nó là căn chưa biết, nên luôn xuống cuối.

    `id DESC` chốt đuôi để hai căn cùng giá không đổi chỗ nhau giữa hai lần lấy
    trang — thiếu nó thì phân trang có thể bỏ sót hoặc lặp hàng.
    """
    if sap_xep not in COT_SAP_XEP_CAN:
        return "ORDER BY id DESC"
    return f"ORDER BY {sap_xep} {'DESC' if giam else 'ASC'} NULLS LAST, id DESC"


async def liet_ke_can(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    product_type: str = "",
    sale_status: str = "",
    direction: str = "",
    unit_code: str = "",
    status: str = "",
    sap_xep: str = "",
    giam: bool = False,
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    # Keyset ĐỌC ĐƯỢC "hàng sau id X" chỉ khi thứ tự LÀ `id DESC`. Sắp xếp theo
    # giá thì `id < X` không còn nghĩa gì — nó cắt mất một mảng hàng tuỳ ý. Router
    # đã bỏ cursor khi có `sort`, nhưng repo không tin caller (cùng lý do
    # `_gioi_han_offset` tồn tại song song với `_LIMIT_Q`).
    co_sap_xep = sap_xep in COT_SAP_XEP_CAN
    return await conn.fetch(
        f"""SELECT {_COT_RA["unit"]}, {_TEN_PHAN_KHU} FROM tenant_data.units
             WHERE {_cach_ly()} AND {_loc_can()}
               AND {_menh_de_keyset("", 8)}
             {_thu_tu_can(sap_xep, giam)}
             LIMIT $9 OFFSET $10""",
        project_code,
        zone_code,
        product_type,
        sale_status,
        direction,
        unit_code,
        status,
        None if co_sap_xep else _sau(cursor),
        _gioi_han(limit),
        _gioi_han_offset(offset),
    )


async def dem_can(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    product_type: str = "",
    sale_status: str = "",
    direction: str = "",
    unit_code: str = "",
    status: str = "",
) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.units WHERE {_cach_ly()} AND {_loc_can()}",
        project_code,
        zone_code,
        product_type,
        sale_status,
        direction,
        unit_code,
        status,
    )


async def facet_can(conn: asyncpg.Connection, *, project_code: str) -> asyncpg.Record | None:
    """Giá trị `product_type`/`direction` CÓ THẬT trong quỹ căn của một dự án.

    Một câu cho cả hai cột: hai câu riêng là hai vòng mạng cho một dải lọc, và
    chúng có thể nhìn thấy hai ảnh chụp khác nhau của cùng một bảng.

    KHÔNG lọc theo các bộ lọc đang bật — danh sách chọn phải đứng yên khi người
    dùng đổi bộ lọc, nếu không chọn «Chung cư» xong là mục «Biệt thự» biến mất
    khỏi dropdown và không còn đường quay lại.
    """
    return await conn.fetchrow(
        f"""SELECT
                coalesce(array_agg(DISTINCT product_type)
                         FILTER (WHERE product_type <> ''), '{{}}'::text[]) AS product_type,
                coalesce(array_agg(DISTINCT direction)
                         FILTER (WHERE direction IS NOT NULL AND direction <> ''), '{{}}'::text[]) AS direction
              FROM tenant_data.units
             WHERE {_cach_ly()} AND ($1 = '' OR project_code = $1)""",
        project_code,
    )


async def doc_can(conn: asyncpg.Connection, id_: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_COT_RA['unit']}, {_TEN_PHAN_KHU} FROM tenant_data.units WHERE id = $1 AND {_cach_ly()}",
        id_,
    )


async def liet_ke_can_cho_agent(
    conn: asyncpg.Connection,
    project_code: str,
    *,
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
) -> list[asyncpg.Record]:
    """CASCADE: `project` VÀ `unit` đều phải `published`."""
    return await conn.fetch(
        f"""SELECT {_voi_tien_to(_COT_RA["unit"], "u.")}
              FROM tenant_data.units u
              JOIN tenant_data.projects p
                ON p.tenant_id = u.tenant_id AND p.project_code = u.project_code
             WHERE {_cach_ly("u.")}
               AND u.project_code = $1 AND p.status = 'published' AND u.status = 'published'
               AND {_menh_de_keyset("u.", 3)}
             ORDER BY u.id DESC
             LIMIT $2""",
        project_code,
        _gioi_han(limit),
        _sau(cursor),
    )


can_cho_agent = liet_ke_can_cho_agent


async def chen_can(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record:
    """LUÔN tạo hàng mới — `unit_code` KHÔNG unique (`02a §4.3`), nên không có
    khái niệm "đã tồn tại" để double-POST bảo vệ; mỗi lần gọi là 1 căn mới."""
    row = await _upsert(conn, "unit", None, payload, tenant_id=tenant_id)
    assert row is not None  # không entity nào có ON CONFLICT cho "unit"
    doc = await doc_can(conn, int(row["id"]))
    assert doc is not None
    return doc


async def sua_can(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    """Đọc lại sau khi ghi — `_upsert` là hàm dùng chung nên `RETURNING` của nó không
    mang `zone_name`. Thiếu vòng này thì bảng hiện ô phân khu trống ngay sau lúc Lưu."""
    row = await _upsert(conn, "unit", id_, payload)
    return None if row is None else await doc_can(conn, int(row["id"]))


async def xoa_can(conn: asyncpg.Connection, id_: int) -> bool:
    kq = await conn.execute(f"DELETE FROM tenant_data.units WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Tài liệu (`documents`) ─────────────────────────────────────────────────


def _loc_tai_lieu() -> str:
    """Filter (KHÔNG kèm `_cach_ly()`, xem docstring `_loc_du_an`) của danh sách
    tài liệu — dùng chung với `dem_tai_lieu()`. Filter chiếm `$1`."""
    return "($1 = '' OR project_code = $1)"


async def liet_ke_tai_lieu(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Đọc CHO PORTAL — lọc ĐÚNG `project_code` được truyền, KHÔNG tự gộp
    `__ALL__`: CMS có tab riêng ("Tài liệu chung") để biên tập đúng phạm vi đó
    (`mau-form-cms.html`), người biên tập tự chọn scope. Gộp `__ALL__` là việc
    của đường đọc CHO AGENT (`liet_ke_tai_lieu_cho_agent`) — agent luôn cần thấy
    cả hai, portal thì không (tránh danh sách "Tài liệu dự án X" lẫn tài liệu
    của dự án khác một cách khó hiểu)."""
    return await conn.fetch(
        f"""SELECT {_COT_RA["document"]} FROM tenant_data.documents
             WHERE {_cach_ly()} AND {_loc_tai_lieu()}
               AND {_menh_de_keyset("", 2)}
             ORDER BY id DESC
             LIMIT $3 OFFSET $4""",
        project_code,
        _sau(cursor),
        _gioi_han(limit),
        _gioi_han_offset(offset),
    )


async def dem_tai_lieu(conn: asyncpg.Connection, *, project_code: str = "") -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.documents WHERE {_cach_ly()} AND {_loc_tai_lieu()}", project_code
    )


async def doc_tai_lieu(conn: asyncpg.Connection, id_: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_COT_RA['document']} FROM tenant_data.documents WHERE id = $1 AND {_cach_ly()}", id_
    )


async def liet_ke_tai_lieu_cho_agent(
    conn: asyncpg.Connection,
    project_code: str,
    *,
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
) -> list[asyncpg.Record]:
    """CASCADE + `__ALL__` (`02 §2`/`02a §4b`): gộp tài liệu của đúng dự án VÀ
    tài liệu cấp tenant (`project_code = "__ALL__"`). JOIN vẫn đúng cho cả hai
    trường hợp vì `"__ALL__"` LÀ một row `projects` hệ thống seed sẵn
    `status = 'published'` — không cần nhánh SQL riêng cho sentinel."""
    return await conn.fetch(
        f"""SELECT {_voi_tien_to(_COT_RA["document"], "d.")}
              FROM tenant_data.documents d
              JOIN tenant_data.projects p
                ON p.tenant_id = d.tenant_id AND p.project_code = d.project_code
             WHERE {_cach_ly("d.")}
               AND d.project_code IN ($1, $3) AND p.status = 'published' AND d.status = 'published'
               AND {_menh_de_keyset("d.", 4)}
             ORDER BY d.id DESC
             LIMIT $2""",
        project_code,
        _gioi_han(limit),
        SENTINEL_TENANT,
        _sau(cursor),
    )


async def chen_tai_lieu(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record:
    """LUÔN tạo hàng mới — không có khoá nghiệp vụ nào unique trên `documents`."""
    row = await _upsert(conn, "document", None, payload, tenant_id=tenant_id)
    assert row is not None
    return row


async def sua_tai_lieu(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    return await _upsert(conn, "document", id_, payload)


async def tat_cho_duyet(conn: asyncpg.Connection, id_: int) -> bool:
    """Tắt cờ "chữ OCR chờ duyệt". Trả False nếu hàng không mang cờ — nơi gọi phân biệt
    được "vừa duyệt" với "không có gì để duyệt"."""
    kq = await conn.execute(
        f"UPDATE tenant_data.documents SET body_cho_duyet = false, updated_at = now() "
        f"WHERE id = $1 AND {_cach_ly()} AND body_cho_duyet",
        id_,
    )
    return kq.endswith(" 1")


async def xoa_tai_lieu(conn: asyncpg.Connection, id_: int) -> bool:
    kq = await conn.execute(f"DELETE FROM tenant_data.documents WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Media (`media`) ────────────────────────────────────────────────────────


def _loc_media() -> str:
    """Filter (KHÔNG kèm `_cach_ly()`, xem docstring `_loc_du_an`) — chiếm `$1..$5`."""
    return """($1 = '' OR project_code  = $1)
               AND ($2 = '' OR zone_code     = $2)
               AND ($3 = '' OR unit_code     = $3)
               AND ($4 = '' OR category      = $4)
               AND ($5 = '' OR content_type  = $5)"""


async def liet_ke_media(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    unit_code: str = "",
    category: str = "",
    content_type: str = "",
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Đọc CHO PORTAL — cùng lý do `liet_ke_tai_lieu`, KHÔNG tự gộp `__ALL__`."""
    return await conn.fetch(
        f"""SELECT {_COT_RA["media"]} FROM tenant_data.media
             WHERE {_cach_ly()} AND {_loc_media()}
               AND {_menh_de_keyset("", 6)}
             ORDER BY id DESC
             LIMIT $7 OFFSET $8""",
        project_code,
        zone_code,
        unit_code,
        category,
        content_type,
        _sau(cursor),
        _gioi_han(limit),
        _gioi_han_offset(offset),
    )


async def dem_media(
    conn: asyncpg.Connection,
    *,
    project_code: str = "",
    zone_code: str = "",
    unit_code: str = "",
    category: str = "",
    content_type: str = "",
) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM tenant_data.media WHERE {_cach_ly()} AND {_loc_media()}",
        project_code,
        zone_code,
        unit_code,
        category,
        content_type,
    )


async def doc_media(conn: asyncpg.Connection, id_: int) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {_COT_RA['media']} FROM tenant_data.media WHERE id = $1 AND {_cach_ly()}", id_)


async def liet_ke_media_cho_agent(
    conn: asyncpg.Connection,
    project_code: str,
    *,
    limit: int = TRANG_MAC_DINH,
    cursor: str | None = None,
) -> list[asyncpg.Record]:
    """CASCADE + `__ALL__` — cùng cơ chế `liet_ke_tai_lieu_cho_agent`."""
    return await conn.fetch(
        f"""SELECT {_voi_tien_to(_COT_RA["media"], "m.")}
              FROM tenant_data.media m
              JOIN tenant_data.projects p
                ON p.tenant_id = m.tenant_id AND p.project_code = m.project_code
             WHERE {_cach_ly("m.")}
               AND m.project_code IN ($1, $3) AND p.status = 'published' AND m.status = 'published'
               AND {_menh_de_keyset("m.", 4)}
             ORDER BY m.id DESC
             LIMIT $2""",
        project_code,
        _gioi_han(limit),
        SENTINEL_TENANT,
        _sau(cursor),
    )


async def dem_anh_theo_danh_muc(
    conn: asyncpg.Connection,
    *,
    project_code: str,
    zone_code: str | None,
    unit_code: str | None,
    category: str,
) -> int:
    """Số ẢNH (`content_type = 'image'`) đang có trong MỘT ô đếm
    `(project_code, zone_code, unit_code, category)`. Trần ≤6 ảnh/danh mục
    (`02a §4.5`) đã bỏ ở router (vòng 2) — hàm này giữ lại vì
    `tests/isolation/test_loc_tenant_o_tang_app.py::test_dem_anh_khong_dem_anh_tenant_khac`
    còn gọi trực tiếp để canh cách ly tenant của câu đếm.

    `IS NOT DISTINCT FROM` chứ không `=` cho `zone_code`/`unit_code`: hai cột đó
    NULLABLE và ảnh cấp dự án có `NULL` ở cả hai — `NULL = NULL` cho `NULL`
    (không phải TRUE) nên `=` sẽ đếm ra 0 mãi mãi và trần không bao giờ chặn được
    ảnh cấp dự án, đúng nhóm nhiều ảnh nhất."""
    return await conn.fetchval(
        f"""SELECT count(*) FROM tenant_data.media
            WHERE {_cach_ly()}
              AND project_code = $1
              AND zone_code IS NOT DISTINCT FROM $2
              AND unit_code IS NOT DISTINCT FROM $3
              AND category = $4
              AND content_type = 'image'""",
        project_code,
        zone_code,
        unit_code,
        category,
    )


def _them_public_url(payload: dict) -> dict:
    """Ở repo chứ không ở router: hàng `media` được tạo từ ba đường khác nhau."""
    from portal.core.public_url import public_url_of

    ra = dict(payload)
    if "media_url" in ra:
        ra["public_url"] = public_url_of(str(ra["media_url"] or ""))
    if "thumb_url" in ra:
        ra["public_thumb_url"] = public_url_of(str(ra["thumb_url"] or ""))
    return ra


async def chen_media(conn: asyncpg.Connection, tenant_id: str, payload: dict) -> asyncpg.Record:
    """LUÔN tạo hàng mới — không có khoá nghiệp vụ nào unique trên `media`."""
    row = await _upsert(conn, "media", None, _them_public_url(payload), tenant_id=tenant_id)
    assert row is not None
    return row


async def sua_media(conn: asyncpg.Connection, id_: int, payload: dict) -> asyncpg.Record | None:
    return await _upsert(conn, "media", id_, _them_public_url(payload))


async def xoa_media(conn: asyncpg.Connection, id_: int) -> bool:
    kq = await conn.execute(f"DELETE FROM tenant_data.media WHERE id = $1 AND {_cach_ly()}", id_)
    return kq.endswith(" 1")


# ─── Trạng thái nạp kiến thức cho agent ─────────────────────────────────────
_MUC_TRONG_TAM_MAT = """
    SELECT 'projects' AS entity, p.id, p.project_code, p.updated_at
      FROM tenant_data.projects p
     WHERE p.tenant_id = portal.current_tenant()
    UNION ALL
    -- Phân khu KHÔNG có dòng sổ riêng từ 2026-08-19 (nội dung nó nằm trong doc dự án),
    -- nên mốc so của nó là lần nạp của DỰ ÁN CHA. Đối chiếu với dòng sổ `zones` như
    -- trước là đỏ vĩnh viễn: không còn gì ghi dòng đó, kể cả nút Thử lại.
    SELECT 'projects', p2.id, z.project_code, z.updated_at
      FROM tenant_data.zones z
      JOIN tenant_data.projects p2
        ON p2.tenant_id = portal.current_tenant() AND p2.project_code = z.project_code
     WHERE z.tenant_id = portal.current_tenant()
    UNION ALL
    SELECT 'documents', d.id, d.project_code, d.updated_at
      FROM tenant_data.documents d
     WHERE d.tenant_id = portal.current_tenant()
       -- Mục chờ duyệt KHÔNG tính là lệch: nó cố ý chưa tới agent.
       AND NOT coalesce(d.body_cho_duyet, false)
    UNION ALL
    SELECT 'media', m.id, m.project_code, m.updated_at
      FROM tenant_data.media m
     WHERE m.tenant_id = portal.current_tenant()
       -- Danh mục ngoài `media_visual` KHÔNG BAO GIỜ được nạp — đếm chúng là lệch thì
       -- chỉ báo lỗi vĩnh viễn (đo trên dev 2026-08-14: 34/38 mục vàng là `csbh`).
       AND m.category = ANY($1::text[])
"""

_PROJECT_STATUS_SQL = f"""
WITH muc AS ({_MUC_TRONG_TAM_MAT}),
so AS (
    SELECT project_code,
           count(*) FILTER (WHERE state = 'error') AS error_count
      FROM tenant_data.kb_index_state
     WHERE tenant_id = portal.current_tenant() AND project_code <> ''
     GROUP BY project_code
),
lech AS (
    SELECT m.project_code, count(*) AS stale_count
      FROM muc m
      LEFT JOIN tenant_data.kb_index_state s
             ON s.tenant_id = portal.current_tenant()
            AND s.entity = m.entity
            AND s.record_id = m.id
            AND s.state <> 'deleted'
     WHERE s.id IS NULL OR s.indexed_at IS NULL OR m.updated_at > s.indexed_at
     GROUP BY m.project_code
),
tong AS (
    SELECT project_code, count(*) AS n FROM muc GROUP BY project_code
),
viec AS (
    SELECT j.payload->>'project_code' AS project_code,
           count(*) FILTER (WHERE j.state IN ('queued', 'running')) AS pending,
           -- Lỗi cũ HẾT tính khi đúng bản ghi đó chạy lại xong: không có vế này thì không
           -- gì dọn hàng `failed`, dự án từng hỏng đỏ vĩnh viễn và nút Thử lại vô nghĩa.
           -- Ghim theo (kind, entity, record_id) chứ không theo dự án: `kb_sync_project`
           -- luôn xong dù job con hỏng, nên so ở mức dự án là tự che lỗi của chính mình.
           count(*) FILTER (
               WHERE j.state = 'failed'
                 AND NOT EXISTS (
                     SELECT 1 FROM control.jobs k
                      WHERE k.tenant_id = j.tenant_id
                        AND k.kind = j.kind
                        AND k.state = 'success'
                        AND k.id > j.id
                        AND k.payload->>'project_code' = j.payload->>'project_code'
                        AND coalesce(k.payload->>'record_id', '') = coalesce(j.payload->>'record_id', '')
                 )
           ) AS failed
      FROM control.jobs j
     WHERE j.tenant_id = portal.current_tenant()
       AND j.kind LIKE 'kb\\_%'
       AND coalesce(j.payload->>'project_code', '') <> ''
     GROUP BY 1
)
SELECT p.project_code,
       coalesce(viec.pending, 0) > 0 AS indexing,
       (coalesce(so.error_count, 0) > 0
        OR coalesce(viec.failed, 0) > 0
        OR (coalesce(lech.stale_count, 0) > 0 AND coalesce(viec.pending, 0) = 0)) AS has_error,
       coalesce(tong.n, 0) AS total,
       -- `greatest(…, 0)`: `lech` đếm cả mục chưa có dòng sổ nên trên dữ liệu drift nó
       -- vượt được `tong`, và số âm làm frontend vẽ thanh tiến độ ngược.
       greatest(coalesce(tong.n, 0) - coalesce(lech.stale_count, 0), 0) AS done
  FROM tenant_data.projects p
  LEFT JOIN so ON so.project_code = p.project_code
  LEFT JOIN lech ON lech.project_code = p.project_code
  LEFT JOIN tong ON tong.project_code = p.project_code
  LEFT JOIN viec ON viec.project_code = p.project_code
 WHERE p.tenant_id = portal.current_tenant()
 ORDER BY p.project_code
"""


async def project_status(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Danh mục media được nạp lấy TỪ `kb.contracts`, không viết lại ở đây: hai bản sao
    của cùng một danh sách là hai bản sẽ lệch nhau ở lần thêm danh mục kế tiếp."""
    from portal.modules.kb.contracts import MEDIA_VISUAL_REAL_ESTATE

    return await conn.fetch(_PROJECT_STATUS_SQL, list(MEDIA_VISUAL_REAL_ESTATE))


CONTENT_TYPE_TOUR = "tour_360"


async def sync_tour_360(
    conn: asyncpg.Connection, tenant_id: str, *, project_code: str, link: str, ten_du_an: str
) -> tuple[int | None, int | None]:
    """`projects.link_360` thành MỘT hàng `media` — trả `(id vừa ghi, id vừa xoá)`.

    Hàng thật chứ không phải nguồn ảo: đường nạp/xoá/đổi cờ của media đã xử lý đúng mọi
    thứ, còn một nguồn ảo là một nhánh song song phải tự lo tất cả.

    CHỈ ĐỤNG HÀNG DO MÌNH SINH (`external_id IS NULL`). Hàng `tour_360` mà adapter đẩy
    qua cổng nạp mang `external_id` của họ — bản trước chọn hàng tour BẤT KỲ theo
    `project_code`, nên dự án không có `link_360` mà adapter gửi tour thì mỗi lượt upsert
    project (cổng nạp gọi sync mỗi lần) XOÁ hàng của họ; có `link_360` thì ghi đè
    `media_url` của họ rồi lượt sync kế của adapter ghi đè ngược lại (bug 2026-08-25,
    bắt được khi review Swagger). Swagger nay dặn adapter đừng gửi `tour_360` trực tiếp,
    nhưng phía mình vẫn không được phá dữ liệu của họ.
    """
    cu = await conn.fetchval(
        f"SELECT id FROM tenant_data.media WHERE {_cach_ly()} AND project_code = $1 AND content_type = $2"
        " AND external_id IS NULL",
        project_code,
        CONTENT_TYPE_TOUR,
    )
    if not link.strip():
        if cu is None:
            return None, None
        await conn.execute(f"DELETE FROM tenant_data.media WHERE id = $1 AND {_cach_ly()}", int(cu))
        return None, int(cu)

    caption = f"Tour tham quan thực tế ảo 360 độ — {ten_du_an}" if ten_du_an else "Tour tham quan thực tế ảo 360 độ"
    payload = {
        "content_type": CONTENT_TYPE_TOUR,
        "category": "tong_quan",
        "media_url": link,
        "caption": caption,
        "status": "published",
    }
    if cu is not None:
        await _upsert(conn, "media", int(cu), payload)
        return int(cu), None
    payload["project_code"] = project_code
    hang = await chen_media(conn, tenant_id, payload)
    return int(hang["id"]), None


async def media_ids_of_zone(conn: asyncpg.Connection, *, project_code: str, zone_code: str) -> list[int]:
    """Gọi TRƯỚC khi xoá/ẩn phân khu: FK `zones → media` là ON DELETE CASCADE, nên
    sau DELETE thì không còn gì để liệt kê. Sổ `kb_index_state` mang `project_code`
    nhưng KHÔNG mang `zone_code`, nên nó không cứu được trường hợp này."""
    rows = await conn.fetch(
        f"SELECT id FROM tenant_data.media WHERE {_cach_ly()} AND project_code = $1 AND zone_code = $2 ORDER BY id",
        project_code,
        zone_code,
    )
    return [int(r["id"]) for r in rows]
