"""Single-turn LLM + tool loop. No handoffs, no per-agent threads."""

from __future__ import annotations

import logging
from collections.abc import Callable

from noble_agent.agent import session_facts
from noble_agent.agent.base import AgentDef
from noble_agent.agent.context_compaction import build_request_messages
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.agent.tools import analytics_vocab
from noble_agent.storage.models import Customer, State, ThreadMessage

logger = logging.getLogger("noble_agent.runner")

MAX_TOOL_ITERATIONS = 7
# Mỗi tool tối đa 2 lần dispatch THẬT/lượt (bất kể tham số) — qwen3.7-flash
# retry kb_search với query biến tấu nên dup-guard exact không chặn được.
# update_customer miễn trừ: quy tắc 4 bảo gộp field vào MỘT call, nhưng model
# chưa gộp mà bị chặn ở call thứ 3 là mất field khách vừa cho — giữ làm lưới.
MAX_CALLS_PER_TOOL = 2
_TOOL_CAP_EXEMPT = frozenset({"update_customer"})
# escalate chặt hơn: 1 lần/lượt — qwen3.7-flash escalate 2 lần cho một câu
# hoàn toàn trả lời được (đo 2026-08-24); tín hiệu chuyển đã gửi thì gửi rồi.
# send_media nới lên 3: luồng hai bước của nó cần ĐÚNG 2 lần dispatch (lượt trả
# `candidates` + lượt gửi theo `ids`), tức dùng hết trọn ngân sách mặc định. Một
# lần gọi sai tham số ở đầu lượt là lượt gửi thật bị chặn bằng `{"repeat": true}`,
# và khách nhận không ảnh nào dù media có tồn tại — hỏng nặng hơn cái nó đang sửa.
_TOOL_CAP_OVERRIDES = {"escalate": 1, "send_media": 3}


