"""Builders for domain objects and fake clients used across tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from edge_lab.models import Market, OrderBook, OrderBookLevel, Token, WalletActivity

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a sanitized API-response fixture from tests/fixtures/."""
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def make_market(slug: str = "test-market") -> Market:
    return Market(
        slug=slug,
        question="Will it happen?",
        condition_id="0xcond",
        tokens=(Token("yes-token", "Yes"), Token("no-token", "No")),
    )


def book(token_id: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=tuple(OrderBookLevel(Decimal(p), Decimal(s)) for p, s in bids),
        asks=tuple(OrderBookLevel(Decimal(p), Decimal(s)) for p, s in asks),
    )


def activity(**kw: object) -> WalletActivity:
    defaults: dict[str, object] = {
        "timestamp": 1_767_225_600,  # 2026-01-01 00:00:00 UTC
        "tx_hash": "0xtx",
        "asset": "yes-token",
        "side": "BUY",
        "activity_type": "TRADE",
        "price": Decimal("0.5"),
        "size": Decimal("10"),
        "usdc_size": Decimal("5"),
        "title": "Market A",
        "outcome": "Yes",
        "event_slug": "market-a",
        "condition_id": "0xcond",
    }
    defaults.update(kw)
    return WalletActivity(**defaults)  # type: ignore[arg-type]


class FakeBooks:
    """A BookProvider backed by a dict; missing tokens raise."""

    def __init__(self, books: dict[str, OrderBook]) -> None:
        self._books = books

    def get_order_book(self, token_id: str) -> OrderBook:
        if token_id not in self._books:
            raise KeyError(token_id)
        return self._books[token_id]
