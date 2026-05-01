"""Algorithm contracts — the package-extractable boundary.

Nothing in this module imports from `rate_limiter.config`, `rate_limiter.models`,
or fastapi. Algorithms speak only to a Redis client and a `RuleSpec` value
object. This is the seam along which the algorithm layer can later be lifted
into its own pip package without rewriting.

`Decision` is intentionally a frozen dataclass with `slots=True`: it is
allocated once per request on the hot path, and the cost of pydantic
validation is unjustifiable for an internal value type.

Time is sourced from Redis (`redis.call('TIME')`) inside Lua, never passed
in from Python. With multiple API replicas, even ~50ms of clock skew
breaks sliding-window correctness; centralizing time on the single-threaded
Redis instance removes the failure mode entirely.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from redis.asyncio import Redis

    RedisClient = Redis[str]
else:
    RedisClient = "Redis"


class AlgorithmType(enum.StrEnum):
    """Mirrors `models.Algorithm` but kept independent for package-extraction.

    The middleware translates the ORM enum to this one; algorithms never see
    SQLAlchemy types.
    """

    token_bucket = "token_bucket"
    fixed_window = "fixed_window"
    sliding_window_log = "sliding_window_log"
    leaky_bucket = "leaky_bucket"


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Minimum information an algorithm needs to evaluate a request.

    Decoupled from `models.RateLimitRule` so the algorithms layer has no
    SQLAlchemy dependency. The middleware constructs this on each request
    after looking up the rule (from Redis cache, falling back to Postgres).
    """

    max_requests: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of one rate-limit check.

    `retry_after_ms` is 0 when `allowed` is True. `reset_at_ms` is when the
    bucket fully recovers — used for the `X-RateLimit-Reset` header.
    """

    allowed: bool
    remaining: int
    retry_after_ms: int
    reset_at_ms: int


class BaseAlgorithm(ABC):
    """Contract every algorithm implements.

    Subclasses register their `AlgorithmType` via the `name` ClassVar so the
    factory can map enum → class without an import-time registry decorator.
    """

    name: ClassVar[AlgorithmType]

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    @abstractmethod
    async def check(self, key: str, rule: RuleSpec) -> Decision:
        """Evaluate one request against `rule` for `key`. Atomic via Lua."""
