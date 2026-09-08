# polymarket-edge-lab — DreamDEX Event Contracts Hackathon Specification

## 1. Objective

Extend the existing `polymarket-edge-lab` project for the Somnia × DreamDEX Event Contracts Hackathon.

The goal is NOT to replace the existing Polymarket research functionality.

The goal is to add DreamDEX as a first-class prediction/event-contract venue and demonstrate:

> An independent probability model estimates the probability of a DreamDEX Event Contract outcome, compares that estimate against the live on-chain market-implied probability, detects statistically meaningful pricing gaps, and allows the user to simulate or safely execute a trade.

The primary hackathon concept is:

## DreamDEX Edge Lab

An explainable probability and edge analysis layer for DreamDEX Event Contracts.

---

# 2. Core Product Thesis

DreamDEX exposes binary Up/Down contracts.

For a market with an Up ask price of:

```text
0.62
```

the approximate market-implied probability is:

```text
62%
```

Edge Lab independently estimates:

```text
P(Up) = 0.71
```

and computes:

```text
raw_edge = model_probability - executable_market_price
         = 0.71 - 0.62
         = +0.09
```

The product then evaluates whether that apparent edge remains meaningful after accounting for:

- spread;
- executable price;
- market depth;
- model uncertainty;
- time remaining;
- external-price staleness;
- oracle/reference basis risk.

Do NOT simply compare against the midpoint and call the difference profit.

---

# 3. Existing Project Boundary

Preserve the existing `polymarket-edge-lab` concepts wherever appropriate.

Conceptual architecture:

```text
                    Edge Lab Core
                         │
          ┌──────────────┴───────────────┐
          │                              │
     Polymarket                     DreamDEX
       Adapter                        Adapter
          │                              │
   Polymarket APIs              markets-sdk / Somnia
          │                              │
    Polymarket                   Event Contracts
      Markets
```

The core probability/edge engine should not directly depend on either exchange.

Venue-specific functionality should remain behind adapters.

Do NOT rewrite the whole repository around DreamDEX.

---

# 4. Suggested Architecture

Adapt to the existing project rather than forcing this exact layout.

Conceptually:

```text
src/
  core/
    probability/
    edge/
    risk/
    market/
    types/

  venues/
    polymarket/
      ...

    dreamdex/
      client.ts
      marketDiscovery.ts
      orderbook.ts
      execution.ts
      settlement.ts
      types.ts
      mapper.ts

  strategies/
    event-contracts/
      probabilityModel.ts
      edgeDetector.ts
      signal.ts

  services/
    marketScanner.ts
    signalEngine.ts

  ui/
    ...
```

Keep:

```text
core
```

venue-agnostic.

Keep:

```text
venues/dreamdex
```

DreamDEX-specific.

---

# 5. Official DreamDEX Integration

Use the official:

```text
@somnia-chain/markets-sdk
```

for Event Contracts.

Use version:

```text
>= 0.25.0
```

unless current official DreamDEX documentation explicitly requires something newer.

Do NOT build Event Contracts primarily against the DreamDEX HTTP API.

The HTTP API is not the Event Contracts developer surface.

Use the SDK for:

- live Event Contract discovery;
- order-book state;
- trades/fills;
- candles where useful;
- order placement;
- order cancellation;
- complete-set operations if required;
- redemption if implemented.

Use `viem` where required by the official SDK.

---

# 6. Network Policy

The hackathon implementation must be TESTNET FIRST.

Default network:

```text
Somnia Shannon Testnet
Chain ID: 50312
```

Mainnet:

```text
Somnia
Chain ID: 5031
```

must be explicitly opt-in.

Default configuration:

```text
TRADING_MODE=paper
NETWORK=testnet
```

Recommended modes:

```text
paper
testnet
mainnet
```

`paper` must be the default.

Mainnet execution must never occur merely because a wallet is connected.

---

# 7. Market Scope

Do NOT attempt to support arbitrary prediction markets.

For the hackathon MVP, support the DreamDEX Event Contract markets currently relevant to:

```text
BTC
ETH
```

and the currently supported rolling windows such as:

```text
15-minute
1-hour
```

The architecture may remain extensible, but implementation should stay focused.

One complete BTC flow and one complete ETH flow are sufficient.

---

# 8. Canonical Market Identity

IMPORTANT:

Do NOT use:

```text
poolAddress
```

as the canonical market identifier.

