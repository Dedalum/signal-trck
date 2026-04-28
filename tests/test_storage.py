"""Store: schema migration + pair + candle CRUD."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from signal_trck.storage import Store
from signal_trck.storage.models import Candle


async def test_migrations_run_to_latest(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    async with Store.open(db_path=db) as store:
        cur = await store.conn.execute("SELECT version FROM schema_version ORDER BY version")
        rows = await cur.fetchall()
        assert [r[0] for r in rows] == [1]


async def test_migrations_idempotent_on_reopen(tmp_path: Path) -> None:
    db = tmp_path / "ro.db"
    async with Store.open(db_path=db):
        pass
    async with Store.open(db_path=db) as store:
        cur = await store.conn.execute("SELECT COUNT(*) FROM schema_version")
        n = (await cur.fetchone())[0]  # type: ignore[index]
        assert n == 1, "reopening should not re-apply migrations"


async def test_add_pair_idempotent(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    pairs = await store.list_pairs()
    assert len(pairs) == 1
    assert pairs[0].pair_id == "coinbase:BTC-USD"


async def test_pin_and_list_order(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    await store.add_pair("coinbase:ETH-USD", "ETH", "USD", "coinbase")
    await store.add_pair("coinbase:SOL-USD", "SOL", "USD", "coinbase", is_pinned=True)
    pairs = await store.list_pairs()
    assert pairs[0].pair_id == "coinbase:SOL-USD"
    assert pairs[0].is_pinned is True


async def test_get_pair_returns_none_for_unknown(store: Store) -> None:
    assert await store.get_pair("coinbase:UNKNOWN-USD") is None


async def test_set_pinned_context(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    await store.set_pinned_context("coinbase:BTC-USD", "/tmp/thesis.md")
    p = await store.get_pair("coinbase:BTC-USD")
    assert p is not None
    assert p.pinned_context_path == "/tmp/thesis.md"


async def test_upsert_candles_replaces_on_conflict(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    ts = int(time.time())
    c1 = Candle("coinbase:BTC-USD", "1d", ts, 100.0, 110.0, 95.0, 105.0, 1000.0, "coinbase")
    n1 = await store.upsert_candles([c1])
    assert n1 == 1

    # Same key, different prices — should replace, not insert.
    c2 = Candle("coinbase:BTC-USD", "1d", ts, 200.0, 210.0, 195.0, 205.0, 2000.0, "coinbase")
    await store.upsert_candles([c2])
    assert await store.candle_count("coinbase:BTC-USD", "1d") == 1
    rows = await store.get_candles("coinbase:BTC-USD", "1d")
    assert rows[0].close == 205.0


async def test_get_candles_range_filter(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    base_ts = 1_700_000_000
    candles = [
        Candle("coinbase:BTC-USD", "1d", base_ts + i * 86400, 100, 110, 95, 105, 1000, "coinbase")
        for i in range(10)
    ]
    await store.upsert_candles(candles)

    mid = await store.get_candles(
        "coinbase:BTC-USD",
        "1d",
        start_ts=base_ts + 3 * 86400,
        end_ts=base_ts + 6 * 86400,
    )
    assert len(mid) == 4
    assert mid[0].ts_utc == base_ts + 3 * 86400
    assert mid[-1].ts_utc == base_ts + 6 * 86400


async def test_latest_candle_ts(store: Store) -> None:
    await store.add_pair("coinbase:BTC-USD", "BTC", "USD", "coinbase")
    assert await store.latest_candle_ts("coinbase:BTC-USD", "1d") is None
    base_ts = 1_700_000_000
    await store.upsert_candles(
        [
            Candle("coinbase:BTC-USD", "1d", base_ts + i * 86400, 1, 1, 1, 1, 1, "coinbase")
            for i in range(3)
        ]
    )
    latest = await store.latest_candle_ts("coinbase:BTC-USD", "1d")
    assert latest == base_ts + 2 * 86400


async def test_wal_mode_enabled(store: Store) -> None:
    cur = await store.conn.execute("PRAGMA journal_mode")
    mode = (await cur.fetchone())[0]  # type: ignore[index]
    assert mode == "wal"


async def test_foreign_keys_enabled(store: Store) -> None:
    cur = await store.conn.execute("PRAGMA foreign_keys")
    on = (await cur.fetchone())[0]  # type: ignore[index]
    assert on == 1


async def test_candle_insert_without_pair_violates_fk(store: Store) -> None:
    """Schema sanity: candles require a parent pair row."""
    import aiosqlite

    c = Candle("coinbase:NOPE-USD", "1d", 1_700_000_000, 1, 1, 1, 1, 1, "coinbase")
    with pytest.raises(aiosqlite.IntegrityError):
        await store.upsert_candles([c])
