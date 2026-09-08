# Edge Lab

A **read-only** research and paper-trading toolkit for testing whether publicly
observable prediction-market trading patterns survive realistic execution
assumptions — latency, price drift, fees, slippage, liquidity, and out-of-sample
validation. It covers **Polymarket** and, as an isolated venue layer, **DreamDEX
Event Contracts on Somnia** (see the DreamDEX section below).

The project exists to **falsify weak trading claims before risking capital**, not
to promise returns. Every number it prints is an observation or a conservative
paper estimate, never a guarantee.

## Safety boundary

This repository is intentionally limited to public-data research and simulated
(paper) trading. It contains **no** capability for and will not implement:

- private-key loading, mnemonic/seed handling, or transaction signing;
- authenticated CLOB trading, order placement, or cancellation;
- deposits, withdrawals, bridging, or token approvals;
- geoblock/VPN/proxy circumvention.

The `geo` command reports the official geoblock status for information only. If a
location is blocked, the tool says real trading is unavailable there and keeps
working in read-only/paper mode — it never suggests a bypass.

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # or: pip install -e .   (runtime only)
edge-lab --help
```

Configuration comes from CLI flags, then environment variables, then defaults:

```text
EDGE_LAB_DB_PATH=.edge-lab/paper.db     # paper-trading SQLite database
EDGE_LAB_HTTP_TIMEOUT=10                # per-request timeout (seconds)
EDGE_LAB_USER_AGENT=polymarket-edge-lab/0.1
```

## Commands

```bash
# Official geoblock status (informational only)
edge-lab geo
edge-lab geo --json

# Market metadata + current price/order-book summary
edge-lab market <market-slug>

# Historical mid-price series for an outcome token (backtesting input)
edge-lab price-history <token-id> --interval 1d
edge-lab price-history <token-id> --interval 1w --fidelity 60 --json
# ...with descriptive stats (return, max drawdown, per-step volatility)
edge-lab price-history <token-id> --interval 1d --stats

# Public wallet behavior (hours, weekdays, sides, price/notional buckets)
edge-lab analyze-wallet 0xADDRESS --max-records 5000 --utc-offset 9

# Falsify a time-window claim ("trades mainly 6-9am"): exact inside/outside %
edge-lab analyze-wallet 0xADDRESS --utc-offset 9 --claim-window 6-9

# Compare several wallets side by side (is a pattern shared or idiosyncratic?)
edge-lab analyze-cohort 0xADDR1 0xADDR2 0xADDR3 --utc-offset 9 --claim-window 6-9

# Export raw public activity to CSV (stable headers, ISO-8601 UTC)
edge-lab export-wallet 0xADDRESS --output activity.csv

# Size-aware complete-set (YES+NO) mispricing check for one market
edge-lab arb <market-slug> --notional 10 --fee-buffer-bps 50 \
  --slippage-buffer-bps 50 --min-edge-bps 25

# Scan active binary markets for size-aware paper-edge candidates
edge-lab scan-arbs --limit 100 --top 20 --notional 10 --min-edge-bps 25
edge-lab scan-arbs --limit 100 --output candidates.csv    # export all scanned rows

# Forward paper-follow a public wallet (never places real orders)
edge-lab paper-follow 0xADDRESS --paper-usdc 10 --max-age 120 \
  --max-drift-bps 300 --poll 5
edge-lab paper-follow 0xADDRESS --once      # single poll then exit

# List paper runs (discover run IDs for paper-report --run-id)
edge-lab paper-runs

# Realized vs. mark-to-market P&L for a paper run (reported separately)
edge-lab paper-report
edge-lab paper-report --run-id 1 --mark --json

# Reverse-engineer candidate strategy patterns into report artifacts
edge-lab reverse-engineer-wallet 0xADDRESS --utc-offset 9 \
  --output-dir reports/wallet-0xADDRESS
