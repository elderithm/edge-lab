"""Forward paper-following of a public wallet's activity.

The point is to measure the gap between *seeing* a public signal and obtaining
a realistically executable simulated price. Fills are size-aware (order-book
walk), conservative, and every rejection is recorded with a reason code. No
real order endpoint exists anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from ..models import FillEstimate, OrderBook, OrderBookLevel, WalletActivity
from .db import PaperDB, PaperPosition

# Skip reason codes (see docs/05-paper-trading.md).
SIGNAL_TOO_OLD = "signal_too_old"
MISSING_TOKEN_ID = "missing_token_id"
MISSING_SOURCE_PRICE = "missing_source_price"
ORDER_BOOK_UNAVAILABLE = "order_book_unavailable"
INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
PRICE_DRIFT_TOO_LARGE = "price_drift_too_large"
DUPLICATE_SIGNAL = "duplicate_signal"
UNSUPPORTED_ACTIVITY = "unsupported_activity"
INVALID_MARKET_STATE = "invalid_market_state"


class BookProvider(Protocol):
    def get_order_book(self, token_id: str) -> OrderBook: ...


@dataclass(frozen=True)
class FollowConfig:
    paper_usdc: Decimal = Decimal("10")
    max_age_seconds: int = 120
    max_drift_bps: Decimal = Decimal("300")
    fee_buffer_bps: Decimal = Decimal("50")
    slippage_buffer_bps: Decimal = Decimal("50")


@dataclass(frozen=True)
class Outcome:
    signal_id: str
    disposition: str  # "filled" | "skipped" | "duplicate"
    reason: str | None
    message: str


def walk_for_notional(levels: Sequence[OrderBookLevel], budget: Decimal) -> FillEstimate:
    """Walk asks spending up to ``budget`` USDC; ``fully_filled`` = budget met."""
    if budget <= 0:
        return FillEstimate(Decimal(0), Decimal(0), Decimal(0), True, 0)
    remaining = budget
    qty = Decimal(0)
    cost = Decimal(0)
    consumed = 0
    for level in levels:
        if remaining <= 0:
            break
        if level.price <= 0:
            continue  # non-positive price is invalid; skip (avoids div-by-zero)
        affordable_qty = remaining / level.price
        take = min(affordable_qty, level.size)
        qty += take
        spent = take * level.price
        cost += spent
        remaining -= spent
        consumed += 1
    vwap = (cost / qty) if qty > 0 else Decimal(0)
    return FillEstimate(qty, cost, vwap, remaining <= Decimal("1e-9"), consumed)


def walk_bids(levels: Sequence[OrderBookLevel], quantity: Decimal) -> FillEstimate:
    """Sell up to ``quantity`` shares into the bids, best (highest) first."""
    if quantity <= 0:
        return FillEstimate(Decimal(0), Decimal(0), Decimal(0), True, 0)
    remaining = quantity
    proceeds = Decimal(0)
    consumed = 0
    for level in levels:
        if remaining <= 0:
            break
        take = min(remaining, level.size)
        proceeds += take * level.price
        remaining -= take
        consumed += 1
    sold = quantity - remaining
    vwap = (proceeds / sold) if sold > 0 else Decimal(0)
    return FillEstimate(sold, proceeds, vwap, remaining <= 0, consumed)


class PaperFollower:
    def __init__(self, db: PaperDB, books: BookProvider, run_id: int, config: FollowConfig) -> None:
        self.db = db
        self.books = books
        self.run_id = run_id
        self.cfg = config

    def process_activities(self, activities: Sequence[WalletActivity], now: int) -> list[Outcome]:
        """Process activities oldest-first so bursts replay in causal order."""
        outcomes: list[Outcome] = []
        for act in sorted(activities, key=lambda a: a.timestamp or 0):
            outcomes.append(self._process_one(act, now))
        return outcomes

    def _process_one(self, act: WalletActivity, now: int) -> Outcome:
        sid = act.signal_id
        if self.db.has_signal(self.run_id, sid):
            return Outcome(sid, "duplicate", DUPLICATE_SIGNAL, "duplicate signal ignored")

        # Validate before any fill attempt; record disposition either way.
        pre_skip = self._pre_validate(act, now)
        if pre_skip is not None:
            return self._skip(act, now, pre_skip)

        if act.side == "BUY":
            return self._simulate_buy(act, now)
        return self._simulate_sell(act, now)

    def _pre_validate(self, act: WalletActivity, now: int) -> str | None:
        if act.activity_type not in ("", "TRADE") or act.side not in ("BUY", "SELL"):
            return UNSUPPORTED_ACTIVITY
        if not act.asset:
            return MISSING_TOKEN_ID
        if act.price is None or act.price <= 0:
            return MISSING_SOURCE_PRICE
        if act.timestamp is None:
            return SIGNAL_TOO_OLD
        age = now - act.timestamp
        if age < 0 or age > self.cfg.max_age_seconds:
            return SIGNAL_TOO_OLD
        return None

    def _simulate_buy(self, act: WalletActivity, now: int) -> Outcome:
        book = self._safe_book(act.asset)
        if book is None:
            return self._skip(act, now, ORDER_BOOK_UNAVAILABLE)
        if not book.asks:
            return self._skip(act, now, INSUFFICIENT_LIQUIDITY)

        fill = walk_for_notional(book.asks, self.cfg.paper_usdc)
        if not fill.fully_filled or fill.quantity <= 0:
            return self._skip(act, now, INSUFFICIENT_LIQUIDITY)

        assert act.price is not None
        drift_bps = ((fill.vwap - act.price) / act.price) * Decimal(10_000)
        if drift_bps > self.cfg.max_drift_bps:
            return self._skip(act, now, PRICE_DRIFT_TOO_LARGE)

        age = now - (act.timestamp or now)
        best = book.best_ask.price if book.best_ask else None
        # Signal, fill, and position update commit atomically so the positions
        # cache can never desync from the fills if the process dies mid-write.
        with self.db.atomic():
            signal_ref = self._record_signal(act, now, "filled", None)
            self.db.record_fill(
                run_id=self.run_id,
                signal_ref=signal_ref,
                filled_at=now,
                asset=act.asset,
                side="BUY",
                quantity=fill.quantity,
                vwap=fill.vwap,
                notional=fill.cost,
                best_at_obs=best,
                source_price=act.price,
                price_drift_bps=drift_bps.quantize(Decimal("0.01")),
                signal_age_seconds=age,
                fee_buffer_bps=self.cfg.fee_buffer_bps,
                slippage_buffer_bps=self.cfg.slippage_buffer_bps,
                title=act.title,
            )
            pos = self.db.get_position(self.run_id, act.asset)
            self.db.upsert_position(
                PaperPosition(
                    run_id=self.run_id,
                    asset=act.asset,
                    quantity=pos.quantity + fill.quantity,
                    cost_basis=pos.cost_basis + fill.cost,
                    title=act.title or pos.title,
                )
            )
        return Outcome(
            act.signal_id,
            "filled",
            None,
            f"PAPER BUY {fill.quantity:.4f} @ {fill.vwap:.4f} "
            f"(spent {fill.cost:.2f}, drift {drift_bps:.0f}bps, age {age}s) | {act.title[:60]}",
        )

    def _simulate_sell(self, act: WalletActivity, now: int) -> Outcome:
        pos = self.db.get_position(self.run_id, act.asset)
        if pos.quantity <= 0:
            # Following a SELL for something we never paper-bought: nothing to exit.
            return self._skip(act, now, INVALID_MARKET_STATE)

        book = self._safe_book(act.asset)
        if book is None:
            return self._skip(act, now, ORDER_BOOK_UNAVAILABLE)
        if not book.bids:
            return self._skip(act, now, INSUFFICIENT_LIQUIDITY)

        # Never sell more than the paper position owns.
        sell_qty = min(pos.quantity, sum((lvl.size for lvl in book.bids), Decimal(0)))
        fill = walk_bids(book.bids, sell_qty)
        if fill.quantity <= 0:
            return self._skip(act, now, INSUFFICIENT_LIQUIDITY)

        avg_entry = pos.avg_price
        realized = (fill.vwap - avg_entry) * fill.quantity
        age = now - (act.timestamp or now)
        remaining_qty = pos.quantity - fill.quantity
        remaining_cost = avg_entry * remaining_qty
        # Fill, position update, and closure commit atomically together.
        with self.db.atomic():
            signal_ref = self._record_signal(act, now, "filled", None)
            self.db.record_fill(
                run_id=self.run_id,
                signal_ref=signal_ref,
                filled_at=now,
                asset=act.asset,
                side="SELL",
                quantity=fill.quantity,
                vwap=fill.vwap,
                notional=fill.cost,
                best_at_obs=book.best_bid.price if book.best_bid else None,
                source_price=act.price,
                price_drift_bps=None,
                signal_age_seconds=age,
                fee_buffer_bps=self.cfg.fee_buffer_bps,
                slippage_buffer_bps=self.cfg.slippage_buffer_bps,
                title=act.title,
            )
            self.db.upsert_position(
                PaperPosition(
                    run_id=self.run_id,
                    asset=act.asset,
                    quantity=remaining_qty,
                    cost_basis=remaining_cost,
                    title=pos.title,
                )
            )
            self.db.record_closure(
                run_id=self.run_id,
                asset=act.asset,
                closed_at=now,
                quantity=fill.quantity,
                avg_entry=avg_entry,
                exit_vwap=fill.vwap,
                realized_pnl=realized,
                title=pos.title or act.title,
            )
        kind = "full" if remaining_qty <= 0 else "partial"
        return Outcome(
            act.signal_id,
            "filled",
            None,
            f"PAPER SELL ({kind}) {fill.quantity:.4f} @ {fill.vwap:.4f} realized {realized:+.4f} | {act.title[:60]}",
        )

    def _safe_book(self, token_id: str) -> OrderBook | None:
        try:
            return self.books.get_order_book(token_id)
        except Exception:  # network/data failure -> recorded as unavailable
            return None

    def _record_signal(self, act: WalletActivity, now: int, disposition: str, reason: str | None) -> int:
        return self.db.record_signal(
            run_id=self.run_id,
            signal_id=act.signal_id,
            observed_at=now,
            source_ts=act.timestamp,
            asset=act.asset,
            side=act.side,
            source_price=act.price,
            source_size=act.size,
            title=act.title,
            outcome=act.outcome,
            tx_hash=act.tx_hash,
            disposition=disposition,
            skip_reason=reason,
        )

    def _skip(self, act: WalletActivity, now: int, reason: str) -> Outcome:
        self._record_signal(act, now, "skipped", reason)
        return Outcome(act.signal_id, "skipped", reason, f"SKIP [{reason}] {act.side} {act.title[:50]}")
