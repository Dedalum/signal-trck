"""Pluggable price-feed adapters. v1 ships Coinbase only."""

from signal_trck.adapters.base import CandleAdapter
from signal_trck.adapters.coinbase import CoinbaseAdapter

__all__ = ["CandleAdapter", "CoinbaseAdapter"]


def build_adapter(source: str) -> CandleAdapter:
    """Pick an adapter by source name."""
    if source == "coinbase":
        return CoinbaseAdapter()
    raise ValueError(f"unknown adapter source: {source!r}")
