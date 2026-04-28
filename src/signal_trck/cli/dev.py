"""``signal-trck dev ...`` — developer utilities (seed, inspect)."""

from __future__ import annotations

import asyncio
import math
import time

import typer
from rich.console import Console

from signal_trck.storage import Store
from signal_trck.storage.models import Candle

app = typer.Typer(no_args_is_help=True)
console = Console()

_SEED_PAIR_ID = "dev:DEMO-USD"


@app.command("seed")
def seed(
    days: int = typer.Option(180, "--days", help="Days of synthetic daily candles."),
) -> None:
    """Insert a deterministic synthetic pair + candles for tests and UI dev.

    Idempotent: re-running overwrites the same rows. Useful when the UI needs
    something to render but you don't want to hit a real exchange.
    """

    async def _run() -> int:
        async with Store.open() as store:
            await store.add_pair(
                pair_id=_SEED_PAIR_ID,
                base="DEMO",
                quote="USD",
                source="dev",
            )
            now_aligned = (int(time.time()) // 86_400) * 86_400
            candles: list[Candle] = []
            for i in range(days):
                ts = now_aligned - (days - 1 - i) * 86_400
                # Deterministic noisy sine wave around $30k baseline.
                base_price = 30_000 + 5_000 * math.sin(i / 12)
                jitter = 200 * math.sin(i * 1.7)
                open_p = base_price + jitter
                close_p = open_p + 100 * math.sin(i * 0.9)
                high_p = max(open_p, close_p) + 150
                low_p = min(open_p, close_p) - 150
                candles.append(
                    Candle(
                        pair_id=_SEED_PAIR_ID,
                        interval="1d",
                        ts_utc=ts,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=1_000 + 50 * math.sin(i / 5),
                        source="dev",
                    )
                )
            return await store.upsert_candles(candles)

    n = asyncio.run(_run())
    console.print(f"[green]seeded[/green] {n} synthetic 1d candles for {_SEED_PAIR_ID}")


@app.command("info")
def info() -> None:
    """Print DB location and basic stats."""

    async def _run() -> dict:
        async with Store.open() as store:
            pairs = await store.list_pairs()
            counts = {}
            for p in pairs:
                for itv in ("1h", "1d"):
                    n = await store.candle_count(p.pair_id, itv)
                    if n:
                        counts[f"{p.pair_id}@{itv}"] = n
            return {"pairs": pairs, "candle_counts": counts}

    out = asyncio.run(_run())
    console.print(f"[bold]pairs[/bold]: {len(out['pairs'])}")
    for p in out["pairs"]:
        console.print(f"  • {p.pair_id}  pinned={p.is_pinned}")
    if out["candle_counts"]:
        console.print("[bold]candles[/bold]:")
        for k, v in out["candle_counts"].items():
            console.print(f"  • {k}: {v}")
