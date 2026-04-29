"""``ChartAnalysis`` schema + ``validate_grounding`` semantic check."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signal_trck.levels.types import Candidate
from signal_trck.llm.analysis import (
    AIAnchor,
    AIDrawing,
    ChartAnalysis,
    GroundingError,
    validate_grounding,
)


def _candidate(id_: str = "sr-1", price: float = 100.0) -> Candidate:
    return Candidate(
        id=id_,
        price=price,
        kind="resistance",
        method="swing_cluster",
        touches=2,
        strength_score=2.0,
        first_seen=1_700_000_000,
        last_touch=1_700_500_000,
    )


def test_chart_analysis_minimal_roundtrips() -> None:
    a = ChartAnalysis(
        analysis_text="hi",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-1")],
                confidence=0.7,
                rationale="r",
            )
        ],
    )
    payload = a.model_dump_json()
    assert "sr-1" in payload
    a2 = ChartAnalysis.model_validate_json(payload)
    assert a2 == a


def test_chart_analysis_rejects_extra_fields() -> None:
    """``extra='forbid'`` catches LLM hallucinated keys."""
    with pytest.raises(ValidationError):
        ChartAnalysis.model_validate(
            {
                "analysis_text": "ok",
                "drawings": [],
                "secret_field": True,
            }
        )


def test_ai_drawing_horizontal_requires_one_anchor() -> None:
    with pytest.raises(ValidationError, match="exactly 1 anchor"):
        AIDrawing(
            kind="horizontal",
            anchors=[AIAnchor(candidate_id="sr-1"), AIAnchor(candidate_id="sr-2")],
            confidence=0.5,
            rationale="r",
        )


def test_ai_drawing_zero_anchors_rejected() -> None:
    with pytest.raises(ValidationError):
        AIDrawing(kind="horizontal", anchors=[], confidence=0.5, rationale="r")


def test_ai_drawing_blank_rationale_rejected() -> None:
    with pytest.raises(ValidationError):
        AIDrawing(
            kind="horizontal",
            anchors=[AIAnchor(candidate_id="sr-1")],
            confidence=0.5,
            rationale="",
        )


def test_ai_drawing_blank_candidate_id_rejected() -> None:
    with pytest.raises(ValidationError):
        AIAnchor(candidate_id="")


def test_ai_drawing_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AIDrawing(
            kind="horizontal",
            anchors=[AIAnchor(candidate_id="sr-1")],
            confidence=1.5,
            rationale="r",
        )


# --- grounding validator ---


def test_validate_grounding_accepts_known_candidate() -> None:
    a = ChartAnalysis(
        analysis_text="ok",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-1")],
                confidence=0.5,
                rationale="r",
            )
        ],
    )
    validate_grounding(a, [_candidate("sr-1"), _candidate("sr-2", 200.0)])


def test_validate_grounding_rejects_unknown_id() -> None:
    a = ChartAnalysis(
        analysis_text="ok",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-99")],
                confidence=0.5,
                rationale="r",
            )
        ],
    )
    with pytest.raises(GroundingError) as info:
        validate_grounding(a, [_candidate("sr-1")])
    assert info.value.offending_ids == ["sr-99"]


def test_validate_grounding_collects_all_offenders() -> None:
    a = ChartAnalysis(
        analysis_text="ok",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-99")],
                confidence=0.5,
                rationale="r",
            ),
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-42")],
                confidence=0.5,
                rationale="r",
            ),
        ],
    )
    with pytest.raises(GroundingError) as info:
        validate_grounding(a, [_candidate("sr-1")])
    assert set(info.value.offending_ids) == {"sr-99", "sr-42"}


def test_validate_grounding_empty_drawings_passes() -> None:
    """An LLM that legitimately decides 'no drawings worth proposing' is allowed."""
    a = ChartAnalysis(analysis_text="nothing to see here", drawings=[])
    validate_grounding(a, [_candidate("sr-1")])
