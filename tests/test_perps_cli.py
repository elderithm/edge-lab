"""`edge-lab perps` CLI and the dashboard Perps view (fixture source, offline)."""

from __future__ import annotations

import json
import threading
import urllib.request
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from edge_lab.cli import app
from edge_lab.dashboard.server import make_server
from edge_lab.venues.dreamdex_perps.adapter import PerpsAdapter

runner = CliRunner()


def _json_tail(output: str) -> dict:
    return json.loads(output[output.index("{") :])


@pytest.fixture
def no_writes(monkeypatch):
    calls: list[object] = []

    def boom(self, approval):  # pragma: no cover - must never run
        calls.append(approval)
        raise AssertionError("place_order must not be reached")

    monkeypatch.setattr(PerpsAdapter, "place_order", boom)
    return calls


def test_perps_mounted_alongside_existing_commands():
    out = runner.invoke(app, ["--help"]).output
    assert "perps" in out and "dreamdex" in out and "analyze-wallet" in out


def test_scan_and_inspect_fixture_json():
    r = runner.invoke(app, ["perps", "scan", "--source", "fixture", "--json"])
    assert r.exit_code == 0, r.output
    data = _json_tail(r.output)
    assert data["source"] == "SIMULATED_FIXTURE" and data["count"] == 4
    assert all(a["expected_edge"]["status"] == "NOT_ESTIMATED" for a in data["assessments"])
    r = runner.invoke(app, ["perps", "inspect", "BTC", "--source", "fixture", "--json"])
    assert r.exit_code == 0 and _json_tail(r.output)["market"]["symbol"] == "BTC-PERP"


def test_inspect_unknown_market_is_clean_error():
    r = runner.invoke(app, ["perps", "inspect", "NOPE", "--source", "fixture"])
    assert r.exit_code == 1 and "no perp market" in r.output


def test_preview_and_paper_lifecycle(tmp_path):
    db = str(tmp_path / "p.db")
    r = runner.invoke(app, ["perps", "preview", "BTC", "--side", "long", "--size", "0.001", "--source", "fixture",
                            "--db", db, "--json"])  # fmt: skip
    assert r.exit_code == 0, r.output
    pv = _json_tail(r.output)
    assert pv["paper"]["approved"] and pv["testnet"] is None and "UNSIGNED" in pv["label"]
    r = runner.invoke(app, ["perps", "paper-trade", "BTC", "--side", "long", "--size", "0.001",
                            "--source", "fixture", "--db", db])  # fmt: skip
    assert r.exit_code == 0 and "PAPER #1" in r.output and "SIMULATED" in r.output
    r = runner.invoke(app, ["perps", "paper-close", "1", "--source", "fixture", "--db", db])
    assert r.exit_code == 0 and "realized" in r.output
    r = runner.invoke(app, ["perps", "report", "--source", "fixture", "--db", db, "--json"])
    rep = _json_tail(r.output)
    assert rep["paper_summary"]["closed"] == 1 and rep["testnet_orders"] == []


def test_paper_trade_blocked_by_risk(tmp_path):
    r = runner.invoke(app, ["perps", "paper-trade", "BTC", "--side", "long", "--size", "0.000015",
                            "--source", "fixture", "--db", str(tmp_path / "p.db")])  # fmt: skip
    assert r.exit_code == 1 and "BLOCKED" in r.output and "lot size" in r.output


def test_bad_side_and_size():
    r = runner.invoke(app, ["perps", "preview", "BTC", "--side", "up", "--size", "1", "--source", "fixture"])
    assert r.exit_code == 1 and "long or short" in r.output
    r = runner.invoke(app, ["perps", "preview", "BTC", "--side", "long", "--size", "abc", "--source", "fixture"])
    assert r.exit_code == 1 and "decimal" in r.output


