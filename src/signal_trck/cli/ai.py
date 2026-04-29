"""``signal-trck ai analyze`` — produce a grounded, AI-annotated chart.

Reads a chart-1.json (the user's chart), pulls the same candles +
indicators + S/R candidates the UI sees, calls the configured LLM
provider, validates the response, and writes chart-2.json + an
``ai_runs`` audit row.

The LLM never invents prices: it picks a ``candidate_id`` from a typed
list, and the server resolves the ID to a real price at insert time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog
import typer
from rich.console import Console

from signal_trck import pair_id as pair_id_mod
from signal_trck.chart_io import read_chart, write_chart
from signal_trck.chart_schema import Chart
from signal_trck.cli._runner import run_async
from signal_trck.config import AppConfig
from signal_trck.indicators.cache import compute_or_load
from signal_trck.levels import detect_candidates
from signal_trck.llm import (
    DEFAULT_MODELS,
    SUPPORTED_PROVIDERS,
    PipelineError,
    Provider,
    analyze_chart,
    build_client,
)
from signal_trck.storage import Store

app = typer.Typer(no_args_is_help=True)
console = Console()
log = structlog.get_logger(__name__)


def analyze(
    input: Path = typer.Option(
        ..., "--input", "-i", help="Path to chart-1.json (the user's chart)."
    ),
    output: Path = typer.Option(
        ..., "--output", "-o", help="Path where chart-2.json will be written."
    ),
    context: Path | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Optional markdown file of qualitative context to feed the LLM.",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help=f"LLM provider. One of: {list(SUPPORTED_PROVIDERS)}. "
        "Default: $LLM_PROVIDER from .env.",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Override the per-provider default model."
    ),
    slug: str = typer.Option("chart-2", "--slug", help="Slug for the produced AI chart."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print proposed chart-2 to stdout without calling the LLM, writing files, "
        "or touching the DB. Useful for verifying inputs.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the data-exfil confirmation prompt."),
) -> None:
    """Run the AI analysis pipeline on a user-authored chart-1.json."""
    chart_in = read_chart(input)
    pid = pair_id_mod.parse(chart_in.pair)

    cfg = AppConfig()
    chosen_provider: Provider = provider or cfg.settings.llm_provider  # type: ignore[assignment]
    if chosen_provider not in SUPPORTED_PROVIDERS:
        raise typer.BadParameter(f"unsupported provider {chosen_provider!r}")
    chosen_model = model or cfg.settings.llm_model or DEFAULT_MODELS[chosen_provider]

    context_md: str | None = None
    if context is not None:
        if not context.exists():
            raise typer.BadParameter(f"context file not found: {context}")
        context_md = context.read_text(encoding="utf-8")

    run_async(
        _run(
            chart_in=chart_in,
            pair_id=pid.value,
            interval=chart_in.data.default_interval,
            window_days=chart_in.data.default_window_days,
            output_path=output,
            context_md=context_md,
            context_path=str(context) if context is not None else None,
            provider=chosen_provider,
            model=chosen_model,
            api_key=cfg.provider_api_key(chosen_provider),
            slug=slug,
            dry_run=dry_run,
            confirm=not yes,
        )
    )


async def _run(
    *,
    chart_in: Chart,
    pair_id: str,
    interval: str,
    window_days: int,
    output_path: Path,
    context_md: str | None,
    context_path: str | None,
    provider: Provider,
    model: str,
    api_key: str,
    slug: str,
    dry_run: bool,
    confirm: bool,
) -> None:
    end_ts = int(time.time())
    start_ts = end_ts - window_days * 86_400

    async with Store.open() as store:
        candles = await store.get_candles(pair_id, interval, start_ts=start_ts, end_ts=end_ts)
        if not candles:
            raise typer.BadParameter(
                f"no candles for {pair_id} interval={interval}; "
                f"run `signal-trck fetch {pair_id} -i {interval}` first"
            )

        # Compute indicators referenced by the chart-1 view (same numbers UI sees).
        indicators: dict = {}
        for ind in chart_in.view.indicators:
            try:
                series = await compute_or_load(
                    store,
                    pair_id=pair_id,
                    interval=interval,
                    name=ind.name,
                    params=dict(ind.params),
                )
            except ValueError as e:
                log.warning("ai.skip_unsupported_indicator", name=ind.name, error=str(e))
                continue
            for k, v in series.items():
                # Key by the chart-1 indicator's stable id so multiple instances
                # of the same indicator (e.g. SMA-50 + SMA-200) don't collide.
                indicators[ind.id if k == "value" else f"{ind.id}.{k}"] = v

        candidates = detect_candidates(candles)

    if dry_run:
        _print_dry_run(
            chart_in=chart_in,
            candle_count=len(candles),
            indicator_keys=list(indicators.keys()),
            candidate_count=len(candidates),
            context_md=context_md,
            provider=provider,
            model=model,
        )
        return

    # Data-exfil disclosure.
    approx_tokens = _estimate_tokens(
        chart_in, len(candles), len(indicators), len(candidates), context_md
    )
    console.print(f"[yellow]→ Sending ~{approx_tokens:,} tokens to {provider}:{model}.[/yellow]")
    if context_md:
        console.print(f"[yellow]  (includes context file, {len(context_md):,} chars)[/yellow]")
    if confirm:
        proceed = typer.confirm("Proceed with the analysis?", default=True)
        if not proceed:
            console.print("[dim]aborted by user[/dim]")
            return

    if not api_key:
        raise typer.BadParameter(
            f"no API key for provider {provider!r}; set the corresponding env var "
            f"(e.g. {provider.upper()}_API_KEY=...) in .env or your shell"
        )
    client = build_client(provider=provider, api_key=api_key, model=model)

    log.info("ai.analyze.start", pair=pair_id, provider=provider, model=model)
    try:
        result = analyze_chart(
            chart_in=chart_in,
            candles=candles,
            indicators=indicators,
            candidates=candidates,
            context_md=context_md,
            client=client,
            output_slug=slug,
        )
    except PipelineError as e:
        console.print(f"[red]✗ AI pipeline failed:[/red] {e}")
        raise typer.Exit(code=1) from e

    # Persist audit row + write chart-2.json.
    async with Store.open() as store:
        await store.write_ai_run(
            pair_id=result.audit.pair_id,
            chart_slug=result.audit.chart_slug,
            provider=result.audit.provider,
            model=result.audit.model,
            prompt_template_version=result.audit.prompt_template_version,
            system_prompt_hash=result.audit.system_prompt_hash,
            context_file_sha256=result.audit.context_file_sha256,
            context_preview=result.audit.context_preview,
            sr_candidates_presented_json=json.dumps(
                [c.model_dump(mode="json") for c in result.audit.sr_candidates_presented]
            ),
            sr_candidates_selected_json=json.dumps(result.audit.sr_candidates_selected),
            ran_at=result.audit.ran_at,
        )

    write_chart(result.chart, output_path)
    console.print(
        f"[green]✓[/green] wrote {output_path} "
        f"({len(result.chart.view.drawings)} AI-drawn lines, "
        f"selected {len(result.audit.sr_candidates_selected)} of "
        f"{len(result.audit.sr_candidates_presented)} candidates)"
    )


def _print_dry_run(
    *,
    chart_in: Chart,
    candle_count: int,
    indicator_keys: list[str],
    candidate_count: int,
    context_md: str | None,
    provider: str,
    model: str,
) -> None:
    console.print("[bold]dry run — no LLM call, no DB write[/bold]")
    console.print(f"  pair:         {chart_in.pair}")
    interval = chart_in.data.default_interval
    days = chart_in.data.default_window_days
    console.print(f"  window:       last {days}d at {interval}")
    console.print(f"  candles:      {candle_count}")
    console.print(f"  indicators:   {', '.join(indicator_keys) or '[none]'}")
    console.print(f"  candidates:   {candidate_count}")
    console.print(
        f"  context md:   {len(context_md):,} chars" if context_md else "  context md:   [none]"
    )
    console.print(f"  provider:     {provider}")
    console.print(f"  model:        {model}")


def _estimate_tokens(
    chart_in: Chart,
    candle_count: int,
    indicator_count: int,
    candidate_count: int,
    context_md: str | None,
) -> int:
    """Rough tokens-from-characters heuristic for the disclosure line.

    Exact enough to give the user a "is this $0.10 or $1.00" sense before
    confirming. Underestimates Anthropic's tokenization slightly; that's
    fine for a budget heuristic.
    """
    approx_chars = (
        len(chart_in.model_dump_json())
        + candle_count * 64  # ts,o,h,l,c,v line
        + indicator_count * candle_count * 24  # ts,value line per indicator
        + candidate_count * 80
        + (len(context_md) if context_md else 0)
        + 2_000  # system prompt + scaffolding
    )
    return approx_chars // 4
