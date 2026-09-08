"""Behavioral analysis of a wallet's public activity.

All functions are pure: they take domain objects and return result objects,
independent of the CLI or network. Entry prices and sizes stay in ``Decimal``.
Timezone conversion happens here (never implicitly via local time).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from ..models import WalletActivity, iso_utc

# Entry-price bucket edges in [0, 1]; labels are half-open [lo, hi).
_PRICE_BUCKETS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("<0.10", Decimal("0.0"), Decimal("0.10")),
    ("0.10-0.20", Decimal("0.10"), Decimal("0.20")),
    ("0.20-0.30", Decimal("0.20"), Decimal("0.30")),
    ("0.30-0.40", Decimal("0.30"), Decimal("0.40")),
    ("0.40-0.50", Decimal("0.40"), Decimal("0.50")),
    ("0.50-0.60", Decimal("0.50"), Decimal("0.60")),
    ("0.60-0.70", Decimal("0.60"), Decimal("0.70")),
    ("0.70-0.80", Decimal("0.70"), Decimal("0.80")),
    ("0.80-0.90", Decimal("0.80"), Decimal("0.90")),
    (">=0.90", Decimal("0.90"), Decimal("1.0000001")),
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class WalletAnalysis:
    record_count: int
    dated_count: int
    time_range: tuple[int, int] | None
    utc_offset_hours: int
    hour_utc: dict[int, int]
    hour_local: dict[int, int]
    weekday_local: dict[str, int]
    buy_count: int
    sell_count: int
    other_side_count: int
    observed_notional: Decimal
    market_concentration: list[tuple[str, int]]
    outcome_concentration: list[tuple[str, int]]
    price_buckets: dict[str, int]
    notional_buckets: dict[str, int]
    warnings: list[str] = field(default_factory=list)

    def window_share(self, start_hour: int, end_hour: int) -> Decimal:
        """Fraction of dated trades whose local hour is in [start, end].

        The window is inclusive of both endpoints and may wrap past midnight
        (e.g. ``22`` → ``2`` covers 22, 23, 0, 1, 2).
        """
        if self.dated_count == 0:
            return Decimal(0)
        inside = sum(c for h, c in self.hour_local.items() if _hour_in_window(h, start_hour, end_hour))
        return (Decimal(inside) / Decimal(self.dated_count)).quantize(Decimal("0.0001"))

    def window_claim(self, start_hour: int, end_hour: int) -> dict[str, object]:
        """Evaluate a 'trades mainly between START and END' claim on the data."""
        if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
            raise ValueError("hours must be in 0..23")
        inside_share = self.window_share(start_hour, end_hour)
        inside_count = sum(c for h, c in self.hour_local.items() if _hour_in_window(h, start_hour, end_hour))
        return {
            "window_local": f"{start_hour:02d}:00-{end_hour:02d}:59",
            "utc_offset_hours": self.utc_offset_hours,
            "dated_count": self.dated_count,
            "inside_count": inside_count,
            "outside_count": self.dated_count - inside_count,
            "inside_pct": str((inside_share * 100).quantize(Decimal("0.1"))),
            "outside_pct": str(((Decimal(1) - inside_share) * 100).quantize(Decimal("0.1"))),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "dated_count": self.dated_count,
            "time_range_utc": ([iso_utc(self.time_range[0]), iso_utc(self.time_range[1])] if self.time_range else None),
            "utc_offset_hours": self.utc_offset_hours,
            "hour_utc": {str(k): v for k, v in sorted(self.hour_utc.items())},
            "hour_local": {str(k): v for k, v in sorted(self.hour_local.items())},
            "weekday_local": self.weekday_local,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "other_side_count": self.other_side_count,
            "observed_notional": str(self.observed_notional),
            "market_concentration": [{"market": m, "count": c} for m, c in self.market_concentration],
            "outcome_concentration": [{"outcome": o, "count": c} for o, c in self.outcome_concentration],
            "price_buckets": self.price_buckets,
            "notional_buckets": self.notional_buckets,
            "warnings": self.warnings,
        }


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    """Inclusive membership test for an hour window that may wrap midnight."""
    if start_hour <= end_hour:
        return start_hour <= hour <= end_hour
    return hour >= start_hour or hour <= end_hour


def parse_claim_window(text: str) -> tuple[int, int]:
    """Parse a ``"6-9"`` style local-hour window into (start, end)."""
    parts = text.split("-")
    if len(parts) != 2:
        raise ValueError("claim window must look like 'START-END', e.g. 6-9")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError("claim window hours must be integers, e.g. 6-9") from exc
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ValueError("claim window hours must be in 0..23")
    return start, end


def analyze_wallet(
    activities: Iterable[WalletActivity],
    *,
    utc_offset_hours: int = 0,
    top_n: int = 10,
) -> WalletAnalysis:
    items = list(activities)
    warnings: list[str] = []

    dated = [a for a in items if a.timestamp is not None]
    if len(dated) < len(items):
        warnings.append(
            f"{len(items) - len(dated)} records lacked a usable timestamp and were excluded from time analysis"
        )

    hour_utc: Counter[int] = Counter()
    hour_local: Counter[int] = Counter()
    weekday_local: Counter[str] = Counter()
    offset_tz = timezone(timedelta(hours=utc_offset_hours))
    for a in dated:
        assert a.timestamp is not None
        utc_dt = datetime.fromtimestamp(a.timestamp, tz=UTC)
        local_dt = utc_dt.astimezone(offset_tz)
        hour_utc[utc_dt.hour] += 1
        hour_local[local_dt.hour] += 1
        weekday_local[_WEEKDAYS[local_dt.weekday()]] += 1

    time_range = None
    if dated:
        stamps = [a.timestamp for a in dated if a.timestamp is not None]
        time_range = (min(stamps), max(stamps))

    buy = sum(1 for a in items if a.side == "BUY")
    sell = sum(1 for a in items if a.side == "SELL")
    other = len(items) - buy - sell

    observed_notional = sum((a.usdc_size for a in items if a.usdc_size is not None), Decimal(0))
    if any(a.usdc_size is None for a in items):
        warnings.append("some records lacked usdcSize; observed_notional is a lower bound")

    market_counts: Counter[str] = Counter(a.title or a.event_slug or a.condition_id or "(unknown)" for a in items)
    outcome_counts: Counter[str] = Counter((a.outcome or "(unknown)") for a in items)

    price_buckets = {label: 0 for label, _, _ in _PRICE_BUCKETS}
    priced = 0
    for a in items:
        if a.price is None:
            continue
        priced += 1
        for label, lo, hi in _PRICE_BUCKETS:
            if lo <= a.price < hi:
                price_buckets[label] += 1
                break
    if priced < len(items):
        warnings.append(f"{len(items) - priced} records lacked a price and were excluded from entry-price buckets")

    notional_buckets = _notional_buckets(items)

    if len(items) < 30:
        warnings.append("small sample (<30 records): distributions are noisy and may not generalize")

    return WalletAnalysis(
        record_count=len(items),
        dated_count=len(dated),
        time_range=time_range,
        utc_offset_hours=utc_offset_hours,
        hour_utc=dict(hour_utc),
        hour_local=dict(hour_local),
        weekday_local={d: weekday_local.get(d, 0) for d in _WEEKDAYS},
        buy_count=buy,
        sell_count=sell,
        other_side_count=other,
        observed_notional=observed_notional,
        market_concentration=market_counts.most_common(top_n),
        outcome_concentration=outcome_counts.most_common(top_n),
        price_buckets=price_buckets,
        notional_buckets=notional_buckets,
        warnings=warnings,
    )


_NOTIONAL_BUCKETS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("<10", Decimal(0), Decimal(10)),
    ("10-50", Decimal(10), Decimal(50)),
    ("50-100", Decimal(50), Decimal(100)),
    ("100-500", Decimal(100), Decimal(500)),
    ("500-1000", Decimal(500), Decimal(1000)),
    (">=1000", Decimal(1000), Decimal("1e30")),
)


def _notional_buckets(items: list[WalletActivity]) -> dict[str, int]:
    buckets = {label: 0 for label, _, _ in _NOTIONAL_BUCKETS}
    for a in items:
        if a.usdc_size is None:
            continue
        for label, lo, hi in _NOTIONAL_BUCKETS:
            if lo <= a.usdc_size < hi:
                buckets[label] += 1
                break
    return buckets
