"""Token bucket — bursty-friendly, smooth long-run rate.

Capacity = `max_requests`. Refills at `capacity / window_seconds` tokens
per second. A client that is idle for a window starts with a full bucket,
then can burst up to capacity before being throttled to the steady refill
rate. Best fit for endpoints where occasional spikes are normal (search,
read APIs).

All real work happens in `lua/token_bucket.lua`. This class is a thin
async wrapper that loads the script once at construction and translates
the Lua return array into a `Decision`.
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


class TokenBucket(BaseAlgorithm):
    name: ClassVar[AlgorithmType] = AlgorithmType.token_bucket

    def __init__(self, redis: RedisClient) -> None:
        super().__init__(redis)
        self._script = load_script(redis, "token_bucket")

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
