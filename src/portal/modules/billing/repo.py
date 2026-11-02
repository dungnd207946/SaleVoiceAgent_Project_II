"""SQL của module billing. Trả `asyncpg.Record` thô — không biết HTTP, không Pydantic.

MỌI câu ở đây mang vị từ tenant qua RLS (`portal.current_tenant()`), và PHẢI được
gọi trong `tenant_conn()`. Đọc ngoài giao dịch trả 0 hàng, KHÔNG báo lỗi.

KHÔNG dùng hai view `billing.usage_by_session`/`usage_by_tenant_month` của 0942:
chúng thiếu `wall_ms` (cơ sở tính tiền của `(stt,'stream')`) và `channel`.
"""

from datetime import date
from decimal import Decimal

import asyncpg

from portal.api import loi

_CACH_LY = "tenant_id = portal.current_tenant()"
"""Tên biến PHẢI chứa `_CACH_LY` — cổng tests/isolation/test_loc_tenant_o_tang_app.py
regex trên CHÍNH TÊN BIẾN, không expand giá trị runtime. Đặt tên khác làm cổng mù
trước mọi câu SQL của file này."""

_COMPONENT_TIEN = ("llm", "tts", "stt", "embed", "search", "call", "vad", "speaker_verify")
"""Các dịch vụ có cột tiền riêng ở `theo_key()` — khớp ĐÚNG mã + thứ tự nhãn của
`component-hien.ts::NHAN` phía FE. MỘT danh sách sinh cả ba chỗ (FILTER trong CTE
`tien`, SELECT ngoài, GROUP BY ngoài) thay vì chép tay 7 dòng x 3 chỗ — chép tay là
chỗ một mã gõ sai làm đúng một cột luôn ra 0 mà không ai thấy (FILTER không khớp
hàng nào không phải lỗi SQL, nó là một cột hợp lệ toàn số 0)."""


_DLN = "purpose = 'kb_web'"
"""Usage của dữ liệu ngoài (`kb/web`): không thuộc phiên hội thoại nào, không có khoá agent."""


