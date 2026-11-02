"""Async summary helper for the unified single-thread agent.

Runs in a background task at the end of a user turn when history exceeds K.
Only summarizes the overflow head; the trailing keep_tail messages stay
verbatim in history so the next LLM call sees fresh recent context.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from noble_agent.storage.models import ThreadMessage, ThreadSummary

logger = logging.getLogger("noble_agent.summary")

_SUMMARY_PROMPT = """\
Bạn là helper tóm tắt cuộc gọi tư vấn bất động sản. Đầu vào là:
- (tuỳ chọn) tóm tắt phiên trước.
- Danh sách các tin nhắn user/assistant/tool cần được nén lại.

Yêu cầu: tiếng Việt, plain text, KHÔNG markdown, dưới 220 từ, ĐÚNG 4 mục theo thứ tự,
mỗi mục MỘT dòng bắt đầu bằng nhãn:
KHÁCH: tên + xưng hô, SĐT nếu có, ngân sách, dự án quan tâm, khu vực, số phòng ngủ,
  mục đích, bối cảnh (nơi làm, gia đình, thời điểm).
ĐÃ TRA: tool đã gọi và kết quả chính — GIỮ NGUYÊN mã căn, tên dự án, con số (giá,
  diện tích, hướng), tên tài liệu / ảnh đã gửi.
ĐÃ CHỐT: lịch hẹn (mã, ngày, giờ, dự án), đã chuyển chuyên viên (bộ phận), quyết định
  khách đã nói rõ.
CÒN MỞ: băn khoăn khách nêu, câu chưa trả lời được, việc trợ lý đã hứa; không có → "không".
Giữ mọi fact trong tóm tắt trước vẫn còn đúng; fact mới mâu thuẫn → lấy mới. KHÔNG bịa,
KHÔNG chép nguyên văn tin nhắn.

{prior_block}

Tin nhắn cần tóm tắt:
{messages_block}
"""


def _format_message(m: ThreadMessage) -> str:
    if m.role == "user":
        return f"User: {m.content}"
    if m.role == "assistant":
        body = m.content or ""
        if m.tool_calls:
            calls = ", ".join(tc.get("function", {}).get("name", "?") for tc in m.tool_calls)
            body = f"{body} [tool_calls: {calls}]".strip()
        return f"Assistant: {body}"
    if m.role == "tool":
        return f"Tool[{m.name}]: {m.content}"
    return f"{m.role}: {m.content}"


def build_summary_prompt(prior: ThreadSummary | None, messages: list[ThreadMessage]) -> str:
    prior_block = f"Tóm tắt phiên trước:\n{prior.text}\n" if prior else "(Chưa có tóm tắt phiên trước.)"
    messages_block = "\n".join(_format_message(m) for m in messages)
    return _SUMMARY_PROMPT.format(prior_block=prior_block, messages_block=messages_block)


async def summarize_and_persist(
    *,
    sid: str,
    history: list[ThreadMessage],
    prior_summary: ThreadSummary | None,
    llm,
    repo,
    model: str | dict[str, str],
    keep_tail: int,
    primary: str | None = None,
) -> ThreadSummary | None:
    """Summarize the overflow head and persist the new summary.

    Returns the newly-persisted ``ThreadSummary`` (so the caller can warm the
    next-turn prompt cache with it), or ``None`` when nothing was summarized
    (not enough new turns) or the LLM call failed.
    """
    covered = prior_summary.covers_turns if prior_summary else 0
    if keep_tail < 0:
        keep_tail = 0

    # K and keep_tail are measured in *user-turns* (one role=user message and
    # all assistant/tool messages that follow it until the next role=user).
    # We always cut at a role=user boundary, which simultaneously (a) makes
    # "keep last N user-turns verbatim" the literal meaning of keep_tail and
    # (b) guarantees the verbatim tail never starts with role=tool — an
    # orphan tool result would 400 the next provider call.
    user_indices = [i for i in range(covered, len(history)) if history[i].role == "user"]
    if keep_tail == 0:
        candidate_cut = len(history)
    else:
        if len(user_indices) <= keep_tail:
            return  # Not enough new user-turns past the keep_tail window.
        candidate_cut = user_indices[len(user_indices) - keep_tail]

    to_summarize = history[covered:candidate_cut]
    if not to_summarize:
        return
    prompt = build_summary_prompt(prior_summary, to_summarize)

    try:
        text = await llm.simple_completion(prompt, model=model, max_tokens=500, primary=primary, purpose="summary")
    except Exception as exc:
        logger.warning("summarizer: llm call failed (%s) — skipping summary update", exc)
        return

    new_summary = ThreadSummary(
        text=(text or "").strip(),
        covers_turns=covered + len(to_summarize),
        updated_at=datetime.now(UTC),
    )
    await repo.update_summary(sid, new_summary)
    return new_summary
