"""Top-level Typer app. Subcommands live in sibling modules."""

from __future__ import annotations

import typer

from signal_trck import __version__, log
from signal_trck.cli import ai, dev, fetch, indicators, levels, pair
from signal_trck.cli import serve as serve_cmd

app = typer.Typer(
    name="signal-trck",
    help="Personal crypto charting + LLM-grounded technical analysis.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(pair.app, name="pair", help="Manage tracked crypto pairs.")
app.add_typer(dev.app, name="dev", help="Developer utilities.")
app.add_typer(indicators.app, name="indicators", help="Compute indicator series.")
app.add_typer(ai.app, name="ai", help="Run grounded LLM analyses on a chart.")
ai.app.command("analyze")(ai.analyze)
app.command("fetch")(fetch.fetch)
app.command("levels")(levels.levels)
app.command("serve")(serve_cmd.serve)


@app.callback()
def _root(
    log_level: str = typer.Option("INFO", "--log-level", help="DEBUG | INFO | WARNING"),
    log_format: str = typer.Option("console", "--log-format", help="console | json"),
) -> None:
    log.configure(level=log_level, fmt=log_format)  # type: ignore[arg-type]
    log.bind_run()


@app.command("version")
def version() -> None:
    """Print signal-trck version and exit."""
    typer.echo(f"signal-trck {__version__}")


if __name__ == "__main__":
    app()
