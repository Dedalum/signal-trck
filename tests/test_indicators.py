"""Indicator engine — cross-check TA-Lib against hand-computed values for
small fixtures. The point isn't to reimplement TA-Lib; it's to lock the
contract so a future refactor that swaps TA-Lib for an alternative cannot
silently change the values the LLM sees."""

from __future__ import annotations

import numpy as np
import pytest

from signal_trck.indicators.engine import SUPPORTED_NAMES, compute, outputs_for


def test_supported_names_locked() -> None:
    """If this changes, callers depending on the name set break."""
    assert SUPPORTED_NAMES == ("SMA", "EMA", "RSI", "MACD", "BB")


def test_outputs_for_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown indicator"):
        outputs_for("FOO")


def test_compute_unknown_raises() -> None:
    closes = np.arange(20, dtype=np.float64)
    with pytest.raises(ValueError, match="unknown indicator"):
        compute("FOO", {}, closes)


def test_compute_rejects_empty_array() -> None:
    with pytest.raises(ValueError, match="empty"):
        compute("SMA", {"period": 5}, np.array([], dtype=np.float64))


def test_compute_rejects_2d_array() -> None:
    with pytest.raises(ValueError, match="1-D"):
        compute("SMA", {"period": 5}, np.zeros((3, 3), dtype=np.float64))


# --- SMA ---


def test_sma_matches_manual_mean() -> None:
    closes = np.array([10, 11, 12, 13, 14, 15, 16], dtype=np.float64)
    out = compute("SMA", {"period": 3}, closes)
    # First 2 values are NaN (warmup).
    assert np.isnan(out["value"][0])
    assert np.isnan(out["value"][1])
    # SMA(3) at index 2: mean of [10, 11, 12] = 11
    assert out["value"][2] == pytest.approx(11.0)
    assert out["value"][6] == pytest.approx((14 + 15 + 16) / 3)


def test_sma_period_too_small_raises() -> None:
    with pytest.raises(ValueError, match="period.*>= 2"):
        compute("SMA", {"period": 1}, np.arange(20, dtype=np.float64))


def test_sma_default_period_is_20() -> None:
    closes = np.linspace(100, 200, 50, dtype=np.float64)
    out = compute("SMA", {}, closes)
    # First 19 are NaN
    assert np.isnan(out["value"][:19]).all()
    assert not np.isnan(out["value"][19])


# --- EMA ---


def test_ema_first_real_value_equals_initial_sma() -> None:
    """TA-Lib's EMA seeds the first value with the SMA of the first ``period``
    samples; subsequent values use the EMA recursion."""
    closes = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.float64)
    out = compute("EMA", {"period": 3}, closes)
    assert np.isnan(out["value"][:2]).all()
    assert out["value"][2] == pytest.approx(2.0)  # mean of [1, 2, 3]


# --- RSI ---


def test_rsi_strict_uptrend_approaches_100() -> None:
    closes = np.arange(1, 30, dtype=np.float64)  # monotonically increasing
    out = compute("RSI", {"period": 14}, closes)
    valid = out["value"][~np.isnan(out["value"])]
    assert valid[-1] == pytest.approx(100.0, abs=1e-6)


def test_rsi_strict_downtrend_approaches_0() -> None:
    closes = np.arange(30, 1, -1, dtype=np.float64)
    out = compute("RSI", {"period": 14}, closes)
    valid = out["value"][~np.isnan(out["value"])]
    assert valid[-1] == pytest.approx(0.0, abs=1e-6)


# --- MACD ---


def test_macd_returns_three_aligned_series() -> None:
    closes = np.linspace(100, 200, 100, dtype=np.float64)
    out = compute("MACD", {}, closes)
    assert set(out.keys()) == {"macd", "signal", "hist"}
    assert all(out[k].shape == closes.shape for k in out)


def test_macd_validates_slow_greater_than_fast() -> None:
    closes = np.arange(50, dtype=np.float64)
    with pytest.raises(ValueError, match="slow"):
        compute("MACD", {"fast": 26, "slow": 12, "signal": 9}, closes)


# --- BB ---


def test_bb_upper_above_middle_above_lower() -> None:
    rng = np.random.default_rng(42)
    closes = 100 + rng.standard_normal(80).cumsum()
    out = compute("BB", {"period": 20, "nbdev": 2.0}, closes)
    valid = ~np.isnan(out["middle"])
    assert (out["upper"][valid] >= out["middle"][valid]).all()
    assert (out["middle"][valid] >= out["lower"][valid]).all()


def test_bb_with_zero_volatility_collapses_bands() -> None:
    closes = np.full(40, 100.0, dtype=np.float64)
    out = compute("BB", {"period": 20, "nbdev": 2.0}, closes)
    valid = ~np.isnan(out["middle"])
    assert np.allclose(out["upper"][valid], 100.0)
    assert np.allclose(out["lower"][valid], 100.0)


# --- param validation ---


def test_period_must_be_whole_number() -> None:
    closes = np.arange(20, dtype=np.float64)
    with pytest.raises(ValueError, match="whole"):
        compute("SMA", {"period": 5.5}, closes)


def test_period_as_int_float_is_accepted() -> None:
    """``period: 50.0`` (e.g. round-tripped from JSON) must work."""
    closes = np.arange(60, dtype=np.float64)
    out = compute("SMA", {"period": 50.0}, closes)
    assert not np.isnan(out["value"][-1])
