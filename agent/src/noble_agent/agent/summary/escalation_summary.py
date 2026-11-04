"""Per-escalation need summary, written in the background.

Distinct from the two neighbours: `generator.py` summarises a whole call at
call end, `summarizer.py` compacts history mid-call. This one runs once per
`escalate` fire and answers a single question for the sale rep who will call
back: what does this customer want?
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.storage.pg_data_plane import save_escalation_summary

from .generator import _call_llm, _format_history

logger = logging.getLogger("noble_agent.summary.escalation")

# asyncio only holds weakrefs to tasks — an unreferenced task is GC'd mid-flight.
_bg_tasks: set[asyncio.Task] = set()

_MAX_TOKENS = 400

_PROMPT = """Tóm tắt NHU CẦU của khách trong hội thoại dưới đây, cho chuyên viên
tư vấn sắp gọi lại đọc.

Viết MỘT đoạn tiếng Việt dưới 80 từ, plain text, KHÔNG markdown, KHÔNG tiêu đề.
Chỉ nêu: khách muốn gì (dự án / ngân sách / số phòng / mục đích) và câu hỏi khách
chưa được trả lời.

KHÔNG viết những thứ sau — màn hình đã hiện sẵn hoặc chuyên viên không cần đọc:
- Lý do vì sao phải chuyển cho người thật, hay nhận xét về hệ thống/công cụ tự động
- Tên và số điện thoại khách (đã hiện ngay trên đầu ca)
- Lời dẫn kiểu "khách hàng liên hệ để hỏi về..." — vào thẳng nội dung

Chỉ dùng thông tin có trong hội thoại. KHÔNG suy đoán, KHÔNG bịa số liệu.

Bối cảnh chuyển (KHÔNG nhắc lại trong bài): {reason}

Thông tin khách: {customer}

Hội thoại:
{history}
"""


def build_prompt(*, history_snapshot: list[dict], customer: dict, reason: str) -> str:
    ho_so = ", ".join(f"{k}={v}" for k, v in (customer or {}).items() if v) or "(chưa có)"
    return _PROMPT.format(
        reason=reason or "(không nêu)",
        customer=ho_so,
        history=_format_history(history_snapshot or []),
    )


async def _run(escalation_id: int, prompt: str) -> None:
    try:
        text = await _call_llm(prompt, max_tokens=_MAX_TOKENS)
        if not (text or "").strip():
            return  # giữ nguyên chuỗi cơ học đã ghi lúc INSERT
        await save_escalation_summary(escalation_id, text.strip())
    except Exception:
        logger.warning("[ESCALATE] summary task failed id=%s", escalation_id, exc_info=True)


def spawn_escalation_summary(
    escalation_id: int | None,
    *,
    history_snapshot: list[dict],
    customer: dict,
    reason: str = "",
) -> asyncio.Task | None:
    """Fire the summary task and return it. `history_snapshot` must already be a
    copy — the runner mutates `state.history` in parallel."""
    if not escalation_id:
        return None
    prompt = build_prompt(history_snapshot=history_snapshot, customer=customer, reason=reason)
    task = asyncio.create_task(_run(escalation_id, prompt))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task
