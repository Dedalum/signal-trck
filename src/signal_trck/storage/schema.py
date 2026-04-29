"""DDL for signal-trck SQLite schema.

Phase A.1 covers ``pairs`` and ``candles``. Indicators, charts, drawings,
and ai_runs are added in Phase A.2 / B.

Schema version is tracked in ``schema_version`` table. On startup the Store
applies any missing migrations in order.
"""

from __future__ import annotations

# Each migration is a list of SQL statements applied in a transaction.
# Adding a new schema version: append a new entry to MIGRATIONS; the migration
# id is the list index + 1.
MIGRATIONS: list[list[str]] = [
    # v1 — pairs + candles
    [
        """
        CREATE TABLE IF NOT EXISTS pairs (
            pair_id TEXT PRIMARY KEY,
            base TEXT NOT NULL,
            quote TEXT NOT NULL,
            source TEXT NOT NULL,
            added_at INTEGER NOT NULL,
            last_viewed_at INTEGER,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            pinned_context_path TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS candles (
            pair_id TEXT NOT NULL,
            interval TEXT NOT NULL,
            ts_utc INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (pair_id, interval, ts_utc),
            FOREIGN KEY (pair_id) REFERENCES pairs(pair_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_candles_pair_interval_ts_desc
        ON candles(pair_id, interval, ts_utc DESC)
        """,
    ],
    # v2 — indicator_values cache (rows, not blobs — see plan §"Architectural decision")
    [
        """
        CREATE TABLE IF NOT EXISTS indicator_values (
            pair_id TEXT NOT NULL,
            interval TEXT NOT NULL,
            name TEXT NOT NULL,
            params_hash TEXT NOT NULL,
            ts_utc INTEGER NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY (pair_id, interval, name, params_hash, ts_utc),
            FOREIGN KEY (pair_id) REFERENCES pairs(pair_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_indicator_values_lookup
        ON indicator_values(pair_id, interval, name, params_hash, ts_utc DESC)
        """,
    ],
    # v3 — ai_runs audit (one row per `signal-trck ai analyze` invocation)
    [
        """
        CREATE TABLE IF NOT EXISTS ai_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id TEXT NOT NULL,
            chart_slug TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            prompt_template_version TEXT NOT NULL,
            system_prompt_hash TEXT NOT NULL,
            context_file_sha256 TEXT,
            context_preview TEXT,
            sr_candidates_presented TEXT NOT NULL,
            sr_candidates_selected TEXT NOT NULL,
            ran_at INTEGER NOT NULL,
            FOREIGN KEY (pair_id) REFERENCES pairs(pair_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_ai_runs_pair_chart_ran
        ON ai_runs(pair_id, chart_slug, ran_at DESC)
        """,
    ],
]


SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
)
"""
