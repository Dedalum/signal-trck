"""Async SQLite store. Owns all SQL strings; callers see Python types only.

Connect with ``async with Store.open() as store:`` for short scripts, or
manage lifecycle explicitly with ``store = Store(); await store.connect();
... await store.close()`` for long-running processes.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import structlog

from signal_trck import paths
from signal_trck.storage.models import Candle, Pair
from signal_trck.storage.schema import MIGRATIONS, SCHEMA_VERSION_DDL

log = structlog.get_logger(__name__)


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

    async def list_ai_runs(self, pair_id: str, *, limit: int | None = None) -> list[dict]:
        """Return AI run audit rows for a pair, newest first.

        Returned dicts contain all columns; JSON columns are returned as raw
        strings so callers can decide whether to parse.
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
        cols = [
            "run_id",
            "pair_id",
            "chart_slug",
            "model",
            "provider",
            "prompt_template_version",
            "system_prompt_hash",
            "context_file_sha256",
            "context_preview",
            "sr_candidates_presented",
            "sr_candidates_selected",
            "ran_at",
        ]
        return [dict(zip(cols, r, strict=True)) for r in rows]
