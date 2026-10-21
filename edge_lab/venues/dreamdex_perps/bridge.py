"""Invoke the Node Perps bridge as a subprocess (JSON in / JSON out).

Same contract as the Event Contracts bridge, but a separate Node package
(``perps-bridge/``) pinned to the SDK version the Perps docs target, so neither
venue's SDK upgrade can break the other.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from .config import PerpsConfig
from .errors import PerpsBridgeUnavailable, PerpsRpcError, perps_error_for


class PerpsBridge:
    def __init__(self, config: PerpsConfig) -> None:
        self.config = config

    def invoke(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not (self.config.bridge_dir / "src" / "index.ts").exists():
            raise PerpsBridgeUnavailable(f"perps bridge entry not found under {self.config.bridge_dir}")
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
            raise PerpsBridgeUnavailable(f"node runtime '{self.config.node_bin}' not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise PerpsRpcError(f"perps bridge '{command}' timed out after {self.config.timeout_seconds}s") from exc

        out = (proc.stdout or "").strip()
        if not out:
            stderr = (proc.stderr or "").strip()[:300]
            raise PerpsBridgeUnavailable(f"perps bridge produced no output (rc={proc.returncode}): {stderr}")
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise PerpsBridgeUnavailable(f"perps bridge returned non-JSON output: {out[:200]}") from exc
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"] or {}
            raise perps_error_for(str(err.get("code", "BRIDGE_ERROR")), str(err.get("message", "unknown error")))
        if not isinstance(payload, dict):
            raise PerpsBridgeUnavailable("perps bridge returned a non-object result")
        return payload
