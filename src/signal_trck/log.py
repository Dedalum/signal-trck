"""structlog setup with run-id correlation + API-key redaction."""

from __future__ import annotations

import logging
import re
import sys
import uuid
from typing import Any, Literal

import structlog

LogFormat = Literal["console", "json"]


# Redact provider API keys if anything ever tries to log them. The CLI / API
# layers should never emit keys to logs, but defense-in-depth + the
# `tests/api/test_api_key_redaction.py` sentinel check pin this behavior.
_KEY_FIELD_RE = re.compile(r"(?i)(API_KEY|TOKEN|SECRET|AUTHORIZATION)$")
_KEY_VALUE_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}")


def _redact_api_keys(
    _logger: object, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redact API-key-shaped values from log records.

    Catches both fields whose names match ``*_API_KEY`` (etc.) and values
    that look like provider keys. Replaces value with ``"***"``.
    """
    for k in list(event_dict.keys()):
        v = event_dict[k]
        if _KEY_FIELD_RE.search(k):
            event_dict[k] = "***"
            continue
        if isinstance(v, str) and _KEY_VALUE_RE.search(v):
            event_dict[k] = _KEY_VALUE_RE.sub("***", v)
    return event_dict


def configure(level: str = "INFO", fmt: LogFormat = "console") -> None:
    """Configure structlog and stdlib logging in one shot.

    Call once near process start. Subsequent calls reset the configuration.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _redact_api_keys,
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
