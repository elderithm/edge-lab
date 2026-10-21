"""Normalized DreamDEX Perps domain models (human units, ``Decimal``).

Raw on-chain integers are converted exactly, per market, using that market's
``baseDecimals``; perp prices are always 18-decimal quote units per WHOLE base
(per the Perps docs). Nothing here is shared with the binary event-contract
types: a perp is not an ``EventContractMarket``.

Identity is ``(chain_id, pool address)``. The symbol is a display label only;
resolving a symbol to a market goes through :func:`resolve_market`, which fails
loudly on ambiguity rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

PRICE_DECIMALS = 18  # perp prices: raw quote atoms per whole base, always 1e18-scaled
FUNDING_PRECISION = Decimal(10) ** 18


class DataSource(StrEnum):
    LIVE = "LIVE_TESTNET"  # live Hideki testnet read via the official SDK
    SIMULATED = "SIMULATED_FIXTURE"  # bundled, clearly-fake fixture data


class PerpSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def is_bid(self) -> bool:
        return self is PerpSide.LONG

    @property
    def sign(self) -> int:
        return 1 if self is PerpSide.LONG else -1


def scale_down(raw: int | str, decimals: int) -> Decimal:
    """Exact raw-integer -> human Decimal (no binary floating point)."""
    return Decimal(int(raw)).scaleb(-decimals)


def scale_up(human: Decimal, decimals: int) -> int:
    """Exact human Decimal -> raw integer; raises if it does not land on an integer."""
    scaled = human.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{human} has more precision than {decimals} decimals")
    return int(scaled)


@dataclass(frozen=True)
class PerpMarket:
    chain_id: int
    market_id: str  # lowercased pool address — the canonical identity on this chain
    base_symbol: str
    quote_symbol: str
    base_decimals: int
    quote_decimals: int
    tick_size_raw: int  # raw price units (18dp)
    lot_size_raw: int  # raw base units
    min_quantity_raw: int  # raw base units
    margin_bank: str
    quote_token: str
    initial_margin_bps: int
    last_price: Decimal | None = None
    last_trade_at: int | None = None
    open_interest: Decimal | None = None
    venue: str = "dreamdex-perps"

    @property
    def symbol(self) -> str:
        return f"{self.base_symbol}-PERP"

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.chain_id}:{self.market_id}"

    @property
    def tick_size(self) -> Decimal:
        return scale_down(self.tick_size_raw, PRICE_DECIMALS)

    @property
    def lot_size(self) -> Decimal:
        return scale_down(self.lot_size_raw, self.base_decimals)

    @property
    def min_quantity(self) -> Decimal:
        return scale_down(self.min_quantity_raw, self.base_decimals)

    @property
    def max_leverage(self) -> Decimal:
        return Decimal(10_000) / Decimal(self.initial_margin_bps) if self.initial_margin_bps else Decimal(0)

    def price_to_raw(self, price: Decimal) -> int:
        return scale_up(price, PRICE_DECIMALS)

    def quantity_to_raw(self, quantity: Decimal) -> int:
        return scale_up(quantity, self.base_decimals)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "chain_id": self.chain_id,
            "market_id": self.market_id,
            "symbol": self.symbol,
            "base_symbol": self.base_symbol,
            "quote_symbol": self.quote_symbol,
            "base_decimals": self.base_decimals,
            "quote_decimals": self.quote_decimals,
            "tick_size": plain(self.tick_size),
            "lot_size": plain(self.lot_size),
            "min_quantity": plain(self.min_quantity),
            "initial_margin_bps": self.initial_margin_bps,
            "protocol_max_leverage": plain(self.max_leverage),
            "margin_bank": self.margin_bank,
            "quote_token": self.quote_token,
            "last_price": _s(self.last_price),
            "last_trade_at": self.last_trade_at,
            "open_interest": _s(self.open_interest),
        }


@dataclass(frozen=True)
class PerpState:
    """Fresh on-chain pricing/funding state (``getPerpState``)."""

    mark_price: Decimal | None  # None when the mark feed is stale (markPriceOk=false)
    mark_price_ok: bool
    index_price: Decimal | None
    index_updated_at: int | None
    funding_rate: Decimal | None  # fraction per funding WINDOW (not per interval, not annualized)
    funding_window_sec: int | None
    funding_interval_sec: int | None
    last_funding_at: int | None
    next_funding_at: int | None
    cumulative_funding_raw: int | None  # 1e18-scaled raw quote per whole base (SDK semantics)
    projected_cumulative_funding_raw: int | None
    open_interest: Decimal | None
    ema_premium: Decimal | None  # fraction; the premium funding actually uses


@dataclass(frozen=True)
class PerpRiskParams:
    initial_margin_bps: Decimal
    maintenance_margin_bps: Decimal
    close_out_margin_bps: Decimal
    max_open_interest: Decimal  # base units
    max_position_size: Decimal  # base units, per account
    taker_fee_bps: Decimal
    maker_fee_bps: Decimal


@dataclass(frozen=True)
class FundingPremium:
    time_weighted_premium: Decimal  # fraction, next settlement (pre-clamp)
    armed: bool  # False => point sample, not a time-weighted average


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    quantity: Decimal  # base units


@dataclass(frozen=True)
class PerpBook:
    bids: tuple[BookLevel, ...]  # best (highest) first
    asks: tuple[BookLevel, ...]  # best (lowest) first
    captured_at: int
    block_number: int | None = None

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class Candle:
    bucket_start: int
    close: Decimal
    trade_count: int


@dataclass(frozen=True)
class PerpSnapshot:
    """Everything observed for one market at one capture time, with provenance."""

    market: PerpMarket
    state: PerpState
    risk: PerpRiskParams
    book: PerpBook
    candles: tuple[Candle, ...]
    candle_interval_seconds: int
    captured_at: int
    source: DataSource
    premium: FundingPremium | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PerpPositionState:
    market_id: str
    symbol: str
    size: Decimal  # signed base units: + long, - short
    avg_entry_price: Decimal


@dataclass(frozen=True)
class PerpAccount:
    account: str
    equity: Decimal | None  # None when the protocol could not price it
    positions: tuple[PerpPositionState, ...]
    voucher: dict[str, object]
    captured_at: int
    source: DataSource


def plain(v: Decimal) -> str:
    """Human display without exponent notation or trailing zeros (1E-7 -> 0.0000001)."""
    return format(v.normalize(), "f")


def _s(v: Decimal | None) -> str | None:
    return None if v is None else plain(v)


def resolve_market(markets: list[PerpMarket], query: str) -> PerpMarket:
    """Resolve a user query (pool address, ``BTC`` or ``BTC-PERP``) to exactly one market."""
    from .errors import AmbiguousMarket, PerpsMarketNotFound

    q = query.strip().lower()
    if q.startswith("0x"):
        hits = [m for m in markets if m.market_id == q]
    else:
        sym = q.removesuffix("-perp")
        hits = [m for m in markets if m.base_symbol.lower() == sym]
    if not hits:
        raise PerpsMarketNotFound(f"no perp market matches '{query}'")
    if len(hits) > 1:
        pools = ", ".join(m.market_id for m in hits)
        raise AmbiguousMarket(f"'{query}' matches {len(hits)} markets ({pools}); pass the pool address")
    return hits[0]
