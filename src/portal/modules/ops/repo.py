"""SQL của M7. Không biết HTTP, không biết Pydantic — trả `asyncpg.Record` thô.

MỌI câu ở đây mang `tenant_id = portal.current_tenant()`. RLS đã bị dỡ (`0909`) rồi
bật lại (`0913`) trong đúng một ngày; một lớp là một điểm chết.
"""

from datetime import date

import asyncpg

from portal.modules.ops.contracts import (
    KENH_CHAT,
    KENH_VOICE,
    SO_NGAY,
    TRANG_CA,
    TRANG_MAC_DINH,
    TRICH_SO_LUOT,
)

# Bộ lọc thời gian — ánh xạ ĐÓNG. Không nhận số tuỳ ý từ query để tránh một
# `tu_ngay` lạ lọt thẳng vào chuỗi SQL.
_KHOANG = {"7": "7 days", "30": "30 days", "all": None}


def _dieu_kien_thoi_gian(tu_ngay: str) -> str:
    """Điều kiện cho HAVING, KHÔNG cho WHERE.

    Spec §3.3: bộ lọc thời gian đi theo `gan_nhat` — mốc gần nhất của cả NHÓM.
    Đặt nó ở WHERE thì nó lọc từng HÀNG trước khi gom, và một khách có phiên mới
    3 hôm trước cộng hai phiên tháng trước sẽ hiện «1 phiên» thay vì «3 phiên».
    Con số sai đó trông hoàn toà
    n hợp lý, nên không ai phát hiện.
    """
    khoang = _KHOANG.get(tu_ngay, _KHOANG["30"])
    if khoang is None:
        return "TRUE"
    return f"max(COALESCE(started_at, created_at)) >= now() - interval '{khoang}'"


def _escape_like(s: str) -> str:
    """`%` và `_` người dùng gõ phải là ký tự thường, không phải ký tự đại diện.

    Không có hàm này thì gõ `%` khớp toàn bộ dữ liệu và gõ `_` khớp mọi ký tự đơn —
    người dùng chỉ thấy "bộ lọc hỏng", không thấy vì sao.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_CACH_LY = "tenant_id = portal.current_tenant()"

_HAVING = """
    ({thoi_gian})
AND (NOT $3 OR bool_or(transferred_to_sales))
AND ($1 = '' OR bool_or(phone ILIKE '%' || $2 || '%' ESCAPE '\\'
                     OR customer_name ILIKE '%' || $2 || '%' ESCAPE '\\'))
"""

_MOI_NHAT = "ORDER BY COALESCE(started_at, created_at) DESC"


_TEN_DU_AN = """(SELECT p.name FROM tenant_data.projects p
                  WHERE p.tenant_id = portal.current_tenant()
                    AND p.project_code = {cot}) AS ten_du_an"""
"""Tên dự án suy từ mã — SUBQUERY, không JOIN.

`liet_ke_phien` GROUP BY cả `_COT_PHIEN`; một JOIN nữa buộc thêm `p.name` vào đó và
làm hai hằng phải đổi cùng nhau. Subquery chỉ tham chiếu cột đã group nên hợp lệ.

`None` khi dự án đã bị xoá mà phiên còn giữ mã — giao diện rơi về mã, đó là hành vi
ĐÚNG: nói «Chưa rõ» cho một phiên có mã là bỏ mất thông tin duy nhất còn lại."""

_LEAD_KHACH = """
    LEFT JOIN LATERAL (
        SELECT e.lead_stage, e.lead_score, e.audience, e.lead_signals
          FROM tenant_data.escalations e
          JOIN tenant_data.conversations c
            ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
         WHERE e.tenant_id = portal.current_tenant()
           AND c.tenant_id = portal.current_tenant()
           AND c.phone = t.phone
           AND e.lead_stage IS NOT NULL
         ORDER BY COALESCE(c.started_at, c.created_at) DESC, e.created_at DESC, e.id DESC
         LIMIT 1
    ) l ON TRUE
"""
"""Lead của KHÁCH = lead của PHIÊN mới nhất có lead (spec §2).

Khoá sắp đầu là thời điểm PHIÊN, không phải `created_at` của hàng ca: danh sách, ô «Lead
hiện tại» và phiên trên cùng có chip ở trang chi tiết phải LUÔN là cùng một hàng. Hai khoá
sau chọn hàng mới nhất TRONG phiên. Nối qua phiên, KHÔNG qua `phone` của hàng ca (đó là
ảnh chụp lúc chuyển, lệch được với khoá gom nhóm).

