"""DreamDEX Perps venue (Somnia Hideki Testnet), isolated from Event Contracts."""

from .adapter import PerpsAdapter
from .config import HIDEKI_CHAIN_ID, PerpsConfig

__all__ = ["HIDEKI_CHAIN_ID", "PerpsAdapter", "PerpsConfig"]
