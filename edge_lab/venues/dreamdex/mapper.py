"""Normalize bridge JSON into venue-agnostic core types.

Prices from the SDK facade are already human probability-scale numbers in [0,1];
we convert to ``Decimal`` and reject non-finite values via ``safe_decimal``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ...core.types import (
    EventContractBook,
    EventContractMarket,
    MarketStatus,
    OrderBookLevel,
    OutcomeBook,
    Side,
    UnderlyingSnapshot,
)
from ...models import safe_decimal

_STATUS_MAP = {
    "listed": MarketStatus.LISTED,
    "trading": MarketStatus.TRADING,
    "locked": MarketStatus.LOCKED,
    "settling": MarketStatus.SETTLING,
    "resolved": MarketStatus.RESOLVED,
    "voided": MarketStatus.VOIDED,
    "finalized": MarketStatus.FINALIZED,
}


def status_from_str(value: Any) -> MarketStatus:
    return _STATUS_MAP.get(str(value or "").strip().lower(), MarketStatus.UNKNOWN)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def market_from_json(row: dict[str, Any]) -> EventContractMarket:
    market_id = str(row.get("marketId") or "")
    if not market_id:
        from .errors import MarketNotFound

        raise MarketNotFound("bridge market row is missing marketId")
    return EventContractMarket(
        venue="dreamdex",
        market_id=market_id,
        asset=str(row.get("asset") or ""),
        symbol=str(row.get("symbol") or ""),
        status=status_from_str(row.get("status")),
        trading_start=_int_or_none(row.get("tradingStart")),
        expiry=_int_or_none(row.get("expiry")),
        opening_reference=safe_decimal(row.get("openingReference")),
        pool_address=(str(row["poolAddress"]) if row.get("poolAddress") else None),
        nonce=(str(row["nonce"]) if row.get("nonce") is not None else None),
        window_label=(str(row["window"]) if row.get("window") else None),
    )


def _levels(raw: Any, *, descending: bool) -> tuple[OrderBookLevel, ...]:
    levels: list[OrderBookLevel] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            price = safe_decimal(item[0])
            size = safe_decimal(item[1])
            if price is None or size is None or price <= 0 or size <= 0:
                continue
            levels.append(OrderBookLevel(price=price, size=size))
    levels.sort(key=lambda level: level.price, reverse=descending)
    return tuple(levels)


def _outcome_book(side: Side, raw: dict[str, Any]) -> OutcomeBook:
    return OutcomeBook(
        side=side,
        asks=_levels(raw.get("asks"), descending=False),  # cheapest first
        bids=_levels(raw.get("bids"), descending=True),  # highest first
    )


def underlying_from_json(row: dict[str, Any]) -> UnderlyingSnapshot:
    import time

    price = safe_decimal(row.get("price"))
    if price is None:
        from .errors import StaleData

        raise StaleData("underlying price snapshot missing a finite price")
    closes: list[tuple[int, Decimal]] = []
    for item in row.get("closes") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts = _int_or_none(item[0])
            close = safe_decimal(item[1])
            if ts is not None and close is not None and close > 0:
                closes.append((ts, close))
    closes.sort(key=lambda c: c[0])
    now = int(time.time())
    return UnderlyingSnapshot(
        asset=str(row.get("asset") or ""),
        price=price,
        timestamp=_int_or_none(row.get("timestamp")) or now,
        received_at=_int_or_none(row.get("receivedAt")) or now,
        source=str(row.get("source") or "dreamdex-pricefeed"),
        closes=tuple(closes),
        interval_seconds=float(row.get("intervalSeconds") or 60),
    )


def book_from_json(row: dict[str, Any]) -> EventContractBook:
    up = row.get("up") or {}
    down = row.get("down") or {}
    captured = _int_or_none(row.get("capturedAt"))
    import time

    return EventContractBook(
        up=_outcome_book(Side.UP, up),
        down=_outcome_book(Side.DOWN, down),
        captured_at=captured if captured is not None else int(time.time()),
    )
