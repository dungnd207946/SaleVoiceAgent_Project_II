"""Meter của lượt hiện hành qua ContextVar + registry theo phiên.

Dùng ContextVar (đúng khuôn ``tenant/current.py``) để ``StreamingClient`` ghi
được usage mà KHÔNG phải đổi chữ ký ``stream_completion`` xuyên 5 tầng. Lợi ích
kèm theo: ``asyncio.create_task`` sao chép context, nên task summary/warm-cache
sinh ra trong lượt tự động ghi vào đúng meter.

Registry theo phiên tồn tại vì ``TurnRunner`` được cache theo
(tenant, version, channel) — nó phục vụ nhiều phiên, nên không thể giữ meter
làm thuộc tính instance.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar, Token

from noble_agent.billing.meter import UsageMeter

_meter: ContextVar[UsageMeter | None] = ContextVar("noble_usage_meter", default=None)

# Chặn trên: phiên không được dọn (transport crash) không được phép làm phình
# bộ nhớ vô hạn. Vượt trần thì bỏ phiên cũ nhất.
MAX_SESSIONS = 500
_sessions: OrderedDict[str, UsageMeter] = OrderedDict()

# High-water seq theo session_id: seq nhỏ nhất một meter MỚI của phiên đó được
# phép dùng. Cần vì meter bị pop lúc WS ngắt (đó là thứ chặn bộ nhớ) nhưng
# `?session=<sid>` cho phép RESUME đúng session_id đó — meter mới bắt lại từ
# seq 0 thì mọi dòng của chặng sau trùng khoá UNIQUE với chặng đầu và bị
# `ON CONFLICT DO NOTHING` bỏ đi, mất trắng cả chặng resume. LRU-evict một phiên
# còn sống trên worker đông cũng cùng một lỗi. Khoảng trống trong dãy seq là
# CHẤP NHẬN ĐƯỢC: contract chỉ đòi seq đơn điệu tăng trong phiên và bất biến khi
# retry, không đòi liên tục.
_seq_high_water: OrderedDict[str, int] = OrderedDict()


def set_meter(meter: UsageMeter | None) -> Token:
    return _meter.set(meter)


def reset_meter(token: Token) -> None:
    _meter.reset(token)


def current_meter() -> UsageMeter | None:
    return _meter.get()


@contextmanager
def use_meter(meter: UsageMeter | None):
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def _remember_seq(meter: UsageMeter) -> None:
    """Ghi lại high-water seq của một meter rời registry (pop hoặc LRU-evict)."""
    sid = meter.session_id
    prev = _seq_high_water.get(sid, 0)
    _seq_high_water[sid] = max(prev, meter.next_seq)
    _seq_high_water.move_to_end(sid)
    while len(_seq_high_water) > MAX_SESSIONS:
        _seq_high_water.popitem(last=False)


def get_session_meter(session_id: str, channel: str) -> UsageMeter:
    m = _sessions.get(session_id)
    if m is None:
        # Phiên resume (hoặc từng bị LRU-evict) tiếp tục từ high-water, không
        # bắt lại từ 0 — xem chú thích ở `_seq_high_water`.
        m = UsageMeter(session_id=session_id, channel=channel, start_seq=_seq_high_water.get(session_id, 0))
        _sessions[session_id] = m
        while len(_sessions) > MAX_SESSIONS:
            _sid, evicted = _sessions.popitem(last=False)
            _remember_seq(evicted)
    _sessions.move_to_end(session_id)
    return m


def peek_session_meter(session_id: str) -> UsageMeter | None:
    """Meter của phiên nếu ĐÃ có, không tạo mới.

    Dùng ở đường teardown: cần gắn meter quanh các lời gọi LLM cuối phiên
    (`summary` / `memory`) mà không được sinh meter cho một phiên chưa từng đo
    (billing tắt, hoặc phiên chưa có lượt nào).
    """
    return _sessions.get(session_id)


def pop_session_meter(session_id: str) -> UsageMeter | None:
    m = _sessions.pop(session_id, None)
    if m is not None:
        _remember_seq(m)
    return m
