"""Swing-highs/lows + agglomerative clustering.

Algorithm (per plan §"Support/resistance detection algorithms"):

1. Detect local extrema with a configurable lookback window (default 5):
   a candle is a swing high if its ``high`` is the max of a centered window
   of size ``2*lookback + 1``; symmetric for swing lows.
2. Cluster swing prices with ``sklearn.cluster.AgglomerativeClustering``
   using distance threshold = ``cluster_pct * mean_price`` (default 0.6%).
   Highs and lows are clustered separately; each cluster becomes one
   candidate band.
3. Score candidates: ``strength = touches * recency_factor`` where
   ``recency_factor = 1 + last_touch_age_fraction`` (recent touches weigh
   slightly more, but ancient many-touch levels still surface).
4. Rank by strength descending, assign stable IDs ``sr-1, sr-2, …``,
   return top N (default 50 — small enough that no provider chokes on
   the candidate enum, large enough to give the LLM real choice).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog
from sklearn.cluster import AgglomerativeClustering

from signal_trck.levels.types import Candidate
from signal_trck.storage.models import Candle

log = structlog.get_logger(__name__)

DEFAULT_LOOKBACK = 5
DEFAULT_CLUSTER_PCT = 0.006  # 0.6% of mean price
DEFAULT_TOP_N = 50


@dataclass(frozen=True, slots=True)
class _SwingPoint:
    ts_utc: int
    price: float


def detect_candidates(
    candles: list[Candle],
    *,
    lookback: int = DEFAULT_LOOKBACK,
    cluster_pct: float = DEFAULT_CLUSTER_PCT,
    top_n: int = DEFAULT_TOP_N,
) -> list[Candidate]:
    """Detect S/R candidates from a candle sequence.

    Returns a ranked list (strongest first), at most ``top_n`` items, with
    stable ``sr-N`` IDs. Empty input or no detected swings → empty list.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    if cluster_pct <= 0:
        raise ValueError(f"cluster_pct must be > 0, got {cluster_pct}")
    if top_n < 1:
        raise ValueError(f"top_n must be >= 1, got {top_n}")
    if len(candles) < 2 * lookback + 1:
        return []

    highs = _detect_swings(candles, lookback=lookback, kind="high")
    lows = _detect_swings(candles, lookback=lookback, kind="low")

    mean_price = float(np.mean([c.close for c in candles]))
    distance_threshold = cluster_pct * mean_price
    now_ts = int(candles[-1].ts_utc)
    history_span = max(1, now_ts - int(candles[0].ts_utc))

    resistance = _cluster_to_candidates(
        highs,
        kind="resistance",
        distance_threshold=distance_threshold,
        now_ts=now_ts,
        history_span=history_span,
    )
    support = _cluster_to_candidates(
        lows,
        kind="support",
        distance_threshold=distance_threshold,
        now_ts=now_ts,
        history_span=history_span,
    )

    combined = resistance + support
    combined.sort(key=lambda c: c.strength_score, reverse=True)
    combined = combined[:top_n]

    # Re-key with stable IDs after final ranking.
    return [
        Candidate(
            id=f"sr-{i + 1}",
            price=c.price,
            kind=c.kind,
            method=c.method,
            touches=c.touches,
            strength_score=c.strength_score,
            first_seen=c.first_seen,
            last_touch=c.last_touch,
        )
        for i, c in enumerate(combined)
    ]


def _detect_swings(candles: list[Candle], *, lookback: int, kind: str) -> list[_SwingPoint]:
    """Find local extrema using a centered window of size ``2 * lookback + 1``."""
    n = len(candles)
    swings: list[_SwingPoint] = []
    if kind == "high":
        prices = [c.high for c in candles]
        cmp = lambda a, b: a > b  # noqa: E731
    elif kind == "low":
        prices = [c.low for c in candles]
        cmp = lambda a, b: a < b  # noqa: E731
    else:
        raise ValueError(f"unknown swing kind {kind!r}")

    for i in range(lookback, n - lookback):
        center = prices[i]
        # Strict on the left, non-strict on the right — handles plateaus
        # without double-counting.
        is_extreme = all(
            cmp(center, prices[j]) or center == prices[j]
            for j in range(i - lookback, i + lookback + 1)
            if j != i
        )
        if not is_extreme:
            continue
        # Filter out trivial plateaus where all values equal.
        if all(prices[j] == center for j in range(i - lookback, i + lookback + 1)):
            continue
        swings.append(_SwingPoint(ts_utc=int(candles[i].ts_utc), price=float(center)))
    return swings


def _cluster_to_candidates(
    swings: list[_SwingPoint],
    *,
    kind: str,
    distance_threshold: float,
    now_ts: int,
    history_span: int,
) -> list[Candidate]:
    """Cluster swing points by price proximity and synthesize candidates.

    Each cluster yields one candidate at the cluster mean price, with
    ``touches`` = cluster size and a strength score that mixes touches and
    recency.
    """
    if not swings:
        return []

    if len(swings) == 1:
        s = swings[0]
        return [
            Candidate(
                id="",
                price=s.price,
                kind=kind,  # type: ignore[arg-type]
                method="swing_cluster",
                touches=1,
                strength_score=1.0,
                first_seen=s.ts_utc,
                last_touch=s.ts_utc,
            )
        ]

    prices = np.array([s.price for s in swings], dtype=np.float64).reshape(-1, 1)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        linkage="single",
    )
    labels = clustering.fit_predict(prices)

    candidates: list[Candidate] = []
    for label in np.unique(labels):
        members = [s for s, lbl in zip(swings, labels, strict=True) if lbl == label]
        cluster_price = float(np.mean([m.price for m in members]))
        first_seen = min(m.ts_utc for m in members)
        last_touch = max(m.ts_utc for m in members)
        touches = len(members)
        # Recency factor: 1.0 (oldest) to 2.0 (most recent).
        recency = 1.0 + (last_touch - (now_ts - history_span)) / history_span
        strength = float(touches) * recency
        candidates.append(
            Candidate(
                id="",
                price=cluster_price,
                kind=kind,  # type: ignore[arg-type]
                method="swing_cluster",
                touches=touches,
                strength_score=strength,
                first_seen=first_seen,
                last_touch=last_touch,
            )
        )
    return candidates
