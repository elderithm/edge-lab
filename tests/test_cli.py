"""CLI integration: mocked network, JSON output, exit codes, safety framing."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from edge_lab.cli import app, main

runner = CliRunner()


def test_exit_code_usage_error_is_2():
    assert main(["market"]) == 2  # missing required argument
    assert main(["no-such-command"]) == 2


def test_exit_code_runtime_error_is_1(tmp_path):
    assert main(["paper-report", "--db", str(tmp_path / "empty.db")]) == 1


def test_paper_report_lists_open_positions(tmp_path):
    from decimal import Decimal

    from helpers import FakeBooks, activity, book

    from edge_lab.paper.db import PaperDB
    from edge_lab.paper.follower import FollowConfig, PaperFollower

    db_path = str(tmp_path / "p.db")
    with PaperDB(db_path) as db:
        rid = db.create_run("0xw", "{}")
        books = FakeBooks({"yes-token": book("yes-token", [], [("0.50", "1000")])})
        follower = PaperFollower(db, books, rid, FollowConfig(paper_usdc=Decimal("10"), max_age_seconds=120))
        follower.process_activities([activity(side="BUY", price=Decimal("0.50"))], 1_767_225_700)

    result = runner.invoke(app, ["paper-report", "--db", db_path])
    assert result.exit_code == 0
    assert "Open positions" in result.output


def test_paper_runs_empty(tmp_path):
    db = str(tmp_path / "p.db")
    result = runner.invoke(app, ["paper-runs", "--db", db])
    assert result.exit_code == 0
    assert "No paper runs" in result.output


def test_paper_runs_lists_created_run(tmp_path):
    from edge_lab.paper.db import PaperDB

    db_path = str(tmp_path / "p.db")
    with PaperDB(db_path) as db:
        db.create_run("0xWALLET", "{}")
    result = runner.invoke(app, ["paper-runs", "--db", db_path, "--json"])
    assert result.exit_code == 0
    runs = json.loads(result.output)["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == 1
    assert runs[0]["source_wallet"] == "0xWALLET"


def market_row():
    return {
        "slug": "will-x-happen",
        "question": "Will X happen?",
        "conditionId": "0xcond",
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["1111","2222"]',
        "acceptingOrders": True,
    }


def test_help_exit_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "paper-trading" in result.output


def test_version_flag():
    from edge_lab import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_geo_json(httpx_mock):
    httpx_mock.add_response(json={"blocked": False, "country": "JP"})
    result = runner.invoke(app, ["geo", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["country"] == "JP"


def test_geo_blocked_mentions_no_bypass(httpx_mock):
    httpx_mock.add_response(json={"blocked": True, "country": "US"})
    result = runner.invoke(app, ["geo"])
    assert result.exit_code == 0
    assert "will not bypass" in result.output.lower()


def test_analyze_wallet_json(httpx_mock):
    rows = [
        {
            "timestamp": 1_767_225_600,
            "transactionHash": "0x1",
            "asset": "1111",
            "side": "BUY",
            "type": "TRADE",
            "price": "0.5",
            "size": "10",
            "usdcSize": "5",
            "title": "Market A",
        }
    ]
    httpx_mock.add_response(json=rows)
    result = runner.invoke(app, ["analyze-wallet", "0xwallet", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["record_count"] == 1


def test_analyze_wallet_human_shows_weekday_and_outcome(httpx_mock):
    httpx_mock.add_response(
        json=[
            {
                "timestamp": 1_767_225_600,
                "transactionHash": "0x1",
                "asset": "1111",
                "side": "BUY",
                "type": "TRADE",
                "price": "0.5",
                "size": "10",
                "usdcSize": "5",
                "outcome": "Yes",
                "title": "Market A",
            }
        ]
    )
    result = runner.invoke(app, ["analyze-wallet", "0xwallet"])
    assert result.exit_code == 0
    assert "Activity by weekday" in result.output
    assert "Outcome/side concentration" in result.output


def test_analyze_wallet_claim_window_json(httpx_mock):
    rows = [
        {
            "timestamp": 1_767_225_600,  # 09:00 at UTC+9
            "transactionHash": "0x1",
            "asset": "1111",
            "side": "BUY",
            "type": "TRADE",
            "price": "0.5",
            "size": "10",
            "usdcSize": "5",
        }
    ]
    httpx_mock.add_response(json=rows)
    result = runner.invoke(app, ["analyze-wallet", "0xw", "--utc-offset", "9", "--claim-window", "6-9", "--json"])
    assert result.exit_code == 0
    claim = json.loads(result.output)["claim_window_evaluation"]
    assert claim["inside_pct"] == "100.0"


def test_analyze_wallet_bad_claim_window_exits_1():
    # Window is parsed before any network call, so no HTTP mock is needed.
    result = runner.invoke(app, ["analyze-wallet", "0xw", "--claim-window", "not-a-window"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_analyze_cohort_json(httpx_mock):
    def rows(side):
        return [
            {
                "timestamp": 1_767_225_600,
                "transactionHash": f"0x{side}",
                "asset": "1111",
                "side": side,
                "type": "TRADE",
                "price": "0.5",
                "size": "10",
                "usdcSize": "5",
                "title": "Market A",
            }
        ]

    httpx_mock.add_response(json=rows("BUY"))  # wallet A activity
    httpx_mock.add_response(json=rows("SELL"))  # wallet B activity
    result = runner.invoke(app, ["analyze-cohort", "0xA", "0xB", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["cohort_size"] == 2
    assert [w["address"] for w in payload["wallets"]] == ["0xA", "0xB"]


def test_export_wallet_writes_csv(httpx_mock, tmp_path):
    httpx_mock.add_response(json=[])
    out = tmp_path / "act.csv"
    result = runner.invoke(app, ["export-wallet", "0xwallet", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert out.read_text().splitlines()[0].startswith("timestamp_utc,")


def test_arb_not_found_exits_1(httpx_mock):
    httpx_mock.add_response(json=[])  # gamma returns no market
    result = runner.invoke(app, ["arb", "missing-slug"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_arb_json_candidate(httpx_mock):
    httpx_mock.add_response(json=[market_row()])  # gamma slug lookup
    # two order books (YES then NO)
    httpx_mock.add_response(json={"bids": [], "asks": [{"price": "0.30", "size": "100"}]})
    httpx_mock.add_response(json={"bids": [], "asks": [{"price": "0.30", "size": "100"}]})
    result = runner.invoke(app, ["arb", "will-x-happen", "--json", "--notional", "10"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["is_candidate"] is True
