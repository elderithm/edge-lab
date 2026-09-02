"""DreamDEX venue adapter — reads + testnet execution via the Node bridge.

Identity is always the canonical ``marketId``; the recycled pool address is
carried for reference only and is never used as identity. ``get_market_status``
performs a fresh on-chain read (the bridge overrides indexer status with
``getMarketOnchain``), satisfying the "read status before every write" rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...core.types import EventContractBook, EventContractMarket, MarketStatus, UnderlyingSnapshot
from ..base import OrderRequest, OrderResult, TradingVenue
from .bridge import DreamdexBridge
from .config import DreamdexConfig
from .errors import PaperModeWrite
from .mapper import book_from_json, market_from_json, underlying_from_json


class DreamdexAdapter(TradingVenue):
    venue = "dreamdex"

    def __init__(self, config: DreamdexConfig | None = None, bridge: DreamdexBridge | None = None) -> None:
        self.config = config or DreamdexConfig.from_env()
        self.bridge = bridge or DreamdexBridge(self.config)

    def list_markets(self, assets: Sequence[str] | None = None) -> list[EventContractMarket]:
        params = {"assets": list(assets)} if assets else {}
        payload = self.bridge.invoke("discover", params)
        rows = payload.get("markets") or []
        out: list[EventContractMarket] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(market_from_json(row))
        return out

    def get_market(self, market_id: str) -> EventContractMarket:
        """Fresh market detail incl. on-chain status and opening reference."""
        payload = self.bridge.invoke("market", {"marketId": market_id})
        return market_from_json(payload)

    def get_order_book(self, market_id: str) -> EventContractBook:
        payload = self.bridge.invoke("orderbook", {"marketId": market_id})
        return book_from_json(payload)

    def get_market_status(self, market_id: str) -> MarketStatus:
        return self.get_market(market_id).status

    def get_underlying(self, asset: str, *, limit: int = 30) -> UnderlyingSnapshot:
        """Underlying spot + recent closes (a MODEL INPUT, not the oracle)."""
        payload = self.bridge.invoke("price", {"asset": asset, "limit": limit})
        return underlying_from_json(payload)

    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit a real (testnet/mainnet) order. Refused in paper mode.

        The bridge re-reads on-chain status immediately before signing and
        enforces the same mode/network gates; this is the Python-side guard.
        """
        if self.config.is_paper:
            raise PaperModeWrite("adapter.place_order is not available in paper mode; use the paper trader")
        params = {
            "marketId": request.market_id,
            "side": request.side.value,
            "size": str(request.size),
            "orderType": request.order_type,
        }
        if request.limit_price is not None:
            params["price"] = str(request.limit_price)
        payload = self.bridge.invoke("place-order", params)
        return OrderResult(
            submitted=bool(payload.get("submitted")),
            venue=self.venue,
            market_id=request.market_id,
            side=request.side,
            detail=payload,
            paper=False,
        )
