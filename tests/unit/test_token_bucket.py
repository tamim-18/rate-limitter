"""Token bucket — atomic Lua, tested against a live Redis.

We deliberately do not mock Redis. The whole correctness argument is
"the script runs atomically inside Redis," which means a fake or in-process
substitute (which doesn't run Lua, or runs it differently) would test the
mock, not the algorithm.

Conventions:
- One key per test, prefixed `tb:test:<name>` to keep failures easy to
  attribute when manually inspecting Redis.
- Every test uses small, easy-to-eyeball numbers (capacity 5–10, windows
  in the 1–60s range). Real load behavior belongs in tests/load/.
- Time-based tests use the smallest sleep that still proves the property,
  to keep the suite fast.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from rate_limiter.algorithms.base import RuleSpec
from rate_limiter.algorithms.token_bucket import TokenBucket

if TYPE_CHECKING:
    import redis.asyncio as redis


# ---------------------------------------------------------------------------
# Allow / deny basics
# ---------------------------------------------------------------------------


async def test_fresh_bucket_starts_full(redis_client: redis.Redis[str]) -> None:
    """First-ever request for a key: bucket is created full, request allowed."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)

    decision = await algo.check("tb:test:fresh", rule)

    assert decision.allowed is True
    assert decision.remaining == 9  # capacity - 1
    assert decision.retry_after_ms == 0


async def test_allows_up_to_capacity_then_denies(redis_client: redis.Redis[str]) -> None:
    """Burst of capacity+1 requests: first C allowed, last denied."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "tb:test:burst"

    decisions = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert all(d.allowed for d in decisions), "first C requests should all pass"
    assert [d.remaining for d in decisions] == [4, 3, 2, 1, 0]

    over = await algo.check(key, rule)
    assert over.allowed is False
    assert over.remaining == 0
    assert over.retry_after_ms > 0


# ---------------------------------------------------------------------------
# Retry-after / reset semantics
# ---------------------------------------------------------------------------


async def test_retry_after_ms_is_close_to_one_token_interval(
    redis_client: redis.Redis[str],
) -> None:
    """When denied immediately after exhausting, retry_after ≈ 1 / r_ms.

    For C=10, W=1s → r_ms = 0.01 → one token regenerates in ~100ms.
    Allow ±20ms slack for Lua's TIME granularity and integer rounding.
    """
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=1)
    key = "tb:test:retry-after"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    denied = await algo.check(key, rule)

    assert denied.allowed is False
    expected_ms = 1000 // rule.max_requests  # 100ms
    assert abs(denied.retry_after_ms - expected_ms) <= 20, denied.retry_after_ms


async def test_reset_at_ms_grows_with_depletion(redis_client: redis.Redis[str]) -> None:
    """`reset_at_ms` is when the bucket fully refills — bigger gap when emptier."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)
    key = "tb:test:reset-grows"

    first = await algo.check(key, rule)  # 9 left
    for _ in range(8):
        await algo.check(key, rule)  # 1 left
    last = await algo.check(key, rule)  # 0 left

    # Both reset projections should be in the future, and the empty bucket's
    # projection must be strictly later than the nearly-full one's.
    assert first.reset_at_ms < last.reset_at_ms
    assert last.reset_at_ms - first.reset_at_ms > 0


async def test_retry_after_is_zero_when_allowed(redis_client: redis.Redis[str]) -> None:
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=60)

    decision = await algo.check("tb:test:retry-zero", rule)

    assert decision.allowed is True
    assert decision.retry_after_ms == 0


# ---------------------------------------------------------------------------
# Refill behavior
# ---------------------------------------------------------------------------


async def test_refill_after_wait_allows_again(redis_client: redis.Redis[str]) -> None:
    """Exhaust → wait one token's worth → next request is allowed.

    C=5, W=1s → r_ms = 0.005 → 1 token in 200ms. Wait 250ms for slack.
    """
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=1)
    key = "tb:test:refill"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    blocked = await algo.check(key, rule)
    assert blocked.allowed is False

    await asyncio.sleep(0.25)
    after_wait = await algo.check(key, rule)
    assert after_wait.allowed is True


async def test_refill_caps_at_capacity(redis_client: redis.Redis[str]) -> None:
    """Long idle does not give more than `capacity` tokens.

    Drain the bucket, sleep well past one full window, then verify that
    capacity (and not capacity+anything) is the most we can consume in
    the next burst before being denied.
    """
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "tb:test:cap"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    await asyncio.sleep(1.5)  # > full window: bucket fully refilled (and clamped)

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
    """Two clients (different keys) maintain independent buckets."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)

    a1 = await algo.check("tb:test:iso:A", rule)
    a2 = await algo.check("tb:test:iso:A", rule)
    a3 = await algo.check("tb:test:iso:A", rule)  # A exhausted

    b1 = await algo.check("tb:test:iso:B", rule)  # B unaffected
    b2 = await algo.check("tb:test:iso:B", rule)

    assert (a1.allowed, a2.allowed, a3.allowed) == (True, True, False)
    assert (b1.allowed, b2.allowed) == (True, True)


async def test_ttl_set_to_two_windows(redis_client: redis.Redis[str]) -> None:
    """PEXPIRE sets the key TTL to ~2×window_seconds (in ms)."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=5)
    key = "tb:test:ttl"

    await algo.check(key, rule)
    pttl: int = await redis_client.pttl(key)

    expected_ms = rule.window_seconds * 2000  # 10_000
    assert 0 < pttl <= expected_ms
    assert pttl >= expected_ms - 500  # allow 0.5s for time between call & assert


async def test_state_persists_across_calls(redis_client: redis.Redis[str]) -> None:
    """A second call sees the state written by the first (the hash exists)."""
    algo = TokenBucket(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "tb:test:persist"

    await algo.check(key, rule)
    fields = await redis_client.hgetall(key)

    assert "tokens" in fields
    assert "last_refill_ms" in fields
    assert float(fields["tokens"]) == pytest.approx(4.0, abs=0.01)
