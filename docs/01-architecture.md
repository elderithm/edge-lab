# Architecture

## Design goals

- Read-only external integrations.
- Clear separation between raw data, normalized domain models, analysis, and paper execution.
- Reproducible outputs.
- Easy mocking for tests.
- Safe defaults.

## Layers

### 1. API layer

Thin clients for official public endpoints:

- Gamma API: market/event discovery and metadata.
- Data API: public user activity/trades/positions where required.
- CLOB read endpoints: order books, prices, spreads, historical prices.
- Geoblock endpoint: informational availability/status check.

API clients return normalized typed models or well-defined transport models. Do not embed trading logic in clients.

### 2. Domain/model layer

Representative types:

- `Market`
- `Token`
- `OrderBook`
- `OrderBookLevel`
- `WalletActivity`
- `WalletTrade`
- `PaperSignal`
- `PaperFill`
- `PaperPosition`
- `StrategyObservation`

Use `Decimal` for all monetary/price/size fields.

### 3. Analysis layer

Pure or mostly-pure functions for:

- hourly/day-of-week wallet distributions;
- market/category concentration;
- entry-price buckets;
- BUY/SELL frequency;
- sizing concentration;
- apparent binary pair arbitrage;
- forward-follow drift;
- strategy reverse engineering.

Prefer functions that accept domain objects and return result objects, independent of the CLI.

### 4. Paper execution layer

Models the difference between a public signal and a realistically obtainable simulated fill.

It should apply:

- signal age limit;
- current best bid/ask;
- max allowed price drift;
- available quantity at price levels;
- configurable fee buffer;
- configurable slippage buffer;
- optional maximum paper notional per signal.

No real order endpoint exists anywhere in this layer.

### 5. Persistence

SQLite for:

- observed signals;
- skipped signals and reasons;
- simulated fills;
- positions;
- closures;
- paper-run metadata.

Use migrations or explicit schema versioning from the beginning.

### 6. CLI

Typer-based command surface. Human-readable terminal output by default and JSON where useful.

## Configuration

Config precedence:

1. CLI flags
2. environment variables
3. defaults

Safe defaults should be conservative.

Suggested environment variables:

```text
EDGE_LAB_DB_PATH=.edge-lab/paper.db
EDGE_LAB_HTTP_TIMEOUT=10
EDGE_LAB_USER_AGENT=polymarket-edge-lab/0.x
```

Do not define private-key or trading-credential settings.

## Logging

Use structured enough logs to diagnose:

- endpoint;
- status/error class;
- retry count;
- records fetched;
- rate-limit/throttling behavior;
- paper signal skip reason.

Never print secrets because this project should not possess trading secrets in the first place.