```

`--json` gives stable machine-readable output where supported. `--verbose`
surfaces tracebacks for unexpected errors. Exit codes: `0` success, `1`
user/data/runtime error, `2` invalid usage.

### Why "size-aware"

`arb`/`scan-arbs` never quote an edge from top-of-book prices alone when the
requested size exceeds top-level liquidity. They walk the order book and compute
the volume-weighted cost, so a tiny top level that *looks* like free money is
correctly reported as insufficient depth after buffers — not as arbitrage.

### Paper trading is deliberately conservative

The follower measures the gap between *seeing* a public signal and getting a
realistically executable price. Each signal is either filled (size-aware
order-book walk) or skipped with a reason code (`signal_too_old`,
`insufficient_liquidity`, `price_drift_too_large`, `duplicate_signal`, …). Runs
are resumable, signals are de-duplicated across restarts, and realized and
unrealized P&L are always reported separately — net cash flow is never presented
as P&L while positions are open.

## DreamDEX Event Contracts

> **Added for the Somnia × DreamDEX Event Contracts Hackathon.** This is a new,
> isolated venue layer — it did not previously exist in the base Edge Lab
> toolkit, and the Polymarket functionality above is unchanged.

**DreamDEX Edge Lab** estimates an independent probability for a DreamDEX Up/Down
Event Contract, compares it against the *executable* on-chain price, and — after
risk checks — lets you paper-trade or submit a Somnia **Shannon Testnet** order.

- Independent quantitative model (realized-volatility Gaussian, no LLM), with an
  explanation and a confidence that is separate from the probability.
- Edge from an **order-book walk** (executable, size-aware), not the midpoint.
- A single risk engine: freshness, expiry, liquidity, slippage, exposure caps.
- **Paper is the default and needs no wallet.** Mainnet is disabled unless
  explicitly triple-gated and is never inferred from a connected wallet.
- Live on-chain reads + testnet execution use the official
  `@somnia-chain/markets-sdk` via a thin TypeScript bridge (`dreamdex-bridge/`);
  all analytics stay in Python.

### How it works (pipeline)

The probability is produced by an explicit **quantitative model** — **no LLM and
no news feed** — and the flow ends in **paper trading by default**, with
testnet execution only on a manual, explicitly confirmed command:

```text
DreamDEX markets   (live · official @somnia-chain/markets-sdk)
      │  market data only: on-chain order book + price history + external spot feed
      │  (no LLM, no news)
      ▼
Quantitative model   realized-volatility Gaussian log-return (no LLM)
      │  P(Up) = Φ( ln(current / opening) / (σ·√T) )   + a separate confidence
      ▼
Estimated probability   ──vs──   DreamDEX implied probability
                                 (executable, size-aware: order-book walk, not the midpoint)
      ▼
Edge detection   executable edge after fee / slippage / liquidity buffers
      ▼
Risk engine   freshness · expiry · liquidity · slippage · exposure
      ▼
Explainable signal
      ├──▶ paper trade       (default · no wallet)
      └──▶ testnet execution (manual · --yes · Shannon Testnet · mainnet disabled by default)
```

It is **decision support, not an autonomous trading agent**: there is no
unattended trade loop, no leverage, and no uncapped sizing.

```bash
# Local read-only dashboard (§32-style cards; live or --source fixture):
edge-lab dreamdex dashboard            # http://127.0.0.1:8787

# Offline, deterministic, clearly SIMULATED (no wallet, no network):
edge-lab dreamdex scan --source fixture
edge-lab dreamdex inspect <marketId> --source fixture   # full reasoning chain
edge-lab dreamdex paper-trade <marketId> --source fixture
edge-lab dreamdex preview <marketId> --side UP --price 0.55 --size 5  # rehearse a testnet order (no wallet)
edge-lab dreamdex report

# Live testnet reads (configure dreamdex-bridge/.env with INDEXER_URL):
edge-lab dreamdex scan
# Testnet execution (TRADING_MODE=testnet + a testnet signer, explicit confirm):
edge-lab dreamdex execute <marketId> --size 5 --yes
```

See `docs/DREAMDEX_ARCHITECTURE.md` and `docs/DREAMDEX_SUBMISSION.md`.

## Architecture

```text
edge_lab/
├── config.py            # typed settings (flags > env > defaults)
├── errors.py            # error hierarchy (expected vs. unexpected)
├── http.py              # httpx client: bounded retries, backoff+jitter
├── models.py            # Decimal-based domain models
├── api/                 # read-only Polymarket clients
│   ├── gamma.py         #   markets/metadata
│   ├── data.py          #   public wallet activity/positions
│   ├── clob.py          #   order books / prices
│   └── geoblock.py      #   geoblock status (informational)
├── analysis/
│   ├── wallet.py        # behavioral distributions
│   ├── arb.py           # size-aware complete-set edge (VWAP walk)
│   └── reverse_engineer.py  # facts/derived/estimates/unknowns + report
├── paper/
│   ├── db.py            # versioned SQLite schema
│   ├── follower.py      # signal lifecycle, skip reasons, fills, exits
│   └── report.py        # realized vs. mark-to-market reporting
├── export/csv_export.py # stable CSV export
└── cli.py               # Typer command surface
```

Design principles: all money/price/size math uses `Decimal`; timestamps are UTC
internally and only converted to a display timezone at presentation; network
access lives behind client interfaces so tests use fixtures/mocks with no live
calls; missing or approximate data is labeled, never fabricated.

## Development

```bash
ruff check .            # lint
ruff format --check .   # formatting
mypy                    # static typing
pytest                  # tests (network mocked; live tests skipped by default)
pytest -m live          # optional: smoke-test against the real Polymarket APIs
```

CI (GitHub Actions) runs all four on pushes and pull requests against Python
3.11 and 3.12.

## Disclaimer

Outputs are **research observations and conservative paper estimates**, not
financial advice and not guaranteed returns. A public trade feed does not reveal
a trader's intent, funding, hedges, or private information. Patterns discovered
from historical data carry in-sample bias and require forward paper validation
before any claim of a reproducible edge. Nothing here executes real trades.
