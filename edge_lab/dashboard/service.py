"""Scan orchestration shared by the CLI and the dashboard.

Caches the underlying snapshot per asset (BTC/ETH fetched once per scan) so a
multi-market scan does not re-fetch the same price feed repeatedly.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from ..core.risk import RiskEngine
from ..core.signal import Signal
from ..core.types import UnderlyingSnapshot
from ..errors import EdgeLabError
from ..strategies.event_contracts import (
    DEFAULT_FEE_BUFFER_BPS,
    DEFAULT_SLIPPAGE_BUFFER_BPS,
    build_event_signal,
)


def scan_signals(
    venue: Any,
    assets: Sequence[str],
    *,
    size: Decimal,
    now: int,
    risk_engine: RiskEngine,
    fee_buffer_bps: Decimal = DEFAULT_FEE_BUFFER_BPS,
    slippage_buffer_bps: Decimal = DEFAULT_SLIPPAGE_BUFFER_BPS,
) -> list[Signal]:
    """Build a ranked list of signals for all live markets in ``assets``.

    A single market failing (bad data, transient RPC) is skipped, never aborting
    the whole scan.
    """
    markets = venue.list_markets(list(assets))
    underlying: dict[str, UnderlyingSnapshot] = {}
    signals: list[Signal] = []
    for m in markets:
        try:
            market = venue.get_market(m.market_id)
            book = venue.get_order_book(m.market_id)
            if market.asset not in underlying:
                underlying[market.asset] = venue.get_underlying(market.asset)
            signals.append(
                build_event_signal(
                    market,
                    book,
                    underlying[market.asset],
                    size=size,
                    now=now,
                    risk_engine=risk_engine,
                    fee_buffer_bps=fee_buffer_bps,
                    slippage_buffer_bps=slippage_buffer_bps,
                )
            )
        except EdgeLabError:
            continue
    signals.sort(key=lambda s: s.rank_score, reverse=True)
    return signals
