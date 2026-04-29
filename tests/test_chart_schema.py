"""Chart schema — round-trip JSON, validators fire correctly, AI charts vs
user charts diverge in the right places."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from signal_trck.chart_schema import (
    SCHEMA_VERSION,
    AIRun,
    Anchor,
    Chart,
    ChartData,
    ChartView,
    Drawing,
    Indicator,
    Provenance,
    SRCandidate,
    Style,
)


def _user_chart() -> Chart:
    return Chart(
        slug="chart-1",
        title="BTC accumulation thesis",
        pair="coinbase:BTC-USD",
        provenance=Provenance(kind="user", created_at=datetime(2026, 4, 22, tzinfo=UTC)),
        data=ChartData(default_window_days=90, default_interval="1d"),
        view=ChartView(
            indicators=[Indicator(id="sma-50", name="SMA", params={"period": 50}, pane=0)],
            drawings=[
                Drawing(
                    id="dr-1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1_704_067_200, price=42_000.0)],
                    style=Style(color="#2a9d8f", dash="solid"),
                )
            ],
        ),
    )


def _ai_chart() -> Chart:
    prov_chart = Provenance(
        kind="ai",
        model="claude-opus-4-7",
        prompt_template_version="v1",
        created_at=datetime(2026, 4, 22, 11, 30, tzinfo=UTC),
    )
    prov_drawing = Provenance(
        kind="ai",
        model="claude-opus-4-7",
        created_at=datetime(2026, 4, 22, 11, 30, tzinfo=UTC),
        confidence=0.78,
        rationale="Tested 3 times in Q1 2026",
    )
    return Chart(
        slug="chart-2",
        title="AI analysis",
        pair="coinbase:BTC-USD",
        provenance=prov_chart,
        parent_chart_id="chart-1",
        data=ChartData(default_window_days=90, default_interval="1d"),
        view=ChartView(
            drawings=[
                Drawing(
                    id="dr-2",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1_704_067_200, price=42_103.5, candidate_id="sr-12")],
                    style=Style(color="#e76f51", dash="dashed"),
                    provenance=prov_drawing,
                )
            ],
            analysis_text="BTC has consolidated…",
        ),
        ai_run=AIRun(
            model="claude-opus-4-7",
            prompt_template_version="v1",
            sr_candidates_presented=[
                SRCandidate(
                    id="sr-12",
                    price=42_103.5,
                    kind="resistance",
                    method="swing_cluster",
                    touches=3,
                    strength_score=4.5,
                    first_seen=1_700_000_000,
                    last_touch=1_704_067_200,
                )
            ],
            sr_candidates_selected=["sr-12"],
        ),
    )


def test_user_chart_roundtrips_through_json() -> None:
    chart = _user_chart()
    payload = chart.model_dump_json(by_alias=True)
    parsed = json.loads(payload)
    assert parsed["schemaVersion"] == SCHEMA_VERSION
    assert parsed["pair"] == "coinbase:BTC-USD"
    assert parsed["provenance"]["kind"] == "user"
    rebuilt = Chart.model_validate_json(payload)
    assert rebuilt == chart


def test_ai_chart_roundtrips_through_json() -> None:
    chart = _ai_chart()
    payload = chart.model_dump_json(by_alias=True)
    rebuilt = Chart.model_validate_json(payload)
    assert rebuilt == chart


def test_user_provenance_rejects_model() -> None:
    with pytest.raises(ValidationError, match="must be empty when kind == 'user'"):
        Provenance(kind="user", model="claude-opus-4-7", created_at=datetime.now(UTC))


def test_ai_provenance_requires_model() -> None:
    with pytest.raises(ValidationError, match="model is required when kind == 'ai'"):
        Provenance(kind="ai", created_at=datetime.now(UTC))


def test_user_chart_with_ai_run_rejected() -> None:
    base = _user_chart()
    with pytest.raises(ValidationError, match="user charts must not include 'ai_run'"):
        Chart.model_validate(
            {
                **base.model_dump(by_alias=True),
                "ai_run": _ai_chart().ai_run.model_dump(by_alias=True),
            }
        )


def test_ai_chart_without_ai_run_rejected() -> None:
    chart = _ai_chart().model_dump(by_alias=True)
    chart["ai_run"] = None
    with pytest.raises(ValidationError, match="ai charts must include 'ai_run'"):
        Chart.model_validate(chart)


def test_ai_chart_drawing_must_carry_ai_provenance() -> None:
    bad = _ai_chart().model_dump(by_alias=True)
    bad["view"]["drawings"][0]["provenance"] = None
    with pytest.raises(ValidationError, match="must carry ai provenance"):
        Chart.model_validate(bad)


def test_ai_run_model_must_match_provenance() -> None:
    bad = _ai_chart().model_dump(by_alias=True)
    bad["ai_run"]["model"] = "different-model"
    with pytest.raises(ValidationError, match="ai_run.model must match"):
        Chart.model_validate(bad)


def test_horizontal_drawing_requires_one_anchor() -> None:
    with pytest.raises(ValidationError, match="horizontal drawing must have exactly 1 anchor"):
        Drawing(
            id="d",
            kind="horizontal",
            anchors=[
                Anchor(ts_utc=1, price=1.0),
                Anchor(ts_utc=2, price=2.0),
            ],
            style=Style(color="#000"),
        )


def test_trend_drawing_requires_two_anchors() -> None:
    with pytest.raises(ValidationError, match="trend drawing must have exactly 2 anchors"):
        Drawing(
            id="d",
            kind="trend",
            anchors=[Anchor(ts_utc=1, price=1.0)],
            style=Style(color="#000"),
        )


def test_drawing_with_zero_anchors_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one anchor"):
        Drawing(id="d", kind="rect", anchors=[], style=Style(color="#000"))


def test_extra_fields_forbidden() -> None:
    """Catches typos like 'colour' instead of 'color' on round-trip."""
    with pytest.raises(ValidationError):
        Style.model_validate({"color": "#000", "colour": "#fff"})


def test_schema_version_mismatch_rejected() -> None:
    payload = _user_chart().model_dump(by_alias=True)
    payload["schemaVersion"] = 2
    with pytest.raises(ValidationError, match="unsupported schemaVersion 2"):
        Chart.model_validate(payload)


def test_confidence_in_unit_interval() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            kind="ai",
            model="m",
            created_at=datetime.now(UTC),
            confidence=1.5,
        )


def test_default_window_days_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ChartData(default_window_days=0, default_interval="1d")
