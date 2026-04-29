"""``signal-trck pair ...`` commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from signal_trck import pair_id as pair_id_mod
from signal_trck.cli._runner import run_async
from signal_trck.storage import Store

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("add")
def add(
    pair: str = typer.Argument(..., help="Canonical pair id, e.g. 'coinbase:BTC-USD'"),
    pin: bool = typer.Option(False, "--pin", help="Pin the pair to the top of the list."),
) -> None:
    """Track a new pair. Idempotent: re-adding an existing pair is a no-op."""
    pid = pair_id_mod.parse(pair)

    async def _run() -> bool:
        async with Store.open() as store:
            existed = await store.get_pair(pid.value) is not None
            await store.add_pair(
                pair_id=pid.value,
                base=pid.base,
                quote=pid.quote,
                source=pid.source,
                is_pinned=pin,
            )
            if pin and existed:
                await store.pin_pair(pid.value, True)
            return existed

    existed = run_async(_run())
    action = "already tracked" if existed else "added"
    console.print(f"[green]{action}[/green] {pid.display}  [dim]({pid.value})[/dim]")


@app.command("list")
def list_pairs() -> None:
    """List all tracked pairs."""

    async def _run() -> list:
        async with Store.open() as store:
            return await store.list_pairs()

    pairs = run_async(_run())

    if not pairs:
        console.print("[dim]No pairs tracked. Add one: signal-trck pair add coinbase:BTC-USD[/dim]")
        return

    table = Table(title="Tracked pairs")
    table.add_column("pair_id", style="cyan")
    table.add_column("display")
    table.add_column("pinned", justify="center")
    table.add_column("context", overflow="fold")
    for p in pairs:
        table.add_row(
            p.pair_id,
            f"{p.base}/{p.quote} @ {p.source}",
            "★" if p.is_pinned else "",
            p.pinned_context_path or "",
        )
    console.print(table)
