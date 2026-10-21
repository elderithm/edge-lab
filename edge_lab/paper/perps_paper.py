"""SQLite ledger for Perps paper positions and testnet order evidence.

Separate from the Polymarket and Event Contracts ledgers. Paper fills are
SIMULATED from an observed book walk (live testnet or fixture — the
``price_source`` column says which); they are never actual on-chain fills.
Testnet orders submitted through ``edge-lab perps execute`` are recorded in a
separate table with their transaction evidence. Decimals are stored as TEXT.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..errors import PaperTradingError
from ..venues.dreamdex_perps.models import FUNDING_PRECISION, PerpSide

SCHEMA_VERSION = 1
DEFAULT_PATH = ".edge-lab/perps-paper.db"
DEFAULT_STARTING_EQUITY = Decimal(1000)


def _t(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


def _d(v: object) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


@dataclass(frozen=True)
class PaperPosition:
    id: int
    opened_at: int
    market_id: str
    symbol: str
    quote_decimals: int
    side: PerpSide
    quantity: Decimal
    entry_price: Decimal
    entry_fee: Decimal
    entry_cum_funding_raw: int | None
    price_source: str
    status: str
    closed_at: int | None
    exit_price: Decimal | None
    exit_fee: Decimal | None
    funding_paid: Decimal | None
    realized_pnl: Decimal | None

    @property
    def entry_notional(self) -> Decimal:
        return self.quantity * self.entry_price

    def funding_since_open(self, cum_now_raw: int | None) -> Decimal | None:
        """Funding paid (+) / received (-) since open, from the cumulative index (exact, SDK semantics)."""
        if cum_now_raw is None or self.entry_cum_funding_raw is None:
            return None
        per_base = Decimal(cum_now_raw - self.entry_cum_funding_raw) / FUNDING_PRECISION
        per_base = per_base.scaleb(-self.quote_decimals)
        return Decimal(self.side.sign) * self.quantity * per_base

    def unrealized(self, mark: Decimal | None) -> Decimal | None:
        if mark is None:
            return None
        return Decimal(self.side.sign) * self.quantity * (mark - self.entry_price)


class PerpsPaperDB:
    def __init__(self, path: str | Path = DEFAULT_PATH, starting_equity: Decimal = DEFAULT_STARTING_EQUITY) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema(starting_equity)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> PerpsPaperDB:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _init_schema(self, starting_equity: Decimal) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS perps_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS perps_paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at INTEGER NOT NULL,
                market_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quote_decimals INTEGER NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
                quantity TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                entry_fee TEXT NOT NULL,
                entry_cum_funding_raw TEXT,
                price_source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_at INTEGER,
                exit_price TEXT,
                exit_fee TEXT,
                funding_paid TEXT,
                realized_pnl TEXT
            );
            CREATE TABLE IF NOT EXISTS perps_testnet_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                market_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                limit_price TEXT NOT NULL,
                order_type TEXT NOT NULL,
                account TEXT,
                tx_hash TEXT,
                receipt_status TEXT,
                block_number TEXT,
                order_id TEXT,
                filled_qty TEXT,
                avg_fill_price TEXT,
                reconciled_status TEXT NOT NULL,
                position_after TEXT,
                evidence_path TEXT
            );
            """
        )
        row = self.conn.execute("SELECT value FROM perps_meta WHERE key='version'").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO perps_meta(key, value) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
            self.conn.execute(
                "INSERT INTO perps_meta(key, value) VALUES ('starting_equity', ?)", (_t(starting_equity),)
            )
        elif int(row["value"]) != SCHEMA_VERSION:
            raise PaperTradingError(f"perps schema version {row['value']} != {SCHEMA_VERSION}; use a fresh db")
        self.conn.commit()

    @property
    def starting_equity(self) -> Decimal:
        row = self.conn.execute("SELECT value FROM perps_meta WHERE key='starting_equity'").fetchone()
        return Decimal(row["value"]) if row else DEFAULT_STARTING_EQUITY

    # ---- paper positions -------------------------------------------------
    def open_position(
        self,
        *,
        market_id: str,
        symbol: str,
        quote_decimals: int,
        side: PerpSide,
        quantity: Decimal,
        entry_price: Decimal,
        entry_fee: Decimal,
        entry_cum_funding_raw: int | None,
        price_source: str,
    ) -> int:
        if quantity <= 0 or entry_price <= 0:
            raise PaperTradingError("quantity and entry price must be positive")
        cur = self.conn.execute(
            """INSERT INTO perps_paper_positions(opened_at, market_id, symbol, quote_decimals, side, quantity,
               entry_price, entry_fee, entry_cum_funding_raw, price_source, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,'open')""",
            (
                int(time.time()),
                market_id,
                symbol,
                quote_decimals,
                side.value,
                _t(quantity),
                _t(entry_price),
                _t(entry_fee),
                None if entry_cum_funding_raw is None else str(entry_cum_funding_raw),
                price_source,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def close_position(
        self, position_id: int, *, exit_price: Decimal, exit_fee: Decimal, cum_funding_raw: int | None
    ) -> Decimal:
        pos = self.get(position_id)
        if pos.status != "open":
            raise PaperTradingError(f"paper position {position_id} already {pos.status}")
        gross = Decimal(pos.side.sign) * pos.quantity * (exit_price - pos.entry_price)
        funding = pos.funding_since_open(cum_funding_raw)
        realized = gross - pos.entry_fee - exit_fee - (funding or Decimal(0))
        self.conn.execute(
            """UPDATE perps_paper_positions SET status='closed', closed_at=?, exit_price=?, exit_fee=?,
               funding_paid=?, realized_pnl=? WHERE id=?""",
            (int(time.time()), _t(exit_price), _t(exit_fee), _t(funding), _t(realized), position_id),
        )
        self.conn.commit()
        return realized

    def get(self, position_id: int) -> PaperPosition:
        row = self.conn.execute("SELECT * FROM perps_paper_positions WHERE id=?", (position_id,)).fetchone()
        if row is None:
            raise PaperTradingError(f"no paper position {position_id}")
        return _row_to_position(row)

    def list_positions(self, status: str | None = None) -> list[PaperPosition]:
        sql = "SELECT * FROM perps_paper_positions"
        args: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        return [_row_to_position(r) for r in self.conn.execute(sql + " ORDER BY id", args).fetchall()]

    def open_exposure(self) -> tuple[dict[str, Decimal], Decimal]:
        """Entry notional of open positions: (per market, total)."""
        per: dict[str, Decimal] = {}
        for p in self.list_positions("open"):
            per[p.market_id] = per.get(p.market_id, Decimal(0)) + p.entry_notional
        return per, sum(per.values(), Decimal(0))

    def summary(self, marks: dict[str, tuple[Decimal | None, int | None]] | None = None) -> dict[str, object]:
        """P&L summary. ``marks`` maps market_id -> (mark price, cumulative funding raw)."""
        marks = marks or {}
        positions = self.list_positions()
        realized = sum((p.realized_pnl or Decimal(0) for p in positions if p.status == "closed"), Decimal(0))
        unrealized = Decimal(0)
        funding_open = Decimal(0)
        unpriced: list[int] = []
        for p in positions:
            if p.status != "open":
                continue
            mark, cum = marks.get(p.market_id, (None, None))
            u = p.unrealized(mark)
            if u is None:
                unpriced.append(p.id)
                continue
            unrealized += u - p.entry_fee
            funding_open += p.funding_since_open(cum) or Decimal(0)
        equity = self.starting_equity + realized + unrealized - funding_open
        return {
            "label": "PAPER (simulated fills; not verified strategy performance)",
            "starting_equity": str(self.starting_equity),
            "positions": len(positions),
            "open": sum(1 for p in positions if p.status == "open"),
            "closed": sum(1 for p in positions if p.status == "closed"),
            "realized_pnl": str(realized.quantize(Decimal("0.000001"))),
            "unrealized_pnl": str(unrealized.quantize(Decimal("0.000001"))),
            "open_funding_paid": str(funding_open.quantize(Decimal("0.000001"))),
            "equity": str(equity.quantize(Decimal("0.000001"))),
            "unpriced_open_positions": unpriced,
        }

    # ---- testnet evidence ------------------------------------------------
    def record_testnet_order(self, rec: dict[str, Any]) -> int:
        cols = (
            "market_id symbol side quantity limit_price order_type account tx_hash receipt_status block_number "
            "order_id filled_qty avg_fill_price reconciled_status position_after evidence_path"
        ).split()
        vals = [None if rec.get(c) is None else str(rec.get(c)) for c in cols]
        cur = self.conn.execute(
            f"INSERT INTO perps_testnet_orders(created_at, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
            (int(time.time()), *vals),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def list_testnet_orders(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM perps_testnet_orders ORDER BY id").fetchall()]


def _row_to_position(r: sqlite3.Row) -> PaperPosition:
    cum = r["entry_cum_funding_raw"]
    return PaperPosition(
        id=int(r["id"]),
        opened_at=int(r["opened_at"]),
        market_id=r["market_id"],
        symbol=r["symbol"],
        quote_decimals=int(r["quote_decimals"]),
        side=PerpSide(r["side"]),
        quantity=Decimal(r["quantity"]),
        entry_price=Decimal(r["entry_price"]),
        entry_fee=Decimal(r["entry_fee"]),
        entry_cum_funding_raw=None if cum is None else int(cum),
        price_source=r["price_source"],
        status=r["status"],
        closed_at=r["closed_at"],
        exit_price=_d(r["exit_price"]),
        exit_fee=_d(r["exit_fee"]),
        funding_paid=_d(r["funding_paid"]),
        realized_pnl=_d(r["realized_pnl"]),
    )
