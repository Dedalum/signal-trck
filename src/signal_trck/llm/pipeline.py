"""End-to-end AI analysis pipeline.

Inputs: chart-1 (already loaded), candles, indicators, S/R candidates,
optional markdown context, an ``LLMClient``.

Output: a fully-formed chart-2 ``Chart`` (with resolved prices on every
AI drawing anchor) plus an ``AIRunAudit`` record ready to persist.

Retry policy: one retry on validation/grounding failure. On second
failure, the raw LLM response + validator error are dumped to
``~/.signal-trck/failed/<timestamp>.json`` for offline prompt tuning,
and a ``PipelineError`` is raised.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from signal_trck import paths
from signal_trck.chart_schema import (
    AIRun,
    Anchor,
    Chart,
    ChartView,
    Drawing,
    Provenance,
    SRCandidate,
    Style,
)
from signal_trck.indicators.cache import IndicatorSeries
from signal_trck.levels.types import Candidate
from signal_trck.llm.analysis import (
    ChartAnalysis,
    GroundingError,
    validate_grounding,
)
from signal_trck.llm.client import LLMClient
from signal_trck.llm.prompts import (
    PROMPT_TEMPLATE_VERSION,
    build_system_prompt,
    build_user_prompt,
    system_prompt_hash,
)
from signal_trck.storage.models import Candle

log = structlog.get_logger(__name__)

_AI_DRAWING_STYLE = Style(color="#e76f51", dash="dashed")


class PipelineError(Exception):
    """Raised when the AI pipeline cannot produce a valid chart-2 after retry."""


@dataclass
class AIRunAudit:
    """Database row payload for ``ai_runs``. Stored alongside chart-2."""

    pair_id: str
    chart_slug: str
    provider: str
    model: str
    prompt_template_version: str
    system_prompt_hash: str
    context_file_sha256: str | None
    context_preview: str | None
    sr_candidates_presented: list[SRCandidate]
    sr_candidates_selected: list[str]
    ran_at: int


@dataclass
class AnalysisResult:
    """Full output of the pipeline: the chart-2 artifact + the audit row.

    ``raw_analysis`` is the LLM's verbatim ``ChartAnalysis`` for diagnostics.
    """

    chart: Chart
    audit: AIRunAudit
    raw_analysis: ChartAnalysis


def analyze_chart(
    *,
    chart_in: Chart,
    candles: list[Candle],
    indicators: dict[str, IndicatorSeries],
    candidates: list[Candidate],
    context_md: str | None,
    client: LLMClient,
    output_slug: str = "chart-2",
    output_title: str | None = None,
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    max_retries: int = 1,
) -> AnalysisResult:
    """Run the analysis pipeline. See module docstring for retry semantics."""
    if not candidates:
        raise PipelineError(
            "no S/R candidates were detected for this pair/window — "
            "run `signal-trck levels` to investigate, or fetch more history"
        )

    system = build_system_prompt(prompt_template_version)
    user = build_user_prompt(chart_in, candles, indicators, candidates, context_md)
    sys_hash = system_prompt_hash(system)

    last_error: Exception | None = None
    validated: ChartAnalysis | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.analyze(system=system, user=user, response_model=ChartAnalysis)
            validate_grounding(response, candidates)
            validated = response
            break
        except (ValidationError, GroundingError) as e:
            last_error = e
            log.warning(
                "ai.attempt_failed",
                attempt=attempt + 1,
                of=max_retries + 1,
                error=str(e),
                error_type=type(e).__name__,
            )

    if validated is None:
        # Every attempt failed validation — dump and raise.
        dump_path = _dump_failure(
            pair_id=chart_in.pair,
            system=system,
            user=user,
            error=last_error,
        )
        raise PipelineError(
            f"AI pipeline failed after {max_retries + 1} attempts: {last_error}. Dump: {dump_path}"
        )
    raw = validated

    chart_2 = _build_chart_2(
        chart_in=chart_in,
        analysis=raw,
        candidates=candidates,
        provider=client.provider,
        model=client.model,
        prompt_template_version=prompt_template_version,
        slug=output_slug,
        title=output_title or f"AI analysis {datetime.now(UTC).strftime('%Y-%m-%d')}",
    )
    audit = _build_audit(
        chart_2=chart_2,
        analysis=raw,
        candidates=candidates,
        provider=client.provider,
        model=client.model,
        prompt_template_version=prompt_template_version,
        system_prompt_hash_=sys_hash,
        context_md=context_md,
        context_path=None,  # set by the CLI when --context is used
    )
    return AnalysisResult(chart=chart_2, audit=audit, raw_analysis=raw)


def context_metadata(
    context_md: str | None, context_path: str | None
) -> tuple[str | None, str | None]:
    """Compute (sha256, ~500-char preview) for an optional markdown context."""
    if not context_md:
        return None, None
    sha = hashlib.sha256(context_md.encode("utf-8")).hexdigest()
    preview = context_md[:500] + ("…" if len(context_md) > 500 else "")
    _ = context_path  # accepted for symmetry; file path itself isn't recorded
    return sha, preview


# --- internals ---


def _build_chart_2(
    *,
    chart_in: Chart,
    analysis: ChartAnalysis,
    candidates: list[Candidate],
    provider: str,
    model: str,
    prompt_template_version: str,
    slug: str,
    title: str,
) -> Chart:
    """Assemble the chart-2 ``Chart`` from the LLM's analysis + presented candidates."""
    by_id = {c.id: c for c in candidates}
    now_iso = datetime.now(UTC)

    chart_prov = Provenance(
        kind="ai",
        model=model,
        prompt_template_version=prompt_template_version,
        created_at=now_iso,
    )

    drawings: list[Drawing] = []
    for i, ai_d in enumerate(analysis.drawings, start=1):
        anchors = [_resolve_anchor(a.candidate_id, by_id) for a in ai_d.anchors]
        drawings.append(
            Drawing(
                id=f"dr-ai-{i}",
                kind=ai_d.kind,
                anchors=anchors,
                style=_AI_DRAWING_STYLE,
                provenance=Provenance(
                    kind="ai",
                    model=model,
                    created_at=now_iso,
                    confidence=ai_d.confidence,
                    rationale=ai_d.rationale,
                ),
            )
        )

    presented_models = [_candidate_to_sr(c) for c in candidates]
    selected_ids: list[str] = sorted({a.candidate_id for d in analysis.drawings for a in d.anchors})
    return Chart(
        slug=slug,
        title=title,
        pair=chart_in.pair,
        provenance=chart_prov,
        parent_chart_id=chart_in.slug,
        data=chart_in.data,
        view=ChartView(
            indicators=list(chart_in.view.indicators),  # inherit from user chart
            drawings=drawings,
            analysis_text=analysis.analysis_text,
        ),
        ai_run=AIRun(
            model=model,
            prompt_template_version=prompt_template_version,
            sr_candidates_presented=presented_models,
            sr_candidates_selected=selected_ids,
        ),
    )


