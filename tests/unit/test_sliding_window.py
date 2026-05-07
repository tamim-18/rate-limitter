"""Sliding window log — atomic Lua, tested against a live Redis.

Same testing principles as the other algorithm tests: real Redis (the
whole point is the atomic ZSET pipeline), small numbers, short waits.

The defining property — `count_in_any_W_seconds ≤ C` — is the headline
test (`test_no_boundary_burst`), since this is the algorithm's reason
for existing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rate_limiter.algorithms.base import RuleSpec
from rate_limiter.algorithms.sliding_window_log import SlidingWindowLog

if TYPE_CHECKING:
    import redis.asyncio as redis


# ---------------------------------------------------------------------------
# Allow / deny basics
# ---------------------------------------------------------------------------


async def test_first_request_allowed_with_full_remaining(
    redis_client: redis.Redis[str],
) -> None:
    """Empty log → first request adds entry 1, remaining = C-1."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)

    decision = await algo.check("swl:test:fresh", rule)

    assert decision.allowed is True
    assert decision.remaining == 9
    assert decision.retry_after_ms == 0


async def test_allows_up_to_capacity_then_denies(redis_client: redis.Redis[str]) -> None:
    """First C requests stored, the C+1-th denied."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "swl:test:burst"

    decisions = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert all(d.allowed for d in decisions)
    assert [d.remaining for d in decisions] == [4, 3, 2, 1, 0]

    over = await algo.check(key, rule)
    assert over.allowed is False
    assert over.remaining == 0
    assert over.retry_after_ms > 0


async def test_denied_requests_do_not_grow_the_log(
    redis_client: redis.Redis[str],
) -> None:
    """Unlike fixed-window, sliding-log MUST NOT add denied requests.

    Adding a denied request would push the next call's count to C+1 and
    keep it there forever — silently breaking the rate guarantee.
    """
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)
    key = "swl:test:no-add-on-deny"

    for _ in range(2):
        await algo.check(key, rule)
    for _ in range(20):  # hammer it well past capacity
        await algo.check(key, rule)

    zcard: int = await redis_client.zcard(key)
    assert zcard == rule.max_requests  # log size never exceeds C


# ---------------------------------------------------------------------------
# The defining property
# ---------------------------------------------------------------------------


async def test_no_boundary_burst(redis_client: redis.Redis[str]) -> None:
    """No W-second interval ever contains more than C allowed requests.

    Setup that would break fixed-window: send C requests, wait a tiny bit,
    send C more right after the half-window mark. Sliding-log must deny
    the second batch because they fall inside the same rolling window as
    the first batch.

    C=3, W=1s. Burst at t=0, attempt second burst at t=0.5s. Total time
    span < W → second batch must be denied.
    """
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "swl:test:no-boundary-burst"

    first = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert all(d.allowed for d in first)

    await asyncio.sleep(0.5)

    second = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert not any(d.allowed for d in second), (
        "sliding-log must deny inside any rolling W-second slice"
    )


# ---------------------------------------------------------------------------
# Sliding behavior
# ---------------------------------------------------------------------------


async def test_old_entries_age_out(redis_client: redis.Redis[str]) -> None:
    """After waiting > W, all prior entries are pruned and the log is empty."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "swl:test:age-out"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)

    await asyncio.sleep(1.2)  # > W: every entry now older than cutoff

    after = await algo.check(key, rule)
    assert after.allowed is True
    assert after.remaining == rule.max_requests - 1


async def test_partial_recovery(redis_client: redis.Redis[str]) -> None:
    """One slot opens up exactly when the oldest entry ages out, not before."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "swl:test:partial"

    await algo.check(key, rule)  # oldest, will expire first
    await asyncio.sleep(0.3)
    await algo.check(key, rule)
    await algo.check(key, rule)
    blocked = await algo.check(key, rule)
    assert blocked.allowed is False

    # Wait until the FIRST entry ages out (~0.7s remaining), but not the
    # rest. One slot should open.
    await asyncio.sleep(0.8)
    one_slot = await algo.check(key, rule)
    assert one_slot.allowed is True

    # The next one should be denied — only one slot opened, we just used it.
    again_blocked = await algo.check(key, rule)
    assert again_blocked.allowed is False


# ---------------------------------------------------------------------------
# Retry / reset semantics
# ---------------------------------------------------------------------------


async def test_retry_after_points_to_oldest_expiry(
    redis_client: redis.Redis[str],
) -> None:
    """retry_after_ms ≈ (oldest + W) - now, bounded by W."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=10)
    key = "swl:test:retry-after"

    await algo.check(key, rule)
    await algo.check(key, rule)
    denied = await algo.check(key, rule)

    assert denied.allowed is False
    # Oldest entry was added moments ago → retry_after ≈ 10s, comfortably
    # within (0, W*1000].
    assert 0 < denied.retry_after_ms <= rule.window_seconds * 1000
    # And not absurdly small either — should be at least most of the window.
    assert denied.retry_after_ms > rule.window_seconds * 1000 * 0.8


async def test_retry_after_is_zero_when_allowed(redis_client: redis.Redis[str]) -> None:
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=60)

    decision = await algo.check("swl:test:retry-zero", rule)

    assert decision.allowed is True
    assert decision.retry_after_ms == 0


# ---------------------------------------------------------------------------
# Isolation and persistence
# ---------------------------------------------------------------------------


async def test_independent_keys_do_not_interfere(redis_client: redis.Redis[str]) -> None:
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)

    a1 = await algo.check("swl:test:iso:A", rule)
    a2 = await algo.check("swl:test:iso:A", rule)
    a3 = await algo.check("swl:test:iso:A", rule)

    b1 = await algo.check("swl:test:iso:B", rule)
    b2 = await algo.check("swl:test:iso:B", rule)

    assert (a1.allowed, a2.allowed, a3.allowed) == (True, True, False)
    assert (b1.allowed, b2.allowed) == (True, True)


async def test_ttl_set_to_window(redis_client: redis.Redis[str]) -> None:
    """PEXPIRE sets TTL = W·1000 and refreshes on every call."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=5)
    key = "swl:test:ttl"

    await algo.check(key, rule)
    pttl_first: int = await redis_client.pttl(key)

    await asyncio.sleep(0.2)
    await algo.check(key, rule)
    pttl_second: int = await redis_client.pttl(key)

    expected_ms = rule.window_seconds * 1000
    assert 0 < pttl_first <= expected_ms
    # The second call should have refreshed the TTL: not significantly less
    # than the first read despite 200ms elapsing.
    assert pttl_second >= pttl_first - 50


async def test_unique_members_within_one_call_path(
    redis_client: redis.Redis[str],
) -> None:
    """Many rapid allows produce that many ZSET entries (no member collisions)."""
    algo = SlidingWindowLog(redis_client)
    rule = RuleSpec(max_requests=20, window_seconds=60)
    key = "swl:test:unique-members"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)

    zcard: int = await redis_client.zcard(key)
    assert zcard == rule.max_requests
