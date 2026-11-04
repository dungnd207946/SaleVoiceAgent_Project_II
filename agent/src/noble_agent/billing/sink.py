"""Ghi lô usage xuống billing.usage_events — chạy NGOÀI đường nóng.

Bảng do Portal sở hữu; agent chỉ ghi thêm (KHÔNG UPDATE/DELETE/TRUNCATE). Vì
vậy toàn bộ tính idempotent nằm ở ``ON CONFLICT ON CONSTRAINT usage_events_idem
DO NOTHING``: lô thất bại được meter giữ nguyên và gửi lại với ĐÚNG seq cũ, nên
nếu lần trước thực ra đã landed thì lần này không nhân dòng.

Đừng bỏ ``ON CONSTRAINT`` khỏi câu trên. Postgres đòi quyền ``SELECT`` khi
``ON CONFLICT`` nêu arbiter tường minh, nên có lúc sẽ thấy ``42501 permission
denied`` và bị dụ "sửa" thành ``ON CONFLICT DO NOTHING`` trần cho hết lỗi. Dạng
trần bỏ qua xung đột trên MỌI ràng buộc unique ⇒ nếu ``usage_events_idem`` bị
xoá/đổi tên thì retry âm thầm NHÂN ĐÔI HOÁ ĐƠN. Cách đúng là cấp ``SELECT``
(đã cấp cho ``agent_all``, và RLS giới hạn nó trong tenant hiện tại).

Hợp đồng bảng + GRANT: docs/handoff/agent-postgres-billing-write-contract.md.
"""

from __future__ import annotations

import json
import logging

from noble_agent.billing.meter import UsageMeter, UsageRow

logger = logging.getLogger("noble_agent.billing.sink")

# `occurred_at` được gửi TƯỜNG MINH (không để DB default now()): contract §8 hứa
# "dòng đến muộn, occurred_at vẫn đúng thời điểm phát sinh". PG chết lúc 23:58
# ngày cuối tháng, lô commit 00:03 → rollup usage_by_tenant_month của Portal gộp
# theo occurred_at nên phiên đó bị tính sang kỳ sau và đối soát lệch.
INSERT_SQL = (
    "INSERT INTO billing.usage_events "
    "(tenant_id, session_id, channel, seq, turn_idx, component, purpose, provider, model, "
    " input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, "
    " audio_sec, wall_ms, units, text_units, exact, occurred_at) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) "
    "ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING"
)

# Đã log lỗi cho phiên nào rồi — chỉ ồn ào lần đầu mỗi phiên.
_logged: set[str] = set()


def _tenant_id() -> str:
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


async def _pool_for_tenant(tenant_id: str):
    from noble_agent.storage.postgres_client import pool_for_tenant

    return await pool_for_tenant(tenant_id)


def _tenant_conn(pool, tenant_id: str):
    from noble_agent.storage.postgres_client import tenant_conn

    return tenant_conn(pool, tenant_id)


def _params(tenant_id: str, meter: UsageMeter, seq: int, row: UsageRow) -> tuple:
    return (
        tenant_id,
        meter.session_id,
        meter.channel,
        seq,
        row.turn_idx,
        row.component,
        row.purpose,
        row.provider,
        row.model,
        int(row.input_tokens),
        int(row.output_tokens),
        int(row.cache_write_tokens),
        int(row.cache_read_tokens),
        float(row.audio_sec),
        float(row.wall_ms),
        int(row.units),
        int(row.text_units),
        bool(row.exact),
        row.occurred_at,
    )


