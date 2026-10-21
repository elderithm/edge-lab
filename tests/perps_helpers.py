"""Builders for DreamDEX Perps tests (offline, deterministic)."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from edge_lab.venues.dreamdex_perps.mapper import snapshot_from_json
from edge_lab.venues.dreamdex_perps.models import (
    BookLevel,
    Candle,
    DataSource,
    PerpBook,
    PerpMarket,
    PerpRiskParams,
    PerpSnapshot,
    PerpState,
)

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
NOW = 1_792_600_000


def live_btc_json() -> dict:
    return json.loads((FIXTURES / "perps_snapshot_btc.json").read_text())


def live_btc_snapshot(now: int = NOW) -> PerpSnapshot:
    item = live_btc_json()
    item["capturedAt"] = now
    item["state"]["indexUpdatedAt"] = str(now)
    return snapshot_from_json(item, DataSource.LIVE)


def market(**kw) -> PerpMarket:
    base = dict(
        chain_id=50383,
        market_id="0x" + "1" * 40,
        base_symbol="BTC",
        quote_symbol="USDso",
        base_decimals=8,
        quote_decimals=18,
        tick_size_raw=10**17,  # 0.1
        lot_size_raw=1000,  # 0.00001
        min_quantity_raw=13000,  # 0.00013
        margin_bank="0x" + "b" * 40,
        quote_token="0x" + "c" * 40,
        initial_margin_bps=500,
    )
    base.update(kw)
    return PerpMarket(**base)  # type: ignore[arg-type]


def snapshot(
    *,
    mid: Decimal = D(100),
    half_spread: Decimal = D("0.05"),
    level_qty: Decimal = D(10),
    levels: int = 5,
    mark_ok: bool = True,
    funding_rate: Decimal | None = D("0.0001"),
    captured_at: int = NOW,
    candles: int = 40,
    source: DataSource = DataSource.LIVE,
    mkt: PerpMarket | None = None,
) -> PerpSnapshot:
    m = mkt or market()
    bids = tuple(BookLevel(mid - half_spread - D(i) * D("0.1"), level_qty) for i in range(levels))
    asks = tuple(BookLevel(mid + half_spread + D(i) * D("0.1"), level_qty) for i in range(levels))
    closes = tuple(
        Candle(bucket_start=captured_at - (candles - i) * 300, close=mid * (1 + D(i % 3 - 1) / 1000), trade_count=1)
        for i in range(candles)
    )
    state = PerpState(
        mark_price=mid if mark_ok else None,
        mark_price_ok=mark_ok,
        index_price=mid,
        index_updated_at=captured_at,
        funding_rate=funding_rate,
        funding_window_sec=28800,
        funding_interval_sec=3600,
        last_funding_at=captured_at - 600,
        next_funding_at=captured_at + 3000,
        cumulative_funding_raw=0,
        projected_cumulative_funding_raw=0,
        open_interest=D(1000),
        ema_premium=funding_rate,
    )
    risk = PerpRiskParams(
        initial_margin_bps=D(500),
        maintenance_margin_bps=D(250),
        close_out_margin_bps=D(125),
        max_open_interest=D(10_000),
        max_position_size=D(100),
        taker_fee_bps=D(0),
        maker_fee_bps=D(0),
    )
    return PerpSnapshot(
        market=m,
        state=state,
        risk=risk,
        book=PerpBook(bids=bids, asks=asks, captured_at=captured_at),
        candles=closes,
        candle_interval_seconds=300,
        captured_at=captured_at,
        source=source,
    )


def with_book(snap: PerpSnapshot, bids: tuple, asks: tuple) -> PerpSnapshot:
    return replace(snap, book=PerpBook(bids=bids, asks=asks, captured_at=snap.captured_at))