`c.phone = t.phone` TRẦN, KHÔNG `COALESCE(c.phone, '')`: bọc cột trong hàm là mất index
theo phone, và khi có bộ lọc LATERAL chạy cho MỌI khách trong cửa sổ ⇒ quét toàn bộ hội
thoại của tenant một lần cho mỗi khách. Hệ quả có chủ ý: nhóm «Chưa có số» (`phone`
NULL, gom thành `''`) KHÔNG có lead cấp khách — nó là nhiều người ẩn danh, một «lead
mới nhất» cho cả nhóm là nói sai, và lọc `sql` sẽ bày nó ra như một khách nóng không
có số để gọi. Lead TỪNG PHIÊN của nhóm vẫn có (`_LEAD_PHIEN`)."""

LOC_LEAD: dict[str, str] = {
    "": "TRUE",
    "none": "l.lead_stage IS NULL",
    "lead": "l.lead_stage = 'lead'",
    "mql": "l.lead_stage = 'mql'",
    "sql": "l.lead_stage = 'sql'",
    "hen_gap": "l.lead_stage = 'hen_gap'",
}
"""Điều kiện lọc theo lead MỚI NHẤT. Khoá đã được router kiểm bằng `pattern`; tra dict chứ
không ghép chuỗi người dùng vào SQL."""


async def liet_ke_khach(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
    lead_stage: str = "",
    limit: int = TRANG_MAC_DINH,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Một hàng một khách, sắp theo phiên gần nhất, kèm lead mới nhất (`_LEAD_KHACH`).

    `array_agg(... ORDER BY ...)[1]` chứ KHÔNG `max()`: cần giá trị của phiên MỚI
    NHẤT, không phải giá trị lớn nhất theo thứ tự chữ cái. `max(customer_name)`
    chạy được, không báo lỗi, và trả tên sai.

    `FILTER (WHERE ... IS NOT NULL)` để một phiên bỏ trống trường không đẩy NULL lên
    đầu mảng và xoá mất giá trị đã biết từ phiên trước.

    Không lọc lead ⇒ `LIMIT` nằm TRONG subquery để LATERAL chỉ chạy cho đúng một trang.
    Có lọc ⇒ `LIMIT` phải nằm SAU `WHERE` của lead, không thì trang cắt trước rồi mới lọc
    và thanh phân trang nói về một tập khác.
    """
    loc = LOC_LEAD[lead_stage]
    trang_trong = "LIMIT $4 OFFSET $5" if not lead_stage else ""
    trang_ngoai = "LIMIT $4 OFFSET $5" if lead_stage else ""
    sql = f"""
        SELECT t.*, l.lead_stage, l.lead_score, l.audience, {_TEN_DU_AN.format(cot="t.du_an")}
          FROM (
        SELECT COALESCE(phone, '')                                  AS phone,
               count(*)                                             AS so_phien,
               max(COALESCE(started_at, created_at))                AS gan_nhat,
               min(COALESCE(started_at, created_at))                AS dau_tien,
               bool_or(transferred_to_sales)                        AS da_chuyen,
               (array_agg(customer_name {_MOI_NHAT})
                  FILTER (WHERE customer_name IS NOT NULL))[1]      AS ten,
               (array_agg(summary {_MOI_NHAT})
                  FILTER (WHERE summary IS NOT NULL AND summary <> ''))[1] AS summary_cuoi,
               (array_agg(project {_MOI_NHAT})
                  FILTER (WHERE project IS NOT NULL))[1]            AS du_an
          FROM tenant_data.conversations
         WHERE {_CACH_LY}
         GROUP BY 1
        HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
         ORDER BY gan_nhat DESC
         {trang_trong}
          ) t
        {_LEAD_KHACH}
         WHERE {loc}
         ORDER BY t.gan_nhat DESC
         {trang_ngoai}
    """
    return list(await conn.fetch(sql, tim, _escape_like(tim), da_chuyen, limit, offset))


async def dem_tong(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    tu_ngay: str = "30",
    da_chuyen: bool = False,
    lead_stage: str = "",
) -> tuple[int, int]:
    """`(số khách, số phiên)` TRÊN TẬP ĐÃ LỌC — không phải tổng toàn bảng.

    Hai con số này hiện cạnh thanh lọc; nếu đếm toàn bảng thì lọc xong con số không
    đổi và người dùng tưởng bộ lọc không chạy. Lọc lead dùng CHUNG `_LEAD_KHACH` +
    `LOC_LEAD` với `liet_ke_khach` để hai chỗ không lệch điều kiện; không lọc thì bỏ
    LATERAL cho nhẹ.
    """
    lead = _LEAD_KHACH if lead_stage else ""
    sql = f"""
        SELECT count(*) AS so_khach, COALESCE(sum(t.n), 0) AS so_phien
          FROM (
            SELECT COALESCE(phone, '') AS phone, count(*) AS n
              FROM tenant_data.conversations
             WHERE {_CACH_LY}
             GROUP BY COALESCE(phone, '')
            HAVING {_HAVING.format(thoi_gian=_dieu_kien_thoi_gian(tu_ngay))}
          ) t
          {lead}
         WHERE {LOC_LEAD[lead_stage]}
    """
    r = await conn.fetchrow(sql, tim, _escape_like(tim), da_chuyen)
    return int(r["so_khach"]), int(r["so_phien"])


