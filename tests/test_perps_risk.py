"""Perps risk engine: hard limits, explicit reasons, and that blocks cannot reach the SDK."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from perps_helpers import NOW, snapshot

from edge_lab.errors import ConfigError
from edge_lab.perps.risk import PerpOrderIntent, PerpsRiskConfig, PerpsRiskEngine, RiskApproval
from edge_lab.venues.dreamdex_perps.adapter import PerpsAdapter
from edge_lab.venues.dreamdex_perps.config import PerpsConfig
from edge_lab.venues.dreamdex_perps.errors import PerpsWriteRefused, RiskBlocked
from edge_lab.venues.dreamdex_perps.models import DataSource, PerpSide

D = Decimal
TESTNET_ENV = PerpsConfig(network="hideki-testnet", trading_mode="testnet", has_signer=True)


class RecordingBridge:
    def __init__(self, responses=None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.responses = responses or {}

    def invoke(self, command, params=None):
        self.calls.append((command, params))
        return self.responses.get(command, {})


def _eval(snap=None, side=PerpSide.LONG, qty=D("0.5"), **kw):
    kw.setdefault("equity", D(1000))
    return PerpsRiskEngine().evaluate(snap or snapshot(), side, qty, now=NOW, **kw)


def _failed(decision) -> set[str]:
    return {c.name for c in decision.checks if not c.passed}


def test_paper_order_approved_with_tick_aligned_limit():
    d = _eval()
    assert d.approved, d.blocked_reasons
    assert d.intent is not None
    assert d.intent.limit_price % D("0.1") == 0
    assert d.intent.limit_price > d.execution.worst_price  # long limit rounds up with buffer
    assert d.intent.quantity_raw == 50_000_000  # 0.5 BTC at 8 decimals


def test_short_limit_rounds_down():
    d = _eval(side=PerpSide.SHORT)
    assert d.approved and d.intent.limit_price < d.execution.worst_price


def test_leverage_hard_cap_cannot_be_configured_away():
    with pytest.raises(ConfigError):
        PerpsRiskConfig(max_effective_leverage=D(2))


def test_effective_leverage_blocks_over_one_x():
    d = _eval(qty=D("0.5"), equity=D(40))  # notional ~50 > equity 40
    assert "effective_leverage" in _failed(d) and not d.approved


def test_unknown_equity_blocks():
    d = _eval(equity=None)
    assert {"effective_leverage", "available_margin"} <= _failed(d)


def test_precision_and_min_quantity():
    assert "quantity_precision" in _failed(_eval(qty=D("0.000015")))  # not a lot multiple
    assert "quantity_precision" in _failed(_eval(qty=D("0.00001")))  # below min 0.00013
    d = _eval(limit_price=D("100.33"))
    assert "price_precision" in _failed(d)


def test_liquidity_slippage_and_caps():
    assert "liquidity" in _failed(_eval(qty=D(100)))
    wide = snapshot(half_spread=D("1"))
    assert "slippage" in _failed(_eval(snap=wide))
    assert "position_notional" in _failed(_eval(qty=D("0.5"), existing_market_notional=D(80)))
    assert "total_exposure" in _failed(_eval(qty=D("0.5"), existing_total_notional=D(240)))


def test_stale_data_blocks():
    assert "mark_price_ok" in _failed(_eval(snap=snapshot(mark_ok=False)))
    assert "data_fresh" in _failed(_eval(snap=snapshot(captured_at=NOW - 60)))


def test_every_block_has_explicit_reason():
    d = _eval(qty=D(100), equity=None)
    assert not d.approved
    assert d.blocked_reasons and all(":" in r and len(r) > 10 for r in d.blocked_reasons)


def test_testnet_mode_requires_gates_and_official_sizing():
    d = _eval(mode="testnet", perps_config=PerpsConfig())
    assert {"execution_mode", "official_sizing"} <= _failed(d)
    sim = _eval(snap=snapshot(source=DataSource.SIMULATED), mode="testnet", perps_config=TESTNET_ENV)
    assert "live_data" in _failed(sim)  # fixtures can never be executed


def _preview(limited_by="collateral", placeable=True, max_qty="100000000", sufficient=True):
    return {
        "sizing": {"priceable": True, "placeable": placeable, "maxQuantity": max_qty, "limitedBy": limited_by},
        "margin": {"priceable": True, "sufficient": sufficient, "isolationBlocked": False},
        "liquidation": {"priceable": True, "projectedLiquidationPrice": "1000000000000000000"},  # 1.0
        "precisionProblems": [],
    }


def test_official_preview_checks():
    ok = _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview())
    assert ok.approved, ok.blocked_reasons
    assert "PROTOCOL" in next(c.detail for c in ok.checks if c.name == "liquidation_distance")
    assert "voucher_allowed" in _failed(
        _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview(limited_by="voucherBlocked"))
    )
    assert "official_sizing" in _failed(
        _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview(max_qty="1000"))
    )
    assert "official_margin" in _failed(
        _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview(sufficient=False))
    )


def test_blocked_decision_cannot_mint_approval():
    d = _eval(equity=None)
    with pytest.raises(RiskBlocked):
        d.approval()


def test_adapter_rejects_forged_or_expired_approval_without_calling_bridge():
    bridge = RecordingBridge()
    adapter = PerpsAdapter(TESTNET_ENV, bridge=bridge)
    intent = PerpOrderIntent("0x" + "1" * 40, "BTC-PERP", PerpSide.LONG, D(1), 1, D(1), 1, "ioc", "testnet")
    forged = RiskApproval(intent=intent, issued_at=9e18, _token=object())
    with pytest.raises(PerpsWriteRefused):
        adapter.place_order(forged)
    approved = _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview()).approval()
    expired = replace(approved, issued_at=approved.issued_at - 3600)
    with pytest.raises(PerpsWriteRefused):
        adapter.place_order(expired)
    with pytest.raises(PerpsWriteRefused):
        adapter.place_order("not an approval")  # type: ignore[arg-type]
    assert bridge.calls == []


def test_adapter_refuses_paper_config_even_with_valid_approval():
    bridge = RecordingBridge()
    approval = _eval().approval()
    with pytest.raises(PerpsWriteRefused):
        PerpsAdapter(PerpsConfig(), bridge=bridge).place_order(approval)
    assert bridge.calls == []


def test_valid_approval_reaches_bridge_with_risk_flag():
    bridge = RecordingBridge({"place-order": {"submitted": True}})
    approval = _eval(mode="testnet", perps_config=TESTNET_ENV, official_preview=_preview()).approval()
    PerpsAdapter(TESTNET_ENV, bridge=bridge).place_order(approval)
    cmd, params = bridge.calls[0]
    assert cmd == "place-order" and params["riskApproved"] is True and params["isBid"] is True
