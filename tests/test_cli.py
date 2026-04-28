"""CLI smoke tests via Typer's ``CliRunner``."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from signal_trck.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert re.match(r"signal-trck \d+\.\d+\.\d+", result.stdout.strip())


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Subcommands are registered.
    assert "pair" in result.stdout
    assert "fetch" in result.stdout
    assert "dev" in result.stdout
    assert "version" in result.stdout


def test_pair_list_empty() -> None:
    result = runner.invoke(app, ["pair", "list"])
    assert result.exit_code == 0
    assert "No pairs tracked" in result.stdout


def test_pair_add_then_list_then_re_add() -> None:
    r1 = runner.invoke(app, ["pair", "add", "coinbase:BTC-USD"])
    assert r1.exit_code == 0
    assert "added" in r1.stdout

    r2 = runner.invoke(app, ["pair", "list"])
    assert r2.exit_code == 0
    assert "coinbase:BTC-USD" in r2.stdout

    r3 = runner.invoke(app, ["pair", "add", "coinbase:BTC-USD"])
    assert r3.exit_code == 0
    assert "already tracked" in r3.stdout


def test_pair_add_rejects_malformed() -> None:
    result = runner.invoke(app, ["pair", "add", "BTC-USD"])
    assert result.exit_code != 0


def test_dev_seed_then_info() -> None:
    r1 = runner.invoke(app, ["dev", "seed", "--days", "30"])
    assert r1.exit_code == 0
    assert "seeded" in r1.stdout

    r2 = runner.invoke(app, ["dev", "info"])
    assert r2.exit_code == 0
    assert "dev:DEMO-USD" in r2.stdout
    assert "30" in r2.stdout
