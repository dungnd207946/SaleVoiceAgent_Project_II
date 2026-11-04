"""Optional live LLM checks — run with INTEGRATION_TEST=1 and API keys."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION_TEST", "").lower() not in ("1", "true", "yes"),
    reason="Set INTEGRATION_TEST=1 to run",
)


@pytest.mark.asyncio
async def test_streaming_llm_single_turn():
    from noble_agent.agent.llm.streaming import StreamingLLM

    llm = await StreamingLLM.create("integration-e2e")
    out: list[str] = []

    await llm.stream_response("Xin chào", on_token=lambda t: out.append(t))
    text = "".join(out)
    assert len(text.strip()) > 0
