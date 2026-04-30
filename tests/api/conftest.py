"""Test fixtures for the FastAPI surface.

Wires an isolated ``Store`` into ``app.state`` before each test so the
lifespan handler doesn't open a second connection against the user's real
DB. Tests use ``httpx.AsyncClient(transport=ASGITransport(app=app))``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from signal_trck.api.app import app
from signal_trck.storage import Store


@pytest.fixture
async def api_store(tmp_path: Path) -> AsyncIterator[Store]:
    """Per-test Store wired onto the FastAPI app state."""
    db_path = tmp_path / "api-test.db"
    store = Store(db_path=db_path)
    await store.connect()
    app.state.store = store
    try:
        yield store
    finally:
        await store.close()
        # Drop the reference so the next test gets a fresh wire-up.
        if hasattr(app.state, "store"):
            del app.state.store


@pytest.fixture
async def client(api_store: Store) -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
