"""Independent short-horizon probability model for Up/Down event contracts.

Method: a driftless Gaussian random-walk on log price. Over a short horizon the
drift term is negligible, so

    z = ln(current / opening) / (sigma_per_sqrt_sec * sqrt(time_remaining))
    P(Up) = P(close >= opening) = Phi(z)

This is deliberately simple and interpretable: realized volatility plus a normal
CDF, exactly as the model explanation states. It is NOT an LLM guess and not a
machine-learning ensemble. ``confidence`` is computed separately from data
quality — a confident-looking probability from stale/thin inputs is suppressed
by low confidence, not by distorting the probability.
"""

from __future__ import annotations

import math
from decimal import Decimal

from .types import ProbabilityEstimate

MODEL_VERSION = "gauss-logreturn-v1"

_ONE = Decimal(1)
_HALF = Decimal("0.5")
_PROB_Q = Decimal("0.000001")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def realized_vol_per_sqrt_sec(log_returns: list[Decimal], interval_seconds: float) -> Decimal | None:
    """Per-second volatility (std of log-returns / sqrt(interval)).

    Returns None when there are too few points to estimate a sample stdev.
    """
    if interval_seconds <= 0 or len(log_returns) < 2:
        return None
    n = Decimal(len(log_returns))
    mean = sum(log_returns, Decimal(0)) / n
    var = sum(((r - mean) ** 2 for r in log_returns), Decimal(0)) / (n - _ONE)
    sigma_interval = var.sqrt()
    return sigma_interval / Decimal(math.sqrt(interval_seconds))


def volatility_from_closes(closes: list[tuple[int, Decimal]], interval_seconds: float) -> Decimal | None:
    """Per-second log-return volatility from a series of (ts, close) points."""
    prices = [c for _, c in closes if c > 0]
    if len(prices) < 3:
        return None
    log_returns = [Decimal(math.log(float(prices[i] / prices[i - 1]))) for i in range(1, len(prices))]
    return realized_vol_per_sqrt_sec(log_returns, interval_seconds)


def volatility_per_sqrt_sec_from_series(points: list[tuple[int, Decimal]]) -> Decimal | None:
    """Per-second volatility from irregularly spaced (ts, price) ticks.

    Uses the realized-variance estimator sqrt(sum(r_i^2) / sum(dt_i)), which is
    robust to uneven sampling (e.g. per-block price-feed ticks) — unlike a fixed
    interval assumption.
    """
    pts = sorted(((t, p) for t, p in points if p > 0), key=lambda x: x[0])
    if len(pts) < 3:
        return None
    ssr = Decimal(0)
    total_dt = Decimal(0)
    for (t0, p0), (t1, p1) in zip(pts, pts[1:], strict=False):
        dt = Decimal(t1 - t0)
        if dt <= 0:
            continue
        r = Decimal(math.log(float(p1 / p0)))
        ssr += r * r
        total_dt += dt
    if total_dt <= 0:
        return None
    return (ssr / total_dt).sqrt()


def estimate_up_probability(
    *,
    current_price: Decimal,
    opening_price: Decimal,
    volatility_per_sqrt_sec: Decimal,
    time_remaining_seconds: int,
    confidence: Decimal,
    sample_size: int | None = None,
) -> ProbabilityEstimate:
    """Estimate P(close >= opening) for a reference-mode event contract.

    ``volatility_per_sqrt_sec`` is the standard deviation of log-price returns
    scaled to one second (see :func:`realized_vol_per_sqrt_sec`).
    """
    if current_price <= 0 or opening_price <= 0:
        raise ValueError("current_price and opening_price must be positive")
    if volatility_per_sqrt_sec < 0:
        raise ValueError("volatility_per_sqrt_sec must be non-negative")

    log_move = Decimal(math.log(float(current_price) / float(opening_price)))
    sigma_t = volatility_per_sqrt_sec * Decimal(math.sqrt(max(time_remaining_seconds, 0)))

    if sigma_t <= 0:
        # No remaining diffusion: outcome is (almost) determined by the sign of
        # the current deviation. We do NOT clamp confidence up — it is the
        # caller's confidence, which will be low near/after expiry.
        if log_move > 0:
            p_up = _ONE
        elif log_move < 0:
            p_up = Decimal(0)
        else:
            p_up = _HALF
        reason_vol = "no remaining diffusion (at/after expiry or zero volatility)"
        z_val = None
    else:
        z = log_move / sigma_t
        p_up = Decimal(_norm_cdf(float(z))).quantize(_PROB_Q)
        z_val = z
        reason_vol = f"z={z.quantize(Decimal('0.0001'))} of the volatility-scaled move"

    p_up = min(_ONE, max(Decimal(0), p_up)).quantize(_PROB_Q)
    p_down = (_ONE - p_up).quantize(_PROB_Q)

    pct_move = ((current_price / opening_price - _ONE) * 100).quantize(Decimal("0.001"))
    direction = "above" if log_move > 0 else "below" if log_move < 0 else "at"
    mins = time_remaining_seconds // 60
    secs = time_remaining_seconds % 60
    explanation = (
        f"Price is {pct_move}% {direction} the opening reference with "
        f"{mins}m {secs:02d}s remaining. Recent realized volatility ({reason_vol}) "
        f"implies P(Up)={(p_up * 100).quantize(Decimal('0.1'))}%. "
        "Model: driftless Gaussian log-return random walk (no ML)."
    )

    inputs = {
        "current_price": str(current_price),
        "opening_price": str(opening_price),
        "volatility_per_sqrt_sec": str(volatility_per_sqrt_sec),
        "time_remaining_seconds": str(time_remaining_seconds),
        "sample_size": str(sample_size) if sample_size is not None else "unknown",
        "z": str(z_val) if z_val is not None else "n/a",
    }
    return ProbabilityEstimate(
        p_up=p_up,
        p_down=p_down,
        confidence=min(_ONE, max(Decimal(0), confidence)),
        model_version=MODEL_VERSION,
        inputs=inputs,
        explanation=explanation,
    )
