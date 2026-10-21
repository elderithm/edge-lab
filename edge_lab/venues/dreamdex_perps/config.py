"""DreamDEX Perps configuration (env-driven; paper by default).

Perps runs on Somnia Hideki Testnet (chain id 50383) with its own bridge and SDK
version, fully separate from the Event Contracts config (Shannon, 50312). The
signer key is NEVER read into Python: the bridge subprocess inherits
``PERPS_PRIVATE_KEY`` from the environment; Python only records its presence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# repo_root/edge_lab/venues/dreamdex_perps/config.py -> parents[3] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BRIDGE_DIR = _REPO_ROOT / "perps-bridge"

HIDEKI_CHAIN_ID = 50383
HIDEKI_NETWORK = "hideki-testnet"
DEFAULT_INDEXER_URL = "https://hideki-dev.smk.somnia.host/v1/graphql"
DEFAULT_RPC_URL = "https://api.hideki2.infra.testnet.somnia.network"
DEFAULT_WS_RPC_URL = "wss://api.hideki2.infra.testnet.somnia.network/ws"


@dataclass(frozen=True)
class PerpsConfig:
    network: str = ""  # must be exactly "hideki-testnet" for writes
    trading_mode: str = "paper"  # "paper" | "testnet" (no mainnet perps mode exists)
    indexer_url: str = DEFAULT_INDEXER_URL
    rpc_url: str = DEFAULT_RPC_URL
    ws_rpc_url: str = DEFAULT_WS_RPC_URL
    account: str = ""  # optional PUBLIC address for read-only account views
    has_signer: bool = False  # PERPS_PRIVATE_KEY present (value never stored)
    max_order_notional: str = "100"  # bridge-side hard cap (quote units)
    bridge_dir: Path = _DEFAULT_BRIDGE_DIR
    node_bin: str = "node"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PerpsConfig:
        env = os.environ if environ is None else environ
        return cls(
            network=(env.get("NETWORK") or "").lower(),
            trading_mode=(env.get("TRADING_MODE") or "paper").lower(),
            indexer_url=env.get("PERPS_INDEXER_URL") or DEFAULT_INDEXER_URL,
            rpc_url=env.get("PERPS_RPC_URL") or DEFAULT_RPC_URL,
            ws_rpc_url=env.get("PERPS_WS_RPC_URL") or DEFAULT_WS_RPC_URL,
            account=(env.get("PERPS_ACCOUNT") or "").lower(),
            has_signer=bool(env.get("PERPS_PRIVATE_KEY")),
            max_order_notional=env.get("PERPS_MAX_ORDER_NOTIONAL") or "100",
            bridge_dir=Path(env["PERPS_BRIDGE_DIR"]) if env.get("PERPS_BRIDGE_DIR") else _DEFAULT_BRIDGE_DIR,
            node_bin=env.get("NODE_BIN", "node"),
            timeout_seconds=float(env.get("PERPS_BRIDGE_TIMEOUT", "60")),
        )

    @property
    def chain_id(self) -> int:
        return HIDEKI_CHAIN_ID

    @property
    def is_paper(self) -> bool:
        return self.trading_mode != "testnet"

    def write_blockers(self) -> list[str]:
        """Reasons this config may NOT submit a testnet transaction (empty = allowed)."""
        out: list[str] = []
        if self.trading_mode != "testnet":
            out.append(f"TRADING_MODE={self.trading_mode or 'paper'} (need testnet)")
        if self.network != HIDEKI_NETWORK:
            out.append(f"NETWORK={self.network or '<unset>'} (need {HIDEKI_NETWORK})")
        if not self.has_signer:
            out.append("PERPS_PRIVATE_KEY is not set (dedicated testnet signer required)")
        return out

    def env_for_subprocess(self) -> dict[str, str]:
        """Env overrides passed to the bridge (never includes the private key)."""
        return {
            "NETWORK": self.network,
            "TRADING_MODE": self.trading_mode,
            "PERPS_INDEXER_URL": self.indexer_url,
            "PERPS_RPC_URL": self.rpc_url,
            "PERPS_WS_RPC_URL": self.ws_rpc_url,
            "PERPS_ACCOUNT": self.account,
            "PERPS_MAX_ORDER_NOTIONAL": self.max_order_notional,
        }
