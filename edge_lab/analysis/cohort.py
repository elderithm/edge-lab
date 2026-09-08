"""Cross-wallet cohort comparison.

A pure comparison over several wallets' :class:`WalletAnalysis` results, so a
researcher can see side-by-side whether a behavioral pattern (timing, side
balance, sizing, market focus) is shared across a cohort or idiosyncratic to
one account. It states only what the per-wallet analyses already established;
it does not infer shared strategy from surface similarity.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .wallet import WalletAnalysis, _hour_in_window

_Q = Decimal("0.0001")


@dataclass(frozen=True)
class CohortRow:
    address: str
    record_count: int
    dated_count: int
    buy_count: int
    sell_count: int
    buy_sell_ratio: Decimal | None  # None when there are no SELLs
    observed_notional: Decimal
    top_market: str | None
    top_market_share: Decimal | None  # fraction of this wallet's records
    window_share: Decimal | None  # share inside the claim window, if requested

    def to_dict(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "address": self.address,
            "record_count": self.record_count,
            "dated_count": self.dated_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "buy_sell_ratio": s(self.buy_sell_ratio),
            "observed_notional": str(self.observed_notional),
            "top_market": self.top_market,
            "top_market_share": s(self.top_market_share),
            "window_share": s(self.window_share),
        }


@dataclass(frozen=True)
class CohortComparison:
    utc_offset_hours: int
    claim_window: tuple[int, int] | None
    rows: list[CohortRow]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_size": len(self.rows),
            "utc_offset_hours": self.utc_offset_hours,
            "claim_window": (
                f"{self.claim_window[0]:02d}:00-{self.claim_window[1]:02d}:59" if self.claim_window else None
            ),
            "wallets": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
        }


def build_cohort(
    analyses: list[tuple[str, WalletAnalysis]],
    *,
    utc_offset_hours: int = 0,
    claim_window: tuple[int, int] | None = None,
) -> CohortComparison:
    rows: list[CohortRow] = []
    warnings: list[str] = []
    for address, analysis in analyses:
        if analysis.record_count == 0:
            warnings.append(f"{address}: no activity retrieved; excluded from ratios")

        ratio: Decimal | None = None
        if analysis.sell_count > 0:
            ratio = (Decimal(analysis.buy_count) / Decimal(analysis.sell_count)).quantize(_Q)

        top_market = top_share = None
        if analysis.market_concentration:
            name, count = analysis.market_concentration[0]
            top_market = name
            if analysis.record_count > 0:
                top_share = (Decimal(count) / Decimal(analysis.record_count)).quantize(_Q)

        window_share = None
        if claim_window is not None and analysis.dated_count > 0:
            inside = sum(c for h, c in analysis.hour_local.items() if _hour_in_window(h, *claim_window))
            window_share = (Decimal(inside) / Decimal(analysis.dated_count)).quantize(_Q)

        rows.append(
            CohortRow(
                address=address,
                record_count=analysis.record_count,
                dated_count=analysis.dated_count,
                buy_count=analysis.buy_count,
                sell_count=analysis.sell_count,
                buy_sell_ratio=ratio,
                observed_notional=analysis.observed_notional,
                top_market=top_market,
                top_market_share=top_share,
                window_share=window_share,
            )
        )

    if len(rows) < 2:
        warnings.append("cohort comparison is most useful with 2+ wallets")
    return CohortComparison(
        utc_offset_hours=utc_offset_hours,
        claim_window=claim_window,
        rows=rows,
        warnings=warnings,
    )
