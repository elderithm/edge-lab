# DreamDEX Perps Edge Lab — DoraHacks Submission (ready to paste)

> Fields marked ⟨…⟩ need a human: the demo video URL (see PERPS_SUBMISSION_CHECKLIST.md).

## Project name

DreamDEX Perps Edge Lab

## Tagline

Explainable Perpetual Futures Intelligence and Risk-Aware Execution.

## Short description

An independent quantitative layer for DreamDEX Perps on Somnia Hideki testnet:
it reads every live perp market through the official Somnia Markets SDK, explains
funding, basis, liquidity and volatility, estimates what an order would really
cost from the live book, blocks unsafe orders with explicit reasons, and lets
traders paper-trade or submit a manually confirmed testnet order with verifiable
receipts.

## Full description

### Problem

Perp dashboards show a funding rate, a mark price and a book — and leave the
trader to guess what an order will actually cost, how close it sits to
liquidation, and whether a striking funding rate means anything at all. Perps
add hazards that are easy to get silently wrong: base decimals that differ per
market, tick and lot grids, collateral-limited order sizes, stale mark feeds,
voucher restrictions and IOC orders that revert when the book moves. A
"high-funding opportunity" that ignores these is not an opportunity.

### Solution

DreamDEX Perps Edge Lab separates four things that are usually blurred together:

1. **Observed market conditions** — funding (normalized from the on-chain window
   and interval), mark-vs-index basis, spread and depth near mid, realized
   volatility from gap-free candles (or `INSUFFICIENT_DATA`).
2. **Estimated execution cost** — a size-aware walk of the live order book:
   average and worst price, spread cost, impact, fees.
3. **Risk** — margin, effective leverage, protocol or labelled-estimate
   liquidation distance, exposure caps, the protocol's own max order size.
4. **Strategy edge** — reported as `NOT_ESTIMATED`. There is no predictive model,
   so no positive expected value is claimed.

Each market gets one documented category (`REVIEW`, `WATCH`,
`HIGH_EXECUTION_COST`, `INSUFFICIENT_LIQUIDITY`, `HIGH_LIQUIDATION_RISK`,
`STALE_DATA`, `INSUFFICIENT_DATA`) from published thresholds — no black-box score.

Paper trading is the default and needs no wallet. Testnet execution is CLI-only
and requires the Hideki network, testnet mode, a dedicated signer, every risk
check, and an explicit `--yes`; the bridge re-validates chain id, mark freshness,
precision and official sizing right before signing, and the result is reconciled
from the receipt and decoded fills — a submission is never shown as a fill.

### Technical architecture

```text
CLI (edge-lab perps …) / local dashboard (/perps, preview only)
  → service: scan · inspect · preview · decide
  → analytics (observed, cost, risk; edge NOT_ESTIMATED) │ risk engine (RiskApproval, 1x cap) │ execution + reconciliation │ paper ledger
  → venue adapter (typed models, exact per-market decimal scaling, identity = chain + pool)
  → perps-bridge (TypeScript, @somnia-chain/markets-sdk 0.32.1) → Somnia Hideki Testnet (50383)
```

Python 3.11+ (typer, stdlib HTTP dashboard, `Decimal` everywhere, SQLite), Node
TypeScript bridge, no new Python dependencies.

### DreamDEX integration

Official SDK methods used: `listPerpMarkets`, `getPerpMarket`,
`getPerpSystemConfig`, `getPerpState`, `getPerpRiskParams`,
`getPerpFundingPremium`, `getSpotOrderBook` (perp pool book), `getCandles`,
`getMaxPerpOrderSize`, `previewPerpOrderMargin`, `previewPerpLiquidationPrice`,
`tryGetPerpAccountEquity`, `getPerpVoucherEligibility`, `getPerpPosition`,
`createTrader().placePerpOrder`, `createTrader().claimPerpVoucher`; chain definition `hidekiTestnet` and
`SOMNIA_HIDEKI_TESTNET_ADDRESSES`. Handled hazards: per-market base decimals
(6–24 live), 18-decimal prices, tick/lot/min alignment, `markPriceOk`,
`limitedBy` (collateral / voucherBlocked / maxPositionSize), isolation,
`ImmediateOrCancelNoFill`, WebSocket requirement, 10 M gas limit.

