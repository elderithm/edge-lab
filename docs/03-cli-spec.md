# CLI Specification

Executable name:

```text
edge-lab
```

## Global behavior

Useful common flags:

```text
--json
--timeout <seconds>
--verbose
```

Exit codes:

- `0`: success
- `1`: user/data/runtime error
- `2`: invalid CLI usage

Commands must avoid stack traces for expected user-facing failures unless `--verbose` is enabled.

## `geo`

Checks the official geoblock status endpoint and prints the response in a human-readable form.

```bash
edge-lab geo
edge-lab geo --json
```

This command is informational only and must not offer bypass instructions.

## `market <slug>`

Displays market metadata, outcome token IDs, status, and current readable price/order-book summary when available.

```bash
edge-lab market <market-slug>
```

## `analyze-wallet <address>`

Fetch public activity and calculate behavior summaries.

```bash
edge-lab analyze-wallet 0x... \
  --max-records 5000 \
  --utc-offset 9
```

Output should include, where supported by the data:

- retrieved record count;
- time range;
- activity by hour;
- activity by weekday;
- BUY vs SELL counts;
- market/event concentration;
- outcome/side concentration;
- entry-price buckets;
- size/notional distribution;
- limitations/incomplete-data warnings.

## `export-wallet <address>`

```bash
edge-lab export-wallet 0x... \
  --max-records 5000 \
  --output activity.csv
```

CSV should use stable headers and ISO-8601 UTC timestamps.

## `arb <market-slug>`

Analyze a binary market for simultaneous executable YES/NO purchase cost.

```bash
edge-lab arb <market-slug> \
  --notional 10 \
  --fee-buffer-bps 50 \
  --slippage-buffer-bps 50 \
  --min-edge-bps 25
```

Do not calculate edge from top-of-book prices alone when requested size exceeds top-level liquidity. Walk the asks and calculate VWAP/executable quantity.

Report:

- raw top-of-book sum;
- size-aware simulated YES cost;
- size-aware simulated NO cost;
- configured buffers;
- estimated net edge;
- maximum size supportable at the stated edge if feasible;
- explicit note that this is an observation, not a real fill.

## `scan-arbs`

```bash
edge-lab scan-arbs \
  --limit 100 \
  --top 20 \
  --notional 10 \
  --min-edge-bps 25
```

Fetch active binary markets, calculate size-aware paper edge, and rank candidates.

Failures for individual markets should not abort the full scan; report skipped/error counts.

## `paper-follow <address>`

Forward paper-trading loop.

```bash
edge-lab paper-follow 0x... \
  --paper-usdc 10 \
  --max-age 120 \
  --max-drift-bps 300 \
  --poll 5
```

Rules are defined in `05-paper-trading.md`.

## `paper-report`

```bash
edge-lab paper-report
edge-lab paper-report --run-id <id>
edge-lab paper-report --json
```

Report realized and mark-to-market figures separately.

## `reverse-engineer-wallet <address>`

Primary research command for extracting repeatable behavior patterns.

```bash
edge-lab reverse-engineer-wallet 0x... \
  --max-records 5000 \
  --utc-offset 9 \
  --output-dir reports/wallet-0x...
```

Minimum outputs:

- `summary.json`
- `trades.csv`
- `patterns.csv`
- `report.md`

See `04-wallet-reverse-engineering.md`.
