"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, cast

from aio_pika.abc import AbstractRobustConnection
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.session_factory,
    )
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


def get_redis(request: Request) -> Redis[str]:
    return cast(Redis[str], request.app.state.redis)


def get_rabbit_connection(request: Request) -> AbstractRobustConnection:
    return cast(AbstractRobustConnection, request.app.state.rabbit)


RedisDep = Annotated[Redis[str], Depends(get_redis)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
RabbitDep = Annotated[AbstractRobustConnection, Depends(get_rabbit_connection)]
