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

from signal_trck.chart_schema import Chart


def read_chart(path: str | Path) -> Chart:
    """Load a chart.json file and validate against the v1 schema.

    Raises ``ValidationError`` from Pydantic on malformed input, with
    actionable messages (extra fields rejected, schemaVersion check, etc.).
    """
    p = Path(path)
    payload = p.read_text(encoding="utf-8")
    return Chart.model_validate_json(payload)


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
