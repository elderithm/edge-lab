"""Executable edge for binary event contracts.

Edge is computed against *executable* prices — the volume-weighted cost of
walking the book for the intended size — never the midpoint. Both the raw
(top-of-book) edge and the size-aware executable edge are exposed.

    edge_up   = model_p_up   - executable_up_ask(size)
    edge_down = model_p_down - executable_down_ask(size)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .types import OrderBookLevel, ProbabilityEstimate, Side

_BPS = Decimal(10_000)
_EDGE_Q = Decimal("0.01")
_PRICE_Q = Decimal("0.000001")


@dataclass(frozen=True)
class FillQuote:
    filled_size: Decimal
    cost: Decimal
    vwap: Decimal
    fully_filled: bool
    top_price: Decimal | None
    available_depth: Decimal
    slippage_bps: Decimal  # vwap vs top ask, in bps (0 if no top)


def walk_book(asks: Sequence[OrderBookLevel], size: Decimal) -> FillQuote:
    """Walk ascending asks to buy ``size`` outcome tokens (executable price)."""
    available = sum((lvl.size for lvl in asks), Decimal(0))
    top = asks[0].price if asks else None
    if size <= 0 or not asks:
        return FillQuote(Decimal(0), Decimal(0), Decimal(0), size <= 0, top, available, Decimal(0))
    remaining = size
    cost = Decimal(0)
    for lvl in asks:
        if remaining <= 0:
            break
        take = min(remaining, lvl.size)
        cost += take * lvl.price
        remaining -= take
    filled = size - remaining
    vwap = (cost / filled) if filled > 0 else Decimal(0)
    slippage = ((vwap - top) / top * _BPS).quantize(_EDGE_Q) if (top and top > 0 and filled > 0) else Decimal(0)
    return FillQuote(
        filled_size=filled,
        cost=cost,
        vwap=vwap.quantize(_PRICE_Q) if filled > 0 else Decimal(0),
        fully_filled=remaining <= 0,
        top_price=top,
        available_depth=available,
        slippage_bps=slippage,
    )


@dataclass(frozen=True)
class SideEdge:
    side: Side
    model_prob: Decimal
    top_ask: Decimal | None
    executable_ask: Decimal | None  # vwap for the requested size
    raw_edge_bps: Decimal | None  # model_prob - top_ask
    executable_edge_bps: Decimal | None  # model_prob - vwap - buffers
    fully_filled: bool
    available_depth: Decimal
    slippage_bps: Decimal

    def to_dict(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "side": self.side.value,
            "model_prob": str(self.model_prob),
            "top_ask": s(self.top_ask),
            "executable_ask": s(self.executable_ask),
            "raw_edge_bps": s(self.raw_edge_bps),
            "executable_edge_bps": s(self.executable_edge_bps),
            "fully_filled": self.fully_filled,
            "available_depth": str(self.available_depth),
            "slippage_bps": str(self.slippage_bps),
        }


@dataclass(frozen=True)
class EdgeBreakdown:
    up: SideEdge
    down: SideEdge
    buffer_bps: Decimal
    size: Decimal

    def best(self) -> SideEdge:
        """Side with the higher executable edge (ties -> Up)."""
        up_e = self.up.executable_edge_bps if self.up.executable_edge_bps is not None else Decimal("-1e9")
        down_e = self.down.executable_edge_bps if self.down.executable_edge_bps is not None else Decimal("-1e9")
        return self.up if up_e >= down_e else self.down

    def to_dict(self) -> dict[str, object]:
        return {
            "size": str(self.size),
            "buffer_bps": str(self.buffer_bps),
            "up": self.up.to_dict(),
            "down": self.down.to_dict(),
        }


def _side_edge(
    side: Side, prob: Decimal, asks: Sequence[OrderBookLevel], size: Decimal, buffer_bps: Decimal
) -> SideEdge:
    quote = walk_book(asks, size)
    top = quote.top_price
    raw = ((prob - top) * _BPS).quantize(_EDGE_Q) if top is not None else None
    if quote.fully_filled and quote.filled_size > 0:
        executable = ((prob - quote.vwap) * _BPS - buffer_bps).quantize(_EDGE_Q)
        exec_ask: Decimal | None = quote.vwap
    else:
        executable = None  # cannot fill requested size -> no executable edge
        exec_ask = None
    return SideEdge(
        side=side,
        model_prob=prob,
        top_ask=top,
        executable_ask=exec_ask,
        raw_edge_bps=raw,
        executable_edge_bps=executable,
        fully_filled=quote.fully_filled,
        available_depth=quote.available_depth,
        slippage_bps=quote.slippage_bps,
    )


def compute_edge(
    prob: ProbabilityEstimate,
    up_asks: Sequence[OrderBookLevel],
    down_asks: Sequence[OrderBookLevel],
    *,
    size: Decimal,
    fee_buffer_bps: Decimal,
    slippage_buffer_bps: Decimal,
) -> EdgeBreakdown:
    buffer_bps = fee_buffer_bps + slippage_buffer_bps
    return EdgeBreakdown(
        up=_side_edge(Side.UP, prob.p_up, up_asks, size, buffer_bps),
        down=_side_edge(Side.DOWN, prob.p_down, down_asks, size, buffer_bps),
        buffer_bps=buffer_bps,
        size=size,
    )
