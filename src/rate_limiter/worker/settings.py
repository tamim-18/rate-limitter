"""ARQ worker settings. Replace noop task with real jobs in P6."""

from arq.connections import RedisSettings

from rate_limiter.config import get_settings


async def noop_task(_ctx: object) -> None:
    """Placeholder until sync / violation tasks are implemented."""
    return None


class WorkerSettings:
    functions = [noop_task]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
