"""Lua source loader.

Each algorithm owns one Lua script. We read the file once at algorithm
construction and hand it to `redis.register_script()`, which returns an
`AsyncScript` object that transparently handles EVALSHA → EVAL fallback
(if Redis evicts the script cache, the first EVALSHA fails with NOSCRIPT
and redis-py retries with EVAL automatically).

Files live next to the package as `src/rate_limiter/lua/<name>.lua`. We
resolve via `importlib.resources` rather than `__file__` so this works
identically when installed as a wheel and when run from a source tree —
important for the eventual extraction into a pip package.
"""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from redis.commands.core import AsyncScript

    RedisClient = Redis[str]


def load_script(redis: RedisClient, name: str) -> AsyncScript:
    """Read `lua/<name>.lua` and register it with `redis`.

    Raises `FileNotFoundError` at startup if the source is missing — better
    to fail loudly during app boot than at the first request.
    """
    source = (files("rate_limiter.lua") / f"{name}.lua").read_text(encoding="utf-8")
    script: AsyncScript = redis.register_script(source)
    return script
