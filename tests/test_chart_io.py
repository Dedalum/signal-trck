"""``chart_io`` round-trips files cleanly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from signal_trck.chart_io import chart_to_json_string, read_chart, write_chart
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


def _user_chart() -> Chart:
    return Chart(
        slug="chart-1",
        title="t",
        pair="coinbase:BTC-USD",
        provenance=Provenance(kind="user", created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        data=ChartData(default_window_days=90, default_interval="1d"),
        view=ChartView(
            indicators=[Indicator(id="sma-50", name="SMA", params={"period": 50}, pane=0)],
            drawings=[
                Drawing(
                    id="dr-1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1, price=42_000.0)],
                    style=Style(color="#000"),
                )
            ],
        ),
    )


def test_write_then_read_returns_equivalent_chart(tmp_path: Path) -> None:
    chart = _user_chart()
    path = tmp_path / "chart-1.json"
    written = write_chart(chart, path)
    assert written == path
    assert path.exists()

    loaded = read_chart(path)
    assert loaded == chart


def test_chart_to_json_string_is_valid_json(tmp_path: Path) -> None:
    import json

    s = chart_to_json_string(_user_chart())
    parsed = json.loads(s)
    assert parsed["schemaVersion"] == 1
    assert parsed["pair"] == "coinbase:BTC-USD"


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "chart.json"
    write_chart(_user_chart(), nested)
    assert nested.exists()


def test_read_rejects_unknown_schema_version(tmp_path: Path) -> None:
    """Schema-version mismatch must surface as a validation error, not a silent load."""
    path = tmp_path / "future.json"
    payload = chart_to_json_string(_user_chart())
    payload = payload.replace('"schemaVersion": 1', '"schemaVersion": 99')
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValidationError, match="unsupported schemaVersion 99"):
        read_chart(path)


def test_read_rejects_extra_fields(tmp_path: Path) -> None:
    """``extra='forbid'`` catches typos like 'colour' instead of 'color'."""
    import json

    path = tmp_path / "typo.json"
    payload = json.loads(chart_to_json_string(_user_chart()))
    payload["view"]["drawings"][0]["style"]["colour"] = "#fff"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_chart(path)
