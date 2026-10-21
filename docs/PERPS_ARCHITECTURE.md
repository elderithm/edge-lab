# DreamDEX Perps Edge Lab — Architecture

DreamDEX Perps Edge Lab extends Edge Lab with an isolated venue for **DreamDEX
perpetual futures on Somnia Hideki Testnet (chain id 50383)**. It reads live
markets through the official `@somnia-chain/markets-sdk`, turns them into
explainable observations, estimates what an order would actually cost, runs a
hard risk gate, and then either paper-trades (default, no wallet) or submits a
manually confirmed testnet order and reconciles the result.

It is decision support, not a trading bot: there is no unattended loop, no
predictive model, no expected-value claim, and effective leverage is capped at 1x.

## Component boundaries

```text
edge-lab perps …  (typer CLI)            /perps  (stdlib dashboard view, preview only)
        │                                        │
        └──────────────┬─────────────────────────┘
                       ▼
        edge_lab/perps/service.py        scan · inspect · build_preview · decide
                       │
   ┌───────────────────┼─────────────────────────────┬──────────────────────────┐
   ▼                   ▼                             ▼                          ▼
analytics.py        risk.py                     execution.py            paper/perps_paper.py
observations,       hard pre-trade checks,      submit an approved      SQLite: paper positions
execution cost,     explicit reasons,           RiskApproval; reconcile (simulated) + testnet
margin estimates,   RiskApproval minting        receipt → order state;  order evidence
assessment          (1x leverage hard cap)      evidence JSON
   │                   │                             │
   └───────────────────┴──────────────┬──────────────┘
                                      ▼
        edge_lab/venues/dreamdex_perps/   adapter · bridge · mapper · models · config · fixtures
                                      │  subprocess, JSON in/out (raw integers as strings)
                                      ▼
        perps-bridge/ (Node, TypeScript)  @somnia-chain/markets-sdk 0.32.1, Hideki only
                                      │  WebSocket + HTTP RPC, GraphQL indexer
                                      ▼
                         Somnia Hideki Testnet (chain 50383)
```

Analytics never calls execution; execution never decides. The adapter's
`place_order` accepts only a `RiskApproval`, which only an approved
`PerpsRiskDecision` can mint.

## Isolation from Event Contracts

| | Event Contracts (existing) | Perps (new) |
|---|---|---|
| Network | Somnia Shannon Testnet, 50312 | Somnia Hideki Testnet, 50383 |
| Node package | `dreamdex-bridge/` | `perps-bridge/` |
| SDK | `@somnia-chain/markets-sdk` ^0.29.0 | `@somnia-chain/markets-sdk` 0.32.1 (pinned) |
| Python venue | `edge_lab/venues/dreamdex/` | `edge_lab/venues/dreamdex_perps/` |
| Signer variable | `PRIVATE_KEY` | `PERPS_PRIVATE_KEY` |
| Write gate | `TRADING_MODE=testnet` (+ mainnet triple gate) | `NETWORK=hideki-testnet` **and** `TRADING_MODE=testnet` **and** signer; no mainnet mode |
| CLI | `edge-lab dreamdex …` | `edge-lab perps …` |
| Paper DB | `.edge-lab/dreamdex-paper.db` | `.edge-lab/perps-paper.db` |

No Event Contracts file was changed to enable Perps except a one-line link from
the Event Contracts dashboard page to the Perps view. A perp is **not** forced into
`EventContractMarket`; it has its own models.

## Market model and identity

`PerpMarket` is keyed by `(chain_id, pool address)` — the SDK's primary key for
perp markets. The symbol (`BTC-PERP`) is display only. `resolve_market` accepts a
pool address or a symbol and raises `AmbiguousMarket` if a symbol maps to more
than one pool instead of guessing.

Per-market parameters come from the market row and are never hardcoded:
`baseDecimals` (6–24 observed live), `quoteDecimals`, `tickSize`, `lotSize`,
`minQuantity`, `marginBank`, `quoteToken`, `initialMarginBps`. Per the Perps
docs, prices are 18-decimal quote units per **whole** base; quantities use the
market's own base decimals. All conversion is exact (`Decimal.scaleb`, integer
`BigInt` in the bridge); a quantity finer than the market's decimals is rejected.

## Data flow

1. **Snapshot** (`perps-bridge snapshot`, one process for all markets, ~1.3 s for
   21 markets): `listPerpMarkets` row + `getPerpState` (mark, `markPriceOk`, index,
   funding rate/window/interval, cumulative funding, open interest) +
   `getPerpRiskParams` (IM/MM bps, fees, position cap) + `getSpotOrderBook` (the
   perp pool shares the order-book core) + `getCandles` (5-minute perp-trade
   candles) + `getPerpFundingPremium` (best effort). Per-market failures are
   returned as `{pool, error}`, not swallowed.
2. **Mapping** (`mapper.py`): raw strings → human `Decimal`. Sentinels become
   `None`: a stale mark feed gives `mark_price=None`; a zero index is absent; a
   missing premium or candle read adds an explicit warning.
