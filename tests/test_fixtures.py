"""Regression tests that parse sanitized real-shape API fixtures.

These pin the parsers against the response shapes we observed from the live
Polymarket APIs. If an upstream shape drifts, these fail loudly instead of a
downstream analysis silently producing wrong numbers.
"""

from __future__ import annotations

from decimal import Decimal

from helpers import load_fixture

from edge_lab.api.clob import ClobClient
from edge_lab.api.data import DataClient
from edge_lab.api.gamma import GammaClient
from edge_lab.api.geoblock import GeoblockClient
from edge_lab.http import HttpClient


def _http():
    return HttpClient(sleep=lambda _s: None)


def test_gamma_market_fixture(httpx_mock):
    httpx_mock.add_response(json=load_fixture("gamma_market.json"))
    market = GammaClient(_http(), "https://gamma.test").get_market_by_slug("example-binary-market")
    assert market.is_binary
    assert market.yes_token and market.no_token
    assert market.yes_token.token_id.endswith("0001")
    assert market.category == "Politics"
    assert "Politics" in market.tags
    assert market.end_date is not None


def test_data_activity_fixture(httpx_mock):
    httpx_mock.add_response(json=load_fixture("data_activity.json"))
    acts = DataClient(_http(), "https://data.test").get_activity("0xwallet")
    assert len(acts) == 3
    assert acts[0].side == "BUY"
    assert acts[0].price == Decimal("0.42")
    assert acts[1].size == Decimal("40")  # numeric in source, Decimal here
    assert acts[2].usdc_size is None  # missing field is not fabricated


def test_clob_book_fixture(httpx_mock):
    httpx_mock.add_response(json=load_fixture("clob_book.json"))
    book = ClobClient(_http(), "https://clob.test").get_order_book("tok")
    assert book.best_bid and book.best_bid.price == Decimal("0.041")  # highest bid
    assert book.best_ask and book.best_ask.price == Decimal("0.046")  # lowest ask
    assert len(book.asks) == 3


def test_clob_price_history_fixture(httpx_mock):
    httpx_mock.add_response(json=load_fixture("clob_price_history.json"))
    hist = ClobClient(_http(), "https://clob.test").get_price_history("tok", interval="1d")
    assert len(hist.points) == 4
    assert hist.points[0].timestamp < hist.points[-1].timestamp  # oldest-first
    assert all(isinstance(p.price, Decimal) for p in hist.points)


def test_geoblock_fixture(httpx_mock):
    httpx_mock.add_response(json=load_fixture("geoblock.json"))
    status = GeoblockClient(_http(), "https://geo.test/api").get_status()
    assert status.blocked is True
    assert status.country == "JP"
