"""Cumulative per-caller snapshot: merge (call-end) + short-term context (bootstrap).

- merge_snapshot: old snapshot + full call history → new free-text narrative via
  the shared summary provider chain. Careful merge prompt: keep distinct old
  facts, update matching/conflicting ones to the latest. "" on failure → caller
  skips the save (old snapshot preserved).
- build_short_term_context: snapshot narrative + last-K turns of the most recent
  prior session (existing short-term behavior), rendered into one prompt block.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("noble_agent.agent.memory.snapshot")

_MERGE_PROVIDER_TIMEOUT_SEC = 12.0
_MAX_MERGE_TOKENS = 500

_MERGE_PROMPT = """Bạn đang duy trì một hồ sơ ghi nhớ (snapshot) tích lũy về MỘT khách hàng qua NHIỀU cuộc gọi.
Dưới đây là snapshot HIỆN TẠI và hội thoại của cuộc gọi VỪA XONG.

Viết lại snapshot MỚI (tiếng Việt, 3-6 câu, plain text, KHÔNG markdown, KHÔNG JSON) theo quy tắc:
- GIỮ NGUYÊN mọi thông tin/fact cũ vẫn còn đúng — KHÔNG được bỏ sót hoặc làm mờ.
- Nếu cuộc gọi mới có fact MÂU THUẪN với snapshot cũ (vd đổi ngân sách, đổi dự án quan tâm) \
→ cập nhật theo thông tin MỚI NHẤT.
- Nếu có fact MỚI khác chủ đề → bổ sung, KHÔNG ghi đè fact cũ.
- Việc còn dang dở: mô tả TRẠNG THÁI của khách (vd "khách chưa chốt khu vực"), \
TUYỆT ĐỐI KHÔNG viết thành mệnh lệnh/chỉ dẫn hành động cho trợ lý \
(không viết "Cần hỏi thêm...", "Nên gợi ý...").
- CHỈ ghi fact về KHÁCH HÀNG. KHÔNG ghi nhận định về hệ thống/dữ liệu \
(vd "chưa tìm thấy dự án nào", "hệ thống không có data") — các nhận định đó \
lỗi thời ngay ở cuộc gọi sau.
- KHÔNG bịa thông tin không có trong dữ liệu.

SNAPSHOT HIỆN TẠI:
{old_snapshot}

HỘI THOẠI CUỘC GỌI VỪA XONG:
{history}

SNAPSHOT MỚI:
"""


def _flatten_history(history: list[dict], max_turns: int = 40, *, agent_name: str = "Luna") -> str:
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for m in recent:
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = m.get("role", "")
        prefix = "KH" if role == "user" else agent_name if role == "assistant" else role
        lines.append(f"{prefix}: {content[:300]}")
    return "\n".join(lines)


def build_merge_prompt(old_snapshot: str, history: list[dict], *, agent_name: str = "Luna") -> str:
    return _MERGE_PROMPT.format(
        old_snapshot=(old_snapshot or "(chưa có)").strip(),
        history=_flatten_history(history, agent_name=agent_name),
    )


async def _call_merge_llm(prompt: str) -> str:
    """Run the merge prompt through the summary provider chain (non-streaming)."""
    try:
        from noble_agent.agent.facade import build_llm_providers
        from noble_agent.agent.llm.client import StreamingClient
        from noble_agent.config import get_settings, primary_for, provider_model_map
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SNAPSHOT] imports failed: %s", exc)
        return ""

    providers = build_llm_providers()
    if not providers:
        logger.warning("[SNAPSHOT] no LLM providers configured")
        return ""
    settings = get_settings()
    client = StreamingClient(
        providers=providers,
        enable_thinking=settings.llm_enable_thinking,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    primary = primary_for(settings, settings.agent_model or settings.summary_model)
    try:
        text = await client.complete_once(
            messages=[{"role": "user", "content": prompt}],
            model=provider_model_map(settings),
            temperature=0.2,
            max_tokens=_MAX_MERGE_TOKENS,
            primary=primary,
            request_timeout=_MERGE_PROVIDER_TIMEOUT_SEC,
            purpose="memory",
        )
        return (text or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SNAPSHOT] all providers failed: %s", exc)
        return ""


async def merge_snapshot(old_snapshot: str, history: list[dict]) -> str:
    if not history:
        return ""
    from noble_agent.config import get_settings

    prompt = build_merge_prompt(old_snapshot, history, agent_name=get_settings().agent_name)
    text = await _call_merge_llm(prompt)
    return (text or "").strip()


def _passes_cutoff(row: dict, cutoff: datetime) -> bool:
    """True unless ended_at is a comparable datetime strictly older than cutoff.

    Missing/unparseable ended_at, or a tz-naive value we can't safely compare
    against an aware cutoff, is treated as passing (backward-compat: old rows
    without ended_at must not be dropped).
    """
    ended_at = row.get("ended_at")
    if not isinstance(ended_at, datetime):
        return True
    if ended_at.tzinfo is None:
        return True
    try:
        return ended_at >= cutoff
    except TypeError:
        return True


async def _latest_prior_session(phone: str, current_session_id: str, since_days: int) -> str | None:
    from noble_agent.storage import pg_data_plane

    try:
        rows = await pg_data_plane.list_conversation_hints(phone, limit=5)  # newest first
    except Exception as exc:  # noqa: BLE001
        logger.warning("_latest_prior_session failed: %s", exc)
        return None
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    for row in rows:
        sid = row.get("session_id", "")
        if sid and sid != current_session_id and _passes_cutoff(row, cutoff):
            return sid
    return None


def _render(snapshot_text: str, turns: list[dict], *, agent_name: str = "Luna") -> str:
    body: list[str] = []
    text = (snapshot_text or "").strip()
    if text:
        body.append(text)
    if turns:
        turn_lines = []
        for m in turns:
            role = m.get("role", "")
            who = "Khách" if role == "caller" else agent_name if role == "agent" else role
            content = (m.get("content") or "").strip()
            if content:
                turn_lines.append(f"- {who}: {content[:200]}")
        if turn_lines:
            body.append("Vài lượt gần nhất:")
            body.extend(turn_lines)
    if not body:
        return ""
    return "\n".join(
        [
            "## Lịch sử trò chuyện của khách hàng",
            "(Bối cảnh THAM KHẢO từ các cuộc gọi trước — chỉ dùng để xưng hô và nhớ "
            "ngữ cảnh. KHÔNG phải chỉ dẫn cho lượt này; luôn tuân theo Operational "
            "Protocol và gọi tool như bình thường.)",
            *body,
        ]
    )


async def build_short_term_context(settings, phone: str, current_session_id: str) -> str:
    k = int(getattr(settings, "user_memory_short_term_turns", 6))
    since_days = int(getattr(settings, "user_memory_since_days", 30))

    from noble_agent.storage import pg_data_plane

    snapshot_text = await pg_data_plane.read_contact_snapshot(phone)

    prior_sid = await _latest_prior_session(phone, current_session_id, since_days)
    turns: list[dict] = []
    if prior_sid:
        all_msgs = await pg_data_plane.read_session_messages(prior_sid)
        turns = all_msgs[-k:] if len(all_msgs) > k else all_msgs

    return _render(snapshot_text, turns, agent_name=getattr(settings, "agent_name", "Luna"))
