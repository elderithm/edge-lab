"""Numeric/timestamp normalization edge cases (untrusted external input)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from edge_lab.errors import DataError
from edge_lab.models import WalletActivity, safe_decimal, to_decimal


def test_to_decimal_basic():
    assert to_decimal("0.42") == Decimal("0.42")
    assert to_decimal(100) == Decimal("100")
    assert to_decimal(None) is None
    assert to_decimal("") is None


def test_to_decimal_rejects_bool():
    with pytest.raises(DataError):
        to_decimal(True)


@pytest.mark.parametrize("bad", ["NaN", "nan", "Infinity", "inf", "-inf", "sNaN"])
def test_to_decimal_rejects_non_finite(bad):
    # These parse as Decimal but would poison money math; must be rejected.
    with pytest.raises(DataError):
        to_decimal(bad)


def test_to_decimal_rejects_non_finite_decimal_input():
    with pytest.raises(DataError):
        to_decimal(Decimal("NaN"))


def test_to_decimal_garbage_raises():
    with pytest.raises(DataError):
        to_decimal("abc")


def test_safe_decimal_degrades_to_none():
    assert safe_decimal("NaN") is None
    assert safe_decimal("abc") is None
    assert safe_decimal("0.5") == Decimal("0.5")


def test_activity_with_nan_price_becomes_none():
    # A non-finite price in one row must not crash the whole page parse.
    act = WalletActivity.from_api({"asset": "1", "side": "BUY", "type": "TRADE", "price": "NaN", "size": "10"})
    assert act.price is None
    assert act.size == Decimal("10")
