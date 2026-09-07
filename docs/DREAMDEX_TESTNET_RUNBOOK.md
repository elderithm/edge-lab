# DreamDEX Testnet Execution Runbook (②)

How to submit a **real Somnia Shannon Testnet** order with DreamDEX Edge Lab.
This step needs your own **dedicated hackathon testnet wallet** — it is the only
part of the flow that cannot be run without wallet credentials.

> Safety: use a throwaway testnet-only key with minimal funds. Never a main
> wallet seed. Never commit the key. The tool reads it only from the environment;
> Python never stores it — it is inherited by the Node bridge subprocess.

## What is already verified without a wallet

The whole write path up to (but not including) the signature is verified live:

```bash
export INDEXER_URL="https://dev.smk.somnia.host/v1/graphql" NETWORK=testnet TRADING_MODE=paper
# resolve pool + on-chain status + build the exact raw params, NO signing, NO wallet:
edge-lab dreamdex preview <marketId> --side UP --price 0.55 --size 5
# -> { "wouldSubmit": true, "status": "Trading", "binarySide": "BUY_YES",
#      "priceRaw": "550000", "quantityRaw": "5000000", ... }
```

`preview` proves pool resolution, the mandatory on-chain status check, and the
raw price/quantity encoding are correct on a live market. Only the signature
remains.

## Prerequisites for a signed order

1. A dedicated **Shannon testnet** wallet (a fresh EOA). Export its private key
   to your shell only (never a file in the repo):
   ```bash
   export PRIVATE_KEY=0x<your-testnet-only-key>
   ```
2. **Gas**: fund it with test STT from the Somnia Shannon faucet
   (see the Somnia developer docs / faucet).
3. **Collateral**: obtain the market's test collateral token (e.g. `tUSDC`) for
   the buy-side escrow. The order auto-approves the escrow (`autoApprove`).
4. A market that is actually **`Trading`** with resting liquidity. DreamDEX rolls
   short-window markets continuously; pick a current one from `dreamdex scan`.

## Submit

```bash
export INDEXER_URL="https://dev.smk.somnia.host/v1/graphql"
export NETWORK=testnet
export TRADING_MODE=testnet        # <- enables writes (still needs the signer)
export PRIVATE_KEY=0x...           # dedicated testnet key

# 1) Find a live TRADING market
edge-lab dreamdex scan --assets BTC,ETH

# 2) Rehearse the exact order (no signing)
edge-lab dreamdex preview <marketId> --side UP --price 0.55 --size 5

# 3) Submit for real — requires explicit --yes confirmation
edge-lab dreamdex execute <marketId> --size 5 --yes
```

`execute` re-runs the model + **risk engine**, prints the proposal and every risk
check, re-reads on-chain status immediately before signing, and only then submits
through the SDK's low-level trader. The result includes the `orderId` / tx info.

A limit order that does not cross rests on the book (a valid submission, no
immediate fill). That already demonstrates "testnet execution works through
DreamDEX" (spec §22, §58).

## Settlement

When the market later resolves, record the paper equivalent and/or read the
on-chain resolution:

```bash
edge-lab dreamdex settle <paperTradeId> UP|DOWN|VOID   # paper P&L bookkeeping
```

On-chain redemption/claim of a won testnet position is optional for the MVP
(spec §30, "if implemented") and is not wired yet.

## Gates (already enforced, cannot be bypassed)

- `TRADING_MODE=paper` → refuses all writes (`PAPER_MODE`).
- `TRADING_MODE=testnet` without `PRIVATE_KEY` → `SIGNER_REQUIRED`.
- Mainnet requires `NETWORK=mainnet` **and** `TRADING_MODE=mainnet` **and**
  `ENABLE_MAINNET_TRADING=true` — never inferred (`MAINNET_DISABLED`).
- Non-`Trading` market → `MARKET_NOT_TRADING` (checked immediately before signing).
