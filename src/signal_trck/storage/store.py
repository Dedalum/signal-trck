"""Async SQLite store. Owns all SQL strings; callers see Python types only.

Connect with ``async with Store.open() as store:`` for short scripts, or
manage lifecycle explicitly with ``store = Store(); await store.connect();
... await store.close()`` for long-running processes.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import aiosqlite
import structlog

from signal_trck import paths
from signal_trck.chart_schema import (
    AIRun,
    Anchor,
    Chart,
    Drawing,
    Indicator,
    Provenance,
    SRCandidate,
    Style,
)
from signal_trck.storage.models import AIRunRow, Candle, ChartListItem, Pair
from signal_trck.storage.schema import MIGRATIONS, SCHEMA_VERSION_DDL

log = structlog.get_logger(__name__)


# --- Exceptions ---


class StoreError(Exception):
    """Base for storage-layer errors that map to specific HTTP statuses."""


class PairNotFound(StoreError):  # noqa: N818 — REST-style name; "Error" suffix would read awkward at call sites
    """A pair_id was referenced that doesn't exist."""

    def __init__(self, pair_id: str) -> None:
        self.pair_id = pair_id
        super().__init__(f"pair {pair_id!r} not found")


class ChartNotFound(StoreError):  # noqa: N818 — see PairNotFound
    """A chart slug was referenced that doesn't exist."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"chart {slug!r} not found")


class ChartSlugConflict(StoreError):  # noqa: N818 — see PairNotFound
    """Attempted to create a chart whose slug is already in use."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"chart slug {slug!r} already exists")


