"""DreamDEX venue configuration (env-driven, testnet + paper by default).

The private key is NEVER read into Python: it is inherited by the Node bridge
subprocess from the environment. Python only records whether one is present, for
gating messages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...core.types import TradingMode

# repo_root/edge_lab/venues/dreamdex/config.py -> parents[3] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BRIDGE_DIR = _REPO_ROOT / "dreamdex-bridge"

TESTNET_CHAIN_ID = 50312
MAINNET_CHAIN_ID = 5031


@dataclass(frozen=True)
class DreamdexConfig:
    network: str = "testnet"  # "testnet" | "mainnet"
    trading_mode: TradingMode = TradingMode.PAPER
    indexer_url: str = ""
    ws_rpc_url: str = ""
    rpc_url: str = ""
    enable_mainnet_trading: bool = False
    has_signer: bool = False  # PRIVATE_KEY present in env (value never stored)
    bridge_dir: Path = _DEFAULT_BRIDGE_DIR
    node_bin: str = "node"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> DreamdexConfig:
        env = os.environ if environ is None else environ
        mode_raw = (env.get("TRADING_MODE") or "paper").lower()
        try:
            mode = TradingMode(mode_raw)
        except ValueError:
            mode = TradingMode.PAPER
        bridge_dir = Path(env["DREAMDEX_BRIDGE_DIR"]) if env.get("DREAMDEX_BRIDGE_DIR") else _DEFAULT_BRIDGE_DIR
        return cls(
            network=(env.get("NETWORK") or "testnet").lower(),
            trading_mode=mode,
            indexer_url=env.get("INDEXER_URL", ""),
            ws_rpc_url=env.get("WS_RPC_URL", ""),
            rpc_url=env.get("RPC_URL", ""),
            enable_mainnet_trading=(env.get("ENABLE_MAINNET_TRADING") or "false").lower() == "true",
            has_signer=bool(env.get("PRIVATE_KEY")),
            bridge_dir=bridge_dir,
            node_bin=env.get("NODE_BIN", "node"),
            timeout_seconds=float(env.get("DREAMDEX_BRIDGE_TIMEOUT", "30")),
        )

    @property
    def chain_id(self) -> int:
        return MAINNET_CHAIN_ID if self.network == "mainnet" else TESTNET_CHAIN_ID

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TradingMode.PAPER

    def env_for_subprocess(self) -> dict[str, str]:
        """Env overrides passed to the bridge (never includes PRIVATE_KEY)."""
        return {
            "NETWORK": self.network,
            "TRADING_MODE": self.trading_mode.value,
            "INDEXER_URL": self.indexer_url,
            "WS_RPC_URL": self.ws_rpc_url,
            "RPC_URL": self.rpc_url,
            "ENABLE_MAINNET_TRADING": "true" if self.enable_mainnet_trading else "false",
        }
