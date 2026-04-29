"""Read-through cache for indicator series.

The cache is the **parity-enforcement mechanism** between the UI and the
LLM, not just a perf optimization. By persisting one set of bytes keyed by
``(pair_id, interval, name, params_hash, ts_utc)``, both readers see the
same numbers regardless of when they ask.

Cache lifecycle:
- ``compute_or_load`` reads the latest candle ``ts_utc`` (one indexed
  query) and the cached rows for the requested cache keys.
- On hit, only the indicator rows are loaded; the candle table is not
  scanned.
- On miss, all candles are loaded, the indicator is computed via TA-Lib,
  and the cache is rewritten atomically via
  ``Store.replace_indicator_rows`` (delete + insert in one transaction).

"Fully cached" requires every cache key to have at least one row AND its
latest cached ``ts_utc`` to equal the latest candle ``ts_utc``. We do
**not** compare row count to candle count: indicators have warmup periods
(NaN values aren't persisted), so cached row count is typically less than
candle count. The "latest cached ts" check is what makes the hit safe —
if a new candle has been fetched, the latest cached ts will lag and we
recompute.

Caveat: a candle revised in place (same ts, different OHLC — Coinbase
sometimes does this for the most recent bar) won't invalidate the cache.
Acceptable for v1; if it causes user-visible drift, switch to invalidating
the cache row-by-row in ``Store.upsert_candles``.
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
    output key in a dict. **Only non-NaN values are returned** — TA-Lib's
    warmup NaNs are filtered out at this boundary on both the miss path
    (after computation) and the hit path (the cache only persists non-NaN
    rows). Callers don't need to mask for NaN.
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

    latest_candle = await store.latest_candle_ts(pair_id, interval)
    if latest_candle is None:
        empty_ts = np.array([], dtype=np.int64)
        empty_v = np.array([], dtype=np.float64)
        return {k: IndicatorSeries(empty_ts, empty_v) for k in keys}

    cached_rows = await store.get_indicator_rows(
        pair_id=pair_id, interval=interval, names=cache_keys, params_hash=h
    )
    if _is_fully_cached(cached_rows, cache_keys, latest_candle):
        log.debug(
            "indicator.cache_hit",
            pair_id=pair_id,
            interval=interval,
            name=name,
            params_hash=h,
            n=len(cached_rows[cache_keys[0]]),
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

    # Cache miss → load candles, compute, persist.
    candles = await store.get_candles(pair_id, interval)
    candle_ts = np.array([c.ts_utc for c in candles], dtype=np.int64)
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

    # Persist non-NaN values; build the non-NaN-only series we return.
    rows_to_persist: list[tuple[str, str, str, str, int, float]] = []
    series_out: dict[str, IndicatorSeries] = {}
    for output_key, series in raw.items():
        ck = cache_name(name, output_key)
        mask = ~np.isnan(series)
        valid_ts = candle_ts[mask]
        valid_vals = series[mask]
        for ts, val in zip(valid_ts.tolist(), valid_vals.tolist(), strict=True):
            rows_to_persist.append((pair_id, interval, ck, h, int(ts), float(val)))
        series_out[output_key] = IndicatorSeries(ts_utc=valid_ts, values=valid_vals)

    await store.replace_indicator_rows(
        pair_id=pair_id,
        interval=interval,
        names=cache_keys,
        params_hash=h,
        rows=rows_to_persist,
    )
    return series_out


def _is_fully_cached(
    cached_rows: dict[str, list[tuple[int, float]]],
    cache_keys: list[str],
    latest_candle: int,
) -> bool:
    """Cache is fresh iff every cache key has at least one row AND the
    latest cached ``ts_utc`` equals the latest candle ``ts_utc``.

    Row count is not compared to candle count: TA-Lib produces NaN during
    indicator warmup and we don't persist NaN, so cached row count is
    typically less than candle count. The "latest cached ts" check is
    sufficient — if a new candle is fetched, the latest cached ts will
    lag and we recompute.
    """
    for key in cache_keys:
        rows = cached_rows.get(key, [])
        if not rows:
            return False
        # Rows are ordered ASC by the SQL query; last row's ts is the max.
        if rows[-1][0] != latest_candle:
            return False
    return True
