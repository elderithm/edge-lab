"""Dashboard HTTP server endpoints (fixture source, offline)."""

from __future__ import annotations

import json
import threading
import urllib.request
from decimal import Decimal

import pytest

from edge_lab.dashboard.server import make_server


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, source="fixture", assets=("BTC", "ETH"), size=Decimal("5"))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _get(base: str, path: str) -> str:
    return urllib.request.urlopen(base + path, timeout=10).read().decode()


def test_serves_page(server):
    html = _get(server, "/")
    assert "DreamDEX Edge Lab" in html
    assert "/api/scan" in html


def test_health(server):
    assert json.loads(_get(server, "/api/health"))["ok"] is True


def test_scan_endpoint_labels_simulated(server):
    data = json.loads(_get(server, "/api/scan"))
    assert data["source"] == "SIMULATED"  # never mislabels a fixture as live
    assert len(data["signals"]) >= 1
    assert {"BUY_UP"} <= {s["state"] for s in data["signals"]}


def test_inspect_endpoint_has_reasoning_chain(server):
    data = json.loads(_get(server, "/api/scan"))
    mid = data["signals"][0]["market"]["market_id"]
    d = json.loads(_get(server, "/api/inspect?market_id=" + mid))
    assert d["risk"]["checks"]
    assert d["probability"]["model_version"]
    assert "up_asks" in d["order_book"]


def test_inspect_requires_market_id(server):
    d = json.loads(_get(server, "/api/inspect"))
    assert "error" in d


def test_unknown_path_404(server):
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(server, "/nope")
    assert ei.value.code == 404
