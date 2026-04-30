"""Pydantic models for ``chart.json`` v1.

The schema is the contract between the UI, the CLI, and the LLM. It is
intentionally export-ready: ``Chart.model_dump_json(indent=2)`` produces a
diffable artifact suitable for committing to git.

Schema versioning is integer (``schemaVersion: 1``). On load we accept
exact-match only. Future major bumps ship a one-shot migration script in
``scripts/`` rather than a generic migration framework — see plan
§"Decisions made post-review".
"""

from signal_trck.chart_schema.models import (
    SCHEMA_VERSION,
    AIRun,
    Anchor,
    Chart,
    ChartData,
    ChartView,
    Drawing,
    DrawingKind,
    Indicator,
    Provenance,
    ProvenanceKind,
    SchemaVersionError,
    SRCandidate,
    Style,
)

__all__ = [
    "SCHEMA_VERSION",
    "AIRun",
    "Anchor",
    "Chart",
    "ChartData",
    "ChartView",
    "Drawing",
    "DrawingKind",
    "Indicator",
    "Provenance",
    "ProvenanceKind",
    "SchemaVersionError",
    "SRCandidate",
    "Style",
]
