"""The venue interface the core pipeline and CLI depend on.

Analysis and execution are separate layers: the probability model never calls
``place_order``. Only the CLI/service, after the risk engine approves a proposal
and the user confirms, calls it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from ..core.types import EventContractBook, EventContractMarket, MarketStatus, Side


@dataclass(frozen=True)
class OrderRequest:
    market_id: str
    side: Side
    size: Decimal  # outcome-token units
    limit_price: Decimal | None  # probability price [0,1]; None = market order
    order_type: str = "limit"  # "limit" | "market"


@dataclass(frozen=True)
class OrderResult:
    submitted: bool
    venue: str
    market_id: str
    side: Side
    detail: dict[str, object]  # raw venue/bridge response (paper or on-chain)
    paper: bool = False


@runtime_checkable
class TradingVenue(Protocol):
    venue: str

    def list_markets(self, assets: Sequence[str] | None = None) -> list[EventContractMarket]: ...

    def get_market(self, market_id: str) -> EventContractMarket: ...

    def get_order_book(self, market_id: str) -> EventContractBook: ...

    def get_market_status(self, market_id: str) -> MarketStatus: ...

    def place_order(self, request: OrderRequest) -> OrderResult: ...