async def tien_tenant(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> tuple[Decimal, str]:
    """Tổng tiền + đơn vị tiền DUY NHẤT của một khoảng, cho tenant hiện tại.

    NÉM `LoiPortal` nếu khoảng này trộn NHIỀU đơn vị tiền — cộng VND với USD
    thành một số là nói dối. Đường tới được không cần bug gì cả:
    `billing.resolve_price_version` fallback về bảng giá `is_default` khi
    ngoài khoảng hiệu lực, nên một tenant đổi bảng giá GIỮA kỳ (khác đơn vị
    tiền với bảng cũ/mặc định) sẽ có usage của cùng kỳ được định giá bằng hai
    đơn vị khác nhau — không lỗi nào phát ra nếu không kiểm ở đây.

    Trước bản vá này hàm gọi chỗ này dùng `min(currency)` — cộng bất kể đơn vị
    rồi gắn một nhãn ĐƠN VỊ CHỌN NGẪU NHIÊN (alphabet) lên tổng đó.
    """
    hang = await conn.fetch(
        f"""
        SELECT currency, sum(amount) AS chi_phi
          FROM billing.rated_usage
         WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
         GROUP BY currency
        """,
        tu_ngay,
        den_ngay,
    )
    if len(hang) > 1:
        ds = ", ".join(sorted(r["currency"] for r in hang))
        raise loi.LoiPortal(
            "NHIEU_DON_VI_TIEN",
            409,
            f"khoảng thời gian này có nhiều đơn vị tiền khác nhau ({ds}) trong cùng "
            "một tenant — không thể cộng thành một số có nghĩa. Nguyên nhân thường gặp: "
            "tenant đổi bảng giá GIỮA kỳ sang một bảng giá khác đơn vị tiền. Chọn một "
            "khoảng hẹp hơn, nằm trọn trong một bảng giá.",
        )
    if not hang:
        return Decimal("0"), "VND"
    return hang[0]["chi_phi"], hang[0]["currency"]


async def tong_quan(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> dict[str, object]:
    """`voice_sec` = thời lượng CUỘC GỌI (`component = 'call'`), KHÔNG phải tổng
    `audio_sec` mọi component. `vad`/`stt`/`tts`/`speaker_verify`/`call` đo
    CHỒNG LẤN cùng một khoảng audio (mỗi component quét/nói/nghe cùng cuộc gọi
    theo cách của nó) — cộng thẳng chúng lại thổi phồng số này lên nhiều lần so
    với thời lượng thật (đo được: 466.22s cộng chéo trong khi cuộc gọi thật chỉ
    176.85s, gấp 2.64×). `call` là mét đồng hồ treo tường — một hàng mỗi phiên
    voice — nên nó là con số đúng nghĩa "thời lượng voice" mà người đọc KPI này
    mong đợi. Phiên chat không có hàng `call` nên đúng ra phải là 0, không phải
    NULL — `FILTER` trả `NULL` khi không hàng nào khớp, `COALESCE` đưa về 0.

    Trả `dict` (không phải `asyncpg.Record`) vì `chi_phi`/`currency` được tính
    riêng qua `tien_tenant()` (kiểm đơn vị tiền, xem docstring hàm đó) rồi ghép
    vào — router chỉ dùng `r["..."]`, cả hai kiểu đều hỗ trợ subscript như nhau.
    """
    chi_phi, currency = await tien_tenant(conn, tu_ngay, den_ngay)
    row = await conn.fetchrow(
        f"""
        WITH ev AS (
            SELECT * FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
        )
        SELECT COALESCE(sum(ev.input_tokens), 0)::bigint      AS input_tokens,
               COALESCE(sum(ev.output_tokens), 0)::bigint     AS output_tokens,
               COALESCE(sum(ev.cache_read_tokens), 0)::bigint AS cache_read_tokens,
               COALESCE(sum(ev.audio_sec) FILTER (WHERE ev.component = 'call'), 0)::float AS voice_sec,
               (count(DISTINCT ev.session_id) FILTER (WHERE NOT ev.{_DLN}))::int AS so_phien,
               (SELECT COALESCE(sum(r.amount), 0) FROM billing.rated_usage r
                 WHERE r.{_CACH_LY} AND r.{_DLN}
                   AND r.occurred_at >= $1::timestamptz AND r.occurred_at < $2::timestamptz) AS chi_phi_du_lieu_ngoai,
               (SELECT count(DISTINCT c.agent_key_id) FROM tenant_data.conversations c
                 WHERE c.{_CACH_LY} AND c.agent_key_id IS NOT NULL
                   AND c.session_id IN (SELECT session_id FROM ev))::int AS so_key
          FROM ev
        """,
        tu_ngay,
        den_ngay,
    )
    return {**dict(row), "chi_phi": chi_phi, "currency": currency}


async def canh_bao(conn: asyncpg.Connection) -> asyncpg.Record:
    """Bốn con số vận hành. `price_coverage_gap` khác rỗng = đang mất doanh thu."""
    return await conn.fetchrow(
        f"""
        SELECT (SELECT count(*) FROM billing.price_coverage_gap
                 WHERE {_CACH_LY})::int                        AS thieu_gia,
               (SELECT count(*) FROM billing.purpose_unclassified)::int
                                                               AS nhan_chua_phan_loai,
               (SELECT count(*) FROM billing.unbillable_event
                 WHERE {_CACH_LY})::int                        AS event_khong_so_do,
               (SELECT count(*) FROM billing.usage_events
                 WHERE {_CACH_LY} AND component = 'llm' AND NOT exact)::int
                                                               AS llm_khong_chinh_xac
        """
    )


async def theo_key(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> list[asyncpg.Record]:
    """LEFT JOIN conversations — nhóm `agent_key_id IS NULL` phải còn lại trong kết quả.

    INNER JOIN ở đây sẽ âm thầm làm mất usage của phiên chưa có hàng conversations
    (agent ghi usage trước khi tạo phiên). Tổng sẽ nhỏ hơn hoá đơn mà không lỗi nào.

    `voice_sec` = thời lượng CUỘC GỌI (`component = 'call'`) — xem docstring dài
    ở `tong_quan()` để biết lý do KHÔNG cộng thẳng `audio_sec` mọi component.

    Bảy cột `chi_phi_<component>` (bảng «Lượt dùng theo khoá» phía FE, thay ba
    cột token in/out/cache read cũ) tách `chi_phi` của CHÍNH hàng đó theo dịch vụ
    — cùng CTE `tien` đang cộng ra `chi_phi`, chỉ thêm `FILTER (WHERE component =
    …)` cho mỗi mã trong `_COMPONENT_TIEN`. Trong MỘT hàng, tổng bảy cột đó LUÔN
    bằng `chi_phi` của hàng ấy — TRỪ KHI kỳ có usage của một component NGOÀI bảy
    mã đó (`usage_events.component` là `text` không CHECK, xem `theo_component()`):
    phần tiền đó vẫn cộng vào `chi_phi`/`chi_phi_tong` như trước nhưng không lộ ra
    ở cột nào trong bảy cột — đúng thứ `canh_bao.thieu_gia`/`price_coverage_gap`
    đã có chỗ báo, không phải lỗi ở đây.

    ⚠️ NHÓM THEO `khoa` = HỢP `agent_key_id` của CẢ `ev` LẪN `tien`, không neo
    một chiều vào `ev` như bản trước (2026-08-27, vá lỗi đo được: Σ `chi_phi`
    của bảng này lệch `tien_tenant()` khi một phiên được GÁN/ĐỔI `agent_key_id`
    SAU KHI usage của nó đã định giá). Lý do: `rated_usage.agent_key_id` ĐÔNG
    CỨNG tại thời điểm định giá (trigger AFTER INSERT, `0950`, tự LEFT JOIN
    `conversations` lúc đó), còn `ev.agent_key_id` ở đây suy SỐNG mỗi lần
    query. `theo_key_giu_usage_khi_chua_co_hang_conversations` đã chứng minh
    usage ghi được TRƯỚC khi có hàng `conversations` — nên hai giá trị hoàn
    toàn có thể lệch nhau về sau. Neo một chiều vào `ev` (bản cũ: `FROM ev
    LEFT JOIN tien`) làm dòng `tien` mang `agent_key_id` CŨ không còn khớp
    được BẤT KỲ dòng `ev` nào nữa ⇒ bị loại khỏi kết quả HOÀN TOÀN — tiền đó
    biến mất khỏi mọi nhóm hiển thị (kể cả «chưa phân loại»), dù vẫn nguyên
    trong `chi_phi_tong`. Hợp `khoa` từ cả hai phía đảm bảo: một khoá đo được
    ở tiền (`tien`) LUÔN có một hàng trong kết quả, dù `ev` (số đo/nhãn) không
    còn khớp được nó — khi đó hàng đó hiện `so_phien`/`so_event` = 0 (đúng
    thực tế: không phiên NÀO ở live-join hiện quy về khoá đó nữa), nhưng
    KHÔNG BAO GIỜ mất tiền. `count(ev.event_id)` (không phải `count(*)`) là
    điều kiện BẮT BUỘC của phép vá này — sau khi thêm LEFT JOIN từ `khoa`,
    một khoá không khớp `ev` vẫn sinh đúng MỘT hàng (cột `ev.*` toàn NULL),
    và `count(*)` sẽ đếm nhầm hàng đó thành 1 sự kiện thay vì 0.
    """
    cot_tien_cte = ",\n                   ".join(
        f"COALESCE(sum(amount) FILTER (WHERE component = '{ma}'), 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    cot_tien_select = ",\n               ".join(
        f"COALESCE(t.chi_phi_{ma}, 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    nhom_tien = ", ".join(f"t.chi_phi_{ma}" for ma in _COMPONENT_TIEN)
    return await conn.fetch(
        f"""
        WITH ev AS (
            SELECT e.session_id, c.agent_key_id, (e.{_DLN}) AS du_lieu_ngoai,
                   e.input_tokens, e.output_tokens, e.cache_read_tokens,
                   e.audio_sec, e.component, e.event_id
              FROM billing.usage_events e
              LEFT JOIN tenant_data.conversations c
                     ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
             WHERE e.{_CACH_LY} AND e.occurred_at >= $1::timestamptz AND e.occurred_at < $2::timestamptz
        ), tien AS (
            SELECT agent_key_id, ({_DLN}) AS du_lieu_ngoai, sum(amount) AS chi_phi,
                   {cot_tien_cte}
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1, 2
        ), khoa AS (
            SELECT agent_key_id, du_lieu_ngoai FROM ev
            UNION
            SELECT agent_key_id, du_lieu_ngoai FROM tien
        )
        SELECT khoa.agent_key_id, khoa.du_lieu_ngoai,
               COALESCE(k.label, '')      AS label,
               COALESCE(k.key_prefix, '') AS key_prefix,
               COALESCE(k.created_by, '') AS nguoi_tao,
               u.name                     AS nguoi_tao_ten,
               (k.revoked_at IS NOT NULL) AS da_thu_hoi,
               (CASE WHEN khoa.du_lieu_ngoai THEN 0 ELSE count(DISTINCT ev.session_id) END)::int AS so_phien,
               COALESCE(sum(ev.input_tokens), 0)::bigint       AS input_tokens,
               COALESCE(sum(ev.output_tokens), 0)::bigint      AS output_tokens,
               COALESCE(sum(ev.cache_read_tokens), 0)::bigint  AS cache_read_tokens,
               COALESCE(sum(ev.audio_sec) FILTER (WHERE ev.component = 'call'), 0)::float AS voice_sec,
               count(ev.event_id)::int                         AS so_event,
               COALESCE(t.chi_phi, 0)                          AS chi_phi,
               {cot_tien_select}
          FROM khoa
          LEFT JOIN ev                   ON ev.agent_key_id IS NOT DISTINCT FROM khoa.agent_key_id
                                        AND ev.du_lieu_ngoai = khoa.du_lieu_ngoai
          LEFT JOIN tien t               ON t.agent_key_id IS NOT DISTINCT FROM khoa.agent_key_id
                                        AND t.du_lieu_ngoai = khoa.du_lieu_ngoai
          LEFT JOIN control.agent_keys k ON k.id = khoa.agent_key_id
          LEFT JOIN control.users u      ON u.id = k.created_by
         GROUP BY khoa.agent_key_id, khoa.du_lieu_ngoai, k.label, k.key_prefix, k.created_by, u.name,
                  k.revoked_at, t.chi_phi, {nhom_tien}
         ORDER BY chi_phi DESC, khoa.agent_key_id NULLS LAST
        """,
        tu_ngay,
        den_ngay,
    )


async def theo_owner(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> list[asyncpg.Record]:
    """Gộp theo `agent_keys.created_by` — trả lời "user nào dùng bao nhiêu".

    Tiền và phiên đều PHẢI được gộp một-hàng-một-khoá TRƯỚC khi JOIN, đúng khuôn
    `theo_key`. Bản trước JOIN thẳng `billing.rated_usage` (hạt event) với
    `tenant_data.conversations` (hạt phiên) chỉ qua `agent_key_id` — một khoá có
    N phiên thì mỗi hàng `rated_usage` của khoá đó bị nhân bản N lần trước khi
    `sum(r.amount)` cộng, thổi phồng `chi_phi` đúng theo hệ số N (đo được:
    khoá có 2 phiên ra `chi_phi` gấp đôi số thật). `so_key`/`so_phien` không lộ
    vì cả hai đều `COUNT DISTINCT` — chỉ cột tiền sai.

    JOIN với `control.agent_keys` PHẢI là LEFT, không INNER: `tien.agent_key_id`
    có một nhóm `NULL` (usage chưa gán được khoá — cùng lý do `theo_key` giữ
    nhóm này, xem docstring hàm đó) và `NULL = NULL` không khớp trong SQL, nên
    INNER JOIN âm thầm LOẠI nhóm đó khỏi kết quả — tổng theo owner khi đó nhỏ
    hơn tổng theo key/tổng tenant mà không lỗi nào phát ra (đo được: thiếu ĐÚNG
    số tiền của nhóm mồ côi). Nhóm mồ côi ra đời với `user_id = NULL` — một
    dòng "không có chủ" tường minh, không bị ẩn.

    `so_phien` PHẢI được lọc theo CÙNG khoảng ngày `[tu_ngay, den_ngay)` với
    tiền — trước bản vá này `phien` đếm TOÀN BỘ lịch sử `tenant_data.
    conversations` của khoá, không giới hạn theo khoảng, nên hai màn "theo khoá"
    (có lọc) và "theo owner" (không lọc) hiện hai số phiên khác nhau cho cùng
    một khoá trong cùng một kỳ. Sửa bằng cách suy phiên từ CHÍNH khoảng usage
    (`ev`, giống `theo_key`) rồi mới quy về owner qua khoá.

    ⚠️ BẢNG DẪN ĐỔI TỪ `tien` SANG `ev` (2026-08-24, cùng lượt thêm sáu cột
    lượng cho bảng của `/usage`) — KHÔNG phải dọn dẹp, nó sửa một chỗ đếm
    thiếu: `FROM tien` nghĩa là owner chỉ tồn tại khi usage của họ đã sinh ra
    TIỀN, nên một component đo được mà chưa có dòng giá nào khớp (`component`
    là `text` không CHECK — `price_coverage_gap` khác rỗng) làm owner đó biến
    khỏi bảng cùng toàn bộ số đo của họ. Đúng lỗi mà `theo_component()` phải
    đặt `usage_events` làm vế trái để tránh: đảo vế là ẩn đúng phần đang mất
    doanh thu. Nay `chi_phi` `COALESCE(…, 0)` — 0 nghĩa là «chưa có giá», không
    phải «không dùng».

    ⚠️ GỘP HAI TẦNG, KHÔNG MỘT TẦNG: `theo_khoa` gộp về hạt KHOÁ trước, rồi
    câu ngoài mới gộp về hạt OWNER. Gộp một tầng (LEFT JOIN `tien` hạt khoá vào
    `ev` hạt event rồi `sum(chi_phi)`) nhân tiền lên đúng số event của khoá —
    chính bug đã đo được và ghi ở đoạn trên, chỉ đổi hệ số.

    Bảy cột `chi_phi_<component>` (2026-08-27, cùng bộ mã `_COMPONENT_TIEN` đã
    dùng ở `theo_key()`) tách `chi_phi` theo dịch vụ cho bảng «Lượt dùng theo
    người tạo» — CTE `tien` mọc thêm `FILTER (WHERE component = …)` giống hệt
    `theo_key`, rồi câu ngoài `sum()` từng cột đó theo owner CẠNH `sum(t.chi_phi)`
    đã có sẵn (không phải một câu SQL thứ hai) — `tien` vẫn ở hạt KHOÁ nên
    `sum()` qua nhiều khoá của một owner không nhân bản, cùng lý lẽ hai tầng ở
    trên.
    """
    cot_tien_cte = ",\n                   ".join(
        f"COALESCE(sum(amount) FILTER (WHERE component = '{ma}'), 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    cot_tien_owner_select = ",\n               ".join(
        f"COALESCE(sum(t.chi_phi_{ma}), 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    return await conn.fetch(
        f"""
        WITH ev AS (
            SELECT e.session_id, c.agent_key_id, (e.{_DLN}) AS du_lieu_ngoai,
                   e.input_tokens, e.output_tokens, e.cache_read_tokens,
                   e.audio_sec, e.component
              FROM billing.usage_events e
              LEFT JOIN tenant_data.conversations c
                     ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
             WHERE e.{_CACH_LY} AND e.occurred_at >= $1::timestamptz AND e.occurred_at < $2::timestamptz
        ), tien AS (
            SELECT agent_key_id, ({_DLN}) AS du_lieu_ngoai, sum(amount) AS chi_phi,
                   {cot_tien_cte}
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1, 2
        ), theo_khoa AS (
            SELECT agent_key_id, du_lieu_ngoai,
                   (CASE WHEN du_lieu_ngoai THEN 0 ELSE count(DISTINCT session_id) END)::int AS so_phien,
                   COALESCE(sum(input_tokens), 0)::bigint       AS input_tokens,
                   COALESCE(sum(output_tokens), 0)::bigint      AS output_tokens,
                   COALESCE(sum(cache_read_tokens), 0)::bigint  AS cache_read_tokens,
                   COALESCE(sum(audio_sec) FILTER (WHERE component = 'call'), 0)::float AS voice_sec,
                   count(*)::int                                AS so_event
              FROM ev
             GROUP BY 1, 2
        )
        SELECT k.created_by AS user_id, u.name AS ten, u.email, kh.du_lieu_ngoai,
               count(DISTINCT k.id)::int                     AS so_key,
               COALESCE(sum(kh.so_phien), 0)::int            AS so_phien,
               COALESCE(sum(kh.input_tokens), 0)::bigint     AS input_tokens,
               COALESCE(sum(kh.output_tokens), 0)::bigint    AS output_tokens,
               COALESCE(sum(kh.cache_read_tokens), 0)::bigint AS cache_read_tokens,
               COALESCE(sum(kh.voice_sec), 0)::float         AS voice_sec,
               COALESCE(sum(kh.so_event), 0)::int            AS so_event,
               COALESCE(sum(t.chi_phi), 0)                   AS chi_phi,
               {cot_tien_owner_select}
          FROM theo_khoa kh
          LEFT JOIN control.agent_keys k ON k.id = kh.agent_key_id
          LEFT JOIN control.users u      ON u.id = k.created_by
          LEFT JOIN tien t               ON t.agent_key_id IS NOT DISTINCT FROM kh.agent_key_id
                                        AND t.du_lieu_ngoai = kh.du_lieu_ngoai
         GROUP BY k.created_by, u.name, u.email, kh.du_lieu_ngoai
         ORDER BY chi_phi DESC, k.created_by NULLS LAST
        """,
        tu_ngay,
        den_ngay,
    )


async def liet_ke_phien(
    conn: asyncpg.Connection, tu_ngay: date, den_ngay: date, limit: int, offset: int
) -> list[asyncpg.Record]:
    """`voice_sec` = thời lượng CUỘC GỌI (`component = 'call'`) — xem docstring
    dài ở `tong_quan()` để biết lý do KHÔNG cộng thẳng `audio_sec` mọi component.

    Bảy cột `chi_phi_<component>` (2026-08-27, cùng bộ mã `_COMPONENT_TIEN` đã
    dùng ở `theo_key()`/`theo_owner()`) tách `chi_phi` theo dịch vụ. Đơn giản
    hơn hai hàm kia: CTE `tien` đã ở ĐÚNG hạt `session_id` (khớp hạt của hàng
    kết quả), nên chỉ cần thêm `FILTER` vào CTE đó — không cần tầng gộp thứ
    hai như `theo_owner()`.
    """
    cot_tien_cte = ",\n                   ".join(
        f"COALESCE(sum(r.amount) FILTER (WHERE r.component = '{ma}'), 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    cot_tien_select = ",\n               ".join(
        f"COALESCE(t.chi_phi_{ma}, 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    return await conn.fetch(
        f"""
        WITH ev AS (
            SELECT session_id,
                   min(occurred_at)                       AS bat_dau,
                   max(channel)                           AS channel,
                   count(DISTINCT turn_idx)::int          AS so_turn,
                   sum(input_tokens)::bigint              AS input_tokens,
                   sum(output_tokens)::bigint             AS output_tokens,
                   COALESCE(sum(audio_sec) FILTER (WHERE component = 'call'), 0)::float AS voice_sec,
                   bool_and(exact)                        AS exact
              FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
               AND NOT {_DLN}
             GROUP BY session_id
        ), tien AS (
            SELECT e.session_id, sum(r.amount) AS chi_phi,
                   {cot_tien_cte}
              FROM billing.rated_usage r
              JOIN billing.usage_events e ON e.event_id = r.event_id
             WHERE r.{_CACH_LY} AND r.occurred_at >= $1::timestamptz AND r.occurred_at < $2::timestamptz
               AND NOT r.{_DLN}
             GROUP BY 1
        )
        SELECT ev.session_id, c.agent_key_id, k.label AS key_label,
               c.customer_name, c.phone, ev.channel, ev.bat_dau, ev.so_turn,
               ev.input_tokens, ev.output_tokens, ev.voice_sec, ev.exact,
               COALESCE(t.chi_phi, 0) AS chi_phi,
               {cot_tien_select},
               count(*) OVER ()::int  AS total
          FROM ev
          LEFT JOIN tenant_data.conversations c
                 ON c.tenant_id = portal.current_tenant() AND c.session_id = ev.session_id
          LEFT JOIN control.agent_keys k ON k.id = c.agent_key_id
          LEFT JOIN tien t ON t.session_id = ev.session_id
         ORDER BY ev.bat_dau DESC
         LIMIT $3 OFFSET $4
        """,
        tu_ngay,
        den_ngay,
        limit,
        offset,
    )


async def doc_phien(conn: asyncpg.Connection, session_id: str) -> asyncpg.Record | None:
    """Tóm tắt của ĐÚNG một phiên — cùng tập cột với `liet_ke_phien` (để
    `_phien_out()` ở tầng router dùng chung), nhưng lọc theo `session_id`,
    KHÔNG theo khoảng ngày.

    Đừng gọi `liet_ke_phien(conn, tu_ngay, den_ngay, 1, 0)` rồi lấy `hang[0]`
    để giả lập việc này: nó không nhận session_id, chỉ `ORDER BY bat_dau DESC`
    trong khoảng — `hang[0]` là phiên MỚI NHẤT trong khoảng đó, không phải
    phiên người gọi hỏi. Mở phiên A có thể trả tên khách, sđt, khoá và tổng
    tiền của phiên B nếu B mới hơn.

    `voice_sec` = thời lượng CUỘC GỌI (`component = 'call'`) — xem docstring dài
    ở `tong_quan()` để biết lý do KHÔNG cộng thẳng `audio_sec` mọi component.

    Bảy cột `chi_phi_<component>` — xem docstring `liet_ke_phien()`, cùng CTE
    `tien` ở hạt `session_id`, chỉ khác lọc theo `session_id = $1` thay vì
    khoảng ngày.
    """
    cot_tien_cte = ",\n                   ".join(
        f"COALESCE(sum(r.amount) FILTER (WHERE r.component = '{ma}'), 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    cot_tien_select = ",\n               ".join(
        f"COALESCE(t.chi_phi_{ma}, 0) AS chi_phi_{ma}" for ma in _COMPONENT_TIEN
    )
    return await conn.fetchrow(
        f"""
        WITH ev AS (
            SELECT session_id,
                   min(occurred_at)                       AS bat_dau,
                   max(channel)                           AS channel,
                   count(DISTINCT turn_idx)::int          AS so_turn,
                   sum(input_tokens)::bigint              AS input_tokens,
                   sum(output_tokens)::bigint             AS output_tokens,
                   COALESCE(sum(audio_sec) FILTER (WHERE component = 'call'), 0)::float AS voice_sec,
                   bool_and(exact)                        AS exact
              FROM billing.usage_events
             WHERE {_CACH_LY} AND session_id = $1
             GROUP BY session_id
        ), tien AS (
            SELECT e.session_id, sum(r.amount) AS chi_phi,
                   {cot_tien_cte}
              FROM billing.rated_usage r
              JOIN billing.usage_events e ON e.event_id = r.event_id
             WHERE r.{_CACH_LY} AND e.session_id = $1
             GROUP BY 1
        )
        SELECT ev.session_id, c.agent_key_id, k.label AS key_label,
               c.customer_name, c.phone, ev.channel, ev.bat_dau, ev.so_turn,
               ev.input_tokens, ev.output_tokens, ev.voice_sec, ev.exact,
               COALESCE(t.chi_phi, 0) AS chi_phi,
               {cot_tien_select}
          FROM ev
          LEFT JOIN tenant_data.conversations c
                 ON c.tenant_id = portal.current_tenant() AND c.session_id = ev.session_id
          LEFT JOIN control.agent_keys k ON k.id = c.agent_key_id
          LEFT JOIN tien t ON t.session_id = ev.session_id
        """,
        session_id,
    )


async def event_cua_phien(conn: asyncpg.Connection, session_id: str) -> list[asyncpg.Record]:
    """Timeline theo `seq`. Tiền từng event = tổng mọi metric của event đó."""
    return await conn.fetch(
        f"""
        SELECT e.event_id, e.seq, e.turn_idx, e.component, e.purpose, e.provider,
               e.model, e.input_tokens, e.output_tokens, e.cache_read_tokens,
               e.audio_sec::float AS audio_sec, e.units, e.text_units, e.exact, e.occurred_at,
               COALESCE((SELECT sum(r.amount) FROM billing.rated_usage r
                          WHERE r.event_id = e.event_id), 0) AS chi_phi
          FROM billing.usage_events e
         WHERE e.{_CACH_LY} AND e.session_id = $1
         ORDER BY e.seq, e.component
        """,
        session_id,
    )


async def theo_ngay(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> list[asyncpg.Record]:
    """Chi phí từng NGÀY của kỳ, TÁCH THEO COMPONENT — trục thời gian mục ② `/usage`.

    HÌNH DẠNG: một hàng cho mỗi cặp (ngày, component); ngày không có usage trả
    ĐÚNG MỘT hàng với `component IS NULL` và `chi_phi IS NULL`. Router gom lại
    thành một mảng ngày, mỗi ngày mang tổng + danh sách phần. Tách theo
    component ở đây (chứ không chỉ tổng ngày) vì tooltip của chart phải trả lời
    «ngày này tốn vào cái gì» — thẻ `theo_component` bên cạnh chỉ trả lời câu
    đó cho CẢ KỲ, không cho từng ngày.

    Sắp `chi_phi DESC NULLS LAST` trong mỗi ngày: tooltip đọc từ trên xuống
    theo độ lớn, và ngày rỗng có đúng một hàng nên thứ tự không đổi gì.

    NGÀY KHÔNG CÓ USAGE VẪN PHẢI CÓ HÀNG (`generate_series` bên trái, `LEFT
    JOIN`). Trả về chỉ những ngày có dữ liệu thì FE nối thẳng hai điểm hai bên
    chỗ trũng — một ngày agent không chạy sẽ được vẽ thành một đoạn dốc ĐI QUA
    mức tiền dương, tức biểu đồ nói sai đúng cái nó sinh ra để nói. Đây cũng là
    lý do việc chèn ngày rỗng nằm ở SQL chứ không ở FE: FE không biết biên kỳ
    theo múi giờ của server.

    GỘP NGÀY bằng `date_trunc` trên CÙNG một múi giờ với vế lọc `>= $1::
    timestamptz` — cả hai đều theo TimeZone của phiên. Ép một bên sang UTC mà
    quên bên kia là lệch một ngày ở hai đầu kỳ, và lệch im lặng.

    KHÔNG chặn số ngày: `_khoang()` ở router mới là chỗ biết kỳ nào hợp lệ.
    Bốn kỳ dựng sẵn của `/usage` tối đa 31 hàng.
    """
    return await conn.fetch(
        f"""
        WITH khung AS (
            SELECT generate_series($1::date, $2::date - 1, '1 day')::date AS ngay
        ), tien AS (
            SELECT date_trunc('day', occurred_at)::date AS ngay, component, sum(amount) AS chi_phi
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1, 2
        )
        SELECT k.ngay, t.component, t.chi_phi
          FROM khung k LEFT JOIN tien t ON t.ngay = k.ngay
         ORDER BY k.ngay, t.chi_phi DESC NULLS LAST
        """,
        tu_ngay,
        den_ngay,
    )


async def usage_theo_ngay(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> list[asyncpg.Record]:
    """SỐ ĐO từng NGÀY tách theo COMPONENT + số phiên mỗi ngày — màn `/usage`.

    Song sinh của `theo_ngay()` nhưng đổi CÂU HỎI: ở đó là TIỀN (`rated_usage`),
    ở đây là LƯỢNG (`usage_events`). Hai endpoint tách nhau vì `/usage` không
    được hiện tiền và `/billing` không cần số đo theo ngày — xem docstring
    `contracts.UsageTheoNgayOut`.

    HÌNH DẠNG giống `theo_ngay()`: một hàng cho mỗi cặp (ngày, component); ngày
    không có usage trả ĐÚNG MỘT hàng `component IS NULL`. Router gom thành mảng
    ngày.

    NĂM BẤT BIẾN, mỗi cái là một chỗ đã sai một lần ở đâu đó trong module này:

    1. CHỈ ĐỌC `usage_events`, KHÔNG `JOIN rated_usage`. Một event LLM sinh tới
       BỐN hàng `rated_usage` (bốn metric), nên JOIN rồi `sum(input_tokens)` là
       nhân bản số đo lên bốn lần. Đúng lớp lỗi `theo_owner()` đã dính một lần
       và `theo_component()` phải tách hai CTE để tránh.

    2. NGÀY RỖNG VẪN CÓ HÀNG (`generate_series` bên trái + `LEFT JOIN`). Trả
       thưa thì FE nối thẳng hai điểm hai bên chỗ trũng — ngày agent không chạy
       được vẽ thành một đoạn dốc ĐI QUA mức dương, tức biểu đồ nói sai đúng
       cái nó sinh ra để nói. Việc chèn ngày rỗng nằm ở SQL chứ không ở FE vì
       FE không biết biên kỳ theo múi giờ của server.

    3. `date_trunc('day', occurred_at)` KHÔNG kèm `AT TIME ZONE` — CÙNG biểu
       thức với `theo_ngay()`. Đổi múi giờ ở một trong hai là biểu đồ lượng và
       biểu đồ tiền của CÙNG một tenant lệch nhau một ngày ở hai đầu kỳ, và
       không cổng nào bắt được vì mỗi bên tự nó vẫn nhất quán.

    4. `so_phien` = `count(DISTINCT session_id)` trên `usage_events` — CÙNG định
       nghĩa với `tong_quan()`. Đếm từ `tenant_data.conversations` ra con số
       khác (phiên có hàng conversations mà chưa phát sinh usage), và khi đó
       tooltip của biểu đồ không khớp dải KPI ngay trên nó.

    5. `wall_ms_stream`/`text_units_hoi_thoai` LỌC THEO `purpose`, KHÔNG cộng
       cả component. `wall_ms` được bên agent ghi cho MỌI event (nó là độ trễ
       xử lý), nhưng chỉ dòng `stt` + `purpose='stream'` mới là «thời gian
       stream mở» mà `billing.pricing_basis` đem tính tiền. Đo trên DB dev
       2026-08-25: `stt` có 177.564,9 ms ở `purpose='stream'` và 10.380,0 ms ở
       `purpose='conversation'` — cộng cả hai rồi gắn nhãn «stream» là sai 6%
       ngay hôm nay, và sai không giới hạn vào ngày agent đổi độ trễ. Cùng lý
       do với `text_units`: migration `0948` định nghĩa vế ký tự của `stt` CHỈ
       cho `purpose='conversation'`.

       ⚠️ Đây KHÔNG phải hai cột thay thế `text_units`. `text_units` (không
       lọc) vẫn là số đo của tab TTS/Embed; `text_units_hoi_thoai` là vế ĐỘC
       LẬP của tab STT. Hai cột cùng tên gốc mà khác mẫu số — đừng dùng lẫn.
    """
    return await conn.fetch(
        f"""
        WITH khung AS (
            SELECT generate_series($1::date, $2::date - 1, '1 day')::date AS ngay
        ), so_do AS (
            SELECT date_trunc('day', occurred_at)::date AS ngay, component,
                   count(*)::int                  AS so_event,
                   sum(input_tokens)::bigint      AS input_tokens,
                   sum(output_tokens)::bigint     AS output_tokens,
                   sum(cache_read_tokens)::bigint AS cache_read_tokens,
                   sum(audio_sec)::float          AS audio_sec,
                   sum(text_units)::bigint        AS text_units,
                   sum(units)::bigint             AS units,
                   -- Hai số đo LỌC THEO `purpose` — xem bất biến 5. `COALESCE`
                   -- ở ngay đây: `sum() FILTER` không khớp hàng nào trả NULL,
                   -- và NULL ra tới `PhanUsageNgayOut` là `ValidationError`.
                   COALESCE(sum(wall_ms) FILTER (WHERE purpose = 'stream'), 0)::float
                       AS wall_ms_stream,
                   COALESCE(sum(text_units) FILTER (WHERE purpose = 'conversation'), 0)::bigint
                       AS text_units_hoi_thoai,
                   COALESCE(sum(input_tokens + output_tokens + cache_read_tokens) FILTER (WHERE {_DLN}), 0)::bigint
                       AS token_du_lieu_ngoai,
                   COALESCE(sum(text_units) FILTER (WHERE {_DLN}), 0)::bigint
                       AS text_units_du_lieu_ngoai
              FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1, 2
        ), phien AS (
            SELECT date_trunc('day', occurred_at)::date AS ngay,
                   count(DISTINCT session_id)::int AS so_phien
              FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
               AND NOT {_DLN}
             GROUP BY 1
        )
        SELECT k.ngay, COALESCE(p.so_phien, 0)::int AS so_phien,
               d.component, d.so_event, d.input_tokens, d.output_tokens,
               d.cache_read_tokens, d.audio_sec, d.text_units, d.units,
               d.wall_ms_stream, d.text_units_hoi_thoai,
               d.token_du_lieu_ngoai, d.text_units_du_lieu_ngoai
          FROM khung k
          LEFT JOIN so_do d ON d.ngay = k.ngay
          LEFT JOIN phien p ON p.ngay = k.ngay
         ORDER BY k.ngay, d.component
        """,
        tu_ngay,
        den_ngay,
    )


async def theo_component(conn: asyncpg.Connection, tu_ngay: date, den_ngay: date) -> list[asyncpg.Record]:
    """Tiền + SỐ ĐO của từng component — thẻ phải của mục ② màn `/usage`.

    HAI HẠT KHÁC NHAU, GỘP RIÊNG RỒI MỚI NỐI. Số đo nằm ở `usage_events` (một
    hàng/event), tiền nằm ở `rated_usage` (một hàng/event/metric — một event
    LLM sinh tới 4 hàng). JOIN thẳng hai bảng rồi `sum` là nhân bản số đo theo
    số metric có giá: `input_tokens` của một event LLM sẽ bị cộng 4 lần. Cùng
    lớp lỗi mà `theo_owner()` đã dính một lần và ghi lại trong docstring của nó.

    VẾ TRÁI LÀ `usage_events`, KHÔNG PHẢI `rated_usage`: component đo được mà
    CHƯA CÓ GIÁ (`vad` khi chưa ai đặt giá, hoặc bất kỳ tổ hợp nào đang nằm
    trong `price_coverage_gap`) phải hiện ra với `chi_phi = 0`. Đảo vế là ẩn
    đúng những dòng đang mất doanh thu — thứ dải cảnh báo `thieu_gia` tồn tại
    để chỉ ra.

    KHÔNG có hàng tổng cho cột số đo, và FE cũng không được tự cộng: `audio_sec`
    của `vad`/`stt`/`call` đo những quãng CHỒNG LẤN nhau (xem docstring
    `tong_quan()`). Chỉ cột tiền cộng được.
    """
    return await conn.fetch(
        f"""
        WITH so_do AS (
            SELECT component,
                   count(*)::int                  AS so_event,
                   sum(input_tokens)::bigint      AS input_tokens,
                   sum(output_tokens)::bigint     AS output_tokens,
                   sum(cache_read_tokens)::bigint AS cache_read_tokens,
                   sum(audio_sec)::float          AS audio_sec,
                   sum(text_units)::bigint        AS text_units,
                   sum(units)::bigint             AS units
              FROM billing.usage_events
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1
        ), tien AS (
            SELECT component, sum(amount) AS chi_phi,
                   COALESCE(sum(amount) FILTER (WHERE {_DLN}), 0) AS chi_phi_du_lieu_ngoai
              FROM billing.rated_usage
             WHERE {_CACH_LY} AND occurred_at >= $1::timestamptz AND occurred_at < $2::timestamptz
             GROUP BY 1
        )
        SELECT d.component, d.so_event, d.input_tokens, d.output_tokens, d.cache_read_tokens,
               d.audio_sec, d.text_units, d.units, COALESCE(t.chi_phi, 0) AS chi_phi,
               COALESCE(t.chi_phi_du_lieu_ngoai, 0) AS chi_phi_du_lieu_ngoai
          FROM so_do d LEFT JOIN tien t ON t.component = d.component
         ORDER BY COALESCE(t.chi_phi, 0) DESC, d.component
        """,
        tu_ngay,
        den_ngay,
    )
