"""Sliding window log — exact per-window enforcement via a ZSET of timestamps.

Where token bucket trades smoothness for memory and fixed window trades
accuracy for simplicity, sliding-window-log trades **memory** for
**provable correctness**: at any time `now`, the count of requests in
`(now - W, now]` is bounded by `max_requests`. No boundary effect, no
2× overshoot.

Memory is O(N) per active client where N ≤ capacity (one ZSET entry per
in-window request). Use this algorithm when fairness matters more than
storage — strict billing APIs, write paths, regulated workloads.

See `sliding_window_log.md` for the math; the heavy lifting is in the
Lua script.
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


class SlidingWindowLog(BaseAlgorithm):
    name: ClassVar[AlgorithmType] = AlgorithmType.sliding_window_log

    def __init__(self, redis: RedisClient) -> None:
        super().__init__(redis)
        self._script = load_script(redis, "sliding_window_log")

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