3. **Analytics** (`analytics.py`) and **risk** (`risk.py`) as below.
4. **Preview** (`preview-order`, unsigned): bridge-side tick/lot/min checks always;
   with a public account address also the official `getMaxPerpOrderSize`,
   `previewPerpOrderMargin` and `previewPerpLiquidationPrice`.
5. **Execution** (`place-order`): see "Testnet execution".

## Analytics

Four layers are reported separately and never blended:

1. **Observed** — funding, basis, liquidity, volatility.
2. **Estimated execution cost** — a size-aware book walk.
3. **Risk** — margin, effective leverage, liquidation distance.
4. **Strategy edge** — always `NOT_ESTIMATED`. There is no validated predictive
   model for perps, so no positive expected value is claimed.

**Funding.** `fundingRate` is a fraction per `fundingWindowSec` (28 800 s on live
pools), settled every `fundingIntervalSec` (3 600 s). Per-interval and per-hour
rates are derived from the *window*, never from a hardcoded 8 h. The annualized
equivalent is shown only when both window and interval are known. Direction is
`LONGS_PAY` / `SHORTS_PAY` / `NEUTRAL`. Funding is flagged stale after two missed
intervals (the SDK's `isFundingStale` default). The next-settlement premium is
labelled "time-weighted" or "point sample" from the SDK's `armed` flag. Holding
cost is a projection at the current rate, not a forecast.

**Basis.** `(mark − index)` absolute and in bps, plus index age. The SDK notes
that the funding premium is an impact-price premium and routinely disagrees with
mark-vs-index; both are shown and neither is called arbitrage.

**Liquidity.** Best bid/ask, mid, spread (abs, bps), and quote-notional depth
within ±50 bps of mid on each side.

**Execution cost.** `walk_book` consumes the opposite side for the requested
quantity and reports average and worst price, filled quantity, spread cost
(best vs mid), impact (average vs best), slippage (average vs mid), taker fee
from on-chain risk params, and total cost in bps and quote units. Labelled
"ESTIMATE (book walk, not a fill)".

**Volatility.** Sample standard deviation of log returns between consecutive
5-minute perp-trade candles. Pairs separated by a missing bucket are skipped,
never interpolated. Fewer than 12 valid returns → `INSUFFICIENT_DATA`; no
substitute volatility is ever used. Note: these are DreamDEX book trades, not the
oracle index.

**Margin and liquidation.** Notional, initial and maintenance margin from the
pool's risk params, effective leverage = notional / equity. The estimated
liquidation price assumes the equity backs only this position and ignores
funding, fees and the protocol's adverse-gap reserve:
long `P = (q·entry − E) / (q·(1 − mm))`, short `P = (E + q·entry) / (q·(1 + mm))`.
It is labelled `ESTIMATE — not the protocol's exact liquidation price`. When an
account is supplied, the risk engine prefers the protocol's
`previewPerpLiquidationPrice` and labels the check `PROTOCOL`.

## Market Opportunity Assessment

Each market gets exactly one category; the **first** matching rule wins. All
thresholds are fields of `AssessmentThresholds`:

| Order | Category | Rule (default) |
|---|---|---|
| 1 | `STALE_DATA` | `markPriceOk=false`, or snapshot older than 30 s, or index older than 120 s |
| 2 | `INSUFFICIENT_DATA` | mark or index missing, or an empty book side |
| 3 | `INSUFFICIENT_LIQUIDITY` | a 100 USDso probe cannot be fully filled on both sides, or depth within ±50 bps < 100 USDso on either side |
| 4 | `HIGH_EXECUTION_COST` | round-trip probe cost (long entry + short entry, incl. fees) > 30 bps |
| 5 | `HIGH_LIQUIDATION_RISK` | estimated liquidation distance at the analysis leverage (1x) < 3 σ of 24 h realized volatility |
| 6 | `REVIEW` | \|basis\| ≥ 10 bps, or \|annualized funding\| ≥ 20 % |
| 7 | `WATCH` | none of the above |

`REVIEW` means "an observation worth a human look", not "trade this".
Volatility `INSUFFICIENT_DATA` and stale funding are appended as reasons.

**Ranking** (published, no black-box score): sort by category order
`REVIEW, WATCH, HIGH_LIQUIDATION_RISK, HIGH_EXECUTION_COST, INSUFFICIENT_LIQUIDITY,
INSUFFICIENT_DATA, STALE_DATA`, then by lower round-trip cost.

## Risk engine

`PerpsRiskEngine.evaluate` returns a `PerpsRiskDecision` with every check, its
pass/fail, and a human-readable detail. Defaults (`PerpsRiskConfig`):

| Check | Default |
|---|---|
| `execution_mode` | paper always allowed; testnet needs `TRADING_MODE=testnet`, `NETWORK=hideki-testnet`, `PERPS_PRIVATE_KEY` |
| `chain_id`, `live_data` (testnet) | market on 50383; fixtures can never be executed |
| `order_type` | `ioc`, `limit`, `post_only` |
| `mark_price_ok`, `data_fresh`, `index_fresh` | live mark; snapshot ≤ 30 s; index ≤ 120 s |
| `quantity_precision` | lot multiple, ≥ min quantity, ≤ base decimals |
| `price_precision` | limit price on tick |
| `liquidity` | book fully fills the quantity |
| `slippage` | average fill vs mid ≤ 25 bps |
| `limit_price_bound` | IOC limit ≤ 25 bps through mid (limit = worst walked level ± 5 bps, rounded away from mid to tick) |
| `position_notional` | ≤ 100 USDso per market (incl. existing) |
| `total_exposure` | ≤ 250 USDso across markets |
| `protocol_position_cap` | ≤ the pool's per-account `maxPositionSize` |
| `effective_leverage` | total notional / equity ≤ **1x (hard cap, cannot be configured higher)**; unknown equity fails |
| `available_margin` | free margin after initial margin ≥ 25 % of equity |
| `liquidation_distance` | ≥ 20 % from mark (protocol preview if available, else labelled estimate) |
| `official_sizing`, `voucher_allowed`, `official_margin`, `isolation_ok` (testnet) | `getMaxPerpOrderSize` priceable + placeable + `maxQuantity ≥ q` + not `voucherBlocked`; `previewPerpOrderMargin.sufficient`; not `isolationBlocked` |

A blocked decision raises `RiskBlocked` from `approval()`. `RiskApproval` carries a
module-private token and expires after 60 s; the adapter rejects anything else
before touching the bridge (tests prove forged, expired and paper-mode approvals
never reach it).

Why 1x: the repository's DreamDEX rules forbid implementing leverage. Perps are
used here as a research and execution-quality venue; leverage scenarios appear
only analytically (protocol max leverage is displayed for information).

## Testnet execution

`edge-lab perps execute` (CLI only):

1. Refuse immediately unless the write gate passes (no market read happens first).
2. Resolve the market and take a fresh snapshot (book + state).
3. Derive the signer's **public** address inside the bridge (`signer`); the key
   never enters Python.
4. Read live equity and positions for that address.
5. Draft decision → official unsigned preview for the exact raw price/quantity →
   final decision with the official results.
6. Print every check; stop if blocked; stop without `--yes`.
7. Bridge `place-order` re-validates: `riskApproved`, RPC `eth_chainId == 50383`,
   `markPriceOk`, tick/lot/min, bridge notional cap (`PERPS_MAX_ORDER_NOTIONAL`),
   `getMaxPerpOrderSize` (priceable, placeable, ≥ quantity, not voucher-blocked) —
   then `trader.placePerpOrder` with a 10 M gas limit (per the docs).
8. Reconcile from the receipt and decoded fills: `REVERTED`, `FILLED`,
   `PARTIALLY_FILLED`, `RESTING`, or `NOT_FILLED`. A successful transaction is
   never reported as a fill by itself. The position is re-read from the MarginBank.
9. Write an evidence JSON (`.edge-lab/perps-evidence/`) and a ledger row.
   `edge-lab perps receipt <hash>` re-reads the receipt independently.

`edge-lab perps claim-voucher` uses the same write gate and `--yes` to claim the
signer's one-time testnet paper-USDso credit (`claimPerpVoucher` against the
MarginBank's credit granter). The bridge requires `confirmed=true`, checks chain
id 50383 and re-reads eligibility right before signing; afterwards equity is
re-read and an evidence JSON is written.

Revert names from the docs are mapped to stable codes: `IOC_NO_FILL`,
`INSUFFICIENT_COLLATERAL`, `ISOLATED_MARKET_BLOCKED`,
`MAX_POSITION_SIZE_EXCEEDED`, `WS_REQUIRED` ("genesis check failed").

## Paper trading

Paper fills are simulated by walking the observed book (live or fixture; the
`price_source` column records which). Positions are marked at the protocol mark
price. Funding is accrued exactly from the cumulative funding index (SDK
semantics: `(end − start) / 1e18 / 10^quoteDecimals` per whole base; positive =
longs pay). Equity starts at a simulated 1 000 USDso. Every summary is labelled
"PAPER (simulated fills; not verified strategy performance)".

## Fixtures

`FixturePerpsVenue` returns four synthetic markets (BTC, ETH, SOL, DOGE) with
obviously fake pool addresses (`0x…f00N`), `source=SIMULATED_FIXTURE`, and a
warning on every snapshot. They reproduce live parameter shapes (decimals, ticks,
lots, margin tiers) so scaling code is exercised offline. A fixture snapshot can
never pass the testnet `live_data` check.

## Design decisions

- **Separate Node package** instead of upgrading the shared SDK: the Event
  Contracts code was verified against 0.29.0; Perps needs 0.32.1 and a different
  chain. Two packages make each upgrade independent.
- **Raw integers across the process boundary**: no float ever touches a price or
  quantity; scaling is per-market in one Python module.
- **One snapshot call per scan** keeps the dashboard responsive (≈1.3 s vs ≈60 s
  for per-market subprocesses).
- **Categories, not scores**: an arbitrary numeric score would imply a precision
  the analysis does not have.
- **Approval objects** make the risk gate structural rather than a convention.
