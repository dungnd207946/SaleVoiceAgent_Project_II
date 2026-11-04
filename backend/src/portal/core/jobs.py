"""Hàng đợi job + sổ đăng ký handler.

CƠ CHẾ ĐỘC LẬP MODULE: mỗi module ship modules/<m>/jobs.py gọi register(),
worker tự gom. Thêm một loại job KHÔNG sửa file nào của M1.

    # portal/modules/<m>/jobs.py
    from portal.core.jobs import JobResult, register

    async def handle_import(conn, payload):
        ...
        return JobResult(count=n, message=f"nhập {n} hàng")

    register("import", handle_import)

Handler nhận connection đã ở TRONG một giao dịch (`tx()`): handler ném lỗi thì mọi
thứ nó ghi được rollback, job chuyển `failed`.
"""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

import asyncpg

from portal.core.db.session import tx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobResult:
    """Kết quả một job. count/message ghi vào hàng jobs để UI hiện."""

    count: int = 0
    message: str = ""


JobHandler = Callable[[asyncpg.Connection, dict], Awaitable[JobResult]]

_HANDLERS: dict[str, JobHandler] = {}

# Số lượt THỬ LẠI theo loại việc (0 = không retry, mặc định). Docstring của `run_once` đã
# khai từ đầu: "retry là quyết định của từng loại job" — đây là chỗ khai nó.
#
# MẶC ĐỊNH PHẢI LÀ 0: loại việc ngoài phạm vi KB (xuất bản cấu hình agent) chạy đúng một
# lượt từ trước tới giờ, và bật retry cho nó là đổi hành vi của một đường không ai yêu cầu.
_RETRIES: dict[str, int] = {}

# Trần đồng thời theo loại việc. Module sở hữu kind khai trần của nó ở register();
# core chỉ cưỡng chế. Mặc định 1 = hành vi cũ.
_CONCURRENCY: dict[str, int] = {}

# Ngưỡng coi là KẸT theo loại việc (phút). Mặc định `_KET_PHUT`; loại việc chạy dài (crawl
# web gọi LLM/Gemini hàng chục phút) khai ngưỡng lớn hơn, không thì thu hồi giật việc khỏi
# một worker đang làm và hai worker cùng chạy một việc.
_STUCK_MINUTES: dict[str, int] = {}

_INFLIGHT: Counter[str] = Counter()


# Claim và tăng bộ đếm phải nằm trong CÙNG một khoá: tính headroom rồi mới claim thì
# hai làn cùng thấy chỗ trống của một kind và cùng nhặt, trần bị vượt.
@dataclass(frozen=True)
class JobRef:
    id: int
    attempt: int
    """Số lượt đã thử trước lượt này (`shop.jobs.attempts` lúc nhận việc)."""
    pool: asyncpg.Pool
    """Pool đang chạy job — để ghi việc phải sống sót khi giao dịch của handler rollback."""


_CURRENT_JOB: ContextVar[JobRef | None] = ContextVar("current_job", default=None)


def current_job() -> JobRef | None:
    """Job đang chạy trong task hiện tại; None ngoài handler."""
    return _CURRENT_JOB.get()


_CLAIM_LOCK = asyncio.Lock()

# Chờ bao lâu trước lượt thử lại thứ n: 30s, rồi 60s, rồi 120s… Đủ để một tunnel embed đổi
# URL hoặc một service khởi động lại xong, chưa đủ để người dùng bỏ đi.
_CHO_GOC_GIAY = 30

# Số lượt chờ một kind lạ trước khi bỏ cuộc. Backoff 30/60/120/240/480s ≈ 16 phút — dài hơn
# khoảng giữa `migrate` và `up -d` của một lần deploy, ngắn hơn một kind gõ sai nằm mãi.
LUOT_CHO_HANDLER = 5

# Việc `running` lâu hơn ngưỡng này coi là KẸT và được thu hồi. Bằng ngưỡng của khung nhìn
# `shop.jobs_stuck` (migration cũ) — khung nhìn đó đã liệt kê việc treo từ lâu nhưng
# KHÔNG CÓ GÌ ĐỌC NÓ, nên việc kẹt nằm `running` vĩnh viễn.
#
# Vì sao phải thu hồi, không chỉ để đó: chỉ báo của tab kiến thức suy "đang nạp" từ đúng
# những hàng `queued|running`, nên một việc kẹt làm dấu quay xoay MÃI và người dùng không có
# nút nào bấm (nút Thử lại chỉ hiện ở nhánh lỗi).
_KET_PHUT = 15

