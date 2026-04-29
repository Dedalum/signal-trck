"""``signal-trck indicators ...`` — compute and display indicator series."""

from __future__ import annotations

import numpy as np
import typer
from rich.console import Console
from rich.table import Table

from signal_trck import pair_id as pair_id_mod
from signal_trck.cli._runner import run_async
from signal_trck.indicators import IndicatorParams
from signal_trck.indicators.cache import compute_or_load
from signal_trck.storage import Store

app = typer.Typer(no_args_is_help=True)
console = Console()


def _print_series(name: str, output_key: str, ts: np.ndarray, values: np.ndarray) -> None:
    """Print the last 20 non-NaN points of an indicator series as a table."""
    mask = ~np.isnan(values)
    ts_nn = ts[mask]
    vals_nn = values[mask]
    if len(vals_nn) == 0:
        console.print(f"[yellow]{name}.{output_key}: no non-NaN values yet[/yellow]")
        return
    tail = list(zip(ts_nn[-20:], vals_nn[-20:], strict=True))
    table = Table(title=f"{name}.{output_key} (last {len(tail)} of {len(vals_nn)})")
    table.add_column("ts_utc", justify="right")
    table.add_column("value", justify="right")
    for t, v in tail:
        table.add_row(str(int(t)), f"{v:.4f}")
    console.print(table)


def _run(name: str, params: IndicatorParams, pair: str, interval: str) -> None:
    pid = pair_id_mod.parse(pair)

    async def _go() -> dict:
        async with Store.open() as store:
            return await compute_or_load(
                store,
                pair_id=pid.value,
                interval=interval,
                name=name,
                params=params,
            )

    series = run_async(_go())
    for output_key, s in series.items():
        _print_series(name, output_key, s.ts_utc, s.values)


@app.command("sma")
def sma(
    pair: str = typer.Argument(..., help="Canonical pair id, e.g. coinbase:BTC-USD"),
    period: int = typer.Option(50, "--period", "-p", help="Window length"),
    interval: str = typer.Option("1d", "--interval", "-i"),
) -> None:
    """Simple moving average."""
    _run("SMA", {"period": period}, pair, interval)


@app.command("ema")
def ema(
    pair: str = typer.Argument(...),
    period: int = typer.Option(50, "--period", "-p"),
    interval: str = typer.Option("1d", "--interval", "-i"),
) -> None:
    """Exponential moving average."""
    _run("EMA", {"period": period}, pair, interval)


@app.command("rsi")
def rsi(
    pair: str = typer.Argument(...),
    period: int = typer.Option(14, "--period", "-p"),
    interval: str = typer.Option("1d", "--interval", "-i"),
) -> None:
    """Relative strength index."""
    _run("RSI", {"period": period}, pair, interval)


@app.command("macd")
def macd(
    pair: str = typer.Argument(...),
    fast: int = typer.Option(12, "--fast"),
    slow: int = typer.Option(26, "--slow"),
    signal: int = typer.Option(9, "--signal"),
    interval: str = typer.Option("1d", "--interval", "-i"),
) -> None:
    """Moving average convergence/divergence."""
    _run("MACD", {"fast": fast, "slow": slow, "signal": signal}, pair, interval)


@app.command("bb")
def bb(
    pair: str = typer.Argument(...),
    period: int = typer.Option(20, "--period", "-p"),
    nbdev: float = typer.Option(2.0, "--nbdev"),
    interval: str = typer.Option("1d", "--interval", "-i"),
) -> None:
    """Bollinger bands."""
    _run("BB", {"period": period, "nbdev": nbdev}, pair, interval)
