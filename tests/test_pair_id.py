"""Pair-id parser is the single most-touched module — exercise it hard."""

from __future__ import annotations

import pytest

from signal_trck import pair_id


def test_parse_basic() -> None:
    p = pair_id.parse("coinbase:BTC-USD")
    assert p.source == "coinbase"
    assert p.base == "BTC"
    assert p.quote == "USD"
    assert p.value == "coinbase:BTC-USD"
    assert p.display == "BTC/USD @ coinbase"


def test_parse_lowercases_source_uppercases_symbols() -> None:
    p = pair_id.parse("Coinbase:btc-usd")
    assert p.source == "coinbase"
    assert p.base == "BTC"
    assert p.quote == "USD"


def test_parse_handles_multiletter_quote() -> None:
    p = pair_id.parse("binance:DOGE-USDT")
    assert p.base == "DOGE"
    assert p.quote == "USDT"


@pytest.mark.parametrize(
    "bad",
    [
        "BTC-USD",
        "coinbase:BTC",
        "coinbase:",
        ":BTC-USD",
        "coinbase:BTC-",
        "coinbase:-USD",
        "",
    ],
)
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        pair_id.parse(bad)


def test_str_returns_value() -> None:
    p = pair_id.parse("coinbase:ETH-USD")
    assert str(p) == "coinbase:ETH-USD"
