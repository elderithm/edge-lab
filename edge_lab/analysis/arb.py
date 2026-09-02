"""Executable-size-aware binary complete-set arbitrage analysis.

A binary market's YES + NO shares form a *complete set*: one share of each
redeems for exactly 1 USDC at resolution. If a complete set can be bought for
less than 1 USDC after fees and slippage, there is an apparent edge.

Crucially we never quote from top-of-book alone when the requested size exceeds
top-level liquidity. We walk the asks and compute the volume-weighted cost, so
insufficient depth is reported as insufficient depth — not as free money.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from ..models import FillEstimate, Market, OrderBook, OrderBookLevel

_EDGE_QUANT = Decimal("0.0001")
_QTY_QUANT = Decimal("0.00000001")


def walk_asks(levels: Sequence[OrderBookLevel], quantity: Decimal) -> FillEstimate:
    """Cost to buy exactly ``quantity`` shares, best price first.

    ``fully_filled`` is False when the book lacks depth; the returned estimate
    then reflects only what could be filled.
    """
    if quantity <= 0:
        return FillEstimate(Decimal(0), Decimal(0), Decimal(0), True, 0)
    remaining = quantity
    cost = Decimal(0)
    consumed = 0
    for level in levels:
        if remaining <= 0:
            break
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        consumed += 1
    filled = quantity - remaining
    vwap = (cost / filled) if filled > 0 else Decimal(0)
    return FillEstimate(
        quantity=filled,
        cost=cost,
        vwap=vwap,
        fully_filled=remaining <= 0,
        levels_consumed=consumed,
    )


def _available(levels: Sequence[OrderBookLevel]) -> Decimal:
    return sum((level.size for level in levels), Decimal(0))


@dataclass(frozen=True)
class ArbResult:
    slug: str
    question: str
    top_of_book_sum: Decimal | None
    notional_budget: Decimal  # target USDC to deploy across the complete set
    executable_quantity: Decimal  # complete sets actually buyable within budget/depth
    fully_filled: bool
    yes_cost: Decimal
    no_cost: Decimal
    yes_vwap: Decimal
    no_vwap: Decimal
    cost_per_set: Decimal
    gross_edge_bps: Decimal
    buffer_bps: Decimal
    net_edge_bps: Decimal
    max_size_at_min_edge: Decimal | None
    is_candidate: bool
    note: str

    def to_dict(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "slug": self.slug,
            "question": self.question,
            "top_of_book_sum": s(self.top_of_book_sum),
            "notional_budget": s(self.notional_budget),
            "executable_quantity": s(self.executable_quantity),
            "fully_filled": self.fully_filled,
            "yes_cost": s(self.yes_cost),
            "no_cost": s(self.no_cost),
            "yes_vwap": s(self.yes_vwap),
            "no_vwap": s(self.no_vwap),
            "cost_per_set": s(self.cost_per_set),
            "gross_edge_bps": s(self.gross_edge_bps),
            "buffer_bps": s(self.buffer_bps),
            "net_edge_bps": s(self.net_edge_bps),
            "max_size_at_min_edge": s(self.max_size_at_min_edge),
            "is_candidate": self.is_candidate,
            "note": self.note,
        }


def analyze_complete_set(
    market: Market,
    yes_book: OrderBook,
    no_book: OrderBook,
    *,
    notional: Decimal,
    fee_buffer_bps: Decimal,
    slippage_buffer_bps: Decimal,
    min_edge_bps: Decimal,
) -> ArbResult:
    """Quote an apparent complete-set edge for roughly ``notional`` USDC.

    ``notional`` is the target number of complete sets to acquire (each set
    costs ~1 USDC and redeems for exactly 1 USDC). We solve for the largest
    quantity buyable on both sides within that budget, quote the VWAP edge at
    that size, and separately report the largest size that still clears
    ``min_edge_bps``.
    """
    buffer_bps = fee_buffer_bps + slippage_buffer_bps
    tob_sum: Decimal | None = None
    if yes_book.best_ask and no_book.best_ask:
        tob_sum = yes_book.best_ask.price + no_book.best_ask.price

    depth = min(_available(yes_book.asks), _available(no_book.asks))
    if depth <= 0:
        return _empty(market, tob_sum, notional, buffer_bps, "insufficient_liquidity: one or both sides have no asks")

    # Budget-constrained size: the most sets buyable for <= `notional` USDC.
    qty = _max_qty_within_budget(yes_book.asks, no_book.asks, budget=notional, ceiling=depth)
    if qty <= 0:
        return _empty(
            market, tob_sum, notional, buffer_bps, "insufficient_liquidity: cannot fill a meaningful size within budget"
        )

    yes_fill = walk_asks(yes_book.asks, qty)
    no_fill = walk_asks(no_book.asks, qty)
    cost_per_set = yes_fill.vwap + no_fill.vwap
    gross_edge_bps = ((Decimal(1) - cost_per_set) * Decimal(10_000)).quantize(_EDGE_QUANT)
    net_edge_bps = (gross_edge_bps - buffer_bps).quantize(_EDGE_QUANT)
    fully = yes_fill.fully_filled and no_fill.fully_filled

    max_size = _max_size_at_edge(
        yes_book.asks, no_book.asks, buffer_bps=buffer_bps, min_edge_bps=min_edge_bps, ceiling=depth
    )
    is_candidate = net_edge_bps >= min_edge_bps and qty > 0
    note = (
        "apparent paper edge; observation only, not a real fill"
        if is_candidate
        else "no apparent edge after buffers at this size"
    )
    return ArbResult(
        slug=market.slug,
        question=market.question,
        top_of_book_sum=tob_sum,
        notional_budget=notional,
        executable_quantity=qty,
        fully_filled=fully,
        yes_cost=yes_fill.cost,
        no_cost=no_fill.cost,
        yes_vwap=yes_fill.vwap,
        no_vwap=no_fill.vwap,
        cost_per_set=cost_per_set,
        gross_edge_bps=gross_edge_bps,
        buffer_bps=buffer_bps,
        net_edge_bps=net_edge_bps,
        max_size_at_min_edge=max_size,
        is_candidate=is_candidate,
        note=note,
    )


def _combined_cost(
    yes_asks: Sequence[OrderBookLevel], no_asks: Sequence[OrderBookLevel], qty: Decimal
) -> Decimal | None:
    y = walk_asks(yes_asks, qty)
    n = walk_asks(no_asks, qty)
    if not (y.fully_filled and n.fully_filled):
        return None
    return y.cost + n.cost


def _max_qty_within_budget(
    yes_asks: Sequence[OrderBookLevel],
    no_asks: Sequence[OrderBookLevel],
    *,
    budget: Decimal,
    ceiling: Decimal,
) -> Decimal:
    """Largest qty (<= ceiling depth) whose combined fill cost <= budget."""
    if ceiling <= 0:
        return Decimal(0)
    full = _combined_cost(yes_asks, no_asks, ceiling)
    if full is not None and full <= budget:
        return ceiling.quantize(_QTY_QUANT, rounding=ROUND_DOWN)
    lo, hi = Decimal(0), ceiling
    for _ in range(60):
        mid = (lo + hi) / 2
        cost = _combined_cost(yes_asks, no_asks, mid)
        if cost is not None and cost <= budget:
            lo = mid
        else:
            hi = mid
    # Round the quantity DOWN so the deployed cost never exceeds the budget.
    return lo.quantize(_QTY_QUANT, rounding=ROUND_DOWN)


def _net_edge_bps_at(
    yes_asks: Sequence[OrderBookLevel],
    no_asks: Sequence[OrderBookLevel],
    qty: Decimal,
    buffer_bps: Decimal,
) -> Decimal | None:
    y = walk_asks(yes_asks, qty)
    n = walk_asks(no_asks, qty)
    if not (y.fully_filled and n.fully_filled) or qty <= 0:
        return None
    cost_per_set = y.vwap + n.vwap
    return (Decimal(1) - cost_per_set) * Decimal(10_000) - buffer_bps


def _max_size_at_edge(
    yes_asks: Sequence[OrderBookLevel],
    no_asks: Sequence[OrderBookLevel],
    *,
    buffer_bps: Decimal,
    min_edge_bps: Decimal,
    ceiling: Decimal,
) -> Decimal | None:
    """Largest qty whose net edge is still >= min_edge_bps.

    Edge is monotonically non-increasing in size (deeper walks pay worse
    prices), so a binary search on quantity is valid.
    """
    if ceiling <= 0:
        return None
    edge_at_ceiling = _net_edge_bps_at(yes_asks, no_asks, ceiling, buffer_bps)
    if edge_at_ceiling is not None and edge_at_ceiling >= min_edge_bps:
        # Even the deepest fillable size clears the threshold.
        return ceiling.quantize(_QTY_QUANT)
    smallest = _QTY_QUANT
    edge_small = _net_edge_bps_at(yes_asks, no_asks, smallest, buffer_bps)
    if edge_small is None or edge_small < min_edge_bps:
        return None
    lo, hi = smallest, ceiling
    for _ in range(60):
        mid = (lo + hi) / 2
        edge = _net_edge_bps_at(yes_asks, no_asks, mid, buffer_bps)
        if edge is not None and edge >= min_edge_bps:
            lo = mid
        else:
            hi = mid
    return lo.quantize(_QTY_QUANT)


def _empty(
    market: Market,
    tob_sum: Decimal | None,
    notional_budget: Decimal,
    buffer_bps: Decimal,
    note: str,
) -> ArbResult:
    return ArbResult(
        slug=market.slug,
        question=market.question,
        top_of_book_sum=tob_sum,
        notional_budget=notional_budget,
        executable_quantity=Decimal(0),
        fully_filled=False,
        yes_cost=Decimal(0),
        no_cost=Decimal(0),
        yes_vwap=Decimal(0),
        no_vwap=Decimal(0),
        cost_per_set=Decimal(0),
        gross_edge_bps=Decimal(0),
        buffer_bps=buffer_bps,
        net_edge_bps=Decimal(0),
        max_size_at_min_edge=None,
        is_candidate=False,
        note=note,
    )
