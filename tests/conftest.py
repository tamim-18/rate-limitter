"""Shared pytest configuration.

`redis_client` is the only cross-cutting fixture so far: a connected
async Redis client backed by a live server (DB 15 to keep the test
namespace away from dev data on a shared local instance). The whole
fixture skips gracefully when Redis is unreachable so `make test-unit`
on a laptop with no services running degrades to "skipped", not "errored".

`asyncio_mode = "auto"` is set in pyproject.toml.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
import redis.asyncio as redis

if TYPE_CHECKING:
    RedisClient = redis.Redis[str]
else:
    RedisClient = redis.Redis

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture(loop_scope="function")
async def redis_client() -> AsyncIterator[RedisClient]:
    """Live Redis client, flushed before each test.

    Skips the test (rather than failing) if no Redis is reachable, so unit
    tests that don't touch Redis still pass on a bare machine.
    """
    client: RedisClient = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()  # type: ignore[attr-defined]
        pytest.skip(f"Redis not reachable at {TEST_REDIS_URL}: {exc}")
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()  # type: ignore[attr-defined]
