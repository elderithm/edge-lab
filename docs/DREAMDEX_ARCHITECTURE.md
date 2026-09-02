# DreamDEX Edge Lab — Architecture

An explainable probability + edge analysis layer for **DreamDEX Event Contracts**
(Somnia), added to `polymarket-edge-lab` as an **isolated venue**. The existing
Polymarket research toolkit is unchanged; DreamDEX lives behind its own adapter.

```
              Edge Lab core (Python, venue-agnostic)
        probability → edge → risk → signal
                        │
        ┌───────────────┴────────────────┐
   Polymarket adapter            DreamDEX adapter (Python)
   (unchanged)                          │  subprocess (JSON)
                                dreamdex-bridge (TypeScript)
                                        │
                          @somnia-chain/markets-sdk + viem
                                        │
                              Somnia Shannon Testnet
```

## Layering (analysis / risk / execution are separate)

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Core types | `edge_lab/core/types.py` | Venue-agnostic `EventContractMarket`, `OutcomeBook`, `ProbabilityEstimate`, `Observation`, `UnderlyingSnapshot`, enums. All `Decimal`. |
| Probability | `edge_lab/core/probability.py` | Independent quantitative model (below). No LLM. |
| Edge | `edge_lab/core/edge.py` | Executable, size-aware edge from an order-book walk. |
| Risk | `edge_lab/core/risk.py` | Single risk engine; every execution passes through it. |
| Signal | `edge_lab/core/signal.py` | Composes the above into one explainable, ranked signal. |
| Strategy | `edge_lab/strategies/event_contracts.py` | Wires a market + book + underlying into the core pipeline. |
| Venue interface | `edge_lab/venues/base.py` | `TradingVenue` (reads + `place_order`). |
| DreamDEX adapter | `edge_lab/venues/dreamdex/` | Transport + normalization only. No analytics. |
| TS bridge | `dreamdex-bridge/` | Thin transport/execution over the official SDK. |
| Paper store | `edge_lab/paper/dreamdex_paper.py` | Simulated fills + settlement + P&L (no wallet). |
| CLI | `edge_lab/dreamdex_cli.py` | `edge-lab dreamdex scan|inspect|paper-trade|settle|report|execute`. |

The probability model **never** calls `place_order`. Execution only happens from
the CLI, after the risk engine approves and the user confirms with `--yes`.

## Event Contract lifecycle

DreamDEX `BinaryMarketStatus` → normalized `MarketStatus`:
`Listed→LISTED, Trading→TRADING, Locked→LOCKED, Settling→SETTLING,
Resolved→RESOLVED, Voided→VOIDED, Finalized→FINALIZED`. Only `TRADING` accepts
orders. **Before every write** the bridge re-reads on-chain status via
`getMarketOnchain(marketId)` and refuses anything but `Trading` — indexer state
can lag, so cached status is never trusted for a write.

## Canonical market identity

Identity is `venue + marketId` (DreamDEX bytes32 `marketId`), e.g.
`dreamdex:0x…`. Pool addresses are **recycled** across successive markets, so
`poolAddress` is carried for reference only and is **never** used as identity.
Discovery, order-book, status, and execution all address markets by `marketId`.

## Probability model

Driftless Gaussian random walk on log price (`probability.py`), version
`gauss-logreturn-v1`:

```
z      = ln(current / opening) / (σ_perSqrtSec · √time_remaining_s)
P(Up)  = Φ(z)        P(Down) = 1 − P(Up)
```

- `opening` = the market's opening/settlement reference (`getMarketResolution`).
- `current` = underlying spot from the DreamDEX price feed (a **model input**).
- `σ_perSqrtSec` = realized volatility from recent 1-minute closes (std of log
  returns / √interval), computed in Python.
- Over minutes the drift term is negligible, so it is omitted.

`confidence` is **separate** from probability and reflects input quality (data
freshness, sample size, time-to-expiry regime). A confident-looking probability
from thin/stale inputs is suppressed by low confidence, not by distorting the
number. Invalid model outputs are never silently clamped.

This is realized volatility + a statistical CDF — stated plainly, with no ML
claims.

## Edge calculation (executable, not midpoint)

```
edge_up   = P(Up)   − executable_up_ask(size)
edge_down = P(Down) − executable_down_ask(size)
```

`executable_*_ask(size)` walks the outcome book to the intended size (VWAP), so
a tiny attractive top-of-book that lacks depth does **not** count as edge. Both
raw (top-of-book) and executable edges are reported; fee + slippage buffers are
subtracted before comparing to `MIN_EDGE_BPS`.

## External data & basis risk

The underlying spot feed is labeled (`source`, `timestamp`, `receivedAt`) and is
treated as a **model input**, not the DreamDEX settlement oracle. There is
inherent **basis risk** between any external feed and DreamDEX's settlement
reference; the tool never presents the external price as the official settlement
value, and settlement is read from DreamDEX's own resolution state.

## Risk engine (hard boundary)

`RiskConfig` (all configurable): `MIN_EDGE_BPS`, `MIN_CONFIDENCE`,
`MIN_TIME_TO_EXPIRY`, `MAX_PRICE_AGE`, `MAX_MARKET_DATA_AGE`, `MAX_SLIPPAGE`,
`MAX_POSITION_PER_MARKET`, `MAX_TOTAL_EXPOSURE`. The engine emits one explicit
state: `BUY_UP, BUY_DOWN, NO_EDGE, LOW_CONFIDENCE, DATA_STALE,
MARKET_NOT_TRADING, TOO_CLOSE_TO_EXPIRY, INSUFFICIENT_LIQUIDITY`, and caps size
(the position cap always overrides strategy output). No leverage, martingale, or
loss-chasing. Opportunities rank by `edge × confidence × liquidity`, never raw
edge alone.

## Execution path & modes

```
market data → probability → edge → risk → proposal → (confirm) → adapter.place_order → bridge → SDK
```

`TRADING_MODE`:
- **paper** (default): reads only; simulated fills; **no wallet**; never signs.
- **testnet**: submits Somnia Shannon Testnet orders; requires a signer; same
  risk checks as mainnet.
- **mainnet**: disabled unless `NETWORK=mainnet` AND `TRADING_MODE=mainnet` AND
  `ENABLE_MAINNET_TRADING=true`; never inferred from a connected wallet.

The gate is enforced in both the Python adapter and the TS bridge (`env.ts`
`assertWriteAllowed`).

## Fixtures

`edge_lab/venues/dreamdex/fixtures.py` provides a fully offline, clearly
**SIMULATED** venue for tests and demo fallback. It is never presented as live
DreamDEX data, and it never submits transactions.
