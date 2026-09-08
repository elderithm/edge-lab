# CLAUDE.md — Polymarket Edge Lab

## Mission

Build **Polymarket Edge Lab**, a read-only research and paper-trading toolkit for testing whether publicly observable Polymarket trading patterns are reproducible after latency, price drift, fees, slippage, liquidity, and out-of-sample validation.

The project exists to **falsify weak trading claims before risking capital**, not to promise returns.

## Non-negotiable scope boundary

This repository MUST remain **read-only with respect to real trading**.

Allowed:

- Public Gamma API reads.
- Public Data API reads.
- Public CLOB market-data reads (prices, spreads, order books, price history).
- Official geoblock status checks.
- Local SQLite persistence.
- CSV/JSON exports.
- Backtests and forward paper trading.
- Wallet-behavior analysis.
- Market-inefficiency scans.
- Statistical summaries and reproducibility reports.

Forbidden in this repository:

- Private-key loading or wallet signing.
- API-key creation or authenticated CLOB trading.
- Real order placement, cancellation, or settlement.
- Deposits, withdrawals, bridging, or token approvals.
- VPN/proxy/Tor/geoblock bypasses.
- Code whose purpose is to evade platform, regulatory, or geographic restrictions.
- Claims that a strategy is profitable without measured evidence.

If a requested implementation crosses this boundary, stop and explain the conflict instead of silently adding it.

## Canonical documentation

Before making meaningful changes, read the relevant files under `docs/`:

1. `docs/00-product-brief.md`
2. `docs/01-architecture.md`
3. `docs/02-data-sources.md`
4. `docs/03-cli-spec.md`
5. `docs/04-wallet-reverse-engineering.md`
6. `docs/05-paper-trading.md`
7. `docs/06-safety-and-compliance.md`
8. `docs/07-testing-and-quality.md`
9. `docs/08-roadmap.md`

When documentation conflicts, this file wins, then `docs/06-safety-and-compliance.md`.

## Engineering principles

- Python 3.11+.
- Prefer a small, typed, testable architecture over cleverness.
- Keep network access behind API client interfaces so tests can use fixtures/fakes.
- Store timestamps internally as UTC Unix seconds or timezone-aware UTC datetimes.
- Never use local timezone implicitly.
- Use `Decimal` for prices, sizes, notional values, fees, and P&L calculations.
- Be explicit about missing or approximate data.
- Never infer realized P&L from incomplete data without labeling the estimate.
- Every network call needs timeout, retry/backoff where appropriate, and actionable errors.
- Respect documented rate limits; do not attempt to defeat throttling.
- CLI commands should be deterministic where practical and script-friendly.
- Machine-readable output (`--json`) should remain stable.

## Preferred project structure

```text
polymarket-edge-lab/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── docs/
├── src/
│   └── polymarket_edge_lab/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── api/
│       │   ├── base.py
│       │   ├── gamma.py
│       │   ├── data.py
│       │   ├── clob.py
│       │   └── geoblock.py
│       ├── analysis/
│       │   ├── wallet.py
│       │   ├── arb.py
│       │   └── reverse_engineer.py
│       ├── paper/
│       │   ├── db.py
│       │   ├── follower.py
│       │   ├── execution.py
│       │   └── report.py
│       └── export/
│           └── csv_export.py
└── tests/
    ├── fixtures/
    ├── test_api_*.py
    ├── test_wallet_analysis.py
    ├── test_arb.py
    └── test_paper_*.py
```

The exact module boundaries may evolve, but keep public API clients, analysis logic, and persistence separated.

## Dependencies

Prefer:

- `httpx` for HTTP.
- `typer` for CLI.
- `rich` for human-readable terminal output.
- `pydantic` for external API models/config validation when useful.
- `pytest` (+ `pytest-httpx` or equivalent) for tests.

Avoid heavy data-science dependencies unless a feature materially benefits from them. If pandas/numpy/scipy are introduced, justify them in the PR/change summary.

## Definition of done for each feature

A feature is not complete until:

1. The CLI/API behavior is implemented.
2. Errors and empty-data cases are handled.
3. Unit tests cover normal and edge cases.
4. Network-dependent tests use fixtures/mocks by default.
5. `README.md` or the appropriate docs are updated.
6. `ruff`/formatting/type checks and `pytest` pass.
7. No real-trading or geoblock-bypass capability has been introduced.

## First implementation priority

Implement the MVP in this order:

1. Package/bootstrap + CLI skeleton.
2. Public API clients and typed models.
3. `geo`, `market`, `analyze-wallet`, `export-wallet`.
4. `arb`, `scan-arbs` with executable-size-aware calculations.
5. SQLite paper-trading schema and `paper-follow` / `paper-report`.
6. `reverse-engineer-wallet` for strategy-pattern analysis.
7. Tests, fixtures, documentation, and CI.

Do not jump ahead to speculative ML before the deterministic pipeline is solid.

## Output expectations when you work

Before coding a substantial change:

- State which docs govern the work.
- Inspect existing code; do not rewrite working code unnecessarily.
- Propose a compact implementation plan.

After coding:

- Summarize changed files.
- List tests/checks run and their results.
- Call out assumptions and data limitations.
- Identify the next highest-value task.

## DreamDEX Event Contracts Hackathon

Before implementing DreamDEX functionality, read `docs/DREAMDEX_HACKATHON.md`.

Critical constraints:

- Preserve the existing `polymarket-edge-lab` functionality.
- Add DreamDEX as an isolated venue adapter rather than rewriting the project around DreamDEX.
- Use the official `@somnia-chain/markets-sdk` Event Contracts integration.
- Do not use the DreamDEX HTTP API as a substitute for the Event Contracts SDK.
- Use `marketId` or symbol as the canonical market identity; never use a recycled pool address as the market identity.
- Verify current on-chain market status before every write.
- Probability estimates must come from an explicit quantitative model, not an LLM guess.
- Calculate edge against executable prices and account for liquidity, data freshness, time to expiry, and model uncertainty.
- Default to paper trading and Somnia Shannon Testnet.
- Mainnet trading must be disabled by default and must never be enabled implicitly.
- Do not expose or commit private keys.
- Do not implement leverage, martingale, loss chasing, or uncapped position sizing.
- Do not fake live market signals or profitable results.
- Do not build a new prediction market, oracle, AMM, or matching engine.
- Keep analysis, risk evaluation, and transaction execution as separate layers.
- Prefer the smallest complete DreamDEX probability → edge → explanation → testnet execution flow.
