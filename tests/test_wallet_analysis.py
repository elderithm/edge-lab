"""Wallet analysis: timezone bins, classification, buckets, empty input."""

from __future__ import annotations

from decimal import Decimal

from helpers import activity

from edge_lab.analysis.wallet import analyze_wallet


def test_no_records():
    result = analyze_wallet([])
    assert result.record_count == 0
    assert result.time_range is None
    assert result.hour_local == {}
    assert any("small sample" in w for w in result.warnings)


def test_timezone_conversion_shifts_hour():
    # 2026-01-01 00:00:00 UTC -> 09:00 at UTC+9.
    a = activity(timestamp=1_767_225_600)
    utc = analyze_wallet([a], utc_offset_hours=0)
    jst = analyze_wallet([a], utc_offset_hours=9)
    assert utc.hour_utc[0] == 1
    assert jst.hour_local[9] == 1


def test_hour_bin_crosses_utc_date_boundary():
    # 2026-01-01 22:00 UTC -> 07:00 next day at UTC+9; hour bin is 7.
    a = activity(timestamp=1_767_304_800)  # 2026-01-01 22:00:00 UTC
    jst = analyze_wallet([a], utc_offset_hours=9)
    assert jst.hour_local[7] == 1


def test_buy_sell_classification():
    acts = [activity(side="BUY"), activity(side="SELL"), activity(side="SELL"), activity(side="")]
    r = analyze_wallet(acts)
    assert r.buy_count == 1
    assert r.sell_count == 2
    assert r.other_side_count == 1


def test_price_buckets():
    acts = [activity(price=Decimal("0.05")), activity(price=Decimal("0.85")), activity(price=Decimal("0.95"))]
    r = analyze_wallet(acts)
    assert r.price_buckets["<0.10"] == 1
    assert r.price_buckets["0.80-0.90"] == 1
    assert r.price_buckets[">=0.90"] == 1


def test_concentration_and_notional():
    acts = [
        activity(title="Alpha", usdc_size=Decimal("100")),
        activity(title="Alpha", usdc_size=Decimal("200")),
        activity(title="Beta", usdc_size=Decimal("5")),
    ]
    r = analyze_wallet(acts)
    assert r.market_concentration[0] == ("Alpha", 2)
    assert r.observed_notional == Decimal("305")


def test_window_share():
    acts = [activity(timestamp=1_767_225_600)]  # 09:00 JST
    r = analyze_wallet(acts, utc_offset_hours=9)
    assert r.window_share(6, 9) == Decimal("1.0000")
    assert r.window_share(10, 12) == Decimal("0")


def test_window_share_wraps_midnight():
    # 22:00 UTC -> 07:00 JST is inside a 22->2 window? No; but 00:00 UTC -> 09:00.
    # Use a trade at 23:00 UTC == 08:00 JST and window 22-2 (should be outside),
    # and a trade at 15:00 UTC == 00:00 JST (should be inside a 22-2 wrap window).
    a_inside = activity(timestamp=1_767_279_600)  # 2026-01-01 15:00 UTC -> 00:00 JST
    r = analyze_wallet([a_inside], utc_offset_hours=9)
    assert r.window_share(22, 2) == Decimal("1.0000")  # 00:00 is inside 22->2
    assert r.window_share(3, 21) == Decimal("0")


def test_window_claim_reports_inside_outside():
    acts = [activity(timestamp=1_767_225_600), activity(timestamp=1_767_279_600, tx_hash="0x2")]
    # 09:00 JST and 00:00 JST
    r = analyze_wallet(acts, utc_offset_hours=9)
    claim = r.window_claim(6, 12)
    assert claim["inside_count"] == 1
    assert claim["outside_count"] == 1
    assert claim["inside_pct"] == "50.0"
    assert claim["outside_pct"] == "50.0"


def test_parse_claim_window():
    from edge_lab.analysis.wallet import parse_claim_window

    assert parse_claim_window("6-9") == (6, 9)
    for bad in ("6", "6-9-12", "a-9", "6-99"):
        with __import__("pytest").raises(ValueError):
            parse_claim_window(bad)


def test_missing_timestamp_excluded_from_time_analysis():
    acts = [activity(timestamp=None), activity(timestamp=1_767_225_600)]
    r = analyze_wallet(acts)
    assert r.dated_count == 1
    assert any("timestamp" in w for w in r.warnings)
