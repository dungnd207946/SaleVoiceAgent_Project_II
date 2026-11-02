"""Bench LLM TTFT/total qua provider chain đang pin.

Brief gốc giả định seam `noble_agent.agent.llm.streaming.StreamingLLM.create(session_id)`
+ `stream_response(user_text=..., on_token=...)`, theo `tests/bench_estate/runner.py::_create_llm`.
Module đó KHÔNG tồn tại trong `src/` hiện tại — nó bị xoá cùng lúc multi-agent architecture
bị xoá khi refactor sang unified single-agent (xem CLAUDE.md). Xác nhận: `_create_llm` sẽ
`ModuleNotFoundError` nếu thật sự chạy; `tests/bench_estate/tests/conftest.py::mock_streaming_llm`
mock lại đúng API multi-agent cũ (`_history`, `_current_agent`, `stream_response(user_input) -> str`),
tức là seam đó trong bench_estate chỉ còn sống qua mock, không có đường thật.

Seam THẬT đang chạy production hôm nay cho một lời gọi LLM streaming một-lượt là
`StreamingClient.stream_completion` (`agent/llm/client.py`), dựng qua
`agent/facade.build_llm_providers()` — cùng pattern `agent/memory/snapshot.py::_call_merge_llm`,
`agent/summary/generator.py`, `voice/addressee_gate.py` đang dùng cho các lời gọi LLM một-lượt
ngoài turn loop chính. Chữ ký thật:

    async def stream_completion(*, messages, tools, model, temperature, max_tokens,
                                 on_token: Callable[[str], Awaitable[None]],
                                 interrupt_check=None, primary=None,
                                 purpose="conversation") -> tuple[str, list[dict] | None]

Khác brief: `on_token` ở đây là **ASYNC** callable, không phải sync.
"""

from __future__ import annotations

import time

from evals.bench.results import ComponentResult, aggregate_runs

DEFAULT_PROMPT = "Chào em, cho anh hỏi Noble có những dự án nào?"


async def _once(prompt: str) -> dict[str, float]:
    from noble_agent.agent.facade import build_llm_providers  # noqa: PLC0415
    from noble_agent.agent.llm.client import StreamingClient  # noqa: PLC0415
    from noble_agent.config import get_settings, primary_for, provider_model_map  # noqa: PLC0415

    providers = build_llm_providers()
    if not providers:
        raise RuntimeError("no LLM providers configured (ANTHROPIC_API_KEY/OPENAI_API_KEY/GEMINI_API_KEY)")
    settings = get_settings()
    llm = StreamingClient(
        providers=providers,
        enable_thinking=settings.llm_enable_thinking,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    primary = primary_for(settings, settings.agent_model)

    t0 = time.perf_counter()
    ttft: list[float] = []

    async def on_token(_tok: str) -> None:
        if not ttft:
            ttft.append((time.perf_counter() - t0) * 1000.0)

    await llm.stream_completion(
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        model=provider_model_map(settings),
        temperature=settings.llm_temperature,
        max_tokens=300,
        on_token=on_token,
        primary=primary,
        purpose="conversation",
    )
    return {"ttft_ms": ttft[0] if ttft else 0.0, "total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_llm(*, prompt: str = DEFAULT_PROMPT, runs: int = 5) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    for _ in range(runs):
        try:
            samples.append(await _once(prompt))
        except Exception:  # noqa: BLE001 — một run lỗi là một điểm error_rate, không crash bench
            errors += 1
    return aggregate_runs("llm", samples, errors)
