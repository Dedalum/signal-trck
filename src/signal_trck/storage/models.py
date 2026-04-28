"""Plain-data shapes returned by the Store. Not Pydantic — Pydantic models
live next to the API surface (``chart_schema``); the storage layer keeps
boring tuples-as-dataclasses for speed and clarity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pair:
    pair_id: str
    base: str
    quote: str
    source: str
    added_at: int
    last_viewed_at: int | None
    is_pinned: bool
    pinned_context_path: str | None


@dataclass(frozen=True, slots=True)
class Candle:
    pair_id: str
    interval: str
    ts_utc: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
