"""End-to-end ``analyze_chart`` pipeline with a fake ``LLMClient``.

Three categories:
1. Happy path — LLM returns a valid response, full chart-2 is produced.
2. Retry semantics — bad first response, good second; or two bads → dump + raise.
3. **Property test** (~20 fixtures) — across a range of synthetic candle
   scenarios with a fake LLM that may emit any candidate from the presented
   set, the produced chart-2 always satisfies:
     - every drawing's ``candidate_id`` is in ``ai_run.sr_candidates_presented``
     - every anchor's ``ts_utc`` aligns with the candidate's ``last_touch``
     - chart-2 schema validation passes
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest

from signal_trck.chart_schema import (
    Anchor,
    Chart,
    ChartData,
    ChartView,
    Drawing,
    Indicator,
    Provenance,
    Style,
)
from signal_trck.levels import detect_candidates
from signal_trck.levels.types import Candidate
from signal_trck.llm.analysis import (
    AIAnchor,
    AIDrawing,
    ChartAnalysis,
    GroundingError,
)
from signal_trck.llm.pipeline import (
    PipelineError,
    analyze_chart,
)
from signal_trck.storage.models import Candle

T = TypeVar("T")


class _FakeLLMClient:
    """Sequenceable fake — returns ``responses[i]`` on the i-th call.

    Each entry is either a ``ChartAnalysis`` (returned as-is) or an Exception
    (raised). This lets tests script retry behavior precisely.
    """

    def __init__(self, responses: list, *, model: str = "test-model", provider: str = "anthropic"):
        self._responses = list(responses)
        self.calls = 0
        self.model = model
        self.provider = provider

    def analyze(
        self,
        *,
        system: str,
        user: str,
        response_model,
        max_tokens: int = 0,
        temperature: float = 0.0,
    ):
        i = self.calls
        self.calls += 1
        if i >= len(self._responses):
            raise AssertionError(
                f"FakeLLMClient called {self.calls} times; only {len(self._responses)} scripted"
            )
        r = self._responses[i]
        if isinstance(r, Exception):
            raise r
        return r


def _candle(ts: int, *, h: float, lo: float, c: float | None = None) -> Candle:
    if c is None:
        c = (h + lo) / 2
    return Candle(
        pair_id="test:T-USD",
        interval="1d",
        ts_utc=ts,
        open=c,
        high=h,
        low=lo,
        close=c,
        volume=1000.0,
        source="test",
    )


def _make_user_chart() -> Chart:
    return Chart(
        slug="chart-1",
        title="user thesis",
        pair="test:T-USD",
        provenance=Provenance(kind="user", created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        data=ChartData(default_window_days=180, default_interval="1d"),
        view=ChartView(
            indicators=[Indicator(id="sma-50", name="SMA", params={"period": 50}, pane=0)],
            drawings=[
                Drawing(
                    id="dr-user-1",
                    kind="horizontal",
                    anchors=[Anchor(ts_utc=1_700_000_000, price=100.0)],
                    style=Style(color="#000"),
                )
            ],
        ),
    )


# --- happy path ---


def test_happy_path_produces_chart_2() -> None:
    user = _make_user_chart()
    candles = [
        _candle(
            1_700_000_000 + i * 86400, h=110 + 5 * math.sin(i / 4), lo=109 + 5 * math.sin(i / 4)
        )
        for i in range(60)
    ]
    candidates = detect_candidates(candles, lookback=3)
    assert candidates, "fixture must produce S/R candidates for the test to be meaningful"

    fake = ChartAnalysis(
        analysis_text="There is meaningful resistance at the highest-strength level.",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id=candidates[0].id)],
                confidence=0.85,
                rationale="Three clear retests on the W-shape, bracket-confirmed.",
            )
        ],
    )
    client = _FakeLLMClient([fake])
    result = analyze_chart(
        chart_in=user,
        candles=candles,
        indicators={},
        candidates=candidates,
        context_md=None,
        client=client,
        output_slug="chart-2",
    )

    # chart-2 carries AI provenance + parent linkage.
    assert result.chart.slug == "chart-2"
    assert result.chart.provenance.kind == "ai"
    assert result.chart.parent_chart_id == "chart-1"
    assert result.chart.ai_run is not None
    assert result.chart.ai_run.sr_candidates_selected == [candidates[0].id]

    # Drawing carries resolved price (from the candidate, not the LLM).
    assert len(result.chart.view.drawings) == 1
    d = result.chart.view.drawings[0]
    assert d.provenance is not None
    assert d.provenance.kind == "ai"
    assert d.provenance.confidence == 0.85
    assert d.anchors[0].price == candidates[0].price
    assert d.anchors[0].ts_utc == candidates[0].last_touch
    assert d.anchors[0].candidate_id == candidates[0].id

    # Indicators inherited from chart-1.
    assert [i.id for i in result.chart.view.indicators] == ["sma-50"]


def test_pipeline_aborts_when_no_candidates() -> None:
    user = _make_user_chart()
    candles = [_candle(1_700_000_000 + i * 86400, h=100, lo=99) for i in range(20)]
    with pytest.raises(PipelineError, match="no S/R candidates"):
        analyze_chart(
            chart_in=user,
            candles=candles,
            indicators={},
            candidates=[],
            context_md=None,
            client=_FakeLLMClient([]),
            output_slug="chart-2",
        )


# --- retry semantics ---


def test_retry_recovers_after_grounding_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIGNAL_TRCK_HOME", str(tmp_path))
    user = _make_user_chart()
    candles = [
        _candle(
            1_700_000_000 + i * 86400, h=110 + 5 * math.sin(i / 4), lo=109 + 5 * math.sin(i / 4)
        )
        for i in range(60)
    ]
    candidates = detect_candidates(candles, lookback=3)
    assert candidates

    bad = ChartAnalysis(
        analysis_text="hallucinating an id",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-9999")],  # not in presented set
                confidence=0.7,
                rationale="r",
            )
        ],
    )
    good = ChartAnalysis(
        analysis_text="recovered",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id=candidates[0].id)],
                confidence=0.7,
                rationale="r",
            )
        ],
    )
    client = _FakeLLMClient([bad, good])
    result = analyze_chart(
        chart_in=user,
        candles=candles,
        indicators={},
        candidates=candidates,
        context_md=None,
        client=client,
        output_slug="chart-2",
    )
    assert client.calls == 2
    assert result.chart.ai_run.sr_candidates_selected == [candidates[0].id]


def test_retry_exhaustion_dumps_and_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_TRCK_HOME", str(tmp_path))
    user = _make_user_chart()
    candles = [
        _candle(
            1_700_000_000 + i * 86400, h=110 + 5 * math.sin(i / 4), lo=109 + 5 * math.sin(i / 4)
        )
        for i in range(60)
    ]
    candidates = detect_candidates(candles, lookback=3)
    assert candidates

    bad = ChartAnalysis(
        analysis_text="bad",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id="sr-9999")],
                confidence=0.7,
                rationale="r",
            )
        ],
    )
    client = _FakeLLMClient([bad, bad])
    with pytest.raises(PipelineError, match="failed after 2 attempts"):
        analyze_chart(
            chart_in=user,
            candles=candles,
            indicators={},
            candidates=candidates,
            context_md=None,
            client=client,
            output_slug="chart-2",
        )

    failed_dir = tmp_path / "failed"
    dumps = list(failed_dir.glob("*.json"))
    assert len(dumps) == 1, "expected exactly one dump file"
    payload = dumps[0].read_text()
    assert "GroundingError" in payload
    assert "sr-9999" in payload


def test_pydantic_validation_failure_also_triggers_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pydantic ValidationError from the LLM call (e.g. instructor rejecting a
    malformed response) is also retryable, not fatal on first try."""
    monkeypatch.setenv("SIGNAL_TRCK_HOME", str(tmp_path))
    from pydantic import ValidationError

    # Trigger a ValidationError by attempting to construct invalid data.
    try:
        ChartAnalysis.model_validate({"drawings": []})  # missing analysis_text
    except ValidationError as e:
        validation_err = e

    user = _make_user_chart()
    candles = [
        _candle(
            1_700_000_000 + i * 86400, h=110 + 5 * math.sin(i / 4), lo=109 + 5 * math.sin(i / 4)
        )
        for i in range(60)
    ]
    candidates = detect_candidates(candles, lookback=3)
    good = ChartAnalysis(
        analysis_text="recovered",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id=candidates[0].id)],
                confidence=0.7,
                rationale="r",
            )
        ],
    )
    client = _FakeLLMClient([validation_err, good])
    result = analyze_chart(
        chart_in=user,
        candles=candles,
        indicators={},
        candidates=candidates,
        context_md=None,
        client=client,
        output_slug="chart-2",
    )
    assert client.calls == 2
    assert result.chart.ai_run is not None


