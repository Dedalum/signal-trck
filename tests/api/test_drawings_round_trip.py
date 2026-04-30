"""Drawings round-trip via PUT /charts/{slug}.

Save a chart with drawings, fetch it back, deep-equal modulo float
precision. This is the contract test for the drawing persistence path —
if the API + Store + Pydantic round-trip matches, the frontend can rely
on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient

from signal_trck.chart_schema import (
    Anchor,
    Chart,
    ChartData,
    ChartView,
    Drawing,
    Provenance,
    Style,
)
from signal_trck.storage import Store


def _chart_with_drawings(slug: str = "chart-1") -> Chart:
    return Chart(
        slug=slug,
        title="Drawings test",
        pair="test:T-USD",
        provenance=Provenance(
            kind="user",
            created_at=datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        ),
        data=ChartData(default_window_days=90, default_interval="1d"),
        view=ChartView(
            drawings=[
                Drawing(
                    id="dr-h1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1704067200, price=42_000.0)],
                    style=Style(color="#2a9d8f", dash="solid"),
                ),
                Drawing(
                    id="dr-t1",
                    kind="trend",
                    anchors=[
                        Anchor(ts_utc=1704067200, price=41_000.0),
                        Anchor(ts_utc=1706659200, price=43_500.0),
                    ],
                    style=Style(color="#264653", dash="dashed"),
                ),
                Drawing(
                    id="dr-r1",
                    kind="rect",
                    anchors=[
                        Anchor(ts_utc=1704067200, price=41_500.0),
                        Anchor(ts_utc=1706659200, price=42_500.0),
                    ],
                    style=Style(color="#e76f51", dash="dotted"),
                ),
            ],
        ),
    )


async def test_create_then_get_drawings_round_trip(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _chart_with_drawings()
    payload = chart.model_dump(by_alias=True, mode="json")

    r = await client.post("/charts", json=payload)
    assert r.status_code == 201, r.text

    r = await client.get("/charts/chart-1")
    assert r.status_code == 200
    body = r.json()
    drawings = body["view"]["drawings"]
    assert len(drawings) == 3
    by_id = {d["id"]: d for d in drawings}
    assert by_id["dr-h1"]["kind"] == "horizontal"
    assert by_id["dr-h1"]["anchors"][0]["price"] == 42_000.0
    assert by_id["dr-t1"]["kind"] == "trend"
    assert by_id["dr-t1"]["style"]["dash"] == "dashed"
    assert by_id["dr-r1"]["kind"] == "rect"


async def test_update_chart_replaces_drawings(
    api_store: Store, client: AsyncClient
) -> None:
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _chart_with_drawings()
    await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))

    # Replace drawings: keep only one with a new price.
    new_chart = chart.model_copy(
        update={
            "view": chart.view.model_copy(
                update={
                    "drawings": [
                        Drawing(
                            id="dr-only",
                            kind="horizontal",
                            anchors=[Anchor(ts_utc=1704067200, price=99_999.0)],
                            style=Style(color="#a594f9", dash="solid"),
                        ),
                    ],
                }
            ),
        }
    )
    r = await client.put(
        "/charts/chart-1", json=new_chart.model_dump(by_alias=True, mode="json")
    )
    assert r.status_code == 200, r.text

    r = await client.get("/charts/chart-1")
    body = r.json()
    drawings = body["view"]["drawings"]
    assert len(drawings) == 1
    assert drawings[0]["id"] == "dr-only"
    assert drawings[0]["anchors"][0]["price"] == 99_999.0


async def test_drawings_preserve_order(api_store: Store, client: AsyncClient) -> None:
    """Drawings round-trip in input order so render-stack stays predictable."""
    await api_store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _chart_with_drawings()
    await client.post("/charts", json=chart.model_dump(by_alias=True, mode="json"))
    r = await client.get("/charts/chart-1")
    ids = [d["id"] for d in r.json()["view"]["drawings"]]
    assert ids == ["dr-h1", "dr-t1", "dr-r1"]