# Nhịp tim của việc đang chạy (`shop.jobs.heartbeat_at`): ghi mỗi `NHIP_TIM_GIAY`.
# Mất nhịp quá `MAT_NHIP_PHUT` là worker giữ việc đã chết (deploy giết container, OOM) — thu hồi ngay, không
# chờ ngưỡng kẹt của loại việc (tới 6 giờ với `kbweb_run`).
NHIP_TIM_GIAY = 30
MAT_NHIP_PHUT = 5

# CÂU NHẶT JOB — HẰNG SỐ CẤP MODULE, CỐ Ý.
#
# `FOR UPDATE SKIP LOCKED` là thứ làm chạy nhiều worker song song thành an toàn mà
# không tắc: worker khác đang giữ job nào thì BỎ QUA job đó, không đợi. Thiếu nó,
# claimant thứ hai chặn ở khoá cho tới khi txn thứ nhất xong — nhiều worker biến
# thành một hàng đợi tuần tự, và một handler chậm giữ khoá là mọi worker khác đứng im.
#
# VÌ SAO PHẢI LÀ HẰNG SỐ CHỨ KHÔNG PHẢI SQL INLINE TRONG run_once():
# test canh SKIP LOCKED trước đây tự khai lại câu SQL thành một string literal trong
# chính file test. Nghĩa là nó chứng minh "Postgres có SKIP LOCKED", KHÔNG chứng minh
# "production dùng SKIP LOCKED" — xoá SKIP LOCKED khỏi jobs.py mà cả bộ test vẫn xanh.
# Một guard mà không ai từng thấy nó đỏ thì chưa phải guard. Đưa câu SQL ra đây để
# test import và chạy ĐÚNG câu mà run_once() chạy, không phải một bản sao của nó.
_CAU_NHAT_JOB = """SELECT id, kind, payload, attempts FROM shop.jobs
                    WHERE state = 'queued' AND run_after <= now() ORDER BY id
                      FOR UPDATE SKIP LOCKED LIMIT 1"""

# Thiếu vế lọc kind, một hàng đợi đầy caption ở đầu chặn làn index dù làn đó đang rỗng:
# `ORDER BY id LIMIT 1` chỉ trả cái cũ nhất, không quan tâm làn nào còn chỗ.
_CLAIM_BY_KIND_SQL = """SELECT id, kind, payload, attempts FROM shop.jobs
                    WHERE state = 'queued' AND run_after <= now() AND kind = ANY($1)
                    ORDER BY id
                      FOR UPDATE SKIP LOCKED LIMIT 1"""

# THU HỒI VIỆC KẸT — chạy trước mỗi lần nhặt, một câu, không khoá gì lâu.
#
# `state='running'` được ghi trong một giao dịch RIÊNG trước khi handler chạy (xem
# `run_once`), nên một tiến trình bị giết giữa việc để lại hàng `running` mà không ai dọn.
# Đưa về `queued` nếu còn lượt, `failed` nếu hết — KHÔNG để `running` mãi.
#
# Hai điều kiện: treo quá ngưỡng kẹt của loại việc (worker còn sống nhưng handler không xong), hoặc mất
# nhịp tim (worker đã chết). `heartbeat_at` NULL = nhận bởi bản cũ, chỉ theo ngưỡng kẹt.
#
# `attempts + 1`: lượt vừa chết vẫn tính là một lượt đã dùng, không thì một việc treo đi
# treo lại — hay một việc tự làm worker chết — sẽ được thu hồi vô hạn.
_CAU_THU_HOI = """UPDATE shop.jobs SET
       state      = CASE WHEN attempts + 1 <= $1 THEN 'queued' ELSE 'failed' END,
       attempts   = attempts + 1,
       run_after  = now(),
       finished_at = CASE WHEN attempts + 1 <= $1 THEN NULL ELSE now() END,
       heartbeat_at = NULL,
       message    = CASE WHEN heartbeat_at < now() - make_interval(mins => $4::int)
                         THEN 'thu hồi: worker mất nhịp tim quá ' || $4::int || ' phút'
                         ELSE 'thu hồi: việc treo quá ' || $3::int || ' phút ở trạng thái running' END
     WHERE state = 'running' AND kind = $2
       AND (started_at < now() - make_interval(mins => $3::int)
            OR heartbeat_at < now() - make_interval(mins => $4::int))
   RETURNING id"""

# Trả việc khi worker dừng (deploy gửi SIGTERM): không tăng `attempts` vì việc không hỏng, chỉ bị cắt. Chỉ hàng
# còn `running` — việc vừa kịp ghi xong thì giữ nguyên kết quả.
_CAU_TRA_LAI = """UPDATE shop.jobs SET
       state = 'queued', started_at = NULL, heartbeat_at = NULL, run_after = now(),
       message = 'trả lại hàng đợi: worker dừng khi việc đang chạy'
     WHERE id = ANY($1::bigint[]) AND state = 'running'
   RETURNING id"""

