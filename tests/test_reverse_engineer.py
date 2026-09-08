"""Reverse-engineer: chronological split, epistemic categories, artifacts."""

from __future__ import annotations

import json
from decimal import Decimal

from helpers import activity

from edge_lab.analysis.reverse_engineer import build_reverse_engineering, write_artifacts


def sample_activities(n: int = 12):
    acts = []
    base = 1_767_225_600
    for i in range(n):
        acts.append(
            activity(
                timestamp=base + i * 3600,
                tx_hash=f"0x{i}",
                side="BUY",
                price=Decimal("0.85"),
                title=f"Market {i % 3}",
                usdc_size=Decimal("50"),
            )
        )
    return acts


def test_result_has_epistemic_categories():
    result = build_reverse_engineering(sample_activities(), address="0xabc", utc_offset_hours=9)
    assert set(result.facts) >= {"record_count", "buy_count"}
    assert "estimated_net_cash_flow_usdc" in result.estimates
    assert "NOT realized P&L" in result.estimates["estimated_net_cash_flow_method"]
    assert result.unknowns  # non-empty
    assert result.limitations


def test_candidate_coverage_math_stable():
    # 4 BUYs, all price 0.85 (bucket 0.70-0.90) at UTC hour 0 (band 00-02h).
    # Split 2/2 -> one candidate covering 100% of both segments.
    base = 1_767_225_600  # 2026-01-01 00:00 UTC
    acts = [activity(timestamp=base + i * 300, tx_hash=f"0x{i}", side="BUY", price=Decimal("0.85")) for i in range(4)]
    result = build_reverse_engineering(acts, address="0xabc", utc_offset_hours=0)
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.discovery_support == 2
    assert c.validation_support == 2
    assert c.discovery_coverage_pct == Decimal("100.0")
    assert c.validation_coverage_pct == Decimal("100.0")
    assert "stable" in c.stability_note
    assert c.sample_warning is not None  # support < 5


def test_candidate_that_does_not_recur():
    # Early buys in bucket 0.70-0.90; later buys in bucket 0.10-0.30, same hour band.
    base = 1_767_225_600
    early = [activity(timestamp=base + i * 300, tx_hash=f"0xe{i}", side="BUY", price=Decimal("0.85")) for i in range(2)]
    late = [
        activity(timestamp=base + 3600 + i * 300, tx_hash=f"0xl{i}", side="BUY", price=Decimal("0.20"))
        for i in range(2)
    ]
    result = build_reverse_engineering(early + late, address="0xabc", utc_offset_hours=0)
    top = result.candidates[0]  # discovered from the early segment
    assert top.discovery_support == 2
    assert top.validation_support == 0
    assert top.validation_coverage_pct == Decimal("0.0")
    assert "did not recur" in top.stability_note


def test_candidates_are_chronologically_split_and_flagged():
    result = build_reverse_engineering(sample_activities(12), address="0xabc")
    assert result.candidates
    for c in result.candidates:
        assert c.in_sample_selected is True  # honest about in-sample bias
        assert c.discovery_support >= 1


def test_small_sample_yields_no_candidates():
    result = build_reverse_engineering(sample_activities(2), address="0xabc")
    assert result.candidates == []


def test_empty_wallet_produces_artifacts_without_crashing(tmp_path):
    # A wrong/inactive address (0 activities) must not crash and must still
    # emit all artifacts with a clear insufficient-data signal.
    result = build_reverse_engineering([], address="0xempty", utc_offset_hours=9)
    assert result.facts["record_count"] == 0
    assert result.candidates == []
    assert any("Small sample" in lim for lim in result.limitations)

    paths = write_artifacts(result, [], tmp_path / "empty")
    for key in ("summary", "trades", "patterns", "report"):
        assert paths[key].exists()
    # summary.json is valid JSON and reports zero records.
    assert json.loads(paths["summary"].read_text())["facts"]["record_count"] == 0
    # patterns.csv has just the header row.
    assert len(paths["patterns"].read_text().strip().splitlines()) == 1


def test_write_artifacts_creates_all_files(tmp_path):
    acts = sample_activities()
    result = build_reverse_engineering(acts, address="0xabc")
    paths = write_artifacts(result, acts, tmp_path / "report")
    for key in ("summary", "trades", "patterns", "report"):
        assert paths[key].exists()
    summary = json.loads(paths["summary"].read_text())
    assert summary["address"] == "0xabc"
    report_md = paths["report"].read_text()
    assert "requiring forward validation" in report_md
    assert "cannot be known" in report_md.lower()