DreamDEX pools may be reused across consecutive markets.

Use:

```text
marketId
```

or an appropriate canonical market symbol.

Internal state should conceptually be keyed by:

```text
venue
+
marketId
```

Example:

```text
dreamdex:0xabc...
```

Do not assume that:

```text
poolAddress == market
```

---

# 9. Market Lifecycle

Correctly represent DreamDEX Event Contract lifecycle states.

Conceptually:

```text
LISTED
TRADING
LOCKED
RESOLVED
VOIDED
```

Only allow order placement when the market is actually:

```text
TRADING
```

Before EVERY write:

read the current on-chain market status.

Do NOT rely solely on indexed/cache state before sending an order.

Indexer state may lag.

---

# 10. Probability Model

The hackathon implementation should provide an independently derived probability estimate.

Do NOT use an LLM alone to invent a probability.

For BTC/ETH short-horizon markets, prefer an interpretable quantitative baseline.

Minimum viable inputs may include:

- current underlying spot price;
- market opening/reference price;
- time remaining;
- recent realized volatility;
- short-term returns;
- optional short-horizon momentum;
- optional cross-venue spot observations.

Example conceptual model:

```text
P(close >= opening_price)
```

derived from:

```text
current_price
opening_price
realized_volatility
time_to_expiry
```

A simple statistically defensible model is better than an opaque complex model.

---

# 11. Model Architecture

Expose a common interface such as:

```typescript
interface ProbabilityEstimate {
  pUp: number;
  pDown: number;

  confidence: number;

  modelVersion: string;

  inputs: {
    currentPrice: number;
    openingPrice: number;
    timeRemainingMs: number;
    realizedVolatility?: number;
  };

  explanation: string;
}
```

Ensure:

```text
0 <= pUp <= 1
0 <= pDown <= 1
```

and approximately:

```text
pUp + pDown = 1
```

Do not silently clamp fundamentally invalid model outputs.

---

# 12. Model Explainability

Every signal should answer:

> Why does the model disagree with the market?

Example:

```text
Model probability
68.4%

DreamDEX executable Up price
60.5%

Raw edge
+7.9%

Reason
BTC is currently 0.42% above the opening reference
with 6m 14s remaining. Recent realized volatility
implies a 68.4% probability of finishing above the
opening reference.
```

Avoid:

```text
AI says BUY
```

with no explanation.

---

# 13. External Price Data

Do NOT assume a single external exchange price is identical to the DreamDEX settlement reference.

External spot data is a MODEL INPUT.

It is not necessarily the settlement oracle.

Explicitly model:

```text
basis risk
```

between:

```text
external price feed
```

and:

```text
DreamDEX settlement reference
```

When displaying an external reference price, label its source.

Never represent it as the official DreamDEX settlement value unless it actually is.

---

# 14. Data Freshness

Every external observation must contain:

```text
source
timestamp
receivedAt
```

Signals must become invalid if required data is stale.

Example concept:

```text
if externalPriceAge > MAX_PRICE_AGE:
    signal = NO_TRADE
```

Do not trade from stale cached market data.

---

# 15. Edge Calculation

Do NOT calculate edge solely from the order-book midpoint.

Use executable prices.

For buying Up:

```text
edge_up =
model_p_up
-
best_executable_up_ask
```

For buying Down:

```text
edge_down =
model_p_down
-
best_executable_down_ask
```

Account for:

- order-book spread;
- price impact;
- intended quantity;
- available depth.

Expose both:

```text
raw edge
```

and:

```text
executable edge
```

where useful.

---

# 16. Edge Threshold

Do not emit a trading signal for every positive difference.

Use a configurable threshold.

Example:

```text
MIN_EDGE_BPS
```

The threshold should account for:

- model uncertainty;
- price-feed noise;
- latency;
- basis risk;
- order-book movement.

Default values should be conservative.

Do not tune thresholds specifically to make historical or demo results look profitable.

---

# 17. Confidence

Probability and confidence are NOT the same thing.

Example:

```text
P(Up) = 72%
confidence = LOW
```

may be valid if inputs are poor.

Confidence may incorporate:

- data freshness;
- model disagreement;
- volatility regime;
- order-book depth;
- time remaining;
- availability of external observations.

Low-confidence signals should be suppressed or clearly labeled.

---

# 18. Signal Output

Use explicit states.

Recommended:

