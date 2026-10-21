# Edge Lab — Development History (Polymarket → Event Contracts → Perps)

Edge Lab is one codebase that has grown venue by venue under a single rule:
**falsify weak trading claims before risking capital.** Each stage kept the
previous one working and added an isolated venue layer rather than rewriting the
core.

```text
Polymarket Edge Lab            DreamDEX Event Contracts          DreamDEX Perps
(public research, paper)  ──▶  (Shannon testnet, 50312)    ──▶  (Hideki testnet, 50383)
2026-08                        2026-09-02 → 09-08, PR #1         2026-10-22 →, this bounty
```

## 1. Polymarket Edge Lab (before both hackathons)

A read-only research and paper-trading toolkit for Polymarket:

- typed public clients for the Gamma, Data and CLOB APIs (timeouts, retries);
- public wallet behaviour analysis, cohort comparison and time-window claim tests;
- price-history and order-book depth analysis;
- size-aware complete-set mispricing checks (executable depth, not midpoints);
- forward paper-following with realized vs mark-to-market P&L kept separate;
- reverse-engineering reports that label observations, estimates and simulations.

Code: `edge_lab/api/`, `edge_lab/analysis/`, `edge_lab/paper/{db,follower,report}.py`, `edge_lab/cli.py`.

## 2. DreamDEX Event Contracts (Somnia × DreamDEX Event Contracts Hackathon)

Merged as [PR #1](https://github.com/elderithm/edge-lab/pull/1)
(branch `hackathon/dreamdex-2026`, commits `f8d6e50` … `d6e32e4`, 2026-09-02 → 09-08):

- `dreamdex-bridge/` — thin TypeScript bridge over `@somnia-chain/markets-sdk` 0.29.0;
- `edge_lab/venues/dreamdex/` — isolated venue adapter on Somnia Shannon Testnet;
- `edge_lab/core/` — realized-volatility Gaussian probability model, executable
  edge from order-book depth, risk engine, explainable signals;
- DreamDEX paper ledger, wallet-free order preview, manual testnet execution path;
- read-only local dashboard (stdlib HTTP server) with SIMULATED fixtures.

Known limitation carried forward: signed testnet execution was implemented but
**not verified end-to-end**.

## 3. DreamDEX Perps (dreamDEX Perps Builder Bounty 2026)

Branch `hackathon/dreamdex-perps-2026`, created from `main` after PR #1.

### Newly implemented in this bounty

| Area | New files |
|---|---|
| SDK bridge (Hideki, SDK 0.32.1) | `perps-bridge/` (`src/{env,sdk,commands,index}.ts`, `test/commands.test.ts`) |
| Venue adapter | `edge_lab/venues/dreamdex_perps/{config,bridge,errors,models,mapper,adapter,fixtures}.py` |
| Analytics | `edge_lab/perps/analytics.py` — funding, basis, liquidity, book-walk execution cost, realized volatility, margin/liquidation estimates, Market Opportunity Assessment |
| Risk engine | `edge_lab/perps/risk.py` — hard checks, 1x leverage cap, `RiskApproval` |
| Execution | `edge_lab/perps/execution.py` — submit, reconcile receipt + fills, evidence |
| Orchestration | `edge_lab/perps/service.py` |
| Paper trading | `edge_lab/paper/perps_paper.py` — long/short, MTM, funding accrual, testnet order ledger |
| CLI | `edge_lab/perps_cli.py` (`edge-lab perps …`) |
| Dashboard | `edge_lab/dashboard/{perps_api,perps_page}.py`, `/perps` route |
| Tests | `tests/test_perps_*.py`, `tests/perps_helpers.py`, captured live fixture `tests/fixtures/perps_snapshot_btc.json` |
| CI | `perps-bridge` typecheck + `node:test` job in `.github/workflows/quality.yml` |

### Reused from earlier stages

- The **subprocess bridge pattern** (JSON in/out, force-exit after flush, typed
  error codes) from `dreamdex-bridge/` and `edge_lab/venues/dreamdex/bridge.py`.
- The **stdlib dashboard server**, its TTL cache and its page styles (the Perps
  page imports the Event Contracts page's CSS).
- The **typer CLI conventions** (`--json`, `--verbose`, `--source fixture`, clean
  `EdgeLabError` exits) and the mount-a-subgroup approach.
- The **error hierarchy** (`EdgeLabError`, `ConfigError`, `PaperTradingError`).
- The **philosophy and labelling**: observed vs estimated vs simulated vs
  verified; paper by default; SIMULATED fixtures; no profit claims.
- The **CI quality gate** (ruff, format, mypy, pytest on 3.11 and 3.14).

Not reused on purpose: `EventContractMarket`, the binary probability model and
the event-contract risk engine are binary-event specific; forcing perps into them
would have been a risky cross-cutting refactor.

### Technical challenges solved

- **Per-market decimals** (6–24 base decimals live) and 18-decimal prices: exact
  integer scaling, quantities finer than a market's decimals rejected.
- **Funding semantics**: the rate is per 8 h *window* but settles hourly; the
  analytics derive both from on-chain fields instead of constants, and funding
  accrual uses the cumulative index rather than a rate approximation.
- **Stale mark feeds**: `markPriceOk=false` is mapped to "missing", never to a
  zero price (which would show a 100 % loss).
- **Official sizing**: `getMaxPerpOrderSize` (collateral, initial margin, position
  cap, wallet, voucher limits) is part of the testnet risk gate.
- **SDK isolation**: two Node packages on two SDK versions and two chains.
- **Honest post-trade state**: receipt status + decoded fills + a fresh position
  read, never "submitted therefore filled".

### Why the architecture is extensible

Venue I/O lives in `venues/<venue>/` behind a bridge; analytics and risk are pure
functions over typed snapshots; the CLI and dashboard only orchestrate. Adding a
venue means a new venue package and a mapper to the shared snapshot shape — the
analytics, risk, paper ledger and dashboard view work unchanged.
