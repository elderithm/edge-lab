/** Offline unit tests for the bridge's exact-integer helpers and write gate (`npm test`). */
import assert from "node:assert/strict";
import { test } from "node:test";
import type { PerpMarket } from "@somnia-chain/markets-sdk";
import { claimVoucher, notionalRaw, plain, precisionProblems } from "../src/commands.ts";
import { BridgeError, assertWriteAllowed, type PerpsEnv } from "../src/env.ts";

const BTC = { tickSize: "100000000000000000", lotSize: "1000", minQuantity: "13000", baseDecimals: 8, quoteDecimals: 18 } as unknown as PerpMarket;

const ENV: PerpsEnv = {
  network: "hideki-testnet",
  tradingMode: "testnet",
  indexerUrl: "x",
  rpcUrl: "x",
  wsRpcUrl: "x",
  privateKey: "0x" + "1".repeat(64),
  maxOrderNotional: "100",
};

test("precision: tick, lot and min quantity are enforced exactly", () => {
  assert.deepEqual(precisionProblems(BTC, 84600n * 10n ** 18n, 100000n), []);
  assert.match(precisionProblems(BTC, 84600n * 10n ** 18n + 1n, 100000n).join(), /tickSize/);
  assert.match(precisionProblems(BTC, 84600n * 10n ** 18n, 100001n).join(), /lotSize/);
  assert.match(precisionProblems(BTC, 84600n * 10n ** 18n, 1000n).join(), /minQuantity/);
});

test("notional uses the market's own base decimals", () => {
  // 0.001 BTC (1e5 raw at 8dp) * 84600 = 84.6 USDso (18dp)
  assert.equal(notionalRaw(BTC, 84600n * 10n ** 18n, 100000n), 846n * 10n ** 17n);
  const near = { ...BTC, baseDecimals: 24 } as unknown as PerpMarket;
  assert.equal(notionalRaw(near, 2n * 10n ** 18n, 10n ** 24n), 2n * 10n ** 18n);
});

test("plain() stringifies nested bigints", () => {
  assert.deepEqual(plain({ a: 1n, b: [2n, { c: 3n }] }), { a: "1", b: ["2", { c: "3" }] });
});

test("write gate: mode, network and signer", () => {
  assert.doesNotThrow(() => assertWriteAllowed(ENV));
  const code = (e: PerpsEnv) => {
    try {
      assertWriteAllowed(e);
      return "OK";
    } catch (err) {
      return (err as BridgeError).code;
    }
  };
  assert.equal(code({ ...ENV, tradingMode: "paper" }), "PAPER_MODE");
  assert.equal(code({ ...ENV, tradingMode: "mainnet" }), "PAPER_MODE");
  assert.equal(code({ ...ENV, network: "testnet" }), "WRONG_NETWORK");
  assert.equal(code({ ...ENV, network: "mainnet" }), "WRONG_NETWORK");
  assert.equal(code({ ...ENV, privateKey: undefined }), "SIGNER_REQUIRED");
});

test("claim-voucher refuses without explicit confirmation before touching the SDK", async () => {
  const untouchable = new Proxy({}, { get: () => assert.fail("SDK must not be touched") }) as never;
  await assert.rejects(claimVoucher(untouchable, ENV, {}), (e: unknown) => e instanceof BridgeError && e.code === "NOT_CONFIRMED");
  await assert.rejects(claimVoucher(untouchable, ENV, { confirmed: "yes" }), /confirmed=true/);
});
