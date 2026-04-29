"""Pydantic v2 models mirroring the chart.json shape from the plan.

Field naming matches the JSON exactly (``schemaVersion``, ``ts_utc``, etc.)
so dump/load is round-trip-stable. Models are ``ConfigDict(frozen=True)``
to communicate that they're immutable artifacts; mutate by constructing
new instances.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: int = 1

ProvenanceKind = Literal["user", "ai"]
DrawingKind = Literal["trend", "horizontal", "fib", "rect"]


class _BaseModel(BaseModel):
    """Common config: frozen, populate by name, forbid extras to catch typos."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )


# --- Provenance ---


class Provenance(_BaseModel):
    """Who created this object and when. ``model`` is set only when
    ``kind == "ai"``. ``confidence`` and ``rationale`` are typically only
    set on AI-created drawings; on chart-level provenance they're omitted.
    """

    kind: ProvenanceKind
    created_at: datetime
    model: str | None = None
    prompt_template_version: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = None

    @model_validator(mode="after")
    def _ai_requires_model(self) -> Provenance:
        if self.kind == "ai" and not self.model:
            raise ValueError("provenance.model is required when kind == 'ai'")
        if self.kind == "user" and self.model:
            raise ValueError("provenance.model must be empty when kind == 'user'")
        return self


# --- View payload ---


class Indicator(_BaseModel):
    id: str
    name: str
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)
    pane: int = 0


class Anchor(_BaseModel):
    """A single anchor on a drawing.

    ``candidate_id`` is set on AI-created drawings to record which S/R
    candidate the model picked (the price is then resolved server-side).
    On user drawings ``candidate_id`` is ``None`` and ``price`` is whatever
    the user dragged the line to.
    """

    ts_utc: int
    price: float
    candidate_id: str | None = None


class Style(_BaseModel):
    color: str
    dash: Literal["solid", "dashed", "dotted"] = "solid"


class Drawing(_BaseModel):
    """A single drawing on a chart (trend line, horizontal, fib, rectangle).

    ``provenance`` is **omitted** on user-created drawings (the chart-level
    provenance covers them). It is **required** on AI-created drawings so
    rationale and confidence travel with each individual line.
    """

    id: str
    kind: DrawingKind
    anchors: list[Anchor]
    style: Style
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _validate_anchors(self) -> Drawing:
        if not self.anchors:
            raise ValueError("drawing must have at least one anchor")
        if self.kind == "horizontal" and len(self.anchors) != 1:
            raise ValueError(
                f"horizontal drawing must have exactly 1 anchor, got {len(self.anchors)}"
            )
        if self.kind == "trend" and len(self.anchors) != 2:
            raise ValueError(f"trend drawing must have exactly 2 anchors, got {len(self.anchors)}")
        return self


class ChartView(_BaseModel):
    indicators: list[Indicator] = Field(default_factory=list)
    drawings: list[Drawing] = Field(default_factory=list)
    analysis_text: str | None = None


class ChartData(_BaseModel):
    """Default time-window the chart was authored against. Relative ('last
    N days from now'), not absolute, so charts stay evergreen."""

    default_window_days: int = Field(ge=1)
    default_interval: Literal["1h", "1d", "1w"]


# --- AI audit payload ---


class SRCandidate(_BaseModel):
    """One S/R candidate as presented to the LLM.

    The full set is recorded in ``AIRun.sr_candidates_presented`` for audit
    so a future replay can know exactly what the model chose from.
    """

    id: str
    price: float
    kind: Literal["support", "resistance"]
    method: str
    touches: int
    strength_score: float
    first_seen: int
    last_touch: int


class AIRun(_BaseModel):
    """Audit record for an AI-produced chart. Populated only on AI charts."""

    model: str
    prompt_template_version: str
    context_file_sha256: str | None = None
    context_preview: str | None = None
    sr_candidates_presented: list[SRCandidate]
    sr_candidates_selected: list[str]


# --- Top-level chart ---


class Chart(_BaseModel):
    """A complete chart artifact — ``schemaVersion: 1``."""

    schema_version: int = Field(alias="schemaVersion", default=SCHEMA_VERSION)
    slug: str
    title: str
    pair: str
    provenance: Provenance
    parent_chart_id: str | None = None
    data: ChartData
    view: ChartView
    ai_run: AIRun | None = None

    @model_validator(mode="after")
    def _validate_schema_version(self) -> Chart:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schemaVersion {self.schema_version}; this build "
                f"writes v{SCHEMA_VERSION}. Re-export from a matching signal-trck "
                f"or write a one-shot migration in scripts/."
            )
        return self

    @model_validator(mode="after")
    def _ai_chart_consistency(self) -> Chart:
        if self.provenance.kind == "ai":
            if self.ai_run is None:
                raise ValueError("ai charts must include 'ai_run'")
            if self.ai_run.model != self.provenance.model:
                raise ValueError(
                    "ai_run.model must match provenance.model "
                    f"({self.ai_run.model!r} vs {self.provenance.model!r})"
                )
            for d in self.view.drawings:
                if d.provenance is None or d.provenance.kind != "ai":
                    raise ValueError(f"drawing {d.id!r} on an AI chart must carry ai provenance")
        else:
            if self.ai_run is not None:
                raise ValueError("user charts must not include 'ai_run'")
        return self
