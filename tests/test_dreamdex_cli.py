"""DreamDEX CLI (mounted under `edge-lab dreamdex`), fixture-driven (§48/§50)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from edge_lab.cli import app

runner = CliRunner()
BTC_A = "0x0000000000000000000000000000000000000000000000000000000000000001"


def _json_tail(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def test_dreamdex_mounted_and_polymarket_intact():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dreamdex" in result.output
    assert "analyze-wallet" in result.output  # Polymarket command still present


def test_scan_fixture_json():
    result = runner.invoke(app, ["dreamdex", "scan", "--source", "fixture", "--json"])
    assert result.exit_code == 0
    payload = _json_tail(result.output)
    assert payload["scanned"] >= 1
    states = {s["state"] for s in payload["signals"]}
    assert "BUY_UP" in states  # the BTC fixture is a clean edge


def test_inspect_fixture_json_has_risk_chain():
    result = runner.invoke(app, ["dreamdex", "inspect", BTC_A, "--source", "fixture", "--json"])
    assert result.exit_code == 0
    payload = _json_tail(result.output)
    assert payload["risk"]["checks"]
    assert payload["probability"]["model_version"]
    assert payload["edge"]["up"]["executable_edge_bps"] is not None


def test_paper_trade_fixture_records(tmp_path):
    db = str(tmp_path / "d.db")
    result = runner.invoke(app, ["dreamdex", "paper-trade", BTC_A, "--source", "fixture", "--db", db])
    assert result.exit_code == 0
    assert "PAPER UP" in result.output
    # report reflects the recorded trade
    rep = runner.invoke(app, ["dreamdex", "report", "--db", db, "--json"])
    payload = _json_tail(rep.output)
    assert payload["summary"]["trades"] == 1


def test_execute_refused_in_paper_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    result = runner.invoke(app, ["dreamdex", "execute", BTC_A, "--yes"])
    assert result.exit_code == 1
    assert "paper" in result.output.lower()


def test_scan_labels_fixture_as_simulated():
    # The SIMULATED banner must appear (never presented as live).
    result = runner.invoke(app, ["dreamdex", "scan", "--source", "fixture"])
    assert result.exit_code == 0
    assert "SIMULATED" in result.output
