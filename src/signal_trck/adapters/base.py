"""Adapter contract. Promote to ABC if shared base behavior emerges."""

from __future__ import annotations

from typing import Protocol

from signal_trck.storage.models import Candle


class CandleAdapter(Protocol):
    """Fetch OHLCV candles from a single price source."""

    source: str

    async def fetch_candles(
        self,
        base: str,
        quote: str,
        interval: str,
        start_ts: int,
        end_ts: int,
    ) -> list[Candle]:
        """Fetch candles for ``[start_ts, end_ts]`` inclusive.

        ``interval`` is one of ``"1h" | "1d" | "1w"``. Implementations should
        handle pagination internally and respect their own rate limits.
        Returned candles carry ``source`` set to the adapter's name.
        """
        ...
