"""DreamDEX-specific error taxonomy (see hackathon spec §39).

The bridge returns ``{"error": {"code", "message"}}``; these map codes to typed
exceptions so the Python layer can react precisely. No secrets/env values are
carried in messages.
"""

from __future__ import annotations

from ...errors import EdgeLabError


class DreamdexError(EdgeLabError):
    """Base for DreamDEX venue errors."""

    code = "DREAMDEX_ERROR"


class MarketNotFound(DreamdexError):
    code = "MARKET_NOT_FOUND"


class MarketNotTrading(DreamdexError):
    code = "MARKET_NOT_TRADING"


class MarketLocked(DreamdexError):
    code = "MARKET_LOCKED"


class MarketResolved(DreamdexError):
    code = "MARKET_RESOLVED"


class MarketVoided(DreamdexError):
    code = "MARKET_VOIDED"


class StaleData(DreamdexError):
    code = "STALE_MARKET_DATA"


class InsufficientLiquidity(DreamdexError):
    code = "INSUFFICIENT_LIQUIDITY"


class SlippageTooHigh(DreamdexError):
    code = "SLIPPAGE_TOO_HIGH"


class SignerRejected(DreamdexError):
    code = "SIGNATURE_REJECTED"


class TransactionFailed(DreamdexError):
    code = "TRANSACTION_FAILED"


class RpcError(DreamdexError):
    code = "RPC_ERROR"


class MainnetDisabled(DreamdexError):
    code = "MAINNET_DISABLED"


class PaperModeWrite(DreamdexError):
    code = "PAPER_MODE"


class BridgeUnavailable(DreamdexError):
    code = "BRIDGE_UNAVAILABLE"


# Bridge/SDK code string -> exception class.
_CODE_MAP: dict[str, type[DreamdexError]] = {
    "MARKET_NOT_FOUND": MarketNotFound,
    "MARKET_NOT_TRADING": MarketNotTrading,
    "MARKET_LOCKED": MarketLocked,
    "MARKET_RESOLVED": MarketResolved,
    "MARKET_VOIDED": MarketVoided,
    "STALE_MARKET_DATA": StaleData,
    "STALE_PRICE_DATA": StaleData,
    "INSUFFICIENT_LIQUIDITY": InsufficientLiquidity,
    "SLIPPAGE_TOO_HIGH": SlippageTooHigh,
    "SIGNATURE_REJECTED": SignerRejected,
    "SignerRequiredError": SignerRejected,
    "SIGNER_REQUIRED": SignerRejected,
    "TRANSACTION_FAILED": TransactionFailed,
    "ContractRevertError": TransactionFailed,
    "RPC_ERROR": RpcError,
    "RpcError": RpcError,
    "IndexerError": RpcError,
    "MAINNET_DISABLED": MainnetDisabled,
    "PAPER_MODE": PaperModeWrite,
}


def error_for(code: str, message: str) -> DreamdexError:
    cls = _CODE_MAP.get(code, DreamdexError)
    exc = cls(f"[{code}] {message}")
    return exc
