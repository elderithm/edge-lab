"""Compose probability + executable edge + risk into an explainable signal.

This is the deterministic core pipeline entry point:

    market data -> probability -> edge detector -> risk engine -> signal

It never places orders; execution lives in the venue/execution layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .edge import EdgeBreakdown, compute_edge
from .risk import RiskAssessment, RiskEngine
from .types import (
    EventContractMarket,
    Observation,
    OrderBookLevel,
    ProbabilityEstimate,
    SignalState,
)


@dataclass(frozen=True)
class Signal:
    market: EventContractMarket
    probability: ProbabilityEstimate
    edge: EdgeBreakdown
    risk: RiskAssessment
    rank_score: Decimal
    explanation: str

    @property
    def state(self) -> SignalState:
        return self.risk.state

    def to_dict(self) -> dict[str, object]:
        return {
            "market": {
                "venue": self.market.venue,
                "market_id": self.market.market_id,
                "key": self.market.key,
                "asset": self.market.asset,
                "symbol": self.market.symbol,
                "status": self.market.status.value,
                "window": self.market.window_label,
                "expiry": self.market.expiry,
                "opening_reference": (
                    str(self.market.opening_reference) if self.market.opening_reference is not None else None
                ),
            },
            "state": self.state.value,
            "rank_score": str(self.rank_score),
            "probability": self.probability.to_dict(),
            "edge": self.edge.to_dict(),
            "risk": self.risk.to_dict(),
            "explanation": self.explanation,
        }


def _rank_score(edge: EdgeBreakdown, prob: ProbabilityEstimate, risk: RiskAssessment) -> Decimal:
    """Risk-adjusted rank: edge x confidence x liquidity factor.

    Zero unless the signal is actionable, so a big raw edge with stale/thin/
    low-confidence inputs never ranks first.
    """
    if not risk.is_actionable or risk.edge_bps is None:
        return Decimal(0)
    edge_pct = risk.edge_bps / Decimal(100)
    requested_notional = edge.size * (risk.price or Decimal(0))
    liquidity_factor = Decimal(1)
    if requested_notional > 0:
        liquidity_factor = min(Decimal(1), risk.allowed_notional / requested_notional)
    return (edge_pct * prob.confidence * liquidity_factor).quantize(Decimal("0.0001"))


def evaluate_market(
    market: EventContractMarket,
    probability: ProbabilityEstimate,
    up_asks: Sequence[OrderBookLevel],
    down_asks: Sequence[OrderBookLevel],
    *,
    size: Decimal,
    now: int,
    book_captured_at: int,
    risk_engine: RiskEngine,
    fee_buffer_bps: Decimal,
    slippage_buffer_bps: Decimal,
    external_obs: Observation | None = None,
    existing_market_notional: Decimal = Decimal(0),
    existing_total_notional: Decimal = Decimal(0),
) -> Signal:
    edge = compute_edge(
        probability,
        up_asks,
        down_asks,
        size=size,
        fee_buffer_bps=fee_buffer_bps,
        slippage_buffer_bps=slippage_buffer_bps,
    )
    risk = risk_engine.evaluate(
        market=market,
        prob=probability,
        edge=edge,
        now=now,
        book_captured_at=book_captured_at,
        requested_size=size,
        external_obs=external_obs,
        existing_market_notional=existing_market_notional,
        existing_total_notional=existing_total_notional,
    )
    best = edge.best()
    if risk.is_actionable:
        headline = (
            f"{risk.state.value}: model P({best.side.value})={best.model_prob} vs executable "
            f"{best.side.value} ask {best.executable_ask} -> {risk.edge_bps}bps executable edge "
            f"(after {edge.buffer_bps}bps buffers)."
        )
    else:
        headline = f"{risk.state.value}: no actionable edge ({market.symbol})."
    explanation = f"{headline} {probability.explanation} (Model estimate, not a profit guarantee.)"
    return Signal(
        market=market,
        probability=probability,
        edge=edge,
        risk=risk,
        rank_score=_rank_score(edge, probability, risk),
        explanation=explanation,
    )
