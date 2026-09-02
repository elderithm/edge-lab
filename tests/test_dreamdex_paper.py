"""DreamDEX paper store + strategy end-to-end (fixtures, no wallet) (§50)."""

from __future__ import annotations

from decimal import Decimal

from edge_lab.core.risk import RiskConfig, RiskEngine
from edge_lab.core.types import Side, SignalState
from edge_lab.paper.dreamdex_paper import DreamdexPaperDB
from edge_lab.strategies.event_contracts import build_event_signal
from edge_lab.venues.dreamdex.fixtures import FixtureVenue

D = Decimal
NOW = 1_800_000_000

BTC_A = "0x0000000000000000000000000000000000000000000000000000000000000001"
ETH = "0x0000000000000000000000000000000000000000000000000000000000000010"


def _signal(venue, market_id, size="10", engine=None):
    market = venue.get_market(market_id)
    book = venue.get_order_book(market_id)
    underlying = venue.get_underlying(market.asset)
    return build_event_signal(market, book, underlying, size=D(size), now=venue.now, risk_engine=engine or RiskEngine())


def test_fixture_btc_is_actionable_buy_up():
    venue = FixtureVenue(NOW)
    sig = _signal(venue, BTC_A)
    assert sig.state == SignalState.BUY_UP
    assert sig.risk.side == Side.UP
    assert sig.rank_score > 0


def test_fixture_eth_low_confidence_or_no_edge():
    venue = FixtureVenue(NOW)
    sig = _signal(venue, ETH)
    assert not sig.risk.is_actionable  # ETH fixture is intentionally not a clean edge


def test_paper_record_and_settle_win(tmp_path):
    venue = FixtureVenue(NOW)
    sig = _signal(venue, BTC_A)
    with DreamdexPaperDB(tmp_path / "d.db") as db:
        tid = db.record_trade(
            venue="dreamdex",
            market_id=sig.market.market_id,
            asset=sig.market.asset,
            symbol=sig.market.symbol,
            side=sig.risk.side,
            model_p=sig.probability.p_up,
            exec_price=sig.risk.price,
            edge_bps=sig.risk.edge_bps,
            size=sig.risk.allowed_size,
            confidence=sig.probability.confidence,
            mode="paper",
        )
        pnl = db.settle_trade(tid, "UP")  # Up wins
        # bought allowed_size at exec price -> win pnl = size - notional > 0
        assert pnl > 0
        summary = db.summary()
        assert summary["settled"] == 1
        assert Decimal(summary["realized_pnl"]) == pnl


def test_paper_settle_loss_and_void(tmp_path):
    with DreamdexPaperDB(tmp_path / "d.db") as db:
        tid = db.record_trade(
            venue="dreamdex",
            market_id="0x1",
            asset="BTC",
            symbol="s",
            side=Side.UP,
            model_p=D("0.7"),
            exec_price=D("0.6"),
            edge_bps=D("100"),
            size=D("10"),
            confidence=D("0.7"),
            mode="paper",
        )
        loss = db.settle_trade(tid, "DOWN")  # Up bet, Down happened
        assert loss == D("-6.000000")  # -notional (10*0.6)

        tid2 = db.record_trade(
            venue="dreamdex",
            market_id="0x2",
            asset="BTC",
            symbol="s",
            side=Side.UP,
            model_p=D("0.7"),
            exec_price=D("0.6"),
            edge_bps=D("100"),
            size=D("10"),
            confidence=D("0.7"),
            mode="paper",
        )
        void = db.settle_trade(tid2, "VOID")
        assert void == D("0")
        summary = db.summary()
        assert summary["void"] == 1 and summary["settled"] == 1


def test_paper_persists_across_reopen(tmp_path):
    path = tmp_path / "d.db"
    with DreamdexPaperDB(path) as db:
        db.record_trade(
            venue="dreamdex",
            market_id="0x1",
            asset="BTC",
            symbol="s",
            side=Side.UP,
            model_p=D("0.7"),
            exec_price=D("0.6"),
            edge_bps=D("100"),
            size=D("10"),
            confidence=D("0.7"),
            mode="paper",
        )
    with DreamdexPaperDB(path) as db2:
        assert len(db2.list_trades()) == 1


def test_min_edge_threshold_blocks_marginal_edge():
    venue = FixtureVenue(NOW)
    strict = RiskEngine(RiskConfig(min_edge_bps=D("100000")))  # absurd threshold
    sig = _signal(venue, BTC_A, engine=strict)
    assert sig.state == SignalState.NO_EDGE
