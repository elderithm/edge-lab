# DreamDEX Perps Edge Lab — Demo Script (2–3 minutes)

## Before recording

```bash
pip install -e ".[dev]" && (cd perps-bridge && npm ci)
edge-lab perps scan >/dev/null                         # confirm live reads work
rm -f .edge-lab/perps-paper.db                         # clean paper ledger for the demo
edge-lab perps dashboard --port 8787 --cache-ttl 120 &  # open http://127.0.0.1:8787/perps
```

Have two terminal panes and the browser ready. Use live data; if Hideki is
unreachable, record with `--source fixture` and say "simulated fixture" on camera
(the UI labels it SIMULATED FIXTURE).

## Script

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:15 | README / repo | "Edge Lab started as a Polymarket research tool built to falsify weak trading claims before risking capital. We extended it to DreamDEX Event Contracts, and for this bounty to DreamDEX Perps on Somnia Hideki testnet." |
| 0:15–0:35 | `edge-lab perps markets` | "Through the official Somnia Markets SDK we discover all live perp markets. Each has its own base decimals, tick, lot and minimum size — read from the chain, never hardcoded." |
| 0:35–1:00 | Dashboard `/perps` overview | "For every market: mark, index, basis, funding per window and annualized, spread, depth near mid, and the round-trip cost of a 100 USDso probe. Each market gets one documented category — REVIEW, WATCH, HIGH_EXECUTION_COST and so on. Missing data is shown as missing." |
| 1:00–1:25 | Inspect BTC dialog | "Inside a market: the order book, funding normalized from the on-chain window, realized volatility from gap-free candles, and a labelled liquidation estimate. Expected edge says NOT_ESTIMATED: funding and basis are observations, not free money." |
| 1:25–1:50 | Preview in dialog, then `edge-lab perps preview BTC --side long --size 0.001 --account 0x…` | "An order preview walks the live book for expected price, slippage and margin, then runs every risk check. With an account it adds the protocol's own max order size, margin and liquidation previews. Effective leverage is capped at one times." |
| 1:50–2:10 | `edge-lab perps paper-trade BTC --side long --size 0.001`, `positions`, `report` | "Paper trading needs no wallet. Fills are simulated from the live book and labelled as such, marked to the protocol mark price, with funding accrued from the cumulative index." |
| 2:10–2:35 | `edge-lab perps execute … --yes`, `receipt 0x…`, dashboard Testnet orders | *If verified:* "On testnet, execution requires the Hideki network, testnet mode, a dedicated signer, every risk check, and an explicit yes. The bridge re-checks chain id and official sizing before signing. We then read the receipt, decode the fills and re-read the position — a submission is never shown as a fill by itself." *If not verified:* show `execute` refusing with its gate reasons and say "Signed execution is gated and implemented; this recording shows the gate." |
| 2:35–2:50 | Dashboard overview | "DreamDEX Perps Edge Lab: explainable perpetual-futures intelligence and risk-aware execution — measure the cost and the risk before any capital moves." |

## Notes

- Never show a private key or `.env` on screen.
- Do not describe REVIEW markets as opportunities to profit.
- If a transaction is shown, show its hash and the `receipt` output.
