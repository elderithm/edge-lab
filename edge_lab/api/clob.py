"""CLOB read-only client: order books and prices.

No authenticated or order-placement endpoints are implemented here, by policy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..errors import DataError
from ..http import HttpClient
from ..models import OrderBook, OrderBookLevel, PriceHistory, PricePoint, safe_decimal

# Fidelity is the sampling resolution in minutes; the API accepts either an
# ``interval`` label (e.g. "1d") or an explicit start/end window. Wider ranges
# require a coarser minimum fidelity (the API 400s otherwise), so we supply a
# safe default per interval when the caller does not specify one.
_DEFAULT_FIDELITY: dict[str, int] = {
    "1m": 1,
    "1h": 1,
    "6h": 5,
    "1d": 10,
    "1w": 60,
    "max": 60,
}
_VALID_INTERVALS = frozenset(_DEFAULT_FIDELITY)


class ClobClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")

    def get_price(self, token_id: str, side: str) -> Decimal | None:
        """Best price for ``side`` (BUY = best ask, SELL = best bid)."""
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        row = self._http.get_json(f"{self._base}/price", {"token_id": token_id, "side": side})
        if isinstance(row, dict) and row.get("price") not in (None, ""):
            return safe_decimal(row["price"])
        return None

    def get_order_book(self, token_id: str) -> OrderBook:
        payload = self._http.get_json(f"{self._base}/book", {"token_id": token_id})
        if not isinstance(payload, dict):
            raise DataError(f"unexpected order book payload for {token_id}")
        bids = _parse_levels(payload.get("bids"))
        asks = _parse_levels(payload.get("asks"))
        # Normalize ordering regardless of source direction.
        bids_sorted = tuple(sorted(bids, key=lambda level: level.price, reverse=True))
        asks_sorted = tuple(sorted(asks, key=lambda level: level.price))
        return OrderBook(
            token_id=token_id,
            bids=bids_sorted,
            asks=asks_sorted,
            timestamp=_parse_ts(payload.get("timestamp")),
        )

    def get_price_history(
        self,
        token_id: str,
        *,
        interval: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        fidelity: int | None = None,
    ) -> PriceHistory:
        """Historical mid-price series for a token (read-only).

        Provide either ``interval`` (a coarse label) or an explicit
        ``start_ts``/``end_ts`` window. Points are returned oldest-first. An
        empty series is returned as an empty history, never fabricated.
        """
        if interval is not None and interval not in _VALID_INTERVALS:
            raise ValueError(f"interval must be one of {sorted(_VALID_INTERVALS)}")
        params: dict[str, Any] = {"market": token_id}
        if interval is not None:
            params["interval"] = interval
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        # Supply a safe default fidelity for interval queries so wider ranges do
        # not fail the API's minimum-resolution requirement.
        if fidelity is None and interval is not None:
            fidelity = _DEFAULT_FIDELITY.get(interval)
        if fidelity is not None:
            params["fidelity"] = fidelity
        payload = self._http.get_json(f"{self._base}/prices-history", params)
        rows = payload.get("history") if isinstance(payload, dict) else payload
        points = _parse_history(rows)
        points.sort(key=lambda p: p.timestamp)
        return PriceHistory(token_id=token_id, points=tuple(points))


def _parse_history(raw: Any) -> list[PricePoint]:
    if not isinstance(raw, list):
        return []
    out: list[PricePoint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts = _parse_ts(item.get("t") if "t" in item else item.get("timestamp"))
        price = safe_decimal(item.get("p") if "p" in item else item.get("price"))
        if ts is None or price is None:
            continue
        out.append(PricePoint(timestamp=ts, price=price))
    return out


def _parse_levels(raw: Any) -> list[OrderBookLevel]:
    if not isinstance(raw, list):
        return []
    levels: list[OrderBookLevel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        price = safe_decimal(item.get("price"))
        size = safe_decimal(item.get("size"))
        # A non-positive price is invalid for an outcome quote and would cause
        # division-by-zero when walking the book for a notional budget.
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append(OrderBookLevel(price=price, size=size))
    return levels


def _parse_ts(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None
