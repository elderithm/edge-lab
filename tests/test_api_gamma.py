"""Gamma client: parsing, numeric coercion, pagination, malformed rows."""

from __future__ import annotations

import pytest

from edge_lab.api.gamma import GammaClient
from edge_lab.errors import DataError, NotFoundError
from edge_lab.http import HttpClient

BASE = "https://gamma.test"


def gamma():
    return GammaClient(HttpClient(sleep=lambda _s: None), BASE)


def market_row(**over):
    row = {
        "slug": "will-x-happen",
        "question": "Will X happen?",
        "conditionId": "0xcond",
        "outcomes": '["Yes", "No"]',  # string-encoded JSON, as Gamma returns
        "clobTokenIds": '["1111", "2222"]',
        "active": True,
        "closed": False,
        "acceptingOrders": True,
    }
    row.update(over)
    return row


def test_parse_market_normal():
    m = GammaClient.parse_market(market_row())
    assert m.slug == "will-x-happen"
    assert m.is_binary
    assert m.yes_token and m.yes_token.token_id == "1111"
    assert m.no_token and m.no_token.token_id == "2222"


def test_parse_market_list_encoded_fields():
    # Already-decoded lists should also work.
    m = GammaClient.parse_market(market_row(outcomes=["Yes", "No"], clobTokenIds=["a", "b"]))
    assert m.yes_token.token_id == "a"  # type: ignore[union-attr]


def test_parse_market_missing_tokens_raises():
    with pytest.raises(DataError):
        GammaClient.parse_market(market_row(clobTokenIds=None))


def test_get_market_by_slug_empty_raises_not_found(httpx_mock):
    httpx_mock.add_response(json=[])
    with pytest.raises(NotFoundError):
        gamma().get_market_by_slug("nope")


def test_get_market_by_slug(httpx_mock):
    httpx_mock.add_response(json=[market_row()])
    m = gamma().get_market_by_slug("will-x-happen")
    assert m.condition_id == "0xcond"


def test_list_markets_skips_malformed(httpx_mock):
    httpx_mock.add_response(json=[market_row(), {"slug": "broken"}])
    markets = gamma().list_markets()
    assert len(markets) == 1


def test_iter_markets_paginates_and_stops_on_short_page(httpx_mock):
    page1 = [market_row(slug=f"m{i}") for i in range(100)]
    page2 = [market_row(slug=f"m{i}") for i in range(100, 150)]
    httpx_mock.add_response(json=page1)
    httpx_mock.add_response(json=page2)
    markets = list(gamma().iter_markets(max_markets=1000))
    assert len(markets) == 150
    assert len(httpx_mock.get_requests()) == 2  # stopped: page2 was short


def test_iter_markets_respects_max(httpx_mock):
    httpx_mock.add_response(json=[market_row(slug=f"m{i}") for i in range(100)])
    markets = list(gamma().iter_markets(max_markets=10))
    assert len(markets) == 10


def test_iter_markets_no_drop_or_dupe_with_malformed_rows(httpx_mock):
    # Page 1: 90 valid + 10 malformed (100 raw rows -> full page, keep paging).
    # Page 2: 50 valid + 10 malformed (60 raw rows -> short page, stop).
    bad = {"slug": "broken"}  # missing clobTokenIds -> DataError, skipped
    page1 = [market_row(slug=f"m{i}") for i in range(90)] + [dict(bad) for _ in range(10)]
    page2 = [market_row(slug=f"m{i}") for i in range(90, 140)] + [dict(bad) for _ in range(10)]
    httpx_mock.add_response(json=page1)
    httpx_mock.add_response(json=page2)

    markets = list(gamma().iter_markets(max_markets=1000))
    slugs = [m.slug for m in markets]
    assert slugs == [f"m{i}" for i in range(140)]  # every valid market, in order
    assert len(slugs) == len(set(slugs))  # no duplicates
    assert len(httpx_mock.get_requests()) == 2  # stopped on the short page
