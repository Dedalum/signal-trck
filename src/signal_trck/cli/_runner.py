"""Async runner shim for Typer commands.

Currently delegates to ``asyncio.run``. The point of having this helper is to
keep all CLI entries calling through one place — when Phase B's FastAPI
handlers need to call into the same engines from an already-running event
loop, this is the single line that gets evolved.

Today's behavior is identical to ``asyncio.run``. Don't add complexity here
until Phase B actually surfaces the need.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")


def run_async(coro: Coroutine[None, None, T]) -> T:
    """Run a coroutine to completion.

    Equivalent to ``asyncio.run(coro)`` today. Future-proofed by being the
    single point of replacement when Phase B introduces FastAPI handlers
    that already own the event loop.
    """
    return asyncio.run(coro)
