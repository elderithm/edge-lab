# dreamdex-bridge

A **thin transport/execution bridge** between the Python Edge Lab core and the
official `@somnia-chain/markets-sdk` (DreamDEX Event Contracts on Somnia).

It contains **no** probability, edge, risk, or strategy logic — that all lives in
Python. This layer only:

1. discovers live BTC/ETH Event Contracts,
2. reads current on-chain market status,
3. reads live order books,
4. reads the underlying price + recent closes (raw; Python computes volatility),
5. submits Shannon Testnet orders when credentials are configured.

## Usage

```bash
npm install
cp .env.example .env    # set INDEXER_URL, NETWORK, TRADING_MODE, (PRIVATE_KEY for writes)

# one command per invocation; JSON params as argv[3] or on stdin; JSON on stdout
node src/index.ts health
node src/index.ts discover '{"assets":["BTC","ETH"]}'
node src/index.ts market   '{"marketId":"0x…"}'
node src/index.ts orderbook '{"marketId":"0x…"}'
node src/index.ts price    '{"asset":"BTC"}'
node src/index.ts place-order '{"marketId":"0x…","side":"UP","size":5,"price":0.6}'
```

The Python `DreamdexAdapter` invokes these commands as a subprocess. Node ≥ 22 is
required (the bridge runs TypeScript natively via type-stripping); `npm run
typecheck` runs `tsc --noEmit`.

## Safety

- `TRADING_MODE=paper` (default) refuses all writes.
- Testnet writes require `TRADING_MODE=testnet` + a `PRIVATE_KEY`.
- Mainnet writes require `NETWORK=mainnet` **and** `TRADING_MODE=mainnet` **and**
  `ENABLE_MAINNET_TRADING=true` — never inferred.
- `place-order` re-reads on-chain status immediately before signing and refuses
  anything but a `Trading` market.
- Never commit a real `.env` or private key. Use a dedicated hackathon testnet
  wallet with minimal funds.

Errors are returned as `{"error":{"code","message"}}` with a non-zero exit; no
secrets or environment values are echoed.
