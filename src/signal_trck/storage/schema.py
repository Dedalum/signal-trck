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
    # v4 — Phase B: charts + drawings + indicator_refs + indicator_values index
    # reorder.
    #
    # The index reorder (Performance M1 from todos/010) matches the actual query
    # pattern: `WHERE pair_id=? AND interval=? AND params_hash=? AND name IN (...)`.
    # Putting params_hash before name lets the planner use the index even when
    # the IN-list expands. Bundled here per Decision 12 to avoid a v3.5 just for
    # an index swap.
    [
        # charts: one row per saved chart, slug-keyed.
        """
        CREATE TABLE IF NOT EXISTS charts (
            slug TEXT PRIMARY KEY,
            pair_id TEXT NOT NULL,
            title TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            default_window_days INTEGER NOT NULL,
            default_interval TEXT NOT NULL,
            parent_chart_slug TEXT,
            analysis_text TEXT,
            ai_run_id INTEGER,
            prov_kind TEXT NOT NULL,
            prov_model TEXT,
            prov_prompt_template_version TEXT,
            prov_created_at TEXT NOT NULL,
            created_at_unix INTEGER NOT NULL,
            updated_at_unix INTEGER NOT NULL,
            FOREIGN KEY (pair_id) REFERENCES pairs(pair_id) ON DELETE CASCADE,
            FOREIGN KEY (ai_run_id) REFERENCES ai_runs(run_id) ON DELETE SET NULL,
            CHECK (prov_kind IN ('user', 'ai'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_charts_pair_updated
        ON charts(pair_id, updated_at_unix DESC)
        """,
        # drawings: per-chart, JSON anchors + JSON style.
        # Composite PK (chart_slug, drawing_id) — drawing IDs are scoped to
        # the chart they live on, so a chart import never collides with
        # an already-imported chart's drawing IDs.
        """
        CREATE TABLE IF NOT EXISTS drawings (
            chart_slug TEXT NOT NULL,
            drawing_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            anchors_json TEXT NOT NULL,
            style_json TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            prov_kind TEXT,
            prov_model TEXT,
            prov_created_at TEXT,
            prov_confidence REAL,
            prov_rationale TEXT,
            PRIMARY KEY (chart_slug, drawing_id),
            FOREIGN KEY (chart_slug) REFERENCES charts(slug) ON DELETE CASCADE,
            CHECK (kind IN ('trend', 'horizontal', 'rect', 'fib')),
            CHECK (prov_kind IS NULL OR prov_kind IN ('user', 'ai'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_drawings_chart_order
        ON drawings(chart_slug, order_index ASC)
        """,
        # indicator_refs: which indicators a chart shows + on which pane.
        """
        CREATE TABLE IF NOT EXISTS indicator_refs (
            chart_slug TEXT NOT NULL,
            indicator_id TEXT NOT NULL,
            name TEXT NOT NULL,
            params_json TEXT NOT NULL,
            pane INTEGER NOT NULL,
            PRIMARY KEY (chart_slug, indicator_id),
            FOREIGN KEY (chart_slug) REFERENCES charts(slug) ON DELETE CASCADE
        )
        """,
        # Slug allocator: auto-incrementing per-pair slug counter.
        """
        CREATE TABLE IF NOT EXISTS chart_slug_seq (
            pair_id TEXT PRIMARY KEY,
            next_n INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (pair_id) REFERENCES pairs(pair_id) ON DELETE CASCADE
        )
        """,
        # Indicator values index reorder: drop the old, create the new.
        # Old: (pair_id, interval, name, params_hash, ts_utc DESC)
        # New: (pair_id, interval, params_hash, name, ts_utc DESC)
        "DROP INDEX IF EXISTS idx_indicator_values_lookup",
        """
        CREATE INDEX IF NOT EXISTS idx_indicator_values_lookup
        ON indicator_values(pair_id, interval, params_hash, name, ts_utc DESC)
        """,
    ],
]


SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
)
"""
