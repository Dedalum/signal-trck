"""Indicator cache: miss → compute → persist → hit."""

from __future__ import annotations

import numpy as np

from signal_trck.indicators.cache import compute_or_load
from signal_trck.indicators.params import params_hash
from signal_trck.storage import Store
from signal_trck.storage.models import Candle

PAIR = "coinbase:TEST-USD"


async def _seed_pair(store: Store, n: int = 60, base_ts: int = 1_700_000_000) -> None:
    await store.add_pair(PAIR, "TEST", "USD", "coinbase")
    candles = [
        Candle(
            pair_id=PAIR,
            interval="1d",
            ts_utc=base_ts + i * 86400,
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100 + i,  # monotonic, makes asserts easy
            volume=1000,
            source="coinbase",
        )
        for i in range(n)
    ]
    await store.upsert_candles(candles)


async def test_no_candles_returns_empty(store: Store) -> None:
    await store.add_pair(PAIR, "TEST", "USD", "coinbase")
    out = await compute_or_load(
        store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}
    )
    assert out["value"].values.size == 0
    assert out["value"].ts_utc.size == 0


async def test_miss_then_hit_returns_same_values(store: Store) -> None:
    await _seed_pair(store, n=40)
    out_miss = await compute_or_load(
        store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}
    )
    out_hit = await compute_or_load(
        store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}
    )
    np.testing.assert_array_equal(out_miss["value"].ts_utc, out_hit["value"].ts_utc)
    # NaN positions are not preserved on hit (we only persist non-NaN values),
    # but the values that ARE present must match exactly.
    miss_vals = out_miss["value"].values
    hit_vals = out_hit["value"].values
    miss_mask = ~np.isnan(miss_vals)
    hit_mask = ~np.isnan(hit_vals)
    np.testing.assert_array_equal(miss_mask, hit_mask)
    np.testing.assert_array_almost_equal(miss_vals[miss_mask], hit_vals[hit_mask])


async def test_persists_one_row_per_non_nan_value(store: Store) -> None:
    await _seed_pair(store, n=30)
    await compute_or_load(store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5})
    h = params_hash({"period": 5})
    cur = await store.conn.execute(
        "SELECT COUNT(*) FROM indicator_values WHERE pair_id = ? AND name = ? AND params_hash = ?",
        (PAIR, "SMA", h),
    )
    n = (await cur.fetchone())[0]  # type: ignore[index]
    # 30 closes, period=5 → first 4 NaN, 26 valid values
    assert n == 26


async def test_different_params_have_independent_cache(store: Store) -> None:
    await _seed_pair(store, n=30)
    out5 = await compute_or_load(
        store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5}
    )
    out10 = await compute_or_load(
        store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 10}
    )
    # Different periods produce different values at the same timestamp.
    last_idx = -1
    assert out5["value"].values[last_idx] != out10["value"].values[last_idx]


async def test_macd_three_outputs_all_persisted(store: Store) -> None:
    await _seed_pair(store, n=80)
    out = await compute_or_load(
        store,
        pair_id=PAIR,
        interval="1d",
        name="MACD",
        params={"fast": 12, "slow": 26, "signal": 9},
    )
    assert set(out.keys()) == {"macd", "signal", "hist"}

    # Three rows per non-NaN aligned timestamp.
    cur = await store.conn.execute(
        "SELECT name, COUNT(*) FROM indicator_values "
        "WHERE pair_id = ? AND name IN ('MACD.macd', 'MACD.signal', 'MACD.hist') "
        "GROUP BY name",
        (PAIR,),
    )
    rows = await cur.fetchall()
    name_to_count = dict(rows)
    assert "MACD.macd" in name_to_count
    assert "MACD.signal" in name_to_count
    assert "MACD.hist" in name_to_count
    # All three should have the same number of non-NaN values.
    counts = list(name_to_count.values())
    assert len(set(counts)) == 1, f"expected equal counts across MACD outputs, got {name_to_count}"


async def test_int_vs_float_period_collapse_to_same_cache_entry(store: Store) -> None:
    """``period: 5`` and ``period: 5.0`` must hit the same cache key."""
    await _seed_pair(store, n=30)
    await compute_or_load(store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5})
    cur = await store.conn.execute(
        "SELECT COUNT(*) FROM indicator_values WHERE pair_id = ? AND name = ?",
        (PAIR, "SMA"),
    )
    n_after_first = (await cur.fetchone())[0]  # type: ignore[index]

    await compute_or_load(store, pair_id=PAIR, interval="1d", name="SMA", params={"period": 5.0})
    cur = await store.conn.execute(
        "SELECT COUNT(*) FROM indicator_values WHERE pair_id = ? AND name = ?",
        (PAIR, "SMA"),
    )
    n_after_second = (await cur.fetchone())[0]  # type: ignore[index]
    # Must be identical — same cache key.
    assert n_after_first == n_after_second
