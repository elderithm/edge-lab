"""Scan / inspect orchestration shared by the Perps CLI and dashboard."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..paper.perps_paper import PerpsPaperDB
from ..venues.dreamdex_perps.adapter import PerpsAdapter
from ..venues.dreamdex_perps.config import PerpsConfig
from ..venues.dreamdex_perps.models import PerpSide, PerpSnapshot
from .analytics import AssessmentThresholds, MarketAssessment, assess_market, rank
from .risk import PerpsRiskConfig, PerpsRiskDecision, PerpsRiskEngine


def scan(venue: Any, now: int, thresholds: AssessmentThresholds | None = None) -> dict[str, Any]:
    snaps, errors = venue.snapshots()
    assessments = rank([assess_market(s, now, thresholds) for s in snaps])
    return {
        "generated_at": now,
        "source": venue.source.value,
        "count": len(assessments),
        "assessments": assessments,
        "read_errors": errors,
    }


def inspect(venue: Any, query: str, now: int, thresholds: AssessmentThresholds | None = None) -> MarketAssessment:
    market = venue.resolve(query)
    return assess_market(venue.get_snapshot(market.market_id), now, thresholds)


def decide(
    snap: PerpSnapshot,
    side: PerpSide,
    size: Decimal,
    now: int,
    *,
    mode: str,
    equity: Decimal | None,
    db: PerpsPaperDB | None,
    order_type: str = "ioc",
    limit_price: Decimal | None = None,
    config: PerpsConfig | None = None,
    preview: dict[str, Any] | None = None,
    live_exposure: tuple[Decimal, Decimal] | None = None,
) -> PerpsRiskDecision:
    """Run the risk engine with exposure taken from the paper ledger or the live account."""
    per_market, total = live_exposure if live_exposure else (Decimal(0), Decimal(0))
    existing_im = Decimal(0)
    if db is not None:
        per, tot = db.open_exposure()
        per_market, total = per.get(snap.market.market_id, Decimal(0)), tot
        existing_im = tot * snap.risk.initial_margin_bps / Decimal(10_000)
    return PerpsRiskEngine(PerpsRiskConfig()).evaluate(
        snap,
        side,
        size,
        now=now,
        mode=mode,
        equity=equity,
        existing_market_notional=per_market,
        existing_total_notional=total,
        existing_initial_margin=existing_im,
        order_type=order_type,
        limit_price=limit_price,
        perps_config=config,
        official_preview=preview,
    )


def live_account_context(
    adapter: PerpsAdapter, account: str, snap: PerpSnapshot
) -> tuple[Decimal | None, tuple[Decimal, Decimal]]:
    """Live equity and (this-market, total) open notional for a public address."""
    acct = adapter.get_account(account)
    per_market = total = Decimal(0)
    for p in acct.positions:
        notional = abs(p.size) * p.avg_entry_price
        total += notional
        if p.market_id == snap.market.market_id:
            per_market += notional
    return acct.equity, (per_market, total)


def build_preview(
    venue: Any,
    query: str,
    side: PerpSide,
    size: Decimal,
    now: int,
    *,
    config: PerpsConfig,
    db_path: str,
    account: str | None = None,
    order_type: str = "ioc",
    limit_price: Decimal | None = None,
) -> dict[str, Any]:
    """Unsigned preview: paper eligibility always; live adds the official SDK preview + testnet eligibility."""
    m = venue.resolve(query)
    snap = venue.get_snapshot(m.market_id)
    with PerpsPaperDB(db_path) as db:
        paper = decide(
            snap, side, size, now, mode="paper", equity=db.starting_equity, db=db,
            order_type=order_type, limit_price=limit_price, config=config,
        )  # fmt: skip
    acct = account or config.account or None
    official = testnet = None
    if isinstance(venue, PerpsAdapter):
        if paper.intent is not None:
            official = venue.preview_order(
                m, is_bid=side.is_bid, price_raw=paper.intent.limit_price_raw,
                quantity_raw=paper.intent.quantity_raw, account=acct,
            )  # fmt: skip
        equity, exposure = (None, None)
        if acct:
            equity, exposure = live_account_context(venue, acct, snap)
        testnet = decide(
            snap, side, size, now, mode="testnet", equity=equity, db=None, order_type=order_type,
            limit_price=limit_price, config=config, preview=official, live_exposure=exposure,
        )  # fmt: skip
    return {
        "label": "UNSIGNED PREVIEW — nothing signed or submitted",
        "source": snap.source.value,
        "account": acct,
        "market": m.to_dict(),
        "paper": paper,
        "testnet": testnet,
        "official_preview": official,
    }
