"""Optional live smoke tests against the real Polymarket public APIs.

These are skipped by default (pyproject sets ``-m 'not live'``); run them
explicitly with ``pytest -m live``. They are deliberately shape-only and
discover a market dynamically, so they do not depend on any single market or
wallet remaining unchanged over time. They never place orders or authenticate.
"""

from __future__ import annotations

import pytest

from edge_lab.api.clob import ClobClient
from edge_lab.api.gamma import GammaClient
from edge_lab.api.geoblock import GeoblockClient
from edge_lab.config import Settings
from edge_lab.http import HttpClient
from edge_lab.models import GeoStatus, Market, OrderBook, PriceHistory

pytestmark = pytest.mark.live


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def http(settings):
    client = HttpClient(
        timeout=settings.http_timeout,
        user_agent=settings.user_agent,
        max_retries=settings.max_retries,
    )
    yield client
    client.close()


def _first_binary_market(gamma: GammaClient) -> Market | None:
    for market in gamma.iter_markets(max_markets=25):
        if market.is_binary and market.yes_token and market.no_token:
            return market
    return None


def test_geo_live(http, settings):
    status = GeoblockClient(http, settings.geoblock_url).get_status()
    assert isinstance(status, GeoStatus)
    assert status.blocked in (True, False, None)


def test_gamma_list_markets_live(http, settings):
    markets = GammaClient(http, settings.gamma_url).list_markets(limit=5)
    assert isinstance(markets, list)
    for m in markets:
        assert isinstance(m, Market)
        assert m.tokens  # every parsed market exposes outcome tokens


def test_market_lookup_and_book_live(http, settings):
    gamma = GammaClient(http, settings.gamma_url)
    market = _first_binary_market(gamma)
    if market is None:
        pytest.skip("no active binary market available right now")

    # Slug round-trip through the documented filter endpoint.
    again = gamma.get_market_by_slug(market.slug)
    assert again.slug == market.slug

    assert market.yes_token is not None
    book = ClobClient(http, settings.clob_url).get_order_book(market.yes_token.token_id)
    assert isinstance(book, OrderBook)
    # Bids/asks are normalized: best bid <= best ask when both present.
    if book.best_bid and book.best_ask:
        assert book.best_bid.price <= book.best_ask.price


def test_price_history_live(http, settings):
    gamma = GammaClient(http, settings.gamma_url)
    market = _first_binary_market(gamma)
    if market is None or market.yes_token is None:
        pytest.skip("no active binary market available right now")
    history = ClobClient(http, settings.clob_url).get_price_history(market.yes_token.token_id, interval="1w")
    assert isinstance(history, PriceHistory)
    # Points, when present, are chronological and carry Decimal prices.
    ts = [p.timestamp for p in history.points]
    assert ts == sorted(ts)
