"""``signal-trck levels <pair>`` — print the S/R candidate set the AI would see."""

from __future__ import annotations

import asyncio
import time

import typer
from rich.console import Console
from rich.table import Table

from signal_trck import pair_id as pair_id_mod
from signal_trck.levels import detect_candidates
from signal_trck.storage import Store

console = Console()


def levels(
    pair: str = typer.Argument(..., help="Canonical pair id, e.g. coinbase:BTC-USD"),
    interval: str = typer.Option("1d", "--interval", "-i"),
    window_days: int = typer.Option(
        90,
        "--window-days",
        "-w",
        help="Look-back window. Matches default chart.json default_window_days.",
    ),
    lookback: int = typer.Option(5, "--lookback", help="Swing detection window."),
    cluster_pct: float = typer.Option(
        0.006, "--cluster-pct", help="Cluster distance as fraction of mean price."
    ),
    top_n: int = typer.Option(50, "--top", help="Max candidates to return."),
) -> None:
    """Compute the S/R candidate set for a pair."""
    pid = pair_id_mod.parse(pair)
    end_ts = int(time.time())
    start_ts = end_ts - window_days * 86_400

    async def _go() -> list:
        async with Store.open() as store:
            candles = await store.get_candles(pid.value, interval, start_ts=start_ts, end_ts=end_ts)
        return detect_candidates(
            candles,
            lookback=lookback,
            cluster_pct=cluster_pct,
            top_n=top_n,
        )

    candidates = asyncio.run(_go())

    if not candidates:
        console.print(
            f"[dim]No candidates for {pid.display} interval={interval} "
            f"window={window_days}d. Did you run `signal-trck fetch`?[/dim]"
        )
        return

    table = Table(title=f"S/R candidates — {pid.display} ({interval}, {window_days}d)")
    table.add_column("id", style="cyan")
    table.add_column("kind")
    table.add_column("price", justify="right")
    table.add_column("touches", justify="right")
    table.add_column("strength", justify="right")
    table.add_column("first_seen")
    table.add_column("last_touch")
    for c in candidates:
        table.add_row(
            c.id,
            c.kind,
            f"{c.price:.2f}",
            str(c.touches),
            f"{c.strength_score:.2f}",
            time.strftime("%Y-%m-%d", time.gmtime(c.first_seen)),
            time.strftime("%Y-%m-%d", time.gmtime(c.last_touch)),
        )
    console.print(table)