```text
BUY_UP
BUY_DOWN
NO_EDGE
LOW_CONFIDENCE
DATA_STALE
MARKET_NOT_TRADING
TOO_CLOSE_TO_EXPIRY
INSUFFICIENT_LIQUIDITY
```

Avoid ambiguous outputs such as:

```text
GOOD
BAD
HOT
WINNER
```

---

# 19. Expiry Guard

Do not place trades too close to market lock/expiry.

Implement:

```text
MIN_TIME_TO_EXPIRY
```

Before execution:

```text
if remainingTime < MIN_TIME_TO_EXPIRY:
    reject execution
```

The exact default may be configurable.

The purpose is to avoid:

- stale signals;
- execution races;
- locking during transaction propagation.

---

# 20. Liquidity Guard

Before execution, verify adequate depth.

Do NOT assume:

```text
best ask
```

is available for the entire requested size.

Estimate expected fill price.

Reject or reduce a trade when:

```text
expected_slippage > MAX_SLIPPAGE
```

or:

```text
available_depth < required_depth
```

---

# 21. Paper Trading

Paper trading is a first-class feature.

Default:

```text
TRADING_MODE=paper
```

Paper trades should use real DreamDEX market data but simulated execution.

Record:

- signal timestamp;
- marketId;
- model probability;
- executable market price;
- edge;
- simulated size;
- simulated fill;
- eventual outcome;
- simulated P&L.

Paper trading must NOT require a private key.

---

# 22. Testnet Trading

Testnet trading may submit actual DreamDEX testnet transactions.

This is the preferred hackathon execution demonstration.

Require explicit:

```text
TRADING_MODE=testnet
```

and a testnet signer.

Testnet execution must use the same risk checks as mainnet.

Do not bypass safety checks simply because testnet funds have no real value.

---

# 23. Mainnet Trading

Mainnet execution is NOT required for the hackathon MVP.

Do not prioritize it.

If implemented, require ALL of:

```text
NETWORK=mainnet
TRADING_MODE=mainnet
ENABLE_MAINNET_TRADING=true
```

and an explicit user action.

Never automatically infer mainnet permission.

---

# 24. Human Confirmation

The primary user-facing implementation should require explicit user confirmation before executing a real transaction.

Target flow:

```text
Signal detected
      ↓
Show probability + edge + risk
      ↓
User selects trade
      ↓
Review transaction
      ↓
User confirms
      ↓
Signed transaction
```

Do not design the primary hackathon UI around unattended real-money execution.

---

# 25. Optional Agent Mode

An autonomous scanner/agent may:

- monitor markets;
- calculate probabilities;
- detect edges;
- rank opportunities;
- generate explanations;
- generate trade proposals.

By default it must NOT:

- move mainnet funds;
- sign transactions;
- bypass confirmation.

Conceptually:

```text
Agent:
"I found a 6.3% estimated executable edge."

Human:
"Execute."

Agent:
submit testnet / permitted transaction
```

This provides an agentic experience without sacrificing control.

---

# 26. Execution Adapter

Keep analysis separate from execution.

Example:

```typescript
interface TradingVenue {
  listMarkets(): Promise<Market[]>;

  getMarket(id: string): Promise<Market>;

  getOrderBook(id: string): Promise<OrderBook>;

  placeOrder(request: OrderRequest): Promise<OrderResult>;

  cancelOrder(orderId: string): Promise<void>;
}
```

The probability model must NOT directly call:

```text
placeOrder()
```

Instead:

```text
Market Data
    ↓
Probability Model
    ↓
Edge Detector
    ↓
Risk Engine
    ↓
Trade Proposal
    ↓
Execution Adapter
```

---

# 27. Hard Risk Boundary

Implement a dedicated risk engine.

Minimum configurable constraints:

```text
MAX_POSITION_PER_MARKET
MAX_TOTAL_EXPOSURE
MAX_SLIPPAGE
MIN_EDGE_BPS
MIN_TIME_TO_EXPIRY
MAX_PRICE_AGE
MAX_MARKET_DATA_AGE
```

Do not scatter risk checks across UI components.

All executions must pass through the risk engine.

---

# 28. Position Sizing

Do NOT implement:

- unlimited Kelly sizing;
- leverage;
- martingale;
- doubling after losses;
- loss-chasing logic.

If position sizing is required, prefer:

```text
fixed small size
```

or:

```text
capped fractional sizing
```

