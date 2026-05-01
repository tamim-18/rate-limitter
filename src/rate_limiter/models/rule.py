"""Rate limit rule — (tier, endpoint) → algorithm + limit + window.

`endpoint = NULL` means a tier-wide default applied when no per-endpoint
rule exists. `UNIQUE(tier, endpoint)` keeps the lookup key unambiguous.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SqlaEnum
from sqlalchemy.orm import Mapped, mapped_column

from rate_limiter.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from rate_limiter.models.client import ClientTier


class Algorithm(enum.StrEnum):
    token_bucket = "token_bucket"
    fixed_window = "fixed_window"
    sliding_window_log = "sliding_window_log"
    leaky_bucket = "leaky_bucket"


class RateLimitRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rate_limit_rules"
    __table_args__ = (
        UniqueConstraint(
            "tier",
            "endpoint",
            name="uq_rate_limit_rules_tier_endpoint",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("max_requests > 0", name="max_requests_positive"),
        CheckConstraint("window_seconds > 0", name="window_seconds_positive"),
    )

    tier: Mapped[ClientTier] = mapped_column(
        SqlaEnum(ClientTier, name="client_tier", create_type=False), nullable=False
    )
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    algorithm: Mapped[Algorithm] = mapped_column(
        SqlaEnum(Algorithm, name="algorithm"), nullable=False
    )
    max_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
