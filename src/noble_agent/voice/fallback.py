"""Init-time backend fallback chains for voice STT & TTS.

Pure-Python, dependency-free: holds the fixed fallback chain constants, a
pure `resolve_order` (configured primary stays head, rest of its chain
follows), and an async `_start_first_available` loop helper shared by the
Transport (STT) and Voice I/O (TTS) layers. Keeping it free of heavy imports
lets its unit tests run without any optional STT/TTS deps.

Init-time only: fallback triggers when a backend fails to construct/start. A
backend that starts healthy but later dies mid-session does NOT trigger
fallback (out of scope).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("voice.fallback")

# Fixed code-constant chains. Service-client backend `remote` đứng đầu; khi nó
# là primary, fallback ưu tiên CLOUD (soniox/elevenlabs) trước rồi mới tới model
# LOCAL (sherpa/vieneu) như last-resort — rớt về local TRONG worker sẽ tái hiện
# đúng vấn đề VRAM/warmup mà service sinh ra để giải. resolve_order giữ nguyên
# ngữ nghĩa: primary cấu hình luôn là head.
STT_FALLBACK_CHAIN: list[str] = ["remote", "soniox", "sherpa"]
TTS_FALLBACK_CHAIN: list[str] = ["remote", "vieneu_vllm", "elevenlabs", "vieneu", "hotline_ws"]


def resolve_order(configured: str, chain: list[str]) -> list[str]:
    """Effective attempt order for `configured` against its fallback `chain`.

    - `configured` not in `chain` → `[configured]` (no auto-fallback; non-chain
      primaries like `qwen3asr` behave exactly as before).
    - otherwise → `[configured]` followed by the other chain members, in the
      chain's documented order.
    """
    if configured not in chain:
        return [configured]
    return [configured] + [c for c in chain if c != configured]


async def _teardown(name: str, inst: object) -> None:
    """Best-effort async teardown of a half-started backend (never raises).

    Tears down a constructed-but-failed-to-start instance via `stop()` (or
    `aclose()` if no `stop`). Teardown failure is logged and swallowed so it
    can neither mask the original start error nor escape the fallback loop.
    """
    closer = getattr(inst, "stop", None) or getattr(inst, "aclose", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup, never propagate
        logger.warning("backend '%s' teardown after failed start raised: %s — ignoring", name, exc)


async def _start_first_available(
    order: list[str],
    builders: dict[str, Callable[[], object]],
    *,
    on_exhausted: Callable[[], Awaitable[None]],
) -> object | None:
    """Build + `start()` each backend in `order`; return the first that succeeds.

    Each `builders[name]()` constructs an instance exposing an awaitable
    `start()`. The first instance whose `start()` does not raise is returned.
    Per-backend construct/start failures are swallowed (logged) and the loop
    continues. If a backend constructs but its `start()` raises, the
    half-started instance is torn down best-effort (`stop()`/`aclose()`, if
    present) before the next backend is tried, so a failed backend never leaks
    an open connection/task behind a live fallback. If every backend fails,
    `on_exhausted()` is awaited exactly once and `None` is returned.
    """
    for name in order:
        inst: object | None = None
        try:
            inst = builders[name]()
            await inst.start()
        except Exception as exc:  # noqa: BLE001 - any construct/start failure → next backend
            logger.warning("backend '%s' failed to start: %s — trying next", name, exc)
            # Only a constructed-but-not-started instance needs teardown; a
            # builder that raised during construction has no instance to stop.
            if inst is not None:
                await _teardown(name, inst)
            continue
        return inst
    await on_exhausted()
    return None
