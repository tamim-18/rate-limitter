"""Redis and RabbitMQ connection lifecycle (async).

Both initializers fail loud at startup: Redis with PING, RabbitMQ by opening
a probe channel. This surfaces broker-side misconfiguration (wrong vhost,
missing perms) at boot rather than on the first request.

`RedisClient` is the canonical alias used across the app. `redis.Redis` is
generic in the type stubs but NOT at runtime; subscripting it (`Redis[str]`)
in a runtime-evaluable annotation raises TypeError. The TYPE_CHECKING-guarded
alias lets mypy see the parameterized form while runtime sees plain `Redis`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis.asyncio as redis
from aio_pika import connect_robust
from aio_pika.abc import AbstractRobustConnection

if TYPE_CHECKING:
    RedisClient = redis.Redis[str]
else:
    RedisClient = redis.Redis


async def init_redis(redis_url: str) -> RedisClient:
    client: RedisClient = redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()  # type: ignore[attr-defined]
        raise
    return client


async def close_redis(client: RedisClient) -> None:
    await client.aclose()  # type: ignore[attr-defined]


async def init_rabbitmq(url: str) -> AbstractRobustConnection:
    connection = await connect_robust(url)
    try:
        channel = await connection.channel()
        await channel.close()
    except Exception:
        await connection.close()
        raise
    return connection


async def close_rabbitmq(connection: AbstractRobustConnection) -> None:
    await connection.close()
