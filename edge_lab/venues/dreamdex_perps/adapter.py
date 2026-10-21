"""DreamDEX Perps venue adapter — reads + gated testnet execution via the bridge.

Reads need no wallet. ``place_order`` accepts ONLY a :class:`RiskApproval`
produced by the Perps risk engine, re-checks the write gate itself, and the
bridge re-validates once more against fresh chain state before signing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .bridge import PerpsBridge
from .config import PerpsConfig
from .errors import PerpsMarketNotFound, PerpsWriteRefused
from .mapper import account_from_json, market_from_json, snapshot_from_json
from .models import DataSource, PerpAccount, PerpMarket, PerpSnapshot, resolve_market

if TYPE_CHECKING:
    from ...perps.risk import RiskApproval


class PerpsAdapter:
    venue = "dreamdex-perps"
    source = DataSource.LIVE

    def __init__(self, config: PerpsConfig | None = None, bridge: Any | None = None) -> None:
        self.config = config or PerpsConfig.from_env()
        self.bridge = bridge or PerpsBridge(self.config)

    # ---- reads -----------------------------------------------------------
    def list_markets(self) -> list[PerpMarket]:
        payload = self.bridge.invoke("markets", {"limit": 50})
        return [market_from_json(r) for r in payload.get("markets") or [] if isinstance(r, dict)]

    def resolve(self, query: str) -> PerpMarket:
        return resolve_market(self.list_markets(), query)

    def snapshots(self, pools: list[str] | None = None) -> tuple[list[PerpSnapshot], list[dict[str, Any]]]:
        """Snapshots for all (or the given) markets, plus per-market read errors."""
        params: dict[str, Any] = {"depth": 25}
        if pools is not None:
            params["pools"] = pools
        payload = self.bridge.invoke("snapshot", params)
        snaps: list[PerpSnapshot] = []
        errors: list[dict[str, Any]] = []
        for item in payload.get("items") or []:
            if "error" in item:
                errors.append({"market_id": item.get("pool"), "error": item["error"]})
                continue
            snaps.append(snapshot_from_json(item, DataSource.LIVE))
        return snaps, errors

    def get_snapshot(self, market_id: str) -> PerpSnapshot:
        snaps, errors = self.snapshots([market_id])
        if snaps:
            return snaps[0]
        if errors:
            raise PerpsMarketNotFound(f"read failed for {market_id}: {errors[0]['error']}")
        raise PerpsMarketNotFound(f"no perp market {market_id}")

    def get_account(self, account: str | None = None) -> PerpAccount:
        payload = self.bridge.invoke("account", {"account": account} if account else {})
        markets = {m.market_id: m for m in self.list_markets()}
        return account_from_json(payload, markets, DataSource.LIVE)

    def preview_order(
        self, market: PerpMarket, *, is_bid: bool, price_raw: int, quantity_raw: int, account: str | None
    ) -> dict[str, Any]:
        """Official unsigned preview (precision + getMaxPerpOrderSize/margin/liquidation if account)."""
        params: dict[str, Any] = {
            "pool": market.market_id,
            "isBid": is_bid,
            "price": str(price_raw),
            "quantity": str(quantity_raw),
        }
        if account:
            params["account"] = account
        return self.bridge.invoke("preview-order", params)

    def signer_address(self) -> str:
        """Public address of PERPS_PRIVATE_KEY, derived inside the bridge (the key never reaches Python)."""
        return str(self.bridge.invoke("signer", {}).get("address", "")).lower()

    def get_receipt(self, tx_hash: str) -> dict[str, Any]:
        return self.bridge.invoke("receipt", {"hash": tx_hash})

    def get_position(self, market_id: str, account: str) -> dict[str, Any]:
        return self.bridge.invoke("position", {"pool": market_id, "account": account})

    # ---- write -------------------------------------------------------------
    def place_order(self, approval: RiskApproval) -> dict[str, Any]:
        from ...perps.risk import RiskApproval

        if not isinstance(approval, RiskApproval) or not approval.is_valid():
            raise PerpsWriteRefused("place_order requires a valid RiskApproval from the Perps risk engine")
        blockers = self.config.write_blockers()
        if blockers:
            raise PerpsWriteRefused("testnet execution not enabled: " + "; ".join(blockers))
        intent = approval.intent
        return self.bridge.invoke(
            "place-order",
            {
                "pool": intent.market_id,
                "isBid": intent.side.is_bid,
                "price": str(intent.limit_price_raw),
                "quantity": str(intent.quantity_raw),
                "orderType": intent.order_type,
                "riskApproved": True,
            },
        )

    def claim_voucher(self, *, confirmed: bool) -> dict[str, Any]:
        """Claim the signer's one-time paper-USDso testnet credit (explicit confirmation only)."""
        if confirmed is not True:
            raise PerpsWriteRefused("claim_voucher requires explicit confirmation")
        blockers = self.config.write_blockers()
        if blockers:
            raise PerpsWriteRefused("testnet execution not enabled: " + "; ".join(blockers))
        return self.bridge.invoke("claim-voucher", {"confirmed": True})
