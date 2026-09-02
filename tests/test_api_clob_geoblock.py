"""CLOB order-book/price parsing and geoblock status normalization."""

from __future__ import annotations

from decimal import Decimal

from edge_lab.api.clob import ClobClient
from edge_lab.api.geoblock import GeoblockClient
from edge_lab.http import HttpClient


def clob():
    return ClobClient(HttpClient(sleep=lambda _s: None), "https://clob.test")


def geo():
    return GeoblockClient(HttpClient(sleep=lambda _s: None), "https://geo.test/api")


def test_order_book_sorted_and_decimal(httpx_mock):
    httpx_mock.add_response(
        json={
            "bids": [{"price": "0.40", "size": "10"}, {"price": "0.45", "size": "5"}],
            "asks": [{"price": "0.55", "size": "8"}, {"price": "0.50", "size": "3"}],
        }
    )
    book = clob().get_order_book("tok")
    assert book.best_bid.price == Decimal("0.45")  # highest bid first
    assert book.best_ask.price == Decimal("0.50")  # lowest ask first
    assert isinstance(book.asks[0].size, Decimal)


def test_order_book_drops_zero_size_levels(httpx_mock):
    httpx_mock.add_response(json={"bids": [{"price": "0.4", "size": "0"}], "asks": []})
    book = clob().get_order_book("tok")
    assert book.bids == ()
    assert book.best_ask is None


def test_order_book_drops_non_positive_price_levels(httpx_mock):
    # A price-0 ask is invalid data and would cause div-by-zero downstream.
    httpx_mock.add_response(json={"bids": [], "asks": [{"price": "0", "size": "10"}, {"price": "0.5", "size": "10"}]})
    book = clob().get_order_book("tok")
    assert len(book.asks) == 1
    assert book.best_ask.price == Decimal("0.5")


def test_price_missing_returns_none(httpx_mock):
    httpx_mock.add_response(json={})
    assert clob().get_price("tok", "BUY") is None


def test_price_history_parsed_and_sorted(httpx_mock):
    httpx_mock.add_response(json={"history": [{"t": 200, "p": "0.6"}, {"t": 100, "p": 0.5}]})
    hist = clob().get_price_history("tok", interval="1d")
    assert len(hist.points) == 2
    assert hist.points[0].timestamp == 100  # sorted oldest-first
    assert hist.points[0].price == Decimal("0.5")
    assert isinstance(hist.points[1].price, Decimal)


def test_price_history_empty(httpx_mock):
    httpx_mock.add_response(json={"history": []})
    assert clob().get_price_history("tok").is_empty


def test_price_history_skips_malformed_points(httpx_mock):
    httpx_mock.add_response(json={"history": [{"t": 100, "p": "0.5"}, {"t": None, "p": "0.4"}, {"p": "0.3"}]})
    hist = clob().get_price_history("tok")
    assert len(hist.points) == 1


def test_price_history_invalid_interval_rejected():
    import pytest

    with pytest.raises(ValueError):
        clob().get_price_history("tok", interval="bogus")


def test_geoblock_blocked_true(httpx_mock):
    httpx_mock.add_response(json={"blocked": True, "country": "US"})
    s = geo().get_status()
    assert s.blocked is True
    assert s.country == "US"


def test_geoblock_allowed_form(httpx_mock):
    httpx_mock.add_response(json={"allowed": True})
    assert geo().get_status().blocked is False


def test_geoblock_unknown_shape(httpx_mock):
    httpx_mock.add_response(json={"something": "else"})
    s = geo().get_status()
    assert s.blocked is None