async def doc_chan_dung(conn: asyncpg.Connection, *, phone: str) -> asyncpg.Record:
    """Những gì agent đã khai thác về MỘT số: `contacts.profile`/`snapshot` + tín hiệu lead.

    LUÔN trả đúng một hàng (khách chưa có hàng `contacts` ⇒ các cột NULL) — số chưa ai
    ghi gì vẫn là một khách mở được, không phải 404.

    Tín hiệu đi qua CHÍNH `_LEAD_KHACH`: cùng hàng ca với ô «Lead hiện tại», nên chip
    tín hiệu không bao giờ nói về một lead khác cái stage đứng cạnh nó.
    """
    return await conn.fetchrow(
        f"""
        SELECT ct.profile, ct.snapshot, ct.updated_at, l.lead_signals
          FROM (SELECT $1::text AS phone) t
          LEFT JOIN tenant_data.contacts ct
                 ON ct.tenant_id = portal.current_tenant() AND ct.phone = t.phone
          {_LEAD_KHACH}
        """,
        phone,
    )


_COT_PHIEN = """
    c.session_id, c.customer_name, c.started_at, c.ended_at, c.summary, c.project,
    c.transferred_to_sales, c.running_version, c.source, c.phone
"""

_LEAD_PHIEN = """
    LEFT JOIN LATERAL (
        SELECT e.lead_stage, e.lead_score, e.audience
          FROM tenant_data.escalations e
         WHERE e.tenant_id = portal.current_tenant()
           AND e.session_id = c.session_id
           AND e.lead_stage IS NOT NULL
         ORDER BY e.created_at DESC, e.id DESC
         LIMIT 1
    ) l ON TRUE
"""
"""Lead của PHIÊN = hàng ca mới nhất CÓ stage của phiên đó; ba trường cùng một hàng (spec §2)."""

_COT_LEAD = "l.lead_stage, l.lead_score, l.audience"


async def liet_ke_phien(conn: asyncpg.Connection, *, phone: str | None) -> list[asyncpg.Record]:
    """Phiên của một khách, mới nhất trên đầu. `phone=None` ⇒ nhóm «Chưa có số».

    LEFT JOIN, KHÔNG `JOIN`: một phiên chưa có lượt nào vẫn phải hiện với
    `so_luot = 0`. `JOIN` trần làm nó biến mất khỏi cột phiên và không có triệu
    chứng nào.

    `count(m.seq)`, KHÔNG `count(*)`: `count(*)` đếm cả hàng NULL mà LEFT JOIN sinh
    ra cho phiên rỗng, và trả `1`.

    `tin_nhan_dau`: nội dung lượt `seq` nhỏ nhất — cùng khuôn
    `array_agg(... ORDER BY ...)[1] FILTER (...)` với `liet_ke_khach`, vì đây cũng
    là "giá trị của MỘT hàng cụ thể trong nhóm", không phải giá trị gộp.
    """
    return list(
        await conn.fetch(
            f"""
            SELECT {_COT_PHIEN}, {_COT_LEAD}, {_TEN_DU_AN.format(cot="c.project")}, count(m.seq) AS so_luot,
                   (array_agg(m.content ORDER BY m.seq)
                      FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
              FROM tenant_data.conversations c
              {_LEAD_PHIEN}
              LEFT JOIN tenant_data.conversation_messages m
                     ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
             WHERE c.tenant_id = portal.current_tenant()
               AND c.phone IS NOT DISTINCT FROM $1
             GROUP BY {_COT_PHIEN}, {_COT_LEAD}, c.created_at
             ORDER BY COALESCE(c.started_at, c.created_at) DESC
            """,
            phone,
        )
    )


async def doc_phien(conn: asyncpg.Connection, session_id: str) -> asyncpg.Record | None:
    """Meta của một phiên. `None` ⇒ không thuộc tenant hiệu lực (router đổi thành 404).

    `tin_nhan_dau` nằm ở đây dù màn chi tiết không hiện nó — `_ra_phien` dùng
    chung cho cả hai endpoint, thiếu cột này ở đây thì `_ra_phien` KeyError khi
    gọi từ `doc_phien` (router.py).
    """
    return await conn.fetchrow(
        f"""
        SELECT {_COT_PHIEN}, {_COT_LEAD}, {_TEN_DU_AN.format(cot="c.project")}, c.skill_calls, count(m.seq) AS so_luot,
               (array_agg(m.content ORDER BY m.seq)
                  FILTER (WHERE m.seq IS NOT NULL))[1]      AS tin_nhan_dau
          FROM tenant_data.conversations c
          {_LEAD_PHIEN}
          LEFT JOIN tenant_data.conversation_messages m
                 ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
         WHERE c.tenant_id = portal.current_tenant() AND c.session_id = $1
         GROUP BY {_COT_PHIEN}, {_COT_LEAD}, c.skill_calls, c.created_at
        """,
        session_id,
    )


# ─── Hộp thư sale ───────────────────────────────────────────────────────────

_TRANG_THAI = {
    "new": "e.status = 'new'",
    "contacted": "e.status = 'contacted'",
    "done": "e.status = 'done'",
    "handled": "e.status <> 'new'",
    "all": "TRUE",
}

_SAP_XEP = {"moi": "DESC", "cu": "ASC"}

