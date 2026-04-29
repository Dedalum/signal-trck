---
status: complete
priority: p1
issue_id: 003
tags: [code-review, performance, phase-b-blocker, indicators, cache]
dependencies: []
---

# `compute_or_load` does full candle scan on every cache hit

## Problem Statement

On every call — including pure cache hits — `compute_or_load` loads **all
candles** for the pair/interval, then does a second full read of
`indicator_values`. For Phase B's "live update on each candle refresh"
use case, a chart render touching 5 indicators × 43 800 hourly rows = ~440k
row materializations per render. At v1: 2–15ms per render (fine). At
Phase B: 50–150ms per render, paid every refresh.

## Findings

From Performance review, Critical C1.

**`src/signal_trck/indicators/cache.py:74`:**
```python
candles = await store.get_candles(pair_id, interval)
```
Always runs, regardless of cache state. Used only to extract `candle_ts`
(for the "fully cached" length check) and as a fallback for the miss path.

**`src/signal_trck/indicators/cache.py:85` (`_load_cached_rows`)** also
loads all `indicator_values` rows for the pair/interval/name/params,
regardless of how many the caller actually wants.

Performance reviewer's measured/estimated impact at Phase B scale: 50–150ms
per chart render, scaling linearly with indicator count and history depth.

## Proposed Solutions

**Option A — Use `latest_candle_ts` + `candle_count` on the hit path**
(Performance reviewer's recommendation)
- Replace the `get_candles` call with `Store.candle_count(pair_id, interval)`
  and `Store.latest_candle_ts(pair_id, interval)` (both already exist on
  the Store class — see `storage/store.py:233, 246`).
- If cached row count for first `cache_key` equals `candle_count` AND
  latest cached `ts_utc` equals `latest_candle_ts`, declare a hit and
  return only the indicator rows.
- Only call `get_candles` on the miss path.

Pros: Replaces a 1825-row scan with two indexed `MAX/COUNT` queries
(microseconds). Net win on every hit; no change on miss.
Cons: Slight logic change in cache.py.
Effort: Small.
Risk: Low — the `candle_count` and `latest_candle_ts` methods already
have tests; just compose them.

**Option B — In-memory N-timestamps cache per process**
- Maintain a `dict[(pair_id, interval), list[int]]` of cached timestamps.
- Hit fast-path consults the dict.
- Cons: Process-local; two concurrent CLI runs duplicate work; cache
  invalidation on candle write becomes a concern.
- Effort: Medium.
- Risk: Medium.

**Option C — Leave as-is**
- The current cost is fine at v1 scale.
- Cons: Phase B will pay it on every chart render.
- Effort: Zero.
- Risk: Low for v1, growing for Phase B.

## Recommended Action

**Option A.** Cheap, idiomatic, uses methods that already exist. Land
this before Phase B's first chart-render endpoint.

## Technical Details

**Affected files:**
- `src/signal_trck/indicators/cache.py:compute_or_load` — restructure
  hit path
- Tests: `tests/test_indicator_cache.py` — add a test that proves the
  hit path doesn't load candles (mock or assert on Store call count)

**No DB schema changes.**

## Acceptance Criteria

- [ ] `compute_or_load` cache-hit path calls `candle_count` +
      `latest_candle_ts` instead of `get_candles`.
- [ ] Cache miss still loads candles via `get_candles` and computes
      indicators.
- [ ] New test: cache-hit path doesn't fetch full candles (use a
      `Mock(wraps=store)` or per-test counter to assert call count).
- [ ] All 134 existing tests still pass.
- [ ] Manual: run `signal-trck indicators sma coinbase:BTC-USD` twice;
      second run should be measurably faster (verify via `--log-level
      DEBUG` showing only `cache_hit` event, no candle-loading
      activity).

## Work Log

_Empty — not yet started._

## Resources

- Performance review: Critical C1
- `src/signal_trck/storage/store.py:233-252` — `candle_count` and
  `latest_candle_ts` methods already exist