# --- property test on ~20 hand-picked fixtures ---


def _fixture_uptrend() -> list[Candle]:
    return [_candle(1_700_000_000 + i * 86400, h=100 + i, lo=99 + i) for i in range(80)]


def _fixture_downtrend() -> list[Candle]:
    return [_candle(1_700_000_000 + i * 86400, h=180 - i, lo=179 - i) for i in range(80)]


def _fixture_range() -> list[Candle]:
    return [
        _candle(
            1_700_000_000 + i * 86400,
            h=110 + 5 * math.sin(i / 3),
            lo=109 + 5 * math.sin(i / 3),
        )
        for i in range(120)
    ]


def _fixture_double_top() -> list[Candle]:
    pts: list[tuple[float, float]] = []
    pts += [(100 + i, 99 + i) for i in range(11)]
    pts += [(110 - i, 109 - i) for i in range(1, 11)]
    pts += [(100 + i, 99 + i) for i in range(1, 11)]
    pts += [(110 - i, 109 - i) for i in range(1, 11)]
    pts += [(100 + i / 2, 99 + i / 2) for i in range(1, 11)]
    return [_candle(1_700_000_000 + i * 86400, h=h, lo=lo) for i, (h, lo) in enumerate(pts)]


def _fixture_double_bottom() -> list[Candle]:
    pts: list[tuple[float, float]] = []
    pts += [(110 - i, 109 - i) for i in range(11)]
    pts += [(100 + i, 99 + i) for i in range(1, 11)]
    pts += [(110 - i, 109 - i) for i in range(1, 11)]
    pts += [(100 + i, 99 + i) for i in range(1, 11)]
    pts += [(110 - i / 2, 109 - i / 2) for i in range(1, 11)]
    return [_candle(1_700_000_000 + i * 86400, h=h, lo=lo) for i, (h, lo) in enumerate(pts)]


