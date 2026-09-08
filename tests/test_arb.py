"""Arbitrage math on synthetic order books (all Decimal)."""

from __future__ import annotations

from decimal import Decimal

from helpers import book, make_market

from edge_lab.analysis.arb import analyze_complete_set, walk_asks

D = Decimal


def quote(yes_book, no_book, *, notional="10", fee="50", slip="50", min_edge="25"):
    return analyze_complete_set(
        make_market(),
        yes_book,
        no_book,
        notional=D(notional),
        fee_buffer_bps=D(fee),
        slippage_buffer_bps=D(slip),
        min_edge_bps=D(min_edge),
    )


def test_walk_asks_multi_level_vwap():
    b = book("t", [], [("0.40", "2"), ("0.50", "2")])
    fill = walk_asks(b.asks, D("3"))
    assert fill.quantity == D("3")
    assert fill.cost == D("0.40") * 2 + D("0.50") * 1  # 1.30
    assert fill.vwap == (D("1.30") / D("3"))
    assert fill.fully_filled


def test_walk_asks_insufficient_depth():
    b = book("t", [], [("0.40", "1")])
    fill = walk_asks(b.asks, D("5"))
    assert not fill.fully_filled
    assert fill.quantity == D("1")


def test_top_of_book_apparent_but_insufficient_size():
    # Tiny top level looks like a huge edge; real depth is priced against us.
    yes = book("y", [], [("0.45", "1"), ("0.60", "100")])
    no = book("n", [], [("0.45", "1"), ("0.60", "100")])
    r = quote(yes, no, notional="10")
    assert r.top_of_book_sum == D("0.90")  # apparent 1000bps at the top
    assert not r.is_candidate  # size-aware edge is gone
    assert r.net_edge_bps < D("25")


def test_notional_is_budget_not_share_count():
    # $10 budget at $0.60 per complete set buys ~16.6 sets, not 10.
    yes = book("y", [], [("0.30", "1000")])
    no = book("n", [], [("0.30", "1000")])
    r = quote(yes, no, notional="10")
    assert r.notional_budget == D("10")
    assert r.executable_quantity > D("16")  # more sets than dollars, since sets cost < $1
    # Deployed cost stays within budget.
    assert r.yes_cost + r.no_cost <= D("10")


def test_multi_level_true_edge():
    yes = book("y", [], [("0.30", "100")])
    no = book("n", [], [("0.30", "100")])
    r = quote(yes, no, notional="10")
    assert r.cost_per_set == D("0.60")
    assert r.gross_edge_bps == D("4000.0000")
    assert r.net_edge_bps == D("3900.0000")
    assert r.is_candidate
    # ~16.67 sets fit in a $10 budget at $0.60/set.
    assert D("16") < r.executable_quantity < D("17")


def test_no_edge_after_buffer():
    yes = book("y", [], [("0.49", "100")])
    no = book("n", [], [("0.49", "100")])
    r = quote(yes, no, fee="100", slip="100")  # gross 200bps, buffers 200bps
    assert r.gross_edge_bps == D("200.0000")
    assert r.net_edge_bps == D("0.0000")
    assert not r.is_candidate


def test_insufficient_liquidity_never_labeled_arb():
    yes = book("y", [], [])
    no = book("n", [], [("0.30", "100")])
    r = quote(yes, no)
    assert not r.is_candidate
    assert "insufficient_liquidity" in r.note


def test_yes_and_no_costs_are_side_specific():
    yes = book("y", [], [("0.20", "100")])
    no = book("n", [], [("0.70", "100")])
    r = quote(yes, no, notional="5")
    assert r.yes_vwap == D("0.20")
    assert r.no_vwap == D("0.70")
    assert r.cost_per_set == D("0.90")


def test_max_size_at_min_edge_reported():
    yes = book("y", [], [("0.30", "50"), ("0.55", "50")])
    no = book("n", [], [("0.30", "50"), ("0.55", "50")])
    r = quote(yes, no, notional="100", min_edge="500")
    # Deep fills erode edge; there is a finite max size clearing 500bps.
    assert r.max_size_at_min_edge is not None
    assert r.max_size_at_min_edge > 0
