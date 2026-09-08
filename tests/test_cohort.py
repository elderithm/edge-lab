"""Cross-wallet cohort comparison (pure)."""

from __future__ import annotations

from decimal import Decimal

from helpers import activity

from edge_lab.analysis.cohort import build_cohort
from edge_lab.analysis.wallet import analyze_wallet

D = Decimal


def analysis_for(acts, offset=0):
    return analyze_wallet(acts, utc_offset_hours=offset)


def test_cohort_rows_and_ratio():
    a = analysis_for([activity(side="BUY"), activity(side="BUY", tx_hash="0x2"), activity(side="SELL", tx_hash="0x3")])
    b = analysis_for([activity(side="BUY"), activity(side="SELL", tx_hash="0x4")])
    cohort = build_cohort([("0xA", a), ("0xB", b)])
    assert len(cohort.rows) == 2
    assert cohort.rows[0].buy_sell_ratio == D("2.0000")  # 2 buys / 1 sell
    assert cohort.rows[1].buy_sell_ratio == D("1.0000")


def test_cohort_ratio_none_when_no_sells():
    a = analysis_for([activity(side="BUY"), activity(side="BUY", tx_hash="0x2")])
    cohort = build_cohort([("0xA", a)])
    assert cohort.rows[0].buy_sell_ratio is None


def test_cohort_top_market_share():
    a = analysis_for(
        [activity(title="Alpha"), activity(title="Alpha", tx_hash="0x2"), activity(title="Beta", tx_hash="0x3")]
    )
    cohort = build_cohort([("0xA", a)])
    assert cohort.rows[0].top_market == "Alpha"
    assert cohort.rows[0].top_market_share == D("0.6667")  # 2/3


def test_cohort_window_share():
    # 09:00 JST trade; window 6-9 should capture it.
    a = analysis_for([activity(timestamp=1_767_225_600)], offset=9)
    cohort = build_cohort([("0xA", a)], utc_offset_hours=9, claim_window=(6, 9))
    assert cohort.rows[0].window_share == D("1.0000")


def test_cohort_warns_on_single_wallet_and_empty():
    empty = analysis_for([])
    cohort = build_cohort([("0xA", empty)])
    assert any("2+" in w for w in cohort.warnings)
    assert any("no activity" in w for w in cohort.warnings)


def test_cohort_to_dict_shape():
    a = analysis_for([activity(side="BUY")])
    d = build_cohort([("0xA", a)], claim_window=(6, 9)).to_dict()
    assert d["cohort_size"] == 1
    assert d["claim_window"] == "06:00-09:59"
    assert d["wallets"][0]["address"] == "0xA"
