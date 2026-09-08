# Implemented Enhancements (beyond the MVP spec)

This file records what exists in the code beyond `docs/00`–`docs/09`, so the
spec and the implementation stay legible together. The safety boundary in
`CLAUDE.md` and `docs/06` still governs everything here: read-only, no real
trading, no geoblock bypass.

## Command surface (current)

MVP commands from `docs/03`: `geo`, `market`, `analyze-wallet`,
`export-wallet`, `arb`, `scan-arbs`, `paper-follow`, `paper-report`,
`reverse-engineer-wallet`.

Added since:

- `price-history <token-id>` — historical mid-price series (CLOB
  `prices-history`), with `--interval`, `--fidelity`, and `--stats`
  (descriptive return / max-drawdown / per-step volatility, all `Decimal`).
- `analyze-cohort <addr...>` — side-by-side comparison of several wallets
  (record counts, BUY/SELL ratio, notional, top-market share, optional shared
  `--claim-window`). First step of roadmap Phase 5.
- `paper-runs` — list paper runs (id, created, wallet, signal/fill counts) so
  `paper-report --run-id` targets are discoverable.
- `--version` (root flag).

Added flags on existing commands:

- `analyze-wallet --claim-window START-END` — evaluate a "trades mainly between
  X and Y" claim, reporting exact inside/outside percentages (wrap-around
  windows supported).
- `scan-arbs --output FILE.csv` — export all scanned results (stable headers).
- `paper-report` human output now lists open positions with mark-to-market, and
  reports `max_realized_drawdown`.
- `analyze-wallet` human output now shows weekday distribution and outcome/side
  concentration (previously JSON-only).

## Correctness fixes found by review (with regression tests)

1. **Arb budget overshoot** (`analysis/arb.py`): the budget solver quantized the
   executable size with default rounding, letting deployed cost exceed the
   stated `--notional` by a rounding epsilon. Now rounds the quantity **down**
   so cost never exceeds budget. The confusingly-named `target_quantity` field
   was also renamed to `notional_budget` (it is a USDC budget, not a share
   count).
2. **Non-finite numeric poisoning** (`models.py`): `to_decimal("NaN")` /
   `"Infinity"` parsed successfully and would silently corrupt money math (NaN
   compares False against everything). `to_decimal` now rejects non-finite
   values; parse boundaries use `safe_decimal` to treat one bad field as missing
   rather than aborting a whole page/book.
3. **Zero-price division crash** (`api/clob.py`, `paper/follower.py`): an
   order-book level with price `0` caused a division-by-zero in
   `walk_for_notional`, crashing a paper-follow poll. Non-positive-price levels
   are now dropped at parse time, with a defensive guard in the walk too.

## Durability

- `PaperDB.atomic()` groups the writes for one signal (observed-signal + fill +
  position update + closure) into a single transaction, so the positions cache
  can never desync from fills/closures if the process dies mid-write.

## Testing

- Sanitized API-response fixtures live under `tests/fixtures/` with regression
  tests that parse each real response shape.
- Optional live smoke tests are marked `@pytest.mark.live` (skipped by default;
  run with `pytest -m live`). They discover a market dynamically rather than
  pinning a specific market/wallet.

## Design notes / interpretations

- **Fee/slippage buffers in paper trading** are *recorded* per fill but not
  added on top of the fill price. Rationale: real slippage is already captured
  by walking the order book for VWAP; layering a flat buffer on top would
  double-count. If the user wants an additional round-trip cushion, that is a
  deliberate modeling choice to make explicitly (not yet implemented).
- **Pagination** intentionally has no hard page cap: a silent cap would violate
  the `docs/07` rule against silently truncating pagination. Real APIs terminate
  with a short/empty page.

## Known limitations / next highest-value work

- **Rule-level forward testing (mission core).** `reverse-engineer-wallet`
  produces candidate rules (price-bucket × hour-band), and `paper-follow` tests
  *wallet copying* — but there is no command yet to forward/paper-test a
  *specific extracted rule* under conservative execution. This is the most
  valuable next feature; it needs a small design decision (rule serialization
  format + signal source) best made interactively.
- A price-history-based backtest is deliberately not built as a toy: a mid-price
  "buy below T, hold to end" backtest ignores resolution and execution and could
  mislead. Any backtest added must be explicitly labeled idealized.
