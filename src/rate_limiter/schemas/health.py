from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceHealth(BaseModel):
    name: str
    status: str = Field(description='"ok" or "error"')
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(description='"ok" if all dependencies healthy')
    services: list[ServiceHealth]
