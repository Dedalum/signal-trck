"""Read/write ``chart.json`` files. Stable formatting so artifacts are
diffable in git.

The on-disk format is exactly what ``Chart.model_dump_json(by_alias=True)``
produces, then re-formatted via ``json.dumps`` with ``indent=2`` and
``sort_keys=False`` (Pydantic's field declaration order is the canonical
key order — sorting alphabetically would scramble logical groupings).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signal_trck.chart_schema import Chart, SchemaVersionError
from signal_trck.chart_schema.models import SCHEMA_VERSION


def read_chart(path: str | Path) -> Chart:
    """Load a chart.json file and validate against the v1 schema.

    Raises ``SchemaVersionError`` if the file declares a ``schemaVersion``
    that doesn't match the running build. Raises ``ValidationError`` from
    Pydantic on other malformed input (extra fields, type mismatches, etc.).
    """
    p = Path(path)
    payload = p.read_text(encoding="utf-8")
    return parse_chart_json(payload)


def parse_chart_json(payload: str) -> Chart:
    """Parse a chart.json string into a ``Chart`` model.

    Schema-version check runs **before** Pydantic so callers get a clean
    ``SchemaVersionError`` rather than the wrapped ``ValidationError`` that
    Pydantic's ``model_validator`` would produce.
    """
    raw: Any = json.loads(payload)
    if isinstance(raw, dict):
        version = raw.get("schemaVersion")
        if isinstance(version, int) and version != SCHEMA_VERSION:
            raise SchemaVersionError(version, SCHEMA_VERSION)
    return Chart.model_validate(raw)


def write_chart(chart: Chart, path: str | Path) -> Path:
    """Write a chart to disk as pretty-printed JSON.

    Returns the resolved path. Parent directory is created if missing.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = chart.model_dump(by_alias=True, mode="json", exclude_none=False)
    p.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def chart_to_json_string(chart: Chart) -> str:
    """Return the on-disk representation of a chart, without writing it."""
    raw = chart.model_dump(by_alias=True, mode="json", exclude_none=False)
    return json.dumps(raw, indent=2, ensure_ascii=False)
