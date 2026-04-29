"""``ChartAnalysis`` — the response shape the LLM is asked to produce.

Critical anti-hallucination mechanism: the LLM emits a ``candidate_id``
string (not a freeform price). The server resolves the ID to a price at
ingest time, so the property "no AI-drawn price outside the candidate set"
is true **by construction** (string-set membership) — see plan §"AI
grounding strategy".

This module defines:
- The ``ChartAnalysis`` Pydantic schema (what the LLM returns).
- The ``GroundingError`` raised when the LLM ignores the rules.
- ``validate_grounding(analysis, candidates)`` — server-side check that
  every emitted ``candidate_id`` is in the presented set.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from signal_trck.levels.types import Candidate

# AI-emittable drawing kinds. v1 ships horizontal-only — the AI proposes
# S/R levels and the schema reflects that. Other kinds (trend, fib, rect)
# are reserved for the user to draw manually until the AI grounds those
# too in a future phase.
AIDrawingKind = Literal["horizontal"]


class GroundingError(Exception):
    """Raised when the LLM emits a ``candidate_id`` not in the presented set,
    or otherwise violates the grounding contract."""

    def __init__(self, message: str, *, offending_ids: list[str] | None = None):
        super().__init__(message)
        self.offending_ids = offending_ids or []


class AIAnchor(BaseModel):
    """An anchor on an AI-drawn line.

    The model emits a ``candidate_id`` only — never a raw price. The
    server resolves the ID against the presented candidate set and
    populates ``price`` and ``ts_utc`` server-side from the candidate's
    own data (see ``signal_trck.llm.pipeline.resolve_anchor``).
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)


class AIDrawing(BaseModel):
    """A drawing the AI proposes adding to the chart.

    v1 only allows ``horizontal`` (a single S/R band selected by ID). Future
    phases may add trend/fib/rect with their own grounding mechanisms.
    """

    model_config = ConfigDict(extra="forbid")

    kind: AIDrawingKind
    anchors: list[AIAnchor] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _horizontal_anchor_count(self) -> AIDrawing:
        if self.kind == "horizontal" and len(self.anchors) != 1:
            raise ValueError(
                f"horizontal drawing requires exactly 1 anchor, got {len(self.anchors)}"
            )
        return self


class ChartAnalysis(BaseModel):
    """The LLM's structured response.

    ``analysis_text`` is a markdown blob that becomes the chart's
    ``view.analysis_text``. ``drawings`` are the proposed S/R lines, each
    referencing a candidate from the presented set.
    """

    model_config = ConfigDict(extra="forbid")

    analysis_text: str = Field(min_length=1)
    drawings: list[AIDrawing]


def validate_grounding(analysis: ChartAnalysis, candidates: list[Candidate]) -> None:
    """Raise ``GroundingError`` if any anchor cites a candidate ID not in the
    presented set.

    Pydantic validation catches schema-level issues (missing fields,
    type errors). This catches the *semantic* contract — that the LLM is
    picking from real candidates — which Pydantic alone can't enforce
    because the valid IDs are only known at run-time.
    """
    presented = {c.id for c in candidates}
    offenders: list[str] = []
    for d in analysis.drawings:
        for a in d.anchors:
            if a.candidate_id not in presented:
                offenders.append(a.candidate_id)
    if offenders:
        raise GroundingError(
            f"{len(offenders)} candidate_id(s) not in presented set: "
            f"{offenders[:5]}{'...' if len(offenders) > 5 else ''}",
            offending_ids=offenders,
        )
