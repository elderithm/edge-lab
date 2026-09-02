"""Data client: activity parsing, Decimal normalization, pagination."""

from __future__ import annotations

from decimal import Decimal

from edge_lab.api.data import DataClient
from edge_lab.http import HttpClient

BASE = "https://data.test"


def data():
    return DataClient(HttpClient(sleep=lambda _s: None), BASE)


def row(**over):
    r = {
        "timestamp": 1_767_225_600,
        "transactionHash": "0xabc",
        "asset": "1111",
        "side": "buy",
        "type": "TRADE",
        "price": "0.42",  # string numeric
        "size": 100,  # numeric
        "usdcSize": "42.5",
        "title": "Market A",
        "outcome": "Yes",
    }
    r.update(over)
    return r


def test_activity_decimal_normalization(httpx_mock):
    httpx_mock.add_response(json=[row()])
    acts = data().get_activity("0xwallet")
    assert acts[0].price == Decimal("0.42")
    assert acts[0].size == Decimal("100")
    assert acts[0].side == "BUY"  # uppercased


def test_activity_empty(httpx_mock):
    httpx_mock.add_response(json=[])
    assert data().get_activity("0xwallet") == []


def test_missing_optional_fields(httpx_mock):
    httpx_mock.add_response(json=[{"asset": "1", "side": "SELL", "type": "TRADE"}])
    acts = data().get_activity("0xwallet")
    assert acts[0].price is None
    assert acts[0].usdc_size is None
    assert acts[0].timestamp is None


def test_iter_activity_paginates(httpx_mock):
    httpx_mock.add_response(json=[row() for _ in range(500)])
    httpx_mock.add_response(json=[row() for _ in range(30)])
    acts = list(data().iter_activity("0xwallet", max_records=1000))
    assert len(acts) == 530
    assert len(httpx_mock.get_requests()) == 2


def test_iter_activity_respects_max(httpx_mock):
    httpx_mock.add_response(json=[row() for _ in range(500)])
    acts = list(data().iter_activity("0xwallet", max_records=100))
    assert len(acts) == 100


def test_get_positions_returns_raw_dicts(httpx_mock):
    payload = [{"asset": "1", "size": "10", "avgPrice": "0.4"}, {"asset": "2", "size": "5"}]
    httpx_mock.add_response(json=payload)
    positions = data().get_positions("0xwallet")
    assert positions == payload  # returned verbatim; shape left to the caller


def test_get_positions_empty(httpx_mock):
    httpx_mock.add_response(json=[])
    assert data().get_positions("0xwallet") == []


def test_get_positions_non_list_payload_is_empty(httpx_mock):
    httpx_mock.add_response(json={"unexpected": "shape"})
    assert data().get_positions("0xwallet") == []
