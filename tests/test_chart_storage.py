"""``Store`` chart CRUD round-trip + slug allocator + remove_pair tests.

These cover the migration-v4 surface: charts/drawings/indicator_refs tables
and the new chart Pydantic-model round-trip. Round-trip-as-property is the
contract test for Phase B.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
from signal_trck.storage import (
    ChartNotFound,
    ChartSlugConflict,
    PairNotFound,
    Store,
)


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
            indicators=[
                Indicator(id="sma-50", name="SMA", params={"period": 50}, pane=0),
                Indicator(id="rsi-14", name="RSI", params={"period": 14}, pane=1),
            ],
            drawings=[
                Drawing(
                    id="dr-1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1704067200, price=42000.0)],
                    style=Style(color="#2a9d8f", dash="solid"),
                ),
                Drawing(
                    id="dr-2",
                    kind="trend",
                    anchors=[
                        Anchor(ts_utc=1704067200, price=41000.0),
                        Anchor(ts_utc=1706659200, price=43500.0),
                    ],
                    style=Style(color="#264653", dash="dashed"),
                ),
            ],
            analysis_text="Test thesis.",
        ),
    )


async def test_round_trip_user_chart(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await store.create_chart(chart)
    loaded = await store.get_chart("chart-1")
    # Pydantic models compare by field equality.
    assert loaded == chart


async def test_create_chart_rejects_unknown_pair(store: Store) -> None:
    with pytest.raises(PairNotFound):
        await store.create_chart(_user_chart(pair="unknown:X-USD"))


async def test_create_chart_rejects_duplicate_slug(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await store.create_chart(chart)
    with pytest.raises(ChartSlugConflict):
        await store.create_chart(chart)


async def test_update_chart_replaces_drawings(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await store.create_chart(chart)

    # Replace drawings: drop dr-2, change dr-1 price.
    new_chart = chart.model_copy(
        update={
            "view": chart.view.model_copy(
                update={
                    "drawings": [
                        Drawing(
                            id="dr-1",
                            kind="horizontal",
                            anchors=[Anchor(ts_utc=1704067200, price=42500.0)],
                            style=Style(color="#e76f51", dash="dotted"),
                        ),
                    ],
                }
            ),
        }
    )
    await store.update_chart(new_chart)

    loaded = await store.get_chart("chart-1")
    assert len(loaded.view.drawings) == 1
    assert loaded.view.drawings[0].anchors[0].price == 42500.0
    assert loaded.view.drawings[0].style.dash == "dotted"


async def test_update_chart_rejects_missing_slug(store: Store) -> None:
    with pytest.raises(ChartNotFound):
        await store.update_chart(_user_chart(slug="never-existed"))


async def test_get_chart_rejects_missing_slug(store: Store) -> None:
    with pytest.raises(ChartNotFound):
        await store.get_chart("never-existed")


async def test_list_charts_filters_and_orders(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filter by ``pair_id``; order by ``updated_at_unix DESC``.

    Time is mocked so that ordering is deterministic — three rapid creates
    within the same wall-clock second otherwise share an ``updated_at_unix``
    and SQLite gives us insertion order, which isn't the documented contract.
    """
    await store.add_pair("test:T-USD", "T", "USD", "test")
    await store.add_pair("test:U-USD", "U", "USD", "test")

    fake_clock = iter([1_700_000_001, 1_700_000_002, 1_700_000_003])
    monkeypatch.setattr("signal_trck.storage.store.time.time", lambda: next(fake_clock))

    await store.create_chart(_user_chart(slug="chart-1", pair="test:T-USD"))
    await store.create_chart(_user_chart(slug="chart-2", pair="test:T-USD"))
    await store.create_chart(_user_chart(slug="chart-3", pair="test:U-USD"))

    t_charts = await store.list_charts(pair_id="test:T-USD")
    assert {c.slug for c in t_charts} == {"chart-1", "chart-2"}

    all_charts = await store.list_charts()
    assert [c.slug for c in all_charts] == ["chart-3", "chart-2", "chart-1"]


async def test_delete_chart_cascades(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    chart = _user_chart()
    await store.create_chart(chart)
    await store.delete_chart("chart-1")
    with pytest.raises(ChartNotFound):
        await store.get_chart("chart-1")
    # Drawings + indicator_refs cascaded — verify directly.
    cur = await store.conn.execute(
        "SELECT COUNT(*) FROM drawings WHERE chart_slug = ?", ("chart-1",)
    )
    row = await cur.fetchone()
    assert row is not None and row[0] == 0
    cur = await store.conn.execute(
        "SELECT COUNT(*) FROM indicator_refs WHERE chart_slug = ?", ("chart-1",)
    )
    row = await cur.fetchone()
    assert row is not None and row[0] == 0


async def test_delete_chart_rejects_missing_slug(store: Store) -> None:
    with pytest.raises(ChartNotFound):
        await store.delete_chart("never-existed")


async def test_next_slug_monotonic(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    s1 = await store.next_slug("test:T-USD")
    s2 = await store.next_slug("test:T-USD")
    s3 = await store.next_slug("test:T-USD")
    assert (s1, s2, s3) == ("chart-1", "chart-2", "chart-3")


async def test_next_slug_rejects_unknown_pair(store: Store) -> None:
    with pytest.raises(PairNotFound):
        await store.next_slug("never:X-USD")


async def test_next_slug_independent_per_pair(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    await store.add_pair("test:U-USD", "U", "USD", "test")
    assert await store.next_slug("test:T-USD") == "chart-1"
    assert await store.next_slug("test:U-USD") == "chart-1"
    assert await store.next_slug("test:T-USD") == "chart-2"


async def test_remove_pair_cascades_to_charts(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    await store.create_chart(_user_chart())
    await store.remove_pair("test:T-USD")
    assert await store.get_pair("test:T-USD") is None
    with pytest.raises(ChartNotFound):
        await store.get_chart("chart-1")


async def test_remove_pair_idempotent(store: Store) -> None:
    # Removing a missing pair is fine — caller decides whether to 404.
    await store.remove_pair("never:X-USD")
