# signal-trck

Personal crypto charting + LLM-grounded technical analysis.

A local-first tool for longer-term TA on crypto pairs (BTC, ETH, SOL, alts):
candlestick charts with manual drawing tools, computed indicators, and a CLI
that produces grounded AI analyses as diffable JSON artifacts.

The differentiator: every chart — user-made or AI-made — is a versioned
`chart.json` file you can commit to git. The AI is grounded against
pre-computed support/resistance candidates and selects levels by ID, never
inventing prices.

See [`plans/feat-crypto-charting-ai-analysis.md`](plans/feat-crypto-charting-ai-analysis.md)
for the full design.

## Status

**Phases A + B complete.** Phase C (AI rationale UI) follows. Currently shipped:

**Phase A (data + analytics + AI CLI):**
- Coinbase Advanced Trade public-market adapter (no auth required)
- SQLite storage with WAL, source-namespaced canonical pair IDs
- Token-bucket rate limiting per adapter
- TA-Lib indicator engine (SMA / EMA / RSI / MACD / BB) with row-cache for
  byte-identical UI ↔ LLM numeric parity
- Swing-cluster S/R candidate engine with stable IDs and strength ranking
- Full Pydantic chart.json schema (v1) with round-trip JSON
- Provider-agnostic LLM wrapper via `instructor` — Anthropic, OpenAI,
  Moonshot/Kimi, DeepSeek
- `signal-trck ai analyze` — grounded LLM analysis of a user-authored chart;
  the LLM picks `candidate_id`s from a typed list, server resolves to price
- AI run audit table for replay/diagnosis
- CLI: `pair add|list`, `fetch`, `indicators sma|ema|rsi|macd|bb`, `levels`,
  `ai analyze`, `dev seed|info`
- structlog with `--log-format json` mode + API-key redaction processor

**Phase B (web UI + FastAPI):**
- FastAPI surface (3 files: `app.py` + `routes.py` + `errors.py`) with
  14 routes — pairs, candles, indicators, S/R candidates, charts CRUD,
  refresh, AI run audit (read-only)
- `signal-trck serve` command — uvicorn boot, hardcoded `127.0.0.1` bind
- DB migration v4: `charts`, `drawings`, `indicator_refs` tables +
  `indicator_values` index reorder
- `Store.create_chart` / `update_chart` / `get_chart` / `list_charts` /
  `delete_chart` / `next_slug` / `remove_pair`
- `chart.json` round-trip through the DB (full Pydantic equivalence)
- Vite + React 18 + zustand + Lightweight Charts v5 frontend
- Two-column layout: pair list + chart canvas with toolbar
- Indicator overlays + sub-panes; Save / Save As / Export / Import
- Drawing layer: trend lines, horizontal S/R lines, rectangles
  (custom-on-`ISeriesPrimitive` since the difurious plugin isn't on npm)
- Phase C scaffolding: dashed stroke for AI provenance,
  `onDrawingClick(drawing)` event surface
- `mypy --strict` gate on `api/`; `tsconfig` strict + extras
- API-key sentinel test pinning the no-key-on-the-wire invariant

## Quick start

```bash
# install in a venv
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# track a pair and fetch a year of daily candles
signal-trck pair add coinbase:BTC-USD --pin
signal-trck fetch coinbase:BTC-USD              # 1y daily by default
signal-trck fetch coinbase:BTC-USD -i 1h -d 30  # 30d hourly on demand
signal-trck pair list

# inspect what's in the DB
signal-trck dev info

# launch the web UI (requires the frontend built once — see below)
signal-trck serve            # binds 127.0.0.1:8000
```

The DB lives at `~/.signal-trck/db.sqlite` by default
(override with `SIGNAL_TRCK_HOME=/path`).

## Web UI

```bash
# one-time: install frontend deps + generate API types from FastAPI
cd web
npm install
npm run gen-types        # reads ../web/openapi.json — regenerate after backend changes

# dev mode (hot reload):
# Terminal 1:
SIGNAL_TRCK_DEV=1 signal-trck serve --reload      # FastAPI on :8000 with CORS for :5173
# Terminal 2:
cd web && npm run dev                              # Vite dev server on :5173

# prod-ish single-command:
cd web && npm run build                            # builds web/dist/
signal-trck serve                                  # FastAPI on :8000 (no CORS)
```

To regenerate `openapi.json` after backend changes:

```bash
.venv/bin/python -c "import json; from signal_trck.api import app; print(json.dumps(app.openapi(), indent=2))" > web/openapi.json
cd web && npm run gen-types
```

## Pair IDs

Pairs are addressed by canonical, source-namespaced IDs:

```
{source}:{base}-{quote}     coinbase:BTC-USD     binance:DOGE-USDT (Phase D)
```

URL-safe and shell-safe by construction. The pretty form (`BTC/USD @ coinbase`)
is for display only.

## Development

```bash
ruff check .
ruff format .
pytest -v
```

Tests are isolated per-test via `SIGNAL_TRCK_HOME` pointing at a tmp dir, and
HTTP is mocked with `httpx.MockTransport`. No network access needed.

## Configuration

Optional `.env` for LLM provider keys (used in Phase A.3, not yet):

```
LLM_PROVIDER=anthropic       # anthropic | openai | moonshot | deepseek
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=...
# MOONSHOT_API_KEY=...
# DEEPSEEK_API_KEY=...
```

See [`.env.example`](.env.example).

## Running an AI analysis

Hand-write a chart-1.json (or use a future Phase B export) describing your
view of a tracked pair, then:

```bash
export LLM_PROVIDER=moonshot          # or anthropic | openai | deepseek
export MOONSHOT_API_KEY=sk-...

signal-trck ai analyze \
  --input chart-1.json \
  --output chart-2.json \
  --context thesis.md      # optional markdown of qualitative context
```

The CLI prints an approximate-token + cost disclosure and asks for
confirmation before the LLM call. `--dry-run` prints what would be sent
without calling the LLM or writing files. `--provider` and `--model`
override the env defaults per run.

## Roadmap

- **Phase A.1** — Data layer + adapters + CLI scaffolding. ✅
- **Phase A.2** — Indicators (TA-Lib) + S/R candidate engine + chart_schema. ✅
- **Phase A.3** — `signal-trck ai analyze` with `instructor` (provider-agnostic). ✅
- **Phase B.1** — FastAPI backend + Vite/React frontend + chart persistence. ✅
- **Phase B.2** — Drawing layer (trend / horizontal / rectangle). ✅
- **Phase C** — AI artifacts in the UI: rationale + trace panels, "Run AI
  analysis" copy-CLI modal, third column.
- **Phase D** — Markdown context + Obsidian sink + scheduler + polish.

See the plans for details and the rationale behind each decision.
