from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ServiceStatus = Literal["ok", "error"]
OverallStatus = Literal["ok", "degraded"]


class ServiceHealth(BaseModel):
    name: str
    status: ServiceStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    status: OverallStatus
    services: list[ServiceHealth]
