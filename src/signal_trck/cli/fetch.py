"""``signal-trck fetch <pair>`` — populate candles from the source adapter."""

from __future__ import annotations

import asyncio
import time

import structlog
import typer
from rich.console import Console

from signal_trck import pair_id as pair_id_mod
from signal_trck.adapters import build_adapter
from signal_trck.storage import Store

console = Console()
log = structlog.get_logger(__name__)

# Default backfill window per interval. Plan A.1 default: 1y daily.
_DEFAULT_DAYS: dict[str, int] = {
    "1h": 90,
    "1d": 365,
}


def fetch(
    pair: str = typer.Argument(..., help="Canonical pair id, e.g. 'coinbase:BTC-USD'"),
    interval: str = typer.Option("1d", "--interval", "-i", help="1h | 1d"),
    days: int = typer.Option(
        0,
        "--days",
        "-d",
        help="Backfill window in days. 0 = use default per interval (1d→365, 1h→90).",
    ),
) -> None:
    """Fetch candles for a tracked pair and store them.

    Re-running is idempotent: existing candles are upserted in place.
    """
    pid = pair_id_mod.parse(pair)
    if interval not in _DEFAULT_DAYS:
        raise typer.BadParameter(f"interval must be one of {list(_DEFAULT_DAYS)}")
    window_days = days or _DEFAULT_DAYS[interval]

    end_ts = int(time.time())
    start_ts = end_ts - window_days * 86_400

    async def _run() -> int:
        adapter = build_adapter(pid.source)
        async with adapter:
            candles = await adapter.fetch_candles(
                base=pid.base,
                quote=pid.quote,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        async with Store.open() as store:
            existing = await store.get_pair(pid.value)
            if existing is None:
                await store.add_pair(pid.value, pid.base, pid.quote, pid.source)
                log.info("fetch.pair_auto_added", pair=pid.value)
            return await store.upsert_candles(candles)

    n = asyncio.run(_run())
    console.print(
        f"[green]ok[/green] fetched {n} candles for {pid.display} "
        f"interval={interval} window={window_days}d"
    )