_COT_CA = """
       e.id, e.session_id, e.project AS du_an, e.missing_data_tool,
       e.summary, e.summary_at, e.message_seq, e.status,
       e.handled_at, e.handled_note, e.created_at,
       -- Tên người, không phải user_id: màn hiện «u_dang đang xử lý» là vô nghĩa
       -- với sale. LEFT JOIN nên người đã rời tổ chức rơi về chính id.
       COALESCE(u.name, e.handled_by)             AS nguoi_xu_ly,
       COALESCE(e.phone, c.phone)                 AS phone,
       COALESCE(e.customer_name, c.customer_name) AS ten,
       p.name                                     AS ten_du_an,
       c.source                                   AS kenh,
       m.n                                        AS so_luot
"""

_NOI_CA = """
     FROM tenant_data.escalations e
     LEFT JOIN tenant_data.conversations c
            ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
     LEFT JOIN tenant_data.projects p
            ON p.tenant_id = e.tenant_id AND p.project_code = e.project
     LEFT JOIN LATERAL (
            SELECT count(*) AS n FROM tenant_data.conversation_messages m
             WHERE m.tenant_id = e.tenant_id AND m.session_id = e.session_id
     ) m ON TRUE
     LEFT JOIN control.users u ON u.id = e.handled_by
    WHERE e.tenant_id = portal.current_tenant()
"""

_LOC_CA = """
      AND {trang_thai}
      AND ($1 = '' OR COALESCE(e.phone, c.phone, '') ILIKE '%' || $2 || '%' ESCAPE '\\'
                   OR COALESCE(e.customer_name, c.customer_name, '') ILIKE '%' || $2 || '%' ESCAPE '\\')
      AND ($3 = '' OR e.project = $3)
"""


def _tu_ca(trang_thai: str) -> str:
    return _NOI_CA + _LOC_CA.format(trang_thai=_TRANG_THAI.get(trang_thai, "TRUE"))


async def liet_ke_ca(
    conn: asyncpg.Connection,
    *,
    tim: str = "",
    trang_thai: str = "all",
    du_an: str = "",
    sap_xep: str = "moi",
    limit: int = TRANG_CA,
    offset: int = 0,
) -> list[asyncpg.Record]:
    """Một hàng một ca chuyển sale, mới nhất trên đầu.

    `COALESCE(e.phone, c.phone)`: hàng ca đóng băng SĐT lúc chuyển; khách cho số ở
    lượt SAU thì sale thấy «chưa có số» dù số nằm ngay bảng bên cạnh.
    """
    sql = f"""
        SELECT {_COT_CA} {_tu_ca(trang_thai)}
        ORDER BY e.created_at {_SAP_XEP.get(sap_xep, "DESC")}, e.id DESC
        LIMIT $4 OFFSET $5
    """
    return list(await conn.fetch(sql, tim, _escape_like(tim), du_an, limit, offset))


async def doc_ca(conn: asyncpg.Connection, ca_id: int) -> asyncpg.Record | None:
    """Một ca sau khi PATCH. `None` ⇒ không thuộc tenant hiệu lực."""
    return await conn.fetchrow(f"SELECT {_COT_CA} {_NOI_CA} AND e.id = $1", ca_id)


async def dem_ca(conn: asyncpg.Connection, *, tim: str = "", trang_thai: str = "all", du_an: str = "") -> int:
    """Số ca TRÊN TẬP ĐÃ LỌC — đếm toàn bảng thì lọc xong con số không đổi."""
    return int(await conn.fetchval(f"SELECT count(*) {_tu_ca(trang_thai)}", tim, _escape_like(tim), du_an))


