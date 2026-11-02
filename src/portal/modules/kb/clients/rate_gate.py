"""Điều tiết nhịp gọi VLM trong một tiến trình: gặp 429 thì lùi, êm rồi thì tiến lại."""

import asyncio
import time
from collections.abc import Callable


class VlmRateGate:
    def __init__(
        self,
        *,
        ceiling: int,
        floor: int = 1,
        cooldown_sec: float = 30.0,
        recover_after: int = 50,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ceiling < 1 or floor < 1 or floor > ceiling:
            raise ValueError(f"ceiling/floor không hợp lệ: {ceiling}/{floor}")
        self._ceiling = ceiling
        self._floor = floor
        self._cooldown = cooldown_sec
        self._recover_after = recover_after
        self._clock = clock
        self.permits = ceiling
        self._paused_until = 0.0
        self._successes = 0
        self._in_use = 0
        # Condition chứ không Semaphore: `permits` GIẢM được lúc chạy, mà semaphore thì
        # khoá cứng số slot lúc dựng — dùng nó là penalize() chỉ đổi một con số trang trí.
        self._cond = asyncio.Condition()

    def penalize(self) -> None:
        self.permits = max(self._floor, self.permits // 2)
        self._successes = 0
        self._paused_until = self._clock() + self._cooldown

    def reward(self) -> None:
        self._successes += 1
        if self._successes >= self._recover_after:
            self._successes = 0
            self.permits = min(self._ceiling, self.permits + 1)

    def paused_for(self) -> float:
        return max(0.0, self._paused_until - self._clock())

    async def __aenter__(self) -> "VlmRateGate":
        cho = self.paused_for()
        if cho:
            await asyncio.sleep(cho)
        async with self._cond:
            await self._cond.wait_for(lambda: self._in_use < self.permits)
            self._in_use += 1
        return self

    async def __aexit__(self, *exc) -> None:
        async with self._cond:
            self._in_use -= 1
            self._cond.notify()
