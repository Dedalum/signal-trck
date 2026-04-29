---
status: complete
priority: p1
issue_id: 002
tags: [code-review, architecture, phase-b-blocker, llm]
dependencies: [001]
---

# `cli/ai.py:_run` opens Store twice with sync LLM call between

## Problem Statement

The `signal-trck ai analyze` CLI handler opens `Store` twice in one
invocation, with a synchronous `analyze_chart` (which makes a 5–30s LLM
network call) sandwiched between. This is a real bug for Phase B:

1. The sync LLM call inside an async function blocks the event loop for
   the duration of the API request — fine for a CLI, fatal for a FastAPI
   handler that wants concurrency.
2. The second `Store.open()` re-runs migrations against a connected DB
   (idempotent, but wasted ceremony every time).
3. The DB handle is held across the LLM call, defeating SQLite's
   single-writer model under any concurrent activity.

## Findings

From Kieran-Python review, Critical C2.

**`src/signal_trck/cli/ai.py`:**
- Line 129: `async with Store.open() as store:` (first open — for reading
  candles, indicators, computing candidates)
- Line 192: synchronous `result = analyze_chart(...)` blocking call
  inside the first `async with`
- Line 206: `async with Store.open() as store:` (second open — to write
  the audit row)

The pipeline reads, then makes an external network call, then writes — the
DB connection should be released *before* the network call.

## Proposed Solutions

**Option A — Single Store, LLM call outside the `async with` block**
- Pros: Releases DB handle before the slow network call. Single migration
  run. Idiomatic.
- Cons: Some restructuring (need to extract candle/indicator/candidate
  loading out of the same `with`).
- Effort: Small.
- Risk: Low — the audit-row write is the only side effect after the LLM
  call.

**Option B — Two separate functions: `prepare_inputs` (async, DB) and
`persist_outputs` (async, DB), with sync `analyze_chart` between**
- Pros: Cleaner separation of phases. Easier to wrap in FastAPI handlers
  for Phase C (when AI moves into the web).
- Cons: More code for the v1 case.
- Effort: Small-Medium.
- Risk: Low.

## Recommended Action

**Option A.** The fix is mechanical:
```python
# Before
async with Store.open() as store:
    candles = await store.get_candles(...)
    indicators = ...  # compute_or_load loop
    candidates = detect_candidates(candles)

if dry_run: ...

# LLM call (sync, blocks loop) — currently INSIDE the async with above
result = analyze_chart(...)

async with Store.open() as store:  # second open — fix below
    await store.write_ai_run(...)
```

```python
# After
async with Store.open() as store:
    candles = await store.get_candles(...)
    indicators = ...  # compute_or_load loop
    candidates = detect_candidates(candles)
# DB handle released here

if dry_run: ...

result = analyze_chart(...)  # LLM call, no DB held

async with Store.open() as store:
    await store.write_ai_run(...)  # new lightweight session
```

Or even simpler: keep one `Store` and explicitly `await store.close()`
before the LLM call, then re-open. But Option A's "two `with` blocks"
shape is the most idiomatic.

## Technical Details

**Affected files:** `src/signal_trck/cli/ai.py:_run`

**No DB changes. No test changes.**

## Acceptance Criteria

- [ ] `cli/ai.py:_run` opens Store at most once before the LLM call,
      releases it before `analyze_chart`, and reopens for the audit
      write.
- [ ] No migrations run during the second `Store.open()` (verify by
      checking `storage.migrate` log events on a real run — should appear
      once, not twice).
- [ ] All 134 tests still pass.
- [ ] Manual smoke: `signal-trck ai analyze --dry-run` and a real
      analyze run work end-to-end.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: Critical C2
- Related todo: 001 (async/sync seam)