async def du_an_co_ca(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Mã + TÊN dự án cho dropdown. KHÔNG theo bộ lọc đang áp: chọn một dự án rồi thì
    danh sách chỉ còn đúng nó, và người dùng không đổi sang dự án khác được.

    Sắp theo TÊN (mã rơi về cuối khi dự án đã xoá) — dropdown bày nhãn nào thì sắp
    theo nhãn đó, nếu không thứ tự trông như ngẫu nhiên với người đọc."""
    return list(
        await conn.fetch(
            """
            SELECT DISTINCT e.project AS ma, p.name AS ten
              FROM tenant_data.escalations e
              LEFT JOIN tenant_data.projects p
                     ON p.tenant_id = portal.current_tenant() AND p.project_code = e.project
             WHERE e.tenant_id = portal.current_tenant()
               AND e.project IS NOT NULL AND e.project <> ''
             ORDER BY p.name NULLS LAST, e.project
            """
        )
    )


async def cap_nhat_ca(
    conn: asyncpg.Connection,
    *,
    ca_id: int,
    trang_thai: str,
    nguoi: str,
    ghi_chu: str | None = None,
) -> bool:
    """Sale nhận ca / đánh dấu xong. `False` ⇒ không có hàng nào (router đổi thành 404).

    `COALESCE($4, handled_note)`: đổi trạng thái không gõ ghi chú thì giữ ghi chú cũ.
    """
    r = await conn.execute(
        """
        UPDATE tenant_data.escalations
           SET status = $2,
               -- Về `new` = trả ca lại cho hàng đợi, không ai còn cầm. Giữ
               -- handled_by ở đây thì nhãn «Chưa liên hệ» và dữ liệu nói ngược nhau.
               handled_by = CASE WHEN $2 = 'new' THEN NULL ELSE $3 END,
               handled_at = CASE WHEN $2 = 'new' THEN NULL ELSE now() END,
               handled_note = COALESCE($4, handled_note)
         WHERE tenant_id = portal.current_tenant() AND id = $1
        """,
        ca_id,
        trang_thai,
        nguoi,
        ghi_chu,
    )
    if r == "UPDATE 0":
        return False
    if ghi_chu is not None:
        await conn.execute(
            """
            INSERT INTO tenant_data.escalation_notes (tenant_id, escalation_id, author, note)
            VALUES (portal.current_tenant(), $1, $2, $3)
            """,
            ca_id,
            nguoi,
            ghi_chu,
        )
    return True


async def doc_ghi_chu(conn: asyncpg.Connection, *, ca_id: int) -> list[asyncpg.Record]:
    return list(
        await conn.fetch(
            """
            SELECT n.id, n.note AS noi_dung, n.author AS nguoi_id,
                   COALESCE(u.name, n.author) AS nguoi, n.created_at AS luc
              FROM tenant_data.escalation_notes n
              LEFT JOIN control.users u ON u.id = n.author
             WHERE n.tenant_id = portal.current_tenant() AND n.escalation_id = $1
             ORDER BY n.created_at, n.id
            """,
            ca_id,
        )
    )


async def doc_luot(conn: asyncpg.Connection, session_id: str) -> list[asyncpg.Record]:
    """Transcript một phiên, ORDER BY `seq`.

    KHÔNG `ORDER BY created_at`: hai lượt trong cùng một giây có thứ tự xác định
    theo `seq` nhưng KHÔNG theo `created_at`, và transcript sẽ đảo lượt ngẫu nhiên
    giữa hai lần tải. `created_at` chỉ để hiển thị.
    """
    return list(
        await conn.fetch(
            """
            SELECT seq, role, content, created_at, meta
              FROM tenant_data.conversation_messages
             WHERE tenant_id = portal.current_tenant() AND session_id = $1
             ORDER BY seq
            """,
            session_id,
        )
    )


async def doc_trich(
    conn: asyncpg.Connection,
    *,
    session_id: str,
    truoc_seq: int | None,
    so_luot: int = TRICH_SO_LUOT,
) -> list[asyncpg.Record]:
    """Mấy lượt thoại ngay TRƯỚC lúc agent chuyển ca, theo thứ tự đọc.

    `truoc_seq` là `escalations.message_seq` — chỉ số tuyệt đối trong
    `state.history` phía agent, cùng hệ đánh số với `conversation_messages.seq`
    (`persist_turn_messages` ghi `seq = base_seq + i`). `None` (ca cũ, cột
    nullable) ⇒ bỏ neo, lấy mấy lượt cuối phiên: có dữ liệu còn hơn khối rỗng.

    Lọc `role`/`content` là BẮT BUỘC, không phải dọn dẹp: bảng giữ cả hàng
    `role='tool'` (JSON kết quả) lẫn hàng assistant rỗng chỉ mang `tool_calls`
    trong `meta` — không lọc thì sale đọc phải tham số của `search_units`.

    `DESC` bên trong để cắt từ phía GẦN mốc chuyển, rồi đảo lại ở vòng ngoài:
    lấy `ASC LIMIT n` là trả về lời chào đầu cuộc gọi.
    """
    return list(
        await conn.fetch(
            """
            SELECT seq, role, content, created_at, meta FROM (
                SELECT seq, role, content, created_at, meta
                  FROM tenant_data.conversation_messages
                 WHERE tenant_id = portal.current_tenant()
                   AND session_id = $1
                   AND ($2::int IS NULL OR seq < $2)
                   AND role IN ('user', 'assistant')
                   AND content <> ''
                 ORDER BY seq DESC
                 LIMIT $3
            ) t ORDER BY seq
            """,
            session_id,
            truoc_seq,
            so_luot,
        )
    )


# ── Overview ────────────────────────────────────────────────────────────────

_TZ_VN = "Asia/Ho_Chi_Minh"

_NGAY = f"(COALESCE(started_at, created_at) AT TIME ZONE '{_TZ_VN}')::date"
"""Gom theo ngày Ở MÚI GIỜ NGƯỜI DÙNG, không phải UTC. Một phiên lúc 23h30
giờ VN nằm ở ngày hôm sau theo UTC — gom sai thì cột cuối biểu đồ (hôm nay)
luôn hụt mấy phiên muộn nhất, đúng những phiên người xem để ý nhất."""


async def hoi_thoai_theo_ngay(
    conn: asyncpg.Connection,
    *,
    tinh_den: date,
    so_ngay: int = SO_NGAY,
) -> list[asyncpg.Record]:
    """Một hàng một NGÀY, đủ `so_ngay` hàng kể cả ngày không có phiên nào.

    `generate_series` LEFT JOIN với dữ liệu — không phải `GROUP BY` trần. Xem
    `test_ngay_khong_co_phien_van_co_mat_voi_0`: biểu đồ vẽ theo chỉ số ô nên
    một ngày vắng mặt làm trượt cả trục.
    """
    return await conn.fetch(
        f"""
        WITH khung AS (
            SELECT generate_series($1::date - ($2::int - 1), $1::date, '1 day')::date AS ngay
        ),
        phien AS (
            SELECT {_NGAY} AS ngay, source
            FROM tenant_data.conversations
            WHERE {_CACH_LY}
              AND {_NGAY} BETWEEN $1::date - ($2::int - 1) AND $1::date
        )
        SELECT khung.ngay,
               count(*) FILTER (WHERE phien.source = $3) AS chat,
               count(*) FILTER (WHERE phien.source = $4) AS voice,
               count(*) FILTER (
                   WHERE phien.ngay IS NOT NULL
                     AND (phien.source IS NULL OR phien.source NOT IN ($3, $4))
               ) AS khac
        FROM khung LEFT JOIN phien ON phien.ngay = khung.ngay
        GROUP BY khung.ngay
        ORDER BY khung.ngay
        """,
        tinh_den,
        so_ngay,
        KENH_CHAT,
        KENH_VOICE,
    )


async def hoi_thoai_theo_kenh(conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date) -> list[asyncpg.Record]:
    """Một hàng một `source` NGUYÊN VĂN, kể cả NULL và kênh chưa biết tên.

    Không gộp kênh lạ vào "khác" ở tầng SQL: chú thích cần gọi đúng tên nó
    («+ Zalo OA 37»), còn việc gộp là quyết định trình bày của FE.
    """
    return await conn.fetch(
        f"""
        SELECT source AS kenh, count(*) AS n
        FROM tenant_data.conversations
        WHERE {_CACH_LY} AND {_NGAY} BETWEEN $1::date AND $2::date
        GROUP BY source
        ORDER BY n DESC, source NULLS LAST
        """,
        tu_ngay,
        tinh_den,
    )


async def dem_hoi_thoai(conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date) -> int:
    """Tổng số phiên trên MỘT cửa sổ do người gọi truyền vào, không tự suy.

    Tách riêng khỏi `hoi_thoai_theo_ngay` vì đây là mẫu số của delta kỳ trước
    (`HoiThoaiOut.truoc`): cửa sổ đó nằm TRƯỚC `tinh_den - so_ngay`, khác cửa
    sổ `so_ngay` ngày gần nhất mà `hoi_thoai_theo_ngay` tự tính — nhận `tu_ngay`
    tường minh để gọi được cho cả hai cửa sổ bằng một hàm.
    """
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM tenant_data.conversations
        WHERE {_CACH_LY} AND {_NGAY} BETWEEN $1::date AND $2::date
        """,
        tu_ngay,
        tinh_den,
    )


