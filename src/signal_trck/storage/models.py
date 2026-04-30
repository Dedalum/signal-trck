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


@dataclass(frozen=True, slots=True)
class ChartListItem:
    """Summary view of a chart for sidebar listings.

    Drops the full ``drawings`` and ``indicator_refs`` payload so a list
    response doesn't drag a chart's entire shape around. Use ``Store.get_chart``
    when you need the full ``Chart`` model.
    """

    slug: str
    pair_id: str
    title: str
    prov_kind: str
    prov_model: str | None
    parent_chart_slug: str | None
    ai_run_id: int | None
    updated_at_unix: int


@dataclass(frozen=True, slots=True)
class AIRunRow:
    """An ``ai_runs`` audit row, with the JSON columns parsed.

    ``sr_candidates_presented`` is a list of dicts (the candidate set as
    presented to the LLM). ``sr_candidates_selected`` is a list of stable
    candidate IDs the LLM selected. JSON parsing happens at the storage
    boundary so callers get typed Python objects.
    """

    run_id: int
    pair_id: str
    chart_slug: str
    model: str
    provider: str
    prompt_template_version: str
    system_prompt_hash: str
    context_file_sha256: str | None
    context_preview: str | None
    sr_candidates_presented: list[dict]
    sr_candidates_selected: list[str]
    ran_at: int