### New work during the bounty

Edge Lab previously covered Polymarket research and DreamDEX Event Contracts
(Shannon testnet, [PR #1](https://github.com/elderithm/edge-lab/pull/1)). All Perps
functionality is new: the isolated `perps-bridge/` package, the
`venues/dreamdex_perps` adapter, Perps analytics, risk engine, execution and
reconciliation, Perps paper ledger, `edge-lab perps` CLI, the dashboard Perps
view, and the tests. Event Contracts and Polymarket behaviour is unchanged. See
`docs/PERPS_DEVELOPMENT_HISTORY.md`.

### GitHub repository

https://github.com/elderithm/edge-lab — branch `hackathon/dreamdex-perps-2026`

### Demo instructions

```bash
pip install -e ".[dev]" && (cd perps-bridge && npm ci)
edge-lab perps markets
edge-lab perps scan
edge-lab perps inspect BTC
edge-lab perps preview BTC --side long --size 0.001
edge-lab perps paper-trade BTC --side long --size 0.001 && edge-lab perps report
edge-lab perps dashboard          # http://127.0.0.1:8787/perps
edge-lab perps scan --source fixture   # offline, SIMULATED
```

Testnet execution: `docs/PERPS_TESTNET_RUNBOOK.md`.

### Testing evidence

- Offline suite: 258 tests pass (183 pre-existing Polymarket / Event Contracts +
  75 new Perps), ruff, ruff-format and mypy clean.
- Bridge: TypeScript typecheck and 5 `node:test` unit tests pass.
- Live Hideki (opt-in `pytest -m live`): market discovery, snapshot + assessment,
  and official unsigned preview / `getMaxPerpOrderSize` pass against the live
  testnet.
- Signed testnet order: one IOC order filled and reconciled end-to-end (see
  Transaction evidence).
- Risk bypass tests: forged, expired and paper-mode approvals, wrong network,
  missing `--yes`, and risk-blocked orders never reach the SDK write.

### Known limitations

- No predictive model: Edge Lab reports observations and costs, not expected
  returns. `REVIEW` is not a trade recommendation.
- Liquidation prices without an account are labelled estimates (single-position,
  no funding/fees); the protocol preview is used when an account is supplied.
- Realized volatility uses DreamDEX perp-trade candles, not the oracle index; thin
  markets report `INSUFFICIENT_DATA`.
- Effective leverage is capped at 1x by design.
- Hideki has no public block explorer; evidence is the tx hash, the RPC receipt
  and the before/after MarginBank position.

### Demo video

⟨YouTube URL⟩

### Transaction evidence

One signed Hideki-testnet order was submitted by `edge-lab perps execute` after
every risk check passed, and verified independently afterwards:

| Field | Value |
|---|---|
| Network | Somnia Hideki Testnet, chain id 50383 |
| Command | `edge-lab perps execute BTC --side long --size 0.00013 --yes` (IOC, limit 82022.9) |
| Tx hash | `0x57fe64c4d310adcdcf8e577be284dff088a55f1b10eb78672a92634af082aa47` |
| Block | 30162072, receipt `success`, 8 logs |
| From → to | dedicated testnet signer `0x74dab13fd6561090fbedc477f7d5de01cf96e501` → BTC-PERP pool `0x4181dd08e73bbcdd1ba3e615a18f6abd941b94c0` |
| Order / fill | order id 6364126705429802276655; 1 fill, 0.00013 BTC at 81970.6 USDso (maker order 7415591117631246718766) |
| Reconciled state | `FILLED`; MarginBank position re-read: 0.00013 BTC long, avg entry 81970.6 |

Re-check with `edge-lab perps receipt 0x57fe64c4d310adcdcf8e577be284dff088a55f1b10eb78672a92634af082aa47`.
Hideki has no public block explorer; the evidence is the RPC receipt, the decoded
fill and the MarginBank position read.

Collateral used: the wallet's Perps Arena paper USDso (100 USDso), moved from the
wallet into the Perps MarginBank with the SDK's `depositMargin`. Edge Lab itself
does not move collateral.
