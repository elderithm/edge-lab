"""Perps risk engine: hard pre-trade controls with an explicit reason for every block.

Every Perps order — paper or testnet — is evaluated here. Only an approved
:class:`PerpsRiskDecision` can mint a :class:`RiskApproval`, and the adapter's
``place_order`` accepts nothing else, so a blocked order can never reach the SDK
write method. Approvals expire quickly so they cannot be replayed against stale
data.

Effective leverage is hard-capped at 1x (notional <= equity), following the
repository rule against leverage: perps are used here as a research venue, and
leverage scenarios are shown only analytically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from ..errors import ConfigError
from ..venues.dreamdex_perps.config import HIDEKI_CHAIN_ID, PerpsConfig
from ..venues.dreamdex_perps.models import PRICE_DECIMALS, PerpMarket, PerpSide, PerpSnapshot, plain, scale_down
from .analytics import BPS, ExecutionEstimate, MarginEstimate, estimate_margin, liquidity_metrics, walk_book

HARD_MAX_EFFECTIVE_LEVERAGE = Decimal(1)
APPROVAL_TTL_SECONDS = 60
ORDER_TYPES = ("ioc", "limit", "post_only")


@dataclass(frozen=True)
class PerpsRiskConfig:
    max_effective_leverage: Decimal = Decimal(1)  # notional / equity, after the trade
    max_position_notional: Decimal = Decimal(100)  # per market, quote units
    max_total_exposure: Decimal = Decimal(250)  # all markets, quote units
    max_slippage_bps: Decimal = Decimal(25)  # avg fill vs mid, and the IOC limit-price bound
    limit_buffer_bps: Decimal = Decimal(5)  # IOC limit = worst walked level + buffer (room for book moves)
    max_data_age_s: int = 30
    max_index_age_s: int = 120
    min_free_margin_ratio: Decimal = Decimal("0.25")  # equity left after initial margin / equity
    min_liquidation_distance_pct: Decimal = Decimal("0.20")  # |liq - mark| / mark

    def __post_init__(self) -> None:
        if self.max_effective_leverage > HARD_MAX_EFFECTIVE_LEVERAGE:
            raise ConfigError(
                f"max_effective_leverage {self.max_effective_leverage} exceeds the hard cap "
                f"{HARD_MAX_EFFECTIVE_LEVERAGE}x (no leverage in Edge Lab)"
            )
        if self.max_effective_leverage <= 0:
            raise ConfigError("max_effective_leverage must be > 0")


@dataclass(frozen=True)
class RiskCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class PerpOrderIntent:
    market_id: str
    symbol: str
    side: PerpSide
    quantity: Decimal
    quantity_raw: int
    limit_price: Decimal
    limit_price_raw: int
    order_type: str
    mode: str  # "paper" | "testnet"

    def to_dict(self) -> dict[str, object]:
        return {
            "market_id": self.market_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "is_bid": self.side.is_bid,
            "quantity": str(self.quantity),
            "quantity_raw": str(self.quantity_raw),
            "limit_price": str(self.limit_price),
            "limit_price_raw": str(self.limit_price_raw),
            "order_type": self.order_type,
            "mode": self.mode,
        }


_ISSUER = object()  # only this module can mint approvals


@dataclass(frozen=True)
class RiskApproval:
    intent: PerpOrderIntent
    issued_at: float
    _token: object = field(repr=False, compare=False)

    def is_valid(self, now: float | None = None) -> bool:
        t = time.time() if now is None else now
        return self._token is _ISSUER and (t - self.issued_at) <= APPROVAL_TTL_SECONDS


@dataclass(frozen=True)
class PerpsRiskDecision:
    approved: bool
    mode: str
    checks: tuple[RiskCheck, ...]
    intent: PerpOrderIntent | None
    execution: ExecutionEstimate | None
    margin: MarginEstimate | None
    official_preview: dict[str, Any] | None = None

    @property
    def blocked_reasons(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]

    def approval(self) -> RiskApproval:
        if not self.approved or self.intent is None:
            from ..venues.dreamdex_perps.errors import RiskBlocked

            raise RiskBlocked("order blocked by risk engine: " + " | ".join(self.blocked_reasons))
        return RiskApproval(intent=self.intent, issued_at=time.time(), _token=_ISSUER)

    def to_dict(self) -> dict[str, object]:
        return {
            "approved": self.approved,
            "mode": self.mode,
            "blocked_reasons": self.blocked_reasons,
            "checks": [c.to_dict() for c in self.checks],
            "intent": self.intent.to_dict() if self.intent else None,
            "execution_estimate": self.execution.to_dict() if self.execution else None,
            "margin_estimate": self.margin.to_dict() if self.margin else None,
            "official_preview": self.official_preview,
        }


def round_to_tick(price: Decimal, market: PerpMarket, *, up: bool) -> Decimal:
    tick = market.tick_size
    steps = (price / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return steps * tick


def quantity_problems(market: PerpMarket, quantity: Decimal) -> list[str]:
    out = []
    if quantity <= 0:
        return ["quantity must be > 0"]
    if quantity % market.lot_size != 0:
        out.append(f"quantity {quantity} is not a multiple of lot size {market.lot_size}")
    if quantity < market.min_quantity:
        out.append(f"quantity {quantity} is below minimum {market.min_quantity}")
    if quantity.as_tuple().exponent < -market.base_decimals:  # type: ignore[operator]
        out.append(f"quantity {quantity} has more than {market.base_decimals} decimals")
    return out


class PerpsRiskEngine:
    def __init__(self, config: PerpsRiskConfig | None = None) -> None:
        self.config = config or PerpsRiskConfig()

    def evaluate(
        self,
        snap: PerpSnapshot,
        side: PerpSide,
        quantity: Decimal,
        *,
        now: int,
        mode: str = "paper",
        equity: Decimal | None,
        existing_market_notional: Decimal = Decimal(0),
        existing_total_notional: Decimal = Decimal(0),
        existing_initial_margin: Decimal = Decimal(0),
        order_type: str = "ioc",
        limit_price: Decimal | None = None,
        perps_config: PerpsConfig | None = None,
        official_preview: dict[str, Any] | None = None,
    ) -> PerpsRiskDecision:
        cfg = self.config
        m = snap.market
        checks: list[RiskCheck] = []

        def add(name: str, passed: bool, detail: str) -> None:
            checks.append(RiskCheck(name, passed, detail))

        # --- execution mode (testnet-only enforcement) ---
        if mode == "testnet":
            blockers = perps_config.write_blockers() if perps_config else ["no perps config supplied"]
            add("execution_mode", not blockers, "; ".join(blockers) or "TRADING_MODE=testnet, NETWORK=hideki-testnet")
            add("chain_id", m.chain_id == HIDEKI_CHAIN_ID, f"market chain {m.chain_id} == Hideki {HIDEKI_CHAIN_ID}")
            add("live_data", snap.source.value == "LIVE_TESTNET", f"source={snap.source.value}")
        elif mode == "paper":
            add("execution_mode", True, "paper (simulated; nothing is signed)")
        else:
            add("execution_mode", False, f"unsupported mode '{mode}' (paper|testnet; mainnet perps disabled)")
        add("order_type", order_type in ORDER_TYPES, f"order_type={order_type} in {ORDER_TYPES}")

        # --- market status / freshness ---
        add("mark_price_ok", snap.state.mark_price_ok and snap.state.mark_price is not None, "mark feed live")
        age = max(0, now - snap.captured_at)  # bridge clock may run ahead of `now` by a second
        add("data_fresh", age <= cfg.max_data_age_s, f"snapshot age {age}s <= {cfg.max_data_age_s}s")
        idx_age = None if snap.state.index_updated_at is None else max(0, now - snap.state.index_updated_at)
        add(
            "index_fresh",
            idx_age is not None and idx_age <= cfg.max_index_age_s,
            f"index age {idx_age}s <= {cfg.max_index_age_s}s",
        )

        # --- precision (lot / min / decimals) ---
        qp = quantity_problems(m, quantity)
        add("quantity_precision", not qp, "; ".join(qp) or f"lot {plain(m.lot_size)}, min {plain(m.min_quantity)}")

        # --- liquidity / slippage from a fresh book walk ---
        est = walk_book(snap.book, side, quantity, snap.risk.taker_fee_bps)
        add(
            "liquidity",
            est.fully_filled,
            f"book fills {est.filled_qty}/{quantity} over {est.levels_used} levels",
        )
        slip_ok = est.slippage_bps is not None and est.slippage_bps <= cfg.max_slippage_bps
        add("slippage", slip_ok, f"avg-vs-mid {_r(est.slippage_bps)}bps <= {cfg.max_slippage_bps}bps")

        # --- limit price: derived from the walk (IOC) or user-supplied, tick-aligned, bounded ---
        intent = None
        mid = liquidity_metrics(snap.book).mid
        if limit_price is None and est.worst_price is not None:
            buf = cfg.limit_buffer_bps / BPS
            raw_limit = est.worst_price * (1 + buf) if side is PerpSide.LONG else est.worst_price * (1 - buf)
            limit_price = round_to_tick(raw_limit, m, up=side is PerpSide.LONG).normalize()
        tick_ok = limit_price is not None and limit_price > 0 and limit_price % m.tick_size == 0
        add(
            "price_precision",
            tick_ok,
            f"limit {plain(limit_price) if limit_price is not None else None} on tick {plain(m.tick_size)}",
        )
        bound_ok = False
        if limit_price is not None and mid:
            dev = (limit_price - mid) / mid * BPS * side.sign
            bound_ok = dev <= cfg.max_slippage_bps
            add("limit_price_bound", bound_ok, f"limit {_r(dev)}bps through mid <= {cfg.max_slippage_bps}bps")
        else:
            add("limit_price_bound", False, "no limit price or no mid")

        # --- exposure caps ---
        price_for_notional = est.avg_price or limit_price or Decimal(0)
        notional = quantity * price_for_notional
        mkt_after = existing_market_notional + notional
        tot_after = existing_total_notional + notional
        add(
            "position_notional",
            mkt_after <= cfg.max_position_notional,
            f"{_r(mkt_after)} <= {cfg.max_position_notional} in this market",
        )
        add("total_exposure", tot_after <= cfg.max_total_exposure, f"{_r(tot_after)} <= {cfg.max_total_exposure}")
        protocol_cap = snap.risk.max_position_size
        add(
            "protocol_position_cap",
            protocol_cap <= 0 or quantity <= protocol_cap,
            f"{quantity} <= per-account cap {plain(protocol_cap)}",
        )

        # --- margin / leverage / liquidation ---
        margin = None
        if equity is None or equity <= 0:
            add("effective_leverage", False, "account equity unknown or zero; leverage cannot be bounded")
            add("available_margin", False, "account equity unknown or zero")
        else:
            lev = tot_after / equity
            add(
                "effective_leverage",
                lev <= cfg.max_effective_leverage,
                f"{_r(lev)}x <= {cfg.max_effective_leverage}x (total notional / equity)",
            )
            im_new = notional * snap.risk.initial_margin_bps / BPS
            free = (equity - existing_initial_margin - im_new) / equity
            add(
                "available_margin",
                free >= cfg.min_free_margin_ratio,
                f"free margin {_r(free * 100)}% >= {cfg.min_free_margin_ratio * 100}% of equity",
            )
            if price_for_notional > 0:
                margin = estimate_margin(
                    side,
                    quantity,
                    price_for_notional,
                    initial_margin_bps=snap.risk.initial_margin_bps,
                    maintenance_margin_bps=snap.risk.maintenance_margin_bps,
                    equity=equity - existing_initial_margin,
                    reference_price=snap.state.mark_price,
                )
        liq_dist, liq_src = self._liquidation_distance(snap, margin, official_preview)
        add(
            "liquidation_distance",
            liq_dist is not None and liq_dist >= cfg.min_liquidation_distance_pct,
            f"{liq_src}: {_r(liq_dist * 100) if liq_dist is not None else '?'}% >= "
            f"{cfg.min_liquidation_distance_pct * 100}% from mark",
        )

        # --- official protocol sizing (testnet only; needs an account address) ---
        if mode == "testnet":
            self._official_checks(add, official_preview, m, quantity)

        if tick_ok and limit_price is not None and not qp:
            intent = PerpOrderIntent(
                market_id=m.market_id,
                symbol=m.symbol,
                side=side,
                quantity=quantity,
                quantity_raw=m.quantity_to_raw(quantity),
                limit_price=limit_price,
                limit_price_raw=m.price_to_raw(limit_price),
                order_type=order_type,
                mode=mode,
            )
        approved = all(c.passed for c in checks) and intent is not None
        return PerpsRiskDecision(approved, mode, tuple(checks), intent, est, margin, official_preview)

    @staticmethod
    def _liquidation_distance(
        snap: PerpSnapshot, margin: MarginEstimate | None, preview: dict[str, Any] | None
    ) -> tuple[Decimal | None, str]:
        mark = snap.state.mark_price
        liq = (preview or {}).get("liquidation") or {}
        projected = liq.get("projectedLiquidationPrice") if liq.get("priceable") else None
        if projected not in (None, "") and mark:
            p = scale_down(int(projected), PRICE_DECIMALS)
            return abs(p - mark) / mark, "PROTOCOL previewPerpLiquidationPrice"
        # A null protocol projection is NOT read as "safe": fall back to the labelled estimate.
        if margin is not None and margin.liquidation_distance_pct is not None:
            return margin.liquidation_distance_pct, "ESTIMATE"
        return None, "UNKNOWN"

    @staticmethod
    def _official_checks(add: Any, preview: dict[str, Any] | None, m: PerpMarket, quantity: Decimal) -> None:
        if not preview or not preview.get("sizing"):
            add("official_sizing", False, "no official getMaxPerpOrderSize result (account address required)")
            return
        sizing = preview["sizing"]
        if not sizing.get("priceable"):
            add("official_sizing", False, "getMaxPerpOrderSize: market not priceable (stale mark)")
            return
        max_q = scale_down(int(sizing.get("maxQuantity", 0)), m.base_decimals)
        limited = sizing.get("limitedBy")
        add("voucher_allowed", limited != "voucherBlocked", f"limitedBy={limited}")
        add(
            "official_sizing",
            bool(sizing.get("placeable")) and quantity <= max_q,
            f"{quantity} <= official max {plain(max_q)} (limitedBy={limited}, placeable={sizing.get('placeable')})",
        )
        margin = preview.get("margin") or {}
        if margin.get("priceable"):
            iso = margin.get("isolationBlocked")
            add("isolation_ok", not iso, f"isolationBlocked={iso}")
            ok = margin.get("sufficient")
            add("official_margin", bool(ok), f"previewPerpOrderMargin.sufficient={ok}")
        if preview.get("precisionProblems"):
            add("bridge_precision", False, "; ".join(preview["precisionProblems"]))


def _r(v: Decimal | None) -> str:
    return "?" if v is None else str(v.quantize(Decimal("0.01")))
