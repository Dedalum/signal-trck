"""Indicator engine. TA-Lib wrappers + read-through DB cache.

Design:
- ``compute(name, params, closes)`` is the only public function — dispatches by name.
- All implementations share a single Pandas/Numpy convention: input is a 1-D
  ``numpy.ndarray`` of close prices (or OHLCV columns for indicators like BB);
  output is a ``numpy.ndarray`` of the same length, with ``NaN`` at indices
  where the indicator hasn't yet warmed up.
- The DB cache lives in ``cache.py`` and is keyed by
  ``(pair_id, interval, name, params_hash, ts_utc)``. A miss recomputes from
  candles in DB.
"""

from signal_trck.indicators.engine import (
    SUPPORTED_NAMES,
    IndicatorParams,
    IndicatorResult,
    compute,
)
from signal_trck.indicators.params import params_hash

__all__ = [
    "SUPPORTED_NAMES",
    "IndicatorParams",
    "IndicatorResult",
    "compute",
    "params_hash",
]
