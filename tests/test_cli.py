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


def test_ai_analyze_dry_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``ai analyze --dry-run`` exercises the full input pipeline (chart-1 read,
    candle load, indicator compute, S/R detection, disclosure summary) without
    making any LLM call. Catches CLI-level argument-parsing and IO regressions
    that test_ai_pipeline.py (which calls analyze_chart directly) doesn't see.
    """
    # Seed the DB with the deterministic dev pair.
    seed_result = runner.invoke(app, ["dev", "seed", "--days", "120"])
    assert seed_result.exit_code == 0

    # Hand-write a chart-1.json against the seed pair.
    chart_in = tmp_path / "chart-1.json"
    chart_in.write_text(
        """\
{
  "schemaVersion": 1,
  "slug": "chart-1",
  "title": "Smoke",
  "pair": "dev:DEMO-USD",
  "provenance": {
    "kind": "user",
    "created_at": "2026-04-29T00:00:00Z"
  },
  "parent_chart_id": null,
  "data": {
    "default_window_days": 60,
    "default_interval": "1d"
  },
  "view": {
    "indicators": [
      {"id": "sma-20", "name": "SMA", "params": {"period": 20}, "pane": 0},
      {"id": "rsi-14", "name": "RSI", "params": {"period": 14}, "pane": 1}
    ],
    "drawings": [],
    "analysis_text": null
  },
  "ai_run": null
}
""",
        encoding="utf-8",
    )
    chart_out = tmp_path / "chart-2.json"

    result = runner.invoke(
        app,
        [
            "ai",
            "analyze",
            "--input",
            str(chart_in),
            "--output",
            str(chart_out),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stdout

    # Dry-run prints a summary of what WOULD be sent to the LLM.
    assert "dry run" in result.stdout
    assert "dev:DEMO-USD" in result.stdout
    assert "candles:" in result.stdout
    assert "indicators:" in result.stdout
    # Indicators are keyed by chart-1 indicator id (sma-20, rsi-14), not name.
    assert "sma-20" in result.stdout
    assert "rsi-14" in result.stdout

    # Dry run must NOT have written the output file.
    assert not chart_out.exists(), "dry-run unexpectedly wrote chart-2.json"


def test_ai_analyze_rejects_missing_chart() -> None:
    """Missing --input file should produce a typer error, not a crash."""
    result = runner.invoke(
        app,
        [
            "ai",
            "analyze",
            "--input",
            "/tmp/nonexistent-chart-do-not-create.json",
            "--output",
            "/tmp/never-written.json",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0


def test_ai_analyze_rejects_when_no_candles_for_pair(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """If the chart's pair has no candles in DB, abort with a helpful message
    (don't try to fetch — the user must explicitly run `signal-trck fetch`)."""
    chart_in = tmp_path / "chart-1.json"
    chart_in.write_text(
        """\
{
  "schemaVersion": 1,
  "slug": "chart-1",
  "title": "Smoke",
  "pair": "test:UNTRACKED-USD",
  "provenance": {"kind": "user", "created_at": "2026-04-29T00:00:00Z"},
  "parent_chart_id": null,
  "data": {"default_window_days": 30, "default_interval": "1d"},
  "view": {"indicators": [], "drawings": [], "analysis_text": null},
  "ai_run": null
}
""",
        encoding="utf-8",
    )
    chart_out = tmp_path / "chart-2.json"
    result = runner.invoke(
        app,
        [
            "ai",
            "analyze",
            "--input",
            str(chart_in),
            "--output",
            str(chart_out),
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert not chart_out.exists()
