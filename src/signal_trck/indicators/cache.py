"""Read-through cache for indicator series.

The cache is the **parity-enforcement mechanism** between the UI and the
LLM, not just a perf optimization. By persisting one set of bytes keyed by
``(pair_id, interval, name, params_hash, ts_utc)``, both readers see the
same numbers regardless of when they ask.

Cache lifecycle:
- ``compute_or_load`` checks ``INDICATOR_VALUES`` for the requested window.
- On full hit, returns the persisted values aligned to candle timestamps.
- On miss (or partial coverage), loads candles from DB, calls
  ``indicators.engine.compute``, persists the new rows, and returns the
  full series. We always recompute the full requested window on miss
  rather than trying to "fill gaps" — gap filling has subtle warmup-bias
  bugs and the data is small enough that it's cheaper to just recompute.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import structlog

from signal_trck.indicators.engine import compute, outputs_for
from signal_trck.indicators.params import params_hash
from signal_trck.storage import Store

log = structlog.get_logger(__name__)


class IndicatorSeries(NamedTuple):
    """Aligned indicator output. ``ts_utc[i]`` corresponds to ``values[i]``.

    Multi-output indicators (MACD, BB) return one ``IndicatorSeries`` per
    output key in a dict. NaNs at the head are normal warmup.
    """

    ts_utc: np.ndarray
    values: np.ndarray


def cache_name(name: str, output_key: str) -> str:
    """Storage key for a (potentially multi-output) indicator.

    Single-output indicators store under their name (``"SMA"``); multi-output
    flatten into ``"NAME.output_key"`` (``"MACD.macd"``, ``"BB.upper"``).
    """
    if output_key == "value":
        return name.upper()
    return f"{name.upper()}.{output_key}"


async def compute_or_load(
    store: Store,
    *,
    pair_id: str,
    interval: str,
    name: str,
    params: dict,
) -> dict[str, IndicatorSeries]:
    """Return aligned indicator series, computing + caching on miss.

    The returned dict has one entry per output key. For SMA/EMA/RSI, that
    is just ``{"value": series}``. For MACD, ``{"macd", "signal", "hist"}``.
    For BB, ``{"upper", "middle", "lower"}``.

    Empty candle history → empty series (no error). Caller decides what to do.
    """
    h = params_hash(params)
    keys = outputs_for(name)
    cache_keys = [cache_name(name, k) for k in keys]

    candles = await store.get_candles(pair_id, interval)
    if not candles:
        empty = np.array([], dtype=np.int64)
        empty_v = np.array([], dtype=np.float64)
        return {k: IndicatorSeries(empty, empty_v) for k in keys}

    candle_ts = np.array([c.ts_utc for c in candles], dtype=np.int64)

    # Cache lookup: do we have rows for every (cache_key, ts)? We treat
    # "fully cached" as the row count for any one cache_key matches the
    # candle count. Anything less → recompute.
    cached_rows = await _load_cached_rows(
        store,
        pair_id=pair_id,
        interval=interval,
        cache_keys=cache_keys,
        params_hash_=h,
    )
    fully_cached = cached_rows and all(
        len(cached_rows.get(k, [])) == len(candle_ts) for k in cache_keys
    )
    if fully_cached:
        log.debug(
            "indicator.cache_hit",
            pair_id=pair_id,
            interval=interval,
            name=name,
            params_hash=h,
            n=len(candle_ts),
        )
        return {
            output_key: IndicatorSeries(
                ts_utc=np.asarray(
                    [r[0] for r in cached_rows[cache_name(name, output_key)]],
                    dtype=np.int64,
                ),
                values=np.asarray(
                    [r[1] for r in cached_rows[cache_name(name, output_key)]],
                    dtype=np.float64,
                ),
            )
            for output_key in keys
        }

    # Cache miss → compute.
    closes = np.array([c.close for c in candles], dtype=np.float64)
    raw = compute(name, params, closes)
    log.info(
        "indicator.cache_miss",
        pair_id=pair_id,
        interval=interval,
        name=name,
        params_hash=h,
        n=len(candle_ts),
    )

    # Persist non-NaN values for each output key.
    rows_to_persist: list[tuple[str, str, str, str, str, int, float]] = []
    series_out: dict[str, IndicatorSeries] = {}
    for output_key, series in raw.items():
        ck = cache_name(name, output_key)
        for i, ts in enumerate(candle_ts):
            val = float(series[i])
            if np.isnan(val):
                continue
            rows_to_persist.append((pair_id, interval, ck, h, "", int(ts), val))
        series_out[output_key] = IndicatorSeries(ts_utc=candle_ts, values=series)

    if rows_to_persist:
        await _delete_then_insert(
            store,
            pair_id=pair_id,
            interval=interval,
            cache_keys=cache_keys,
            params_hash_=h,
            rows=rows_to_persist,
        )
    return series_out


async def _load_cached_rows(
    store: Store,
    *,
    pair_id: str,
    interval: str,
    cache_keys: list[str],
    params_hash_: str,
) -> dict[str, list[tuple[int, float]]]:
    """Fetch existing rows by cache key. Returns ``{}`` on full miss."""
    placeholders = ",".join("?" for _ in cache_keys)
    sql = (
        "SELECT name, ts_utc, value FROM indicator_values "
        f"WHERE pair_id = ? AND interval = ? AND params_hash = ? "
        f"AND name IN ({placeholders}) "
        "ORDER BY name, ts_utc ASC"
    )
    args = [pair_id, interval, params_hash_, *cache_keys]
    cur = await store.conn.execute(sql, args)
    rows = await cur.fetchall()
    if not rows:
        return {}
    out: dict[str, list[tuple[int, float]]] = {k: [] for k in cache_keys}
    for name, ts, value in rows:
        out.setdefault(name, []).append((int(ts), float(value)))
    return out


async def _delete_then_insert(
    store: Store,
    *,
    pair_id: str,
    interval: str,
    cache_keys: list[str],
    params_hash_: str,
    rows: list[tuple[str, str, str, str, str, int, float]],
) -> None:
    """Replace any existing rows for these cache_keys with the new ones."""
    placeholders = ",".join("?" for _ in cache_keys)
    await store.conn.execute(
        f"""
        DELETE FROM indicator_values
        WHERE pair_id = ? AND interval = ? AND params_hash = ?
          AND name IN ({placeholders})
        """,
        [pair_id, interval, params_hash_, *cache_keys],
    )
    await store.conn.executemany(
        """
        INSERT INTO indicator_values
            (pair_id, interval, name, params_hash, ts_utc, value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        # Strip the placeholder column ("" at index 4) from the row tuple.
        [(r[0], r[1], r[2], r[3], r[5], r[6]) for r in rows],
    )
    await store.conn.commit()
