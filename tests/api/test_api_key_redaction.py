"""API-key sentinel test (Decision 25).

Set ``ANTHROPIC_API_KEY=sentinel-xyz-12345``, hit every error path + every
successful response, grep response bodies + headers for the sentinel — must
never appear. Pins the no-key-on-the-wire invariant.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from signal_trck.chart_schema import Chart, ChartData, ChartView, Provenance
from signal_trck.storage import Store

SENTINEL = "sentinel-key-xyz-12345-must-never-appear"


@pytest.fixture(autouse=True)
def _set_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set sentinel-keyed env vars for the duration of every test in this file."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL)
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.setenv("MOONSHOT_API_KEY", SENTINEL)
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)


def _seed_chart() -> Chart:
    return Chart(
        slug="chart-1",
        title="Sentinel test",
        pair="test:T-USD",
        provenance=Provenance(
            kind="user",
            created_at=datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        ),
        data=ChartData(default_window_days=30, default_interval="1d"),
        view=ChartView(),
    )


async def test_sentinel_never_appears_in_any_response(
    api_store: Store, client: AsyncClient
) -> None:
    """Walk every response surface and grep for the sentinel."""
    await api_store.add_pair("test:T-USD", "T", "USD", "test")

    chart = _seed_chart()
    chart_payload = chart.model_dump(by_alias=True, mode="json")

    requests = [
        ("GET", "/healthz", None, None),
        ("GET", "/pairs", None, None),
        ("POST", "/pairs", {"pair_id": "coinbase:BTC-USD"}, None),
        ("POST", "/pairs", {"pair_id": "BAD-FORMAT"}, None),  # 400 path
        ("DELETE", "/pairs/never:X-USD", None, None),  # 404 path
        ("GET", "/pairs/test:T-USD/candles?interval=1d&window_days=10", None, None),
        ("GET", "/pairs/test:T-USD/sr-candidates", None, None),
        ("POST", "/charts", chart_payload, None),
        ("GET", "/charts", None, None),
        ("GET", "/charts/chart-1", None, None),
        ("GET", "/charts/never-existed", None, None),  # 404 path
        ("GET", "/charts/chart-1/export", None, None),
        ("GET", "/pairs/test:T-USD/ai_runs", None, None),
    ]
    for method, path, json, _ in requests:
        if method == "GET":
            r = await client.get(path)
        elif method == "POST":
            r = await client.post(path, json=json)
        elif method == "DELETE":
            r = await client.delete(path)
        else:  # pragma: no cover
            raise AssertionError(method)
        body_text = r.text
        assert SENTINEL not in body_text, f"{method} {path} leaked sentinel"
        for hdr_name, hdr_val in r.headers.items():
            assert SENTINEL not in hdr_val, f"{method} {path} leaked sentinel in header {hdr_name}"
