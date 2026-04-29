---
status: complete
priority: p2
issue_id: 008
tags: [code-review, tests, concurrency, phase-b-prep]
dependencies: []
---

# Add concurrent-writes test for the Store

## Problem Statement

Phase A has zero tests for concurrent writes to the Store. Phase B will
have two requests racing on the same pair (one fetching, one computing
indicators). WAL helps but doesn't make `INSERT ON CONFLICT DO UPDATE`
semantics free. Two concurrent `compute_or_load` calls for the same
`(pair, indicator, params)` would both miss → both compute → both call
`_delete_then_insert` → the deletes race and the cache could end up empty
or partially populated.

## Findings

From Kieran-Python review, "Coverage gaps that will bite Phase B."

**No test exercises:**
1. Two `Store.upsert_candles` calls running simultaneously (same pair,
   overlapping timestamps).
2. Two `compute_or_load` calls running simultaneously (same pair,
   indicator, params).
3. Reader (e.g., `signal-trck indicators sma`) reading while a writer
   (e.g., `signal-trck fetch`) is upserting.

These are exactly the workloads Phase B will introduce.

## Proposed Solutions

**Option A — Add `tests/test_storage_concurrency.py`**
- Test 1: `asyncio.gather` two `upsert_candles` with overlapping rows;
  verify final state is consistent.
- Test 2: `asyncio.gather` two `compute_or_load` for same params;
  verify only one "winning" delete+insert and the cache is consistent.
- Test 3: One reader + one writer; verify reader sees consistent state
  (either pre-write or post-write, never partial).
- Pros: Catches races now, before Phase B exposes them under real load.
- Cons: Tests can be flaky; need careful design.
- Effort: Medium.
- Risk: Medium for test design.

**Option B — Defer until Phase B observes a bug**
- Pros: Zero work now.
- Cons: Phase B will discover races under real concurrent load —
  harder to debug then.

## Recommended Action

**Option A.** Once todo 004 lands (`Store.replace_indicator_rows` as a
single transaction), the concurrency story improves naturally — but we
still need tests that prove it.

## Technical Details

**Affected files:**
- New: `tests/test_storage_concurrency.py`

**Implementation note:** SQLite under WAL mode allows concurrent reads
during a write. `asyncio.gather` with two awaitables on the same Store
serializes them via aiosqlite's single-thread executor — but distinct
Store instances (or distinct DB connections) race for real.

For tests:
- Use distinct `Store` instances pointing at the same DB path.
- `await asyncio.gather(s1.upsert_candles(...), s2.upsert_candles(...))`
  to force concurrency.
- Verify SELECT result matches one of the legal outcomes
  (last-writer-wins by ts_utc).

## Acceptance Criteria

- [ ] `tests/test_storage_concurrency.py` exists with at least 3 tests:
      concurrent upsert_candles, concurrent compute_or_load, concurrent
      read+write.
- [ ] Tests are deterministic (no random sleeps, no tolerance for
      flakiness).
- [ ] All tests pass on first run, and on 10 consecutive runs (sanity
      check for flakiness — `pytest --count 10` if pytest-repeat is
      adopted, otherwise manual loop).

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: "Coverage gaps that will bite Phase B"
- Related todo: 004 (Store.replace_indicator_rows)
- [SQLite WAL docs](https://www.sqlite.org/wal.html)
