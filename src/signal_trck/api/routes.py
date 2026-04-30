"""All FastAPI route handlers for the signal-trck Phase B web UI.

Decision 13: one routes.py, not six router files. Per the Phase A pattern
(``Store`` holds all SQL strings) — split when the file genuinely hurts,
not when it merely contains many similar things. ~14 handlers, mostly
thin wrappers, currently fits one file.

Per-indicator-name params (Decision 20): flat query params + manual
dispatch on the ``name`` path param. Pydantic discriminated unions don't
bind to FastAPI's flat querystring without JSON-encoding the params blob,
which defeats auto-validation; manual dispatch is cleaner.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from signal_trck import chart_io
from signal_trck import pair_id as pair_id_mod
from signal_trck.adapters import build_adapter
from signal_trck.chart_schema import Chart
from signal_trck.indicators.cache import compute_or_load
from signal_trck.indicators.engine import SUPPORTED_NAMES
from signal_trck.levels.swing_cluster import detect_candidates
from signal_trck.storage import (
    AIRunRow,
    ChartListItem,
    ChartNotFound,
    Pair,
    PairNotFound,
    Store,
)


def get_store(request: Request) -> Store:
    """FastAPI dependency: resolve the Store stashed on ``app.state``.

    Lives here (not a separate ``deps.py``) per Decision 13: 3 files in the
    api/ package, not 4. The lifespan handler in ``app.py`` populates
    ``app.state.store`` once at startup.
    """
    return request.app.state.store  # type: ignore[no-any-return]

log = structlog.get_logger(__name__)

router = APIRouter()


# --- Build version constant ---
# Reported by /healthz so the frontend can detect a backend upgrade and
# regenerate api-types if needed.
try:
    from signal_trck import __version__ as _BUILD_VERSION  # noqa: N812 — module constant alias
except ImportError:  # pragma: no cover - defensive
    _BUILD_VERSION = "unknown"


# --- Common response shapes ---


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class PairResponse(BaseModel):
    pair_id: str
    base: str
    quote: str
    source: str
    added_at: int
    last_viewed_at: int | None = None
    is_pinned: bool
    pinned_context_path: str | None = None

    @classmethod
    def from_pair(cls, p: Pair) -> PairResponse:
        return cls(
            pair_id=p.pair_id,
            base=p.base,
            quote=p.quote,
            source=p.source,
            added_at=p.added_at,
            last_viewed_at=p.last_viewed_at,
            is_pinned=p.is_pinned,
            pinned_context_path=p.pinned_context_path,
        )


class CreatePairRequest(BaseModel):
    pair_id: str = Field(..., description="Canonical id, e.g. 'coinbase:BTC-USD'")


class CandleResponse(BaseModel):
    ts_utc: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorPointResponse(BaseModel):
    ts_utc: int
    value: float


class IndicatorSeriesResponse(BaseModel):
    """One named series. Multi-output indicators (MACD, BB) emit multiple."""

    name: str
    output_key: str
    points: list[IndicatorPointResponse]


class IndicatorResponse(BaseModel):
    pair_id: str
    interval: str
    name: str
    params: dict[str, float | int | str | bool]
    series: list[IndicatorSeriesResponse]


class SRCandidateResponse(BaseModel):
    id: str
    price: float
    kind: Literal["support", "resistance"]
    method: str
    touches: int
    strength_score: float
    first_seen: int
    last_touch: int


class SRCandidatesResponse(BaseModel):
    pair_id: str
    interval: str
    candidates: list[SRCandidateResponse]


class RefreshRequest(BaseModel):
    interval: Literal["1h", "1d"] = "1d"
    days: int = Field(default=30, ge=1, le=730)


class RefreshResponse(BaseModel):
    pair_id: str
    interval: str
    fetched: int


class ChartListItemResponse(BaseModel):
    slug: str
    pair_id: str
    title: str
    prov_kind: Literal["user", "ai"]
    prov_model: str | None = None
    parent_chart_slug: str | None = None
    ai_run_id: int | None = None
    updated_at_unix: int

    @classmethod
    def from_row(cls, r: ChartListItem) -> ChartListItemResponse:
        kind: Literal["user", "ai"]
        if r.prov_kind == "user":
            kind = "user"
        elif r.prov_kind == "ai":
            kind = "ai"
        else:
            raise ValueError(f"unexpected prov_kind {r.prov_kind!r}")
        return cls(
            slug=r.slug,
            pair_id=r.pair_id,
            title=r.title,
            prov_kind=kind,
            prov_model=r.prov_model,
            parent_chart_slug=r.parent_chart_slug,
            ai_run_id=r.ai_run_id,
            updated_at_unix=r.updated_at_unix,
        )


class AIRunResponse(BaseModel):
    run_id: int
    pair_id: str
    chart_slug: str
    model: str
    provider: str
    prompt_template_version: str
    context_file_sha256: str | None = None
    context_preview: str | None = None
    sr_candidates_selected: list[str]
    ran_at: int

    @classmethod
    def from_row(cls, r: AIRunRow) -> AIRunResponse:
        return cls(
            run_id=r.run_id,
            pair_id=r.pair_id,
            chart_slug=r.chart_slug,
            model=r.model,
            provider=r.provider,
            prompt_template_version=r.prompt_template_version,
            context_file_sha256=r.context_file_sha256,
            context_preview=r.context_preview,
            sr_candidates_selected=r.sr_candidates_selected,
            ran_at=r.ran_at,
        )


# --- Routes ---


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(version=_BUILD_VERSION)


@router.get("/pairs", response_model=list[PairResponse])
async def list_pairs(store: Annotated[Store, Depends(get_store)]) -> list[PairResponse]:
    pairs = await store.list_pairs()
    return [PairResponse.from_pair(p) for p in pairs]


@router.post("/pairs", response_model=PairResponse, status_code=201)
async def create_pair(
    body: CreatePairRequest, store: Annotated[Store, Depends(get_store)]
) -> PairResponse:
    pid = pair_id_mod.parse(body.pair_id)
    await store.add_pair(pid.value, pid.base, pid.quote, pid.source)
    pair = await store.get_pair(pid.value)
    if pair is None:  # pragma: no cover - add_pair just inserted it
        raise PairNotFound(pid.value)
    return PairResponse.from_pair(pair)


@router.delete("/pairs/{pair_id}", status_code=204)
async def remove_pair(pair_id: str, store: Annotated[Store, Depends(get_store)]) -> None:
    if await store.get_pair(pair_id) is None:
        raise PairNotFound(pair_id)
    await store.remove_pair(pair_id)


@router.get(
    "/pairs/{pair_id}/candles",
    response_model=list[CandleResponse],
)
async def get_candles(
    pair_id: str,
    store: Annotated[Store, Depends(get_store)],
    interval: Literal["1h", "1d", "1w"] = "1d",
    window_days: int = Query(90, ge=1, le=3650),
) -> list[CandleResponse]:
    if await store.get_pair(pair_id) is None:
        raise PairNotFound(pair_id)
    end = int(time.time())
    start = end - window_days * 86_400
    candles = await store.get_candles(pair_id, interval, start_ts=start, end_ts=end)
    return [
        CandleResponse(
            ts_utc=c.ts_utc,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles
    ]


@router.get(
    "/pairs/{pair_id}/indicators/{name}",
    response_model=IndicatorResponse,
)
async def get_indicator(
    pair_id: str,
    name: str,
    store: Annotated[Store, Depends(get_store)],
    interval: Literal["1h", "1d", "1w"] = "1d",
    period: int | None = Query(None, ge=2, le=500),
    fast: int | None = Query(None, ge=2, le=200),
    slow: int | None = Query(None, ge=3, le=500),
    signal: int | None = Query(None, ge=2, le=200),
    stddev: float | None = Query(None, gt=0, le=10),
) -> IndicatorResponse:
    """Return a (potentially multi-output) indicator series.

    Per Decision 20: the ``name`` path param dispatches to a per-indicator
    params shape. SMA/EMA/RSI take ``period``; MACD takes ``fast``/``slow``/
    ``signal``; BB takes ``period``/``stddev``. Unknown ``name`` → 422.
    """
    name_u = name.upper()
    if name_u not in SUPPORTED_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown indicator {name!r}; supported: {list(SUPPORTED_NAMES)}",
        )
    if await store.get_pair(pair_id) is None:
        raise PairNotFound(pair_id)

    params = _params_for(name_u, period=period, fast=fast, slow=slow, signal=signal, stddev=stddev)
    raw = await compute_or_load(
        store, pair_id=pair_id, interval=interval, name=name_u, params=params
    )
    series = [
        IndicatorSeriesResponse(
            name=name_u,
            output_key=output_key,
            points=[
                IndicatorPointResponse(ts_utc=int(ts), value=float(v))
                for ts, v in zip(s.ts_utc.tolist(), s.values.tolist(), strict=True)
            ],
        )
        for output_key, s in raw.items()
    ]
    return IndicatorResponse(
        pair_id=pair_id,
        interval=interval,
        name=name_u,
        params=params,
        series=series,
    )


def _params_for(
    name_u: str,
    *,
    period: int | None,
    fast: int | None,
    slow: int | None,
    signal: int | None,
    stddev: float | None,
) -> dict[str, float | int | str | bool]:
    """Per-indicator-name params dispatch.

    Manual instead of Pydantic discriminated unions (Decision 20). Returns
    only the params relevant to this indicator, with sensible defaults.
    """
    params: dict[str, float | int | str | bool] = {}
    if name_u in {"SMA", "EMA"}:
        params["period"] = period or 20
    elif name_u == "RSI":
        params["period"] = period or 14
    elif name_u == "MACD":
        params["fast"] = fast or 12
        params["slow"] = slow or 26
        params["signal"] = signal or 9
    elif name_u == "BB":
        params["period"] = period or 20
        params["stddev"] = stddev or 2.0
    return params


@router.get(
    "/pairs/{pair_id}/sr-candidates",
    response_model=SRCandidatesResponse,
)
async def get_sr_candidates(
    pair_id: str,
    store: Annotated[Store, Depends(get_store)],
    interval: Literal["1h", "1d", "1w"] = "1d",
    window_days: int = Query(180, ge=1, le=3650),
    top_n: int = Query(50, ge=1, le=500),
) -> SRCandidatesResponse:
    if await store.get_pair(pair_id) is None:
        raise PairNotFound(pair_id)
    end = int(time.time())
    start = end - window_days * 86_400
    candles = await store.get_candles(pair_id, interval, start_ts=start, end_ts=end)
    candidates = detect_candidates(candles, top_n=top_n)
    return SRCandidatesResponse(
        pair_id=pair_id,
        interval=interval,
        candidates=[
            SRCandidateResponse(
                id=c.id,
                price=c.price,
                kind=c.kind,
                method=c.method,
                touches=c.touches,
                strength_score=c.strength_score,
                first_seen=c.first_seen,
                last_touch=c.last_touch,
            )
            for c in candidates
        ],
    )


@router.post(
    "/pairs/{pair_id}/refresh",
    response_model=RefreshResponse,
)
async def refresh_pair(
    pair_id: str, body: RefreshRequest, store: Annotated[Store, Depends(get_store)]
) -> RefreshResponse:
    """Fetch the most recent ``days`` worth of candles via the source adapter."""
    pair = await store.get_pair(pair_id)
    if pair is None:
        raise PairNotFound(pair_id)
    end = int(time.time())
    start = end - body.days * 86_400
    adapter = build_adapter(pair.source)
    async with adapter:
        new_candles = await adapter.fetch_candles(
            base=pair.base,
            quote=pair.quote,
            interval=body.interval,
            start_ts=start,
            end_ts=end,
        )
    written = await store.upsert_candles(new_candles)
    return RefreshResponse(pair_id=pair_id, interval=body.interval, fetched=written)


# --- Charts ---


@router.get("/charts", response_model=list[ChartListItemResponse])
async def list_charts(
    store: Annotated[Store, Depends(get_store)],
    pair_id: str | None = None,
    limit: int | None = Query(None, ge=1, le=1000),
) -> list[ChartListItemResponse]:
    rows = await store.list_charts(pair_id=pair_id, limit=limit)
    return [ChartListItemResponse.from_row(r) for r in rows]


@router.get("/charts/{slug}", response_model=Chart)
async def get_chart(slug: str, store: Annotated[Store, Depends(get_store)]) -> Chart:
    return await store.get_chart(slug)


@router.post("/charts", response_model=Chart, status_code=201)
async def create_chart(
    body: Chart, store: Annotated[Store, Depends(get_store)]
) -> Chart:
    """Create a new chart. 409 ``CHART_SLUG_CONFLICT`` if slug exists."""
    await store.create_chart(body)
    return await store.get_chart(body.slug)


@router.put("/charts/{slug}", response_model=Chart)
async def update_chart(
    slug: str, body: Chart, store: Annotated[Store, Depends(get_store)]
) -> Chart:
    """Edit-in-place. 404 ``CHART_NOT_FOUND`` if slug doesn't exist."""
    if body.slug != slug:
        raise HTTPException(
            status_code=400,
            detail=f"slug mismatch: path={slug!r} body={body.slug!r}",
        )
    await store.update_chart(body)
    return await store.get_chart(body.slug)