def test_execute_refused_in_paper_mode_before_any_read(monkeypatch, no_writes):
    for k in ("TRADING_MODE", "NETWORK", "PERPS_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(PerpsAdapter, "resolve", lambda *a: (_ for _ in ()).throw(AssertionError("no read")))
    r = runner.invoke(app, ["perps", "execute", "BTC", "--side", "long", "--size", "0.001", "--yes"])
    assert r.exit_code == 1 and "not enabled" in r.output
    assert no_writes == []


def test_execute_wrong_network_refused(monkeypatch, no_writes):
    monkeypatch.setenv("TRADING_MODE", "testnet")
    monkeypatch.setenv("NETWORK", "testnet")  # Shannon (Event Contracts) is not the perps network
    monkeypatch.setenv("PERPS_PRIVATE_KEY", "0x" + "1" * 64)
    r = runner.invoke(app, ["perps", "execute", "BTC", "--side", "long", "--size", "0.001", "--yes"])
    assert r.exit_code == 1 and "hideki-testnet" in r.output
    assert no_writes == []


def test_execute_risk_block_and_missing_yes_never_submit(monkeypatch, no_writes):
    from perps_helpers import snapshot

    snap = snapshot()
    monkeypatch.setenv("TRADING_MODE", "testnet")
    monkeypatch.setenv("NETWORK", "hideki-testnet")
    monkeypatch.setenv("PERPS_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setattr(PerpsAdapter, "resolve", lambda self, q: snap.market)
    monkeypatch.setattr(PerpsAdapter, "get_snapshot", lambda self, mid: snap)
    monkeypatch.setattr(PerpsAdapter, "signer_address", lambda self: "0x" + "9" * 40)

    class Acct:
        equity = Decimal(1000)
        positions = ()

    monkeypatch.setattr(PerpsAdapter, "get_account", lambda self, a=None: Acct())
    preview = {
        "sizing": {"priceable": True, "placeable": True, "maxQuantity": "100000000", "limitedBy": "collateral"},
        "margin": {"priceable": True, "sufficient": True, "isolationBlocked": False},
        "liquidation": {"priceable": False},
        "precisionProblems": [],
    }
    monkeypatch.setattr(PerpsAdapter, "preview_order", lambda self, *a, **k: preview)
    # risk block: misaligned lot
    r = runner.invoke(app, ["perps", "execute", "BTC", "--side", "long", "--size", "0.000015", "--yes"])
    assert r.exit_code == 1 and "blocked by risk engine" in r.output
    # approved but no --yes
    r = runner.invoke(app, ["perps", "execute", "BTC", "--side", "long", "--size", "0.5"])
    assert r.exit_code == 1 and "APPROVED" in r.output and "--yes" in r.output
    assert no_writes == []


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, source="fixture", assets=("BTC",), size=Decimal(5), perps_source="fixture")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(base: str, path: str) -> str:
    return urllib.request.urlopen(base + path, timeout=10).read().decode()


def test_dashboard_perps_view(server, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # paper db is created under .edge-lab/ in cwd
    assert "DreamDEX Perps Edge Lab" in _get(server, "/perps")
    assert "Perps view" in _get(server, "/")  # existing Event Contracts page preserved, now linked
    scan = json.loads(_get(server, "/api/perps/scan"))
    assert scan["source"] == "SIMULATED_FIXTURE" and scan["count"] == 4
    mid = scan["assessments"][0]["market"]["market_id"]
    ins = json.loads(_get(server, f"/api/perps/inspect?market={mid}"))
    assert ins["order_book"]["bids"] and ins["expected_edge"]["status"] == "NOT_ESTIMATED"
    pv = json.loads(_get(server, "/api/perps/preview?market=BTC&side=long&size=0.001"))
    assert pv["paper"]["approved"] and "never submits" in pv["execution_note"]
    assert "error" in json.loads(_get(server, "/api/perps/preview?market=BTC&side=up&size=1"))
    paper = json.loads(_get(server, "/api/perps/paper"))
    assert paper["positions"] == [] and paper["testnet_orders"] == []
    assert json.loads(_get(server, "/api/perps/execute")).get("error") == "not found"  # no execution endpoint
