"""Redis and RabbitMQ connection lifecycle (async)."""

from __future__ import annotations

import redis.asyncio as redis
from aio_pika import connect_robust
from aio_pika.abc import AbstractRobustConnection


async def init_redis(redis_url: str) -> redis.Redis[str]:
    client = redis.from_url(
        redis_url,
        decode_responses=True,
    )
    await client.ping()
    return client


async def close_redis(client: redis.Redis[str]) -> None:
    await client.close()


async def init_rabbitmq(url: str) -> AbstractRobustConnection:
    connection = await connect_robust(url)
    return connection


async def close_rabbitmq(connection: AbstractRobustConnection) -> None:
    await connection.close()
