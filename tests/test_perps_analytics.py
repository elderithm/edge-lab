"""Perps analytics: funding, basis, liquidity, execution cost, volatility, margin, assessment."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from perps_helpers import NOW, live_btc_snapshot, snapshot, with_book

from edge_lab.perps.analytics import (
    AssessmentThresholds,
    Category,
    assess_market,
    basis_metrics,
    estimate_margin,
    funding_metrics,
    liquidity_metrics,
    rank,
    volatility_metrics,
    walk_book,
)
from edge_lab.venues.dreamdex_perps.fixtures import FixturePerpsVenue
from edge_lab.venues.dreamdex_perps.models import BookLevel, PerpSide

D = Decimal


def test_funding_normalization_uses_window_not_hardcoded():
    f = funding_metrics(snapshot(funding_rate=D("0.0008")), NOW)
    assert f.rate_per_interval == D("0.0001")  # 0.0008 per 8h window, 1h interval
    assert f.rate_per_hour == D("0.0001")
    assert f.annualized == D("0.0008") * 365 * 24 * 3600 / 28800
    assert f.direction == "LONGS_PAY"
    assert f.holding_cost(PerpSide.LONG, D(1000), D(8)) == D("0.8")
    assert f.holding_cost(PerpSide.SHORT, D(1000), D(8)) == D("-0.8")


def test_funding_missing_reported():
    f = funding_metrics(snapshot(funding_rate=None), NOW)
    assert f.direction == "UNKNOWN" and f.annualized is None
    assert "funding_rate" in f.missing


def test_basis():
    s = snapshot(mid=D(100))
    s = replace(s, state=replace(s.state, mark_price=D("100.2")))
    b = basis_metrics(s, NOW)
    assert b.absolute == D("0.2")
    assert b.bps == D(20)


def test_spread_and_depth_band():
    liq = liquidity_metrics(snapshot(mid=D(100), half_spread=D("0.05")).book, D(50))
    assert liq.mid == D(100)
    assert liq.spread == D("0.1")
    assert liq.spread_bps == D(10)
    assert liq.bid_depth_quote > 0 and liq.ask_depth_quote > 0


def test_walk_book_multi_level_average_and_partial():
    s = with_book(
        snapshot(),
        bids=(BookLevel(D(99), D(1)),),
        asks=(BookLevel(D(101), D(1)), BookLevel(D(103), D(1))),
    )
    est = walk_book(s.book, PerpSide.LONG, D(2), D(1))
    assert est.fully_filled and est.avg_price == D(102) and est.worst_price == D(103)
    assert est.slippage_bps == D(200)  # avg 102 vs mid 100
    assert est.impact_bps is not None and est.impact_bps > 0
    assert est.total_cost_bps == D(201)
    part = walk_book(s.book, PerpSide.LONG, D(5))
    assert not part.fully_filled and part.filled_qty == D(2)


def test_volatility_ok_and_insufficient():
    assert volatility_metrics(snapshot(candles=40)).status == "OK"
    v = volatility_metrics(snapshot(candles=5))
    assert v.status == "INSUFFICIENT_DATA" and v.sigma_interval is None
    assert v.sigma_over(D(24)) is None  # never substitutes a fake volatility


def test_volatility_skips_gaps():
    s = snapshot(candles=40)
    holes = tuple(c for i, c in enumerate(s.candles) if i % 2 == 0)
    v = volatility_metrics(replace(s, candles=holes))
    assert v.status == "INSUFFICIENT_DATA" and v.gaps_skipped > 0


def test_margin_and_estimated_liquidation_long_short():
    long = estimate_margin(
        PerpSide.LONG, D(1), D(100), initial_margin_bps=D(500), maintenance_margin_bps=D(250), equity=D(10)
    )
    assert long.notional == D(100) and long.initial_margin == D(5) and long.effective_leverage == D(10)
    # (100 - 10) / (1 * 0.975)
    assert long.est_liquidation_price.quantize(D("0.0001")) == D("92.3077")
    short = estimate_margin(
        PerpSide.SHORT, D(1), D(100), initial_margin_bps=D(500), maintenance_margin_bps=D(250), equity=D(10)
    )
    assert short.est_liquidation_price.quantize(D("0.0001")) == D("107.3171")
    assert "ESTIMATE" in long.to_dict()["label"]
    one_x = estimate_margin(
        PerpSide.LONG, D(1), D(100), initial_margin_bps=D(500), maintenance_margin_bps=D(250), equity=D(100)
    )
    assert one_x.est_liquidation_price == D(0)


def test_assessment_categories():
    assert assess_market(snapshot(mark_ok=False), NOW).category == Category.STALE_DATA
    assert assess_market(snapshot(captured_at=NOW - 120), NOW).category == Category.STALE_DATA
    no_asks = with_book(snapshot(), bids=snapshot().book.bids, asks=())
    assert assess_market(no_asks, NOW).category == Category.INSUFFICIENT_DATA
    thin = snapshot(level_qty=D("0.01"))
    assert assess_market(thin, NOW).category == Category.INSUFFICIENT_LIQUIDITY
    wide = snapshot(half_spread=D("0.5"))  # 100bps spread
    assert assess_market(wide, NOW).category == Category.HIGH_EXECUTION_COST
    hot = snapshot(funding_rate=D("0.001"))  # ~110%/yr
    a = assess_market(hot, NOW)
    assert a.category == Category.REVIEW and any("funding" in r for r in a.reasons)
    calm = snapshot(funding_rate=D("0.00001"))
    assert assess_market(calm, NOW).category == Category.WATCH


def test_high_liquidation_risk_needs_leverage_and_volatility():
    th = AssessmentThresholds(analysis_leverage=D(20), min_liquidation_z=D(1000))
    assert assess_market(snapshot(funding_rate=D(0)), NOW, th).category == Category.HIGH_LIQUIDATION_RISK


def test_expected_edge_never_claimed():
    d = assess_market(snapshot(funding_rate=D("0.002")), NOW).to_dict()
    assert d["expected_edge"]["status"] == "NOT_ESTIMATED"


def test_rank_published_order():
    v = FixturePerpsVenue(NOW)
    snaps, _ = v.snapshots()
    ranked = rank([assess_market(s, NOW) for s in snaps])
    order = [a.category for a in ranked]
    assert order.index(Category.REVIEW) < order.index(Category.WATCH) < order.index(Category.HIGH_EXECUTION_COST)


def test_live_captured_snapshot_assesses():
    a = assess_market(live_btc_snapshot(), NOW)
    assert a.category in {Category.WATCH, Category.REVIEW}
    assert a.round_trip_cost_bps is not None and a.round_trip_cost_bps < 30
    assert a.to_dict()["source"] == "LIVE_TESTNET"


def test_fixture_is_labeled_simulated():
    snaps, _ = FixturePerpsVenue(NOW).snapshots()
    assert all(s.source.value == "SIMULATED_FIXTURE" for s in snaps)
    assert all("SIMULATED" in " ".join(s.warnings) for s in snaps)
