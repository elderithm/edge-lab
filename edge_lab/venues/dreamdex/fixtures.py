"""SIMULATED DreamDEX data for tests and offline demo fallback.

Everything here is clearly labeled ``SIMULATED`` and must NEVER be presented as
live DreamDEX data (hackathon spec §49). Live mode uses :class:`DreamdexAdapter`.
Two BTC markets deliberately share one recycled pool address with distinct
``marketId``s to exercise the "identity is marketId, not pool" rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from ...core.types import (
    EventContractBook,
    EventContractMarket,
    MarketStatus,
    OrderBookLevel,
    OutcomeBook,
    Side,
    UnderlyingSnapshot,
)
from ..base import OrderRequest, OrderResult
from .errors import MarketNotFound, PaperModeWrite

SIMULATED_SOURCE = "SIMULATED"


def _book(up: list[tuple[str, str]], down: list[tuple[str, str]], captured_at: int) -> EventContractBook:
    def levels(rows: list[tuple[str, str]]) -> tuple[OrderBookLevel, ...]:
        return tuple(OrderBookLevel(Decimal(p), Decimal(s)) for p, s in rows)

    return EventContractBook(
        up=OutcomeBook(Side.UP, asks=levels(up), bids=()),
        down=OutcomeBook(Side.DOWN, asks=levels(down), bids=()),
        captured_at=captured_at,
    )


def _closes(base: Decimal, now: int, n: int = 20) -> tuple[tuple[int, Decimal], ...]:
    # Deterministic mild oscillation -> a finite, non-trivial realized vol.
    pattern = [Decimal("0"), Decimal("0.001"), Decimal("-0.0008"), Decimal("0.0012"), Decimal("-0.0005")]
    out: list[tuple[int, Decimal]] = []
    price = base
    for i in range(n):
        price = price * (Decimal(1) + pattern[i % len(pattern)])
        out.append((now - (n - i) * 60, price.quantize(Decimal("0.01"))))
    return tuple(out)


class FixtureVenue:
    """A TradingVenue-shaped, fully offline SIMULATED source."""

    venue = "dreamdex"

    def __init__(self, now: int) -> None:
        self.now = now
        self._markets: dict[str, EventContractMarket] = {}
        self._books: dict[str, EventContractBook] = {}
        self._underlying: dict[str, UnderlyingSnapshot] = {}
        self._build(now)

    def _build(self, now: int) -> None:
        # Two BTC 15m markets sharing ONE recycled pool, distinct marketIds.
        btc_a = EventContractMarket(
            venue="dreamdex",
            market_id="0x0000000000000000000000000000000000000000000000000000000000000001",
            asset="BTC",
            symbol="BTC-15m/USDso [SIMULATED]",
            status=MarketStatus.TRADING,
            trading_start=now - 500,
            expiry=now + 400,
            opening_reference=Decimal("100000"),
            pool_address="0xpoolbtc",
            nonce="7",
            window_label="15m",
        )
        btc_b = EventContractMarket(
            venue="dreamdex",
            market_id="0x0000000000000000000000000000000000000000000000000000000000000002",
            asset="BTC",
            symbol="BTC-15m/USDso (next) [SIMULATED]",
            status=MarketStatus.LOCKED,  # a later market on the SAME pool
            trading_start=now - 100,
            expiry=now + 800,
            opening_reference=Decimal("100050"),
            pool_address="0xpoolbtc",  # RECYCLED pool address
            nonce="8",
            window_label="15m",
        )
        eth = EventContractMarket(
            venue="dreamdex",
            market_id="0x0000000000000000000000000000000000000000000000000000000000000010",
            asset="ETH",
            symbol="ETH-1h/USDso [SIMULATED]",
            status=MarketStatus.TRADING,
            trading_start=now - 1200,
            expiry=now + 2400,
            opening_reference=Decimal("3500"),
            pool_address="0xpooleth",
            nonce="3",
            window_label="1h",
        )
        for m in (btc_a, btc_b, eth):
            self._markets[m.market_id] = m

        # BTC A: price 0.42% above opening -> Up under-priced -> a demo edge.
        self._books[btc_a.market_id] = _book(
            up=[("0.60", "80"), ("0.63", "300")], down=[("0.41", "80"), ("0.45", "300")], captured_at=now - 2
        )
        self._books[btc_b.market_id] = _book(up=[("0.55", "50")], down=[("0.47", "50")], captured_at=now - 2)
        self._books[eth.market_id] = _book(
            up=[("0.49", "100"), ("0.52", "400")], down=[("0.50", "100")], captured_at=now - 2
        )

        self._underlying["BTC"] = UnderlyingSnapshot(
            asset="BTC",
            price=Decimal("100420"),
            timestamp=now - 1,
            received_at=now - 1,
            source=f"{SIMULATED_SOURCE}-spot",
            closes=_closes(Decimal("100000"), now),
            interval_seconds=60,
        )
        self._underlying["ETH"] = UnderlyingSnapshot(
            asset="ETH",
            price=Decimal("3496"),
            timestamp=now - 1,
            received_at=now - 1,
            source=f"{SIMULATED_SOURCE}-spot",
            closes=_closes(Decimal("3500"), now),
            interval_seconds=60,
        )

    def list_markets(self, assets: Sequence[str] | None = None) -> list[EventContractMarket]:
        wanted = {a.upper() for a in assets} if assets else None
        return [m for m in self._markets.values() if wanted is None or m.asset.upper() in wanted]

    def get_market(self, market_id: str) -> EventContractMarket:
        m = self._markets.get(market_id)
        if m is None:
            raise MarketNotFound(f"[SIMULATED] no market {market_id}")
        return m

    def get_order_book(self, market_id: str) -> EventContractBook:
        if market_id not in self._books:
            raise MarketNotFound(f"[SIMULATED] no book {market_id}")
        return self._books[market_id]

    def get_market_status(self, market_id: str) -> MarketStatus:
        return self.get_market(market_id).status

    def get_underlying(self, asset: str, *, limit: int = 30) -> UnderlyingSnapshot:
        snap = self._underlying.get(asset.upper())
        if snap is None:
            raise MarketNotFound(f"[SIMULATED] no underlying {asset}")
        return snap

    def place_order(self, request: OrderRequest) -> OrderResult:
        raise PaperModeWrite("[SIMULATED] fixture venue never submits transactions")