async def run_turn(
    *,
    agent: AgentDef,
    state: State,
    customer: Customer,
    llm,
    dispatcher,
    callbacks,
    interrupt_check: Callable[[], bool] | None = None,
    model: str | dict[str, str] | None = None,
    primary: str | None = None,
    force_tool_first_round: bool = False,
) -> None:
    """Drive one user turn against the live state. Mutates state.history.

    `interrupt_check` (optional) is polled by the LLM streaming layer between
    chunks so voice barge-in can cut the response short. It is also polled
    here between iterations so tool loops terminate fast on interrupt.
    """
    system = build_system_prompt(agent, customer, state.summary, customer_block=state.scratchpad.get("customer_block"))
    messages: list[dict] = [{"role": "system", "content": system}]

    start = state.summary.covers_turns if state.summary else 0
    # Kết quả tool của lượt cũ → digest; khối "[Ngữ cảnh hiện tại]" (hồ sơ mới nhất +
    # fact phiên) chèn vào user message cuối. Chỉ bản request — history không đổi.
    messages.extend(
        build_request_messages(state.history, start=start, ephemeral=session_facts.render(state, customer) or None)
    )

    # Caller (orchestrator) passes a per-provider model map + primary pin.
    # Backwards-compatible path (older callers / direct unit tests): if no
    # routing is supplied, fall back to `agent.model` flowed through chain.
    turn_model: str | dict[str, str] = model if model is not None else agent.model

    # Per-turn: điền vocab giá trị thật + xref vào description (AgentDef frozen
    # nên không chèn được lúc build_schemas). No-op khi tenant không bật tool.
    tool_schemas = analytics_vocab.inject(agent.tool_schemas)
    seen_calls: set[tuple[str, str]] = set()
    tool_counts: dict[str, int] = {}

    for iteration in range(MAX_TOOL_ITERATIONS):
        if interrupt_check is not None and interrupt_check():
            logger.info("runner: interrupted before LLM call")
            return

        # Vòng ĐẦU của turn có thể bị ép gọi tool (chặn model "nhớ" dữ liệu
        # thay vì tra cứu — gemini-2.5-flash/qwen bỏ tool ở câu mở màn). Van
        # xả cho lượt xã giao là tool no_lookup_needed. Các vòng sau luôn
        # auto để model kết thúc được câu trả lời.
        forced = "required" if (force_tool_first_round and iteration == 0 and tool_schemas) else None

        content, tool_calls = await llm.stream_completion(
            messages=messages,
            tools=tool_schemas,
            model=turn_model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            on_token=callbacks.on_token,
            interrupt_check=interrupt_check,
            primary=primary,
            tool_choice=forced,
        )

        # Drop tool_calls the provider cut off mid-stream — without an id or
        # name we cannot pair a tool result message, and persisting them would
        # 400 the next turn (orphan tool_call_id="").
        if tool_calls:
            valid_tcs = [tc for tc in tool_calls if tc.get("id") and (tc.get("function") or {}).get("name")]
            dropped = len(tool_calls) - len(valid_tcs)
            if dropped:
                logger.warning("runner: dropping %d tool_call(s) with empty id/name", dropped)
            tool_calls = valid_tcs or None

        assistant_msg = ThreadMessage(role="assistant", content=content or "", tool_calls=tool_calls)
        state.history.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            await _ket_luot(dispatcher)
            return

        if interrupt_check is not None and interrupt_check():
            # Inject placeholder tool results so history invariant holds — every
            # tool_call must have a sibling tool message before we stop.
            for tc in tool_calls:
                state.history.append(
                    ThreadMessage(
                        role="tool",
                        tool_call_id=tc["id"],
                        name=tc["function"]["name"],
                        content='{"interrupted": true}',
                    )
                )
            logger.info("runner: interrupted before tool dispatch")
            return

        for tc in tool_calls:
            # Chặn vòng lặp tool: CÙNG tool + CÙNG tham số trong một lượt thì
            # không dispatch lại (qwen3.7-flash lặp kb_search 4-5 lần khi kết
            # quả rỗng, đốt hết MAX_TOOL_ITERATIONS mà không trả lời). Tham số
            # khác nhau (phân trang index, nới filter) vẫn đi qua bình thường.
            name = tc["function"]["name"]
            key = (name, (tc["function"].get("arguments") or "").strip())
            cap = _TOOL_CAP_OVERRIDES.get(name, MAX_CALLS_PER_TOOL)
            over_cap = name not in _TOOL_CAP_EXEMPT and tool_counts.get(name, 0) >= cap
            if key in seen_calls or over_cap:
                result = (
                    '{"repeat": true, "note": "Tool này đã được gọi đủ trong lượt — dừng tra cứu,'
                    ' trả lời khách bằng dữ liệu đã có; kết quả rỗng thì nói rõ, không bịa."}'
                )
            else:
                seen_calls.add(key)
                tool_counts[name] = tool_counts.get(name, 0) + 1
                result = await dispatcher.dispatch(tc)
            tool_msg = ThreadMessage(
                role="tool",
                tool_call_id=tc["id"],
                name=tc["function"]["name"],
                content=result,
            )
            state.history.append(tool_msg)
            messages.append(tool_msg.to_openai())

    # Chạm trần vòng tool mà model vẫn đòi gọi tiếp → ép MỘT vòng chốt
    # tool_choice="none" để khách luôn nhận được câu trả lời thay vì im lặng
    # (đã xảy ra thật với qwen3.7-flash: 2/3 lượt kb-policy trả về rỗng).
    logger.warning("runner: hit MAX_TOOL_ITERATIONS — ép vòng chốt không tool")
    # tools=[] chứ không phải tool_choice="none": qwen3.7-flash phớt lờ "none"
    # và vẫn đòi tool → content rỗng. Không khai tools thì model BẮT BUỘC trả
    # lời bằng văn bản; cả dashscope lẫn gemini openai-compat đều chấp nhận
    # history có tool-message mà không khai tools (probe 2026-08-24, 200 OK).
    content, tool_calls = await llm.stream_completion(
        messages=messages,
        tools=[],
        model=turn_model,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        on_token=callbacks.on_token,
        interrupt_check=interrupt_check,
        primary=primary,
    )
    if tool_calls:
        # Provider phớt lờ "none" vẫn có thể trả tool_calls — không dispatch,
        # nhưng phải giữ invariant assistant(tool_calls) ↔ tool messages.
        tool_calls = [tc for tc in tool_calls if tc.get("id") and (tc.get("function") or {}).get("name")]
    state.history.append(ThreadMessage(role="assistant", content=content or "", tool_calls=tool_calls or None))
    for tc in tool_calls or []:
        state.history.append(
            ThreadMessage(
                role="tool",
                tool_call_id=tc["id"],
                name=tc["function"]["name"],
                content='{"skipped": "đã đạt giới hạn vòng tool trong lượt"}',
            )
        )
    await _ket_luot(dispatcher)


async def _ket_luot(dispatcher) -> None:
    """Cho dispatcher trả nợ cuối lượt (xem `ToolDispatcher.finish_turn`).

    Gọi ở HAI đường ra "lượt xong bình thường", cố ý KHÔNG gọi ở đường interrupt:
    khách vừa ngắt lời thì đẩy thêm một thẻ ảnh lên màn hình là sai.

    `getattr` vì `run_turn` nhận dispatcher dạng duck-typed — sandbox của semcache
    và các test cũ truyền vào bản không có phương thức này.
    """
    hook = getattr(dispatcher, "finish_turn", None)
    if hook is None:
        return
    try:
        await hook()
    except Exception:
        logger.warning("runner: finish_turn thất bại", exc_info=True)
