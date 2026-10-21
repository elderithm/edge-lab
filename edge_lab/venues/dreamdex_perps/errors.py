"""DreamDEX Perps error taxonomy. Bridge codes map to typed exceptions."""

from __future__ import annotations

from ...errors import EdgeLabError


class PerpsError(EdgeLabError):
    code = "PERPS_ERROR"


class PerpsMarketNotFound(PerpsError):
    code = "MARKET_NOT_FOUND"


class AmbiguousMarket(PerpsError):
    code = "AMBIGUOUS_MARKET"


class PerpsBridgeUnavailable(PerpsError):
    code = "BRIDGE_UNAVAILABLE"


class PerpsRpcError(PerpsError):
    code = "RPC_ERROR"


class PerpsWriteRefused(PerpsError):
    """Mode / network / signer / chain gate refused a write."""

    code = "WRITE_REFUSED"


class PerpsOrderRejected(PerpsError):
    """Pre-trade validation failed (precision, sizing, voucher, caps)."""

    code = "ORDER_REJECTED"


class PerpsTransactionFailed(PerpsError):
    """The transaction reverted or its outcome could not be confirmed."""

    code = "TRANSACTION_FAILED"


class RiskBlocked(PerpsError):
    """The Perps risk engine blocked the order. It never reached the SDK."""

    code = "RISK_BLOCKED"


_CODE_MAP: dict[str, type[PerpsError]] = {
    "MARKET_NOT_FOUND": PerpsMarketNotFound,
    "RPC_ERROR": PerpsRpcError,
    "RpcError": PerpsRpcError,
    "IndexerError": PerpsRpcError,
    "IndexerUnavailableError": PerpsRpcError,
    "WS_REQUIRED": PerpsRpcError,
    "PAPER_MODE": PerpsWriteRefused,
    "WRONG_NETWORK": PerpsWriteRefused,
    "WRONG_CHAIN": PerpsWriteRefused,
    "SIGNER_REQUIRED": PerpsWriteRefused,
    "SignerRequiredError": PerpsWriteRefused,
    "RISK_NOT_APPROVED": PerpsWriteRefused,
    "PRECISION_ERROR": PerpsOrderRejected,
    "NOTIONAL_CAP": PerpsOrderRejected,
    "MAX_ORDER_SIZE": PerpsOrderRejected,
    "VOUCHER_BLOCKED": PerpsOrderRejected,
    "STALE_MARK_PRICE": PerpsOrderRejected,
    "INSUFFICIENT_COLLATERAL": PerpsOrderRejected,
    "ISOLATED_MARKET_BLOCKED": PerpsOrderRejected,
    "MAX_POSITION_SIZE_EXCEEDED": PerpsOrderRejected,
    "IOC_NO_FILL": PerpsTransactionFailed,
    "ContractRevertError": PerpsTransactionFailed,
    "TransactionOutcomeUnknownError": PerpsTransactionFailed,
}


def perps_error_for(code: str, message: str) -> PerpsError:
    exc = _CODE_MAP.get(code, PerpsError)(f"[{code}] {message}")
    exc.code = code
    return exc
