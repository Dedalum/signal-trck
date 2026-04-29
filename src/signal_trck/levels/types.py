"""Shapes returned by the levels engine.

These mirror the ``SRCandidate`` model in ``chart_schema`` but are kept here
as plain dataclasses so the engine has no Pydantic dependency. Conversion
to ``SRCandidate`` happens at the API/CLI/LLM boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CandidateKind = Literal["support", "resistance"]
CandidateMethod = Literal["swing_cluster"]
# Future methods to be added without touching this Literal until ready:
# "pivot_classic", "pivot_fibonacci", "volume_profile", "trend".


@dataclass(frozen=True, slots=True)
class Candidate:
    """A single S/R candidate level.

    ``id`` is monotonic within a candidate batch (``sr-1``, ``sr-2``, …).
    The ``strength_score`` ranks candidates within the batch (higher = more
    confidence). The LLM picks levels by ``id``; the server resolves them
    back to ``price`` at insert time so prices are never invented.
    """

    id: str
    price: float
    kind: CandidateKind
    method: CandidateMethod
    touches: int
    strength_score: float
    first_seen: int  # ts_utc, unix seconds
    last_touch: int  # ts_utc, unix seconds
