"""SQLite persistence for paper trading.

Decimals are stored as TEXT to preserve exact precision (never as REAL). The
schema is versioned from the start via ``schema_meta`` so migrations remain
explicit. All state needed to audit a paper result back to its source activity
is persisted.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..errors import PaperTradingError

SCHEMA_VERSION = 1


def _d(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


@dataclass(frozen=True)
class PaperPosition:
    run_id: int
    asset: str
    quantity: Decimal
    cost_basis: Decimal
    title: str = ""

    @property
    def avg_price(self) -> Decimal:
        return (self.cost_basis / self.quantity) if self.quantity > 0 else Decimal(0)


class PaperDB:
    def __init__(self, path: str | Path = ".edge-lab/paper.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._defer_commit = False
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _commit(self) -> None:
        """Commit unless inside an ``atomic()`` block that defers it."""
        if not self._defer_commit:
            self.conn.commit()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Group writes into one transaction: all commit together, or none.

        Prevents the positions cache from desyncing from fills/closures if the
        process dies mid-write. On any exception the partial writes roll back.
        """
        prev = self._defer_commit
        self._defer_commit = True
        try:
            yield
        except BaseException:
            self.conn.rollback()
            raise
        else:
            if not prev:
                self.conn.commit()
        finally:
            self._defer_commit = prev

    def __enter__(self) -> PaperDB:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                source_wallet TEXT NOT NULL,
                params_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            );
            CREATE TABLE IF NOT EXISTS observed_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_runs(id),
                signal_id TEXT NOT NULL,
                observed_at INTEGER NOT NULL,
                source_ts INTEGER,
                asset TEXT,
                side TEXT,
                source_price TEXT,
                source_size TEXT,
                title TEXT,
                outcome TEXT,
                tx_hash TEXT,
                disposition TEXT NOT NULL,
                skip_reason TEXT,
                UNIQUE(run_id, signal_id)
            );
            CREATE TABLE IF NOT EXISTS paper_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_runs(id),
                signal_ref INTEGER REFERENCES observed_signals(id),
                filled_at INTEGER NOT NULL,
                asset TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                quantity TEXT NOT NULL,
                vwap TEXT NOT NULL,
                notional TEXT NOT NULL,
                best_at_obs TEXT,
                source_price TEXT,
                price_drift_bps TEXT,
                signal_age_seconds INTEGER,
                fee_buffer_bps TEXT,
                slippage_buffer_bps TEXT,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                run_id INTEGER NOT NULL REFERENCES paper_runs(id),
                asset TEXT NOT NULL,
                quantity TEXT NOT NULL,
                cost_basis TEXT NOT NULL,
                title TEXT,
                PRIMARY KEY (run_id, asset)
            );
            CREATE TABLE IF NOT EXISTS paper_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_runs(id),
                asset TEXT NOT NULL,
                closed_at INTEGER NOT NULL,
                quantity TEXT NOT NULL,
                avg_entry TEXT NOT NULL,
                exit_vwap TEXT NOT NULL,
                realized_pnl TEXT NOT NULL,
                title TEXT
            );
            """
        )
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_meta(key, value) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
        elif int(row["value"]) != SCHEMA_VERSION:
            raise PaperTradingError(
                f"database schema version {row['value']} != supported {SCHEMA_VERSION}; use a fresh db"
            )
        self._commit()

    # --- runs ---------------------------------------------------------------
    def create_run(self, source_wallet: str, params_json: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO paper_runs(created_at, source_wallet, params_json) VALUES (?, ?, ?)",
            (int(time.time()), source_wallet, params_json),
        )
        self._commit()
        return int(cur.lastrowid or 0)

    def latest_run_id(self, source_wallet: str | None = None) -> int | None:
        if source_wallet:
            row = self.conn.execute(
                "SELECT id FROM paper_runs WHERE source_wallet=? ORDER BY id DESC LIMIT 1",
                (source_wallet,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT id FROM paper_runs ORDER BY id DESC LIMIT 1").fetchone()
        return int(row["id"]) if row else None

    def list_runs(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM paper_runs ORDER BY id").fetchall())

    # --- signals ------------------------------------------------------------
    def has_signal(self, run_id: int, signal_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM observed_signals WHERE run_id=? AND signal_id=?", (run_id, signal_id)
        ).fetchone()
        return row is not None

    def record_signal(
        self,
        *,
        run_id: int,
        signal_id: str,
        observed_at: int,
        source_ts: int | None,
        asset: str,
        side: str,
        source_price: Decimal | None,
        source_size: Decimal | None,
        title: str,
        outcome: str,
        tx_hash: str,
        disposition: str,
        skip_reason: str | None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO observed_signals(
                run_id, signal_id, observed_at, source_ts, asset, side,
                source_price, source_size, title, outcome, tx_hash, disposition, skip_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                signal_id,
                observed_at,
                source_ts,
                asset,
                side,
                _text(source_price),
                _text(source_size),
                title,
                outcome,
                tx_hash,
                disposition,
                skip_reason,
            ),
        )
        self._commit()
        return int(cur.lastrowid or 0)

    # --- fills / positions --------------------------------------------------
    def record_fill(self, **kw: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_fills(
                run_id, signal_ref, filled_at, asset, side, quantity, vwap, notional,
                best_at_obs, source_price, price_drift_bps, signal_age_seconds,
                fee_buffer_bps, slippage_buffer_bps, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kw["run_id"],
                kw.get("signal_ref"),
                kw["filled_at"],
                kw["asset"],
                kw["side"],
                _text(kw["quantity"]),
                _text(kw["vwap"]),
                _text(kw["notional"]),
                _text(kw.get("best_at_obs")),
                _text(kw.get("source_price")),
                _text(kw.get("price_drift_bps")),
                kw.get("signal_age_seconds"),
                _text(kw.get("fee_buffer_bps")),
                _text(kw.get("slippage_buffer_bps")),
                kw.get("title", ""),
            ),
        )
        self._commit()

    def get_position(self, run_id: int, asset: str) -> PaperPosition:
        row = self.conn.execute("SELECT * FROM paper_positions WHERE run_id=? AND asset=?", (run_id, asset)).fetchone()
        if row is None:
            return PaperPosition(run_id=run_id, asset=asset, quantity=Decimal(0), cost_basis=Decimal(0))
        return PaperPosition(
            run_id=run_id,
            asset=asset,
            quantity=_d(row["quantity"]),
            cost_basis=_d(row["cost_basis"]),
            title=row["title"] or "",
        )

    def upsert_position(self, pos: PaperPosition) -> None:
        if pos.quantity <= 0:
            self.conn.execute("DELETE FROM paper_positions WHERE run_id=? AND asset=?", (pos.run_id, pos.asset))
        else:
            self.conn.execute(
                """
                INSERT INTO paper_positions(run_id, asset, quantity, cost_basis, title)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, asset) DO UPDATE SET
                    quantity=excluded.quantity,
                    cost_basis=excluded.cost_basis,
                    title=excluded.title
                """,
                (pos.run_id, pos.asset, _text(pos.quantity), _text(pos.cost_basis), pos.title),
            )
        self._commit()

    def record_closure(self, **kw: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_closures(
                run_id, asset, closed_at, quantity, avg_entry, exit_vwap, realized_pnl, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kw["run_id"],
                kw["asset"],
                kw["closed_at"],
                _text(kw["quantity"]),
                _text(kw["avg_entry"]),
                _text(kw["exit_vwap"]),
                _text(kw["realized_pnl"]),
                kw.get("title", ""),
            ),
        )
        self._commit()

    def open_positions(self, run_id: int) -> list[PaperPosition]:
        rows = self.conn.execute("SELECT * FROM paper_positions WHERE run_id=? ORDER BY asset", (run_id,)).fetchall()
        return [
            PaperPosition(
                run_id=run_id,
                asset=r["asset"],
                quantity=_d(r["quantity"]),
                cost_basis=_d(r["cost_basis"]),
                title=r["title"] or "",
            )
            for r in rows
        ]

    def fills(self, run_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM paper_fills WHERE run_id=? ORDER BY id", (run_id,)).fetchall())

    def closures(self, run_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM paper_closures WHERE run_id=? ORDER BY id", (run_id,)).fetchall())

    def signals(self, run_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute("SELECT * FROM observed_signals WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        )

    def skip_reason_counts(self, run_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT skip_reason, COUNT(*) AS c FROM observed_signals "
            "WHERE run_id=? AND disposition='skipped' GROUP BY skip_reason",
            (run_id,),
        ).fetchall()
        return {str(r["skip_reason"]): int(r["c"]) for r in rows}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def decimals(rows: Iterable[sqlite3.Row], column: str) -> list[Decimal]:
    return [_d(r[column]) for r in rows if r[column] is not None]
