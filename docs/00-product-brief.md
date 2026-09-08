# Product Brief

## Product

**Polymarket Edge Lab**

A research and paper-trading toolkit for investigating whether apparent Polymarket edges survive realistic execution assumptions.

## Problem

Social posts frequently highlight profitable prediction-market accounts or apparent price discrepancies. Those claims are difficult to evaluate because screenshots and aggregate P&L do not reveal:

- survivorship bias;
- losing trades;
- capital deployed;
- liquidity consumed;
- signal-to-execution latency;
- price drift;
- fee/slippage impact;
- whether a pattern remains valid out of sample.

## Core thesis

The product should turn "this trader seems to win" into a falsifiable workflow:

1. Retrieve public market/wallet data.
2. Measure the claimed pattern.
3. Reconstruct what can be reconstructed without inventing missing data.
4. Forward-test the signal in paper mode.
5. Apply conservative execution costs.
6. Report whether the edge persists.

## Initial target user

A technically capable individual researcher who wants to investigate prediction-market strategies using reproducible data rather than social-media anecdotes.

## MVP outcomes

The user can:

- inspect market metadata and order books;
- analyze a public wallet's activity distribution;
- export activity for independent analysis;
- scan binary markets for apparent YES/NO pricing gaps;
- simulate following public wallet buys/sells;
- generate a paper P&L report;
- reverse-engineer wallet patterns across time, market type, side, entry price, and sizing;
- distinguish observed facts from estimates.

## Explicit non-goals

- Real-money trading.
- Automated betting.
- Circumventing geographic restrictions.
- "AI predicts winners" marketing.
- Guaranteed-return claims.
- Copying a wallet blindly without measuring execution degradation.
