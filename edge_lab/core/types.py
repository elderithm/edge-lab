"""Shared, venue-agnostic domain types for event-contract analysis.

Prices and probabilities are ``Decimal`` in [0, 1]; sizes are ``Decimal``
outcome-token units. Timestamps are UTC Unix seconds unless a field name says
milliseconds. Nothing here knows about DreamDEX or Polymarket specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    """Which side of a binary event contract."""

    UP = "UP"
    DOWN = "DOWN"


class MarketStatus(StrEnum):
    """Normalized event-contract lifecycle state.

    Venue-specific states are mapped into these by the venue adapter. Only
    ``TRADING`` permits order placement.
    """

    LISTED = "LISTED"
    TRADING = "TRADING"
    LOCKED = "LOCKED"
    SETTLING = "SETTLING"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"
    FINALIZED = "FINALIZED"
    UNKNOWN = "UNKNOWN"


class SignalState(StrEnum):
    """Explicit signal outcomes (never ambiguous 'GOOD'/'HOT')."""

    BUY_UP = "BUY_UP"
    BUY_DOWN = "BUY_DOWN"
    NO_EDGE = "NO_EDGE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    DATA_STALE = "DATA_STALE"
    MARKET_NOT_TRADING = "MARKET_NOT_TRADING"
    TOO_CLOSE_TO_EXPIRY = "TOO_CLOSE_TO_EXPIRY"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"


class TradingMode(StrEnum):
    PAPER = "paper"
    TESTNET = "testnet"
    MAINNET = "mainnet"


@dataclass(frozen=True)
class OrderBookLevel:
    """One resting price level. ``price`` is a probability in [0, 1]."""

    price: Decimal
    size: Decimal  # outcome-token units available at this level


@dataclass(frozen=True)
class OutcomeBook:
    """Executable book for one outcome (Up or Down), best price first."""

    side: Side
    asks: tuple[OrderBookLevel, ...]  # ascending price (best/cheapest first)
    bids: tuple[OrderBookLevel, ...]  # descending price (best/highest first)

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return self.bids[0] if self.bids else None


@dataclass(frozen=True)
class EventContractBook:
    """Both outcome books for a market, captured at a point in time."""

    up: OutcomeBook
    down: OutcomeBook
    captured_at: int  # unix seconds (local receive clock)


@dataclass(frozen=True)
class EventContractMarket:
    """Normalized DreamDEX/Polymarket event contract.

    Identity is ``(venue, market_id)`` — never a recycled pool address.
    """

    venue: str
    market_id: str  # canonical id (DreamDEX bytes32 marketId)
    asset: str  # "BTC" | "ETH"
    symbol: str  # human label, e.g. "BTC-...#/USDC"
    status: MarketStatus
    trading_start: int | None  # unix seconds
    expiry: int | None  # unix seconds (lock/settlement)
    opening_reference: Decimal | None  # settlement reference/opening price if known
    pool_address: str | None = None  # informational ONLY; not identity
    nonce: str | None = None
    window_label: str | None = None  # "15m" | "1h" ...

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.market_id}"

    def time_to_expiry(self, now: int) -> int | None:
        if self.expiry is None:
            return None
        return self.expiry - now


@dataclass(frozen=True)
class Observation:
    """An external data point with mandatory provenance and freshness."""

    source: str
    value: Decimal
    timestamp: int  # source event time, unix seconds
    received_at: int  # when we received it, unix seconds

    def age_seconds(self, now: int) -> int:
        return now - self.received_at


@dataclass(frozen=True)
class UnderlyingSnapshot:
    """Underlying spot + recent closes used as MODEL INPUTS.

    This is an external observation, NOT the DreamDEX settlement oracle. Its
    ``source`` is always labeled and its freshness is enforced downstream.
    """

    asset: str
    price: Decimal
    timestamp: int  # source event time, unix seconds
    received_at: int  # unix seconds
    source: str
    closes: tuple[tuple[int, Decimal], ...]  # (unix_sec, close), oldest first
    interval_seconds: float

    def as_observation(self) -> Observation:
        return Observation(source=self.source, value=self.price, timestamp=self.timestamp, received_at=self.received_at)


@dataclass(frozen=True)
class ProbabilityEstimate:
    """Independent model estimate. ``confidence`` is distinct from probability."""

    p_up: Decimal
    p_down: Decimal
    confidence: Decimal  # [0, 1]
    model_version: str
    inputs: dict[str, str]  # stringified for stable JSON
    explanation: str

    def is_valid(self) -> bool:
        return (
            Decimal(0) <= self.p_up <= Decimal(1)
            and Decimal(0) <= self.p_down <= Decimal(1)
            and abs((self.p_up + self.p_down) - Decimal(1)) <= Decimal("0.001")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "p_up": str(self.p_up),
            "p_down": str(self.p_down),
            "confidence": str(self.confidence),
            "model_version": self.model_version,
            "inputs": self.inputs,
            "explanation": self.explanation,
        }
