"""Exception handlers mapping domain errors to HTTP responses.

The handler table from §Error handling in the Phase B plan. Stable string
``code`` enums are returned in the response body so the frontend can switch
on them without parsing English error messages.

The narrowed ``OperationalError → 503`` mapping (Decision 19) only catches
genuine "database is locked" / I/O errors; all other ``OperationalError``s
(no such table, syntax error, schema-out-of-date) fall through to 500
because they're code bugs and shouldn't masquerade as transient unavailability.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

import aiosqlite
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from signal_trck.chart_schema import SchemaVersionError
from signal_trck.pair_id import PairIdError
from signal_trck.storage import ChartNotFound, ChartSlugConflict, PairNotFound

log = structlog.get_logger(__name__)

# Match only the "database is locked" / "disk I/O error" forms of
# ``OperationalError``. Everything else (no such table, near-syntax error,
# schema-out-of-date) is a code bug, not a transient infrastructure failure,
# and should surface as 500.
_TRANSIENT_DB_RE = re.compile(r"^(database is locked|disk I/O error)", re.IGNORECASE)


def _err(code: str, detail: str) -> dict[str, Any]:
    return {"detail": detail, "code": code}


def register(app: FastAPI) -> None:
    """Register all domain → HTTP exception handlers on ``app``."""

    @app.exception_handler(PairIdError)
    async def _pair_id_error(_req: Request, exc: PairIdError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_err("INVALID_PAIR_ID", str(exc)))

    @app.exception_handler(PairNotFound)
    async def _pair_not_found(_req: Request, exc: PairNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_err("PAIR_NOT_FOUND", str(exc)))

    @app.exception_handler(ChartNotFound)
    async def _chart_not_found(_req: Request, exc: ChartNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_err("CHART_NOT_FOUND", str(exc)))

    @app.exception_handler(ChartSlugConflict)
    async def _slug_conflict(_req: Request, exc: ChartSlugConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409, content=_err("CHART_SLUG_CONFLICT", str(exc))
        )

    @app.exception_handler(SchemaVersionError)
    async def _schema_mismatch(_req: Request, exc: SchemaVersionError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_err("SCHEMA_MISMATCH", str(exc)))

    @app.exception_handler(aiosqlite.OperationalError)
    async def _db_operational(_req: Request, exc: aiosqlite.OperationalError) -> JSONResponse:
        msg = str(exc)
        if _TRANSIENT_DB_RE.match(msg):
            log.warning("db.transient", error=msg)
            return JSONResponse(status_code=503, content=_err("DB_BUSY", "db unavailable"))
        log.exception("db.bug", error=msg)
        return JSONResponse(status_code=500, content=_err("INTERNAL", "internal error"))

    @app.exception_handler(sqlite3.OperationalError)
    async def _sqlite_operational(_req: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        # aiosqlite re-raises some errors as the stdlib type; same logic.
        msg = str(exc)
        if _TRANSIENT_DB_RE.match(msg):
            log.warning("db.transient", error=msg)
            return JSONResponse(status_code=503, content=_err("DB_BUSY", "db unavailable"))
        log.exception("db.bug", error=msg)
        return JSONResponse(status_code=500, content=_err("INTERNAL", "internal error"))