async def flush(
    meter: UsageMeter,
    *,
    tenant_id: str | None = None,
    final: bool = False,
    turn_idx: int | None = None,
) -> bool:
    """Rút meter và ghi một lô. True khi đã ghi (meter đã commit).

    Không bao giờ raise: mọi lỗi được nuốt và log, lô ở lại meter chờ lượt sau.

    ``final=True`` = lần rút CUỐI của phiên (đóng phiên): không còn lượt sau để
    thử lại, nên thất bại ở đây là mất vĩnh viễn → dump nguyên lô ra log mức
    ``error`` dạng JSON (spec §6) để còn cứu lại được bằng tay.

    ``turn_idx`` — dấu lượt cho dòng audio, chuyển thẳng xuống ``meter.drain``.
    BẮT BUỘC truyền khi flush được lên lịch bằng ``fire_and_forget``: lúc đó
    ``meter.turn_idx`` đã bị tăng trước khi coroutine này chạy, và dòng audio sẽ
    lệch một lượt so với dòng ``llm``.
    """
    batch = None
    try:
        batch = meter.drain(turn_idx=turn_idx)
        if batch is None:
            return False
        seq, rows = batch
        tid = tenant_id or _tenant_id()
        pool = await _pool_for_tenant(tid)
        if pool is None:
            _log_failure(meter, "pool_for_tenant trả None", batch=batch, final=final)
            return False
        args = [_params(tid, meter, seq, r) for r in rows]
        async with _tenant_conn(pool, tid) as conn:
            await conn.executemany(INSERT_SQL, args)
        meter.commit(seq)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort, không được nổ ra hot path
        _log_failure(meter, repr(exc), batch=batch, final=final)
        return False


def _log_failure(
    meter: UsageMeter,
    detail: str,
    *,
    batch: tuple[int, list[UsageRow]] | None = None,
    final: bool = False,
) -> None:
    """Log lỗi: một lần mỗi phiên, CỘNG một dump payload ở lần rút cuối."""
    _log_once(meter, detail)
    if final:
        _dump_lost_batch(meter, detail, batch)


def _log_once(meter: UsageMeter, detail: str) -> None:
    """Log ở mức error đúng MỘT lần mỗi phiên.

    Ba nguyên nhân nhìn giống hệt nhau và cần phân biệt được từ log:
    chưa cấp INSERT (SQLSTATE 42501), credential hết hạn (28P01), PG không tới
    được. Vì vậy log kèm nguyên repr của exception.
    """
    if meter.session_id in _logged:
        return
    _logged.add(meter.session_id)
    logger.error(
        "billing: ghi usage thất bại (session=%s, tenant=%s): %s — lô giữ lại, thử lại lượt sau",
        meter.session_id,
        _safe_tenant(),
        detail,
    )


def _dump_lost_batch(meter: UsageMeter, detail: str, batch: tuple[int, list[UsageRow]] | None) -> None:
    """Dump lô của lần rút CUỐI ra log JSON — đường cứu duy nhất còn lại.

    ``_log_once`` chỉ ồn ào lần đầu mỗi phiên, nên PG chết suốt một cuộc gọi 12
    phút sẽ log ở lần flush giữa cuộc rồi IM LẶNG ở lần cuối — đúng lần mang
    dòng ``call`` (toàn bộ thời lượng cuộc gọi) cộng mọi lượt chưa commit. Mất
    vừa không cứu được vừa không thấy được.
    """
    if batch is None:
        logger.error(
            "billing: flush CUỐI thất bại (session=%s, tenant=%s): %s — không rút được lô để dump",
            meter.session_id,
            _safe_tenant(),
            detail,
        )
        return
    seq, rows = batch
    try:
        payload = json.dumps(
            {
                "session_id": meter.session_id,
                "channel": meter.channel,
                "tenant": _safe_tenant(),
                "seq": seq,
                "rows": [_row_json(r) for r in rows],
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:  # noqa: BLE001 — dump không được tự làm hỏng teardown
        payload = f"<không serialize được: {exc!r}>"
    logger.error(
        "billing: flush CUỐI thất bại (session=%s): %s — MẤT VĨNH VIỄN, payload: %s",
        meter.session_id,
        detail,
        payload,
    )


def _row_json(row: UsageRow) -> dict:
    d = dict(vars(row))
    occurred = d.get("occurred_at")
    if hasattr(occurred, "isoformat"):
        d["occurred_at"] = occurred.isoformat()
    return d


def _safe_tenant() -> str:
    try:
        return _tenant_id()
    except Exception:  # noqa: BLE001
        return "?"


def forget_session(session_id: str) -> None:
    """Quên trạng thái log của một phiên đã đóng (tránh set phình vô hạn)."""
    _logged.discard(session_id)
