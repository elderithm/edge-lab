# Roadmap

## Phase 0 — Bootstrap

- `pyproject.toml`
- `src/` package
- Typer CLI
- HTTP client abstraction
- logging/error model
- test/quality tooling
- GitHub Actions

## Phase 1 — Public-data foundation

- Gamma market lookup/listing
- Data API wallet activity/trades
- CLOB read-only order book/prices
- geoblock status
- pagination and retries
- normalized models

## Phase 2 — Research commands

- `geo`
- `market`
- `analyze-wallet`
- `export-wallet`
- `arb`
- `scan-arbs`

## Phase 3 — Forward paper follower

- SQLite schema
- run IDs
- signal deduplication
- size-aware simulated execution
- skip reasons
- paper positions
- exit simulation
- `paper-report`

## Phase 4 — Strategy Reverse Engineer

- `reverse-engineer-wallet`
- time-window claims
- entry-price clusters
- sizing patterns
- repeated market families
- candidate rule generation
- chronological discovery/validation split
- report artifacts

## Phase 5 — Research hardening

- multi-wallet cohort comparison
- leaderboard-based candidate discovery using public data
- strategy stability across wallets and time
- richer reports
- optional notebook/examples layer

## Phase 6 — Optional local dashboard

Only after the CLI/research core is mature:

- local read-only web UI;
- wallet report viewer;
- paper-run dashboard;
- market edge scanner;
- no real-trading controls.

## Not on roadmap

Real-money execution is deliberately outside this repository.
