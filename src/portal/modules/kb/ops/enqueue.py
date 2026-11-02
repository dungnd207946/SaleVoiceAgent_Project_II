"""Một chỗ DUY NHẤT để `modules/realestate` đặt việc nạp/đổi cờ/đổi nhãn.

Mười route ghi đều cần cùng một phép GỘP, và mười bản sao của phép đó là mười chỗ để lệch
nhau. Ở `ops/` chứ không ở `router.py` vì nó là luật của module kb, không phải của HTTP.

MỌI hàm ở đây gọi TRONG `tenant_conn` đang mở của route, tức CÙNG GIAO DỊCH với lệnh Lưu.
Đó là cả lý do không cần cột cờ *dirty* và không cần sweeper quét định kỳ: "lưu xong mà việc
không được đặt" là điều không thể xảy ra, và ngược lại.
"""

import logging

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.contracts import (
    KIND_DOI_CO,
    KIND_DOI_NHAN,
    KIND_INDEX,
    KIND_PROVISION,
    KIND_THUMB,
    MODE_DELTA,
)

log = logging.getLogger("kb.enqueue")

_CAU_DA_CHO = """SELECT 1 FROM control.jobs
                  WHERE tenant_id = portal.current_tenant()
                    AND kind = $1 AND state = 'queued'
                    AND payload->>'entity' = $2
                    AND (payload->>'record_id')::bigint = $3
                  LIMIT 1"""

_REDIRECT_TO_ANCHOR = {"zones", "buildings"}

_ANCHOR_ID_SQL = """SELECT id FROM tenant_data.projects
                     WHERE tenant_id = portal.current_tenant() AND project_code = $1"""


async def dat_viec_provision(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    vertical: str = "real_estate",
) -> int:
    """Dựng 2 collection Qdrant cho một workspace VỪA tạo.

    Gọi TRONG giao dịch tạo workspace: hàng job sống chết cùng `control.tenants`, nên
    workspace rollback thì việc dựng biến mất theo — không để lại collection mồ côi
    mang tên một tenant không tồn tại.

    KHÔNG gộp việc như `dat_viec_nap`: một workspace chỉ đi qua đây đúng một lần trong
    đời, nên không có gì để đụng, và một câu SELECT dò trùng ở đây là phí.
    """
    return await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=KIND_PROVISION,
        actor=actor,
        payload={"vertical": vertical},
    )


async def dat_viec_nap(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    entity: str,
    record_id: int,
    project_code: str,
    vertical: str = "real_estate",
) -> int | None:
    """Đặt việc nạp cho MỘT record. Trả id việc, hoặc `None` nếu đã gộp vào việc đang chờ."""
    if entity in _REDIRECT_TO_ANCHOR:
        anchor_id = await conn.fetchval(_ANCHOR_ID_SQL, project_code)
        if anchor_id is None:
            log.warning("bỏ qua: %s#%s không có dự án %r", entity, record_id, project_code)
            return None
        entity, record_id = "projects", int(anchor_id)
    if await conn.fetchval(_CAU_DA_CHO, KIND_INDEX, entity, record_id):
        log.info("gộp: %s#%s đã có việc nạp đang chờ", entity, record_id)
        return None
    return await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=KIND_INDEX,
        actor=actor,
        payload={
            "vertical": vertical,
            "entity": entity,
            "record_id": record_id,
            "project_code": project_code,
            "mode": MODE_DELTA,
            "op": "upsert",
        },
    )


async def dat_viec_thumb(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    entity: str,
    record_id: int,
    project_code: str,
    ghi_de: bool = False,
    tu_duyet: bool = False,
) -> int | None:
    """Đặt việc sinh ảnh thu nhỏ. Việc đó TỰ đặt việc nạp khi xong.

    Nối chuỗi thay vì đặt cả hai từ đây: hàng đợi cho phép chạy nhiều worker (nó bỏ qua việc
    worker khác đang giữ), nên đặt song song rồi trông vào thứ tự id là việc nạp có thể chạy
    TRƯỚC và point mang khoá thumb rỗng — mà không có gì kích hoạt nạp lại.
    """
    if not ghi_de and await conn.fetchval(_CAU_DA_CHO, KIND_THUMB, entity, record_id):
        log.info("gộp: %s#%s đã có việc thumb đang chờ", entity, record_id)
        return None
    return await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=KIND_THUMB,
        actor=actor,
        payload={
            "vertical": "real_estate",
            "entity": entity,
            "record_id": record_id,
            "project_code": project_code,
            "ghi_de": ghi_de,
            "tu_duyet": tu_duyet,
        },
    )


async def dat_viec_doi_co(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    project_code: str,
) -> int:
    """Đổi trạng thái hiển thị của MỌI point thuộc một dự án — KHÔNG nhúng lại gì.

    Đây là chỗ chữa cái bẫy lớn nhất của việc cho hàng nháp có point: chuyển dự án từ nháp
    sang đã đăng không đổi một chữ nội dung nào, nên dấu tay giống, nên bước so dấu tay thoát
    sớm và payload giữ nguyên cờ cũ — **công bố rồi mà agent vẫn không thấy**, và mọi thứ báo
    thành công. Việc này cập nhật payload trực tiếp nên nó tức thì, kể cả dự án 116 record.
    """
    return await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=KIND_DOI_CO,
        actor=actor,
        payload={"vertical": "real_estate", "project_code": project_code},
    )


async def dat_viec_doi_nhan(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    actor: str,
    project_code: str,
    ten_cu: str = "",
) -> int:
    """Đổi TÊN dự án trong payload của mọi point thuộc dự án — KHÔNG nhúng lại gì.

    Dấu tay nội dung băm trên nội dung THUẦN (không gồm nhãn), nên đổi tên dự án không đổi
    dấu tay. Trước 2026-08-14 tên nằm trong chuỗi được băm, nên đổi tên làm nhúng lại cả cây
    con trong khi nội dung không đổi một chữ.
    """
    return await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=KIND_DOI_NHAN,
        actor=actor,
        payload={"vertical": "real_estate", "project_code": project_code, "ten_cu": ten_cu},
    )
