"""Predicts the next N user queries given recent history + customer state.

Single LLM call returning a JSON array of strings. The same StreamingClient
used by the agent is reused — we just call it with ``tools=[]`` and parse
the streamed content.
"""

from __future__ import annotations

import json
import logging
import re

from noble_agent.storage.models import Customer, ThreadMessage

logger = logging.getLogger("noble_agent.semcache.predictor")


_SYS = (
    "Bạn là trợ lý dự đoán câu hỏi tiếp theo của khách hàng đang gọi hotline "
    "tư vấn bất động sản NobleX. Dựa trên lịch sử cuộc hội thoại gần nhất "
    "(và thông tin khách hàng nếu có), hãy đoán {n} câu hỏi/câu yêu cầu mà "
    "khách rất có thể nói tiếp ngay sau đó.\n\n"
    "QUY TẮC:\n"
    "1. Viết bằng tiếng Việt giao tiếp tự nhiên đúng như khách hàng sẽ nói.\n"
    "2. Mỗi câu ngắn gọn (5-25 từ), độc lập, có thể đứng riêng.\n"
    "3. Đa dạng: bao phủ các hướng khác nhau (hỏi thông tin, đặt lịch, giá, vị "
    "trí, so sánh dự án, yêu cầu hỗ trợ…).\n"
    "4. KHÔNG nhắc lại câu khách vừa hỏi.\n"
    "5. Chỉ trả về một JSON array đúng {n} phần tử string, không thêm văn bản "
    "nào khác."
)


def _format_history(history: list[ThreadMessage], lookback: int) -> str:
    msgs = [m for m in history if m.role in ("user", "assistant") and m.content]
    msgs = msgs[-lookback:]
    lines: list[str] = []
    for m in msgs:
        tag = "Khách" if m.role == "user" else "Tư vấn"
        text = (m.content or "").strip().replace("\n", " ")
        if text:
            lines.append(f"{tag}: {text}")
    return "\n".join(lines) if lines else "(chưa có lượt nào)"


def _customer_snippet(customer: Customer) -> str:
    bits: list[str] = []
    if customer.name:
        bits.append(f"tên={customer.name}")
    if customer.project_interest:
        bits.append(f"dự án={customer.project_interest}")
    if customer.purpose:
        bits.append(f"mục đích={customer.purpose}")
    if customer.budget:
        bits.append(f"ngân sách={customer.budget}")
    return ", ".join(bits) if bits else "(chưa rõ)"


def _parse_array(raw: str, n: int) -> list[str]:
    """Tolerate models that wrap the array in prose or code fences."""
    if not raw:
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        arr = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    out: list[str] = []
    for item in arr:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= n:
            break
    return out


async def predict_next_queries(
    *,
    llm,
    model: str | dict[str, str],
    history: list[ThreadMessage],
    customer: Customer,
    last_user_text: str,
    n: int,
    lookback: int,
    temperature: float,
    primary: str | None = None,
) -> list[str]:
    sys_prompt = _SYS.format(n=n)
    user_prompt = (
        f"Thông tin khách: {_customer_snippet(customer)}\n\n"
        f"Lịch sử gần nhất:\n{_format_history(history, lookback)}\n\n"
        f"Khách vừa nói: {last_user_text.strip()}\n\n"
        f"Hãy trả về JSON array đúng {n} câu hỏi/câu yêu cầu kế tiếp của khách."
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    async def _drain(_token: str) -> None:
        return None

    try:
        content, _tc = await llm.stream_completion(
            messages=messages,
            tools=[],
            model=model,
            temperature=temperature,
            max_tokens=512,
            on_token=_drain,
            primary=primary,
            purpose="semcache",
        )
    except Exception:
        logger.exception("semcache.predictor: LLM call failed")
        return []

    return _parse_array(content or "", n)
