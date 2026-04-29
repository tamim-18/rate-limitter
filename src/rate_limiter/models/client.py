"""Client model — issued API keys, mapped to a tier."""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum as SqlaEnum
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rate_limiter.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ClientTier(enum.StrEnum):
    free = "free"
    pro = "pro"
    enterprise = "enterprise"


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clients"

    api_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[ClientTier] = mapped_column(
        SqlaEnum(ClientTier, name="client_tier"), nullable=False
    )
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
