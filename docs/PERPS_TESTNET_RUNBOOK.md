# DreamDEX Perps — Testnet Runbook

Everything here runs on **Somnia Hideki Testnet (chain id 50383)** with test funds.
There are no mainnet perp markets, and Edge Lab has no mainnet perps mode.

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd perps-bridge && npm ci && cd ..      # Node >= 22 (runs TypeScript natively)
edge-lab perps --help
```

## 2. Configure (reads need nothing)

Defaults point at the official Hideki endpoints from the Perps SDK docs:

| Variable | Default |
|---|---|
| `PERPS_INDEXER_URL` | `https://hideki-dev.smk.somnia.host/v1/graphql` |
| `PERPS_RPC_URL` | `https://api.hideki2.infra.testnet.somnia.network` |
| `PERPS_WS_RPC_URL` | `wss://api.hideki2.infra.testnet.somnia.network/ws` |
| `PERPS_ACCOUNT` | *(empty)* — optional **public** address for read-only account views |
| `PERPS_MAX_ORDER_NOTIONAL` | `100` — bridge-side per-order cap in USDso |

The SDK reads the chain over WebSocket; HTTP-only environments fail with
"genesis check failed" (reported as `WS_REQUIRED`). Hideki was regenesised on
2026-09-17 on the same chain id; the defaults are the v2 (`hideki2`) endpoints.

## 3. Discover and analyse (no wallet)

```bash
edge-lab perps markets                   # 21 live markets, decimals/tick/lot/min per market
edge-lab perps scan                      # ranked Market Opportunity Assessment
edge-lab perps inspect BTC               # funding, basis, liquidity, volatility, cost, risk
edge-lab perps inspect BTC --json        # stable machine-readable output
```

## 4. Preview an order (no wallet, nothing signed)

```bash
edge-lab perps preview BTC --side long --size 0.001
edge-lab perps preview BTC --side long --size 0.001 --account 0xYourPublicAddress
```

With an account, the preview adds the official `getMaxPerpOrderSize`,
`previewPerpOrderMargin` and `previewPerpLiquidationPrice` and shows testnet
eligibility check by check.

## 5. Paper trade (default; no wallet)

```bash
edge-lab perps paper-trade BTC --side long --size 0.001
edge-lab perps paper-trade ETH --side short --size 0.02
edge-lab perps positions
edge-lab perps paper-close 1
edge-lab perps report
```

## 6. Dashboard

```bash
edge-lab perps dashboard --port 8787            # http://127.0.0.1:8787/perps
edge-lab perps dashboard --source fixture       # SIMULATED, offline
```

The dashboard previews but never submits.

## 7. Signed testnet execution — prerequisites (user action)

1. **A dedicated, throwaway testnet key.** Never a key that holds real funds.
   Do not paste it into chat or commit it. Load it from a secret manager, e.g. 1Password:
   ```bash
   export PERPS_PRIVATE_KEY="$(op read op://<vault>/<item>/private_key)"
   ```
   Alternatively put it in `perps-bridge/.env` (gitignored) — see `.env.example`.
2. **Test funds for that address** (from the DreamDEX Perps testnet docs).
   Edge Lab trades the margin of the **signer's own address**, so fund that address:
   - **STT for gas:** sign in at `app.testnet.dreamdex.io`, open **Link a Bot**,
     enter the signer's *public* address and choose "Send … for gas" / "Top up".
     Note: a linked bot can place orders against the *linked app wallet's* margin
     (the bot kit's `OWNER_ADDRESS`); Edge Lab does not use that mode — it only
     uses the link to send gas to the signer.
   - **Paper USDso:** any address can claim a one-time 1 000 USDso Perps credit
     while it holds no perp positions or orders. Claim it for the signer itself:
     ```bash
     export NETWORK=hideki-testnet TRADING_MODE=testnet
     edge-lab perps claim-voucher          # shows signer, equity and eligibility; refuses without --yes
     edge-lab perps claim-voucher --yes    # claimPerpVoucher → receipt → equity re-read → evidence JSON
     ```
     (Joining Perps Arena in the app credits the wallet you are signed in with,
     which is not the signer unless you signed in with this same key.)
   - Paper USDso cannot open positions in 1000PEPE, LIT, PUMP, VVV, ZEC, ZRO
     (`limitedBy: voucherBlocked`). BTC, ETH, SOL are fine.
3. **Verify read-only first:**
   ```bash
   export PERPS_ACCOUNT=0xYourPublicAddress
   edge-lab perps positions                         # equity, voucher, positions
   edge-lab perps preview BTC --side long --size 0.00013
   ```
   Testnet eligibility should show every check PASS except `execution_mode`.

## 8. Execute (explicit, manual)

```bash
export NETWORK=hideki-testnet TRADING_MODE=testnet    # both required
edge-lab perps execute BTC --side long --size 0.00013        # dry: prints checks, refuses without --yes
edge-lab perps execute BTC --side long --size 0.00013 --yes  # submits one IOC order
edge-lab perps receipt 0x<txHash>                            # independent receipt read
edge-lab perps report                                        # ledger + reconciled state
```

Use the market's minimum quantity (BTC: 0.00013 ≈ 11 USDso) for the first order.
Default order type is IOC with a limit 5 bps beyond the worst walked level;
`--order-type limit` rests the order instead.

What happens: write gate → fresh snapshot → signer address (derived in the
bridge) → live equity → official preview → risk decision → `--yes` → bridge
re-validation (chain id 50383, mark freshness, precision, notional cap, official
max size, voucher) → `placePerpOrder` → receipt + fills → reconciled state →
position re-read → evidence JSON in `.edge-lab/perps-evidence/`.

Hideki has no public block explorer (per the SDK chain definition), so the
evidence is the transaction hash, the receipt (status, block, gas) re-read via
RPC, the decoded fills and the MarginBank position before/after.

To close a test position, submit the opposite side for the same quantity.

## 9. Troubleshooting

| Code / symptom | Meaning | Action |
|---|---|---|
| `WRITE_REFUSED` / `PAPER_MODE` / `WRONG_NETWORK` / `SIGNER_REQUIRED` | write gate | set `NETWORK=hideki-testnet`, `TRADING_MODE=testnet`, `PERPS_PRIVATE_KEY` |
| `WRONG_CHAIN` | RPC is not 50383 | fix `PERPS_RPC_URL` |
| `official_sizing … limitedBy=collateral` | no/low USDso in the Perps account | fund and move USDso to Perps |
| `voucher_allowed … voucherBlocked` | paper USDso not allowed in this market | use BTC/ETH/SOL etc. |
| `STALE_MARK_PRICE` | mark feed stale; sizing unavailable | wait and retry |
| `IOC_NO_FILL` | book moved; IOC found nothing | re-preview; retry |
| `ISOLATED_MARKET_BLOCKED` | isolated account can only trade one market | use that market or a cross account |
| `MAX_POSITION_SIZE_EXCEEDED` | per-account cap | reduce size |
| `WS_REQUIRED` | WebSocket unreachable | check `PERPS_WS_RPC_URL` / network |
| `VOUCHER_NOT_ELIGIBLE` (`alreadyClaimed`, `notFlat`, `mainFunded`, …) | the credit cannot be claimed by this address | see the reason; claim only once, while flat |

## 10. Tests

```bash
pytest                                   # offline suite (no network, no keys)
pytest -m live tests/test_perps_live.py  # live Hideki reads + unsigned preview
PERPS_LIVE_EXECUTE=1 pytest -m live tests/test_perps_live.py   # + one signed min-size order
cd perps-bridge && npm run typecheck && npm test
```
