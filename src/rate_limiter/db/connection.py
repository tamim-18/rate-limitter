"""Redis and RabbitMQ connection lifecycle (async).

Both initializers fail loud at startup: Redis with PING, RabbitMQ by opening
a probe channel. This surfaces broker-side misconfiguration (wrong vhost,
missing perms) at boot rather than on the first request.
"""

from __future__ import annotations

import redis.asyncio as redis
from aio_pika import connect_robust
from aio_pika.abc import AbstractRobustConnection


async def init_redis(redis_url: str) -> redis.Redis[str]:
    client: redis.Redis[str] = redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()  # type: ignore[attr-defined]
        raise
    return client


async def close_redis(client: redis.Redis[str]) -> None:
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