@router.delete("/charts/{slug}", status_code=204)
async def delete_chart(slug: str, store: Annotated[Store, Depends(get_store)]) -> None:
    await store.delete_chart(slug)


@router.post("/charts/import", response_model=Chart, status_code=201)
async def import_chart(
    file: UploadFile, store: Annotated[Store, Depends(get_store)]
) -> Chart:
    """Multipart upload of a ``chart.json`` file.

    Goes through ``chart_io.parse_chart_json`` so a ``schemaVersion``
    mismatch surfaces as ``SchemaVersionError`` (→ 422 SCHEMA_MISMATCH),
    not a generic ``ValidationError``.
    """
    payload = (await file.read()).decode("utf-8")
    chart = chart_io.parse_chart_json(payload)
    await store.create_chart(chart)
    return await store.get_chart(chart.slug)


@router.get("/charts/{slug}/export")
async def export_chart(slug: str, store: Annotated[Store, Depends(get_store)]) -> dict[str, object]:
    """Return the canonical ``chart.json`` payload (for download by the UI)."""
    chart = await store.get_chart(slug)
    # Use ``by_alias=True`` so the field is ``schemaVersion`` (camelCase) on
    # the wire, matching the on-disk JSON contract.
    return chart.model_dump(by_alias=True, mode="json", exclude_none=False)


# --- AI runs (read-only) ---


@router.get("/pairs/{pair_id}/ai_runs", response_model=list[AIRunResponse])
async def list_ai_runs(
    pair_id: str,
    store: Annotated[Store, Depends(get_store)],
    limit: int | None = Query(None, ge=1, le=1000),
) -> list[AIRunResponse]:
    if await store.get_pair(pair_id) is None:
        raise PairNotFound(pair_id)
    runs = await store.list_ai_runs(pair_id, limit=limit)
    return [AIRunResponse.from_row(r) for r in runs]


# Defensive ChartNotFound import — referenced via raise indirectly through Store.
_ = ChartNotFound
