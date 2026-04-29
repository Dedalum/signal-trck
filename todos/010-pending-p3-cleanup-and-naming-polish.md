---
status: pending
priority: p3
issue_id: 010
tags: [code-review, cleanup, naming, simplicity]
dependencies: []
---

# Phase A cleanup batch — naming, dead code, minor polish

## Problem Statement

A grouped batch of nice-to-have findings from the Phase A review. None
block Phase B; all compound if left. Best handled as a single sweep PR
when the rest of the P1/P2 work is settled.

## Findings

Compiled from Kieran-Python and Simplicity reviews — items that are
small, mechanical, or cosmetic.

### Dead code / inlining

- **`llm/client.py:resolve_model`** is dead — only used inside
  `build_client` which already does the same. Drop. (Simplicity #3)
- **`log.py:new_run_id`** is called only inside `bind_run`. Inline it
  (single `uuid.uuid4().hex[:12]`). (Simplicity #8)

### Naming

- `cache_name(name, output_key)` → `cache_key_for(indicator, output)`.
  "Name" is overloaded already. (Kieran rename list)
- `IndicatorSeries.values` → rename or restructure — `ndarray.values` is
  a pandas-ism that doesn't fit. (Kieran rename list)
- `validate_grounding` → `assert_grounded` for consistency with
  `_resolve_anchor`'s assertive name. (Kieran rename list)
- `cache_name`'s mixed case asymmetry: returns `"SMA"` (uppercase) for
  single-output, `"MACD.macd"` (mixed) for multi-output. Pick one
  convention and document it. (Kieran nit n1)
- `Provenance` validator wording: "must be empty when kind == 'user'" →
  "must not be set when kind == 'user'" reads more naturally for a
  Python dev. (Kieran minor m6)

### Redundancy / consistency

- **`AIRunAudit` (`pipeline.py:64`)** is a dataclass while
  `SRCandidate` is a Pydantic model — same audit row, two shapes. CLI
  re-dumps each side separately. Promote to Pydantic so
  `Store.write_ai_run` takes the model and does the JSON dance once.
  (Kieran nit n3)
- **`AIRunAudit.sr_candidates_presented`/`sr_candidates_selected`**
  duplicates `chart.ai_run.sr_candidates_*` — drop from `AIRunAudit`,
  read from `result.chart.ai_run` in `cli/ai.py`. (Simplicity #5)
- **NaN detection inconsistency**: `prompts.py:99` uses `if v == v:
  # NaN != NaN`; `indicators/cache.py:137` and `cli/indicators.py:23`
  use `np.isnan(v)`. Pick `not math.isnan(v)` or `np.isnan` and apply
  consistently. (Kieran minor m4)

### Structure

- **`cli/ai.py:_run`** has a 14-arg signature. Pack into a `RunConfig`
  dataclass or move some args into the body. (Simplicity #10, Kieran
  implicit)
- **`cli/main.py:21`** registers `ai analyze` twice (once via
  `add_typer`, once via `app.command("analyze")`). Pick one wiring style.
  (Simplicity #9)
- **`_estimate_tokens`** (`cli/ai.py:257`) duplicates structure already
  in `build_user_prompt`. When the prompt format changes, this drifts.
  Easier: build the prompt once, then `len(prompt) // 4`. (Kieran minor
  m3)
- **`_resolve_anchor`** (`pipeline.py:254`) trusts that
  `validate_grounding` ran first. Add a guarding `KeyError` →
  `GroundingError` re-raise. (Kieran minor m1)
- **`_dump_failure` filename sanitization** (`pipeline.py:313`) does
  `.replace(":", "_").replace("-", "_")` inline. Move to
  `paths.dump_filename(pair_id, ts)`. (Kieran minor m5)
- **`_validate_schema_version` message** in `chart_schema/models.py`
  refers to `scripts/` directory that doesn't exist yet. Trim message
  to one line. (Simplicity #4)
- **`cli/ai.py:80`** — `chosen_provider: Provider = provider or
  cfg.settings.llm_provider` with `# type: ignore[assignment]`. Validate
  before assigning, then `cast(Provider, ...)`. (Kieran minor m2)
- **Lambda in `_detect_swings`** (`swing_cluster.py:114,117`) uses
  `noqa: E731`. Replace with `operator.gt`/`operator.lt` or inline.
  (Kieran nit n2)

### Tests

- **Property-test docstring count**
  (`tests/test_ai_pipeline.py` line 6): "~20 fixtures" → "9 fixtures"
  (the count was already cut at planning; the comment didn't follow).
  (Simplicity #11)
- **`test_pydantic_validation_failure_also_triggers_retry`** manufactures
  a `ValidationError` via try-catch. Cleaner with a callable in the
  fake. Cosmetic only. (Simplicity #11)

### Performance (not P1)

- **Index column reorder** for `indicator_values`: current is
  `(pair_id, interval, name, params_hash, ts_utc DESC)`. The query
  pattern is `WHERE pair_id=? AND interval=? AND params_hash=? AND
  name IN (...)` which would benefit from
  `(pair_id, interval, params_hash, name, ts_utc DESC)`. Micro-opt;
  invisible at <100k rows. (Performance M1)

## Recommended Action

Bundle these into a single "Phase A polish" PR after the P1/P2 items
land. Each individual item is 1–10 LOC; the whole batch is maybe 200
LOC. Don't try to ship them all at once if they spread across many
modules — split by module if needed.

## Technical Details

Affected files (alphabetical):
- `src/signal_trck/cli/ai.py`
- `src/signal_trck/cli/main.py`
- `src/signal_trck/chart_schema/models.py`
- `src/signal_trck/indicators/cache.py`
- `src/signal_trck/indicators/__init__.py`
- `src/signal_trck/levels/swing_cluster.py`
- `src/signal_trck/llm/analysis.py`
- `src/signal_trck/llm/client.py`
- `src/signal_trck/llm/pipeline.py`
- `src/signal_trck/llm/prompts.py`
- `src/signal_trck/log.py`
- `src/signal_trck/paths.py`
- `src/signal_trck/storage/schema.py`
- `tests/test_ai_pipeline.py`

## Acceptance Criteria

- [ ] All listed dead-code items removed
- [ ] Naming changes applied with passing tests
- [ ] No `# type: ignore` comments added in this batch (preferably some
      removed)
- [ ] All 134 existing tests still pass after each item
- [ ] No `noqa: E731` or `noqa: B008` (other than already-justified
      cli/per-file-ignores) in this batch's diff

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: minor + nit findings
- Simplicity review: items 3, 4, 5, 8, 9, 10, 11
- Performance review: Medium M1 (index reorder)
