"""Explainable Perps market analytics (pure functions over a :class:`PerpSnapshot`).

Four layers are kept separate on purpose and never blended into one score:

1. **Observed** market conditions — funding, basis, spread, depth, volatility.
2. **Estimated execution cost** — a size-aware walk of the live book.
3. **Risk** — margin, effective leverage, estimated liquidation distance.
4. **Strategy edge** — always ``NOT_ESTIMATED``: Edge Lab has no validated
   predictive model for perps, so it never claims positive expected value.

Funding, basis and spread are observations, not executable arbitrage. Every
threshold used to categorize a market is a named field of
:class:`AssessmentThresholds` and is documented in docs/PERPS_ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..venues.dreamdex_perps.models import BookLevel, PerpBook, PerpSide, PerpSnapshot

BPS = Decimal(10_000)
SECONDS_PER_YEAR = Decimal(365 * 24 * 3600)
MIN_VOL_RETURNS = 12  # fewer valid log returns than this => INSUFFICIENT_DATA


def _q(v: Decimal | None, places: str = "0.0001") -> str | None:
    return None if v is None else str(v.quantize(Decimal(places)))


def _bps(v: Decimal | None) -> str | None:
    return _q(v, "0.01")


# --------------------------------------------------------------------------- funding
@dataclass(frozen=True)
class FundingMetrics:
    rate_per_window: Decimal | None
    window_sec: int | None
    interval_sec: int | None
    rate_per_interval: Decimal | None
    rate_per_hour: Decimal | None
    annualized: Decimal | None  # only when window AND interval are known
    direction: str  # LONGS_PAY | SHORTS_PAY | NEUTRAL | UNKNOWN
    last_funding_at: int | None
    next_funding_at: int | None
    stale: bool | None
    next_premium: Decimal | None
    next_premium_basis: str | None
    missing: tuple[str, ...]

    def holding_cost(self, side: PerpSide, notional: Decimal, hours: Decimal) -> Decimal | None:
        """Estimated funding paid (+) or received (-) holding ``notional`` for ``hours``.

        Assumes the current rate persists — a projection, not a forecast.
        """
        if self.rate_per_window is None or not self.window_sec:
            return None
        return Decimal(side.sign) * notional * self.rate_per_window * hours * 3600 / Decimal(self.window_sec)

    def to_dict(self) -> dict[str, object]:
        return {
            "rate_per_window": _q(self.rate_per_window, "0.00000001"),
            "window_sec": self.window_sec,
            "interval_sec": self.interval_sec,
            "rate_per_interval": _q(self.rate_per_interval, "0.00000001"),
            "rate_per_hour": _q(self.rate_per_hour, "0.00000001"),
            "annualized": _q(self.annualized, "0.0001"),
            "direction": self.direction,
            "last_funding_at": self.last_funding_at,
            "next_funding_at": self.next_funding_at,
            "stale": self.stale,
            "next_premium": _q(self.next_premium, "0.00000001"),
            "next_premium_basis": self.next_premium_basis,
            "missing": list(self.missing),
        }


def funding_metrics(snap: PerpSnapshot, now: int) -> FundingMetrics:
    st = snap.state
    missing: list[str] = []
    rate, window, interval = st.funding_rate, st.funding_window_sec, st.funding_interval_sec
    if rate is None:
        missing.append("funding_rate")
    if not window:
        missing.append("funding_window_sec")
    if not interval:
        missing.append("funding_interval_sec")
    per_interval = per_hour = annual = None
    if rate is not None and window:
        per_hour = rate * Decimal(3600) / Decimal(window)
        if interval:
            per_interval = rate * Decimal(interval) / Decimal(window)
            annual = rate * SECONDS_PER_YEAR / Decimal(window)
    if rate is None:
        direction = "UNKNOWN"
    elif rate > 0:
        direction = "LONGS_PAY"
    elif rate < 0:
        direction = "SHORTS_PAY"
    else:
        direction = "NEUTRAL"
    stale = None
    if st.last_funding_at is not None and interval:
        stale = now - st.last_funding_at > 2 * interval  # SDK's isFundingStale default (2 intervals)
    prem = snap.premium
    return FundingMetrics(
        rate_per_window=rate,
        window_sec=window,
        interval_sec=interval,
        rate_per_interval=per_interval,
        rate_per_hour=per_hour,
        annualized=annual,
        direction=direction,
        last_funding_at=st.last_funding_at,
        next_funding_at=st.next_funding_at,
        stale=stale,
        next_premium=prem.time_weighted_premium if prem else None,
        next_premium_basis=(("time-weighted" if prem.armed else "point sample (pre-upgrade)") if prem else None),
        missing=tuple(missing),
    )


# --------------------------------------------------------------------------- basis
@dataclass(frozen=True)
class BasisMetrics:
    mark: Decimal | None
    index: Decimal | None
    absolute: Decimal | None
    bps: Decimal | None
    index_age_s: int | None
    missing: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mark": _q(self.mark, "0.00000001"),
            "index": _q(self.index, "0.00000001"),
            "absolute": _q(self.absolute, "0.00000001"),
            "bps": _bps(self.bps),
            "index_age_s": self.index_age_s,
            "missing": list(self.missing),
        }


def basis_metrics(snap: PerpSnapshot, now: int) -> BasisMetrics:
    st = snap.state
    missing = []
    if st.mark_price is None:
        missing.append("mark_price" + ("" if st.mark_price_ok else " (feed stale)"))
    if st.index_price is None:
        missing.append("index_price")
    absolute = bps = None
    if st.mark_price is not None and st.index_price is not None:
        absolute = st.mark_price - st.index_price
        bps = absolute / st.index_price * BPS
    age = None if st.index_updated_at is None else max(0, now - st.index_updated_at)
    return BasisMetrics(st.mark_price, st.index_price, absolute, bps, age, tuple(missing))


# --------------------------------------------------------------------------- liquidity
@dataclass(frozen=True)
class LiquidityMetrics:
    best_bid: Decimal | None
    best_ask: Decimal | None
    mid: Decimal | None
    spread: Decimal | None
    spread_bps: Decimal | None
    band_bps: Decimal
    bid_depth_quote: Decimal  # quote notional resting within band of mid
    ask_depth_quote: Decimal
    bid_levels: int
    ask_levels: int

    def to_dict(self) -> dict[str, object]:
        return {
            "best_bid": _q(self.best_bid, "0.00000001"),
            "best_ask": _q(self.best_ask, "0.00000001"),
            "mid": _q(self.mid, "0.00000001"),
            "spread": _q(self.spread, "0.00000001"),
            "spread_bps": _bps(self.spread_bps),
            "band_bps": str(self.band_bps),
            "bid_depth_quote": _q(self.bid_depth_quote, "0.01"),
            "ask_depth_quote": _q(self.ask_depth_quote, "0.01"),
            "bid_levels": self.bid_levels,
            "ask_levels": self.ask_levels,
        }


def liquidity_metrics(book: PerpBook, band_bps: Decimal = Decimal(50)) -> LiquidityMetrics:
    bb, ba = book.best_bid, book.best_ask
    mid = spread = spread_bps = None
    bid_depth = ask_depth = Decimal(0)
    if bb and ba:
        mid = (bb.price + ba.price) / 2
        spread = ba.price - bb.price
        spread_bps = spread / mid * BPS
        lo, hi = mid * (1 - band_bps / BPS), mid * (1 + band_bps / BPS)
        bid_depth = sum((lv.price * lv.quantity for lv in book.bids if lv.price >= lo), Decimal(0))
        ask_depth = sum((lv.price * lv.quantity for lv in book.asks if lv.price <= hi), Decimal(0))
    return LiquidityMetrics(
        best_bid=bb.price if bb else None,
        best_ask=ba.price if ba else None,
        mid=mid,
        spread=spread,
        spread_bps=spread_bps,
        band_bps=band_bps,
        bid_depth_quote=bid_depth,
        ask_depth_quote=ask_depth,
        bid_levels=len(book.bids),
        ask_levels=len(book.asks),
    )


# --------------------------------------------------------------------------- execution
@dataclass(frozen=True)
class ExecutionEstimate:
    """Size-aware taker fill estimate from the observed book (NOT an actual fill)."""

    side: PerpSide
    requested_qty: Decimal
    filled_qty: Decimal
    fully_filled: bool
    avg_price: Decimal | None
    worst_price: Decimal | None
    mid: Decimal | None
    notional: Decimal
    spread_cost_bps: Decimal | None  # best price vs mid
    impact_bps: Decimal | None  # average fill vs best price
    slippage_bps: Decimal | None  # average fill vs mid (= spread cost + impact)
    fee_bps: Decimal
    total_cost_bps: Decimal | None  # slippage + fee
    total_cost_quote: Decimal | None
    levels_used: int
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": "ESTIMATE (book walk, not a fill)",
            "side": self.side.value,
            "requested_qty": str(self.requested_qty),
            "filled_qty": str(self.filled_qty),
            "fully_filled": self.fully_filled,
            "avg_price": _q(self.avg_price, "0.00000001"),
            "worst_price": _q(self.worst_price, "0.00000001"),
            "mid": _q(self.mid, "0.00000001"),
            "notional": _q(self.notional, "0.0001"),
            "spread_cost_bps": _bps(self.spread_cost_bps),
            "impact_bps": _bps(self.impact_bps),
            "slippage_bps": _bps(self.slippage_bps),
            "fee_bps": str(self.fee_bps),
            "total_cost_bps": _bps(self.total_cost_bps),
            "total_cost_quote": _q(self.total_cost_quote, "0.000001"),
            "levels_used": self.levels_used,
            "assumptions": list(self.assumptions),
        }


def walk_book(book: PerpBook, side: PerpSide, quantity: Decimal, fee_bps: Decimal = Decimal(0)) -> ExecutionEstimate:
    """Walk the opposite side of the book for a taker of ``quantity`` base units."""
    levels: tuple[BookLevel, ...] = book.asks if side is PerpSide.LONG else book.bids
    bb, ba = book.best_bid, book.best_ask
    mid = (bb.price + ba.price) / 2 if bb and ba else None
    remaining = quantity
    cost = Decimal(0)
    worst = None
    used = 0
    for lv in levels:
        if remaining <= 0:
            break
        take = min(remaining, lv.quantity)
        cost += take * lv.price
        remaining -= take
        worst = lv.price
        used += 1
    filled = quantity - remaining
    avg = cost / filled if filled > 0 else None
    best = levels[0].price if levels else None
    spread_cost = impact = slippage = total_bps = total_quote = None
    if avg is not None and best is not None:
        impact = abs(avg - best) / best * BPS
    if mid is not None and best is not None:
        spread_cost = abs(best - mid) / mid * BPS
    if mid is not None and avg is not None:
        slippage = abs(avg - mid) / mid * BPS
        total_bps = slippage + fee_bps
        total_quote = cost * total_bps / BPS
    return ExecutionEstimate(
        side=side,
        requested_qty=quantity,
        filled_qty=filled,
        fully_filled=remaining <= 0,
        avg_price=avg,
        worst_price=worst,
        mid=mid,
        notional=cost,
        spread_cost_bps=spread_cost,
        impact_bps=impact,
        slippage_bps=slippage,
        fee_bps=fee_bps,
        total_cost_bps=total_bps,
        total_cost_quote=total_quote,
        levels_used=used,
        assumptions=(
            "book is a point-in-time snapshot; it can move before a transaction lands",
            "taker fee from on-chain risk params; builder fees not included",
            "costs measured against the book mid",
        ),
    )


# --------------------------------------------------------------------------- volatility
@dataclass(frozen=True)
class VolatilityMetrics:
    status: str  # OK | INSUFFICIENT_DATA
    n_returns: int
    interval_sec: int
    gaps_skipped: int
    sigma_interval: Decimal | None
    sigma_annualized: Decimal | None
    note: str

    def sigma_over(self, hours: Decimal) -> Decimal | None:
        if self.sigma_interval is None:
            return None
        n = hours * 3600 / Decimal(self.interval_sec)
        return self.sigma_interval * n.sqrt()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "n_returns": self.n_returns,
            "interval_sec": self.interval_sec,
            "gaps_skipped": self.gaps_skipped,
            "sigma_interval": _q(self.sigma_interval, "0.000001"),
            "sigma_annualized": _q(self.sigma_annualized, "0.0001"),
            "sigma_24h": _q(self.sigma_over(Decimal(24)), "0.000001"),
            "note": self.note,
        }


def volatility_metrics(snap: PerpSnapshot) -> VolatilityMetrics:
    """Realized volatility of log returns between consecutive, gap-free perp candles.

    Pairs separated by a missing bucket are skipped (never interpolated). Fewer
    than ``MIN_VOL_RETURNS`` valid returns yields INSUFFICIENT_DATA — no fallback
    volatility is ever substituted.
    """
    interval = snap.candle_interval_seconds
    rets: list[Decimal] = []
    gaps = 0
    c = snap.candles
    for prev, cur in zip(c, c[1:], strict=False):
        if cur.bucket_start - prev.bucket_start != interval:
            gaps += 1
            continue
        if prev.close <= 0 or cur.close <= 0:
            continue
        rets.append((cur.close / prev.close).ln())
    if len(rets) < MIN_VOL_RETURNS:
        return VolatilityMetrics(
            "INSUFFICIENT_DATA",
            len(rets),
            interval,
            gaps,
            None,
            None,
            f"need >= {MIN_VOL_RETURNS} gap-free {interval}s returns, have {len(rets)}",
        )
    mean = sum(rets, Decimal(0)) / len(rets)
    var = sum(((r - mean) ** 2 for r in rets), Decimal(0)) / (len(rets) - 1)
    sigma = var.sqrt()
    annual = sigma * (SECONDS_PER_YEAR / Decimal(interval)).sqrt()
    return VolatilityMetrics(
        "OK",
        len(rets),
        interval,
        gaps,
        sigma,
        annual,
        f"sample stdev of {len(rets)} log returns of {interval}s perp-trade candles (DreamDEX book, not the index)",
    )


# --------------------------------------------------------------------------- margin / liquidation
@dataclass(frozen=True)
class MarginEstimate:
    side: PerpSide
    quantity: Decimal
    entry_price: Decimal
    notional: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal
    equity: Decimal | None
    effective_leverage: Decimal | None
    est_liquidation_price: Decimal | None
    liquidation_distance_pct: Decimal | None
    source: str = "ESTIMATE"
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": f"{self.source} — not the protocol's exact liquidation price",
            "side": self.side.value,
            "quantity": str(self.quantity),
            "entry_price": _q(self.entry_price, "0.00000001"),
            "notional": _q(self.notional, "0.0001"),
            "initial_margin": _q(self.initial_margin, "0.0001"),
            "maintenance_margin": _q(self.maintenance_margin, "0.0001"),
            "equity": _q(self.equity, "0.0001"),
            "effective_leverage": _q(self.effective_leverage, "0.0001"),
            "est_liquidation_price": _q(self.est_liquidation_price, "0.00000001"),
            "liquidation_distance_pct": _q(self.liquidation_distance_pct, "0.0001"),
            "assumptions": list(self.assumptions),
        }


def estimate_margin(
    side: PerpSide,
    quantity: Decimal,
    entry_price: Decimal,
    *,
    initial_margin_bps: Decimal,
    maintenance_margin_bps: Decimal,
    equity: Decimal | None,
    reference_price: Decimal | None = None,
) -> MarginEstimate:
    """Margin, effective leverage and an ESTIMATED liquidation price for one new position.

    Treats ``equity`` as backing only this position (no other positions, no funding,
    no fees). Liquidation when equity + PnL = maintenance margin at price P:
    long  P = (q*entry - E) / (q*(1 - mm));  short  P = (E + q*entry) / (q*(1 + mm)).
    """
    notional = quantity * entry_price
    im = notional * initial_margin_bps / BPS
    mm_frac = maintenance_margin_bps / BPS
    mm = notional * mm_frac
    lev = liq = dist = None
    if equity is not None and equity > 0 and quantity > 0:
        lev = notional / equity
        if side is PerpSide.LONG:
            liq = (quantity * entry_price - equity) / (quantity * (1 - mm_frac))
            liq = liq if liq > 0 else Decimal(0)
        else:
            liq = (equity + quantity * entry_price) / (quantity * (1 + mm_frac))
        ref = reference_price or entry_price
        dist = abs(liq - ref) / ref if ref > 0 else None
    return MarginEstimate(
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        notional=notional,
        initial_margin=im,
        maintenance_margin=mm,
        equity=equity,
        effective_leverage=lev,
        est_liquidation_price=liq,
        liquidation_distance_pct=dist,
        assumptions=(
            "equity backs only this position (cross-margin effects of other positions ignored)",
            "excludes funding accrual, fees, and the protocol's adverse-gap reserve",
            "liquidation when equity + unrealized PnL falls to maintenance margin",
        ),
    )


# --------------------------------------------------------------------------- assessment
class Category:
    REVIEW = "REVIEW"
    WATCH = "WATCH"
    HIGH_LIQUIDATION_RISK = "HIGH_LIQUIDATION_RISK"
    HIGH_EXECUTION_COST = "HIGH_EXECUTION_COST"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"


# Published ranking: lower rank sorts first; ties broken by lower round-trip cost.
CATEGORY_RANK = {
    Category.REVIEW: 0,
    Category.WATCH: 1,
    Category.HIGH_LIQUIDATION_RISK: 2,
    Category.HIGH_EXECUTION_COST: 3,
    Category.INSUFFICIENT_LIQUIDITY: 4,
    Category.INSUFFICIENT_DATA: 5,
    Category.STALE_DATA: 6,
}


@dataclass(frozen=True)
class AssessmentThresholds:
    max_snapshot_age_s: int = 30  # book/state older than this => STALE_DATA
    max_index_age_s: int = 120  # oracle index older than this => STALE_DATA
    reference_notional: Decimal = Decimal(100)  # quote units used to probe cost/liquidity
    liquidity_band_bps: Decimal = Decimal(50)  # depth counted within ±band of mid
    max_round_trip_cost_bps: Decimal = Decimal(30)  # entry+exit cost above this => HIGH_EXECUTION_COST
    analysis_leverage: Decimal = Decimal(1)  # effective leverage assumed for the liquidation probe
    horizon_hours: Decimal = Decimal(24)  # volatility horizon for the liquidation probe
    min_liquidation_z: Decimal = Decimal(3)  # liq distance < z * sigma(horizon) => HIGH_LIQUIDATION_RISK
    review_basis_bps: Decimal = Decimal(10)  # |mark-index| at/above this => REVIEW
    review_funding_annualized: Decimal = Decimal("0.20")  # |annualized funding| at/above this => REVIEW


@dataclass(frozen=True)
class MarketAssessment:
    snapshot: PerpSnapshot
    category: str
    reasons: tuple[str, ...]
    funding: FundingMetrics
    basis: BasisMetrics
    liquidity: LiquidityMetrics
    volatility: VolatilityMetrics
    entry_long: ExecutionEstimate | None
    entry_short: ExecutionEstimate | None
    round_trip_cost_bps: Decimal | None
    liquidation_probe: MarginEstimate | None
    liquidation_z: Decimal | None
    thresholds: AssessmentThresholds

    @property
    def rank_key(self) -> tuple[int, Decimal]:
        return (CATEGORY_RANK[self.category], self.round_trip_cost_bps or Decimal(10**9))

    def to_dict(self) -> dict[str, object]:
        m = self.snapshot.market
        return {
            "market": m.to_dict(),
            "source": self.snapshot.source.value,
            "captured_at": self.snapshot.captured_at,
            "category": self.category,
            "reasons": list(self.reasons),
            "observed": {
                "funding": self.funding.to_dict(),
                "basis": self.basis.to_dict(),
                "liquidity": self.liquidity.to_dict(),
                "volatility": self.volatility.to_dict(),
                "open_interest": str(self.snapshot.state.open_interest)
                if self.snapshot.state.open_interest is not None
                else None,
                "mark_price_ok": self.snapshot.state.mark_price_ok,
            },
            "execution_cost": {
                "reference_notional": str(self.thresholds.reference_notional),
                "entry_long": self.entry_long.to_dict() if self.entry_long else None,
                "entry_short": self.entry_short.to_dict() if self.entry_short else None,
                "round_trip_cost_bps": _bps(self.round_trip_cost_bps),
            },
            "risk": {
                "risk_params": {
                    "initial_margin_bps": str(self.snapshot.risk.initial_margin_bps),
                    "maintenance_margin_bps": str(self.snapshot.risk.maintenance_margin_bps),
                    "max_position_size": str(self.snapshot.risk.max_position_size),
                    "taker_fee_bps": str(self.snapshot.risk.taker_fee_bps),
                    "maker_fee_bps": str(self.snapshot.risk.maker_fee_bps),
                },
                "liquidation_probe": self.liquidation_probe.to_dict() if self.liquidation_probe else None,
                "liquidation_z": _q(self.liquidation_z, "0.01"),
            },
            "expected_edge": {
                "status": "NOT_ESTIMATED",
                "note": "no validated predictive model for perps; observations are not executable edge",
            },
            "warnings": list(self.snapshot.warnings),
        }


def assess_market(snap: PerpSnapshot, now: int, th: AssessmentThresholds | None = None) -> MarketAssessment:
    """Categorize one market with explicit, documented thresholds (first blocker wins)."""
    th = th or AssessmentThresholds()
    funding = funding_metrics(snap, now)
    basis = basis_metrics(snap, now)
    liq = liquidity_metrics(snap.book, th.liquidity_band_bps)
    vol = volatility_metrics(snap)
    fee = snap.risk.taker_fee_bps
    reasons: list[str] = []

    long_est = short_est = None
    round_trip = None
    probe = None
    z = None
    if liq.mid is not None:
        ref_qty = th.reference_notional / liq.mid
        long_est = walk_book(snap.book, PerpSide.LONG, ref_qty, fee)
        short_est = walk_book(snap.book, PerpSide.SHORT, ref_qty, fee)
        if long_est.total_cost_bps is not None and short_est.total_cost_bps is not None:
            round_trip = long_est.total_cost_bps + short_est.total_cost_bps
        if snap.state.mark_price is not None and th.analysis_leverage > 0:
            probe = estimate_margin(
                PerpSide.LONG,
                ref_qty,
                snap.state.mark_price,
                initial_margin_bps=snap.risk.initial_margin_bps,
                maintenance_margin_bps=snap.risk.maintenance_margin_bps,
                equity=th.reference_notional / th.analysis_leverage,
            )
            sig = vol.sigma_over(th.horizon_hours)
            if probe.liquidation_distance_pct is not None and sig:
                z = probe.liquidation_distance_pct / sig

    snap_age = max(0, now - snap.captured_at)
    stale: list[str] = []
    if not snap.state.mark_price_ok:
        stale.append("mark feed reports stale (markPriceOk=false)")
    if snap_age > th.max_snapshot_age_s:
        stale.append(f"snapshot age {snap_age}s > {th.max_snapshot_age_s}s")
    if basis.index_age_s is not None and basis.index_age_s > th.max_index_age_s:
        stale.append(f"index age {basis.index_age_s}s > {th.max_index_age_s}s")
    missing = [*basis.missing]
    if not snap.book.bids:
        missing.append("no bids")
    if not snap.book.asks:
        missing.append("no asks")

    if stale:
        category = Category.STALE_DATA
        reasons += stale
    elif missing:
        category = Category.INSUFFICIENT_DATA
        reasons.append("missing: " + ", ".join(missing))
    elif not (long_est and short_est and long_est.fully_filled and short_est.fully_filled) or (
        min(liq.bid_depth_quote, liq.ask_depth_quote) < th.reference_notional
    ):
        category = Category.INSUFFICIENT_LIQUIDITY
        reasons.append(
            f"reference {th.reference_notional} {snap.market.quote_symbol} not fully fillable within "
            f"±{th.liquidity_band_bps}bps (bid depth {_q(liq.bid_depth_quote, '0.01')}, "
            f"ask depth {_q(liq.ask_depth_quote, '0.01')})"
        )
    elif round_trip is not None and round_trip > th.max_round_trip_cost_bps:
        category = Category.HIGH_EXECUTION_COST
        reasons.append(f"round-trip cost {_bps(round_trip)}bps > {th.max_round_trip_cost_bps}bps")
    elif z is not None and z < th.min_liquidation_z:
        category = Category.HIGH_LIQUIDATION_RISK
        reasons.append(
            f"est. liquidation {_q(z, '0.01')}σ away over {th.horizon_hours}h at "
            f"{th.analysis_leverage}x < {th.min_liquidation_z}σ"
        )
    else:
        notable = []
        if basis.bps is not None and abs(basis.bps) >= th.review_basis_bps:
            notable.append(f"|basis| {_bps(abs(basis.bps))}bps >= {th.review_basis_bps}bps")
        if funding.annualized is not None and abs(funding.annualized) >= th.review_funding_annualized:
            notable.append(
                f"|funding| {_q(abs(funding.annualized) * 100, '0.01')}%/yr >= "
                f"{th.review_funding_annualized * 100}%/yr ({funding.direction})"
            )
        category = Category.REVIEW if notable else Category.WATCH
        reasons += notable or ["tradable conditions; nothing unusual against thresholds"]
    if vol.status != "OK":
        reasons.append(f"volatility INSUFFICIENT_DATA: {vol.note}; liquidation risk not assessed")
    if funding.stale:
        reasons.append("funding settlement is stale (> 2 intervals since last update)")

    return MarketAssessment(
        snapshot=snap,
        category=category,
        reasons=tuple(reasons),
        funding=funding,
        basis=basis,
        liquidity=liq,
        volatility=vol,
        entry_long=long_est,
        entry_short=short_est,
        round_trip_cost_bps=round_trip,
        liquidation_probe=probe,
        liquidation_z=z,
        thresholds=th,
    )


def rank(assessments: list[MarketAssessment]) -> list[MarketAssessment]:
    return sorted(assessments, key=lambda a: a.rank_key)
