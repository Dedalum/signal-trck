---
title: signal-trck architecture & Phase A retrospective
status: current
phase: A (complete)
last_updated: 2026-04-29
related:
  - plans/feat-crypto-charting-ai-analysis.md
  - README.md
---

# signal-trck — architecture & Phase A retrospective

This is the tour-guide doc for the codebase. It captures **what got built**
in Phase A, **why** the load-bearing decisions were made, and **where** to
look when extending. The full design rationale lives in
[`plans/feat-crypto-charting-ai-analysis.md`](../plans/feat-crypto-charting-ai-analysis.md);
this doc is the "ten-minute orientation" version.

---

## What is signal-trck

A **personal, local-first** tool for longer-term technical analysis of
crypto pairs. The differentiator is **"chart as code"**: every view —
user-made or AI-made — is a versioned `chart.json` artifact, with the AI
**grounded** against pre-computed S/R candidates so it picks levels by
stable ID rather than inventing prices.

Three components, one DB:
1. **Backend + (eventually) UI.** Coinbase Advanced Trade for candles;
   SQLite (WAL) for storage; TA-Lib for indicators; scikit-learn for
   S/R clustering.
2. **AI analysis CLI** — `signal-trck ai analyze` — calls a configurable
   LLM provider (Anthropic, OpenAI, Moonshot/Kimi, DeepSeek) via
   [`instructor`](https://github.com/instructor-ai/instructor) to produce
   a grounded `chart-2.json`.
3. **`chart.json` schema** — the contract between UI, CLI, AI, and git.

## Phase A status

**Phase A is complete** as of commit `201ddc3`. Three sub-phases shipped
on `master` as fast-forward merges from feature branches:

| Commit    | Sub-phase | Title                                                           |
|-----------|-----------|-----------------------------------------------------------------|
| `9591ac2` | A.1       | Foundation + data layer                                         |
| `0c3a30b` | A.2       | Analytics layer — indicators, S/R levels, chart_schema          |
| `201ddc3` | A.3       | Provider-agnostic AI analysis CLI — Phase A done                |

By the numbers: **3,379 LOC** in `src/signal_trck/`, **2,086 LOC** in
`tests/`, **134 tests** passing, ruff clean.

## What each sub-phase delivered

### A.1 — Foundation + data layer

The skeleton: project structure, config loader, async SQLite store with
migrations, Coinbase adapter with rate limiting, Typer CLI scaffold. End
state was `signal-trck fetch coinbase:BTC-USD` populating a real
candles table.

Concrete deliverables:
- `pyproject.toml` (py311, ruff, console script `signal-trck`)
- Config (env + YAML, signalfetch idiom)
- aiosqlite `Store` class with WAL mode + per-version migrations
- `CandleAdapter` Protocol + Coinbase adapter + token-bucket rate limiter
- Commands: `pair add|list`, `fetch`, `dev seed|info`, `version`
- `pair_id` parser/validator (canonical `coinbase:BTC-USD` format)
- structlog with run-id correlation

### A.2 — Analytics layer

The numerical engines that produce the inputs the LLM reasons over.

- **TA-Lib indicator engine** under uniform `compute(name, params, closes)`
  — SMA, EMA, RSI, MACD, BB. Multi-output indicators (MACD, BB) flatten
  into per-key entries.
- **`params_hash`** locked spec:
  `sha256(json.dumps(p, sort_keys=True, separators=(",",":"))).hexdigest()[:16]`,
  with int-coercion of integer-valued floats so JSON round-trips don't
  bust the cache.
- **Read-through cache** in `INDICATOR_VALUES` rows (not JSON blobs;
  queryable by `ts_utc`, append-only).
- **Levels engine** — swing-highs/lows + agglomerative clustering on
  close proximity. Stable monotonic IDs (`sr-1, sr-2, …`) ranked by
  `strength = touches × recency_factor`. Top-N capped (default 50) so
  the LLM tool-use enum stays small.
- **`chart_schema`** — full Pydantic v2 models for `chart.json` v1 with
  cross-field validators (AI charts require `ai_run`; user charts can't
  have one; horizontal drawings need exactly 1 anchor; `extra="forbid"`).
- New CLI: `indicators sma|ema|rsi|macd|bb`, `levels`.

### A.3 — Provider-agnostic AI CLI (Phase A exit)

The differentiator. End-to-end: `chart-1.json` in, grounded `chart-2.json`
out. The LLM picks `candidate_id`s; the server resolves them to prices.

- **`src/signal_trck/llm/client.py`** — `LLMClient` Protocol + factory
  for Anthropic, OpenAI, Moonshot/Kimi, DeepSeek (instructor-backed,
  uniform `client.analyze(system, user, response_model) → T`).
- **`ChartAnalysis`** Pydantic schema — what the LLM returns
  (`analysis_text` + `drawings: list[AIDrawing]`, each anchor has
  `candidate_id` only).
- **`validate_grounding`** — post-Pydantic semantic check that every
  emitted `candidate_id` is in the presented set. The schema can't enforce
  this because the valid set is run-time-only.
- **`analyze_chart`** pipeline — retry-once on
  `ValidationError`/`GroundingError`; on second failure, dump prompt +
  error to `~/.signal-trck/failed/<timestamp>.json` and raise
  `PipelineError`.
- **`AI_RUN`** audit table (migration v3) — model, prompt template version,
  prompt hash, context SHA-256 + 500-char preview, full presented
  candidate set as JSON, selected IDs, ran_at.
- **`signal-trck ai analyze`** Typer command with `--input`, `--output`,
  `--context`, `--provider`, `--model`, `--dry-run`, `--yes`. Per-run
  disclosure: prints approximate tokens + `provider:model` before the
  call.

## Module map

```
src/signal_trck/
├── __init__.py            — package marker, __version__
├── paths.py               — XDG-style paths (~/.signal-trck/db.sqlite, /failed/)
├── pair_id.py             — parse/validate `coinbase:BTC-USD` form
├── log.py                 — structlog setup, run-id contextvars
├── config.py              — Settings (env) + AppConfig (env + YAML overlay)
├── chart_io.py            — read/write chart.json files (stable JSON formatting)
│
├── storage/               — async aiosqlite, single Store class, no SQL leakage
│   ├── models.py          — Pair, Candle dataclasses (storage-side, not Pydantic)
│   ├── schema.py          — MIGRATIONS list (indexed); v1 pairs+candles, v2
│   │                        indicator_values, v3 ai_runs
│   └── store.py           — Store(open|connect|close), all SQL strings live here
│
├── adapters/              — pluggable price-feed adapters (just Coinbase in v1)
│   ├── base.py            — CandleAdapter Protocol (no ABC)
│   ├── _rate_limit.py     — async TokenBucket
│   └── coinbase.py        — Advanced Trade public-market endpoint, paginated
│
├── indicators/            — TA-Lib wrappers + read-through DB cache
│   ├── engine.py          — compute(name, params, closes) — SMA/EMA/RSI/MACD/BB
│   ├── params.py          — params_hash locked spec
│   └── cache.py           — compute_or_load(): hit / miss → recompute → persist
│
├── levels/                — S/R candidate detection
│   ├── types.py           — Candidate dataclass (engine-side, frozen, slots)
│   └── swing_cluster.py   — swing detection + sklearn agglomerative clustering
│
├── chart_schema/          — Pydantic models for chart.json contract
│   └── models.py          — Chart, Provenance, Drawing, Anchor, Style, AIRun, …
│
├── llm/                   — provider-agnostic LLM wrapper
│   ├── client.py          — LLMClient Protocol + instructor-backed builders
│   ├── analysis.py        — ChartAnalysis schema + validate_grounding
│   ├── prompts.py         — versioned system + user prompt builders
│   └── pipeline.py        — analyze_chart() with retry + failure dump
│
└── cli/                   — Typer app
    ├── main.py            — root app, --log-level / --log-format options
    ├── pair.py            — pair add|list
    ├── fetch.py           — fetch <pair> [--interval --days]
    ├── dev.py             — dev seed|info
    ├── indicators.py      — indicators sma|ema|rsi|macd|bb
    ├── levels.py          — levels <pair>
    └── ai.py              — ai analyze
```

## Data flow

The pipeline from raw exchange data to a grounded AI-annotated chart.

```mermaid
flowchart LR
    subgraph Source
      CB[Coinbase Advanced Trade<br/>public market]
    end

    subgraph Backend[signal-trck — local]
      Adapter[adapters/coinbase.py<br/>+ TokenBucket]
      DB[(SQLite WAL<br/>candles · indicator_values<br/>· pairs · ai_runs)]
      IndCache[indicators/cache.py<br/>compute_or_load]
      Engine[indicators/engine.py<br/>TA-Lib]
      Levels[levels/swing_cluster.py<br/>+ sklearn]
    end

    subgraph CLI[signal-trck CLI]
      Fetch[fetch]
      Analyze[ai analyze]
    end

    subgraph LLM[provider via instructor]
      Anthropic[Anthropic]
      OpenAI[OpenAI]
      Moonshot[Moonshot/Kimi]
      DeepSeek[DeepSeek]
    end

    User[User] --> Fetch
    User --> Analyze
    User -.writes.-> ChartIn[chart-1.json on disk]

    CB -->|REST poll| Adapter
    Adapter -->|upsert_candles| DB

    Analyze -->|read_chart| ChartIn
    Analyze -->|get_candles<br/>compute_or_load<br/>detect_candidates| DB
    DB <--> IndCache
    IndCache --> Engine
    DB --> Levels

    Analyze -->|prompts.build_*<br/>+ instructor| LLM
    LLM -->|ChartAnalysis<br/>(candidate_id only)| Analyze
    Analyze -->|validate_grounding<br/>resolve candidate_id → price| ChartOut[chart-2.json on disk]
    Analyze -->|write_ai_run| DB
```

**Key invariant**: every numeric value the LLM reasons over is read from the
same DB rows the UI will read (Phase B), so UI and LLM see byte-identical
numbers. This is the *whole point* of caching indicators server-side
rather than recomputing on the frontend.

## Key design decisions

These are the load-bearing calls. Cross-references in `(parens)` point to
the relevant plan section if you want the long version.

### 1. `pair_id = "coinbase:BTC-USD"` — source-prefixed, URL-safe

(Plan: critical fix C1, post-review.) The slash in `BTC/USD` collides
with FastAPI path-segment parsing — would have been a Phase B disaster.
Source-namespaced (`{source}:{base}-{quote}`) is the MCP/k8s convention,
ASCII-only, shell-safe. Pretty form (`BTC/USD @ coinbase`) is for display
only — never used in URLs or filenames.

Touch points: `src/signal_trck/pair_id.py`, `paths.failed_dir()` filename
sanitization in `llm/pipeline.py:_dump_failure`.

### 2. LLM emits `candidate_id`, server resolves to price

(Plan: critical fix C2 + §"AI grounding strategy".) The earlier draft
typed prices as `Literal[float, …]` enums — fragile to JSON round-trip
and float-equality bugs. Now the LLM emits a candidate ID string, and
`pipeline.py:_resolve_anchor` looks up the price + `ts_utc` from the
candidate set on the server. The "no AI-drawn price outside the
candidate set" property test is true **by construction** — string-set
membership, not float equality. Tested across 9 hand-picked candle
fixtures in `tests/test_ai_pipeline.py`.

### 3. Indicator cache as parity-enforcement, not optimization

(Plan: §"Architectural decision: where price analytics are computed".)
TA-Lib computes SMA-50 in <1ms; we don't need a cache for speed. We do
need a guarantee that the UI and the LLM see byte-identical numbers, and
the simplest way to guarantee that is to store the bytes once and have
both readers slurp them. `INDICATOR_VALUES` rows (not JSON blobs) are
keyed by `(pair_id, interval, name, params_hash, ts_utc)`. Multi-output
indicators (MACD, BB) flatten into `MACD.macd`, `MACD.signal`, etc.

Touch points: `src/signal_trck/indicators/cache.py:compute_or_load`,
schema migration v2 in `storage/schema.py`.

### 4. Schema migrations as integer + ad-hoc scripts

(Plan: post-review cuts — schema migration framework was YAGNI.)
`MIGRATIONS` in `storage/schema.py` is a list-indexed-by-version. Add a
new entry to ship a v(N+1). The day a `chart.json` schema break ships,
write a one-shot script in `scripts/`. No migration framework, no `.bak`
siblings, no auto-upgrade. The simplest thing that survives.

### 5. Provider-agnostic LLM via `instructor`

(Plan: v2.1 amendments — LLM-provider-agnostic.) `LLMClient` is a
`Protocol` with one method: `analyze(system, user, response_model) → T`.
Two concrete impls: `_AnthropicClient` (uses `instructor.from_anthropic`,
`messages.create`) and `_OpenAICompatClient` (uses
`instructor.from_openai`, `chat.completions.create`). Moonshot and
DeepSeek go through the OpenAI client with a custom `base_url`. Adding
a new provider is one entry in `_OPENAI_COMPAT_BASE_URLS` if it's
OpenAI-compatible, or a new wrapper class if it isn't.

### 6. `INDICATOR_VALUES` rows, not JSON blobs

(Plan: post-review M2 fix.) Storing the SMA-50 series as a JSON blob
column makes range queries impossible without deserializing the whole
thing in Python. Rows give you `WHERE ts_utc BETWEEN ?` natively, and
the data is small (a few hundred rows per indicator at the v1 scale).

### 7. Drawings carry `Provenance` only when AI-created

(Plan: post-review minor.) On a user chart, every drawing is by the user
— stamping `created_by: "user"` on each is noise. Sparse provenance:
chart-level only on user charts, per-drawing on AI charts (since the AI's
rationale + confidence travels per line). Drives the
`Drawing.provenance: Provenance | None` shape in `chart_schema/models.py`.

### 8. No FastAPI / web UI yet

The plan's data-flow diagram includes FastAPI endpoints
(`/indicators/sma`, `/sr-candidates`, etc.) intended for Phase B. **None
of these are implemented in Phase A** — the CLI calls the Python engines
directly via `compute_or_load` and `detect_candidates`. Phase B will add
the FastAPI layer as a thin wrapper over the same functions; the LLM
already reads from those functions, so the FastAPI surface is purely a
Phase B / web-UI concern.

## File reference index — "where do I look for X?"

| If you want to…                                  | Look at                                                  |
|--------------------------------------------------|----------------------------------------------------------|
| Change pair-id format                            | `src/signal_trck/pair_id.py`                             |
| Add a new indicator                              | `src/signal_trck/indicators/engine.py:_SPECS`            |
| Add a new exchange                               | `src/signal_trck/adapters/__init__.py:build_adapter`     |
| Change the S/R algorithm                         | `src/signal_trck/levels/swing_cluster.py`                |
| Add an LLM provider                              | `src/signal_trck/llm/client.py:_OPENAI_COMPAT_BASE_URLS` |
| Tune the AI system prompt                        | `src/signal_trck/llm/prompts.py:_SYSTEM_TEMPLATE`        |
| Bump the prompt template version                 | `src/signal_trck/llm/prompts.py:PROMPT_TEMPLATE_VERSION` |
| Add a DB column                                  | `src/signal_trck/storage/schema.py:MIGRATIONS` (append)  |
| Change `chart.json` shape                        | `src/signal_trck/chart_schema/models.py` + bump `SCHEMA_VERSION` |
| Persist a new audit field                        | `storage/schema.py:MIGRATIONS` v3 + `Store.write_ai_run` |
| Find what the LLM was sent                       | `~/.signal-trck/failed/<ts>.json` on failure; `ai_runs.context_preview` on success |
| Inspect the cache for a pair                     | `sqlite3 ~/.signal-trck/db.sqlite "SELECT * FROM indicator_values"` |

## Phase B integration points

When the web UI lands, these are the seams it will plug into. The Phase A
code was structured with these integration points in mind — they're
already accessible Python functions, just not yet exposed over HTTP.

| Phase B need                                  | Phase A function to wrap                                                  |
|-----------------------------------------------|---------------------------------------------------------------------------|
| `GET /pairs`                                  | `Store.list_pairs`                                                         |
| `POST /pairs`                                 | `Store.add_pair` + `pair_id.parse`                                         |
| `GET /pairs/{id}/candles`                     | `Store.get_candles`                                                        |
| `GET /pairs/{id}/indicators/{name}`           | `indicators.cache.compute_or_load`                                         |
| `GET /pairs/{id}/sr-candidates`               | `levels.detect_candidates` (stateless, takes `list[Candle]`)               |
| `POST /charts` (save user chart from UI)      | `chart_io.write_chart` (file-based v1) — DB-backed in v2 (new `charts` table) |
| `GET /charts/{slug}`                          | `chart_io.read_chart` — DB-backed in v2                                    |
| `GET /pairs/{id}/ai_runs`                     | `Store.list_ai_runs` (already exists — used by the rationale/trace panel)  |

The `charts` and `drawings` tables are deferred to Phase B — Phase A only
needs `ai_runs` for audit. When Phase B persists charts in DB, the
existing `chart_io` file functions become export/import helpers rather
than the storage layer.

## Out of v1 scope (parking lot)

Tracked in the plan; not in the code yet:

- MCP server facade (was Phase 7, demoted to "future" — wraps the same
  Python functions when ready)
- Pivot points + volume profile S/R methods (the `method` field on
  `Candidate` is reserved for them)
- Trend-line candidate engine (separate from swing-cluster)
- Backtesting (would consume `ai_runs` history)
- Pair aliasing (e.g. tracking `BTC` through an exchange rebrand)
- Obsidian sink (Phase D — reuse from `signalfetch`)
- CoinGecko adapter (Phase D fallback for alts not on Coinbase)

## Conventions to keep using

These are the patterns Phase A established that Phase B should match.

- **Storage**: `Store` class hides all SQL strings. No `await
  db.execute("SELECT ...")` outside `storage/store.py`.
- **Migrations**: append to `MIGRATIONS` list. Don't edit existing
  entries. Version is the index + 1.
- **Tests**: per-test isolation via `SIGNAL_TRCK_HOME=tmp_path`
  (`tests/conftest.py`). HTTP mocked via `httpx.MockTransport`, not real
  network.
- **Naming**: pair IDs are `{source}:{base}-{quote}`, lowercase source,
  uppercase symbols. Slugs are kebab-case (`chart-1`, `chart-2`).
  Candidate IDs are `sr-N` monotonic.
- **Validation**: Pydantic models use `extra="forbid"` so typos surface
  at parse time. Round-trip JSON on every model addition is the contract
  test.
- **Provenance**: sparse on user objects, full on AI objects. AI
  drawings carry `confidence` + `rationale` per line.
- **CLI**: each subcommand module exposes a `Typer` app or a top-level
  function; `cli/main.py` wires them together. `--log-level` and
  `--log-format` are root flags so any command can emit JSON logs.

## Reference

- Plan: [`plans/feat-crypto-charting-ai-analysis.md`](../plans/feat-crypto-charting-ai-analysis.md) — full design, alternatives considered, plan v2.1 with reviewer feedback applied
- README: [`README.md`](../README.md) — quick-start
- Sibling repos referenced for patterns:
  - `signalfetch` — config loader idiom, async SQLite store template, Anthropic client factory
  - `leads-ai` — Pydantic structured-response pattern (less directly used in v1)
