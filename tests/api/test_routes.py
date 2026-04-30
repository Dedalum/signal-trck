"""API contract tests for all 14 routes.

Per-route happy-path + key error-path tests. Runs against an in-memory
``Store`` via ``ASGITransport``, no real network or filesystem I/O beyond
the per-test SQLite file.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from httpx import AsyncClient

from signal_trck.chart_schema import (
    Anchor,
    Chart,
    ChartData,
    ChartView,
    Drawing,
    Indicator,
    Provenance,
    Style,
)
from signal_trck.storage import Store
from signal_trck.storage.models import Candle


def _user_chart(slug: str = "chart-1", pair: str = "test:T-USD") -> Chart:
    return Chart(
        slug=slug,
        title=f"Test {slug}",
        pair=pair,
        provenance=Provenance(
            kind="user",
            created_at=datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        ),
        data=ChartData(default_window_days=90, default_interval="1d"),
        view=ChartView(
            indicators=[Indicator(id="sma-20", name="SMA", params={"period": 20}, pane=0)],
            drawings=[
                Drawing(
                    id="dr-1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1704067200, price=42000.0)],
                    style=Style(color="#2a9d8f", dash="solid"),
                )
            ],
        ),
    )


# --- /healthz ---


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# --- /pairs ---


async def test_list_pairs_empty(client: AsyncClient) -> None:
    r = await client.get("/pairs")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_pair_then_list(client: AsyncClient) -> None:
    r = await client.post("/pairs", json={"pair_id": "coinbase:BTC-USD"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pair_id"] == "coinbase:BTC-USD"
    assert body["base"] == "BTC"
    assert body["quote"] == "USD"
    assert body["source"] == "coinbase"

    r = await client.get("/pairs")
    assert r.status_code == 200
    pairs = r.json()
    assert len(pairs) == 1
    assert pairs[0]["pair_id"] == "coinbase:BTC-USD"


async def test_create_pair_invalid_id(client: AsyncClient) -> None:
    r = await client.post("/pairs", json={"pair_id": "BTC-USD"})  # missing source prefix
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_PAIR_ID"


async def test_remove_pair_404_when_missing(client: AsyncClient) -> None:
    r = await client.delete("/pairs/never:X-USD")
    assert r.status_code == 404
    assert r.json()["code"] == "PAIR_NOT_FOUND"


async def test_remove_pair_204_when_exists(client: AsyncClient) -> None:
    await client.post("/pairs", json={"pair_id": "coinbase:BTC-USD"})
    r = await client.delete("/pairs/coinbase:BTC-USD")
    assert r.status_code == 204
    r = await client.get("/pairs")
    assert r.json() == []


# --- /pairs/{id}/candles ---


async def test_get_candles_404_for_unknown_pair(client: AsyncClient) -> None:
    r = await client.get("/pairs/never:X-USD/candles")
    assert r.status_code == 404


async def test_get_candles_returns_window(api_store: Store, client: AsyncClient) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    now = int(time.time())
    candles = [
        Candle(
            pair_id="test:T-USD",
            interval="1d",
            ts_utc=now - i * 86_400,
            open=100.0 + i,
            high=110.0 + i,
            low=90.0 + i,
            close=105.0 + i,
            volume=1000.0,
            source="test",
        )
        for i in range(5)
    ]
    await api_store.upsert_candles(candles)

    r = await client.get("/pairs/test:T-USD/candles?interval=1d&window_days=30")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 5
    # Ascending
    assert body[0]["ts_utc"] < body[-1]["ts_utc"]


# --- /pairs/{id}/indicators/{name} ---


async def test_get_indicator_404_for_unknown_pair(client: AsyncClient) -> None:
    r = await client.get("/pairs/never:X-USD/indicators/SMA")
    assert r.status_code == 404


async def test_get_indicator_422_for_unknown_name(api_store: Store, client: AsyncClient) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    r = await client.get("/pairs/test:T-USD/indicators/NONSENSE")
    assert r.status_code == 422


async def test_get_indicator_sma_returns_series(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    now = int(time.time()) - 86_400 * 30  # 30 days ago start so the window includes them
    candles = [
        Candle(
            pair_id="test:T-USD",
            interval="1d",
            ts_utc=now + i * 86_400,
            open=100.0 + i,
            high=110.0 + i,
            low=90.0 + i,
            close=100.0 + i * 0.5,
            volume=1000.0,
            source="test",
        )
        for i in range(50)
    ]
    await api_store.upsert_candles(candles)

    r = await client.get("/pairs/test:T-USD/indicators/SMA?period=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "SMA"
    assert body["params"]["period"] == 10
    assert len(body["series"]) == 1
    series = body["series"][0]
    assert series["output_key"] == "value"
    # SMA-10 over 50 points produces 41 non-NaN values (warmup is 9 NaN).
    assert len(series["points"]) == 41


# --- /pairs/{id}/sr-candidates ---


async def test_sr_candidates_empty_on_no_candles(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    r = await client.get("/pairs/test:T-USD/sr-candidates")
    assert r.status_code == 200
    assert r.json()["candidates"] == []


# --- /charts (CRUD) ---


async def test_chart_crud_round_trip(api_store: Store, client: AsyncClient) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()

    r = await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))
    assert r.status_code == 201, r.text

    r = await client.get("/charts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["slug"] == "chart-1"

    r = await client.get("/charts/chart-1")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "chart-1"
    assert body["pair"] == "test:T-USD"
    assert body["view"]["drawings"][0]["id"] == "dr-1"


async def test_chart_create_409_on_duplicate_slug(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    payload = _user_chart().model_dump(by_alias=True, mode="json")
    r = await client.post("/charts", json=payload)
    assert r.status_code == 201
    r = await client.post("/charts", json=payload)
    assert r.status_code == 409
    assert r.json()["code"] == "CHART_SLUG_CONFLICT"


async def test_chart_update_404_when_missing(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    payload = _user_chart().model_dump(by_alias=True, mode="json")
    r = await client.put("/charts/chart-1", json=payload)
    assert r.status_code == 404
    assert r.json()["code"] == "CHART_NOT_FOUND"


async def test_chart_update_400_on_slug_mismatch(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))
    # Body says chart-1, path says chart-99 → rejected.
    r = await client.put(
        "/charts/chart-99", json=chart.model_dump(by_alias=True, mode="json")
    )
    assert r.status_code == 400


async def test_chart_get_404_when_missing(client: AsyncClient) -> None:
    r = await client.get("/charts/never-existed")
    assert r.status_code == 404
    assert r.json()["code"] == "CHART_NOT_FOUND"


async def test_chart_delete_round_trip(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))
    r = await client.delete("/charts/chart-1")
    assert r.status_code == 204
    r = await client.get("/charts/chart-1")
    assert r.status_code == 404


async def test_chart_export(api_store: Store, client: AsyncClient) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))
    r = await client.get("/charts/chart-1/export")
    assert r.status_code == 200
    body = r.json()
    assert body["schemaVersion"] == 1


async def test_chart_import_round_trip(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart(slug="imported-1")
    payload = chart.model_dump_json(by_alias=True)
    r = await client.post(
        "/charts/import",
        files={"file": ("chart.json", payload.encode("utf-8"), "application/json")},
    )
    assert r.status_code == 201, r.text
    r = await client.get("/charts/imported-1")
    assert r.status_code == 200


async def test_chart_import_422_on_schema_mismatch(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    payload = chart.model_dump_json(by_alias=True)
    bad = payload.replace('"schemaVersion":1', '"schemaVersion":99')
    r = await client.post(
        "/charts/import",
        files={"file": ("chart.json", bad.encode("utf-8"), "application/json")},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "SCHEMA_MISMATCH"


# --- AI runs ---


async def test_ai_runs_404_for_unknown_pair(client: AsyncClient) -> None:
    r = await client.get("/pairs/never:X-USD/ai_runs")
    assert r.status_code == 404


async def test_ai_runs_empty_for_known_pair_with_no_runs(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    r = await client.get("/pairs/test:T-USD/ai_runs")
    assert r.status_code == 200
    assert r.json() == []
