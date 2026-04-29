---
status: complete
priority: p2
issue_id: 005
tags: [code-review, architecture, phase-b-prep, types, audit]
dependencies: []
---

# `Store.list_ai_runs` returns `list[dict]` instead of typed dataclass

## Problem Statement

Every other Store method returns a typed dataclass (`Pair`, `Candle`).
`list_ai_runs` returns `list[dict]` with raw JSON strings for the
`sr_candidates_presented` and `sr_candidates_selected` columns. When
Phase B adds `GET /pairs/{id}/ai_runs`, every web caller will rewrite
the same parsing code.

## Findings

From Kieran-Python review, Major M3.

**`src/signal_trck/storage/store.py:298`:**
```python
return [dict(zip(cols, r, strict=True)) for r in rows]
```

The columns include `sr_candidates_presented` and
`sr_candidates_selected` as JSON-string columns; callers must parse them
themselves.

## Proposed Solutions

**Option A — Add `AIRunRow` dataclass in `storage/models.py`**
- New: `AIRunRow(run_id, pair_id, chart_slug, model, provider,
  prompt_template_version, system_prompt_hash, context_file_sha256,
  context_preview, sr_candidates_presented: list[dict],
  sr_candidates_selected: list[str], ran_at)`
- `Store.list_ai_runs` parses the JSON columns at the boundary and
  returns `list[AIRunRow]`.
- Pros: Consistent with `Pair`, `Candle`. Phase B's API serializer can
  return the dataclass directly.
- Cons: One more dataclass in `models.py`.
- Effort: Small.
- Risk: Low.

**Option B — Reuse the `AIRun` Pydantic model from `chart_schema`**
- Pros: One shape for both DB and chart-artifact.
- Cons: `chart_schema.AIRun` carries different fields (no `pair_id`, no
  `ran_at` — those are DB metadata). Forcing them together creates
  optional-field bloat.
- Effort: Medium.
- Risk: Medium.

## Recommended Action

**Option A.** Keep the dataclass-for-storage / Pydantic-for-artifact
distinction (it's the right separation of concerns).

## Technical Details

**Affected files:**
- `src/signal_trck/storage/models.py` — add `AIRunRow`
- `src/signal_trck/storage/store.py:list_ai_runs` — return typed list,
  parse JSON at boundary
- `tests/test_ai_run_storage.py` — update assertions to use typed access

**No DB schema changes.**

## Acceptance Criteria

- [ ] `AIRunRow` dataclass exists in `storage/models.py` with typed
      fields including parsed `sr_candidates_presented` and
      `sr_candidates_selected`.
- [ ] `Store.list_ai_runs` returns `list[AIRunRow]`.
- [ ] All 134 existing tests still pass after type updates.
- [ ] No JSON parsing in callers of `list_ai_runs`.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: Major M3
- `src/signal_trck/storage/models.py` — pattern for `Pair`, `Candle`