Maximum position size must always override strategy output.

---

# 29. No Profit Guarantees

Never display:

```text
Guaranteed profit
Risk-free
Certain win
Free money
Guaranteed edge
```

An estimated edge is:

```text
model-estimated expected advantage
```

not guaranteed profit.

Always distinguish:

```text
model estimate
```

from:

```text
actual future outcome
```

---

# 30. Settlement

If implemented, support the DreamDEX lifecycle correctly.

After resolution:

```text
RESOLVED
```

a winning outcome may be redeemable.

For:

```text
VOIDED
```

do not treat either prediction as a normal win/loss.

Void behavior must be represented separately.

Do not manually infer the winner from an external exchange tick.

Use DreamDEX's actual market resolution state.

---

# 31. Settlement Audit

Where practical, surface the market's official settlement/oracle reference.

Recommended UI:

```text
Settlement

Status: Resolved
Outcome: Up

[Audit settlement]
```

This strengthens the product's transparency.

Do not duplicate or fabricate oracle information.

---

# 32. Dashboard

Implement a focused dashboard.

Recommended market row/card:

```text
BTC · 15m

Time remaining
08:42

Opening reference
$XX,XXX

Current external reference
$XX,XXX

DreamDEX
Up ask: 0.58

Edge Lab model
P(Up): 0.66

Executable edge
+8.0%

Confidence
72%

Signal
BUY UP

[Inspect]
```

Do not overwhelm judges with professional trading-terminal complexity.

---

# 33. Opportunity Ranking

Rank opportunities by a risk-adjusted score.

For example:

```text
edge
×
confidence
×
liquidity factor
```

Do NOT rank merely by raw edge.

A huge apparent edge with:

```text
stale data
low liquidity
low confidence
```

should not appear as the best opportunity.

---

# 34. Signal Details

Clicking a signal should show:

```text
Market
Model
Inputs
Order book
Edge calculation
Confidence
Risk checks
Execution option
```

Make the chain of reasoning auditable.

---

# 35. LLM Usage

LLMs may be used for:

- natural-language explanations;
- summarizing model signals;
- agent interaction;
- user-facing descriptions.

LLMs must NOT be the sole source of numerical probability.

Do not ask an LLM:

```text
What probability will BTC go up?
```

and directly trade from the answer.

Quantitative probability must come from a deterministic/statistical model.

---

# 36. No Fake AI

Do not claim:

```text
AI ensemble
machine learning
deep learning
predictive AI
```

unless the implementation actually contains it.

If the implementation uses:

```text
realized volatility
+
statistical probability model
```

say exactly that.

Transparency is preferred over marketing exaggeration.

---

# 37. Historical Evaluation

If enough data is available, optionally show:

```text
historical signal accuracy
Brier score
calibration
paper P&L
```

However:

Do NOT fabricate backtests.

Do NOT use future information when calculating historical probabilities.

Prevent look-ahead bias.

Clearly separate:

```text
backtest
paper trading
live testnet
```

results.

---

# 38. Metrics

Useful metrics include:

```text
Brier score
calibration error
number of signals
average predicted edge
realized signal accuracy
paper P&L
```

Do not optimize only for:

```text
win rate
```

A probability model should primarily be judged on calibration and expected value, not just binary accuracy.

---

# 39. DreamDEX-Specific Error Handling

Handle at minimum:

```text
MARKET_NOT_FOUND
MARKET_NOT_TRADING
MARKET_LOCKED
MARKET_RESOLVED
MARKET_VOIDED
STALE_MARKET_DATA
STALE_PRICE_DATA
INSUFFICIENT_LIQUIDITY
SLIPPAGE_TOO_HIGH
EDGE_BELOW_THRESHOLD
SIGNATURE_REJECTED
TRANSACTION_FAILED
RPC_ERROR
```

Do not leak private keys, environment values, or raw sensitive provider information in errors.

---

# 40. Wallet Security

NEVER commit:

- private keys;
- seed phrases;
- mnemonic phrases;
- wallet recovery information;
- production API credentials.

Use:

```text
.env.example
```

with fake placeholders.

Browser applications must never embed raw private keys in client-side source.

Prefer normal wallet signing for user-facing execution.

---

# 41. Bot / Server Wallet

If a bot signer is technically required for TESTNET automation:

