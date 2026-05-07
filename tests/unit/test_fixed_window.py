"""Fixed window counter — atomic Lua, tested against a live Redis.

Same testing principles as test_token_bucket.py: real Redis (no fakes,
because the whole point is the atomic Lua execution), small numbers,
short waits.

The boundary-burst flaw (§3.5 of fixed_window.md) is *not* tested as a
bug — it's a documented property of the algorithm. We verify only that
the long-run rate and the per-window cap behave as specified.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rate_limiter.algorithms.base import RuleSpec
from rate_limiter.algorithms.fixed_window import FixedWindow

if TYPE_CHECKING:
    import redis.asyncio as redis


# ---------------------------------------------------------------------------
# Allow / deny basics
# ---------------------------------------------------------------------------


async def test_first_request_allowed_with_full_remaining(
    redis_client: redis.Redis[str],
) -> None:
    """First request in a fresh window: count=1, remaining=C-1."""
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=60)

    decision = await algo.check("fw:test:fresh", rule)

    assert decision.allowed is True
    assert decision.remaining == 9
    assert decision.retry_after_ms == 0


async def test_allows_up_to_capacity_then_denies(redis_client: redis.Redis[str]) -> None:
    """Within one window, the first C requests pass and the next one fails."""
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=5, window_seconds=60)
    key = "fw:test:burst"

    decisions = [await algo.check(key, rule) for _ in range(rule.max_requests)]
    assert all(d.allowed for d in decisions)
    assert [d.remaining for d in decisions] == [4, 3, 2, 1, 0]

    over = await algo.check(key, rule)
    assert over.allowed is False
    assert over.remaining == 0
    assert over.retry_after_ms > 0


async def test_remaining_clamped_at_zero_under_overload(
    redis_client: redis.Redis[str],
) -> None:
    """Counter still INCRs on denied requests; `remaining` must clamp at 0."""
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)
    key = "fw:test:overload"

    for _ in range(10):  # well past capacity
        d = await algo.check(key, rule)
    assert d.allowed is False
    assert d.remaining == 0  # not negative


# ---------------------------------------------------------------------------
# Retry / reset semantics
# ---------------------------------------------------------------------------


async def test_retry_after_equals_reset_minus_now(redis_client: redis.Redis[str]) -> None:
    """For fixed-window, retry-after IS the time until reset (no per-token math)."""
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=1, window_seconds=10)
    key = "fw:test:retry-eq-reset"

    await algo.check(key, rule)  # uses the 1 token
    denied = await algo.check(key, rule)

    assert denied.allowed is False
    # retry_after_ms ≈ reset_at_ms - now; since `now` isn't returned, just
    # verify both are positive and retry_after fits in one window.
    assert 0 < denied.retry_after_ms <= rule.window_seconds * 1000
    assert denied.reset_at_ms > 0


async def test_retry_after_is_zero_when_allowed(redis_client: redis.Redis[str]) -> None:
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=60)

    decision = await algo.check("fw:test:retry-zero", rule)

    assert decision.allowed is True
    assert decision.retry_after_ms == 0


# ---------------------------------------------------------------------------
# Window boundary behavior
# ---------------------------------------------------------------------------


async def test_counter_resets_at_window_boundary(redis_client: redis.Redis[str]) -> None:
    """Exhaust the window, wait past the boundary, fresh window starts at 0.

    W=1s is the smallest window we can use here while still keeping the
    test deterministic (sleep 1.2s to safely cross the boundary).
    """
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=3, window_seconds=1)
    key = "fw:test:boundary"

    for _ in range(rule.max_requests):
        await algo.check(key, rule)
    blocked = await algo.check(key, rule)
    assert blocked.allowed is False

    await asyncio.sleep(1.2)
    after = await algo.check(key, rule)
    assert after.allowed is True
    assert after.remaining == rule.max_requests - 1


# ---------------------------------------------------------------------------
# Isolation and persistence
# ---------------------------------------------------------------------------


async def test_independent_keys_do_not_interfere(redis_client: redis.Redis[str]) -> None:
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=2, window_seconds=60)

    a1 = await algo.check("fw:test:iso:A", rule)
    a2 = await algo.check("fw:test:iso:A", rule)
    a3 = await algo.check("fw:test:iso:A", rule)  # A exhausted

    b1 = await algo.check("fw:test:iso:B", rule)
    b2 = await algo.check("fw:test:iso:B", rule)

    assert (a1.allowed, a2.allowed, a3.allowed) == (True, True, False)
    assert (b1.allowed, b2.allowed) == (True, True)


async def test_ttl_set_to_window_seconds(redis_client: redis.Redis[str]) -> None:
    """The actual storage key (prefix:window_idx) carries TTL ≤ W seconds."""
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=10, window_seconds=5)
    key_prefix = "fw:test:ttl"

    await algo.check(key_prefix, rule)

    # The script appends `:<window_idx>` to the prefix. We don't replicate
    # that math here — just scan keys with the prefix and verify TTL bound.
    matches = [k async for k in redis_client.scan_iter(match=f"{key_prefix}:*")]
    assert len(matches) == 1
    pttl: int = await redis_client.pttl(matches[0])
    expected_ms = rule.window_seconds * 1000
    assert 0 < pttl <= expected_ms


async def test_ttl_not_refreshed_on_subsequent_calls(
    redis_client: redis.Redis[str],
) -> None:
    """Only the first INCR sets EXPIRE; subsequent calls don't push it forward.

    This guarantees the counter dies exactly at the window boundary even
    under continuous load — the property the boundary-reset behavior depends on.
    """
    algo = FixedWindow(redis_client)
    rule = RuleSpec(max_requests=100, window_seconds=10)
    key_prefix = "fw:test:ttl-fixed"

    await algo.check(key_prefix, rule)
    [storage_key] = [k async for k in redis_client.scan_iter(match=f"{key_prefix}:*")]
    pttl_first: int = await redis_client.pttl(storage_key)

    await asyncio.sleep(0.2)
    await algo.check(key_prefix, rule)
    pttl_second: int = await redis_client.pttl(storage_key)

    # If the second INCR refreshed TTL, pttl_second would be ~= pttl_first.
    # We expect it to have ticked DOWN by at least 100ms.
    assert pttl_second < pttl_first - 100
