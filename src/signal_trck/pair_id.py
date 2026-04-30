"""Canonical pair identifier handling.

Format: ``{source}:{base}-{quote}`` (e.g. ``coinbase:BTC-USD``).

URL-safe (no slashes), shell-safe (no special characters), and source-prefixed
so the same base symbol on different exchanges is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass


class PairIdError(ValueError):
    """Raised when a pair id string is malformed.

    Subclass of ``ValueError`` so existing callers that catch ``ValueError``
    keep working; the API layer maps it to 400 ``INVALID_PAIR_ID``.
    """


@dataclass(frozen=True)
class PairId:
    source: str
    base: str
    quote: str

    @property
    def value(self) -> str:
        return f"{self.source}:{self.base}-{self.quote}"

    @property
    def display(self) -> str:
        """Pretty form for UIs and logs only — never use in URLs or filenames."""
        return f"{self.base}/{self.quote} @ {self.source}"

    def __str__(self) -> str:
        return self.value


def parse(s: str) -> PairId:
    """Parse a pair string. Accepts ``coinbase:BTC-USD`` only.

    Raises ``PairIdError`` for ambiguous or malformed input.
    """
    if ":" not in s:
        raise PairIdError(
            f"pair id must be '{{source}}:{{base}}-{{quote}}' (got {s!r}); "
            f"example: 'coinbase:BTC-USD'"
        )
    source, _, rest = s.partition(":")
    if not source or "-" not in rest:
        raise PairIdError(f"malformed pair id {s!r}; example: 'coinbase:BTC-USD'")
    base, _, quote = rest.partition("-")
    if not base or not quote:
        raise PairIdError(f"malformed pair id {s!r}; example: 'coinbase:BTC-USD'")
    return PairId(source=source.lower(), base=base.upper(), quote=quote.upper())