def _resolve_anchor(candidate_id: str, by_id: dict[str, Candidate]) -> Anchor:
    """Map an AI candidate_id to a fully-realized ``Anchor`` with price + ts_utc.

    By convention, the anchor's ``ts_utc`` is the candidate's ``last_touch``
    (most recent confirmation of the level). Horizontal lines render across
    the full chart regardless, so the timestamp is informational.
    """
    cand = by_id[candidate_id]  # validate_grounding has already checked membership
    return Anchor(ts_utc=cand.last_touch, price=cand.price, candidate_id=candidate_id)


def _candidate_to_sr(c: Candidate) -> SRCandidate:
    """Convert engine-side ``Candidate`` to schema-side ``SRCandidate``."""
    return SRCandidate(
        id=c.id,
        price=c.price,
        kind=c.kind,
        method=c.method,
        touches=c.touches,
        strength_score=c.strength_score,
        first_seen=c.first_seen,
        last_touch=c.last_touch,
    )


def _build_audit(
    *,
    chart_2: Chart,
    analysis: ChartAnalysis,
    candidates: list[Candidate],
    provider: str,
    model: str,
    prompt_template_version: str,
    system_prompt_hash_: str,
    context_md: str | None,
    context_path: str | None,
) -> AIRunAudit:
    sha, preview = context_metadata(context_md, context_path)
    selected_ids: list[str] = sorted({a.candidate_id for d in analysis.drawings for a in d.anchors})
    return AIRunAudit(
        pair_id=chart_2.pair,
        chart_slug=chart_2.slug,
        provider=provider,
        model=model,
        prompt_template_version=prompt_template_version,
        system_prompt_hash=system_prompt_hash_,
        context_file_sha256=sha,
        context_preview=preview,
        sr_candidates_presented=[_candidate_to_sr(c) for c in candidates],
        sr_candidates_selected=selected_ids,
        ran_at=int(time.time()),
    )


def _dump_failure(*, pair_id: str, system: str, user: str, error: Exception | None) -> Path:
    """Write the failed prompt + error to ``~/.signal-trck/failed/`` for tuning."""
    failed = paths.failed_dir()
    failed.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = failed / f"{ts}_{pair_id.replace(':', '_').replace('-', '_')}.json"
    payload: dict[str, Any] = {
        "ran_at": int(time.time()),
        "pair_id": pair_id,
        "error": repr(error) if error is not None else None,
        "system": system,
        "user": user,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.error("ai.dump_failure", path=str(out), pair=pair_id)
    return out