# Việc tiến trình này đang giữ (tập id). Việc bị huỷ giữa chừng ở lại đây để `tra_lai_viec_dang_giu` trả nó.
_DANG_GIU: set[int] = set()


def register(
    kind: str,
    handler: JobHandler,
    *,
    retries: int = 0,
    max_concurrency: int = 1,
    stuck_minutes: int = _KET_PHUT,
) -> None:
    """`retries` = số lượt THỬ LẠI (không tính lượt đầu). `max_concurrency` = trần đồng thời.
    `stuck_minutes` = `running` quá bấy nhiêu phút thì thu hồi — phải dài hơn lượt chạy thật lâu nhất."""
    if not kind:
        raise ValueError("kind rỗng")
    if retries < 0:
        raise ValueError(f"retries âm cho kind={kind!r}")
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency phải ≥ 1 cho kind={kind!r}")
    if stuck_minutes < 1:
        raise ValueError(f"stuck_minutes phải ≥ 1 cho kind={kind!r}")
    _HANDLERS[kind] = handler
    _RETRIES[kind] = retries
    _CONCURRENCY[kind] = max_concurrency
    _STUCK_MINUTES[kind] = stuck_minutes


def retries_of(kind: str) -> int:
    return _RETRIES.get(kind, 0)


def concurrency_of(kind: str) -> int:
    return _CONCURRENCY.get(kind, 1)


def stuck_minutes_of(kind: str) -> int:
    return _STUCK_MINUTES.get(kind, _KET_PHUT)


def kinds_with_headroom() -> list[str]:
    return [k for k in _HANDLERS if _INFLIGHT[k] < concurrency_of(k)]


def get_handler(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


async def enqueue(conn: asyncpg.Connection, *, kind: str, actor: str, payload: dict, cho_giay: float = 0) -> int | None:
    """Xếp một job. Gọi trong CÙNG giao dịch với thay đổi dữ liệu sinh ra nó: giao dịch
    rollback thì job cũng không tồn tại — không có job trỏ vào hàng chưa từng được ghi.

    Đã có việc y hệt (`kind` + `payload`) đang chờ ⇒ không xếp thêm, trả None
    (`shop.enqueue_once`, cùng hàm trigger KB dùng). `cho_giay` > 0: việc chỉ được nhặt sau chừng ấy giây.
    """
    return await conn.fetchval(
        "SELECT shop.enqueue_once($1, $2, $3::jsonb, $4)",
        kind,
        actor,
        json.dumps(payload),
        float(max(0.0, cho_giay)),
    )


async def thu_hoi_viec_ket(pool: asyncpg.Pool) -> list[int]:
    """Đưa việc `running` quá hạn về `queued` (còn lượt) hoặc `failed` (hết lượt).

    Chạy theo TỪNG `kind` vì trần retry khai theo kind. Chỉ quét những kind đã đăng ký —
    một kind lạ trong bảng (di sản, hoặc một module chưa nạp) không được đụng tới.
    """
    ra: list[int] = []
    async with pool.acquire() as conn:
        for kind in list(_HANDLERS):
            phut = stuck_minutes_of(kind)
            rows = await conn.fetch(_CAU_THU_HOI, retries_of(kind), kind, phut, MAT_NHIP_PHUT)
            for r in rows:
                ra.append(int(r["id"]))
                log.warning("thu hồi job %s (%s): treo quá %d phút hoặc mất nhịp tim", r["id"], kind, phut)
    return ra


async def tra_lai_viec_dang_giu(pool: asyncpg.Pool) -> list[int]:
    """Đưa việc tiến trình này đang giữ về `queued` để worker mới nhặt ngay. Gọi khi worker dừng."""
    ids = list(_DANG_GIU)
    _DANG_GIU.clear()
    if not ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(_CAU_TRA_LAI, ids)
    return [int(r["id"]) for r in rows]


async def run_once(pool: asyncpg.Pool, *, kinds: list[str] | None = None) -> int | None:
    """Nhặt và chạy MỘT job. Trả id job đã chạy, hoặc None nếu không có gì để nhặt.

    `kinds` giới hạn tập loại việc được nhặt — mỗi làn của worker truyền vào tập kind
    còn chỗ trống. None = mọi kind, hành vi cũ.

    FOR UPDATE SKIP LOCKED: worker khác đang giữ job nào thì bỏ qua job đó, KHÔNG
    đợi. Nhờ vậy chạy nhiều worker (và nhiều làn trong một worker) song song mà không
    nhặt trùng và không tắc.

    Job failed KHÔNG được nhặt lại. Retry là quyết định của từng loại job, mặc
    định không có — retry vô hạn một job hỏng là cách chắc chắn nhất để lấp đầy
    log mà không ai đọc.
    """
    async with _CLAIM_LOCK:
        async with pool.acquire() as claim_conn, claim_conn.transaction():
            if kinds is None:
                row = await claim_conn.fetchrow(_CAU_NHAT_JOB)
            else:
                row = await claim_conn.fetchrow(_CLAIM_BY_KIND_SQL, kinds)
            if row is None:
                return None
            await claim_conn.execute(
                "UPDATE shop.jobs SET state = 'running', started_at = now(), heartbeat_at = now() WHERE id = $1",
                row["id"],
            )
        _INFLIGHT[str(row["kind"])] += 1
        job_id = int(row["id"])
        _DANG_GIU.add(job_id)

    nhip = asyncio.create_task(_giu_nhip(pool, job_id))
    bi_huy = False
    try:
        return await _run_claimed_job(pool, row)
    except asyncio.CancelledError:
        bi_huy = True
        raise
    finally:
        nhip.cancel()
        _INFLIGHT[str(row["kind"])] -= 1
        if not bi_huy:
            _DANG_GIU.discard(job_id)


async def _giu_nhip(pool: asyncpg.Pool, job_id: int) -> None:
    while True:
        await asyncio.sleep(NHIP_TIM_GIAY)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE shop.jobs SET heartbeat_at = now() WHERE id = $1 AND state = 'running'", job_id
                )
        except Exception:  # noqa: BLE001 — lỡ một nhịp không được giết việc đang chạy
            log.warning("ghi nhịp tim job %s hỏng", job_id, exc_info=True)


