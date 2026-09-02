"""Short-horizon BTC/ETH event-contract strategy.

Wires an :class:`UnderlyingSnapshot` and an :class:`EventContractMarket` into
the deterministic core pipeline (probability -> edge -> risk -> signal). All
numbers come from the quantitative model, never an LLM.
"""

from __future__ import annotations

from decimal import Decimal

from ..core.probability import estimate_up_probability, volatility_from_closes
from ..core.risk import RiskEngine
from ..core.signal import Signal, evaluate_market
from ..core.types import (
    EventContractBook,
    EventContractMarket,
    ProbabilityEstimate,
    UnderlyingSnapshot,
)

DEFAULT_FEE_BUFFER_BPS = Decimal("50")
DEFAULT_SLIPPAGE_BUFFER_BPS = Decimal("50")


def _confidence(
    *,
    has_vol: bool,
    sample_size: int,
    data_age: int,
    time_to_expiry: int | None,
) -> Decimal:
    if not has_vol:
        return Decimal(0)
    sample_factor = min(Decimal(1), max(Decimal(0), Decimal(sample_size - 2) / Decimal(28)))
    if data_age <= 15:
        fresh_factor = Decimal(1)
    elif data_age <= 60:
        fresh_factor = Decimal("0.5")
    else:
        fresh_factor = Decimal("0.1")
    if time_to_expiry is None or time_to_expiry <= 0:
        time_factor = Decimal(0)
    elif 60 <= time_to_expiry <= 1200:
        time_factor = Decimal(1)
    else:
        time_factor = Decimal("0.5")
    return (sample_factor * fresh_factor * time_factor).quantize(Decimal("0.0001"))


def build_probability(
    market: EventContractMarket,
    underlying: UnderlyingSnapshot,
    *,
    now: int,
) -> ProbabilityEstimate:
    tte = market.time_to_expiry(now)
    vol = volatility_from_closes(list(underlying.closes), underlying.interval_seconds)
    confidence = _confidence(
        has_vol=vol is not None,
        sample_size=len(underlying.closes),
        data_age=underlying.received_at and (now - underlying.received_at) or 0,
        time_to_expiry=tte,
    )
    if market.opening_reference is None or market.opening_reference <= 0 or vol is None or tte is None:
        # Cannot form a defensible estimate; return a neutral one with zero
        # confidence rather than inventing a probability. Risk -> LOW_CONFIDENCE.
        reason = (
            "opening reference unavailable"
            if (market.opening_reference is None or market.opening_reference <= 0)
            else "insufficient recent data to estimate volatility"
            if vol is None
            else "no time-to-expiry available"
        )
        return ProbabilityEstimate(
            p_up=Decimal("0.5"),
            p_down=Decimal("0.5"),
            confidence=Decimal(0),
            model_version="gauss-logreturn-v1",
            inputs={
                "opening_reference": str(market.opening_reference),
                "current_price": str(underlying.price),
                "time_to_expiry": str(tte),
            },
            explanation=f"No quantitative estimate: {reason}. (Not an LLM guess.)",
        )
    return estimate_up_probability(
        current_price=underlying.price,
        opening_price=market.opening_reference,
        volatility_per_sqrt_sec=vol,
        time_remaining_seconds=tte,
        confidence=confidence,
        sample_size=len(underlying.closes),
    )


def build_event_signal(
    market: EventContractMarket,
    book: EventContractBook,
    underlying: UnderlyingSnapshot,
    *,
    size: Decimal,
    now: int,
    risk_engine: RiskEngine,
    fee_buffer_bps: Decimal = DEFAULT_FEE_BUFFER_BPS,
    slippage_buffer_bps: Decimal = DEFAULT_SLIPPAGE_BUFFER_BPS,
    existing_market_notional: Decimal = Decimal(0),
    existing_total_notional: Decimal = Decimal(0),
) -> Signal:
    probability = build_probability(market, underlying, now=now)
    return evaluate_market(
        market,
        probability,
        book.up.asks,
        book.down.asks,
        size=size,
        now=now,
        book_captured_at=book.captured_at,
        risk_engine=risk_engine,
        fee_buffer_bps=fee_buffer_bps,
        slippage_buffer_bps=slippage_buffer_bps,
        external_obs=underlying.as_observation(),
        existing_market_notional=existing_market_notional,
        existing_total_notional=existing_total_notional,
    )
