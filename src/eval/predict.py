"""Teacher-forcing prediction: one LLM completion per turn using the agent's provider chain."""

from __future__ import annotations

from eval.data import TurnSample


async def _noop(_token: str) -> None:
    return None


def build_predictor():
    """Build (StreamingClient, model_map, primary_provider) from the agent's .env config.

    Returns the same provider chain the live agent uses, so predictions reflect
    the production model (NOBLE_AGENT_MODEL primary, openai/gemini fallback).
    """
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.agent.llm.client import StreamingClient
    from noble_agent.config import get_settings, primary_for, provider_model_map

    settings = get_settings()
    client = StreamingClient(build_llm_providers(), enable_thinking=settings.llm_enable_thinking)
    model = provider_model_map(settings)
    primary = primary_for(settings, settings.agent_model)
    return client, model, primary


async def predict_turn(client, sample: TurnSample, *, model, primary, temperature: float, max_tokens: int) -> dict:
    """One non-iterating completion. Returns an OpenAI-shaped assistant message.

    Strips any ``<think>...</think>`` reasoning from the prediction so the judge
    scores the answer, not the model's reasoning.
    """
    from noble_agent.agent.llm.thinking import strip_think

    content, tool_calls = await client.stream_completion(
        messages=sample.prefix,
        tools=sample.tools,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        on_token=_noop,
        primary=primary,
    )
    return {"role": "assistant", "content": strip_think(content or ""), "tool_calls": tool_calls or []}
