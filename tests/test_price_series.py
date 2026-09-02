"""Descriptive price-series analytics (all Decimal)."""

from __future__ import annotations

from decimal import Decimal

from edge_lab.analysis.price_series import summarize_price_series
from edge_lab.models import PriceHistory, PricePoint

D = Decimal


def hist(prices: list[str]) -> PriceHistory:
    return PriceHistory(
        token_id="tok",
        points=tuple(PricePoint(timestamp=1000 + i * 60, price=Decimal(p)) for i, p in enumerate(prices)),
    )


def test_empty_series():
    s = summarize_price_series(PriceHistory("tok", ()))
    assert s.n_points == 0
    assert s.total_return is None
    assert "empty" in s.note


def test_single_point():
    s = summarize_price_series(hist(["0.5"]))
    assert s.n_points == 1
    assert s.total_return == D("0")
    assert s.per_step_return_volatility is None


def test_total_return_and_min_max():
    s = summarize_price_series(hist(["0.40", "0.50", "0.60"]))
    assert s.start_price == D("0.40")
    assert s.end_price == D("0.60")
    assert s.min_price == D("0.40")
    assert s.max_price == D("0.60")
    assert s.total_return == D("0.5")  # 0.60/0.40 - 1


def test_max_drawdown_fraction():
    # peak 1.00 then 0.75 -> drawdown 0.25
    s = summarize_price_series(hist(["0.80", "1.00", "0.75", "0.90"]))
    assert s.max_drawdown == D("0.25")


def test_no_drawdown_when_monotonic():
    s = summarize_price_series(hist(["0.10", "0.20", "0.30"]))
    assert s.max_drawdown == D("0")


def test_volatility_is_decimal_and_positive():
    s = summarize_price_series(hist(["0.50", "0.55", "0.50", "0.55", "0.50"]))
    assert s.per_step_return_volatility is not None
    assert isinstance(s.per_step_return_volatility, Decimal)
    assert s.per_step_return_volatility > 0


def test_constant_series_has_zero_volatility():
    s = summarize_price_series(hist(["0.50", "0.50", "0.50"]))
    assert s.per_step_return_volatility == D("0")
    assert s.total_return == D("0")
