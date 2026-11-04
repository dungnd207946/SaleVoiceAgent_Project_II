"""In-process chat admission cap (memo §0.4, §4).

Enforced now so a shared multi-tenant chat process rejects rather than
degrading all sessions at overload; the active/rejected counts are the signal
the phase-sau KEDA autoscaler reuses (scale on active-sessions, not CPU%)."""

from __future__ import annotations

import asyncio


class ChatAdmission:
    def __init__(self, max_sessions: int):
        self._max = max_sessions            # <= 0 → unbounded
        self._active = 0
        self._rejected = 0
        self._admitted = 0
        self._lock = asyncio.Lock()

    async def try_admit(self) -> bool:
        async with self._lock:
            if self._max > 0 and self._active >= self._max:
                self._rejected += 1
                return False
            self._active += 1
            self._admitted += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._active > 0:
                self._active -= 1

    def stats(self) -> dict:
        return {
            "active": self._active,
            "max": self._max,
            "admitted": self._admitted,
            "rejected": self._rejected,
            "at_capacity": self._max > 0 and self._active >= self._max,
        }


_admission: ChatAdmission | None = None


def get_chat_admission() -> ChatAdmission:
    global _admission
    if _admission is None:
        from noble_agent.config import get_settings

        _admission = ChatAdmission(get_settings().chat_max_concurrent_sessions)
    return _admission


def reset_admission_for_tests() -> None:
    global _admission
    _admission = None
