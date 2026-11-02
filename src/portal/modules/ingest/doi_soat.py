"""Đối soát — so bản kê của khách với bảng của mình.

Xem `docs/superpowers/specs/2026-08-14-cong-nap-du-lieu-ngoai-design.md` §7 và
docstring của migration `0928`.

── HAI HƯỚNG LỆCH, HAI CÁCH XỬ LÝ HOÀN TOÀN KHÁC NHAU ──────────────────────
  · **Khách có, mình thiếu hoặc cũ hơn** ⇒ mình hụt một lần cập nhật. Biết chính
    xác thiếu cái nào, nên trả danh sách về cho họ đẩy lại. KHÔNG cần người.
  · **Mình có, bản kê không có** ⇒ nghi mất tích. Đánh dấu, KHÔNG tự xoá — hai
    khả năng (họ xoá thật / `delete` bị rơi) trông giống hệt nhau ở phía mình.

── «TỰ YÊU CẦU ĐẨY LẠI» LÀ CHÍNH CÂU TRẢ LỜI, KHÔNG PHẢI MỘT CALLBACK ──────
Bản kê do BÊN KHÁCH gửi lên, nên response của chính lượt đó là chỗ tự nhiên để
nói «những mã này bạn đẩy lại giúp». Dựng một webhook gọi ngược sang họ sẽ cần
một URL đăng ký, một cơ chế retry, và một cổng xác thực thứ hai — cho đúng một
danh sách chuỗi mà họ đang đứng chờ.

── BẢN KÊ PHẢI ĐẦY ĐỦ CHO KHOẢNG NÓ TỰ KHAI ────────────────────────────────
Đây là cái bẫy lớn nhất của cả cơ chế: một bản kê CẮT DỞ làm mọi bản ghi không
nằm trong đó bị đánh dấu nghi mất tích.

Phân trang (2026-08-15) giải nó bằng KHOẢNG, không bằng PHIÊN. Mỗi trang tự khai
mình phủ đoạn nào của không gian mã, và phép so chỉ chạm đúng đoạn đó:

    (afterExternalId, max(externalId trong trang)]      — trang giữa
    (afterExternalId, +∞)                               — trang cuối
    (-∞, …]                                             — trang đầu (không có after)

⚠️ VÌ SAO KHÔNG DÙNG PHIÊN (`/start` → `/page` → `/finish`): phiên cần trạng thái
giữa các request, cần hạn cho phiên bỏ dở, và cần một câu trả lời cho «phiên chết
giữa chừng thì dữ liệu đã gắn cờ đi đâu». Khoảng thì mỗi request TỰ ĐỦ: gửi lại
được, gửi lệch thứ tự được, và một trang không bao giờ tới chỉ khiến đoạn đó KHÔNG
ĐƯỢC KIỂM — hỏng về phía an toàn, chứ không phải gắn cờ sai.

⚠️ SO SÁNH BẰNG `COLLATE "C"` (thứ tự BYTE). Không có nó, ranh giới khoảng phụ
thuộc collation của DB còn bên khách thì sắp theo thứ tự của họ — hai thứ tự lệch
nhau nghĩa là có bản ghi rơi ngoài mọi trang (không kiểm, an toàn) HOẶC rơi vào
trang không chứa nó (gắn cờ sai, nguy hiểm). `COLLATE "C"` khớp đúng thứ tự mà
`sorted()` của Python và `ORDER BY` bytewise cho ra.

Trần `TRAN_BAN_KE` giờ là trần MỘT TRANG, không phải trần cả cuộc đối soát.
"""

from collections import Counter

import asyncpg

from portal.modules.ingest import contracts

TRAN_BAN_KE = 20_000
"""Số mục tối đa MỘT bản kê, cho MỘT thực thể.

Cao hơn hẳn `TRAN_LO` (500) vì đây là ảnh chụp toàn bộ chứ không phải một lô thay
đổi, và mỗi mục chỉ có hai trường. Chạm trần thì từ chối — xem docstring đầu tệp.
"""

_CACH_LY = "tenant_id = portal.current_tenant()"


