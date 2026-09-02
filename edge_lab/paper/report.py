"""Paper-run reporting.

Realized and unrealized (mark-to-market) P&L are always reported separately.
Net cash flow is never presented as P&L while positions remain open. When a
current price cannot be obtained for an open position, its mark-to-market value
is labeled unknown rather than guessed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from .db import PaperDB, decimals

PriceProvider = Callable[[str], Decimal | None]


def _percentile(values: list[Decimal], pct: float) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = pct * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = Decimal(str(rank - lo))
    return (ordered[lo] + (ordered[hi] - ordered[lo]) * frac).quantize(Decimal("0.01"))


def _max_realized_drawdown(realized_increments: list[Decimal]) -> Decimal:
    """Largest peak-to-trough decline of the cumulative realized-P&L curve.

    Returned as a non-negative magnitude (0 when the curve never declines).
    Computed over closures in chronological order; it is only meaningful once
    at least one position has been closed.
    """
    peak = Decimal(0)
    cumulative = Decimal(0)
    max_dd = Decimal(0)
    for inc in realized_increments:
        cumulative += inc
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


@dataclass
class MarkToMarket:
    asset: str
    title: str
    quantity: Decimal
    avg_entry: Decimal
    mark_price: Decimal | None
    unrealized: Decimal | None  # None when price unavailable


@dataclass
class PaperReport:
    run_id: int
    signals_observed: int
    signals_filled: int
    signals_skipped: int
    skip_reasons: dict[str, int]
    fill_rate: Decimal | None
    median_age_seconds: Decimal | None
    p90_age_seconds: Decimal | None
    median_drift_bps: Decimal | None
    p90_drift_bps: Decimal | None
    realized_pnl: Decimal
    max_realized_drawdown: Decimal | None
    buy_notional: Decimal
    sell_notional: Decimal
    avg_paper_notional: Decimal | None
    open_positions: list[MarkToMarket]
    unrealized_pnl: Decimal | None
    unrealized_known: bool
    market_concentration: list[tuple[str, Decimal]]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_net_pnl(self) -> Decimal | None:
        if self.unrealized_pnl is None:
            return None
        return self.realized_pnl + self.unrealized_pnl

    def to_dict(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "run_id": self.run_id,
            "signals_observed": self.signals_observed,
            "signals_filled": self.signals_filled,
            "signals_skipped": self.signals_skipped,
            "skip_reasons": self.skip_reasons,
            "fill_rate": s(self.fill_rate),
            "median_age_seconds": s(self.median_age_seconds),
            "p90_age_seconds": s(self.p90_age_seconds),
            "median_drift_bps": s(self.median_drift_bps),
            "p90_drift_bps": s(self.p90_drift_bps),
            "realized_pnl": s(self.realized_pnl),
            "max_realized_drawdown": s(self.max_realized_drawdown),
            "buy_notional": s(self.buy_notional),
            "sell_notional": s(self.sell_notional),
            "avg_paper_notional": s(self.avg_paper_notional),
            "unrealized_pnl": s(self.unrealized_pnl),
            "unrealized_known": self.unrealized_known,
            "total_net_pnl": s(self.total_net_pnl),
            "open_positions": [
                {
                    "asset": p.asset,
                    "title": p.title,
                    "quantity": str(p.quantity),
                    "avg_entry": str(p.avg_entry),
                    "mark_price": s(p.mark_price),
                    "unrealized": s(p.unrealized),
                }
                for p in self.open_positions
            ],
            "market_concentration": [{"market": m, "notional": str(n)} for m, n in self.market_concentration],
            "warnings": self.warnings,
        }


def build_report(db: PaperDB, run_id: int, price_provider: PriceProvider | None = None) -> PaperReport:
    signals = db.signals(run_id)
    fills = db.fills(run_id)
    closures = db.closures(run_id)
    positions = db.open_positions(run_id)

    observed = len(signals)
    filled = sum(1 for s in signals if s["disposition"] == "filled")
    skipped = sum(1 for s in signals if s["disposition"] == "skipped")
    fill_rate = (Decimal(filled) / Decimal(observed)).quantize(Decimal("0.0001")) if observed else None

    ages = [Decimal(s["signal_age_seconds"]) for s in fills if s["signal_age_seconds"] is not None]
    drifts = decimals([s for s in fills if s["side"] == "BUY"], "price_drift_bps")

    realized_increments = decimals(closures, "realized_pnl")  # chronological (ordered by id)
    realized = sum(realized_increments, Decimal(0))
    max_drawdown = _max_realized_drawdown(realized_increments) if closures else None
    buy_notional = sum(decimals([f for f in fills if f["side"] == "BUY"], "notional"), Decimal(0))
    sell_notional = sum(decimals([f for f in fills if f["side"] == "SELL"], "notional"), Decimal(0))
    buy_fills = [f for f in fills if f["side"] == "BUY"]
    avg_notional = (buy_notional / Decimal(len(buy_fills))).quantize(Decimal("0.01")) if buy_fills else None

    warnings: list[str] = []
    mtm: list[MarkToMarket] = []
    unrealized_total = Decimal(0)
    unrealized_known = True
    for pos in positions:
        price = price_provider(pos.asset) if price_provider else None
        if price is None:
            unrealized_known = False
            mtm.append(MarkToMarket(pos.asset, pos.title, pos.quantity, pos.avg_price, None, None))
            continue
        unreal = (price - pos.avg_price) * pos.quantity
        unrealized_total += unreal
        mtm.append(MarkToMarket(pos.asset, pos.title, pos.quantity, pos.avg_price, price, unreal))

    if positions and not unrealized_known:
        warnings.append("some open positions could not be marked to market; unrealized P&L is incomplete")
    unrealized_pnl = unrealized_total if (unrealized_known or not positions) else None

    conc: dict[str, Decimal] = {}
    for f in fills:
        key = f["title"] or f["asset"]
        conc[key] = conc.get(key, Decimal(0)) + (Decimal(str(f["notional"])) if f["notional"] else Decimal(0))
    market_conc = sorted(conc.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return PaperReport(
        run_id=run_id,
        signals_observed=observed,
        signals_filled=filled,
        signals_skipped=skipped,
        skip_reasons=db.skip_reason_counts(run_id),
        fill_rate=fill_rate,
        median_age_seconds=_percentile(ages, 0.5),
        p90_age_seconds=_percentile(ages, 0.9),
        median_drift_bps=_percentile(drifts, 0.5),
        p90_drift_bps=_percentile(drifts, 0.9),
        realized_pnl=realized,
        max_realized_drawdown=max_drawdown,
        buy_notional=buy_notional,
        sell_notional=sell_notional,
        avg_paper_notional=avg_notional,
        open_positions=mtm,
        unrealized_pnl=unrealized_pnl,
        unrealized_known=unrealized_known if positions else True,
        market_concentration=market_conc,
        warnings=warnings,
    )
