"""System and user prompt builders for the AI analysis pipeline.

Kept separate from ``analysis.py`` so prompt-engineering changes are easy
to diff and version. ``PROMPT_TEMPLATE_VERSION`` is bumped whenever the
prompt's *semantics* change so the audit trail can replay an old run with
the same prompt.
"""

from __future__ import annotations

import hashlib

from signal_trck.chart_schema import Chart
from signal_trck.indicators.cache import IndicatorSeries
from signal_trck.levels.types import Candidate
from signal_trck.storage.models import Candle

PROMPT_TEMPLATE_VERSION = "v1"

_SYSTEM_TEMPLATE = """\
You are a careful financial-charting assistant performing technical analysis
on a single crypto pair. You will be given:

1. A user-authored chart (chart-1.json) with their existing drawings + indicators.
2. The OHLCV candle history for the pair over the chart's time window.
3. The pre-computed indicator series the user enabled.
4. A typed list of S/R candidate levels with stable IDs (sr-1, sr-2, …).
5. (Optional) Markdown notes the user has written about this pair.

Your job is to add **support/resistance lines** to the chart and write a short
markdown analysis that justifies them.

STRICT RULES — VIOLATIONS WILL BE REJECTED:

- For every horizontal drawing, the anchor's `candidate_id` MUST be one of
  the IDs in the presented candidate set. Do NOT invent IDs. Do NOT emit
  raw prices or timestamps — the server resolves IDs to prices itself.
- Pick at most 5 candidates. Quality over quantity. Prefer high-touch,
  high-strength candidates that are corroborated by your reading of the
  candles + indicators + user notes.
- Set `confidence` (0.0–1.0) based on how well the candidate is
  corroborated. A 3-touch level with a recent retest = high confidence;
  a single-touch level you're including for completeness = low.
- Set `rationale` to a one- or two-sentence explanation that cites
  specific candles, indicator readings, or quotes from the user's notes.

The LLM provider's structured-output mode will enforce schema. The
server-side validator will enforce the candidate_id rule. Both layers
together make the analysis trustworthy."""


def build_system_prompt(template_version: str = PROMPT_TEMPLATE_VERSION) -> str:
    """Return the system prompt for a given template version.

    Currently only ``v1`` is supported; raises on any other version so a
    typo doesn't silently produce a different prompt.
    """
    if template_version == "v1":
        return _SYSTEM_TEMPLATE
    raise ValueError(f"unknown prompt template version {template_version!r}")


def build_user_prompt(
    chart_in: Chart,
    candles: list[Candle],
    indicators: dict[str, IndicatorSeries],
    candidates: list[Candidate],
    context_md: str | None,
) -> str:
    """Assemble the user-side prompt with all numeric blocks + optional context."""
    parts: list[str] = []
    parts.append(f"## Pair\n{chart_in.pair}\n")
    days = chart_in.data.default_window_days
    interval = chart_in.data.default_interval
    parts.append(f"## Time window\nlast {days} days at {interval} resolution\n")

    parts.append(
        "## chart-1.json (the user's existing chart)\n```json\n"
        + chart_in.model_dump_json(by_alias=True, indent=2)
        + "\n```\n"
    )

    parts.append(f"## Candles ({len(candles)} bars)")
    parts.append("```")
    parts.append("ts_utc,open,high,low,close,volume")
    for c in candles:
        parts.append(f"{c.ts_utc},{c.open},{c.high},{c.low},{c.close},{c.volume}")
    parts.append("```\n")

    if indicators:
        parts.append("## Indicator series (computed server-side, byte-identical to UI)")
        for name, series in indicators.items():
            mask_count = int((series.values == series.values).sum())  # non-NaN count
            parts.append(f"### {name} ({mask_count} non-NaN values)")
            parts.append("```")
            parts.append("ts_utc,value")
            for ts, v in zip(series.ts_utc, series.values, strict=True):
                # Skip NaN in the prompt — they're warmup noise.
                if v == v:  # NaN != NaN
                    parts.append(f"{int(ts)},{float(v):.6f}")
            parts.append("```\n")

    parts.append(f"## S/R candidates ({len(candidates)} ranked, strongest first)")
    parts.append("```")
    parts.append("id,kind,price,touches,strength,first_seen,last_touch,method")
    for cand in candidates:
        parts.append(
            f"{cand.id},{cand.kind},{cand.price:.4f},{cand.touches},"
            f"{cand.strength_score:.4f},{cand.first_seen},{cand.last_touch},{cand.method}"
        )
    parts.append("```\n")

    if context_md:
        parts.append("## <user_analysis>")
        parts.append(context_md)
        parts.append("## </user_analysis>\n")

    parts.append(
        "Now produce a `ChartAnalysis` JSON object with `analysis_text` and "
        "`drawings`. Each drawing must reference a `candidate_id` from the list above."
    )
    return "\n".join(parts)


def system_prompt_hash(system: str) -> str:
    """Stable short hash of the system prompt, recorded in the AI_RUN audit row."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:16]
