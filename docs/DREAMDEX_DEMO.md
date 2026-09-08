# DreamDEX Edge Lab — Demo Script (③)

A deterministic, judge-friendly walkthrough. Everything is real DreamDEX Shannon
testnet data except where a step is explicitly labeled **SIMULATED FIXTURE**.

## Setup (once)

```bash
pip install -e ".[dev]"
cd dreamdex-bridge && npm install && cd ..
export INDEXER_URL="https://dev.smk.somnia.host/v1/graphql"
export NETWORK=testnet
export TRADING_MODE=paper
```

## Option A — Dashboard (recommended for judges)

```bash
edge-lab dreamdex dashboard          # serves http://127.0.0.1:8787
```

1. Open the dashboard. It lists live BTC/ETH Event Contracts as cards.
2. Each card shows: time remaining, opening reference, current external
   reference (source-labeled), DreamDEX Up ask, model `P(Up)`, executable edge,
   confidence, and the signal state.
3. Click **Inspect** on a card to see the full auditable chain: model inputs,
   order book, edge calculation, every risk check, and the explanation.
4. When the live venue has no started/liquid market, cards honestly show
   `LOW_CONFIDENCE` / `INSUFFICIENT_LIQUIDITY` / `TOO_CLOSE_TO_EXPIRY` — the model
   never fabricates an edge.

## Option B — CLI (same pipeline, terminal)

```bash
# 1-2. Discover + rank live markets
edge-lab dreamdex scan --assets BTC,ETH

# 3-7. Full reasoning chain for one market (model, order book, edge, risk)
edge-lab dreamdex inspect <marketId>

# 8-9. Paper proposal + simulated fill (no wallet)
edge-lab dreamdex paper-trade <marketId>
edge-lab dreamdex report

# 8b. Rehearse the exact testnet transaction WITHOUT signing (no wallet)
edge-lab dreamdex preview <marketId> --side UP --price 0.55 --size 5
```

## Explaining a positive-edge case (SIMULATED FIXTURE)

If no live edge exists during the demo (common on testnet), show a clearly
labeled simulated market to explain a positive-edge signal end to end:

```bash
edge-lab dreamdex scan --source fixture
edge-lab dreamdex inspect 0x0000000000000000000000000000000000000000000000000000000000000001 --source fixture
```

The header prints `[SIMULATED FIXTURE — not live DreamDEX data]`. Never present
this as live.

## Signed testnet execution (needs your testnet wallet)

Steps 9-12 (confirm → submit → result → settlement) require a dedicated testnet
signer. See `docs/DREAMDEX_TESTNET_RUNBOOK.md`.

## What to emphasize

- Independent quantitative probability (realized-vol Gaussian, **no LLM**), with
  confidence separate from probability.
- Edge from an **order-book walk** (executable), not the midpoint.
- One risk engine; explicit signal states; ranked by `edge × confidence × liquidity`.
- Paper default, no wallet; mainnet disabled and never inferred.
- Honest `NO_EDGE`/`LOW_CONFIDENCE` output — no fabricated signals.
