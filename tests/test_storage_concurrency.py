"""Concurrent-access tests for the Store.

Exercises the Phase B workload pattern: web request reading the DB while
the CLI writes (or vice-versa), and concurrent compute_or_load calls
racing for the same indicator cache slot.

WAL mode + the atomic ``replace_indicator_rows`` transaction are what
make this safe; these tests prove it. Each test uses **two distinct
Store instances pointing at the same DB file** so we get real
concurrency, not aiosqlite's single-writer serialization within one
connection.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from signal_trck.indicators.cache import compute_or_load
from signal_trck.indicators.params import params_hash
from signal_trck.storage import Store
from signal_trck.storage.models import Candle

PAIR = "test:CON-USD"


@pytest.fixture
async def two_stores(tmp_path: Path) -> AsyncIterator[tuple[Store, Store]]:
    """Two independent Store connections to the same DB file."""
    db = tmp_path / "concurrency.db"
    a = Store(db_path=db)
    b = Store(db_path=db)
    await a.connect()
    await b.connect()
    try:
        # Seed the pair once via either store.
        await a.add_pair(PAIR, "CON", "USD", "test")
        yield a, b
    finally:
        await a.close()
        await b.close()


def _candle(ts: int, close: float = 100.0) -> Candle:
    return Candle(
        pair_id=PAIR,
        interval="1d",
        ts_utc=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000.0,
        source="test",
    )


async def test_concurrent_upsert_candles_converges_to_last_writer(
    two_stores: tuple[Store, Store],
) -> None:
    """Two concurrent upserts of the same (pair_id, interval, ts_utc) must
    leave the row in a valid state — last writer wins, no corruption."""
    store_a, store_b = two_stores
    ts = 1_700_000_000
    candle_a = _candle(ts, close=100.0)
    candle_b = _candle(ts, close=200.0)

    await asyncio.gather(
        store_a.upsert_candles([candle_a]),
        store_b.upsert_candles([candle_b]),
    )

    # Read back via either store.
    rows = await store_a.get_candles(PAIR, "1d")
    assert len(rows) == 1, f"expected exactly one row at ts={ts}, got {len(rows)}"
    # The close price must be one of the two written values (no torn write).
    assert rows[0].close in (100.0, 200.0)
    assert rows[0].ts_utc == ts


async def test_concurrent_compute_or_load_yields_consistent_cache(
    two_stores: tuple[Store, Store],
) -> None:
    """Two concurrent compute_or_load runs for the same params should both
    return identical values, and the final cache state must be consistent
    (one full set of rows, not partially populated from a torn write)."""
    store_a, store_b = two_stores
    base_ts = 1_700_000_000
    await store_a.upsert_candles([_candle(base_ts + i * 86400, close=100 + i) for i in range(40)])

    # Race two compute_or_load calls.
    out_a, out_b = await asyncio.gather(
        compute_or_load(store_a, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}),
        compute_or_load(store_b, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}),
    )

    # Both calls must return the same values (TA-Lib is deterministic; both
    # paths see the same candle data).
    assert (out_a["value"].values == out_b["value"].values).all()

    # Cache state must reflect a complete write — exactly 36 rows for SMA-5
    # on 40 candles (first 4 are NaN warmup).
    h = params_hash({"period": 5})
    cur = await store_a.conn.execute(
        "SELECT COUNT(*) FROM indicator_values WHERE pair_id = ? AND name = ? AND params_hash = ?",
        (PAIR, "SMA", h),
    )
    n = (await cur.fetchone())[0]  # type: ignore[index]
    assert n == 36, f"expected 36 cached rows after concurrent writes, got {n}"


async def test_concurrent_reader_and_writer_see_consistent_state(
    two_stores: tuple[Store, Store],
) -> None:
    """A reader concurrent with a writer must see either pre-write or
    post-write state — never a partial/torn write. WAL mode + a single
    atomic transaction in upsert_candles guarantees this."""
    store_a, store_b = two_stores
    base_ts = 1_700_000_000
    # Seed with 5 candles so there's something to read pre-write.
    await store_a.upsert_candles([_candle(base_ts + i * 86400, close=100 + i) for i in range(5)])

    # Writer adds 20 more candles in one transaction; reader counts in a tight loop.
    new_candles = [_candle(base_ts + i * 86400, close=200 + i) for i in range(5, 25)]

    async def writer() -> None:
        await store_a.upsert_candles(new_candles)

    async def reader() -> set[int]:
        observed: set[int] = set()
        for _ in range(20):
            rows = await store_b.get_candles(PAIR, "1d")
            observed.add(len(rows))
            await asyncio.sleep(0)
        return observed

    _, observed_counts = await asyncio.gather(writer(), reader())
    # Reader should only ever see 5 (pre-write) or 25 (post-write), never anything in between.
    assert observed_counts.issubset({5, 25}), (
        f"reader saw torn-write count(s): {observed_counts - {5, 25}}"
    )

    # Final state is the post-write count.
    final = await store_a.get_candles(PAIR, "1d")
    assert len(final) == 25


async def test_replace_indicator_rows_is_atomic(two_stores: tuple[Store, Store]) -> None:
    """A reader during a replace_indicator_rows operation should see either
    the old set or the new set — never an empty intermediate state."""
    store_a, store_b = two_stores
    h = "abc1234567890def"
    name = "SMA"
    interval = "1d"

    # Seed with the "old" rows.
    old_rows = [(PAIR, interval, name, h, 1_700_000_000 + i * 86400, float(i)) for i in range(10)]
    await store_a.replace_indicator_rows(
        pair_id=PAIR, interval=interval, names=[name], params_hash=h, rows=old_rows
    )

    # New rows replacing the old set.
    new_rows = [
        (PAIR, interval, name, h, 1_700_000_000 + i * 86400, float(i * 2)) for i in range(10)
    ]

    async def writer() -> None:
        await store_a.replace_indicator_rows(
            pair_id=PAIR, interval=interval, names=[name], params_hash=h, rows=new_rows
        )

    async def reader() -> set[int]:
        counts: set[int] = set()
        for _ in range(20):
            got = await store_b.get_indicator_rows(
                pair_id=PAIR, interval=interval, names=[name], params_hash=h
            )
            counts.add(len(got.get(name, [])))
            await asyncio.sleep(0)
        return counts

    _, observed = await asyncio.gather(writer(), reader())
    # Reader should never see 0 rows (the empty state between delete and insert
    # if the transaction were not atomic).
    assert 0 not in observed, f"reader saw atomically-zero state: {observed}"
    # Should see only 10 (either old or new — we don't care which).
    assert observed.issubset({10}), f"unexpected counts during replace: {observed}"


async def test_ai_run_audit_concurrent_writes(two_stores: tuple[Store, Store]) -> None:
    """Multiple ``write_ai_run`` calls in flight must each persist a distinct
    row (auto-increment run_id is the contract)."""
    store_a, store_b = two_stores
    base = int(time.time())

    async def write_one(store: Store, slug: str, t: int) -> int:
        return await store.write_ai_run(
            pair_id=PAIR,
            chart_slug=slug,
            provider="anthropic",
            model="m",
            prompt_template_version="v1",
            system_prompt_hash="h",
            context_file_sha256=None,
            context_preview=None,
            sr_candidates_presented_json=json.dumps([]),
            sr_candidates_selected_json=json.dumps([]),
            ran_at=t,
        )

    run_ids = await asyncio.gather(
        write_one(store_a, "chart-c1", base + 1),
        write_one(store_b, "chart-c2", base + 2),
        write_one(store_a, "chart-c3", base + 3),
    )
    assert len(set(run_ids)) == 3, f"expected 3 distinct run_ids, got {run_ids}"
    assert all(r > 0 for r in run_ids)

    runs = await store_a.list_ai_runs(PAIR)
    assert len(runs) == 3
