"""Stable hashing for indicator parameter dicts.

Hash spec (locked — see plan §"Decisions made post-review"):

    sha256(json.dumps(params, sort_keys=True, separators=(",", ":"))).hexdigest()[:16]

Float parameters that are integer-valued (e.g. ``period: 50.0``) are coerced
to ``int`` before hashing. This keeps the cache hit when a JSON round-trip
turns an int into a float, *without* turning ``period: 50.5`` into ``50``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_HASH_LEN = 16


def _canonicalize(value: Any) -> Any:
    """Normalize a single value before hashing.

    - ``True``/``False`` left as-is (JSON-serializable).
    - ``int`` left as-is.
    - ``float`` coerced to ``int`` if it has no fractional part.
    - dicts and lists recursed.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def params_hash(params: dict[str, Any]) -> str:
    """Stable, short hash of an indicator's parameters.

    Two dicts that differ only in JSON round-trip artifacts (key order,
    int vs ``int.0`` floats) hash identically. Genuinely different params
    (different period, different MA type) hash differently.
    """
    canonical = _canonicalize(params)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_HASH_LEN]
