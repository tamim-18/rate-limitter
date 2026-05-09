"""Leaky bucket (meter formulation) — dual of token bucket.

`level` counts how full the bucket is (0 ≤ level ≤ capacity); each request
adds 1 unit; the bucket leaks at `r = capacity / window` units per second.
A request is denied if it would push the level past capacity.

Mathematically equivalent to token bucket (`level = capacity − tokens`),
kept as its own algorithm for the Strategy-pattern demonstration and
because some operational vocabularies natively think in fill/drain terms.

The classic *queue* formulation of leaky bucket — buffer requests, drain
them at constant rate — is deliberately not used here. See
`leaky_bucket.md` §3.8 for why.
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


class LeakyBucket(BaseAlgorithm):
    name: ClassVar[AlgorithmType] = AlgorithmType.leaky_bucket

    def __init__(self, redis: RedisClient) -> None:
        super().__init__(redis)
        self._script = load_script(redis, "leaky_bucket")

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
