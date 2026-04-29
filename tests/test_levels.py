"""Levels engine — exercise on hand-built fixtures matching the plan's
"~20 hand-picked candle fixtures" acceptance criterion."""

from __future__ import annotations

import math

import pytest

from signal_trck.levels import detect_candidates
from signal_trck.storage.models import Candle


def _candle(ts: int, *, high: float, low: float, close: float | None = None) -> Candle:
    if close is None:
        close = (high + low) / 2
    return Candle(
        pair_id="test:T-USD",
        interval="1d",
        ts_utc=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
        source="test",
    )


def _series(prices_high_low: list[tuple[float, float]]) -> list[Candle]:
    return [
        _candle(1_700_000_000 + i * 86400, high=h, low=lo)
        for i, (h, lo) in enumerate(prices_high_low)
    ]


def test_empty_input_returns_empty() -> None:
    assert detect_candidates([]) == []


def test_too_few_candles_returns_empty() -> None:
    candles = _series([(100, 99), (101, 100), (102, 101)])  # < 2*5+1
    assert detect_candidates(candles) == []


def test_strict_uptrend_has_no_clear_levels() -> None:
    """A pure monotonic uptrend has no swing highs *or* lows except the
    endpoints — which the centered-window detector excludes by construction."""
    candles = _series([(100 + i, 99 + i) for i in range(40)])
    result = detect_candidates(candles)
    # No internal swings → no candidates.
    assert result == []


def test_clear_double_top_produces_resistance() -> None:
    """A series with two well-separated peaks at the same level should produce
    one resistance candidate at that price."""
    # Build a W-shape: rise to 110, fall to 100, rise to 110, fall to 100, rise to 105.
    pts: list[tuple[float, float]] = []
    pts += [(100 + i, 99 + i) for i in range(11)]  # 100 -> 110
    pts += [(110 - i, 109 - i) for i in range(1, 11)]  # 110 -> 100
    pts += [(100 + i, 99 + i) for i in range(1, 11)]  # 100 -> 110
    pts += [(110 - i, 109 - i) for i in range(1, 11)]  # 110 -> 100
    pts += [(100 + i / 2, 99 + i / 2) for i in range(1, 11)]  # tail to 105

    candles = _series(pts)
    result = detect_candidates(candles, lookback=3)
    resistance = [c for c in result if c.kind == "resistance"]
    assert resistance, "expected at least one resistance candidate"
    # Should detect ~110 as resistance.
    assert any(abs(r.price - 110) < 1.5 for r in resistance), (
        f"expected resistance near 110, got {[r.price for r in resistance]}"
    )


def test_double_bottom_produces_support() -> None:
    """Mirror image of double-top."""
    pts: list[tuple[float, float]] = []
    pts += [(110 - i, 109 - i) for i in range(11)]  # 110 -> 100
    pts += [(100 + i, 99 + i) for i in range(1, 11)]  # 100 -> 110
    pts += [(110 - i, 109 - i) for i in range(1, 11)]  # 110 -> 100
    pts += [(100 + i, 99 + i) for i in range(1, 11)]  # 100 -> 110
    pts += [(110 - i / 2, 109 - i / 2) for i in range(1, 11)]  # tail to 105

    candles = _series(pts)
    result = detect_candidates(candles, lookback=3)
    support = [c for c in result if c.kind == "support"]
    assert support, "expected at least one support candidate"
    assert any(abs(s.price - 100) < 1.5 for s in support), (
        f"expected support near 100, got {[s.price for s in support]}"
    )


def test_candidates_have_stable_monotonic_ids() -> None:
    """IDs must be ``sr-1, sr-2, …`` in strength order. The exact ordering by
    strength is the contract; the IDs must always start at 1 and be unique."""
    pts = [(100 + 3 * math.sin(i / 4), 99 + 3 * math.sin(i / 4)) for i in range(80)]
    candles = _series(pts)
    result = detect_candidates(candles, lookback=3)
    ids = [c.id for c in result]
    assert all(c.id.startswith("sr-") for c in result)
    assert ids == sorted(ids, key=lambda s: int(s.split("-")[1]))
    assert len(set(ids)) == len(ids)


def test_top_n_caps_results() -> None:
    pts = [(100 + 5 * math.sin(i / 3), 99 + 5 * math.sin(i / 3)) for i in range(120)]
    candles = _series(pts)
    result = detect_candidates(candles, lookback=3, top_n=3)
    assert len(result) <= 3


def test_strength_score_is_descending() -> None:
    pts = [(100 + 2 * math.sin(i / 5), 99 + 2 * math.sin(i / 5)) for i in range(80)]
    candles = _series(pts)
    result = detect_candidates(candles, lookback=3)
    if len(result) > 1:
        scores = [c.strength_score for c in result]
        assert scores == sorted(scores, reverse=True), f"expected descending, got {scores}"


def test_lookback_validation() -> None:
    candles = _series([(100, 99) for _ in range(20)])
    with pytest.raises(ValueError, match="lookback"):
        detect_candidates(candles, lookback=0)


def test_cluster_pct_validation() -> None:
    candles = _series([(100, 99) for _ in range(20)])
    with pytest.raises(ValueError, match="cluster_pct"):
        detect_candidates(candles, cluster_pct=0.0)


def test_top_n_validation() -> None:
    candles = _series([(100, 99) for _ in range(20)])
    with pytest.raises(ValueError, match="top_n"):
        detect_candidates(candles, top_n=0)
