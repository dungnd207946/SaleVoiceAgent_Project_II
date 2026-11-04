"""Self-hosted Arize Phoenix OTEL LLM tracing — boot-time init.

`init_tracing(settings)` auto-instruments the Anthropic + OpenAI SDKs so every
live LLM turn, the async-summary path, and the semcache path emit spans to a
self-hosted Phoenix collector. The two instrumentors cover the whole provider
matrix: `AnthropicInstrumentor` catches the `AnthropicProvider` path, and
`OpenAIInstrumentor` catches all four openai-compat slots (openai / dashscope /
vllm / gemini — each an `openai.AsyncOpenAI` instance).

Contract (mirrors `voice/prewarm.py` "log + continue"):
  - Empty `phoenix_collector_endpoint` → clean no-op, returns False. The heavy
    imports (`phoenix.otel`, `openinference.*`) are function-local so the
    `tracing` extra need not be installed for the no-op path or for
    `make test-unit` collection.
  - Idempotent per process via a module-level `_initialized` flag — correct for
    both the single-process aiortc server and each forked LiveKit job-subprocess
    (separate processes ⇒ separate module state ⇒ one register each).
  - `batch=True` on `register(...)` → background BatchSpanProcessor. NEVER the
    default SimpleSpanProcessor, which exports synchronously and would block the
    TTFT/TTFA hot path.
  - Any failure (missing dep, bad kwarg, collector down) is swallowed: log a
    warning and return False. Boot never aborts on tracing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.observability")

# Per-process idempotency guard. Separate processes (aiortc server / each
# LiveKit job-subprocess) have independent module state → each registers once.
_initialized = False


def reset_tracing_for_tests() -> None:
    """Test-only helper: clear the per-process init flag (mirrors
    `config.reset_settings_for_tests`)."""
    global _initialized
    _initialized = False


def _normalize_endpoint(endpoint: str) -> str:
    """Ensure the HTTP OTLP traces path is present (append `/v1/traces`)."""
    stripped = endpoint.rstrip("/")
    if stripped.endswith("/v1/traces"):
        return stripped
    return stripped + "/v1/traces"


def init_tracing(settings) -> bool:
    """Initialise Phoenix tracing once per process. Returns True if tracing is
    active after the call, else False (no-op / disabled / failed).
    """
    global _initialized

    endpoint = (settings.phoenix_collector_endpoint or "").strip()
    if not endpoint:
        return False

    if _initialized:
        return True

    try:
        # Heavy imports stay function-local so the no-op path and unit-test
        # collection don't require the `tracing` extra.
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from phoenix.otel import register

        traces_endpoint = _normalize_endpoint(endpoint)
        headers: dict[str, str] = {}
        if settings.phoenix_api_key:
            headers["Authorization"] = f"Bearer {settings.phoenix_api_key}"

        project_name = settings.phoenix_project_name or "noble-voice-agent"

        tracer_provider = register(
            project_name=project_name,
            endpoint=traces_endpoint,
            headers=headers,
            batch=True,  # background BatchSpanProcessor — NOT the sync default
            auto_instrument=False,  # explicit instrumentors below (deterministic)
        )

        AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

        _initialized = True
        logger.info("phoenix tracing enabled → %s (project=%s)", traces_endpoint, project_name)
        return True
    except Exception as exc:  # noqa: BLE001 — never abort boot on tracing
        logger.warning("phoenix tracing init failed (continuing without tracing): %s", exc)
        return False
