"""Paper follower: skips, fills, exits, oversell guard, persistence, report."""

from __future__ import annotations

from decimal import Decimal

from helpers import FakeBooks, activity, book

from edge_lab.paper.db import PaperDB
from edge_lab.paper.follower import FollowConfig, PaperFollower
from edge_lab.paper.report import build_report

D = Decimal
NOW = 1_767_225_700  # 100s after the default activity timestamp


def follower(db, books, cfg=None):
    rid = db.create_run("0xwallet", "{}")
    return PaperFollower(db, books, rid, cfg or FollowConfig(paper_usdc=D("10"), max_age_seconds=120)), rid


def yes_books(asks=None, bids=None):
    return FakeBooks({"yes-token": book("yes-token", bids or [], asks or [("0.50", "1000")])})


def test_buy_fill_creates_position(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, yes_books())
    out = f.process_activities([activity(side="BUY", price=D("0.50"))], NOW)
    assert out[0].disposition == "filled"
    pos = db.get_position(rid, "yes-token")
    assert pos.quantity == D("20")  # $10 / $0.50
    assert pos.avg_price == D("0.50")
    db.close()


def test_duplicate_signal_skipped(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, _ = follower(db, yes_books())
    a = activity(side="BUY", price=D("0.50"))
    f.process_activities([a], NOW)
    out = f.process_activities([a], NOW)
    assert out[0].disposition == "duplicate"
    db.close()


def test_stale_signal_skipped(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, yes_books())
    out = f.process_activities([activity(side="BUY", timestamp=NOW - 10_000)], NOW)
    assert out[0].reason == "signal_too_old"
    assert db.get_position(rid, "yes-token").quantity == 0
    db.close()


def test_price_drift_too_large_skipped(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, _ = follower(db, yes_books(asks=[("0.50", "1000")]), FollowConfig(paper_usdc=D("10"), max_drift_bps=D("100")))
    out = f.process_activities([activity(side="BUY", price=D("0.10"))], NOW)  # book 0.50 vs source 0.10
    assert out[0].reason == "price_drift_too_large"
    db.close()


def test_missing_token_and_price(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, _ = follower(db, yes_books())
    out = f.process_activities([activity(asset="", side="BUY")], NOW)
    assert out[0].reason == "missing_token_id"
    out2 = f.process_activities([activity(side="BUY", price=None, tx_hash="0xother")], NOW)
    assert out2[0].reason == "missing_source_price"
    db.close()


def test_insufficient_liquidity(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, _ = follower(db, yes_books(asks=[("0.50", "1")]))  # only $0.50 of depth, need $10
    out = f.process_activities([activity(side="BUY", price=D("0.50"))], NOW)
    assert out[0].reason == "insufficient_liquidity"
    db.close()


def test_full_sell_realizes_pnl(tmp_path):
    books = FakeBooks({"yes-token": book("yes-token", [("0.60", "1000")], [("0.50", "1000")])})
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, books)
    f.process_activities([activity(side="BUY", price=D("0.50"), tx_hash="0xbuy")], NOW)
    out = f.process_activities([activity(side="SELL", price=D("0.60"), tx_hash="0xsell")], NOW)
    assert out[0].disposition == "filled"
    assert db.get_position(rid, "yes-token").quantity == 0
    closures = db.closures(rid)
    assert Decimal(closures[0]["realized_pnl"]) == D("2.0")  # (0.60-0.50)*20


def test_partial_sell_keeps_remainder(tmp_path):
    books = FakeBooks({"yes-token": book("yes-token", [("0.60", "5")], [("0.50", "1000")])})
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, books)
    f.process_activities([activity(side="BUY", price=D("0.50"), tx_hash="0xbuy")], NOW)
    f.process_activities([activity(side="SELL", price=D("0.60"), tx_hash="0xsell")], NOW)
    pos = db.get_position(rid, "yes-token")
    assert pos.quantity == D("15")  # sold only 5 of 20


def test_cannot_sell_more_than_owned(tmp_path):
    # Deep bids, but paper position is only 20 shares.
    books = FakeBooks({"yes-token": book("yes-token", [("0.60", "100000")], [("0.50", "1000")])})
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, books)
    f.process_activities([activity(side="BUY", price=D("0.50"), tx_hash="0xbuy")], NOW)
    f.process_activities([activity(side="SELL", price=D("0.60"), tx_hash="0xsell")], NOW)
    fills = [dict(r) for r in db.fills(rid)]
    sell = [f for f in fills if f["side"] == "SELL"][0]
    assert Decimal(sell["quantity"]) == D("20")


def test_sell_without_position_is_invalid_state(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, _ = follower(db, yes_books(bids=[("0.60", "100")]))
    out = f.process_activities([activity(side="SELL", price=D("0.60"))], NOW)
    assert out[0].reason == "invalid_market_state"
    db.close()


def test_persistence_across_reload(tmp_path):
    path = tmp_path / "p.db"
    db = PaperDB(path)
    f, rid = follower(db, yes_books())
    a = activity(side="BUY", price=D("0.50"))
    f.process_activities([a], NOW)
    db.close()

    db2 = PaperDB(path)
    assert db2.get_position(rid, "yes-token").quantity == D("20")
    assert db2.has_signal(rid, a.signal_id)  # dedup survives restart
    db2.close()


def test_report_separates_realized_and_unrealized(tmp_path):
    books = FakeBooks({"yes-token": book("yes-token", [("0.60", "5")], [("0.50", "1000")])})
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, books)
    f.process_activities([activity(side="BUY", price=D("0.50"), tx_hash="0xbuy")], NOW)
    f.process_activities([activity(side="SELL", price=D("0.60"), tx_hash="0xsell")], NOW)

    # Mark remaining 15 shares at 0.70 -> unrealized (0.70-0.50)*15 = 3.0.
    report = build_report(db, rid, price_provider=lambda _t: D("0.70"))
    assert report.realized_pnl == D("0.5")  # (0.60-0.50)*5
    assert report.unrealized_pnl == D("3.0")
    assert report.total_net_pnl == D("3.5")
    assert report.signals_filled == 2


def test_atomic_rolls_back_partial_writes(tmp_path):
    # A failure inside atomic() must leave none of the grouped writes committed.
    db = PaperDB(tmp_path / "p.db")
    rid = db.create_run("0xw", "{}")
    try:
        with db.atomic():
            db.record_signal(
                run_id=rid,
                signal_id="sig1",
                observed_at=NOW,
                source_ts=NOW,
                asset="yes-token",
                side="BUY",
                source_price=D("0.5"),
                source_size=D("10"),
                title="t",
                outcome="Yes",
                tx_hash="0x",
                disposition="filled",
                skip_reason=None,
            )
            raise RuntimeError("boom before position write")
    except RuntimeError:
        pass
    assert not db.has_signal(rid, "sig1")  # rolled back
    db.close()


def test_atomic_commits_on_success(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    rid = db.create_run("0xw", "{}")
    with db.atomic():
        db.record_signal(
            run_id=rid,
            signal_id="sig1",
            observed_at=NOW,
            source_ts=NOW,
            asset="yes-token",
            side="BUY",
            source_price=D("0.5"),
            source_size=D("10"),
            title="t",
            outcome="Yes",
            tx_hash="0x",
            disposition="skipped",
            skip_reason="signal_too_old",
        )
    assert db.has_signal(rid, "sig1")  # committed
    db.close()


def test_walk_for_notional_skips_zero_price_level():
    from edge_lab.paper.follower import walk_for_notional

    # A zero-price level must be skipped, not cause a division-by-zero crash.
    levels = book("t", [], [("0", "100"), ("0.50", "1000")]).asks
    fill = walk_for_notional(levels, D("10"))
    assert fill.fully_filled
    assert fill.quantity == D("20")  # filled entirely from the valid 0.50 level
    assert fill.vwap == D("0.50")


def test_max_realized_drawdown_pure():
    from edge_lab.paper.report import _max_realized_drawdown

    # cumulative: +5, +3 (dd 2), +8, +2 (dd 6) -> max dd 6
    increments = [D("5"), D("-2"), D("5"), D("-6")]
    assert _max_realized_drawdown(increments) == D("6")
    # monotonically rising -> no drawdown
    assert _max_realized_drawdown([D("1"), D("2"), D("3")]) == D("0")
    assert _max_realized_drawdown([]) == D("0")


def test_report_max_drawdown_from_closures(tmp_path):
    # Two round-trips: first a win, then a loss -> realized curve draws down.
    books_win = FakeBooks({"yes-token": book("yes-token", [("0.70", "1000")], [("0.50", "1000")])})
    books_loss = FakeBooks({"no-token": book("no-token", [("0.30", "1000")], [("0.50", "1000")])})
    db = PaperDB(tmp_path / "p.db")
    rid = db.create_run("0xwallet", "{}")
    fw = PaperFollower(db, books_win, rid, FollowConfig(paper_usdc=D("10"), max_age_seconds=120))
    fw.process_activities([activity(side="BUY", asset="yes-token", price=D("0.50"), tx_hash="0xb1")], NOW)
    fw.process_activities([activity(side="SELL", asset="yes-token", price=D("0.70"), tx_hash="0xs1")], NOW)
    fl = PaperFollower(db, books_loss, rid, FollowConfig(paper_usdc=D("10"), max_age_seconds=120))
    fl.process_activities([activity(side="BUY", asset="no-token", price=D("0.50"), tx_hash="0xb2")], NOW)
    fl.process_activities([activity(side="SELL", asset="no-token", price=D("0.30"), tx_hash="0xs2")], NOW)

    report = build_report(db, rid, price_provider=lambda _t: None)
    # win: (0.70-0.50)*20 = +4 ; loss: (0.30-0.50)*20 = -4 ; peak +4, trough 0 -> dd 4
    assert report.realized_pnl == D("0")
    assert report.max_realized_drawdown == D("4")
    db.close()


def test_report_unrealized_unknown_when_no_price(tmp_path):
    db = PaperDB(tmp_path / "p.db")
    f, rid = follower(db, yes_books())
    f.process_activities([activity(side="BUY", price=D("0.50"))], NOW)
    report = build_report(db, rid, price_provider=lambda _t: None)
    assert report.unrealized_pnl is None
    assert report.total_net_pnl is None
    assert not report.unrealized_known
    db.close()