_NGAY_ESC = f"(created_at AT TIME ZONE '{_TZ_VN}')::date"
"""`escalations` chỉ có `created_at` (agent ghi hàng ca NGAY lúc chuyển, không có
cặp `started_at`/`created_at` như `conversations`). Vẫn quy đổi múi giờ VN, cùng
lý do với `_NGAY`: một ca chuyển lúc 23h30 giờ VN không được rơi sang ngày UTC
hôm sau."""


async def dem_chuyen_sale(conn: asyncpg.Connection, *, tu_ngay: date, tinh_den: date) -> asyncpg.Record:
    """Tử số đếm CA trong `tenant_data.escalations`, mẫu số đếm PHIÊN.

    ⚠️ **Đổi nguồn tử số 2026-08-14 — đọc trước khi đổi lại.** Bản đầu đếm
    `count(*) FILTER (WHERE transferred_to_sales)` NGAY TRÊN `conversations`,
    tức cùng một `FROM`/`WHERE` với mẫu số. Gọn hơn, nhưng nó đếm một thứ KHÁC
    với thứ màn `/chuyen-sale` — nơi ô này dẫn tới — bày ra:

      · `conversations.transferred_to_sales` là một CỜ trên phiên, do agent ghi
        lúc CHỐT bản tóm tắt cuối cuộc gọi (`odyssey-agent`,
        `storage/pg_data_plane.py`, sticky-true);
      · `tenant_data.escalations` là một HÀNG CA trong hộp thư sale, agent ghi
        NGAY LÚC chuyển — trước khi cuộc gọi kết thúc (xem chú thích `_NOI_CA`
        ngay trên: đó chính là lý do mọi JOIN ở đây phải LEFT).

    Hai nguồn lệch nhau có hệ thống, không phải thi thoảng: ca vừa mở mà cuộc
    gọi chưa chốt thì có hàng `escalations` nhưng chưa có cờ. Người dùng đối
    chiếu số trên ô ② với số ca ở `/chuyen-sale` và thấy vênh — đúng, và đó là
    lỗi của ô, không phải của họ. Ô nói «Chuyển sale» rồi dẫn sang hộp thư sale
    thì nó phải đếm hàng của chính hộp thư đó.

    **Mẫu số vẫn là PHIÊN trong kỳ** (`conversations`), vì đại lượng ô này vẽ
    là «phần phiên agent phải giao lại cho người thật» — mẫu số là mọi phiên
    đã diễn ra, không phải mọi ca. Hai `FROM` khác nhau nên bất biến cũ
    («cùng một `FROM`/`WHERE`, không thể ra > 100%») KHÔNG còn tự đúng: một ca
    mở trong kỳ mà phiên của nó chốt sang kỳ sau vẫn đếm vào tử số. Chốt chặn
    ở `router.py` (`tu_xu_ly` không âm) chứ không ở đây — SQL trả số thô đúng
    như nó đo được, tầng trình bày mới quyết định kẹp.
    """
    return await conn.fetchrow(
        f"""
        SELECT (
                 SELECT count(*) FROM tenant_data.escalations
                 WHERE {_CACH_LY} AND {_NGAY_ESC} BETWEEN $1::date AND $2::date
               ) AS chuyen,
               (
                 SELECT count(*) FROM tenant_data.conversations
                 WHERE {_CACH_LY} AND {_NGAY} BETWEEN $1::date AND $2::date
               ) AS tong
        """,
        tu_ngay,
        tinh_den,
    )


