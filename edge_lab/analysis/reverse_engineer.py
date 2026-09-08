"""Strategy reverse-engineering for a public wallet.

The deliverable strictly separates four epistemic categories:

* **facts** — directly observed in public data;
* **derived** — computed from those facts;
* **estimates** — rely on assumptions (always labeled);
* **unknowns** — cannot be reconstructed reliably from public data.

Candidate rules are discovered on an *earlier* chronological segment and
evaluated on a *later* one. In-sample fit is never presented as evidence of a
reproducible edge.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from ..models import WalletActivity, iso_utc
from .wallet import analyze_wallet

_PRICE_BUCKETS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("<0.10", Decimal("0.0"), Decimal("0.10")),
    ("0.10-0.30", Decimal("0.10"), Decimal("0.30")),
    ("0.30-0.50", Decimal("0.30"), Decimal("0.50")),
    ("0.50-0.70", Decimal("0.50"), Decimal("0.70")),
    ("0.70-0.90", Decimal("0.70"), Decimal("0.90")),
    (">=0.90", Decimal("0.90"), Decimal("1.0000001")),
)


def _bucket_for(price: Decimal) -> str:
    for label, lo, hi in _PRICE_BUCKETS:
        if lo <= price < hi:
            return label
    return "unknown"


@dataclass
class CandidatePattern:
    pattern_id: str
    description: str
    discovery_support: int
    discovery_coverage_pct: Decimal
    validation_support: int
    validation_coverage_pct: Decimal
    stability_note: str
    sample_warning: str | None
    in_sample_selected: bool = True


@dataclass
class ReverseEngineerResult:
    address: str
    utc_offset_hours: int
    facts: dict[str, object]
    derived: dict[str, object]
    estimates: dict[str, object]
    unknowns: list[str]
    candidates: list[CandidatePattern] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, object]:
        return {
            "address": self.address,
            "utc_offset_hours": self.utc_offset_hours,
            "facts": self.facts,
            "derived": self.derived,
            "estimates": self.estimates,
            "unknowns": self.unknowns,
            "candidate_patterns": [_pattern_dict(c) for c in self.candidates],
            "limitations": self.limitations,
        }


def _pattern_dict(c: CandidatePattern) -> dict[str, object]:
    d = asdict(c)
    d["discovery_coverage_pct"] = str(c.discovery_coverage_pct)
    d["validation_coverage_pct"] = str(c.validation_coverage_pct)
    return d


def build_reverse_engineering(
    activities: Sequence[WalletActivity],
    *,
    address: str,
    utc_offset_hours: int = 0,
) -> ReverseEngineerResult:
    items = list(activities)
    analysis = analyze_wallet(items, utc_offset_hours=utc_offset_hours)

    dated = sorted([a for a in items if a.timestamp is not None], key=lambda a: a.timestamp or 0)
    offset_tz = timezone(timedelta(hours=utc_offset_hours))

    facts: dict[str, object] = {
        "record_count": analysis.record_count,
        "dated_count": analysis.dated_count,
        "time_range_utc": (
            [iso_utc(analysis.time_range[0]), iso_utc(analysis.time_range[1])] if analysis.time_range else None
        ),
        "buy_count": analysis.buy_count,
        "sell_count": analysis.sell_count,
        "observed_notional_usdc": str(analysis.observed_notional),
        "top_markets": [{"market": m, "count": c} for m, c in analysis.market_concentration],
    }

    derived: dict[str, object] = {
        "hour_local_distribution": {str(k): v for k, v in sorted(analysis.hour_local.items())},
        "weekday_local_distribution": analysis.weekday_local,
        "entry_price_buckets": analysis.price_buckets,
        "notional_buckets": analysis.notional_buckets,
        "busiest_local_window": _busiest_window(analysis.hour_local, analysis.dated_count),
    }

    # Estimated cash flow is NOT realized P&L; open positions are ignored here.
    buy_usdc = sum((a.usdc_size for a in items if a.side == "BUY" and a.usdc_size is not None), Decimal(0))
    sell_usdc = sum((a.usdc_size for a in items if a.side == "SELL" and a.usdc_size is not None), Decimal(0))
    estimates: dict[str, object] = {
        "estimated_net_cash_flow_usdc": str(sell_usdc - buy_usdc),
        "estimated_net_cash_flow_method": (
            "sum(SELL usdcSize) - sum(BUY usdcSize) from public activity; "
            "NOT realized P&L, ignores open positions, unresolved markets, fees, and off-platform hedges"
        ),
    }

    unknowns = [
        "true realized P&L (requires complete resolved-position accounting)",
        "trader intent, conviction, and private information set",
        "capital base, funding history, and leverage",
        "hedges or correlated positions held elsewhere",
        "whether observed order was the trader's own decision vs. copy/bot activity",
    ]

    candidates = _discover_candidates(dated, offset_tz)

    limitations = [
        "A public trade feed is not a complete strategy: it omits intent, funding, hedges, and private information.",
        "Candidate patterns were selected by inspecting this same wallet's history (in-sample bias).",
        "Out-of-sample coverage here is descriptive, not a profitability test; "
        "only forward paper testing can falsify a rule.",
    ]
    if analysis.record_count < 50:
        limitations.append(f"Small sample ({analysis.record_count} records): all patterns are low-confidence.")

    return ReverseEngineerResult(
        address=address,
        utc_offset_hours=utc_offset_hours,
        facts=facts,
        derived=derived,
        estimates=estimates,
        unknowns=unknowns,
        candidates=candidates,
        limitations=limitations,
    )


def _busiest_window(hour_local: dict[int, int], total: int, width: int = 3) -> dict[str, object]:
    if not hour_local or total == 0:
        return {"window": None, "coverage_pct": "0"}
    best_start, best_count = 0, -1
    for start in range(24):
        count = sum(hour_local.get((start + i) % 24, 0) for i in range(width))
        if count > best_count:
            best_start, best_count = start, count
    end = (best_start + width - 1) % 24
    coverage = (Decimal(best_count) / Decimal(total) * 100).quantize(Decimal("0.1"))
    return {"window": f"{best_start:02d}:00-{end:02d}:59 (local)", "coverage_pct": str(coverage)}


def _discover_candidates(dated: list[WalletActivity], offset_tz: timezone) -> list[CandidatePattern]:
    """Discover on the earlier half, evaluate on the later half."""
    buys = [a for a in dated if a.side == "BUY" and a.price is not None]
    if len(buys) < 4:
        return []
    mid = len(buys) // 2
    discovery, validation = buys[:mid], buys[mid:]
    if not discovery or not validation:
        return []

    def key(a: WalletActivity) -> tuple[str, str]:
        assert a.price is not None
        assert a.timestamp is not None
        local_hour = datetime.fromtimestamp(a.timestamp, tz=UTC).astimezone(offset_tz).hour
        band = f"{(local_hour // 3) * 3:02d}-{((local_hour // 3) * 3 + 2):02d}h"
        return (_bucket_for(a.price), band)

    disc_counts: dict[tuple[str, str], int] = {}
    for a in discovery:
        k = key(a)
        disc_counts[k] = disc_counts.get(k, 0) + 1
    val_counts: dict[tuple[str, str], int] = {}
    for a in validation:
        k = key(a)
        val_counts[k] = val_counts.get(k, 0) + 1

    ranked = sorted(disc_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    candidates: list[CandidatePattern] = []
    for idx, ((bucket, band), support) in enumerate(ranked, start=1):
        disc_cov = (Decimal(support) / Decimal(len(discovery)) * 100).quantize(Decimal("0.1"))
        val_support = val_counts.get((bucket, band), 0)
        val_cov = (Decimal(val_support) / Decimal(len(validation)) * 100).quantize(Decimal("0.1"))
        if val_cov == 0:
            stability = "did not recur in validation segment"
        elif abs(val_cov - disc_cov) <= Decimal("10"):
            stability = "coverage broadly stable across segments"
        else:
            stability = "coverage shifted materially between segments"
        warning = None
        if support < 5:
            warning = f"low discovery support ({support}); likely noise"
        candidates.append(
            CandidatePattern(
                pattern_id=f"P{idx}",
                description=f"BUY where entry_price in {bucket} AND local_hour in {band}",
                discovery_support=support,
                discovery_coverage_pct=disc_cov,
                validation_support=val_support,
                validation_coverage_pct=val_cov,
                stability_note=stability,
                sample_warning=warning,
            )
        )
    return candidates


def write_artifacts(
    result: ReverseEngineerResult,
    activities: Sequence[WalletActivity],
    output_dir: str | Path,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(result.to_summary(), indent=2), encoding="utf-8")

    from ..export.csv_export import write_activity_csv

    trades_path = out / "trades.csv"
    write_activity_csv(activities, trades_path)

    patterns_path = out / "patterns.csv"
    _write_patterns_csv(result, patterns_path)

    report_path = out / "report.md"
    report_path.write_text(_render_report(result), encoding="utf-8")

    return {
        "summary": summary_path,
        "trades": trades_path,
        "patterns": patterns_path,
        "report": report_path,
    }


def _write_patterns_csv(result: ReverseEngineerResult, path: Path) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "pattern_id",
                "description",
                "discovery_support",
                "discovery_coverage_pct",
                "validation_support",
                "validation_coverage_pct",
                "stability_note",
                "sample_warning",
                "in_sample_selected",
            ]
        )
        for c in result.candidates:
            writer.writerow(
                [
                    c.pattern_id,
                    c.description,
                    c.discovery_support,
                    c.discovery_coverage_pct,
                    c.validation_support,
                    c.validation_coverage_pct,
                    c.stability_note,
                    c.sample_warning or "",
                    c.in_sample_selected,
                ]
            )


def _render_report(result: ReverseEngineerResult) -> str:
    lines: list[str] = []
    lines.append(f"# Wallet reverse-engineering report — `{result.address}`")
    lines.append("")
    lines.append(
        "> Research artifact. Findings are **observed patterns requiring forward validation**, "
        "not guaranteed returns. Categories below separate facts from estimates deliberately."
    )
    lines.append("")

    lines.append("## What this wallet demonstrably does (facts)")
    lines.append("")
    tr = result.facts.get("time_range_utc")
    lines.append(f"- Records analyzed: **{result.facts['record_count']}** (dated: {result.facts['dated_count']}).")
    if isinstance(tr, (list, tuple)) and len(tr) == 2:
        lines.append(f"- Activity window (UTC): {tr[0]} → {tr[1]}.")
    lines.append(f"- BUY / SELL counts: {result.facts['buy_count']} / {result.facts['sell_count']}.")
    lines.append(f"- Observed traded notional: {result.facts['observed_notional_usdc']} USDC.")
    top_markets = result.facts.get("top_markets") or []
    if top_markets:
        lines.append("- Most-traded markets:")
        for m in top_markets[:5]:  # type: ignore[index]
            lines.append(f"  - {m['count']}× {m['market']}")
    lines.append("")

    lines.append("## Derived metrics")
    lines.append("")
    window = result.derived.get("busiest_local_window") or {}
    if isinstance(window, dict) and window.get("window"):
        lines.append(
            f"- Busiest local trading window: **{window['window']}** "
            f"covering {window['coverage_pct']}% of dated trades "
            f"(UTC offset {result.utc_offset_hours:+d})."
        )
    lines.append(f"- Entry-price buckets: {result.derived.get('entry_price_buckets')}")
    lines.append(f"- Notional buckets: {result.derived.get('notional_buckets')}")
    lines.append("")

    lines.append("## Estimates (labeled — not realized P&L)")
    lines.append("")
    lines.append(f"- Estimated net cash flow: **{result.estimates['estimated_net_cash_flow_usdc']} USDC**.")
    lines.append(f"  - Method: {result.estimates['estimated_net_cash_flow_method']}")
    lines.append("")

    lines.append("## Candidate patterns (in-sample discovery → out-of-sample coverage)")
    lines.append("")
    if not result.candidates:
        lines.append("- Insufficient dated BUY history to split chronologically; no candidates generated.")
    else:
        lines.append("| ID | Rule | Disc. support | Disc. cov % | Val. support | Val. cov % | Stability |")
        lines.append("|----|------|---------------|-------------|--------------|------------|-----------|")
        for c in result.candidates:
            lines.append(
                f"| {c.pattern_id} | {c.description} | {c.discovery_support} | "
                f"{c.discovery_coverage_pct} | {c.validation_support} | {c.validation_coverage_pct} | "
                f"{c.stability_note} |"
            )
        lines.append("")
        lines.append(
            "Every candidate was selected after looking at this wallet's own history, so the "
            "discovery figures carry in-sample bias. Validation coverage is descriptive only."
        )
    lines.append("")

    lines.append("## What cannot be known from public data")
    lines.append("")
    for u in result.unknowns:
        lines.append(f"- {u}")
    lines.append("")

    lines.append("## How to falsify each candidate")
    lines.append("")
    lines.append(
        "- Freeze the rule, then run `edge-lab paper-follow` (or replay future activity) so each pattern "
        "is evaluated on data it was **not** derived from, under conservative execution assumptions "
        "(latency, drift, fees, slippage, liquidity)."
    )
    lines.append("- A pattern whose paper edge disappears after buffers is falsified for practical use.")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    for lim in result.limitations:
        lines.append(f"- {lim}")
    lines.append("")

    return "\n".join(lines)
