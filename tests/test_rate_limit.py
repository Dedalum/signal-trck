"""Token-bucket rate limiter behavior under contention."""

from __future__ import annotations

import asyncio
import time

import pytest

from signal_trck.adapters._rate_limit import TokenBucket


async def test_acquire_within_capacity_is_instant() -> None:
    bucket = TokenBucket(rate=10, capacity=5)
    start = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, "first N acquires up to capacity should be ~free"


async def test_acquire_beyond_capacity_blocks_for_refill() -> None:
    bucket = TokenBucket(rate=10, capacity=2)
    start = time.monotonic()
    # Drain bucket
    await bucket.acquire()
    await bucket.acquire()
    # Next acquire requires 1 token / 10 tokens-per-second = ~0.1s wait
    await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08, f"expected ≥80ms wait for refill, got {elapsed * 1000:.0f}ms"
    assert elapsed < 0.5, "shouldn't take half a second for one token"


async def test_concurrent_acquires_are_serialized() -> None:
    bucket = TokenBucket(rate=20, capacity=2)

    async def grab() -> float:
        t0 = time.monotonic()
        await bucket.acquire()
        return time.monotonic() - t0

    waits = await asyncio.gather(*(grab() for _ in range(6)))
    # 2 free, then 4 waits of ~50ms each (1/20s = 50ms per token)
    free_count = sum(1 for w in waits if w < 0.02)
    assert free_count == 2, f"expected 2 free acquires, got {free_count}"


def test_rejects_invalid_construction() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=0, capacity=1)
    with pytest.raises(ValueError):
        TokenBucket(rate=10, capacity=0)


async def test_rejects_acquire_above_capacity() -> None:
    bucket = TokenBucket(rate=10, capacity=2)
    with pytest.raises(ValueError):
        await bucket.acquire(3)
