"""DreamDEX core: probability bounds, executable edge, and risk guards (§50)."""

from __future__ import annotations

from decimal import Decimal

from edge_lab.core.edge import compute_edge, walk_book
from edge_lab.core.probability import estimate_up_probability, volatility_from_closes
from edge_lab.core.risk import RiskConfig, RiskEngine
from edge_lab.core.signal import evaluate_market
from edge_lab.core.types import (
    EventContractMarket,
    MarketStatus,
    Observation,
    OrderBookLevel,
    ProbabilityEstimate,
    SignalState,
)

D = Decimal
NOW = 1_800_000_000


def _market(status=MarketStatus.TRADING, expiry_in=400, opening="100000"):
    return EventContractMarket(
        venue="dreamdex",
        market_id="0xabc",
        asset="BTC",
        symbol="BTC-15m",
        status=status,
        trading_start=NOW - 500,
        expiry=NOW + expiry_in,
        opening_reference=D(opening),
        window_label="15m",
    )


def _levels(rows):
    return [OrderBookLevel(D(p), D(s)) for p, s in rows]


def _prob(p_up="0.70", conf="0.7"):
    return ProbabilityEstimate(D(p_up), (D(1) - D(p_up)), D(conf), "test-v1", {}, "test")


def _engine(**over):
    base = dict(min_edge_bps=D("150"), min_confidence=D("0.35"), min_time_to_expiry_seconds=45)
    base.update(over)
    return RiskEngine(RiskConfig(**base))


# --- probability ---------------------------------------------------------
def test_probability_within_bounds_and_sums_to_one():
    est = estimate_up_probability(
        current_price=D("100420"),
        opening_price=D("100000"),
        volatility_per_sqrt_sec=D("0.0004"),
        time_remaining_seconds=400,
        confidence=D("0.6"),
    )
    assert D(0) <= est.p_up <= D(1)
    assert est.is_valid()
    assert abs((est.p_up + est.p_down) - D(1)) <= D("0.001")


def test_probability_above_opening_favours_up():
    est = estimate_up_probability(
        current_price=D("101000"),
        opening_price=D("100000"),
        volatility_per_sqrt_sec=D("0.0004"),
        time_remaining_seconds=300,
        confidence=D("0.6"),
    )
    assert est.p_up > D("0.5")


def test_volatility_from_closes_none_when_too_few():
    assert volatility_from_closes([(1, D("100"))], 60) is None
    vol = volatility_from_closes([(i, D(100 + (i % 3))) for i in range(10)], 60)
    assert vol is not None and vol > 0


# --- executable edge -----------------------------------------------------
def test_walk_book_vwap_and_insufficient_depth():
    asks = _levels([("0.40", "2"), ("0.50", "2")])
    q = walk_book(asks, D("3"))
    assert q.fully_filled and q.vwap == (D("1.30") / D("3")).quantize(D("0.000001"))
    q2 = walk_book(asks, D("10"))
    assert not q2.fully_filled


def test_executable_edge_uses_vwap_not_midpoint():
    prob = _prob("0.70")
    # Up asks: cheap top then deep worse level; size forces walking deeper.
    up = _levels([("0.60", "5"), ("0.66", "100")])
    down = _levels([("0.42", "100")])
    edge = compute_edge(prob, up, down, size=D("20"), fee_buffer_bps=D("50"), slippage_buffer_bps=D("50"))
    # vwap for 20 = (5*0.60 + 15*0.66)/20 = 0.645 ; edge = (0.70-0.645)*1e4 - 100 = 450bps
    assert edge.up.executable_ask == D("0.645")
    assert edge.up.executable_edge_bps == D("450.00")
    # raw (top) edge is larger than executable edge — proving we don't use top alone
    assert edge.up.raw_edge_bps > edge.up.executable_edge_bps


def test_edge_insufficient_depth_has_no_executable_edge():
    prob = _prob("0.70")
    up = _levels([("0.60", "1")])  # only 1 unit
    edge = compute_edge(
        prob, up, _levels([("0.42", "100")]), size=D("20"), fee_buffer_bps=D("0"), slippage_buffer_bps=D("0")
    )
    assert edge.up.executable_edge_bps is None
    assert not edge.up.fully_filled


