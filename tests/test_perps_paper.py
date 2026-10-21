"""Perps paper ledger P&L and testnet order reconciliation."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from perps_helpers import market

from edge_lab.errors import PaperTradingError
from edge_lab.paper.perps_paper import PerpsPaperDB
from edge_lab.perps.execution import reconcile, write_evidence
from edge_lab.perps.risk import PerpOrderIntent
from edge_lab.venues.dreamdex_perps.models import PerpSide

D = Decimal
E36 = 10**36  # 1 quote per whole base, in the SDK's 1e18 * 1e18 cumulative-funding scale


def _open(db, side=PerpSide.LONG, qty=D("0.01"), price=D(100), cum=0):
    return db.open_position(
        market_id="0xm",
        symbol="BTC-PERP",
        quote_decimals=18,
        side=side,
        quantity=qty,
        entry_price=price,
        entry_fee=D(0),
        entry_cum_funding_raw=cum,
        price_source="SIMULATED_FILL_FROM_LIVE_TESTNET_BOOK",
    )


def test_long_and_short_realized_pnl():
    with PerpsPaperDB(":memory:") as db:
        a = _open(db, PerpSide.LONG, D(2), D(100))
        b = _open(db, PerpSide.SHORT, D(2), D(100))
        assert db.close_position(a, exit_price=D(110), exit_fee=D(0), cum_funding_raw=0) == D(20)
        assert db.close_position(b, exit_price=D(110), exit_fee=D("0.5"), cum_funding_raw=0) == D("-20.5")
        with pytest.raises(PaperTradingError):
            db.close_position(a, exit_price=D(1), exit_fee=D(0), cum_funding_raw=0)


def test_funding_accrual_from_cumulative_index():
    with PerpsPaperDB(":memory:") as db:
        pid = _open(db, PerpSide.LONG, D(2), D(100), cum=0)
        pos = db.get(pid)
        assert pos.funding_since_open(E36 * 3) == D(6)  # longs pay 3/base * 2 base
        short = db.get(_open(db, PerpSide.SHORT, D(2), D(100), cum=0))
        assert short.funding_since_open(E36 * 3) == D(-6)  # shorts receive
        assert pos.funding_since_open(None) is None
        realized = db.close_position(pid, exit_price=D(100), exit_fee=D(0), cum_funding_raw=E36)
        assert realized == D(-2)


def test_summary_marks_and_unpriced():
    with PerpsPaperDB(":memory:", starting_equity=D(500)) as db:
        _open(db, PerpSide.LONG, D(1), D(100))
        s = db.summary({"0xm": (D(105), 0)})
        assert s["unrealized_pnl"] == "5.000000" and s["equity"] == "505.000000"
        assert "PAPER" in s["label"]
        assert db.summary({})["unpriced_open_positions"] == [1]
        per, total = db.open_exposure()
        assert per["0xm"] == D(100) and total == D(100)


def _intent(qty_raw=100_000, order_type="ioc"):
    return PerpOrderIntent("0xm", "BTC-PERP", PerpSide.LONG, D("0.001"), qty_raw, D(100), 10**20, order_type, "testnet")


def _result(status="success", fills=(), order_id=None, pos="100000"):
    return {
        "txHash": "0x" + "ab" * 32,
        "receipt": {"status": status, "blockNumber": "123"},
        "orderId": order_id,
        "fills": [{"quantityFilled": q, "fillPrice": p} for q, p in fills],
        "positionAfter": {"size": pos},
    }


def test_reconcile_states():
    m = market()
    p = str(100 * 10**18)
    full = reconcile(_result(fills=[("60000", p), ("40000", p)]), _intent(), m)
    assert full.status == "FILLED" and full.filled_qty == D("0.001") and full.avg_fill_price == D(100)
    assert full.position_after == D("0.001")
    assert reconcile(_result(fills=[("50000", p)]), _intent(), m).status == "PARTIALLY_FILLED"
    assert reconcile(_result(status="reverted"), _intent(), m).status == "REVERTED"
    resting = reconcile(_result(order_id="7", pos="0"), _intent(order_type="limit"), m)
    assert resting.status == "RESTING"  # submission success is not reported as a fill
    assert reconcile(_result(pos="0"), _intent(), m).status == "NOT_FILLED"


def test_evidence_and_ledger(tmp_path):
    m = market()
    res = _result(fills=[("100000", str(100 * 10**18))])
    rec = reconcile(res, _intent(), m)
    path = write_evidence(tmp_path, decision={"approved": True}, result=res, reconciled=rec)
    data = json.loads(path.read_text())
    assert data["reconciled"]["status"] == "FILLED" and "LIVE TESTNET" in data["label"]
    with PerpsPaperDB(tmp_path / "db.sqlite") as db:
        db.record_testnet_order({"market_id": "0xm", "symbol": "BTC-PERP", "side": "LONG", "quantity": D("0.001"),
                                 "limit_price": D(100), "order_type": "ioc", "tx_hash": rec.tx_hash,
                                 "reconciled_status": rec.status})  # fmt: skip
        rows = db.list_testnet_orders()
    assert rows[0]["tx_hash"] == rec.tx_hash and rows[0]["reconciled_status"] == "FILLED"
