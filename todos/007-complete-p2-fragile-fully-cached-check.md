---
status: complete
priority: p2
issue_id: 007
tags: [code-review, indicators, cache, edge-cases]
dependencies: [003, 004]
---

# Indicator-cache "fully cached" check has hidden edge cases

## Problem Statement

The cache-hit decision in `compute_or_load` declares a hit when "any one
cache_key's row count equals the candle count." This collapses for
multi-output indicators (MACD, BB) where one output fully caches but
another partially fails (process killed mid-batch, constraint violation).
Additionally, `_load_cached_rows` doesn't filter by the actual candle
timestamp set, so a partial-history cache passes the length check but
returns stale rows.

## Findings

From Kieran-Python review, Major M4.

**`src/signal_trck/indicators/cache.py:92`:**
```python
fully_cached = cached_rows and all(
    len(cached_rows.get(k, [])) == len(candle_ts) for k in cache_keys
)
```

The `cached_rows and all(...)` short-circuit hides a bug: if `cached_rows`
is non-empty but missing one cache_key entirely, `cached_rows.get(k, [])`
returns `[]`, length 0, fails the equality check — correctly a miss. So
this specific edge case is fine. But:

**The deeper issue**: `_load_cached_rows` (lines 154–178) doesn't filter
its SELECT by the actual candle timestamps. If the cache contains stale
rows from an earlier run with a different candle history (e.g., the user
cleared and re-fetched candles), the row count check could match the new
candle count by coincidence and return stale indicator values.

This is currently not exploitable because the code path that writes the
cache always rewrites the full series. But the implicit invariant ("cache
rows always match the candle set") isn't enforced and could break with
any future change to how candles are written.

## Proposed Solutions

**Option A — Filter `_load_cached_rows` by exact candle timestamp set**
- Pass the candle ts list into the SELECT; require row count to match
  filtered count.
- Pros: Makes the invariant load-bearing.
- Cons: Larger SQL `WHERE ts_utc IN (...)`, but candle counts are small
  (few thousand) so it's fine.
- Effort: Small.
- Risk: Low.

**Option B — Add a `version` column to `indicator_values` that's
incremented when candles change**
- Cache writes record the `version`; reads reject if mismatched.
- Pros: Decouples cache validity from row-count coincidence.
- Cons: Schema change (migration v4); more state to track.
- Effort: Medium.
- Risk: Medium.

**Option C — Combined with todo 003: rewrite the hit path entirely**
- After todo 003 lands, the hit path uses `candle_count` +
  `latest_candle_ts` instead of full candle scan. Add a check that
  `cached_rows`'s max ts_utc equals the candle's latest ts_utc.
- Pros: Strong invariant ("cache is current to latest candle"), no
  schema change.
- Cons: Depends on todo 003.
- Effort: Small (after 003).
- Risk: Low.

## Recommended Action

**Option C** — depend on todo 003 and tighten the check at the same
time. Single PR, single test addition.

## Technical Details

**Affected files:**
- `src/signal_trck/indicators/cache.py:compute_or_load`
- `tests/test_indicator_cache.py` — add a "stale cache" test:
  populate cache, then add a new candle, verify the next call detects
  staleness.

## Acceptance Criteria

- [ ] Cache hit requires (a) row count for every cache_key equals
      candle_count, AND (b) max cached `ts_utc` equals
      `latest_candle_ts`.
- [ ] New test: write cache, append a candle, call `compute_or_load`
      again — must be a miss (recompute), not a hit on the stale set.
- [ ] All 134 existing tests still pass.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: Major M4
- Related todo: 003 (compute_or_load hit-path rewrite)
