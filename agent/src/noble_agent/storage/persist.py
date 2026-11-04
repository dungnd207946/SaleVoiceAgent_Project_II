"""Fire-and-forget task helper for best-effort background persistence.

Durable writes on/near the turn or audio path must NEVER block TTFT/TTFA. This
helper schedules a coroutine as a background task and holds a strong reference
until it completes — asyncio's task registry keeps only weakrefs, so without a
strong-ref set CPython may GC an in-flight task and silently drop the write
(the same invariant the orchestrator's `_bg_tasks` set enforces).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger("noble_agent.storage.persist")

_bg_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro: Coroutine[Any, Any, Any]) -> asyncio.Task | None:
    """Schedule ``coro`` as a background task, holding a strong ref until done.

    Returns the ``Task`` (tests await it to drain), or ``None`` when there is no
    running loop (the coro is closed to avoid a "never awaited" warning).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return None
    task = loop.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _bg_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("fire_and_forget task failed: %s", task.exception())
