---
status: complete
priority: p2
issue_id: 009
tags: [code-review, tests, llm, cli]
dependencies: []
---

# No CLI smoke test for `signal-trck ai analyze`

## Problem Statement

`tests/test_cli.py` covers `pair`, `dev`, `version`, `--help` but leaves
the most important command — `signal-trck ai analyze` — unexercised.
This is the phase-A differentiator. Any change to its CLI argument
parsing, file IO, or pipeline integration could break silently.

## Findings

From Kieran-Python review, "Coverage gaps that will bite Phase B."

**`tests/test_cli.py`** exists but has no `test_ai_analyze_*` cases.
The pipeline itself is well-tested via `test_ai_pipeline.py` (with mocked
`LLMClient`). But the CLI wrapper — argument parsing, `chart_io.read_chart`
integration, dry-run output, error paths — is not exercised end-to-end.

## Proposed Solutions

**Option A — Add CLI smoke test using `--dry-run` + seeded data**
- Use the existing `dev seed` command to populate a test DB with
  synthetic candles + a hand-written `chart-1.json` fixture.
- Invoke `runner.invoke(app, ["ai", "analyze", "--input", ..., "--output",
  ..., "--dry-run"])`.
- Assert exit code 0, stdout contains the expected dry-run summary lines
  (pair, candles, indicators, candidates, provider:model).
- Pros: Exercises the full CLI surface short of the LLM call.
- Cons: Doesn't test the LLM-call path (covered separately by
  test_ai_pipeline.py).
- Effort: Small (~30 LOC).
- Risk: Low.

**Option B — Add full pipeline test with mock LLM via `monkeypatch`**
- Patch `signal_trck.cli.ai.build_client` to return a `_FakeLLMClient`
  (already exists in test_ai_pipeline.py).
- Test full path: parse args → load chart → run pipeline → write
  chart-2 → assert ai_runs row exists.
- Pros: Highest coverage.
- Cons: More test setup; some duplication with test_ai_pipeline.py.
- Effort: Medium.
- Risk: Low-Medium.

## Recommended Action

**Both** — Option A as a quick smoke (catches arg-parsing regressions),
Option B as the integration test (catches CLI ↔ pipeline contract
regressions). Option A is the priority; B can come later.

## Technical Details

**Affected files:**
- `tests/test_cli.py` — add `test_ai_analyze_dry_run`
- Possibly new: `tests/test_ai_cli_integration.py` for Option B

**Fixture:** create a tests/fixtures directory with a hand-written
chart-1.json + use `dev seed` to populate candles for the test pair
(`dev:DEMO-USD`, the existing seed pair).

## Acceptance Criteria

- [ ] At least one new test: `test_ai_analyze_dry_run` using the seed
      pair + a fixture chart-1.json.
- [ ] Test asserts the dry-run summary includes the expected pair name,
      candle count, indicator names, candidate count, provider:model
      line.
- [ ] Test passes without any LLM API key configured.
- [ ] All 134 existing tests still pass.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: "Coverage gaps that will bite Phase B"
- Existing pattern: `tests/test_cli.py:test_dev_seed_then_info`
- Existing fake: `tests/test_ai_pipeline.py:_FakeLLMClient`
