"""FastAPI app for signal-trck Phase B web UI.

Module-level ``app`` (no ``build_app()`` factory per Decision 13).
Tests use ``httpx.AsyncClient(transport=ASGITransport(app=app))`` with a
``Store`` injected via dependency override.

Per Decision 15: no ``request_id`` middleware. Single user, localhost,
nothing to correlate. The structured access log lives inline below as a
~15-line ASGI middleware.

CORS allow-list ``localhost:5173`` is enabled only when ``SIGNAL_TRCK_DEV=1``
in the environment (Vite dev server). Prod mode (no env var) serves the
frontend assets from the same origin and disables CORS entirely.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from signal_trck import log as log_mod
from signal_trck.api import errors
from signal_trck.api.routes import router
from signal_trck.storage import Store

log = structlog.get_logger(__name__)


# --- Lifespan ---


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open a Store on startup, close on shutdown.

    Tests bypass this by setting ``app.state.store`` directly before
    ``ASGITransport`` boots the app — see ``tests/api/conftest.py``.
    """
    if not getattr(app.state, "store", None):
        store = Store()
        await store.connect()
        app.state.store = store
        app.state._owns_store = True
    else:
        app.state._owns_store = False
    try:
        yield
    finally:
        if getattr(app.state, "_owns_store", False):
            await app.state.store.close()


app = FastAPI(
    title="signal-trck",
    version="0.1.0",
    lifespan=_lifespan,
    # Stable JSON dump format for diffability — matches chart_io behavior.
)


# --- Access-log middleware (inline, per Decision 13/15) ---


class _AccessLogMiddleware:
    """One log line per HTTP request: method, path, status, duration_ms.

    Slow requests (> 1s) get a ``slow=True`` flag for grep-ability.
    """

    def __init__(self, inner: ASGIApp) -> None:
        self._inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 0}

        async def _wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
            await send(message)

        try:
            await self._inner(scope, receive, _wrapped_send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            status = status_holder["status"]
            slow = duration_ms > 1000.0
            log.info(
                "http.request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                duration_ms=round(duration_ms, 2),
                slow=slow,
            )


app.add_middleware(_AccessLogMiddleware)


# --- CORS (dev-only) ---


if os.environ.get("SIGNAL_TRCK_DEV") == "1":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- Routes + error handlers ---


app.include_router(router)
errors.register(app)


# --- Bootstrap log config when imported ---


def _ensure_logging() -> None:
    """Configure structlog if it hasn't been touched yet.

    The CLI configures structlog explicitly; if the API is imported in a
    different context (tests, ``uvicorn`` directly), we still want a sane
    default. Idempotent — safe to call multiple times.
    """
    log_mod.configure(level="INFO", fmt="console")


_ensure_logging()