- use a dedicated hackathon testnet wallet;
- keep the private key server-side;
- use environment secrets;
- keep minimal testnet funds;
- never reuse the user's primary wallet.

Do NOT require a main wallet seed phrase.

---

# 42. Transaction Safety

Every transaction must validate immediately before signing:

```text
network
chainId
marketId
market status
side
price
quantity
maximum spend
slippage
time remaining
```

Do not sign stale prebuilt transactions.

---

# 43. Dependency Security

Pin or appropriately constrain major Web3 dependencies.

Use the current supported DreamDEX SDK.

Do not:

- install random unofficial DreamDEX SDKs;
- paste unknown smart-contract code from social media;
- execute downloaded scripts without inspection.

Use official documentation and official packages as primary references.

---

# 44. Do Not Build a New Prediction Market

DreamDEX already provides the Event Contract infrastructure.

Do NOT implement:

- custom binary-market smart contracts;
- custom oracle;
- custom settlement protocol;
- custom matching engine;
- separate prediction-market AMM.

The hackathon value should be built ON TOP OF DreamDEX.

---

# 45. Explicitly Forbidden Scope

Do NOT expand this project into:

- generic crypto trading bot;
- spot trading system;
- perpetual futures bot;
- leverage platform;
- arbitrage across dozens of exchanges;
- social copy-trading network;
- token issuance;
- custom prediction market;
- new wallet;
- portfolio accounting platform.

Unless absolutely required to complete the DreamDEX demo.

Focus on:

```text
probability
→ edge
→ explain
→ safe execution
```

---

# 46. Polymarket Separation

Do NOT remove existing Polymarket functionality.

Do NOT change existing Polymarket behavior merely to accommodate DreamDEX.

Common concepts should move into shared interfaces only when doing so is a natural, low-risk refactor.

Preferred:

```text
EdgeLab Core
    │
    ├── PolymarketAdapter
    │
    └── DreamDEXAdapter
```

Avoid:

```text
DreamDEX-specific assumptions
embedded into Polymarket code
```

---

# 47. Terminology Separation

Polymarket and DreamDEX may have different:

- market structures;
- settlement semantics;
- outcome representations;
- order-book behavior;
- identifiers.

Do not force both venues into an abstraction that loses important semantics.

Common interfaces should cover only genuinely common concepts.

Venue-specific details may remain venue-specific.

---

# 48. Hackathon Demo Mode

Provide one deterministic, judge-friendly flow.

Recommended:

```text
1. Open dashboard.

2. Load live DreamDEX testnet Event Contracts.

3. Select BTC 15m.

4. Show:
   - DreamDEX order book
   - underlying/reference inputs
   - independent model probability

5. Calculate executable edge.

6. Explain why edge exists.

7. Show all risk checks.

8. Create a trade proposal.

9. User confirms testnet trade.

10. Submit through DreamDEX SDK.

11. Show transaction/order result.

12. Later show settlement/audit state.
```

If no attractive live edge exists during the demo:

DO NOT fake one.

Instead allow:

```text
"Show all markets"
```

and demonstrate:

```text
NO_EDGE
```

as a valid model output.

Optionally include a clearly labeled historical/demo fixture for explaining a positive-edge case.

---

# 49. Fixture Policy

Fixtures may be used for:

- tests;
- reproducible demo explanation;
- UI development.

They must be clearly labeled:

```text
SIMULATED
HISTORICAL FIXTURE
```

Never present fixtures as:

```text
LIVE DREAMDEX
```

Do not hardcode a profitable-looking signal into live mode.

---

# 50. Test Requirements

At minimum test:

## Market mapping

DreamDEX market correctly maps into Edge Lab internal representation.

## Market identity

Markets remain separate even if pool addresses are reused.

## Probability validation

Probabilities remain within valid bounds.

## Edge calculation

Executable Up/Down edge calculation is correct.

## Stale data

Stale external data results in no trade.

## Market state

Locked/resolved/voided markets cannot receive new orders.

## Expiry

Trades too near expiry are rejected.

## Liquidity

Insufficient depth is rejected.

## Slippage

Excessive slippage is rejected.

## Paper mode

Paper mode never submits a blockchain transaction.

## Mainnet protection

Mainnet trading cannot be enabled accidentally.

---

# 51. Documentation

Create:

```text
docs/DREAMDEX_ARCHITECTURE.md
```

Explain:

