"""DreamDEX venue layer: mapping, identity, adapter gating, config (§50)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from edge_lab.core.types import MarketStatus, Side, TradingMode
from edge_lab.venues.base import OrderRequest
from edge_lab.venues.dreamdex.adapter import DreamdexAdapter
from edge_lab.venues.dreamdex.config import DreamdexConfig
from edge_lab.venues.dreamdex.errors import (
    MainnetDisabled,
    MarketNotTrading,
    PaperModeWrite,
    error_for,
)
from edge_lab.venues.dreamdex.fixtures import FixtureVenue
from edge_lab.venues.dreamdex.mapper import book_from_json, market_from_json

D = Decimal


def _row(market_id="0xabc", pool="0xpool", status="Trading", nonce="1"):
    return {
        "marketId": market_id,
        "asset": "BTC",
        "symbol": "BTC-15m/USDso",
        "status": status,
        "tradingStart": 1000,
        "expiry": 1900,
        "openingReference": 100000,
        "poolAddress": pool,
        "nonce": nonce,
        "window": "15m",
    }


class FakeBridge:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, object]] = []

    def invoke(self, command: str, params=None):
        self.calls.append((command, params))
        r = self.responses[command]
        if isinstance(r, Exception):
            raise r
        return r


# --- mapping -------------------------------------------------------------
def test_market_mapping():
    m = market_from_json(_row())
    assert m.venue == "dreamdex"
    assert m.market_id == "0xabc"
    assert m.asset == "BTC"
    assert m.status == MarketStatus.TRADING
    assert m.opening_reference == D("100000")
    assert m.pool_address == "0xpool"
    assert m.key == "dreamdex:0xabc"


def test_status_mapping_all_states():
    for raw, want in [
        ("Trading", MarketStatus.TRADING),
        ("Locked", MarketStatus.LOCKED),
        ("Resolved", MarketStatus.RESOLVED),
        ("Voided", MarketStatus.VOIDED),
        ("whatever", MarketStatus.UNKNOWN),
    ]:
        assert market_from_json(_row(status=raw)).status == want


def test_book_mapping_filters_bad_levels():
    book = book_from_json(
        {
            "capturedAt": 123,
            "up": {"asks": [["0.60", "10"], ["0", "5"], ["0.70", "NaN"]], "bids": [["0.58", "3"]]},
            "down": {"asks": [["0.40", "8"]], "bids": []},
        }
    )
    assert len(book.up.asks) == 1  # zero-price and NaN dropped
    assert book.up.asks[0].price == D("0.60")
    assert book.captured_at == 123


# --- identity (pool reuse) ----------------------------------------------
def test_pool_reuse_keeps_markets_distinct():
    bridge = FakeBridge(
        {
            "discover": {
                "markets": [_row("0xAAA", pool="0xshared", nonce="7"), _row("0xBBB", pool="0xshared", nonce="8")]
            }
        }
    )
    adapter = DreamdexAdapter(DreamdexConfig(), bridge=bridge)  # type: ignore[arg-type]
    markets = adapter.list_markets(["BTC"])
    assert {m.market_id for m in markets} == {"0xAAA", "0xBBB"}
    assert {m.key for m in markets} == {"dreamdex:0xAAA", "dreamdex:0xBBB"}
    # Same recycled pool, still two distinct markets.
    assert len({m.pool_address for m in markets}) == 1


def test_fixture_pool_reuse_distinct_markets():
    venue = FixtureVenue(now=1_800_000_000)
    btc = [m for m in venue.list_markets(["BTC"])]
    pools = {m.pool_address for m in btc}
    ids = {m.market_id for m in btc}
    assert len(btc) == 2 and len(ids) == 2 and len(pools) == 1  # shared pool, distinct ids


# --- adapter reads + gating ---------------------------------------------
def test_get_market_uses_fresh_bridge_status():
    bridge = FakeBridge({"market": _row(status="Locked")})
    adapter = DreamdexAdapter(DreamdexConfig(), bridge=bridge)  # type: ignore[arg-type]
    assert adapter.get_market("0xabc").status == MarketStatus.LOCKED
    assert bridge.calls[0][0] == "market"


def test_paper_mode_place_order_refused():
    adapter = DreamdexAdapter(DreamdexConfig(trading_mode=TradingMode.PAPER), bridge=FakeBridge({}))  # type: ignore[arg-type]
    with pytest.raises(PaperModeWrite):
        adapter.place_order(OrderRequest("0xabc", Side.UP, D("5"), D("0.6")))


def test_testnet_place_order_calls_bridge():
    bridge = FakeBridge({"place-order": {"submitted": True, "order": {"orderId": "1"}}})
    adapter = DreamdexAdapter(DreamdexConfig(trading_mode=TradingMode.TESTNET), bridge=bridge)  # type: ignore[arg-type]
    res = adapter.place_order(OrderRequest("0xabc", Side.UP, D("5"), D("0.6")))
    assert res.submitted and not res.paper
    assert bridge.calls[0][0] == "place-order"
    assert bridge.calls[0][1]["side"] == "UP"


def test_bridge_error_propagates_typed():
    bridge = FakeBridge({"market": MarketNotTrading("[MARKET_NOT_TRADING] locked")})
    adapter = DreamdexAdapter(DreamdexConfig(), bridge=bridge)  # type: ignore[arg-type]
    with pytest.raises(MarketNotTrading):
        adapter.get_market("0xabc")


def test_error_for_maps_codes():
    assert isinstance(error_for("MAINNET_DISABLED", "x"), MainnetDisabled)
    assert isinstance(error_for("MARKET_NOT_TRADING", "x"), MarketNotTrading)
    assert isinstance(error_for("PAPER_MODE", "x"), PaperModeWrite)


# --- config / mainnet protection ----------------------------------------
def test_config_defaults_are_paper_testnet():
    cfg = DreamdexConfig.from_env(environ={})
    assert cfg.network == "testnet"
    assert cfg.trading_mode == TradingMode.PAPER
    assert cfg.is_paper is True
    assert cfg.enable_mainnet_trading is False


def test_mainnet_not_enabled_without_explicit_flag():
    cfg = DreamdexConfig.from_env(environ={"NETWORK": "mainnet", "TRADING_MODE": "mainnet"})
    # The flag stays false unless explicitly set -> bridge will refuse the write.
    assert cfg.enable_mainnet_trading is False
    assert cfg.env_for_subprocess()["ENABLE_MAINNET_TRADING"] == "false"


def test_fixture_venue_never_submits():
    venue = FixtureVenue(now=1_800_000_000)
    with pytest.raises(PaperModeWrite):
        venue.place_order(OrderRequest("0x01", Side.UP, D("5"), D("0.6")))
