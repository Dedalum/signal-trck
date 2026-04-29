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

**Phase A complete.** Web UI follows in Phase B. Currently shipped:

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
- structlog with `--log-format json` mode

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
```

The DB lives at `~/.signal-trck/db.sqlite` by default
(override with `SIGNAL_TRCK_HOME=/path`).

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
- **Phase B** — Web UI: Vite + TS + Lightweight Charts v5 + drawing tools.
- **Phase C** — AI artifacts in the UI.
- **Phase D** — Markdown context + Obsidian sink + polish.

See the plan for details and the rationale behind each decision.
