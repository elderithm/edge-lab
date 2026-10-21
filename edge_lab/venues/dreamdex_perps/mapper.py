"""Bridge JSON (raw SDK integers as strings) -> normalized Perps models.

Missing or sentinel values become ``None`` and are never synthesized: a stale
mark feed (``markPriceOk=false``) yields ``mark_price=None``, a zero index price
is treated as absent, and a pool without funding-premium support yields no
premium. Callers surface these as explicit data gaps.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .config import HIDEKI_CHAIN_ID
from .models import (
    FUNDING_PRECISION,
    PRICE_DECIMALS,
    BookLevel,
    Candle,
    DataSource,
    FundingPremium,
    PerpAccount,
    PerpBook,
    PerpMarket,
    PerpPositionState,
    PerpRiskParams,
    PerpSnapshot,
    PerpState,
    scale_down,
)


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v))
    except ValueError:
        return None


def _price(v: Any) -> Decimal | None:
    raw = _int(v)
    return None if raw is None or raw <= 0 else scale_down(raw, PRICE_DECIMALS)


def _fraction(v: Any) -> Decimal | None:
    raw = _int(v)
    return None if raw is None else Decimal(raw) / FUNDING_PRECISION


def market_from_json(row: dict[str, Any], chain_id: int = HIDEKI_CHAIN_ID) -> PerpMarket:
    base_decimals = int(row["baseDecimals"])
    oi = _int(row.get("openInterest"))
    return PerpMarket(
        chain_id=int(row.get("chainId") or chain_id),
        market_id=str(row["poolAddress"]).lower(),
        base_symbol=str(row.get("baseSymbol") or "?"),
        quote_symbol=str(row.get("quoteSymbol") or "?"),
        base_decimals=base_decimals,
        quote_decimals=int(row["quoteDecimals"]),
        tick_size_raw=int(row["tickSize"]),
        lot_size_raw=int(row["lotSize"]),
        min_quantity_raw=int(row["minQuantity"]),
        margin_bank=str(row.get("marginBank") or "").lower(),
        quote_token=str(row.get("quoteToken") or "").lower(),
        initial_margin_bps=int(row.get("initialMarginBps") or 0),
        last_price=_price(row.get("lastPrice")),
        last_trade_at=_int(row.get("lastTradeAt")),
        open_interest=None if oi is None else scale_down(oi, base_decimals),
    )


def state_from_json(s: dict[str, Any], market: PerpMarket) -> PerpState:
    ok = bool(s.get("markPriceOk"))
    oi = _int(s.get("openInterest"))
    return PerpState(
        mark_price=_price(s.get("markPrice")) if ok else None,
        mark_price_ok=ok,
        index_price=_price(s.get("indexPrice")),
        index_updated_at=_int(s.get("indexUpdatedAt")),
        funding_rate=_fraction(s.get("fundingRate")),
        funding_window_sec=_int(s.get("fundingWindowSec")),
        funding_interval_sec=_int(s.get("fundingIntervalSec")),
        last_funding_at=_int(s.get("lastFundingUpdateAt")),
        next_funding_at=_int(s.get("nextFundingAt")),
        cumulative_funding_raw=_int(s.get("cumulativeFundingPerUnit")),
        projected_cumulative_funding_raw=_int(s.get("projectedCumulativeFundingPerUnit")),
        open_interest=None if oi is None else scale_down(oi, market.base_decimals),
        ema_premium=_fraction(s.get("emaPremium")),
    )


def risk_from_json(r: dict[str, Any], market: PerpMarket) -> PerpRiskParams:
    return PerpRiskParams(
        initial_margin_bps=Decimal(str(r["initialMarginBps"])),
        maintenance_margin_bps=Decimal(str(r["maintenanceMarginBps"])),
        close_out_margin_bps=Decimal(str(r.get("closeOutMarginBps", 0))),
        max_open_interest=scale_down(int(r.get("maxOpenInterest", 0)), market.base_decimals),
        max_position_size=scale_down(int(r.get("maxPositionSize", 0)), market.base_decimals),
        taker_fee_bps=Decimal(str(r.get("takerFeeBpsTimes1k", 0))) / 1000,
        maker_fee_bps=Decimal(str(r.get("makerFeeBpsTimes1k", 0))) / 1000,
    )


def premium_from_json(p: dict[str, Any] | None) -> FundingPremium | None:
    if not p:
        return None
    twp = _fraction(p.get("timeWeightedPremium"))
    if twp is None:
        return None
    return FundingPremium(time_weighted_premium=twp, armed=bool(p.get("armed")))


def book_from_json(b: dict[str, Any], market: PerpMarket, captured_at: int) -> PerpBook:
    def levels(side: Any) -> tuple[BookLevel, ...]:
        out = []
        for lv in side or []:
            price = _price(lv.get("price"))
            qty = _int(lv.get("quantity"))
            if price is None or qty is None or qty <= 0:
                continue
            out.append(BookLevel(price=price, quantity=scale_down(qty, market.base_decimals)))
        return tuple(out)

    bids = tuple(sorted(levels(b.get("bids")), key=lambda lv: lv.price, reverse=True))
    asks = tuple(sorted(levels(b.get("asks")), key=lambda lv: lv.price))
    return PerpBook(bids=bids, asks=asks, captured_at=captured_at, block_number=_int(b.get("blockNumber")))


def candles_from_json(rows: Any) -> tuple[Candle, ...]:
    out: list[Candle] = []
    for c in rows or []:
        close = _price(c.get("closePrice"))
        start = _int(c.get("bucketStart"))
        if close is None or start is None:
            continue  # invalid observation: dropped, never filled in
        out.append(Candle(bucket_start=start, close=close, trade_count=int(c.get("tradeCount") or 0)))
    out.sort(key=lambda c: c.bucket_start)
    return tuple(out)


def snapshot_from_json(item: dict[str, Any], source: DataSource = DataSource.LIVE) -> PerpSnapshot:
    market = market_from_json(item["market"])
    captured = int(item.get("capturedAt") or 0)
    warnings: list[str] = []
    if market.quote_decimals != PRICE_DECIMALS:
        warnings.append(f"quoteDecimals={market.quote_decimals} != {PRICE_DECIMALS}; notional scaling unverified")
    candles = candles_from_json(item.get("candles"))
    if item.get("candles") is None:
        warnings.append("candle history unavailable from indexer")
    premium = premium_from_json(item.get("premium"))
    if item.get("premium") is None:
        warnings.append("funding premium read unavailable for this pool")
    return PerpSnapshot(
        market=market,
        state=state_from_json(item["state"], market),
        risk=risk_from_json(item["risk"], market),
        book=book_from_json(item.get("book") or {}, market, captured),
        candles=candles,
        candle_interval_seconds=int(item.get("candleIntervalSeconds") or 300),
        captured_at=captured,
        source=source,
        premium=premium,
        warnings=tuple(warnings),
    )


def account_from_json(
    payload: dict[str, Any], markets: dict[str, PerpMarket], source: DataSource = DataSource.LIVE
) -> PerpAccount:
    eq = _int(payload.get("equity"))
    quote_decimals = next(iter(markets.values())).quote_decimals if markets else PRICE_DECIMALS
    positions = []
    for p in payload.get("positions") or []:
        pool = str(p.get("pool", "")).lower()
        m = markets.get(pool)
        size = _int(p.get("size")) or 0
        positions.append(
            PerpPositionState(
                market_id=pool,
                symbol=m.symbol if m else str(p.get("baseSymbol") or pool),
                size=scale_down(size, m.base_decimals) if m else Decimal(size),
                avg_entry_price=_price(p.get("avgEntryPrice")) or Decimal(0),
            )
        )
    voucher = payload.get("voucher")
    return PerpAccount(
        account=str(payload.get("account", "")),
        equity=None if eq is None else scale_down(eq, quote_decimals),
        positions=tuple(positions),
        voucher=voucher if isinstance(voucher, dict) else {},
        captured_at=int(payload.get("capturedAt") or 0),
        source=source,
    )
