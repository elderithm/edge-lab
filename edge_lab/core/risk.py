"""Dedicated risk engine. Every execution must pass through here.

Risk checks are not scattered across UI/CLI code. The engine takes the model
probability, the executable edge, market lifecycle/freshness, and exposure, and
returns an auditable list of checks plus a single decided :class:`SignalState`.
It also caps size — the maximum position always overrides strategy output.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .edge import EdgeBreakdown
from .types import EventContractMarket, MarketStatus, Observation, ProbabilityEstimate, Side, SignalState


@dataclass(frozen=True)
class RiskConfig:
    min_edge_bps: Decimal = Decimal("150")  # conservative default
    min_confidence: Decimal = Decimal("0.35")
    min_time_to_expiry_seconds: int = 45
    max_price_age_seconds: int = 30
    max_market_data_age_seconds: int = 20
    max_slippage_bps: Decimal = Decimal("300")
    max_position_per_market: Decimal = Decimal("25")  # collateral notional
    max_total_exposure: Decimal = Decimal("100")  # collateral notional


@dataclass(frozen=True)
class RiskCheckResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class RiskAssessment:
    state: SignalState
    side: Side | None
    checks: list[RiskCheckResult]
    allowed_size: Decimal
    allowed_notional: Decimal
    price: Decimal | None  # executable price of the chosen side
    edge_bps: Decimal | None

    @property
    def is_actionable(self) -> bool:
        return self.state in (SignalState.BUY_UP, SignalState.BUY_DOWN) and self.allowed_size > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "side": self.side.value if self.side else None,
            "allowed_size": str(self.allowed_size),
            "allowed_notional": str(self.allowed_notional),
            "price": str(self.price) if self.price is not None else None,
            "edge_bps": str(self.edge_bps) if self.edge_bps is not None else None,
            "checks": [c.to_dict() for c in self.checks],
        }


class RiskEngine:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def evaluate(
        self,
        *,
        market: EventContractMarket,
        prob: ProbabilityEstimate,
        edge: EdgeBreakdown,
        now: int,
        book_captured_at: int,
        requested_size: Decimal,
        external_obs: Observation | None = None,
        existing_market_notional: Decimal = Decimal(0),
        existing_total_notional: Decimal = Decimal(0),
    ) -> RiskAssessment:
        cfg = self.config
        checks: list[RiskCheckResult] = []

        def add(name: str, passed: bool, detail: str) -> None:
            checks.append(RiskCheckResult(name, passed, detail))

        # --- lifecycle ---
        trading = market.status == MarketStatus.TRADING
        add("market_trading", trading, f"status={market.status.value}")

        # --- freshness ---
        data_age = now - book_captured_at
        data_fresh = data_age <= cfg.max_market_data_age_seconds
        add("market_data_fresh", data_fresh, f"age={data_age}s <= {cfg.max_market_data_age_seconds}s")

        price_fresh = True
        if external_obs is not None:
            p_age = external_obs.age_seconds(now)
            price_fresh = p_age <= cfg.max_price_age_seconds
            add(
                "external_price_fresh",
                price_fresh,
                f"age={p_age}s <= {cfg.max_price_age_seconds}s ({external_obs.source})",
            )
        else:
            add("external_price_fresh", True, "no external observation supplied")

        # --- timing ---
        tte = market.time_to_expiry(now)
        tte_ok = tte is not None and tte >= cfg.min_time_to_expiry_seconds
        add("time_to_expiry", tte_ok, f"tte={tte}s >= {cfg.min_time_to_expiry_seconds}s")

        # --- probability validity + confidence ---
        add("probability_valid", prob.is_valid(), f"pUp={prob.p_up} pDown={prob.p_down}")
        conf_ok = prob.confidence >= cfg.min_confidence
        add("confidence", conf_ok, f"confidence={prob.confidence} >= {cfg.min_confidence}")

        best = edge.best()
        # --- liquidity ---
        liquidity_ok = best.fully_filled and best.executable_edge_bps is not None
        add(
            "liquidity",
            liquidity_ok,
            f"best={best.side.value} depth={best.available_depth} fully_filled={best.fully_filled}",
        )
        # --- slippage ---
        slippage_ok = best.slippage_bps <= cfg.max_slippage_bps
        add("slippage", slippage_ok, f"slippage={best.slippage_bps}bps <= {cfg.max_slippage_bps}bps")

        # --- edge threshold ---
        edge_bps = best.executable_edge_bps
        edge_ok = edge_bps is not None and edge_bps >= cfg.min_edge_bps
        add("edge_threshold", edge_ok, f"executable_edge={edge_bps}bps >= {cfg.min_edge_bps}bps")

        price = best.executable_ask
        # --- exposure caps (always override strategy) ---
        allowed_size = Decimal(0)
        allowed_notional = Decimal(0)
        if price is not None and price > 0:
            requested_notional = requested_size * price
            per_market_room = max(Decimal(0), cfg.max_position_per_market - existing_market_notional)
            total_room = max(Decimal(0), cfg.max_total_exposure - existing_total_notional)
            allowed_notional = min(requested_notional, per_market_room, total_room)
            allowed_size = (allowed_notional / price) if price > 0 else Decimal(0)
        exposure_ok = allowed_size > 0
        add(
            "exposure_cap",
            exposure_ok,
            f"allowed_notional={allowed_notional} (per_market_left="
            f"{max(Decimal(0), cfg.max_position_per_market - existing_market_notional)}, "
            f"total_left={max(Decimal(0), cfg.max_total_exposure - existing_total_notional)})",
        )

        # --- decide the single signal state (most specific blocker first) ---
        if not trading:
            state = SignalState.MARKET_NOT_TRADING
        elif not (data_fresh and price_fresh):
            state = SignalState.DATA_STALE
        elif not tte_ok:
            state = SignalState.TOO_CLOSE_TO_EXPIRY
        elif not conf_ok or not prob.is_valid():
            state = SignalState.LOW_CONFIDENCE
        elif not liquidity_ok or not slippage_ok or not exposure_ok:
            state = SignalState.INSUFFICIENT_LIQUIDITY
        elif not edge_ok:
            state = SignalState.NO_EDGE
        else:
            state = SignalState.BUY_UP if best.side == Side.UP else SignalState.BUY_DOWN

        side = best.side if state in (SignalState.BUY_UP, SignalState.BUY_DOWN) else None
        if side is None:
            allowed_size = Decimal(0)
            allowed_notional = Decimal(0)

        return RiskAssessment(
            state=state,
            side=side,
            checks=checks,
            allowed_size=allowed_size,
            allowed_notional=allowed_notional,
            price=price,
            edge_bps=edge_bps,
        )
