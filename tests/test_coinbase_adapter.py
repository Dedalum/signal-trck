"""Coinbase adapter — exercise pagination + parsing with a mocked transport.

We use ``httpx.MockTransport`` rather than real HTTP / cassettes for these
tests because the math (chunk boundaries, dedup, ascending-sort) is the
interesting bit, not the wire format. A separate cassette-recorded smoke
test against real Coinbase can be added later via ``pytest-recording``.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from signal_trck.adapters.coinbase import API_ROOT, CoinbaseAdapter

_Handler = Callable[[httpx.Request], httpx.Response]


def _make_candle(ts: int, price: float, volume: float = 1000.0) -> dict[str, str]:
    """Coinbase Advanced Trade returns string fields."""
    return {
        "start": str(ts),
        "low": str(price - 1),
        "high": str(price + 1),
        "open": str(price),
        "close": str(price),
        "volume": str(volume),
    }


def _build_adapter(handler: _Handler, rate_limit_burst: int = 10) -> CoinbaseAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    # rate_limit_rps high to avoid sleeping in tests
    return CoinbaseAdapter(client=client, rate_limit_rps=1000, rate_limit_burst=rate_limit_burst)


async def test_single_request_window() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "candles": [
                    _make_candle(1_700_000_000, 42_000),
                    _make_candle(1_700_086_400, 42_500),
                    _make_candle(1_700_172_800, 43_000),
                ]
            },
        )

    adapter = _build_adapter(handler)
    candles = await adapter.fetch_candles(
        base="BTC",
        quote="USD",
        interval="1d",
        start_ts=1_700_000_000,
        end_ts=1_700_172_800,
    )

    assert len(candles) == 3
    assert candles[0].ts_utc == 1_700_000_000  # ascending
    assert candles[-1].ts_utc == 1_700_172_800
    assert all(c.source == "coinbase" for c in candles)
    assert all(c.pair_id == "coinbase:BTC-USD" for c in candles)
    assert all(c.interval == "1d" for c in candles)
    assert candles[0].open == 42_000.0
    assert len(captured) == 1
    assert "BTC-USD/candles" in str(captured[0].url)
    assert captured[0].url.params["granularity"] == "ONE_DAY"


async def test_paginates_when_window_exceeds_max() -> None:
    """A 800-day window at daily resolution should fan out to 3 chunks (350+350+100)."""
    requests_made: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        start = int(request.url.params["start"])
        end = int(request.url.params["end"])
        # Return one synthetic candle per day in the requested window.
        candles = []
        ts = start
        while ts <= end:
            candles.append(_make_candle(ts, 100.0 + len(candles)))
            ts += 86_400
        return httpx.Response(200, json={"candles": candles})

    adapter = _build_adapter(handler)
    end_ts = 1_700_000_000
    start_ts = end_ts - 800 * 86_400

    candles = await adapter.fetch_candles(
        base="BTC",
        quote="USD",
        interval="1d",
        start_ts=start_ts,
        end_ts=end_ts,
    )

    assert len(requests_made) == 3, "expected 3 chunks for 800 days @ 350 max"
    # Ascending, no duplicates.
    timestamps = [c.ts_utc for c in candles]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))


async def test_dedups_chunk_boundary_overlap() -> None:
    """If the source returns a candle on an exact chunk boundary in two
    consecutive responses, only one should survive."""
    boundary_ts = 1_700_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candles": [
                    _make_candle(boundary_ts, 100.0),
                ]
            },
        )

    adapter = _build_adapter(handler)
    candles = await adapter.fetch_candles(
        base="BTC",
        quote="USD",
        interval="1d",
        start_ts=boundary_ts - 100,
        end_ts=boundary_ts + 100,
    )
    assert len(candles) == 1


async def test_empty_window_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not have been called")

    adapter = _build_adapter(handler)
    candles = await adapter.fetch_candles(
        base="BTC",
        quote="USD",
        interval="1d",
        start_ts=1000,
        end_ts=1000,
    )
    assert candles == []


async def test_rejects_unsupported_interval() -> None:
    adapter = CoinbaseAdapter()
    with pytest.raises(ValueError, match="1w"):
        await adapter.fetch_candles(
            base="BTC", quote="USD", interval="1w", start_ts=0, end_ts=86400
        )


async def test_passes_correct_granularity_for_hourly() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"candles": []})

    adapter = _build_adapter(handler)
    await adapter.fetch_candles(
        base="ETH",
        quote="USD",
        interval="1h",
        start_ts=1_700_000_000,
        end_ts=1_700_000_000 + 3600 * 50,
    )
    assert captured[0].url.params["granularity"] == "ONE_HOUR"


def test_api_root_is_advanced_trade() -> None:
    """Sanity: the URL we hit is the public Advanced Trade endpoint, not the
    auth-required signed one. Catches accidental endpoint changes."""
    assert API_ROOT == "https://api.coinbase.com/api/v3/brokerage/market"
