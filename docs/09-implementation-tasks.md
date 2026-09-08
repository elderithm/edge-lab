# Initial Implementation Tasks for Claude Code

Work in small, reviewable increments. Complete and test one group before moving to the next.

## Task 1 — Bootstrap

- Create `pyproject.toml` and package structure.
- Add dependencies: Typer, Rich, httpx, pydantic, pytest, Ruff, selected type checker.
- Add `edge-lab --help`.
- Add typed settings and error hierarchy.
- Add GitHub Actions quality workflow.

Acceptance:

```bash
edge-lab --help
ruff check .
ruff format --check .
pytest
```

all pass.

## Task 2 — Public clients

Implement read-only clients for:

- Gamma markets;
- Data user activity/trades;
- CLOB order book/prices/history as needed;
- geoblock.

Acceptance:
- fully mocked unit tests;
- pagination tested;
- `Decimal` normalization tested;
- retries are bounded.

## Task 3 — Core CLI

Implement:

- `geo`
- `market`
- `analyze-wallet`
- `export-wallet`

Acceptance:
- human and JSON output where specified;
- correct timezone behavior;
- stable CSV headers.

## Task 4 — Edge scanner

Implement:

- `arb`
- `scan-arbs`

Acceptance:
- executable-size/VWAP logic;
- configurable buffers;
- no false "arbitrage" label when liquidity is insufficient;
- ranking works despite per-market failures.

## Task 5 — Paper follower

Implement database, signal polling, paper fills, positions, exits, and reports.

Acceptance:
- resumable after restart;
- dedupes signals;
- reason-coded skips;
- separate realized and unrealized P&L.

## Task 6 — Reverse engineer

Implement `reverse-engineer-wallet` according to `04-wallet-reverse-engineering.md`.

Acceptance:
- generates JSON/CSV/Markdown artifacts;
- discovery/validation split is chronological;
- report distinguishes facts/derived metrics/estimates/unknowns.

## Task 7 — README

Replace the minimal README with a concise user-facing README containing:

- purpose;
- safety boundary;
- installation;
- command examples;
- architecture summary;
- development commands;
- disclaimer that results are research/paper estimates, not guaranteed returns.