def khoang(ma: list[str], tu_ma: str | None, la_trang_cuoi: bool) -> tuple[str | None, str | None] | None:
    """`(cận dưới HỞ, cận trên ĐÓNG)` mà trang này phủ. HÀM THUẦN.

    `None` bên trong tuple = vô cực. **`None` thay cho cả tuple = phủ KHÔNG GÌ.**

    Cận trên là `max(ma)` chứ không phải một giá trị khách khai: nếu để họ khai,
    một trang khai rộng hơn thứ nó chứa sẽ gắn cờ cho phần chênh — chế độ hỏng
    nguy hiểm nhất của cả cơ chế. Suy từ chính nội dung thì lời khai không thể
    rộng hơn bằng chứng.

    ⚠️ TRANG GIỮA RỖNG PHẢI TRẢ `None`, KHÔNG phải `(None, None)`. Bản đầu trả
    `(tu_ma, tu_ma)` — đúng khi `tu_ma` có giá trị, nhưng với trang ĐẦU (`tu_ma`
    là `None`) nó thành `(None, None)` tức `(-∞, +∞)`: một trang rỗng phủ TOÀN BỘ
    và gỡ sạch mọi cờ. Hai nghĩa hoàn toàn trái nhau nằm trong cùng một giá trị —
    nên «phủ không gì» phải có biểu diễn RIÊNG.
    """
    if la_trang_cuoi:
        return tu_ma, None
    if not ma:
        return None
    return tu_ma, max(ma)


_TRONG_KHOANG = """
           AND ($3::text IS NULL OR r.external_id COLLATE "C" >  $3 COLLATE "C")
           AND ($4::text IS NULL OR r.external_id COLLATE "C" <= $4 COLLATE "C")
"""


async def so_ban_ke(
    conn: asyncpg.Connection,
    *,
    entity: str,
    ma: list[str],
    moc: list,
    kh: tuple[str | None, str | None] | None = (None, None),
) -> tuple[list[str], list[str]]:
    """Trả `(mã lệch, mã nghi mất tích)`. Một lượt đi DB, không kéo bảng lên Python.

    `unnest` hai mảng song song thành một bảng tạm rồi JOIN — cách này giữ toàn bộ
    phép so ở Postgres. Kéo cả `ingest_records` về app rồi so bằng `set` sẽ tốn
    một vòng truyền cho mỗi lượt đối soát, mà đối soát chạy trên TOÀN BỘ dữ liệu.

    «Lệch» KHÔNG cần vị từ khoảng: nó đi từ bản kê ra, nên đã tự giới hạn trong
    những mã khách vừa gửi. Chỉ chiều NGƯỢC LẠI — «mình có mà kê không có» — mới
    phải hỏi «đoạn nào đã được phủ», vì nó quét bảng của mình.

    ⚠️ `kh` TRUYỀN VÀO, không tính tại chỗ. Nó phải là CÙNG một khoảng mà
    `dat_co_mat_tich` dùng, và cách duy nhất bảo đảm điều đó là tính một lần ở
    người gọi. Bản đầu để mỗi hàm tự tính từ tham số `ma` của chính nó — mà `ma`
    của hàm kia là danh sách MẤT TÍCH chứ không phải bản kê, nên hai khoảng lệch
    nhau và trang rỗng gỡ sạch cờ của trang trước.
    """
    if kh is None:
        return [], []
    tu, den = kh

    lech = await conn.fetch(
        """
        WITH ban_ke AS (
            SELECT * FROM unnest($2::text[], $3::timestamptz[]) AS t(external_id, updated_at)
        )
        SELECT bk.external_id
          FROM ban_ke bk
          LEFT JOIN tenant_data.ingest_records r
                 ON r.tenant_id = portal.current_tenant()
                AND r.entity = $1
                AND r.external_id = bk.external_id
         WHERE r.id IS NULL OR bk.updated_at > r.occurred_at
         ORDER BY 1
        """,
        entity,
        ma,
        moc,
    )
    mat_tich = await conn.fetch(
        f"""
        SELECT r.external_id
          FROM tenant_data.ingest_records r
         WHERE r.{_CACH_LY} AND r.entity = $1
           -- `op='delete'` KHÔNG tính là mất tích: mình đã biết nó đi rồi, và
           -- bản kê của khách đương nhiên không liệt kê thứ họ vừa xoá.
           AND r.op = 'upsert'
           AND NOT EXISTS (SELECT 1 FROM unnest($2::text[]) AS m(x) WHERE m.x = r.external_id)
        """
        + _TRONG_KHOANG
        + " ORDER BY 1",
        entity,
        ma,
        tu,
        den,
    )
    return [h["external_id"] for h in lech], [h["external_id"] for h in mat_tich]


