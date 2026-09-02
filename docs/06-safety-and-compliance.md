# Safety and Compliance Boundary

## Repository policy

This repository is intentionally limited to:

- public-data collection;
- market/wallet research;
- statistical analysis;
- backtesting where data supports it;
- forward paper trading.

## Prohibited implementation

Do not add:

- wallet private keys;
- mnemonic/seed handling;
- transaction signing;
- CLOB authenticated trading headers;
- order placement/cancellation;
- smart-contract approvals or settlement;
- deposit/withdrawal/bridge automation;
- geoblock circumvention;
- proxy rotation designed to change apparent jurisdiction;
- instructions to bypass platform restrictions.

## Geoblock handling

The `geo` feature may query and display official geoblock status.

If the official endpoint reports blocked access, the program should state that real trading is unavailable from that location and continue to allow only public research/paper functionality.

Never automatically change network routes or suggest evasion.

## Financial claims

Documentation and CLI output must avoid statements like:

- "guaranteed arbitrage";
- "risk-free profit";
- "this wallet always wins";
- "expected guaranteed return".

Prefer:

- "apparent edge";
- "paper-estimated edge";
- "observed historical pattern";
- "requires forward validation".

## Data limitations

A public trade feed is not the same as knowing a trader's complete strategy, intent, funding history, hedges elsewhere, or private information set.

Reports must include this limitation when drawing behavioral conclusions.
