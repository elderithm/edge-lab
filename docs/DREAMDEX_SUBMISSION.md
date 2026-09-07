# DreamDEX Edge Lab — Hackathon Submission

## Project

**DreamDEX Edge Lab** — an explainable probability & edge analysis layer for
DreamDEX Event Contracts, built on the existing `polymarket-edge-lab` core.

## Problem

DreamDEX Event Contract prices are market-implied probabilities (an Up ask of
`0.62` ≈ a 62% implied chance), but traders have little tooling to independently
estimate a fair probability and see when the market price diverges from a
quantitative estimate — after real execution costs.

## Solution

Combine live DreamDEX Event Contracts with an independent short-horizon
quantitative model. For each BTC/ETH market the tool:

1. reads the live on-chain market + order book (official SDK),
2. estimates `P(Up)` from realized volatility and the move vs. the opening
   reference (no LLM),
3. computes the **executable** edge by walking the book to the intended size,
4. runs a risk engine (freshness, expiry, liquidity, slippage, exposure),
5. emits an explicit, explainable signal, and
6. lets the user paper-trade or submit a Shannon Testnet order after confirming.

## Technology

- Somnia (Shannon Testnet, chainId 50312)
- DreamDEX Event Contracts
- `@somnia-chain/markets-sdk` **v0.29.0** (`>=0.25.0`)
- `viem` v2
- Existing Edge Lab core (Python 3.11+, `Decimal` math)
- Thin TypeScript bridge (`dreamdex-bridge/`) run via Node's native TS support

## How it is built

- **Analytics in Python**, transport/execution in a thin **TypeScript** bridge
  over the official SDK. No analytic logic is duplicated in TS.
- DreamDEX is an **isolated venue adapter**; existing Polymarket functionality is
  untouched (176 tests pass, including the original Polymarket suite).

## Demo instructions

Paper / offline (no wallet, deterministic, clearly SIMULATED):

```bash
pip install -e ".[dev]"
edge-lab dreamdex scan --source fixture
edge-lab dreamdex inspect 0x0000000000000000000000000000000000000000000000000000000000000001 --source fixture
edge-lab dreamdex paper-trade 0x0000000000000000000000000000000000000000000000000000000000000001 --source fixture
edge-lab dreamdex report
```

Live testnet reads (verified against Shannon testnet):

```bash
cd dreamdex-bridge && npm install
# Shannon testnet endpoints (from the markets-sdk README):
export INDEXER_URL="https://dev.smk.somnia.host/v1/graphql"
export NETWORK=testnet TRADING_MODE=paper
edge-lab dreamdex scan --assets BTC,ETH   # live discovery + model + executable edge
edge-lab dreamdex inspect <marketId>
```

Live discovery and the full read pipeline (on-chain status, order book, price
feed → model → edge → risk) are verified end-to-end against Shannon testnet. When
the live venue has no started/liquid market, the tool honestly reports
`LOW_CONFIDENCE` / `INSUFFICIENT_LIQUIDITY` / `TOO_CLOSE_TO_EXPIRY` — it never
fabricates an edge.

Testnet execution (dedicated hackathon testnet wallet):

```bash
# in dreamdex-bridge/.env: TRADING_MODE=testnet, PRIVATE_KEY=<testnet-only key>
edge-lab dreamdex execute <marketId> --size 5 --yes
```

## Submission facts

- **Network:** Somnia Shannon Testnet (chainId 50312); mainnet (5031) disabled by default.
- **DreamDEX SDK version:** `@somnia-chain/markets-sdk@0.29.0`.
- **Supported market types:** BTC and ETH short-window (15m / 1h) binary Event Contracts.
- **Working testnet URL / demo video:** _add before submitting_ (indexer URL is deployment-specific and supplied via `.env`).
- **Repository:** this repo (`polymarket-edge-lab`), DreamDEX code under `edge_lab/core`, `edge_lab/venues/dreamdex`, `edge_lab/strategies`, `dreamdex-bridge/`.

## Known limitations

- This is a **research / decision-support prototype**, not a production trading
  system. No guaranteed-profit claims: an edge is a *model-estimated* expected
  advantage.
- The probability model is a single interpretable baseline (realized-vol
  Gaussian). It is judged on calibration/EV, not win rate.
- Live discovery/execution require a DreamDEX testnet **indexer URL** and (for
  writes) a testnet **signer**; these are supplied via `.env` and were not
  bundled. Signed testnet transactions require wallet credentials to verify
  end-to-end; the SDK integration and gating are complete and typechecked.
- The external spot feed is a model input with **basis risk** vs. the DreamDEX
  settlement reference; it is labeled and never shown as the official settlement.
