---
status: complete
priority: p2
issue_id: 004
tags: [code-review, architecture, simplicity, indicators, store]
dependencies: [003]
---

# Indicator-cache SQL leaks out of the Store

## Problem Statement

`src/signal_trck/indicators/cache.py` contains two SQL helper functions —
`_load_cached_rows` and `_delete_then_insert` — that violate the
architectural invariant stated in `docs/architecture.md`:

> "Storage: `Store` class hides all SQL strings. No `await
> db.execute("SELECT ...")` outside `storage/store.py`."

Additionally, the same file uses a smelly placeholder `""`-in-tuple
shape in `rows_to_persist` that gets stripped on insert.

## Findings

From Simplicity review (#1, single highest-leverage simplification).

**`src/signal_trck/indicators/cache.py:131,139,206-207`:** the
`rows_to_persist` list packs 7-tuples with `""` at index 4. The
`_delete_then_insert` function then strips it back out on insert. The
placeholder exists to coexist with a tuple shape that doesn't actually
exist upstream.

**`src/signal_trck/indicators/cache.py:154-178` (`_load_cached_rows`)
and `181-209` (`_delete_then_insert`):** pure SQL with no business logic,
operating on the `indicator_values` table. These belong on `Store`.

## Proposed Solutions

**Option A — Move both functions to `Store` as typed methods**
- New on Store: `Store.get_indicator_rows(pair_id, interval, names,
  params_hash) -> dict[str, list[tuple[int, float]]]`
- New on Store: `Store.replace_indicator_rows(pair_id, interval, names,
  params_hash, rows)` — does delete + insert in one transaction
- Drop the 7-tuple placeholder; use 6-tuples directly
- Pros: Restores the architectural invariant. Cache file drops to
  ~150 LOC. The Phase B FastAPI endpoint
  `GET /pairs/{id}/indicators/{name}` becomes a one-line wrapper.
- Cons: Touches Store (which already has 12+ public methods).
- Effort: Small (moving code, no logic change).
- Risk: Low.

**Option B — Leave as-is**
- Pros: No work.
- Cons: Architectural debt compounds. The `# Strip the placeholder
  column` comment in `cache.py:206` is an apology for the smell.
- Effort: Zero.
- Risk: Compounds with each new use of cache.

## Recommended Action

**Option A.** Done correctly, this both fixes the smell and prepares
the API for Phase B's web layer.

## Technical Details

**Affected files:**
- `src/signal_trck/storage/store.py` — add two methods
- `src/signal_trck/indicators/cache.py` — replace internal helpers with
  Store methods, drop placeholder tuple
- `tests/test_indicator_cache.py` — should still pass; add a Store-level
  test for the new methods

## Acceptance Criteria

- [ ] `Store.get_indicator_rows(...)` exists with a typed return.
- [ ] `Store.replace_indicator_rows(...)` exists, atomic (delete + insert
      in one commit).
- [ ] `cache.py` no longer contains `await store.conn.execute(...)`
      or `await store.conn.executemany(...)`.
- [ ] `rows_to_persist` is `list[tuple[str, str, str, str, int, float]]`
      (6 fields, no placeholder).
- [ ] All 134 existing tests still pass.
- [ ] At least one new test exercising `Store.replace_indicator_rows`
      atomicity.

## Work Log

_Empty — not yet started._

## Resources

- Simplicity review: #1 — single highest-leverage simplification
- `docs/architecture.md` §"Conventions to keep using" — Store SQL discipline
