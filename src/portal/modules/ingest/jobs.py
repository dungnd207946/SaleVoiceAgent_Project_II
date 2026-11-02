"""Job đêm — bắt tenant IM LẶNG, tức adapter bên khách đã ngừng đối soát.

Xem docstring migration `0929` để biết vì sao cơ chế này cần tồn tại. Tóm tắt:
đối soát §7 do BÊN KHÁCH kích hoạt, nên job của họ chết là §7 tắt **im lặng**, và
phía mình không có gì để quan sát.

`worker/__main__.py` tự import tệp này (nó quét `modules/<m>/jobs.py`), nên thêm
handler không phải sửa file nào khác. Job được xếp hàng bởi
`fanout.xep_kiem_im_lang()` — cron trên máy chủ gọi
`python -m portal.cli.kiem_tenant_im_lang`.

── MỘT JOB MỖI TENANT, KHÔNG PHẢI MỘT JOB QUÉT TẤT CẢ ──────────────────────
`core/jobs.run_once` chạy MỌI handler trong `tenant_conn(tenant_id)`. Một job
«quét mọi tenant» vì thế sẽ chạy trong ngữ cảnh của đúng một tenant và RLS cắt
sạch phần còn lại — nó sẽ không lỗi, chỉ âm thầm kiểm thiếu. Khuôn ở `ingest/fanout.py`.
"""

from datetime import UTC, datetime, timedelta

import asyncpg

from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.core.jobs import JobResult, register
from portal.modules.ingest import repo

KIND_IM_LANG = "ingest_tenant_im_lang"
KIND_DON_LOI = "ingest_don_loi"

HANH_DONG = "ingest.tenant_im_lang"
"""Khoá nhật ký. Màn Nhật ký của portal đọc `control.audit_log`, nên đây là kênh
vận hành — không có kênh thứ hai, và giao diện quản trị workspace CỐ Ý không bày
kết quả đối soát (nó khoe cả lúc không có việc)."""


async def handle_im_lang(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Một tenant. Ghi nhật ký nếu đang im lặng VÀ chưa báo cho lần im lặng này.

    BA ĐIỀU KIỆN, thiếu cái nào cũng ra một kênh cảnh báo không ai đọc:

    1. **Tenant có dùng cổng nạp** (`ingest_records` không rỗng). Workspace chưa
       đấu nối mà bị nhắc mỗi đêm là cách nhanh nhất để người trực tắt kênh này.
    2. **Quá `ingest_im_lang_ngay`** kể từ bản kê gần nhất — hoặc CHƯA TỪNG gửi.
       Ca «chưa từng» phải tính là im lặng: một adapter chỉ đẩy `/events` mà không
       bao giờ đối soát thì đúng là thứ cơ chế này tồn tại để phát hiện.
    3. **Chưa có dòng nhật ký nào cho ĐỢT im lặng này.** Xem `_da_bao`.
    """
    _ = payload
    tran_ngay = int(get_settings().ingest_im_lang_ngay)
    tenant_id = await conn.fetchval("SELECT portal.current_tenant()")

    if not await repo.co_du_lieu_nap(conn):
        return JobResult(0, "tenant chưa dùng cổng nạp — bỏ qua")

    gan_nhat = await repo.ban_ke_gan_nhat(conn)
    han = datetime.now(UTC) - timedelta(days=tran_ngay)
    if gan_nhat is not None and gan_nhat > han:
        return JobResult(0, f"đối soát gần nhất {gan_nhat:%Y-%m-%d %H:%M} — bình thường")

    if await _da_bao(conn, gan_nhat):
        return JobResult(0, "đang im lặng nhưng đã báo rồi — không lặp lại")

    await nhat_ky.ghi(
        conn,
        tenant_id,
        HANH_DONG,
        "cron",
        {
            "banKeGanNhat": gan_nhat.isoformat() if gan_nhat else None,
            "soNgayImLang": None if gan_nhat is None else (datetime.now(UTC) - gan_nhat).days,
            "tranNgay": tran_ngay,
        },
    )
    return JobResult(1, "chưa từng đối soát" if gan_nhat is None else f"im lặng từ {gan_nhat:%Y-%m-%d}")


async def _da_bao(conn: asyncpg.Connection, gan_nhat: datetime | None) -> bool:
    """Đã có cảnh báo cho ĐỢT im lặng hiện tại chưa.

    Mốc so là chính `gan_nhat` — nghĩa là một dòng nhật ký ghi SAU bản kê cuối
    cùng thuộc về đợt im lặng đang diễn ra. Khách chạy lại đối soát rồi lại ngừng
    ⇒ `gan_nhat` nhích lên ⇒ dòng cũ rơi về trước mốc ⇒ đợt mới được báo lại.

    MỘT CẢNH BÁO MỖI ĐỢT, không phải mỗi đêm. Cùng lý lẽ đã dùng cho cờ nghi mất
    tích (`doi_soat.dat_co_mat_tich` chỉ trả về mã VỪA MỚI bị nghi): một dòng lặp
    lại 30 đêm liền là cách dạy người trực bỏ qua đúng dòng đó. Trạng thái «đang
    im lặng bao lâu rồi» đọc được từ bảng `ingest_manifest_runs` — nhật ký kể sự
    kiện, không phải nơi giữ trạng thái liên tục.

    `gan_nhat is None` (chưa từng đối soát) ⇒ so với `-infinity`, tức bất kỳ dòng
    nào đã có cũng tính là đã báo. Một tenant chưa từng đối soát vì thế được nhắc
    ĐÚNG MỘT LẦN.
    """
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM control.audit_log
                 WHERE tenant_id = portal.current_tenant()
                   AND hanh_dong = $1
                   AND luc > coalesce($2::timestamptz, '-infinity')
            )
            """,
            HANH_DONG,
            gan_nhat,
        )
    )


async def handle_don_loi(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Dọn `ingest_errors` của MỘT tenant. Xem `repo.don_loi` để biết hai vế cắt.

    VÌ SAO LÀ JOB CHỨ KHÔNG PHẢI MỘT `DELETE` TRONG CRON SQL: chạy qua
    `control.jobs` thì mỗi lượt dọn để lại một hàng có `state`/`count`/`message`,
    nên «đêm qua dọn được bao nhiêu» và «tenant nào dọn hỏng» là thứ ĐỌC ĐƯỢC —
    còn một câu SQL trong crontab thì không để lại gì, đúng lớp im lặng mà cả
    `jobs.py` này tồn tại để chống.

    KHÔNG ghi nhật ký: dọn theo chính sách là việc thường lệ, không phải sự kiện
    ai cần biết. Hàng `control.jobs` đã là dấu vết đủ.
    """
    _ = payload
    c = get_settings()
    so = await repo.don_loi(conn, giu_ngay=int(c.ingest_loi_giu_ngay), tran_hang=int(c.ingest_loi_tran_hang))
    return JobResult(so, f"xoá {so} dòng lỗi" if so else "không có gì để dọn")


register(KIND_IM_LANG, handle_im_lang)
register(KIND_DON_LOI, handle_don_loi)
