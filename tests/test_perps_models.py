"""Perps market normalization, decimal scaling and identity."""

from __future__ import annotations

from decimal import Decimal

import pytest
from perps_helpers import live_btc_json, live_btc_snapshot, market

from edge_lab.venues.dreamdex_perps.errors import AmbiguousMarket, PerpsMarketNotFound
from edge_lab.venues.dreamdex_perps.mapper import market_from_json, state_from_json
from edge_lab.venues.dreamdex_perps.models import DataSource, plain, resolve_market, scale_down, scale_up

D = Decimal


def test_scale_roundtrip_exact():
    assert scale_down(13000, 8) == D("0.00013")
    assert scale_up(D("0.00013"), 8) == 13000
    assert scale_down("84662100000000000000000", 18) == D("84662.1")
    with pytest.raises(ValueError):
        scale_up(D("0.000000001"), 8)  # finer than base decimals


def test_live_btc_row_normalizes_with_market_specific_decimals():
    m = market_from_json(live_btc_json()["market"])
    assert m.chain_id == 50383
    assert m.base_decimals == 8 and m.quote_decimals == 18
    assert m.tick_size == D("0.1")
    assert m.lot_size == D("0.00001")
    assert m.min_quantity == D("0.00013")
    assert m.max_leverage == D(20)
    assert m.key == f"dreamdex-perps:50383:{m.market_id}"
    assert m.symbol == "BTC-PERP"


def test_quantity_scaling_differs_per_market():
    btc = market(base_decimals=8)
    near = market(base_decimals=24, lot_size_raw=10**23)
    assert btc.quantity_to_raw(D("0.001")) == 100_000
    assert near.quantity_to_raw(D("0.1")) == 10**23  # never assume 18 decimals


def test_live_snapshot_maps_state_risk_book_candles():
    s = live_btc_snapshot()
    assert s.source is DataSource.LIVE
    assert s.state.mark_price_ok and s.state.mark_price and s.state.mark_price > 1000
    assert s.state.funding_window_sec == 28800 and s.state.funding_interval_sec == 3600
    assert s.risk.initial_margin_bps == 500 and s.risk.maintenance_margin_bps == 250
    assert s.book.bids and s.book.asks
    assert s.book.bids[0].price < s.book.asks[0].price
    assert all(a.price >= b.price for a, b in zip(s.book.bids, s.book.bids[1:], strict=False))
    assert len(s.candles) > 10


def test_stale_mark_is_missing_not_synthesized():
    m = market()
    st = state_from_json({"markPrice": "0", "markPriceOk": False, "indexPrice": "0"}, m)
    assert st.mark_price is None and st.index_price is None
    assert st.funding_rate is None


def test_resolve_market_by_symbol_pool_and_ambiguity():
    a = market(market_id="0x" + "a" * 40, base_symbol="BTC")
    b = market(market_id="0x" + "b" * 40, base_symbol="ETH")
    assert resolve_market([a, b], "btc-perp") is a
    assert resolve_market([a, b], "0x" + "B" * 40) is b
    with pytest.raises(PerpsMarketNotFound):
        resolve_market([a, b], "SOL")
    dup = market(market_id="0x" + "c" * 40, base_symbol="BTC")
    with pytest.raises(AmbiguousMarket):
        resolve_market([a, dup], "BTC")  # symbol alone is not identity


def test_plain_display():
    assert plain(D("1E-7")) == "0.0000001"
    assert plain(D("100.000")) == "100"
