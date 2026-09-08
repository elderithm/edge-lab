"""Descriptive analytics over a historical mid-price series.

All math is in ``Decimal``. These are *descriptive* statistics of observed
mid-prices — they are not a trading backtest and assume no execution. Volatility
is reported per sampling step (not annualized), because annualizing would
require assuming the sampling interval, which we do not fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import PriceHistory

_Q = Decimal("0.000001")


@dataclass(frozen=True)
class PriceSeriesStats:
    n_points: int
    start_price: Decimal | None
    end_price: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    total_return: Decimal | None  # end/start - 1, as a fraction
    max_drawdown: Decimal | None  # largest peak-to-trough decline, as a fraction (>= 0)
    per_step_return_volatility: Decimal | None  # stdev of simple step returns
    mean_abs_step_return: Decimal | None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "n_points": self.n_points,
            "start_price": s(self.start_price),
            "end_price": s(self.end_price),
            "min_price": s(self.min_price),
            "max_price": s(self.max_price),
            "total_return": s(self.total_return),
            "max_drawdown": s(self.max_drawdown),
            "per_step_return_volatility": s(self.per_step_return_volatility),
            "mean_abs_step_return": s(self.mean_abs_step_return),
            "note": self.note,
        }


def summarize_price_series(history: PriceHistory) -> PriceSeriesStats:
    prices = [p.price for p in history.points]
    n = len(prices)
    if n == 0:
        return PriceSeriesStats(0, None, None, None, None, None, None, None, None, "empty series")
    if n == 1:
        return PriceSeriesStats(
            1,
            prices[0],
            prices[0],
            prices[0],
            prices[0],
            Decimal(0),
            Decimal(0),
            None,
            None,
            "single point: returns/volatility undefined",
        )

    start, end = prices[0], prices[-1]
    total_return = (end / start - Decimal(1)).quantize(_Q) if start > 0 else None

    # Simple step returns; skip steps where the prior price is zero (undefined).
    step_returns: list[Decimal] = []
    for prev, cur in zip(prices, prices[1:], strict=False):
        if prev > 0:
            step_returns.append(cur / prev - Decimal(1))

    volatility = _stdev(step_returns) if len(step_returns) >= 2 else None
    mean_abs = (
        (sum((abs(r) for r in step_returns), Decimal(0)) / Decimal(len(step_returns))).quantize(_Q)
        if step_returns
        else None
    )

    return PriceSeriesStats(
        n_points=n,
        start_price=start,
        end_price=end,
        min_price=min(prices),
        max_price=max(prices),
        total_return=total_return,
        max_drawdown=_max_drawdown(prices),
        per_step_return_volatility=volatility,
        mean_abs_step_return=mean_abs,
    )


def _max_drawdown(prices: list[Decimal]) -> Decimal:
    """Largest peak-to-trough decline as a fraction of the running peak (>= 0)."""
    peak = prices[0]
    max_dd = Decimal(0)
    for price in prices:
        peak = max(peak, price)
        if peak > 0:
            dd = (peak - price) / peak
            max_dd = max(max_dd, dd)
    return max_dd.quantize(_Q)


def _stdev(values: list[Decimal]) -> Decimal:
    """Sample standard deviation in Decimal (no float round-trip)."""
    n = Decimal(len(values))
    mean = sum(values, Decimal(0)) / n
    variance = sum(((v - mean) ** 2 for v in values), Decimal(0)) / (n - Decimal(1))
    return variance.sqrt().quantize(_Q)