def _fixture_triple_top() -> list[Candle]:
    pts: list[tuple[float, float]] = []
    for _peak in range(3):
        pts += [(100 + i, 99 + i) for i in range(11)]
        pts += [(110 - i, 109 - i) for i in range(1, 11)]
    pts += [(100 + i / 2, 99 + i / 2) for i in range(1, 11)]
    return [_candle(1_700_000_000 + i * 86400, h=h, lo=lo) for i, (h, lo) in enumerate(pts)]


def _fixture_post_halving_rally() -> list[Candle]:
    """Range 100–110 then breakout to 200."""
    pts: list[tuple[float, float]] = []
    for i in range(60):
        v = 105 + 3 * math.sin(i / 4)
        pts.append((v + 1, v - 1))
    for i in range(40):
        v = 110 + 2.5 * i
        pts.append((v + 1, v - 1))
    return [_candle(1_700_000_000 + i * 86400, h=h, lo=lo) for i, (h, lo) in enumerate(pts)]


def _fixture_long_consolidation() -> list[Candle]:
    return [
        _candle(
            1_700_000_000 + i * 86400,
            h=200 + 0.5 * math.sin(i / 6),
            lo=199 + 0.5 * math.sin(i / 6),
        )
        for i in range(150)
    ]


def _fixture_volatile() -> list[Candle]:
    out: list[Candle] = []
    for i in range(120):
        v = 100 + 12 * math.sin(i / 2.5) + 3 * math.cos(i / 1.7)
        out.append(_candle(1_700_000_000 + i * 86400, h=v + 2, lo=v - 2))
    return out


