"""Invoke the Node DreamDEX bridge as a subprocess (JSON in / JSON out).

The bridge calls the official ``@somnia-chain/markets-sdk``. Python passes the
command + params, inherits the environment (so a configured ``PRIVATE_KEY``
reaches the bridge without Python reading it), and parses the JSON result.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .config import DreamdexConfig
from .errors import BridgeUnavailable, RpcError, error_for


class DreamdexBridge:
    def __init__(self, config: DreamdexConfig) -> None:
        self.config = config

    def invoke(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import os

        if not (self.config.bridge_dir / "src" / "index.ts").exists():
            raise BridgeUnavailable(f"bridge entry not found under {self.config.bridge_dir}")
        argv = [self.config.node_bin, "src/index.ts", command, json.dumps(params or {})]
        env = {**os.environ, **self.config.env_for_subprocess()}
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.config.bridge_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise BridgeUnavailable(f"node runtime '{self.config.node_bin}' not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RpcError(f"bridge command '{command}' timed out after {self.config.timeout_seconds}s") from exc

        out = (proc.stdout or "").strip()
        if not out:
            stderr = (proc.stderr or "").strip()[:300]
            raise BridgeUnavailable(f"bridge produced no output (rc={proc.returncode}): {stderr}")
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise BridgeUnavailable(f"bridge returned non-JSON output: {out[:200]}") from exc

        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"] or {}
            raise error_for(str(err.get("code", "BRIDGE_ERROR")), str(err.get("message", "unknown error")))
        if not isinstance(payload, dict):
            raise BridgeUnavailable("bridge returned a non-object result")
        return payload