async def dat_co_mat_tich(
    conn: asyncpg.Connection,
    entity: str,
    ma: list[str],
    *,
    kh: tuple[str | None, str | None] | None = (None, None),
) -> list[str]:
    """Gắn cờ, gỡ cờ, và trả về những mã VỪA MỚI bị nghi lần đầu.

    Trả «mới» chứ không trả cả danh sách: cảnh báo vận hành chỉ nên kêu khi có
    thứ MỚI. Một bản ghi nghi mất tích ba tuần liền mà đêm nào cũng sinh một dòng
    nhật ký là cách dạy người trực bỏ qua chính dòng đó.

    Hai câu chứ không một: gỡ cờ phải phủ CẢ hàng không nằm trong lần đối soát này
    (bản ghi xuất hiện lại ở bản kê sau), nên không gộp được vào một `UPDATE`
    theo danh sách.

    `coalesce(nghi_mat_tich_tu, now())` giữ nguyên mốc LẦN ĐẦU bị nghi — nó là câu
    trả lời cho «đã nghi bao lâu rồi», thứ quyết định có nên đi điều tra hay không.
    Đè `now()` mỗi đêm sẽ làm mọi hàng trông như vừa mới bị nghi.

    ⚠️ CÂU GỠ CỜ PHẢI MANG VỊ TỪ KHOẢNG. Không có nó, với bản kê phân trang thì
    trang 1 gỡ sạch cờ mà trang 2 vừa đặt — mỗi trang lần lượt xoá công của trang
    trước, và cuối cuộc chỉ còn cờ của trang cuối cùng. Đây là chỗ dễ sai nhất của
    cả bản phân trang, và nó hỏng ÂM THẦM: kết quả vẫn hợp lý, chỉ thiếu.

    `kh` là khoảng của BẢN KÊ, truyền từ người gọi — KHÔNG suy từ `ma`, vì `ma`
    ở đây là danh sách mất tích chứ không phải bản kê. Suy nhầm nguồn là đúng lỗi
    đã sập một lần: trang không có mã nào mất tích ra khoảng `(-∞, +∞)` và gỡ sạch
    cờ mọi trang trước.
    """
    if kh is None:
        return []
    tu, den = kh
    moi = await conn.fetch(
        f"""
        UPDATE tenant_data.ingest_records
           SET nghi_mat_tich_tu = coalesce(nghi_mat_tich_tu, now())
         WHERE {_CACH_LY} AND entity = $1 AND external_id = ANY($2::text[])
           AND nghi_mat_tich_tu IS NULL
        RETURNING external_id
        """,
        entity,
        ma,
    )
    await conn.execute(
        f"""
        UPDATE tenant_data.ingest_records
           SET nghi_mat_tich_tu = NULL
         WHERE {_CACH_LY} AND entity = $1
           AND nghi_mat_tich_tu IS NOT NULL
           AND NOT (external_id = ANY($2::text[]))
        """
        + _TRONG_KHOANG.replace("r.external_id", "external_id"),
        entity,
        ma,
        tu,
        den,
    )
    return [h["external_id"] for h in moi]


def kiem_ban_ke(ban_ke: contracts.BanKeIn) -> str | None:
    """Lý do từ chối, hoặc `None`. HÀM THUẦN.

    Trùng `externalId` trong một bản kê là dấu hiệu adapter bên khách nối hai
    nguồn mà không khử trùng — và nó làm phép so ra kết quả tuỳ theo mục nào
    thắng. Từ chối thẳng còn hơn trả một kết quả không tái lập được.
    """
    if len(ban_ke.records) > TRAN_BAN_KE:
        return (
            f"Bản kê {len(ban_ke.records)} mục, quá trần {TRAN_BAN_KE} của MỘT TRANG. "
            "Chia trang: sắp theo externalId (thứ tự byte), gửi từng trang kèm "
            "`afterExternalId` = mã cuối của trang trước, và `isLastPage: true` ở "
            "trang cuối. ĐỪNG gửi một nửa rồi thôi — đoạn không trang nào phủ sẽ "
            "không bao giờ được kiểm."
        )
    ma = [m.externalId for m in ban_ke.records]
    if len(ma) != len(set(ma)):
        dem = Counter(ma)
        trung = sorted(x for x, n in dem.items() if n > 1)[:5]
        return f"Bản kê có externalId trùng: {', '.join(trung)}"
    return None
