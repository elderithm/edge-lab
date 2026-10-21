"""Testnet execution + post-submission reconciliation for DreamDEX Perps.

Separate from analytics and risk: this module only (1) hands an already-minted
:class:`RiskApproval` to the adapter and (2) turns the bridge's transaction
result into an honest order state. A successful submission is NOT reported as a
fill: the state comes from the receipt status and the decoded fills.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..venues.dreamdex_perps.models import PRICE_DECIMALS, PerpMarket, scale_down
from .risk import PerpOrderIntent, RiskApproval

DEFAULT_EVIDENCE_DIR = ".edge-lab/perps-evidence"


@dataclass(frozen=True)
class ReconciledOrder:
    status: str  # REVERTED | FILLED | PARTIALLY_FILLED | RESTING | NOT_FILLED
    tx_hash: str | None
    receipt_status: str | None
    block_number: str | None
    order_id: str | None
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    position_after: Decimal | None  # signed base units, from a fresh MarginBank read
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "tx_hash": self.tx_hash,
            "receipt_status": self.receipt_status,
            "block_number": self.block_number,
            "order_id": self.order_id,
            "filled_qty": str(self.filled_qty),
            "avg_fill_price": None if self.avg_fill_price is None else str(self.avg_fill_price),
            "position_after": None if self.position_after is None else str(self.position_after),
            "detail": self.detail,
        }


def reconcile(result: dict[str, Any], intent: PerpOrderIntent, market: PerpMarket) -> ReconciledOrder:
    receipt = result.get("receipt") or {}
    rstatus = receipt.get("status")
    fills = result.get("fills") or []
    filled_raw = 0
    cost = Decimal(0)
    for f in fills:
        q = int(f.get("quantityFilled") or 0)
        filled_raw += q
        cost += scale_down(q, market.base_decimals) * scale_down(int(f.get("fillPrice") or 0), PRICE_DECIMALS)
    filled = scale_down(filled_raw, market.base_decimals)
    avg = cost / filled if filled > 0 else None
    pos = result.get("positionAfter") or {}
    pos_size = None if "size" not in pos else scale_down(int(pos["size"]), market.base_decimals)
    order_id = None if result.get("orderId") in (None, "") else str(result.get("orderId"))

    if rstatus != "success":
        status, detail = "REVERTED", f"receipt status {rstatus!r}; no state change"
    elif filled_raw >= intent.quantity_raw:
        status, detail = "FILLED", f"filled {filled} in {len(fills)} fill(s)"
    elif filled_raw > 0:
        rest = "remainder cancelled (IOC)" if intent.order_type == "ioc" else "remainder resting"
        status, detail = "PARTIALLY_FILLED", f"filled {filled}/{intent.quantity}; {rest}"
    elif order_id is not None and intent.order_type != "ioc":
        status, detail = "RESTING", f"order {order_id} resting on book, no fill yet"
    else:
        status, detail = "NOT_FILLED", "transaction succeeded but no fill was decoded"
    return ReconciledOrder(
        status=status,
        tx_hash=result.get("txHash"),
        receipt_status=None if rstatus is None else str(rstatus),
        block_number=None if receipt.get("blockNumber") is None else str(receipt.get("blockNumber")),
        order_id=order_id,
        filled_qty=filled,
        avg_fill_price=avg,
        position_after=pos_size,
        detail=detail,
    )


def submit(adapter: Any, approval: RiskApproval, market: PerpMarket) -> tuple[dict[str, Any], ReconciledOrder]:
    result = adapter.place_order(approval)
    return result, reconcile(result, approval.intent, market)


def write_evidence(
    evidence_dir: str | Path, *, decision: dict[str, Any], result: dict[str, Any], reconciled: ReconciledOrder
) -> Path:
    """Persist a JSON evidence bundle (no secrets: the bridge never returns the key)."""
    d = Path(evidence_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time())}-{(reconciled.tx_hash or 'nohash')[:18]}.json"
    path = d / name
    path.write_text(
        json.dumps(
            {
                "label": "LIVE TESTNET order evidence (Somnia Hideki, chain 50383)",
                "risk_decision": decision,
                "bridge_result": result,
                "reconciled": reconciled.to_dict(),
            },
            indent=2,
            default=str,
        )
    )
    return path
