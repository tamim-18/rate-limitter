from __future__ import annotations

from typing import cast

import structlog
from aio_pika.abc import AbstractRobustConnection
from fastapi import APIRouter, Request, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rate_limiter.schemas.health import HealthResponse, ServiceHealth

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, response: Response) -> HealthResponse:
    """Ping Redis, Postgres, and RabbitMQ; 503 if any dependency fails."""
    services: list[ServiceHealth] = []
    all_ok = True

    redis_client = cast(Redis[str], request.app.state.redis)
    try:
        pong = await redis_client.ping()
        if pong is not True:
            raise RuntimeError(f"unexpected PING reply: {pong!r}")
        services.append(ServiceHealth(name="redis", status="ok"))
    except Exception as exc:
        all_ok = False
        detail = str(exc)
        services.append(ServiceHealth(name="redis", status="error", detail=detail))
        log.warning("health_redis_failed", error=detail)

    session_factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.session_factory,
    )
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        services.append(ServiceHealth(name="postgres", status="ok"))
    except Exception as exc:
        all_ok = False
        detail = str(exc)
        services.append(ServiceHealth(name="postgres", status="error", detail=detail))
        log.warning("health_postgres_failed", error=detail)

    rabbit = cast(AbstractRobustConnection, request.app.state.rabbit)
    try:
        if rabbit.is_closed:
            raise RuntimeError("connection is closed")
        channel = await rabbit.channel()
        await channel.close()
        services.append(ServiceHealth(name="rabbitmq", status="ok"))
    except Exception as exc:
        all_ok = False
        detail = str(exc)
        services.append(ServiceHealth(name="rabbitmq", status="error", detail=detail))
        log.warning("health_rabbitmq_failed", error=detail)

    body = HealthResponse(status="ok" if all_ok else "degraded", services=services)
    if not all_ok:
        response.status_code = 503
    return body
