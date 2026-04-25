from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from rate_limiter.api.health import router as health_router
from rate_limiter.config import get_settings
from rate_limiter.db import create_engine, create_session_factory, dispose_engine
from rate_limiter.db.connection import close_rabbitmq, close_redis, init_rabbitmq, init_redis
from rate_limiter.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_logs=settings.json_logs)
    log.info("app_starting", environment=settings.environment)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    redis_client = await init_redis(settings.redis_url)
    rabbit = await init_rabbitmq(settings.rabbitmq_url)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    app.state.rabbit = rabbit

    try:
        yield
    finally:
        log.info("app_shutting_down")
        await close_rabbitmq(rabbit)
        await close_redis(redis_client)
        await dispose_engine(engine)
        log.info("app_stopped")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    app = FastAPI(
        title="Rate Limiter",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.include_router(health_router)
    return app


app = create_app()
