"""Async token-bucket rate limiter for adapter HTTP calls."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Token-bucket rate limiter.

    Tokens accumulate at ``rate`` per second up to ``capacity``. ``acquire``
    blocks until enough tokens are available, then debits them.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._rate = rate
        self._capacity = capacity
        self._tokens: float = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int = 1) -> None:
        if n <= 0:
            return
        if n > self._capacity:
            raise ValueError(f"requested {n} tokens > capacity {self._capacity}")
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(float(self._capacity), self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                wait = deficit / self._rate
            await asyncio.sleep(wait)
