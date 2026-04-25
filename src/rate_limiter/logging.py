from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import structlog.typing


def configure_logging(*, log_level: str, json_logs: bool) -> None:
    """Structured logging: JSON in production, console in development."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    timestamper: structlog.typing.Processor = structlog.processors.TimeStamper(
        fmt="iso",
        utc=True,
        key="timestamp",
    )
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]
    if json_logs:
        processors: list[structlog.typing.Processor] = [
            *shared,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            *shared,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
