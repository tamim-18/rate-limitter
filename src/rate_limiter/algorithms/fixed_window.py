"""Fixed window counter — simplest of the four, INCR + EXPIRE in Lua.

Time is sliced into back-to-back windows of `window_seconds`. Each request
increments the counter for the current window; when the count exceeds
`max_requests`, the request is denied. The counter for window N exists only
until the window's end (TTL = window_seconds, set on the first INCR), so
window N+1 naturally starts from zero against a missing key.

Trade-off vs token bucket: at a window boundary a client can land up to
`2 · max_requests` requests inside an arbitrarily small interval. Long-run
rate is still `max_requests / window_seconds`. See `fixed_window.md` §3.5
for the math behind the boundary burst.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rate_limiter.algorithms._lua import load_script
from rate_limiter.algorithms.base import (
    AlgorithmType,
    BaseAlgorithm,
    Decision,
    RuleSpec,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    RedisClient = Redis[str]


class FixedWindow(BaseAlgorithm):
    name: ClassVar[AlgorithmType] = AlgorithmType.fixed_window

    def __init__(self, redis: RedisClient) -> None:
        super().__init__(redis)
        self._script = load_script(redis, "fixed_window")

    async def check(self, key: str, rule: RuleSpec) -> Decision:
        result: list[int] = await self._script(
            keys=[key],
            args=[rule.max_requests, rule.window_seconds],
        )
        allowed, remaining, retry_after_ms, reset_at_ms = result
        return Decision(
            allowed=bool(allowed),
            remaining=int(remaining),
            retry_after_ms=int(retry_after_ms),
            reset_at_ms=int(reset_at_ms),
        )