_NGAY_FB = f"(created_at AT TIME ZONE '{_TZ_VN}')::date"
"""`agent_feedback` không có `started_at`/`created_at` kép như `conversations` —
chỉ `created_at`. Vẫn quy đổi múi giờ VN, cùng lý do với `_NGAY`: một lượt chấm
23h30 giờ VN không được rơi sang ngày UTC hôm sau."""


async def danh_gia(
    conn: asyncpg.Connection,
    *,
    tu_ngay: date | None = None,
    truoc_ngay: date | None = None,
    tinh_den: date | None = None,
) -> asyncpg.Record:
    """Điểm trung bình VÀ phân bố sao từ CÙNG một tập — xem test cùng tên.

    Tính `trung_binh` ở một truy vấn rồi phân bố sao ở truy vấn khác (hai lượt
    đếm trên `agent_feedback`) là hai nguồn rời nhau cho cùng một biểu đồ: hai
    con số có thể lệch cửa sổ mà không ai phát hiện, và ngôi sao tô một đằng
    trong khi số in một nẻo.

    `trung_binh` trả NULL khi chưa có lượt nào (`avg()` trên tập rỗng) — router
    mới quyết định hiển thị, KHÔNG ép 0.0 ở đây: «0,00/5» là một điểm số thật,
    «chưa có lượt nào» thì không, và ép nhầm hai thứ đó vào nhau là hứa với
    người xem một mức hài lòng chưa từng được đo.

    **Ba cửa sổ, cả ba đều tuỳ chọn** (đổi 2026-08-14 — trước đó `tu_ngay`/
    `tinh_den` bắt buộc, tức luôn có cửa sổ):

      · không truyền gì  ⇒ TOÀN BỘ feedback của tenant;
      · `truoc_ngay`     ⇒ mọi lượt chấm TRƯỚC ngày đó (không cận dưới);
      · `tu_ngay`/`tinh_den` ⇒ một khoảng đóng như cũ.

    Vì sao cần ca «toàn bộ»: ô ③ màn Tổng quan và dải thống kê màn `/quality`
    nói về CÙNG một đại lượng («khách chấm agent mấy điểm»), nhưng `/quality`
    cố ý đếm toàn bộ feedback bất kể bộ lọc đang áp (xem
    `modules/enrollment/service.py::liet_ke_feedback_cua_tenant`) trong khi ô ③
    đếm 7 ngày. Hai màn cạnh nhau in hai con số khác nhau dưới cùng một nhãn
    «điểm trung bình» thì người đọc không có cách nào biết cái nào đúng — và họ
    kết luận cả hai đều sai. Người dùng chốt: ô ③ theo `/quality`.

    `truoc_ngay` là hệ quả trực tiếp của quyết định đó. Badge delta phải so
    được với một cái gì; khi số chính đã là TÍCH LUỸ thì mốc so duy nhất còn
    đúng nghĩa là **cũng tích luỹ, nhưng tính tới trước kỳ này** — «điểm trung
    bình mọi thời đã nhích lên/xuống bao nhiêu sau bảy ngày vừa rồi». So một
    con số tích luỹ với trung bình của riêng bảy ngày trước đó là so hai đại
    lượng khác loại, và ra một mũi tên nói dối rất to ở tenant mới.
    """
    # ⚠️ Tên biến PHẢI chứa `_cach_ly`. `tests/isolation/test_loc_tenant_o_tang_app.py`
    # unparse AST của f-string rồi regex tìm `current_tenant\(` hoặc `_cach_ly`
    # trong CHÍNH TÊN BIẾN ghép vào chuỗi — nó KHÔNG expand giá trị runtime. Một
    # cái tên trung tính (`dieu_kien`) làm cổng an ninh mù trước câu này dù SQL
    # chạy ra vẫn mang `tenant_id = portal.current_tenant()`. Đúng cái bẫy đã ăn
    # hằng `_LOC` của chính file này (Change Log 2026-08-13).
    vi_tu_cach_ly = [_CACH_LY]
    tham_so: list[date] = []
    if truoc_ngay is not None:
        tham_so.append(truoc_ngay)
        vi_tu_cach_ly.append(f"{_NGAY_FB} < ${len(tham_so)}::date")
    if tu_ngay is not None:
        tham_so.append(tu_ngay)
        vi_tu_cach_ly.append(f"{_NGAY_FB} >= ${len(tham_so)}::date")
    if tinh_den is not None:
        tham_so.append(tinh_den)
        vi_tu_cach_ly.append(f"{_NGAY_FB} <= ${len(tham_so)}::date")

    return await conn.fetchrow(
        f"""
        SELECT count(*) AS tong,
               avg(rating)::float8 AS trung_binh,
               count(*) FILTER (WHERE rating = 1) AS sao1,
               count(*) FILTER (WHERE rating = 2) AS sao2,
               count(*) FILTER (WHERE rating = 3) AS sao3,
               count(*) FILTER (WHERE rating = 4) AS sao4,
               count(*) FILTER (WHERE rating = 5) AS sao5
        FROM tenant_data.agent_feedback
        WHERE {" AND ".join(vi_tu_cach_ly)}
        """,
        *tham_so,
    )


