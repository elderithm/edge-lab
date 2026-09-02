"""CSV export with stable headers and ISO-8601 UTC timestamps."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import WalletActivity, iso_utc

if TYPE_CHECKING:
    from ..analysis.arb import ArbResult

# Stable, ordered header row. Appending new columns is allowed; reordering or
# renaming existing ones is a breaking change for downstream consumers.
ACTIVITY_HEADERS = [
    "timestamp_utc",
    "timestamp_unix",
    "tx_hash",
    "asset",
    "side",
    "type",
    "price",
    "size",
    "usdc_size",
    "outcome",
    "title",
    "event_slug",
    "condition_id",
]


# Stable header row for exported arbitrage-scan candidates.
ARB_HEADERS = [
    "slug",
    "question",
    "top_of_book_sum",
    "executable_quantity",
    "fully_filled",
    "cost_per_set",
    "gross_edge_bps",
    "buffer_bps",
    "net_edge_bps",
    "max_size_at_min_edge",
    "is_candidate",
    "note",
]


def _fmt(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def write_activity_csv(activities: Iterable[WalletActivity], path: str | Path) -> int:
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(ACTIVITY_HEADERS)
        for a in activities:
            writer.writerow(
                [
                    iso_utc(a.timestamp),
                    a.timestamp if a.timestamp is not None else "",
                    a.tx_hash,
                    a.asset,
                    a.side,
                    a.activity_type,
                    _fmt(a.price),
                    _fmt(a.size),
                    _fmt(a.usdc_size),
                    a.outcome,
                    a.title,
                    a.event_slug,
                    a.condition_id,
                ]
            )
            count += 1
    return count


def write_arb_candidates_csv(results: Iterable[ArbResult], path: str | Path) -> int:
    """Write arbitrage-scan results with stable headers. Returns row count."""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(ARB_HEADERS)
        for r in results:
            writer.writerow(
                [
                    r.slug,
                    r.question,
                    _fmt(r.top_of_book_sum),
                    _fmt(r.executable_quantity),
                    r.fully_filled,
                    _fmt(r.cost_per_set),
                    _fmt(r.gross_edge_bps),
                    _fmt(r.buffer_bps),
                    _fmt(r.net_edge_bps),
                    _fmt(r.max_size_at_min_edge),
                    r.is_candidate,
                    r.note,
                ]
            )
            count += 1
    return count
