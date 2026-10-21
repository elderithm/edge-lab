"""Opt-in live integration tests against Somnia Hideki Testnet (``pytest -m live``).

Read-only by default: market discovery, snapshot, official unsigned preview and
max-order-size for a public address. The signed-order test additionally needs
``PERPS_LIVE_EXECUTE=1`` plus the full testnet write configuration, and is
never run in CI.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import pytest

from edge_lab.perps.analytics import assess_market
from edge_lab.perps.execution import submit
from edge_lab.perps.service import decide, live_account_context
from edge_lab.venues.dreamdex_perps.adapter import PerpsAdapter
from edge_lab.venues.dreamdex_perps.config import HIDEKI_CHAIN_ID, PerpsConfig
from edge_lab.venues.dreamdex_perps.models import PerpSide

pytestmark = pytest.mark.live
BURN = "0x000000000000000000000000000000000000dead"  # public address with no perps account


@pytest.fixture(scope="module")
def adapter() -> PerpsAdapter:
    return PerpsAdapter(PerpsConfig.from_env())


def test_live_market_discovery(adapter):
    markets = adapter.list_markets()
    assert markets and all(m.chain_id == HIDEKI_CHAIN_ID for m in markets)
    btc = adapter.resolve("BTC")
    assert btc.lot_size > 0 and btc.tick_size > 0 and btc.min_quantity >= btc.lot_size


def test_live_snapshot_and_assessment(adapter):
    btc = adapter.resolve("BTC")
    snap = adapter.get_snapshot(btc.market_id)
    assert snap.book.bids and snap.book.asks
    a = assess_market(snap, int(time.time()))
    assert a.to_dict()["source"] == "LIVE_TESTNET"


def test_live_unsigned_preview_and_max_size(adapter):
    btc = adapter.resolve("BTC")
    snap = adapter.get_snapshot(btc.market_id)
    d = decide(snap, PerpSide.LONG, Decimal("0.001"), int(time.time()), mode="paper", equity=Decimal(1000), db=None)
    assert d.intent is not None
    pv = adapter.preview_order(
        btc, is_bid=True, price_raw=d.intent.limit_price_raw, quantity_raw=d.intent.quantity_raw, account=BURN
    )
    assert pv["dryRun"] is True and pv["precisionProblems"] == []
    assert pv["sizing"]["priceable"] is True
    assert pv["sizing"]["placeable"] is False and pv["sizing"]["limitedBy"] == "collateral"  # empty account


@pytest.mark.skipif(os.environ.get("PERPS_LIVE_EXECUTE") != "1", reason="signed testnet execution is opt-in")
def test_live_signed_min_order(adapter):
    cfg = adapter.config
    assert cfg.write_blockers() == [], cfg.write_blockers()
    btc = adapter.resolve("BTC")
    snap = adapter.get_snapshot(btc.market_id)
    signer = adapter.signer_address()
    equity, exposure = live_account_context(adapter, signer, snap)
    now = int(time.time())
    draft = decide(snap, PerpSide.LONG, btc.min_quantity, now, mode="testnet", equity=equity, db=None,
                   config=cfg, live_exposure=exposure)  # fmt: skip
    assert draft.intent is not None
    pv = adapter.preview_order(btc, is_bid=True, price_raw=draft.intent.limit_price_raw,
                               quantity_raw=draft.intent.quantity_raw, account=signer)  # fmt: skip
    decision = decide(snap, PerpSide.LONG, btc.min_quantity, int(time.time()), mode="testnet", equity=equity,
                      db=None, config=cfg, preview=pv, live_exposure=exposure)  # fmt: skip
    assert decision.approved, decision.blocked_reasons
    result, rec = submit(adapter, decision.approval(), btc)
    assert rec.tx_hash and rec.receipt_status == "success"
    assert adapter.get_receipt(rec.tx_hash)["status"] == "success"
