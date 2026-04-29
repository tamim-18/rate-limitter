"""ORM models — re-exported so Alembic autogenerate sees every table.

Importing `Base` alone is not enough; each model must be imported so its
`__tablename__` is registered on `Base.metadata`. Keep this file as the
single import surface for migrations and tests.
"""

from rate_limiter.models.base import Base
from rate_limiter.models.client import Client, ClientTier
from rate_limiter.models.rule import Algorithm, RateLimitRule
from rate_limiter.models.violation import Violation

__all__ = [
    "Algorithm",
    "Base",
    "Client",
    "ClientTier",
    "RateLimitRule",
    "Violation",
]