async def _run_claimed_job(pool: asyncpg.Pool, row: asyncpg.Record) -> int:
    job_id, kind = row["id"], row["kind"]
    payload = json.loads(row["payload"])
    handler = get_handler(kind)

    if handler is None:
        # Kind lạ = "bản đang chạy chưa biết", KHÔNG phải "việc sai". Deploy chạy `migrate`
        # trước `up -d`, nên migration xếp việc cho handler chỉ có ở image mới trong khi
        # worker cũ còn sống — giết ngay là mất việc (37 job kb_thumb, dev 2026-08-17).
        da_thu = int(row["attempts"])
        if da_thu < LUOT_CHO_HANDLER:
            await _xep_lai(pool, job_id, da_thu + 1, f"chưa có handler cho kind={kind!r} — chờ bản mới")
        else:
            await _finish(pool, job_id, "failed", 0, f"không có handler cho kind={kind!r}")
        return job_id

    token = _CURRENT_JOB.set(JobRef(id=int(job_id), attempt=int(row["attempts"]), pool=pool))
    try:
        async with tx(pool) as conn:
            result = await handler(conn, payload)
    except Exception as exc:  # noqa: BLE001 — mọi lỗi handler thành job failed, có thông điệp thật
        da_thu = int(row["attempts"])
        con_luot = da_thu < retries_of(kind)
        log.exception("job %s (%s) hỏng ở lượt %d/%d", job_id, kind, da_thu + 1, retries_of(kind) + 1)
        if con_luot:
            await _xep_lai(pool, job_id, da_thu + 1, f"{type(exc).__name__}: {exc}")
        else:
            await _finish(pool, job_id, "failed", 0, f"{type(exc).__name__}: {exc}")
        return job_id
    finally:
        _CURRENT_JOB.reset(token)

    await _finish(pool, job_id, "success", result.count, result.message)
    return job_id


async def _xep_lai(pool: asyncpg.Pool, job_id: int, attempts: int, message: str) -> None:
    """Về `queued` với `run_after` lùi theo cấp số nhân. Giữ nguyên `id` nên nó vẫn đứng
    trước các việc mới theo `ORDER BY id` khi tới lúc chạy — cố ý, việc cũ ưu tiên hơn."""
    cho = _CHO_GOC_GIAY * (2 ** (attempts - 1))
    async with tx(pool) as conn:
        await conn.execute(
            """UPDATE shop.jobs
                  SET state = 'queued', attempts = $2, run_after = now() + make_interval(secs => $3),
                      started_at = NULL, message = $4
                WHERE id = $1""",
            job_id,
            attempts,
            float(cho),
            message[:2000],
        )
    log.info("job %s xếp lại, thử lượt %d sau %ds", job_id, attempts + 1, cho)


async def _finish(pool: asyncpg.Pool, job_id: int, state: str, count: int, message: str) -> None:
    async with tx(pool) as conn:
        await conn.execute(
            """UPDATE shop.jobs
                  SET state = $2, finished_at = now(), count = $3, message = $4
                WHERE id = $1""",
            job_id,
            state,
            count,
            message[:2000],
        )
