---
status: complete
priority: p1
issue_id: 001
tags: [code-review, architecture, phase-b-blocker, async]
dependencies: []
---

# Async/sync seam will block Phase B

## Problem Statement

Every Typer command wraps work in `asyncio.run(...)` (7 callsites across the
CLI). FastAPI handlers run on an *already-active* event loop — calling
`asyncio.run` from one raises `RuntimeError: This event loop is already
running`. Worse, the data engines mix sync and async inconsistently:
`compute_or_load` is async, `detect_candidates` is sync, `analyze_chart` is
sync but calls async `client.analyze` synchronously via `instructor`. When
Phase B's FastAPI handlers wrap these, the sync calls block the event loop
for every concurrent request.

## Findings

Both Kieran-Python (Critical C1) and Performance reviewer (High H1) flagged
this independently — strongest cross-reviewer signal in the review.

**`asyncio.run` callsites that won't survive a FastAPI handler:**
- `src/signal_trck/cli/ai.py:91`
- `src/signal_trck/cli/fetch.py:65`
- `src/signal_trck/cli/indicators.py:51`
- `src/signal_trck/cli/levels.py:49`
- `src/signal_trck/cli/pair.py:40, 53`
- `src/signal_trck/cli/dev.py:65, 84`

**Sync-blocks-loop callsites:**
- `src/signal_trck/levels/swing_cluster.py:44` — `detect_candidates` is
  sync; ~10–30ms for daily, ~250–600ms estimated for 5y hourly. Will
  freeze every concurrent request.
- `src/signal_trck/llm/pipeline.py:93` — `analyze_chart` is sync; calls
  `client.analyze` synchronously (the LLM round-trip is 5–30s of network
  blocking).

**Honest analysis (Kieran):** SQLite-via-aiosqlite gives no real
concurrency on a single file regardless of WAL. The work in
`compute_or_load` is CPU-bound NumPy. The genuinely-async piece is the
Coinbase HTTP fetch.

## Proposed Solutions

**Option A — Single-line fix: extract `cli/_runner.py:run_async(coro)`**
- Pros: One-place change for Phase B (replace the helper to use
  `asyncio.get_event_loop()` or no-op if already in a loop). Zero
  refactoring of engines. Ships in <30 min.
- Cons: Doesn't fix the underlying sync-blocks-loop issue for
  `detect_candidates` and `analyze_chart` — still need `to_thread`
  wrappers in FastAPI handlers.
- Effort: Small.
- Risk: Low.

**Option B — Make Store sync, keep adapters async**
- Pros: Honest about the shape (SQLite is sync; HTTP is async). Removes
  half the seam friction. `compute_or_load` becomes sync; FastAPI
  handlers wrap it in `to_thread` when needed (consistent pattern).
- Cons: Bigger surgery. Switch `aiosqlite` → `sqlite3`. Adapters keep
  `httpx.AsyncClient`. Touch every Store callsite.
- Effort: Medium.
- Risk: Medium. Test coverage protects.

**Option C — Make everything async, including `detect_candidates` and
`analyze_chart`** by wrapping internals in `asyncio.to_thread`
- Pros: Phase B's FastAPI handlers are fully async-clean.
- Cons: Hides CPU-bound work behind async signature; tests get more
  ceremonial; the genuinely-sync work isn't actually faster.
- Effort: Medium.
- Risk: Medium.

## Recommended Action

Ship **Option A first** (the runner helper) before Phase B starts — cheap
and unblocks the FastAPI handler writing. Defer the larger Option B
decision until Phase B's first handler is on the page and we can measure
which seams hurt. If Option B is right, do it as its own PR with full test
suite green.

For `detect_candidates` and `analyze_chart`: adopt the convention that
**FastAPI handlers wrap them in `asyncio.to_thread()`** (per Performance
reviewer's H1 fix recommendation). Document this in `docs/architecture.md`
when Phase B lands.

## Technical Details

**Affected files (Option A):**
- New: `src/signal_trck/cli/_runner.py`
- All 7 `asyncio.run(...)` callsites listed above

**Affected files (Option B, if pursued):**
- `src/signal_trck/storage/store.py` — switch to `sqlite3`
- All `Store` callsites in cli/, indicators/, levels/, llm/

**No DB changes.**

## Acceptance Criteria

Option A:
- [ ] `cli/_runner.py:run_async(coro)` exists and handles
      already-running-loop case (try `asyncio.get_running_loop()` →
      use `nest_asyncio` or alternative; or `loop.run_until_complete` if
      we control the loop).
- [ ] Every `asyncio.run(...)` in `cli/*.py` replaced with
      `_runner.run_async(...)`.
- [ ] `pytest -q` still passes (all 134 tests).
- [ ] Smoke: `signal-trck pair list`, `signal-trck dev info`, and
      `signal-trck ai analyze --dry-run` work as before.

Option B (if adopted):
- [ ] `Store` class uses `sqlite3` directly, no async methods.
- [ ] `compute_or_load` is sync.
- [ ] Tests updated; concurrency tests (see todo 008) pass.
- [ ] Documentation reflects the change.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review (this PR): Critical C1
- Performance review (this PR): High H1
- `docs/architecture.md` §"Phase B integration points"
