"""FastAPI surface for signal-trck Phase B web UI.

Three files: ``app.py`` (FastAPI factory + lifespan + middleware), ``routes.py``
(all 14 handlers), ``errors.py`` (exception handlers). Decision 13 in the
Phase B plan: split when one file genuinely hurts (~400 LOC), not before.
"""

from signal_trck.api.app import app

__all__ = ["app"]