- DreamDEX adapter;
- Event Contract lifecycle;
- probability model;
- edge calculation;
- external data;
- basis risk;
- risk engine;
- execution path;
- paper/testnet/mainnet modes.

---

# 52. Hackathon Submission Documentation

Create:

```text
docs/DREAMDEX_SUBMISSION.md
```

Include:

```text
Project
DreamDEX Edge Lab

Problem

DreamDEX prices represent market-implied probabilities,
but traders have little tooling to independently estimate
fair probabilities and understand when market prices
diverge from quantitative estimates.

Solution

An explainable probability and edge analysis layer that
combines live DreamDEX Event Contracts with an independent
short-horizon quantitative model.

Technology

- Somnia
- DreamDEX Event Contracts
- @somnia-chain/markets-sdk
- viem
- existing Edge Lab core
```

Also document:

- working testnet URL;
- repository;
- demo instructions;
- network;
- DreamDEX SDK version;
- supported market types;
- known limitations.

---

# 53. README

Add:

```text
## DreamDEX Event Contracts
```

Clearly describe what functionality was added specifically for this hackathon.

Do not make the repository look as though DreamDEX was always part of the existing system if it was not.

---

# 54. Git Strategy

Before implementation:

```text
tag:
pre-dreamdex-hackathon
```

Suggested branch:

```text
hackathon/dreamdex-2026
```

Suggested commits:

```text
feat(dreamdex): add Event Contracts market adapter

feat(model): add short-horizon event probability estimator

feat(edge): calculate executable DreamDEX edge

feat(risk): add expiry liquidity and stale-data guards

feat(dreamdex): add paper and testnet execution

feat(ui): add DreamDEX Edge Lab dashboard

test(dreamdex): cover lifecycle and execution guards

docs(dreamdex): document Event Contracts integration
```

Do not falsify timestamps or rewrite old work as new work.

---

# 55. Performance

Event Contracts are short-duration markets.

Avoid slow polling loops where a realtime SDK mechanism is available.

Use live market/order-book streams where appropriate.

However, do not prematurely build complex low-latency trading infrastructure.

This is an analytics and decision-support product first.

---

# 56. Rate and Resource Limits

Avoid:

- uncontrolled loops;
- excessive RPC calls;
- reconnect storms;
- polling every component independently.

Centralize market subscriptions and share state.

Gracefully reconnect WebSocket/SDK subscriptions.

---

# 57. Production Claims

This is a hackathon prototype.

Do NOT claim:

```text
production-grade trading system
institutional-grade execution
guaranteed alpha
```

unless those properties are genuinely established.

Use:

```text
research prototype
decision-support tool
testnet trading prototype
```

where appropriate.

---

# 58. Definition of Done

The DreamDEX integration is complete when:

- [ ] Existing Polymarket functionality still works.
- [ ] DreamDEX exists as an isolated venue adapter.
- [ ] Official DreamDEX Event Contracts SDK is used.
- [ ] Live Event Contracts can be discovered.
- [ ] `marketId` or symbol is used as canonical market identity.
- [ ] Pool address reuse does not corrupt state.
- [ ] Current on-chain market state is checked before writes.
- [ ] Independent quantitative Up probability is calculated.
- [ ] Model inputs and explanation are visible.
- [ ] Edge uses executable prices, not merely midpoint.
- [ ] Data freshness is enforced.
- [ ] Expiry protection is implemented.
- [ ] Liquidity/slippage protection is implemented.
- [ ] Paper mode works without a wallet.
- [ ] Testnet execution works through DreamDEX.
- [ ] Mainnet is disabled by default.
- [ ] Mainnet cannot be accidentally activated.
- [ ] User confirmation exists before real execution.
- [ ] Resolved/voided markets are handled correctly.
- [ ] No fake live signals are shown.
- [ ] No private keys are committed.
- [ ] Build passes.
- [ ] Relevant tests pass.
- [ ] README and hackathon documentation are complete.

---

# 59. Highest-Level Rule

For every proposed feature ask:

> Does this improve our ability to independently estimate, explain, and safely act on a pricing discrepancy in a DreamDEX Event Contract?

If YES:

it may belong in this hackathon.

If NO:

do not implement it.

The product should remain:

```text
DreamDEX market
      ↓
Independent probability
      ↓
Executable edge
      ↓
Risk checks
      ↓
Explainable proposal
      ↓
Paper / testnet execution
```

Do not turn it into a generic crypto trading platform.
