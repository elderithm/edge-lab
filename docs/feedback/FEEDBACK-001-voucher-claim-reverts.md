# `claimPerpVoucher` reverts for every address while `getPerpVoucherEligibility` returns `eligible: true`

| Field | Value |
|---|---|
| Area | Perps voucher (paper-USDso credit) — SDK eligibility read vs VoucherDistributor `claim()` |
| Severity | Medium — blocks the documented script/bot path to test funds; the eligibility read gives a false positive |
| Network | Somnia Hideki Testnet, chain id 50383 (RPC `https://api.hideki2.infra.testnet.somnia.network`) |
| SDK | `@somnia-chain/markets-sdk` 0.32.1 |
| First observed | 2026-10-22; re-verified 2026-11-01 at block 38511146 |

## Summary

The Perps developer docs say any address can claim the one-time 1 000 USDso Perps
credit while it holds no perp positions or orders, and to call
`getPerpVoucherEligibility` first, then `claimPerpVoucher` with the market's
`marginBank`. For every address tried, `getPerpVoucherEligibility` returns
`{ eligible: true, grantAmount: 1000e18 }`, but the distributor's `claim()`
reverts with custom error `0x3e31dcc2`. The selector is not in the SDK's error
ABIs or in public signature databases, so the SDK cannot decode it, and the
thrown message (`claim reverted: rpc eth_call failed: RPC Request failed`) reads
like a transport failure rather than a contract revert.

## Steps to reproduce (no key needed)

1. Read eligibility for any flat address, e.g. `0x…dEaD`:
   ```ts
   const bank = (await client.listPerpMarkets({ limit: 1 }))[0].marginBank; // 0x478769e1…1394
   await client.getPerpVoucherEligibility(bank, "0x000000000000000000000000000000000000dEaD");
   // -> { eligible: true, grantAmount: 1000000000000000000000n }
   ```
2. Simulate the exact call the SDK builds (`trader.buildClaimPerpVoucher({ marginBank })`
   returns `to = 0x2ACD9EFdA721450906bfE1bef3edE269636E42C4`, `data = 0x4e71d92d`, `claim()`):
   ```bash
   curl -s -X POST https://api.hideki2.infra.testnet.somnia.network \
     -H 'content-type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"from":"0x000000000000000000000000000000000000dEaD","to":"0x2ACD9EFdA721450906bfE1bef3edE269636E42C4","data":"0x4e71d92d","gas":"0x989680"},"latest"]}'
   ```
3. With a funded signer, `trader.claimPerpVoucher({ marginBank })` throws before sending.

## Expected

Either `claim()` succeeds for an address the SDK reports as eligible, or
`getPerpVoucherEligibility` returns `eligible: false` with a reason that names the
missing condition. A revert should surface as a decoded `ContractRevertError`.

## Actual

```json
{"jsonrpc":"2.0","id":1,"error":{"code":3,"message":"execution reverted","data":"0x3e31dcc2"}}
```

The same revert data is returned for a dedicated testnet signer
(`0x74dab13fd6561090fbedc477f7d5de01cf96e501`, 50 STT, no positions) and for
unrelated addresses (`0x…dEaD`, `0x1234567890abcdef1234567890abcdef12345678`). The
campaign read at the same time is active: `startsAt 1790553600`, `endsAt
1798477478`, `claimsRemaining 410497`, `budgetRemaining 410497e18`.

## Evidence

- Distributor proxy `0x2ACD9EFdA721450906bfE1bef3edE269636E42C4`, implementation
  (EIP-1967 slot) `0x9657f0fd53efc01cd108d93c835bb4b517732b43`; the selector
  `3e31dcc2` appears in the implementation bytecode.
- `getPerpVoucher` for the signer: `{ claimed: false, floor: 0, expiresAt: 0 }`.

## Workaround used

Signing in to the app with the same wallet and registering for Perps Arena
airdropped paper USDso to the wallet; it was then moved into the Perps MarginBank
with `trader.depositMargin`. Note that the airdrop was 100 USDso, while the docs
and the Arena page mention 1 000.

## Suggested fix

Expose the distributor's error in the SDK error ABI, and have
`getPerpVoucherEligibility` check the same condition `claim()` enforces (or
document that the credit is only claimable through Perps Arena).