async def kien_thuc(conn: asyncpg.Connection) -> asyncpg.Record:
    """Năm cặp (agent đọc được / tổng trong kho) của ô ⑤ màn Tổng quan.

    KHÔNG có cửa sổ thời gian, khác mọi hàm khác trong file này: kho kiến thức
    là trạng thái HIỆN TẠI của dữ liệu tenant (bao nhiêu dự án/phân khu/căn/tài
    liệu đã sẵn sàng, agent đang bật mấy kỹ năng), không phải một lưu lượng
    phát sinh trong 7 ngày — không có "kiến thức mới trong tuần" để đếm riêng.

    BA mục đầu dùng luật CHUNG `status = 'published'`. Hai mục cuối là NGOẠI
    LỆ, mỗi cái một kiểu:

    · `tai_lieu_tra_cuu` đọc `kb_files` — kho tệp của màn `/kb`, KHÔNG phải
      `tenant_data.documents`. Portal có HAI kho tài liệu và chúng khác cả
      bảng lẫn tool agent dùng để đọc (`kb_search` tra ↔ `get_document` gửi);
      đếm nhầm sang `documents` là chuyện ĐÃ XẢY RA (2026-08-14: ô ⑤ hiện 6/6
      trong khi `/kb` trống trơn). `kb_files` cũng không có cột `status` — nó
      dùng `state`, giá trị agent đọc được là `'san_sang'` (đã bóc chữ → chia
      đoạn → nhúng vector xong). ĐỪNG gộp hai luật về một điều kiện chung.
    · `ky_nang` khác LOẠI hẳn: nó không đếm dữ liệu trong kho mà đếm NĂNG LỰC
      agent — kho đủ dữ liệu nhưng kỹ năng tắt thì agent vẫn không làm được
      việc đó.

    `ky_nang_thay` đọc `tenant_data.agent_config` — bản PHẲNG của cấu hình
    ĐANG PHỤC VỤ KHÁCH (từ `0966` là nguồn duy nhất, không còn bản nháp).
    Mỗi tenant có HAI hàng (`sale`, `customer`), nên con số là
    số kỹ năng KHÁC NHAU đang bật ở ÍT NHẤT MỘT role — `jsonb_array_length` trên
    một subquery vô hướng như bản trước thì nổ «more than one row» ⇒ màn Tổng
    quan 500. Tenant chưa lưu lần nào ⇒ không có hàng ⇒ `count` ra 0, đúng nghĩa
    nghiệp vụ ("chưa cấu hình thì chưa bật kỹ năng nào").

    MẪU SỐ của `ky_nang` KHÔNG nằm ở đây — router lấy từ sổ kỹ năng
    (`config.contracts.TEN_KY_NANG`). Viết `12` vào câu SQL này thì ngày thêm
    kỹ năng thứ 13, thước vẽ đầy «đã đủ» trong khi còn một kỹ năng chưa bật.
    """
    return await conn.fetchrow(
        f"""
        SELECT
          (SELECT count(*) FILTER (WHERE status = 'published')
             FROM tenant_data.projects WHERE {_CACH_LY})                AS du_an_thay,
          (SELECT count(*) FROM tenant_data.projects WHERE {_CACH_LY})  AS du_an_tong,
          (SELECT count(*) FILTER (WHERE status = 'published')
             FROM tenant_data.zones WHERE {_CACH_LY})                   AS phan_khu_thay,
          (SELECT count(*) FROM tenant_data.zones WHERE {_CACH_LY})     AS phan_khu_tong,
          (SELECT count(*) FILTER (WHERE status = 'published')
             FROM tenant_data.units WHERE {_CACH_LY})                   AS can_thay,
          (SELECT count(*) FROM tenant_data.units WHERE {_CACH_LY})     AS can_tong,
          (SELECT count(*) FILTER (WHERE state = 'san_sang')
             FROM tenant_data.kb_files WHERE {_CACH_LY})                AS tai_lieu_tra_cuu_thay,
          (SELECT count(*) FROM tenant_data.kb_files WHERE {_CACH_LY})  AS tai_lieu_tra_cuu_tong,
          (SELECT count(DISTINCT k)
             FROM tenant_data.agent_config, jsonb_array_elements_text(skills) AS k
            WHERE {_CACH_LY})                                           AS ky_nang_thay
        """
    )