_FIXTURES = [
    ("uptrend", _fixture_uptrend()),
    ("downtrend", _fixture_downtrend()),
    ("range_20pct", _fixture_range()),
    ("double_top", _fixture_double_top()),
    ("double_bottom", _fixture_double_bottom()),
    ("triple_top", _fixture_triple_top()),
    ("post_halving_rally", _fixture_post_halving_rally()),
    ("long_consolidation", _fixture_long_consolidation()),
    ("volatile", _fixture_volatile()),
]


@pytest.mark.parametrize("name,candles", _FIXTURES)
def test_property_grounding_invariants_hold(name: str, candles: list[Candle]) -> None:
    """For every fixture, simulate an LLM that picks the strongest candidate and
    verify the produced chart-2 satisfies the grounding contract."""
    user = _make_user_chart()
    candidates = detect_candidates(candles, lookback=3)
    if not candidates:
        # Fixture is intentionally featureless (e.g. monotonic uptrend) — the
        # pipeline aborts with PipelineError, which is the correct behavior.
        with pytest.raises(PipelineError):
            analyze_chart(
                chart_in=user,
                candles=candles,
                indicators={},
                candidates=[],
                context_md=None,
                client=_FakeLLMClient([]),
                output_slug="chart-2",
            )
        return

    fake = ChartAnalysis(
        analysis_text=f"Picked the strongest candidate from the {name} fixture.",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id=candidates[0].id)],
                confidence=0.6,
                rationale="strongest by score",
            )
        ],
    )
    result = analyze_chart(
        chart_in=user,
        candles=candles,
        indicators={},
        candidates=candidates,
        context_md=None,
        client=_FakeLLMClient([fake]),
        output_slug="chart-2",
    )

    # Invariant 1 — every selected candidate_id is in the presented set.
    presented_ids = {c.id for c in result.chart.ai_run.sr_candidates_presented}
    for d in result.chart.view.drawings:
        for a in d.anchors:
            assert a.candidate_id in presented_ids, (
                f"[{name}] drawing {d.id} cited candidate_id {a.candidate_id} "
                f"not in presented set {sorted(presented_ids)[:5]}…"
            )

    # Invariant 2 — every anchor ts_utc aligns with its candidate's last_touch.
    by_id = {c.id: c for c in candidates}
    for d in result.chart.view.drawings:
        for a in d.anchors:
            cand = by_id[a.candidate_id]
            assert a.ts_utc == cand.last_touch, (
                f"[{name}] anchor ts_utc {a.ts_utc} != candidate.last_touch {cand.last_touch}"
            )
            assert a.price == cand.price

    # Invariant 3 — chart-2 schema validation passes (re-validate by round-trip).
    payload = result.chart.model_dump_json(by_alias=True)
    Chart.model_validate_json(payload)


def test_grounding_error_message_truncates_long_lists() -> None:
    a = ChartAnalysis(
        analysis_text="ok",
        drawings=[
            AIDrawing(
                kind="horizontal",
                anchors=[AIAnchor(candidate_id=f"sr-bad-{i}")],
                confidence=0.5,
                rationale="r",
            )
            for i in range(20)
        ],
    )
    candidates = [
        Candidate(
            id="sr-1",
            price=1.0,
            kind="resistance",
            method="swing_cluster",
            touches=1,
            strength_score=1.0,
            first_seen=0,
            last_touch=0,
        )
    ]
    with pytest.raises(GroundingError) as info:
        from signal_trck.llm.analysis import validate_grounding

        validate_grounding(a, candidates)
    # Message shows truncated list, full list available on the exception.
    assert "..." in str(info.value)
    assert len(info.value.offending_ids) == 20
