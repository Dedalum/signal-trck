"""Coinbase Advanced Trade public market-data adapter.

Endpoint: ``GET /api/v3/brokerage/market/products/{product_id}/candles``
Public (no auth), 10 req/s per IP, max 350 candles per request.

Granularity is an enum string (``ONE_DAY``, ``ONE_HOUR``, …). Weekly is
not natively supported; we fetch daily and let the analytics layer roll
up to weekly when needed (Phase A.2).
"""

from __future__ import annotations

from typing import Final

import httpx
import structlog

from signal_trck.adapters._rate_limit import TokenBucket
from signal_trck.storage.models import Candle

log = structlog.get_logger(__name__)

API_ROOT: Final[str] = "https://api.coinbase.com/api/v3/brokerage/market"
MAX_CANDLES_PER_REQUEST: Final[int] = 350

# interval -> (granularity_enum, granularity_seconds)
_GRANULARITY: dict[str, tuple[str, int]] = {
    "1h": ("ONE_HOUR", 3600),
    "1d": ("ONE_DAY", 86_400),
}


class CoinbaseAdapter:
    """Fetch candles from Coinbase Advanced Trade public market endpoint."""

    source: str = "coinbase"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limit_rps: float = 8.0,
        rate_limit_burst: int = 8,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._rate = TokenBucket(rate=rate_limit_rps, capacity=rate_limit_burst)

    async def __aenter__(self) -> CoinbaseAdapter:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_candles(
        self,
        base: str,
        quote: str,
        interval: str,
        start_ts: int,
        end_ts: int,
    ) -> list[Candle]:
        if interval not in _GRANULARITY:
            raise ValueError(f"coinbase adapter supports {list(_GRANULARITY)}; got {interval!r}")
        if start_ts >= end_ts:
            return []

        granularity_enum, step = _GRANULARITY[interval]
        product_id = f"{base.upper()}-{quote.upper()}"
        pair_id = f"{self.source}:{product_id}"
        chunk_seconds = step * MAX_CANDLES_PER_REQUEST

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)

        all_candles: list[Candle] = []
        cursor = start_ts
        while cursor < end_ts:
            window_end = min(cursor + chunk_seconds, end_ts)
            chunk = await self._fetch_chunk(
                product_id=product_id,
                pair_id=pair_id,
                interval=interval,
                granularity_enum=granularity_enum,
                start=cursor,
                end=window_end,
            )
            all_candles.extend(chunk)
            cursor = window_end + 1

        # Coinbase returns newest-first; canonicalize to ascending.
        all_candles.sort(key=lambda c: c.ts_utc)
        # Deduplicate on ts_utc (chunk boundaries can produce overlap).
        seen: set[int] = set()
        deduped: list[Candle] = []
        for c in all_candles:
            if c.ts_utc in seen:
                continue
            seen.add(c.ts_utc)
            deduped.append(c)
        return deduped

    async def _fetch_chunk(
        self,
        *,
        product_id: str,
        pair_id: str,
        interval: str,
        granularity_enum: str,
        start: int,
        end: int,
    ) -> list[Candle]:
        await self._rate.acquire()
        url = f"{API_ROOT}/products/{product_id}/candles"
        params = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity_enum,
        }
        assert self._client is not None
        log.debug("coinbase.fetch", product=product_id, start=start, end=end)
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
        raw_candles = payload.get("candles", [])
        return [
            Candle(
                pair_id=pair_id,
                interval=interval,
                ts_utc=int(item["start"]),
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
                source=self.source,
            )
            for item in raw_candles
        ]
