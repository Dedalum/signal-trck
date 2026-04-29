"""Support/resistance candidate engine.

v1 ships a single method: **swing-highs/lows + agglomerative clustering on
close proximity**. The ``method`` field on each ``Candidate`` is reserved
so additional methods (pivot points, volume profile) can be added later
without changing the public shape — see plan §"Implementation phases".
"""

from signal_trck.levels.swing_cluster import detect_candidates
from signal_trck.levels.types import Candidate, CandidateKind, CandidateMethod

__all__ = [
    "Candidate",
    "CandidateKind",
    "CandidateMethod",
    "detect_candidates",
]
