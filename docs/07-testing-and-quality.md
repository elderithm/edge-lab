# Testing and Quality

## Required tooling

Configure:

- `pytest`
- `ruff`
- a formatter (`ruff format` is acceptable)
- static typing (`mypy` or `pyright`; choose one and document it)

## Unit tests

### API parsing

Fixture tests for:

- normal responses;
- empty arrays;
- string/number numeric representations;
- missing optional fields;
- HTTP 4xx/5xx;
- timeouts;
- throttling/transient errors.

### Wallet analysis

Tests for:

- timezone conversion;
- hour bins around UTC date boundaries;
- BUY/SELL classification;
- price buckets;
- concentration metrics;
- no-record behavior.

### Arbitrage math

Test using synthetic order books:

- top-of-book apparent edge but insufficient size;
- multi-level fills;
- no edge after buffer;
- partial liquidity;
- Decimal precision;
- binary outcomes are mapped correctly.

### Paper follower

Test:

- duplicate signals;
- stale signals;
- drift threshold;
- simulated BUY;
- partial/full SELL;
- cannot sell beyond paper position;
- persistence/reload;
- report realized vs unrealized separation.

## Integration tests

Live official API tests should be optional and marked, e.g. `@pytest.mark.live`, so normal CI does not depend on external services.

## Fixtures

Keep sanitized API response fixtures under `tests/fixtures/`.

Do not make tests depend on a single famous wallet remaining unchanged forever.

## CI

GitHub Actions should run on pull requests and pushes:

```text
ruff check .
ruff format --check .
<type checker>
pytest
```

Use at least Python 3.11 and one newer supported version.

## Quality gate

No feature is accepted if it:

- introduces float-based money math;
- requires live network access for ordinary tests;
- silently drops pagination;
- hides partial-fetch errors;
- conflates realized and unrealized P&L;
- introduces real-trading credentials/endpoints.
