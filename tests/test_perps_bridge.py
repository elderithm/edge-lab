"""Perps bridge contract: subprocess JSON, error mapping, config/network isolation.

A stand-in "bridge" is a Python script saved as ``src/index.ts`` and run with
``node_bin=sys.executable``, so these tests need neither Node nor a network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from edge_lab.venues.dreamdex.config import DreamdexConfig
from edge_lab.venues.dreamdex_perps.bridge import PerpsBridge
from edge_lab.venues.dreamdex_perps.config import HIDEKI_CHAIN_ID, PerpsConfig
from edge_lab.venues.dreamdex_perps.errors import (
    PerpsBridgeUnavailable,
    PerpsError,
    PerpsOrderRejected,
    PerpsRpcError,
    PerpsTransactionFailed,
    PerpsWriteRefused,
)


def _bridge(tmp_path: Path, body: str, **cfg) -> PerpsBridge:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "index.ts").write_text(body)
    return PerpsBridge(PerpsConfig(bridge_dir=tmp_path, node_bin=sys.executable, **cfg))


def _err(code: str) -> str:
    return f'import json,sys; sys.stdout.write(json.dumps({{"error":{{"code":"{code}","message":"m"}}}})); sys.exit(1)'


def test_ok_payload_and_args(tmp_path):
    b = _bridge(tmp_path, "import json,sys; print(json.dumps({'cmd': sys.argv[1], 'p': json.loads(sys.argv[2])}))")
    assert b.invoke("markets", {"limit": 5}) == {"cmd": "markets", "p": {"limit": 5}}


@pytest.mark.parametrize(
    "code,exc",
    [
        ("WRONG_CHAIN", PerpsWriteRefused),
        ("WRONG_NETWORK", PerpsWriteRefused),
        ("SIGNER_REQUIRED", PerpsWriteRefused),
        ("PAPER_MODE", PerpsWriteRefused),
        ("RISK_NOT_APPROVED", PerpsWriteRefused),
        ("VOUCHER_BLOCKED", PerpsOrderRejected),
        ("MAX_ORDER_SIZE", PerpsOrderRejected),
        ("STALE_MARK_PRICE", PerpsOrderRejected),
        ("ISOLATED_MARKET_BLOCKED", PerpsOrderRejected),
        ("IOC_NO_FILL", PerpsTransactionFailed),
        ("ContractRevertError", PerpsTransactionFailed),
        ("RPC_ERROR", PerpsRpcError),
        ("WS_REQUIRED", PerpsRpcError),
        ("SOMETHING_NEW", PerpsError),
    ],
)
def test_error_codes_map_to_typed_exceptions(tmp_path, code, exc):
    with pytest.raises(exc) as info:
        _bridge(tmp_path, _err(code)).invoke("place-order", {})
    assert info.value.code == code


def test_missing_entry_non_json_and_empty(tmp_path):
    with pytest.raises(PerpsBridgeUnavailable):
        PerpsBridge(PerpsConfig(bridge_dir=tmp_path / "nope")).invoke("markets")
    with pytest.raises(PerpsBridgeUnavailable):
        _bridge(tmp_path, "print('not json')").invoke("markets")
    with pytest.raises(PerpsBridgeUnavailable):
        _bridge(tmp_path, "pass").invoke("markets")


def test_missing_node_runtime(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("")
    with pytest.raises(PerpsBridgeUnavailable):
        PerpsBridge(PerpsConfig(bridge_dir=tmp_path, node_bin="/nonexistent/node")).invoke("markets")


def test_timeout_is_rpc_error(tmp_path):
    b = _bridge(tmp_path, "import time; time.sleep(5)", timeout_seconds=0.5)
    with pytest.raises(PerpsRpcError):
        b.invoke("markets")


def test_private_key_never_passed_via_overrides_and_not_read(tmp_path):
    cfg = PerpsConfig.from_env({"PERPS_PRIVATE_KEY": "0xsecret", "NETWORK": "hideki-testnet"})
    assert cfg.has_signer
    assert "0xsecret" not in repr(cfg)
    assert all("PRIVATE" not in k for k in cfg.env_for_subprocess())


def test_write_blockers():
    assert PerpsConfig().write_blockers()  # default: paper, no network, no signer
    ok = PerpsConfig.from_env({"NETWORK": "hideki-testnet", "TRADING_MODE": "testnet", "PERPS_PRIVATE_KEY": "x"})
    assert ok.write_blockers() == []
    shannon = PerpsConfig.from_env({"NETWORK": "testnet", "TRADING_MODE": "testnet", "PERPS_PRIVATE_KEY": "x"})
    assert any("hideki-testnet" in b for b in shannon.write_blockers())
    mainnet = PerpsConfig.from_env({"NETWORK": "mainnet", "TRADING_MODE": "mainnet", "PERPS_PRIVATE_KEY": "x"})
    assert len(mainnet.write_blockers()) == 2


def test_event_contract_key_does_not_enable_perps():
    cfg = PerpsConfig.from_env({"NETWORK": "hideki-testnet", "TRADING_MODE": "testnet", "PRIVATE_KEY": "0xabc"})
    assert not cfg.has_signer and cfg.write_blockers()


def test_network_isolation_from_event_contracts():
    perps = PerpsConfig.from_env({})
    ec = DreamdexConfig.from_env({})
    assert perps.chain_id == HIDEKI_CHAIN_ID == 50383
    assert ec.chain_id == 50312  # Event Contracts stay on Shannon
    assert perps.bridge_dir.name == "perps-bridge" and ec.bridge_dir.name == "dreamdex-bridge"
    assert "hideki" in perps.indexer_url