class Store:
    """Async SQLite store with WAL mode and per-version migrations."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else paths.db_path()
        self._db: aiosqlite.Connection | None = None

    @classmethod
    @asynccontextmanager
    async def open(cls, db_path: str | Path | None = None) -> AsyncIterator[Store]:
        store = cls(db_path)
        await store.connect()
        try:
            yield store
        finally:
            await store.close()

    async def connect(self) -> None:
        paths.ensure_data_dir()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._migrate()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not connected; call .connect() first")
        return self._db

    async def _migrate(self) -> None:
        await self.conn.execute(SCHEMA_VERSION_DDL)
        await self.conn.commit()
        cur = await self.conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cur.fetchone()
        current = row[0] if row and row[0] is not None else 0
        target = len(MIGRATIONS)
        if current >= target:
            return
        log.info("storage.migrate", from_version=current, to_version=target)
        for v in range(current + 1, target + 1):
            for stmt in MIGRATIONS[v - 1]:
                await self.conn.execute(stmt)
            await self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
            await self.conn.commit()

    # ---- pairs ----

    async def add_pair(
        self,
        pair_id: str,
        base: str,
        quote: str,
        source: str,
        *,
        is_pinned: bool = False,
    ) -> None:
        now = int(time.time())
        await self.conn.execute(
            """
            INSERT INTO pairs (pair_id, base, quote, source, added_at, is_pinned)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pair_id) DO NOTHING
            """,
            (pair_id, base, quote, source, now, 1 if is_pinned else 0),
        )
        await self.conn.commit()

    async def list_pairs(self) -> list[Pair]:
        cur = await self.conn.execute(
            """
            SELECT pair_id, base, quote, source, added_at, last_viewed_at,
                   is_pinned, pinned_context_path
            FROM pairs
            ORDER BY is_pinned DESC, added_at ASC
            """
        )
        rows = await cur.fetchall()
        return [
            Pair(
                pair_id=r[0],
                base=r[1],
                quote=r[2],
                source=r[3],
                added_at=r[4],
                last_viewed_at=r[5],
                is_pinned=bool(r[6]),
                pinned_context_path=r[7],
            )
            for r in rows
        ]

    async def get_pair(self, pair_id: str) -> Pair | None:
        cur = await self.conn.execute(
            """
            SELECT pair_id, base, quote, source, added_at, last_viewed_at,
                   is_pinned, pinned_context_path
            FROM pairs WHERE pair_id = ?
            """,
            (pair_id,),
        )
        r = await cur.fetchone()
        if r is None:
            return None
        return Pair(
            pair_id=r[0],
            base=r[1],
            quote=r[2],
            source=r[3],
            added_at=r[4],
            last_viewed_at=r[5],
            is_pinned=bool(r[6]),
            pinned_context_path=r[7],
        )

    async def pin_pair(self, pair_id: str, pinned: bool = True) -> None:
        await self.conn.execute(
            "UPDATE pairs SET is_pinned = ? WHERE pair_id = ?",
            (1 if pinned else 0, pair_id),
        )
        await self.conn.commit()

    async def set_pinned_context(self, pair_id: str, path: str | None) -> None:
        await self.conn.execute(
            "UPDATE pairs SET pinned_context_path = ? WHERE pair_id = ?",
            (path, pair_id),
        )
        await self.conn.commit()

    # ---- candles ----

    async def upsert_candles(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        await self.conn.executemany(
            """
            INSERT INTO candles
                (pair_id, interval, ts_utc, open, high, low, close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pair_id, interval, ts_utc) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                source = excluded.source
            """,
            [
                (
                    c.pair_id,
                    c.interval,
                    c.ts_utc,
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.volume,
                    c.source,
                )
                for c in candles
            ],
        )
        await self.conn.commit()
        return len(candles)

    async def get_candles(
        self,
        pair_id: str,
        interval: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        sql = (
            "SELECT pair_id, interval, ts_utc, open, high, low, close, volume, source "
            "FROM candles WHERE pair_id = ? AND interval = ?"
        )
        params: list = [pair_id, interval]
        if start_ts is not None:
            sql += " AND ts_utc >= ?"
            params.append(start_ts)
        if end_ts is not None:
            sql += " AND ts_utc <= ?"
            params.append(end_ts)
        sql += " ORDER BY ts_utc ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        return [
            Candle(
                pair_id=r[0],
                interval=r[1],
                ts_utc=r[2],
                open=r[3],
                high=r[4],
                low=r[5],
                close=r[6],
                volume=r[7],
                source=r[8],
            )
            for r in rows
        ]

    async def candle_count(self, pair_id: str, interval: str) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM candles WHERE pair_id = ? AND interval = ?",
            (pair_id, interval),
        )
        r = await cur.fetchone()
        return int(r[0]) if r else 0

    async def latest_candle_ts(self, pair_id: str, interval: str) -> int | None:
        cur = await self.conn.execute(
            "SELECT MAX(ts_utc) FROM candles WHERE pair_id = ? AND interval = ?",
            (pair_id, interval),
        )
        r = await cur.fetchone()
        return r[0] if r and r[0] is not None else None

    # ---- indicator_values cache ----

    async def get_indicator_rows(
        self,
        pair_id: str,
        interval: str,
        names: list[str],
        params_hash: str,
    ) -> dict[str, list[tuple[int, float]]]:
        """Fetch indicator rows grouped by cache name (e.g. ``"SMA"``,
        ``"MACD.macd"``).

        Returns a dict with one entry per name in ``names``. Names with no
        cached rows yield an empty list. Within each list, entries are
        ascending by ``ts_utc``.
        """
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        sql = (
            "SELECT name, ts_utc, value FROM indicator_values "
            f"WHERE pair_id = ? AND interval = ? AND params_hash = ? "
            f"AND name IN ({placeholders}) "
            "ORDER BY name, ts_utc ASC"
        )
        args = [pair_id, interval, params_hash, *names]
        cur = await self.conn.execute(sql, args)
        rows = await cur.fetchall()
        out: dict[str, list[tuple[int, float]]] = {n: [] for n in names}
        for name, ts, value in rows:
            out.setdefault(name, []).append((int(ts), float(value)))
        return out

    async def replace_indicator_rows(
        self,
        pair_id: str,
        interval: str,
        names: list[str],
        params_hash: str,
        rows: list[tuple[str, str, str, str, int, float]],
    ) -> None:
        """Atomically replace cached indicator rows for the given ``names``.

        Each row is ``(pair_id, interval, name, params_hash, ts_utc, value)``.
        Delete + insert run in a single transaction so a crash mid-way leaves
        the cache in its previous state, not partially populated.
        """
        if not names:
            return
        placeholders = ",".join("?" for _ in names)
        await self.conn.execute(
            f"""
            DELETE FROM indicator_values
            WHERE pair_id = ? AND interval = ? AND params_hash = ?
              AND name IN ({placeholders})
            """,
            [pair_id, interval, params_hash, *names],
        )
        if rows:
            await self.conn.executemany(
                """
                INSERT INTO indicator_values
                    (pair_id, interval, name, params_hash, ts_utc, value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        await self.conn.commit()

    # ---- ai_runs ----

    async def write_ai_run(
        self,
        *,
        pair_id: str,
        chart_slug: str,
        provider: str,
        model: str,
        prompt_template_version: str,
        system_prompt_hash: str,
        context_file_sha256: str | None,
        context_preview: str | None,
        sr_candidates_presented_json: str,
        sr_candidates_selected_json: str,
        ran_at: int,
    ) -> int:
        """Persist a single ``ai_runs`` row. Returns the new ``run_id``."""
        cur = await self.conn.execute(
            """
            INSERT INTO ai_runs (
                pair_id, chart_slug, model, provider,
                prompt_template_version, system_prompt_hash,
                context_file_sha256, context_preview,
                sr_candidates_presented, sr_candidates_selected, ran_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pair_id,
                chart_slug,
                model,
                provider,
                prompt_template_version,
                system_prompt_hash,
                context_file_sha256,
                context_preview,
                sr_candidates_presented_json,
                sr_candidates_selected_json,
                ran_at,
            ),
        )
        await self.conn.commit()
        return int(cur.lastrowid or 0)

    async def list_ai_runs(self, pair_id: str, *, limit: int | None = None) -> list[AIRunRow]:
        """Return AI run audit rows for a pair, newest first.

        JSON columns are parsed at the boundary; callers receive typed
        Python lists, not raw JSON strings.
        """
        sql = (
            "SELECT run_id, pair_id, chart_slug, model, provider, "
            "prompt_template_version, system_prompt_hash, "
            "context_file_sha256, context_preview, "
            "sr_candidates_presented, sr_candidates_selected, ran_at "
            "FROM ai_runs WHERE pair_id = ? ORDER BY ran_at DESC"
        )
        params: list = [pair_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        return [
            AIRunRow(
                run_id=int(r[0]),
                pair_id=r[1],
                chart_slug=r[2],
                model=r[3],
                provider=r[4],
                prompt_template_version=r[5],
                system_prompt_hash=r[6],
                context_file_sha256=r[7],
                context_preview=r[8],
                sr_candidates_presented=json.loads(r[9]),
                sr_candidates_selected=json.loads(r[10]),
                ran_at=int(r[11]),
            )
            for r in rows
        ]

    async def remove_pair(self, pair_id: str) -> None:
        """Delete a pair. Cascades via FK to candles, indicator_values,
        ai_runs, charts (and through them, drawings + indicator_refs).
        Idempotent: deleting a missing pair is a no-op (no exception)."""
        await self.conn.execute("DELETE FROM pairs WHERE pair_id = ?", (pair_id,))
        await self.conn.commit()

    # ---- chart slug allocator ----

    async def next_slug(self, pair_id: str) -> str:
        """Allocate the next available slug for ``pair_id``.

        Uses a per-pair counter row (``chart_slug_seq``) updated atomically
        in a single SQL roundtrip. Slugs are monotonic; gaps are OK (a slug
        allocated then unused is fine — git is the version history).

        Returns ``"chart-{n}"`` where n is 1-based.
        """
        if await self.get_pair(pair_id) is None:
            raise PairNotFound(pair_id)
        # Insert-or-bump in one transaction. RETURNING gets us the value
        # of next_n *after* the increment, so the slug we hand out is the
        # value before the bump.
        await self.conn.execute(
            """
            INSERT INTO chart_slug_seq (pair_id, next_n) VALUES (?, 2)
            ON CONFLICT(pair_id) DO UPDATE SET next_n = next_n + 1
            """,
            (pair_id,),
        )
        cur = await self.conn.execute(
            "SELECT next_n FROM chart_slug_seq WHERE pair_id = ?", (pair_id,)
        )
        row = await cur.fetchone()
        await self.conn.commit()
        if row is None:
            raise RuntimeError("chart_slug_seq row missing after upsert")
        # next_n is the *next* counter — the value we just allocated is one less.
        n = int(row[0]) - 1
        return f"chart-{n}"

    # ---- charts / drawings / indicator_refs ----

    async def create_chart(self, chart: Chart) -> None:
        """Persist a new chart with its drawings + indicator refs.

        Raises ``ChartSlugConflict`` if the slug is already in use.
        Raises ``PairNotFound`` if ``chart.pair`` doesn't exist.
        """
        if await self.get_pair(chart.pair) is None:
            raise PairNotFound(chart.pair)
        existing = await self.conn.execute(
            "SELECT 1 FROM charts WHERE slug = ?", (chart.slug,)
        )
        if await existing.fetchone() is not None:
            raise ChartSlugConflict(chart.slug)
        await self._insert_chart_rows(chart)

    async def update_chart(self, chart: Chart) -> None:
        """Replace an existing chart's row + drawings + indicator refs.

        Raises ``ChartNotFound`` if the slug doesn't exist.
        """
        existing = await self.conn.execute(
            "SELECT 1 FROM charts WHERE slug = ?", (chart.slug,)
        )
        if await existing.fetchone() is None:
            raise ChartNotFound(chart.slug)
        # Delete + re-insert is simpler than per-row diff for v1; the
        # drawings/indicator_refs sets are small (< 50 typical).
        await self.conn.execute("DELETE FROM drawings WHERE chart_slug = ?", (chart.slug,))
        await self.conn.execute(
            "DELETE FROM indicator_refs WHERE chart_slug = ?", (chart.slug,)
        )
        await self.conn.execute("DELETE FROM charts WHERE slug = ?", (chart.slug,))
        await self._insert_chart_rows(chart)

    async def _insert_chart_rows(self, chart: Chart) -> None:
        """Insert charts + drawings + indicator_refs for ``chart``.

        Caller is responsible for prior cleanup (or for asserting absence).
        Commit happens once at the end so the three inserts share a
        transaction.
        """
        now = int(time.time())
        ai_run = chart.ai_run
        # Persist a placeholder ai_run_id only if the chart already has one
        # via prior mechanism; for now charts created from CLI/UI don't
        # carry an ai_run_id reference (they're either fresh user charts or
        # imported AI charts where the AI run was on a different machine).
        # This stays NULL until Phase C wires through.
        ai_run_id: int | None = None
        prov = chart.provenance
        await self.conn.execute(
            """
            INSERT INTO charts (
                slug, pair_id, title,
                schema_version, default_window_days, default_interval,
                parent_chart_slug, analysis_text, ai_run_id,
                prov_kind, prov_model, prov_prompt_template_version, prov_created_at,
                created_at_unix, updated_at_unix
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chart.slug,
                chart.pair,
                chart.title,
                chart.schema_version,
                chart.data.default_window_days,
                chart.data.default_interval,
                chart.parent_chart_id,
                chart.view.analysis_text,
                ai_run_id,
                prov.kind,
                prov.model,
                prov.prompt_template_version,
                prov.created_at.isoformat(),
                now,
                now,
            ),
        )
        if chart.view.indicators:
            await self.conn.executemany(
                """
                INSERT INTO indicator_refs
                    (chart_slug, indicator_id, name, params_json, pane)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (chart.slug, ind.id, ind.name, json.dumps(ind.params, sort_keys=True), ind.pane)
                    for ind in chart.view.indicators
                ],
            )
        if chart.view.drawings:
            await self.conn.executemany(
                """
                INSERT INTO drawings (
                    drawing_id, chart_slug, kind,
                    anchors_json, style_json, order_index,
                    prov_kind, prov_model, prov_created_at,
                    prov_confidence, prov_rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        d.id,
                        chart.slug,
                        d.kind,
                        json.dumps(
                            [a.model_dump(mode="json") for a in d.anchors],
                            sort_keys=False,
                        ),
                        json.dumps(d.style.model_dump(mode="json"), sort_keys=False),
                        idx,
                        d.provenance.kind if d.provenance else None,
                        d.provenance.model if d.provenance else None,
                        d.provenance.created_at.isoformat() if d.provenance else None,
                        d.provenance.confidence if d.provenance else None,
                        d.provenance.rationale if d.provenance else None,
                    )
                    for idx, d in enumerate(chart.view.drawings)
                ],
            )
        # ai_run_data: if the chart carries an embedded AIRun payload, we
        # could persist it to the ai_runs table here. Current decision: AI
        # runs come from the `signal-trck ai analyze` CLI which writes to
        # ai_runs directly; importing an AI chart from disk does NOT
        # re-create an ai_runs row (the data already lives on the
        # originating machine). The chart's `ai_run` field stays in the
        # exported JSON for portability but isn't shadow-persisted.
        _ = ai_run  # explicit no-op — see comment above
        await self.conn.commit()

    async def get_chart(self, slug: str) -> Chart:
        """Load a complete ``Chart`` (with drawings + indicator refs).

        Raises ``ChartNotFound`` if the slug doesn't exist.
        """
        cur = await self.conn.execute(
            """
            SELECT slug, pair_id, title, schema_version,
                   default_window_days, default_interval,
                   parent_chart_slug, analysis_text, ai_run_id,
                   prov_kind, prov_model, prov_prompt_template_version, prov_created_at
            FROM charts WHERE slug = ?
            """,
            (slug,),
        )
        row = await cur.fetchone()
        if row is None:
            raise ChartNotFound(slug)
        # Indicators
        ind_cur = await self.conn.execute(
            "SELECT indicator_id, name, params_json, pane "
            "FROM indicator_refs WHERE chart_slug = ? ORDER BY pane ASC, indicator_id ASC",
            (slug,),
        )
        indicators = [
            Indicator(
                id=r[0],
                name=r[1],
                params=json.loads(r[2]),
                pane=int(r[3]),
            )
            for r in await ind_cur.fetchall()
        ]
        # Drawings
        dr_cur = await self.conn.execute(
            """
            SELECT drawing_id, kind, anchors_json, style_json, order_index,
                   prov_kind, prov_model, prov_created_at,
                   prov_confidence, prov_rationale
            FROM drawings WHERE chart_slug = ? ORDER BY order_index ASC
            """,
            (slug,),
        )
        drawings: list[Drawing] = []
        for d in await dr_cur.fetchall():
            anchors = [Anchor.model_validate(a) for a in json.loads(d[2])]
            style = Style.model_validate(json.loads(d[3]))
            prov: Provenance | None = None
            if d[5] is not None:  # prov_kind
                prov = Provenance(
                    kind=d[5],
                    model=d[6],
                    created_at=datetime.fromisoformat(d[7]),
                    confidence=d[8],
                    rationale=d[9],
                )
            drawings.append(
                Drawing(
                    id=d[0],
                    kind=d[1],
                    anchors=anchors,
                    style=style,
                    provenance=prov,
                )
            )
        # AI run (if linked)
        ai_run: AIRun | None = None
        if row[8] is not None:
            ai_run = await self._load_ai_run_for_chart(int(row[8]))
        # Reassemble Chart. Use model_validate so all sub-validators run.
        return Chart.model_validate(
            {
                "schemaVersion": int(row[3]),
                "slug": row[0],
                "title": row[2],
                "pair": row[1],
                "provenance": {
                    "kind": row[9],
                    "model": row[10],
                    "prompt_template_version": row[11],
                    "created_at": row[12],
                },
                "parent_chart_id": row[6],
                "data": {
                    "default_window_days": int(row[4]),
                    "default_interval": row[5],
                },
                "view": {
                    "indicators": [i.model_dump(mode="json") for i in indicators],
                    "drawings": [d.model_dump(mode="json") for d in drawings],
                    "analysis_text": row[7],
                },
                "ai_run": ai_run.model_dump(mode="json") if ai_run else None,
            }
        )

    async def _load_ai_run_for_chart(self, ai_run_id: int) -> AIRun | None:
        """Reconstruct the embedded ``AIRun`` model from ``ai_runs`` row."""
        cur = await self.conn.execute(
            """
            SELECT model, prompt_template_version, context_file_sha256,
                   context_preview, sr_candidates_presented, sr_candidates_selected
            FROM ai_runs WHERE run_id = ?
            """,
            (ai_run_id,),
        )
        r = await cur.fetchone()
        if r is None:
            return None
        presented = [SRCandidate.model_validate(c) for c in json.loads(r[4])]
        selected = json.loads(r[5])
        return AIRun(
            model=r[0],
            prompt_template_version=r[1],
            context_file_sha256=r[2],
            context_preview=r[3],
            sr_candidates_presented=presented,
            sr_candidates_selected=selected,
        )

    async def list_charts(
        self, *, pair_id: str | None = None, limit: int | None = None
    ) -> list[ChartListItem]:
        """Return chart summaries for sidebar listings.

        Newest first by ``updated_at_unix``. Filters by ``pair_id`` when
        supplied (this is the typical UI flow — "show charts for this pair").
        """
        sql = (
            "SELECT slug, pair_id, title, prov_kind, prov_model, "
            "parent_chart_slug, ai_run_id, updated_at_unix FROM charts"
        )
        params: list = []
        if pair_id is not None:
            sql += " WHERE pair_id = ?"
            params.append(pair_id)
        sql += " ORDER BY updated_at_unix DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        return [
            ChartListItem(
                slug=r[0],
                pair_id=r[1],
                title=r[2],
                prov_kind=r[3],
                prov_model=r[4],
                parent_chart_slug=r[5],
                ai_run_id=int(r[6]) if r[6] is not None else None,
                updated_at_unix=int(r[7]),
            )
            for r in rows
        ]

    async def delete_chart(self, slug: str) -> None:
        """Delete a chart. Cascades via FK to drawings + indicator_refs.

        Idempotent — raises ``ChartNotFound`` if the slug doesn't exist so
        callers can report a 404, but the underlying DELETE itself is safe
        on missing rows.
        """
        existing = await self.conn.execute("SELECT 1 FROM charts WHERE slug = ?", (slug,))
        if await existing.fetchone() is None:
            raise ChartNotFound(slug)
        await self.conn.execute("DELETE FROM charts WHERE slug = ?", (slug,))
        await self.conn.commit()
