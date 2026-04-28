"""structlog setup with run-id correlation."""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Literal

import structlog

LogFormat = Literal["console", "json"]


def configure(level: str = "INFO", fmt: LogFormat = "console") -> None:
    """Configure structlog and stdlib logging in one shot.

    Call once near process start. Subsequent calls reset the configuration.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if fmt == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Mirror stdlib root logger into structlog so library logs flow through.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper()),
    )


def new_run_id() -> str:
    """Short correlation id, suitable for human-readable logs."""
    return uuid.uuid4().hex[:12]


def bind_run(run_id: str | None = None) -> str:
    """Bind a run_id to the contextvars logger context. Returns the id."""
    rid = run_id or new_run_id()
    structlog.contextvars.bind_contextvars(run_id=rid)
    return rid
