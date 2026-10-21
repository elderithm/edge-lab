"""SIMULATED Perps fixture venue for offline demos and tests.

Every snapshot it returns carries ``source=SIMULATED_FIXTURE``. Prices, books
and candles are synthetic and deterministic; they are NOT DreamDEX data and must
never be presented as live observations. Market parameters (decimals, ticks,
lots, margin tiers) mirror the shapes seen on Hideki so the scaling paths are
exercised realistically. Pool addresses are obviously fake (``0x…f00N``).
"""

from __future__ import annotations

import math
from decimal import Decimal

from .models import (
    BookLevel,
    Candle,
    DataSource,
    FundingPremium,
    PerpBook,
    PerpMarket,
    PerpRiskParams,
    PerpSnapshot,
    PerpState,
    resolve_market,
)

D = Decimal
_SPECS = [
    # symbol, pool suffix, base_decimals, tick, lot, min_qty, im_bps, mid, half_spread_bps, level_qty, funding/8h
    ("BTC", "f001", 8, D("0.1"), D("0.00001"), D("0.00013"), 500, D("84500"), D("0.5"), D("0.05"), D("0.0001")),
    ("ETH", "f002", 18, D("0.01"), D("0.0001"), D("0.004"), 500, D("3100"), D("1"), D("1.2"), D("0.0012")),
    ("SOL", "f003", 9, D("0.01"), D("0.01"), D("0.1"), 500, D("185"), D("2"), D("15"), D("-0.0004")),
    ("DOGE", "f004", 8, D("0.00001"), D("10"), D("120"), 1000, D("0.21"), D("40"), D("40"), D("0.00005")),
]


def _market(spec: tuple) -> PerpMarket:
    sym, suffix, bd, tick, lot, minq, im, mid = spec[:8]
    return PerpMarket(
        chain_id=50383,
        market_id="0x" + "0" * 36 + suffix,
        base_symbol=sym,
        quote_symbol="USDso",
        base_decimals=bd,
        quote_decimals=18,
        tick_size_raw=int(tick.scaleb(18)),
        lot_size_raw=int(lot.scaleb(bd)),
        min_quantity_raw=int(minq.scaleb(bd)),
        margin_bank="0x" + "0" * 36 + "ba4c",
        quote_token="0x" + "0" * 36 + "c011",
        initial_margin_bps=im,
        last_price=mid,
    )


def _round(v: Decimal, tick: Decimal) -> Decimal:
    return (v / tick).to_integral_value() * tick


class FixturePerpsVenue:
    venue = "dreamdex-perps"
    source = DataSource.SIMULATED

    def __init__(self, now: int) -> None:
        self.now = now
        self._specs = {_market(s).market_id: s for s in _SPECS}

    def list_markets(self) -> list[PerpMarket]:
        return [_market(s) for s in _SPECS]

    def resolve(self, query: str) -> PerpMarket:
        return resolve_market(self.list_markets(), query)

    def _snapshot(self, spec: tuple) -> PerpSnapshot:
        m = _market(spec)
        _, _, _, tick, _, _, im, mid, half_bps, level_qty, f8h = spec
        half = mid * half_bps / D(10_000)
        bids = tuple(BookLevel(_round(mid - half - tick * i * 3, tick), level_qty * (1 + D(i) / 2)) for i in range(8))
        asks = tuple(BookLevel(_round(mid + half + tick * i * 3, tick), level_qty * (1 + D(i) / 2)) for i in range(8))
        interval = 300
        start = (self.now // interval) * interval - 47 * interval
        candles = tuple(
            Candle(
                bucket_start=start + i * interval,
                close=_round(mid * (1 + D(str(0.002 * math.sin(i * 0.7) + 0.001 * math.cos(i * 1.9)))), tick),
                trade_count=10 + i,
            )
            for i in range(48)
        )
        mark = _round(mid * D("1.0002"), tick)
        state = PerpState(
            mark_price=mark,
            mark_price_ok=True,
            index_price=mid,
            index_updated_at=self.now - 5,
            funding_rate=f8h,
            funding_window_sec=28800,
            funding_interval_sec=3600,
            last_funding_at=self.now - 1200,
            next_funding_at=self.now + 2400,
            cumulative_funding_raw=10**36,
            projected_cumulative_funding_raw=10**36,
            open_interest=level_qty * 100,
            ema_premium=f8h,
        )
        risk = PerpRiskParams(
            initial_margin_bps=D(im),
            maintenance_margin_bps=D(im) / 2,
            close_out_margin_bps=D(im) / 4,
            max_open_interest=level_qty * 1000,
            max_position_size=level_qty * 100,
            taker_fee_bps=D(0),
            maker_fee_bps=D(0),
        )
        return PerpSnapshot(
            market=m,
            state=state,
            risk=risk,
            book=PerpBook(bids=bids, asks=asks, captured_at=self.now),
            candles=candles,
            candle_interval_seconds=interval,
            captured_at=self.now,
            source=DataSource.SIMULATED,
            premium=FundingPremium(time_weighted_premium=f8h, armed=True),
            warnings=("SIMULATED FIXTURE — synthetic data, not DreamDEX",),
        )

    def snapshots(self, pools: list[str] | None = None) -> tuple[list[PerpSnapshot], list[dict[str, object]]]:
        specs = [s for pid, s in self._specs.items() if pools is None or pid in pools]
        return [self._snapshot(s) for s in specs], []

    def get_snapshot(self, market_id: str) -> PerpSnapshot:
        from .errors import PerpsMarketNotFound

        spec = self._specs.get(market_id)
        if spec is None:
            raise PerpsMarketNotFound(f"no fixture market {market_id}")
        return self._snapshot(spec)
