"""Leaky bucket — atomic Lua, tested against a live Redis.

Same testing principles as the prior three suites: real Redis, small
numbers, short waits. Because leaky bucket is the dual of token bucket,
the test shape is nearly identical — we substitute "level fills toward C"
for "tokens drain toward 0".
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from rate_limiter.algorithms.base import RuleSpec
from rate_limiter.algorithms.leaky_bucket import LeakyBucket

if TYPE_CHECKING:
    import redis.asyncio as redis


# ---------------------------------------------------------------------------
# Allow / deny basics
# ---------------------------------------------------------------------------


async def test_fresh_bucket_starts_empty(redis_client: redis.Redis[str]) -> None:
    """First-ever request: bucket starts empty, fills to 1, remaining = C-1."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)

    decision = await algo.check("lb:test:fresh", rule)

    assert decision.allowed is True
    assert decision.remaining == 9
    assert decision.retry_after_ms == 0


async def test_allows_up_to_capacity_then_denies(redis_client: redis.Redis[str]) -> None:
    """Burst of capacity+1 → first C allowed (fill 1..C), last denied (would overflow)."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "lb:test:burst"

    decisions = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert all(d.allowed for d in decisions)
    assert [d.remaining for d in decisions] == [4, 3, 2, 1, 0]

    over = await algo.check(key, rule)
    assert over.allowed is False
    assert over.remaining == 0
    assert over.retry_after_ms > 0


async def test_remaining_clamped_at_zero(redis_client: redis.Redis[str]) -> None:
    """Once the bucket is full, repeated denies must keep `remaining = 0`."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)
    key = "lb:test:clamped"

    for _ in range(2):
        await algo.check(key, rule)
    for _ in range(5):
        d = await algo.check(key, rule)
    assert d.allowed is False
    assert d.remaining == 0


# ---------------------------------------------------------------------------
# Retry-after / reset semantics
# ---------------------------------------------------------------------------


async def test_retry_after_ms_is_close_to_one_drain_interval(
    redis_client: redis.Redis[str],
) -> None:
    """Denied right after fill → retry_after ≈ 1 / r_ms.

    For C=10, W=1s → r_ms = 0.01 → ~100ms per drained slot. Allow ±20ms slack.
    """
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=1)
    key = "lb:test:retry-after"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    denied = await algo.check(key, rule)

    assert denied.allowed is False
    expected_ms = 1000 // rule.max_requests
    assert abs(denied.retry_after_ms - expected_ms) <= 20, denied.retry_after_ms


async def test_reset_at_ms_grows_with_fullness(redis_client: redis.Redis[str]) -> None:
    """`reset_at_ms` projects when the bucket fully drains — fuller ⇒ later reset."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)
    key = "lb:test:reset-grows"

    first = await algo.check(key, rule)  # level = 1
    for _ in range(8):
        await algo.check(key, rule)  # level = 9
    last = await algo.check(key, rule)  # level = 10 (full)

    assert first.reset_at_ms < last.reset_at_ms


async def test_retry_after_is_zero_when_allowed(redis_client: redis.Redis[str]) -> None:
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=60)

    decision = await algo.check("lb:test:retry-zero", rule)

    assert decision.allowed is True
    assert decision.retry_after_ms == 0


# ---------------------------------------------------------------------------
# Drain behavior
# ---------------------------------------------------------------------------


async def test_drain_after_wait_allows_again(redis_client: redis.Redis[str]) -> None:
    """Fill → wait one drain interval → next request is allowed.

    C=5, W=1s → r_ms = 0.005 → 1 slot drains in 200ms. Wait 250ms for slack.
    """
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=1)
    key = "lb:test:drain"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    blocked = await algo.check(key, rule)
    assert blocked.allowed is False

    await asyncio.sleep(0.25)
    after_wait = await algo.check(key, rule)
    assert after_wait.allowed is True


async def test_drain_floor_is_zero(redis_client: redis.Redis[str]) -> None:
    """Long idle does not produce extra capacity beyond C.

    Mirror of token bucket's "cap at capacity" test: leak can't go below 0,
    so a long sleep can't grant > C burst on the next round.
    """
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "lb:test:floor"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    await asyncio.sleep(1.5)  # > full window: bucket fully drained (and clamped at 0)

    allowed = 0
    for _ in range(rule.max_requests + 2):
        d = await algo.check(key, rule)
        if d.allowed:
            allowed += 1
        else:
            break
    assert allowed == rule.max_requests


# ---------------------------------------------------------------------------
# Isolation and persistence
# ---------------------------------------------------------------------------


async def test_independent_keys_do_not_interfere(redis_client: redis.Redis[str]) -> None:
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)

    a1 = await algo.check("lb:test:iso:A", rule)
    a2 = await algo.check("lb:test:iso:A", rule)
    a3 = await algo.check("lb:test:iso:A", rule)

    b1 = await algo.check("lb:test:iso:B", rule)
    b2 = await algo.check("lb:test:iso:B", rule)

    assert (a1.allowed, a2.allowed, a3.allowed) == (True, True, False)
    assert (b1.allowed, b2.allowed) == (True, True)


async def test_ttl_set_to_two_windows(redis_client: redis.Redis[str]) -> None:
    """PEXPIRE sets the key TTL to ≤ 2×window_seconds (in ms)."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=5)
    key = "lb:test:ttl"

    await algo.check(key, rule)
    pttl: int = await redis_client.pttl(key)

    expected_ms = rule.window_seconds * 2000  # 10_000
    assert 0 < pttl <= expected_ms
    assert pttl >= expected_ms - 500


async def test_state_persists_across_calls(redis_client: redis.Redis[str]) -> None:
    """A second call sees `level` and `last_drain_ms` from the first."""
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "lb:test:persist"

    await algo.check(key, rule)
    fields = await redis_client.hgetall(key)

    assert "level" in fields
    assert "last_drain_ms" in fields
    assert float(fields["level"]) == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Duality with token bucket (sanity check, not a full equivalence proof)
# ---------------------------------------------------------------------------


async def test_dual_invariant_level_plus_remaining_equals_capacity(
    redis_client: redis.Redis[str],
) -> None:
    """At every moment, level + remaining = capacity (proves the duality holds).

    Reads Redis directly so we see the float `level` rather than the
    floored integer the public API returns.
    """
    algo = LeakyBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "lb:test:dual"

    for _ in range(3):
        d = await algo.check(key, rule)
    fields = await redis_client.hgetall(key)
    level = float(fields["level"])

    assert d.allowed is True
    assert level + d.remaining == pytest.approx(rule.max_requests, abs=0.01)
