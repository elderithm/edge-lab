"""CSV export of arbitrage-scan results (stable headers)."""

from __future__ import annotations

import csv
from decimal import Decimal

from helpers import book, make_market

from edge_lab.analysis.arb import analyze_complete_set
from edge_lab.export.csv_export import ARB_HEADERS, write_arb_candidates_csv

D = Decimal


def _result(yes_ask, no_ask):
    yes = book("y", [], [(yes_ask, "1000")])
    no = book("n", [], [(no_ask, "1000")])
    return analyze_complete_set(
        make_market(),
        yes,
        no,
        notional=D("10"),
        fee_buffer_bps=D("50"),
        slippage_buffer_bps=D("50"),
        min_edge_bps=D("25"),
    )


def test_write_arb_csv_headers_and_rows(tmp_path):
    results = [_result("0.30", "0.30"), _result("0.49", "0.49")]
    out = tmp_path / "cands.csv"
    n = write_arb_candidates_csv(results, out)
    assert n == 2
    with out.open() as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ARB_HEADERS
    assert len(rows) == 3  # header + 2
    # First data row is the strong-edge market; is_candidate column is truthy.
    candidate_col = ARB_HEADERS.index("is_candidate")
    assert rows[1][candidate_col] == "True"


def test_write_arb_csv_creates_parent_dir(tmp_path):
    out = tmp_path / "nested" / "dir" / "cands.csv"
    n = write_arb_candidates_csv([_result("0.30", "0.30")], out)
    assert n == 1
    assert out.exists()
