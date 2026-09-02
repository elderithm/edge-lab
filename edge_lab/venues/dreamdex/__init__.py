"""DreamDEX Event Contracts venue adapter (isolated).

On-chain reads and testnet execution go through the official
``@somnia-chain/markets-sdk`` via the Node bridge in ``dreamdex-bridge/``. No
analytic logic lives here — this package is transport + normalization only.
"""

from .adapter import DreamdexAdapter
from .config import DreamdexConfig

__all__ = ["DreamdexAdapter", "DreamdexConfig"]
