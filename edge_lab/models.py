"""Normalized domain models.

Every monetary or size field is a :class:`~decimal.Decimal`. Timestamps are
stored as UTC Unix seconds (int); conversion to a display timezone happens only
in the presentation/analysis layer. Parsing is deliberately defensive: external
APIs mix strings and numbers and omit optional fields, and we never fabricate a
value that was not present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import DataError


def to_decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    """Normalize a string/number/None into a finite Decimal without float rounding.

    Non-finite inputs (``NaN``, ``Infinity``) are rejected: ``Decimal("NaN")``
    parses successfully but would silently poison money math (NaN compares
    False against everything), so we treat it as unparseable data.
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):  # avoid True -> Decimal(1)
        raise DataError(f"expected numeric, got bool {value!r}")
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise DataError(f"cannot parse decimal from {value!r}") from exc
    if not result.is_finite():
        raise DataError(f"non-finite numeric value {value!r}")
    return result


def safe_decimal(value: Any) -> Decimal | None:
    """Like :func:`to_decimal` but returns None instead of raising on bad data.

    Use at parse boundaries for optional fields, so one malformed value is
    treated as missing rather than aborting a whole page/book. The strict
    :func:`to_decimal` still guards anything that feeds money math.
    """
    try:
        return to_decimal(value)
    except DataError:
        return None


def require_decimal(value: Any, field_name: str) -> Decimal:
    out = to_decimal(value)
    if out is None:
        raise DataError(f"missing required numeric field {field_name!r}")
    return out


def to_int_timestamp(value: Any) -> int | None:
    """Coerce a Unix-seconds timestamp; return None if absent/unparseable."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_jsonish_list(value: Any) -> list[str]:
    """Gamma encodes some list fields as JSON strings; accept either form."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise DataError(f"expected JSON array, got {value!r}") from exc
        if not isinstance(parsed, list):
            raise DataError(f"expected JSON array, got {value!r}")
        return [str(v) for v in parsed]
    raise DataError(f"expected list or JSON-encoded list, got {type(value).__name__}")


def iso_utc(timestamp: int | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Token:
    token_id: str
    outcome: str


@dataclass(frozen=True)
class Market:
    slug: str
    question: str
    condition_id: str
    tokens: tuple[Token, ...]
    active: bool = True
    closed: bool = False
    accepting_orders: bool = True
    category: str | None = None
    tags: tuple[str, ...] = ()
    end_date: int | None = None

    @property
    def is_binary(self) -> bool:
        return len(self.tokens) == 2

    def token_for(self, outcome: str) -> Token | None:
        target = outcome.strip().lower()
        for token in self.tokens:
            if token.outcome.strip().lower() == target:
                return token
        return None

    @property
    def yes_token(self) -> Token | None:
        return self.token_for("yes")

    @property
    def no_token(self) -> Token | None:
        return self.token_for("no")


@dataclass(frozen=True)
class OrderBookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: tuple[OrderBookLevel, ...]  # sorted best (highest) first
    asks: tuple[OrderBookLevel, ...]  # sorted best (lowest) first
    timestamp: int | None = None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class WalletActivity:
    timestamp: int | None
    tx_hash: str
    asset: str  # token id
    side: str  # "BUY" | "SELL" | other
    activity_type: str  # "TRADE", ...
    price: Decimal | None
    size: Decimal | None
    usdc_size: Decimal | None
    title: str = ""
    outcome: str = ""
    event_slug: str = ""
    condition_id: str = ""

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> WalletActivity:
        return cls(
            timestamp=to_int_timestamp(row.get("timestamp")),
            tx_hash=str(row.get("transactionHash") or ""),
            asset=str(row.get("asset") or ""),
            side=str(row.get("side") or "").upper(),
            activity_type=str(row.get("type") or "").upper(),
            price=safe_decimal(row.get("price")),
            size=safe_decimal(row.get("size")),
            usdc_size=safe_decimal(row.get("usdcSize")),
            title=str(row.get("title") or ""),
            outcome=str(row.get("outcome") or ""),
            event_slug=str(row.get("eventSlug") or row.get("slug") or ""),
            condition_id=str(row.get("conditionId") or ""),
        )

    @property
    def signal_id(self) -> str:
        """Stable identifier for de-duplicating an observed activity item."""
        size = "" if self.size is None else format(self.size, "f")
        return f"{self.tx_hash}:{self.asset}:{self.side}:{self.timestamp}:{size}"


@dataclass(frozen=True)
class GeoStatus:
    blocked: bool | None
    country: str | None
    region: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FillEstimate:
    """Result of walking one side of a book to acquire ``quantity`` shares."""

    quantity: Decimal
    cost: Decimal
    vwap: Decimal
    fully_filled: bool
    levels_consumed: int


@dataclass(frozen=True)
class PricePoint:
    timestamp: int
    price: Decimal


@dataclass(frozen=True)
class PriceHistory:
    token_id: str
    points: tuple[PricePoint, ...]  # chronological (oldest first)

    @property
    def is_empty(self) -> bool:
        return len(self.points) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "points": [{"t": p.timestamp, "t_utc": iso_utc(p.timestamp), "p": str(p.price)} for p in self.points],
        }
