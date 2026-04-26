"""FastAPI dependency providers.

Connections (engine, session factory, redis client, rabbit connection) are
created once in the lifespan and stashed on `app.state`. These providers
read from `app.state` per request — no module-level singletons, no global
state, fully overridable in tests via `app.dependency_overrides`.

Transaction policy: `get_db` opens a session and auto-rolls back on
exception, but does NOT auto-commit. Services own transaction boundaries
explicitly (`await session.commit()`). This keeps reads side-effect-free,
lets multi-service operations share one transaction, and matches the
service-layer-owns-data-access rule.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, cast

from aio_pika.abc import AbstractRobustConnection
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rate_limiter.config import Settings, get_settings
from rate_limiter.db.connection import RedisClient


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.session_factory,
    )
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


def get_redis(request: Request) -> RedisClient:
    return cast(RedisClient, request.app.state.redis)


def get_rabbit_connection(request: Request) -> AbstractRobustConnection:
    return cast(AbstractRobustConnection, request.app.state.rabbit)


RedisDep = Annotated[RedisClient, Depends(get_redis)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
RabbitDep = Annotated[AbstractRobustConnection, Depends(get_rabbit_connection)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
