"""Indicator dispatch — TA-Lib wrappers under a uniform ``compute()``.

Each indicator returns one or more named series of the same length as the
input. Multi-output indicators (MACD, BB) return a dict; single-output
(SMA, EMA, RSI) return ``{"value": np.ndarray}``. The cache layer flattens
multi-output series into ``(name, output_key)`` row groups.
"""

from __future__ import annotations

from typing import TypedDict

import numpy as np
import talib

# What the engine accepts as the params for a given indicator. Open-ended
# so providers and the AI can pass arbitrary kwargs; engine validates each.
IndicatorParams = dict[str, float | int | str | bool]
IndicatorResult = dict[str, np.ndarray]


class _Spec(TypedDict):
    outputs: list[str]


# Each indicator declares its output series names. Single-output indicators
# emit one series at key "value"; multi-output emits multiple.
_SPECS: dict[str, _Spec] = {
    "SMA": {"outputs": ["value"]},
    "EMA": {"outputs": ["value"]},
    "RSI": {"outputs": ["value"]},
    "MACD": {"outputs": ["macd", "signal", "hist"]},
    "BB": {"outputs": ["upper", "middle", "lower"]},
}

SUPPORTED_NAMES: tuple[str, ...] = tuple(_SPECS.keys())


def outputs_for(name: str) -> list[str]:
    """Expected output keys for an indicator. Raises on unknown names."""
    name_u = name.upper()
    if name_u not in _SPECS:
        raise ValueError(f"unknown indicator {name!r}; supported: {list(_SPECS)}")
    return list(_SPECS[name_u]["outputs"])


def compute(name: str, params: IndicatorParams, closes: np.ndarray) -> IndicatorResult:
    """Compute an indicator's output series from a close-price array.

    ``closes`` must be 1-D ``float64`` and at least one element long. NaN at
    the start of the output series is normal and indicates warmup. Callers
    aligning indicator series to a candle timestamp array should preserve
    NaNs and let downstream filter them.
    """
    if closes.ndim != 1:
        raise ValueError(f"closes must be 1-D, got shape {closes.shape}")
    if closes.size == 0:
        raise ValueError("closes is empty")
    closes_64 = closes.astype(np.float64, copy=False)

    name_u = name.upper()
    if name_u == "SMA":
        period = _int_param(params, "period", default=20, min_=2)
        return {"value": talib.SMA(closes_64, timeperiod=period)}

    if name_u == "EMA":
        period = _int_param(params, "period", default=20, min_=2)
        return {"value": talib.EMA(closes_64, timeperiod=period)}

    if name_u == "RSI":
        period = _int_param(params, "period", default=14, min_=2)
        return {"value": talib.RSI(closes_64, timeperiod=period)}

    if name_u == "MACD":
        fast = _int_param(params, "fast", default=12, min_=2)
        slow = _int_param(params, "slow", default=26, min_=fast + 1)
        signal = _int_param(params, "signal", default=9, min_=2)
        macd, sig, hist = talib.MACD(
            closes_64, fastperiod=fast, slowperiod=slow, signalperiod=signal
        )
        return {"macd": macd, "signal": sig, "hist": hist}

    if name_u == "BB":
        period = _int_param(params, "period", default=20, min_=2)
        nbdev = _float_param(params, "nbdev", default=2.0, min_=0.1)
        upper, middle, lower = talib.BBANDS(
            closes_64, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev, matype=0
        )
        return {"upper": upper, "middle": middle, "lower": lower}

    raise ValueError(f"unknown indicator {name!r}; supported: {list(_SPECS)}")


def _int_param(params: IndicatorParams, key: str, *, default: int, min_: int) -> int:
    raw = params.get(key, default)
    if isinstance(raw, bool):
        raise TypeError(f"{key} must be int, got bool")
    if isinstance(raw, float) and not raw.is_integer():
        raise ValueError(f"{key} must be a whole number, got {raw}")
    val = int(raw)
    if val < min_:
        raise ValueError(f"{key} must be >= {min_}, got {val}")
    return val


def _float_param(params: IndicatorParams, key: str, *, default: float, min_: float) -> float:
    raw = params.get(key, default)
    if isinstance(raw, bool):
        raise TypeError(f"{key} must be float, got bool")
    val = float(raw)
    if val < min_:
        raise ValueError(f"{key} must be >= {min_}, got {val}")
    return val