# --- risk guards ---------------------------------------------------------
def _signal(market, up, down, *, size="10", now=NOW, obs_age=1, engine=None, captured_age=2):
    obs = Observation("sim-spot", D("100420"), now - obs_age, now - obs_age)
    return evaluate_market(
        market,
        _prob("0.70"),
        _levels(up),
        _levels(down),
        size=D(size),
        now=now,
        book_captured_at=now - captured_age,
        risk_engine=engine or _engine(),
        fee_buffer_bps=D("50"),
        slippage_buffer_bps=D("50"),
        external_obs=obs,
    )


def test_buy_up_when_edge_clears_threshold():
    sig = _signal(_market(), [("0.55", "100")], [("0.42", "100")])
    assert sig.state == SignalState.BUY_UP
    assert sig.risk.is_actionable


def test_locked_market_not_trading():
    sig = _signal(_market(status=MarketStatus.LOCKED), [("0.55", "100")], [("0.42", "100")])
    assert sig.state == SignalState.MARKET_NOT_TRADING
    assert not sig.risk.is_actionable


def test_resolved_and_voided_block_orders():
    for st in (MarketStatus.RESOLVED, MarketStatus.VOIDED):
        sig = _signal(_market(status=st), [("0.55", "100")], [("0.42", "100")])
        assert sig.state == SignalState.MARKET_NOT_TRADING


def test_too_close_to_expiry_rejected():
    sig = _signal(_market(expiry_in=10), [("0.55", "100")], [("0.42", "100")])
    assert sig.state == SignalState.TOO_CLOSE_TO_EXPIRY


def test_stale_external_data_no_trade():
    sig = _signal(_market(), [("0.55", "100")], [("0.42", "100")], obs_age=120)
    assert sig.state == SignalState.DATA_STALE


def test_stale_market_data_no_trade():
    sig = _signal(_market(), [("0.55", "100")], [("0.42", "100")], captured_age=120)
    assert sig.state == SignalState.DATA_STALE


def test_insufficient_liquidity_rejected():
    sig = _signal(_market(), [("0.55", "1")], [("0.42", "1")], size="50")
    assert sig.state == SignalState.INSUFFICIENT_LIQUIDITY


def test_excessive_slippage_rejected():
    # Tiny cheap top then a huge jump -> walking 20 blows past max slippage.
    sig = _signal(
        _market(),
        [("0.30", "1"), ("0.58", "1000")],
        [("0.42", "1000")],
        size="20",
        engine=_engine(max_slippage_bps=D("100")),
    )
    assert sig.state == SignalState.INSUFFICIENT_LIQUIDITY


def test_edge_below_threshold_is_no_edge():
    sig = _signal(_market(), [("0.69", "100")], [("0.42", "100")], engine=_engine(min_edge_bps=D("500")))
    assert sig.state == SignalState.NO_EDGE


def test_low_confidence_suppressed():
    market = _market()
    prob = _prob("0.70", conf="0.10")
    obs = Observation("sim", D("100420"), NOW - 1, NOW - 1)
    sig = evaluate_market(
        market,
        prob,
        _levels([("0.55", "100")]),
        _levels([("0.42", "100")]),
        size=D("10"),
        now=NOW,
        book_captured_at=NOW - 2,
        risk_engine=_engine(),
        fee_buffer_bps=D("50"),
        slippage_buffer_bps=D("50"),
        external_obs=obs,
    )
    assert sig.state == SignalState.LOW_CONFIDENCE


def test_exposure_cap_overrides_size():
    sig = _signal(
        _market(),
        [("0.55", "1000")],
        [("0.42", "1000")],
        size="1000",
        engine=_engine(max_position_per_market=D("5")),
    )
    # notional capped at 5 collateral -> allowed_size < requested
    assert sig.risk.allowed_notional <= D("5")
    assert sig.risk.allowed_size < D("1000")
