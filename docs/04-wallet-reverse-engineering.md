# Wallet Strategy Reverse Engineering

## Goal

Determine what is actually observable about a successful public wallet and whether those behaviors define a testable forward strategy.

The output must separate:

1. **Observed facts** from public data.
2. **Derived metrics** calculated from those facts.
3. **Estimates** that rely on assumptions.
4. **Unknowns** that cannot be reconstructed reliably.

## Required analyses

### Time behavior

- activity by hour in UTC;
- activity by hour in requested UTC offset;
- weekday distribution;
- rolling activity count by day/week;
- concentration metrics for trading windows.

When someone claims "this wallet trades mainly between 06:00 and 09:00", calculate the exact percentage inside and outside that interval.

### Market concentration

Where metadata supports it:

- event/market frequency;
- sports vs non-sports or tag/category breakdown;
- repeated participation in similar market families;
- concentration of notional by market.

### Direction and entry behavior

- BUY/SELL counts;
- outcome distribution;
- entry-price histogram/buckets, e.g. `<0.1`, `0.1–0.2`, ...;
- trade-size/notional distribution;
- relationship between size and entry price.

### Sequence behavior

Try to identify, without overclaiming:

- scaling into positions;
- repeated buys on the same token;
- partial exits;
- full exits;
- rapid reversals;
- trading near market start/resolution, when timestamps are reliably available.

### Performance reconstruction

Use official position/closed-position data where available and reliable.

Do not label a hand-reconstructed cash-flow series as exact realized P&L unless the source data fully supports that statement.

When exact performance cannot be reconstructed, prefer metrics such as:

- trade count;
- traded notional;
- entry/exit price distribution;
- resolved-position outcome if directly available;
- estimated cash-flow with an `estimated` label.

## Pattern scoring

Generate candidate rules from deterministic observations, such as:

```text
IF category=sports
AND local_hour in [6,7,8]
AND entry_price between 0.80 and 0.95
THEN candidate_pattern=P1
```

A candidate pattern is **not** a strategy until validated.

For each candidate pattern report:

- support count;
- percentage of wallet activity covered;
- historical observed outcome metrics if available;
- time stability;
- sample size warning;
- whether it was selected after looking at the same data (in-sample bias).

## Validation design

Whenever timestamps permit:

1. Sort observations chronologically.
2. Use an earlier segment for discovery.
3. Freeze candidate rules.
4. Evaluate them on a later segment.
5. Prefer forward paper testing for final validation.

Never report in-sample fit as evidence of a reproducible edge.

## Reports

`report.md` should answer:

- What does this wallet demonstrably do?
- Which viral/social claims are supported or contradicted by the data?
- Which patterns are strongest?
- What cannot be known from available public data?
- What forward paper test would falsify each candidate strategy?
