"""SQLite paper-trading store for DreamDEX event contracts.

Separate from the Polymarket paper ledger so neither disturbs the other. Uses
real DreamDEX market data (recorded at signal time) with simulated execution;
requires no private key. Decimals are stored as TEXT to preserve precision.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..core.types import Side
from ..errors import PaperTradingError

SCHEMA_VERSION = 1


def _t(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _d(value: object) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


@dataclass(frozen=True)
class PaperTrade:
    id: int
    market_id: str
    asset: str
    side: str
    size: Decimal
    exec_price: Decimal
    notional: Decimal
    model_p: Decimal
    edge_bps: Decimal
    status: str
    outcome: str | None
    realized_pnl: Decimal | None


class DreamdexPaperDB:
    def __init__(self, path: str | Path = ".edge-lab/dreamdex-paper.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> DreamdexPaperDB:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS dreamdex_paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                signal_ts INTEGER NOT NULL,
                venue TEXT NOT NULL,
                market_id TEXT NOT NULL,
                asset TEXT NOT NULL,
                symbol TEXT,
                side TEXT NOT NULL CHECK(side IN ('UP','DOWN')),
                model_p TEXT NOT NULL,
                exec_price TEXT NOT NULL,
                edge_bps TEXT NOT NULL,
                size TEXT NOT NULL,
                notional TEXT NOT NULL,
                expected_value TEXT NOT NULL,
                confidence TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                outcome TEXT,
                realized_pnl TEXT,
                settled_at INTEGER
            );
            """
        )
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_meta(key, value) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
        elif int(row["value"]) != SCHEMA_VERSION:
            raise PaperTradingError(f"schema version {row['value']} != {SCHEMA_VERSION}; use a fresh db")
        self.conn.commit()

    def record_trade(
        self,
        *,
        venue: str,
        market_id: str,
        asset: str,
        symbol: str,
        side: Side,
        model_p: Decimal,
        exec_price: Decimal,
        edge_bps: Decimal,
        size: Decimal,
        confidence: Decimal,
        mode: str,
        signal_ts: int | None = None,
    ) -> int:
        notional = (size * exec_price).quantize(Decimal("0.000001"))
        expected_value = (size * (model_p - exec_price)).quantize(Decimal("0.000001"))
        now = int(time.time())
        cur = self.conn.execute(
            """
            INSERT INTO dreamdex_paper_trades(
                created_at, signal_ts, venue, market_id, asset, symbol, side,
                model_p, exec_price, edge_bps, size, notional, expected_value,
                confidence, mode, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open')
            """,
            (
                now,
                signal_ts or now,
                venue,
                market_id,
                asset,
                symbol,
                side.value,
                _t(model_p),
                _t(exec_price),
                _t(edge_bps),
                _t(size),
                _t(notional),
                _t(expected_value),
                _t(confidence),
                mode,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def settle_trade(self, trade_id: int, outcome: str) -> Decimal:
        """Settle a paper trade against a resolved/voided outcome.

        Payoff: each outcome token pays 1 on a win. VOID returns the stake
        (P&L 0) and is tracked separately from a win/loss.
        """
        outcome = outcome.upper()
        if outcome not in ("UP", "DOWN", "VOID"):
            raise PaperTradingError("outcome must be UP, DOWN or VOID")
        row = self.conn.execute(
            "SELECT side, size, notional, status FROM dreamdex_paper_trades WHERE id=?", (trade_id,)
        ).fetchone()
        if row is None:
            raise PaperTradingError(f"no paper trade {trade_id}")
        if row["status"] != "open":
            raise PaperTradingError(f"trade {trade_id} already {row['status']}")
        size = _d(row["size"])
        notional = _d(row["notional"])
        if outcome == "VOID":
            realized = Decimal(0)
            status = "void"
        else:
            won = outcome == row["side"]
            realized = (size - notional) if won else (-notional)
            status = "settled"
        self.conn.execute(
            "UPDATE dreamdex_paper_trades SET status=?, outcome=?, realized_pnl=?, settled_at=? WHERE id=?",
            (status, outcome, _t(realized), int(time.time()), trade_id),
        )
        self.conn.commit()
        return realized

    def list_trades(self) -> list[PaperTrade]:
        rows = self.conn.execute("SELECT * FROM dreamdex_paper_trades ORDER BY id").fetchall()
        return [
            PaperTrade(
                id=int(r["id"]),
                market_id=r["market_id"],
                asset=r["asset"],
                side=r["side"],
                size=_d(r["size"]),
                exec_price=_d(r["exec_price"]),
                notional=_d(r["notional"]),
                model_p=_d(r["model_p"]),
                edge_bps=_d(r["edge_bps"]),
                status=r["status"],
                outcome=r["outcome"],
                realized_pnl=_d(r["realized_pnl"]) if r["realized_pnl"] is not None else None,
            )
            for r in rows
        ]

    def summary(self) -> dict[str, object]:
        rows = self.list_trades()
        settled = [t for t in rows if t.status == "settled"]
        realized = sum((t.realized_pnl or Decimal(0) for t in settled), Decimal(0))
        expected_open = sum((t.size * (t.model_p - t.exec_price) for t in rows if t.status == "open"), Decimal(0))
        return {
            "trades": len(rows),
            "open": sum(1 for t in rows if t.status == "open"),
            "settled": len(settled),
            "void": sum(1 for t in rows if t.status == "void"),
            "realized_pnl": str(realized),
            "open_expected_value": str(expected_open.quantize(Decimal("0.000001"))),
            "total_notional": str(sum((t.notional for t in rows), Decimal(0))),
        }
