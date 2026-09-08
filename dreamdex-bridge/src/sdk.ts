/**
 * Build the official SomniaMarkets client from bridge env. This is the ONLY
 * place the SDK is constructed. A signer is attached only for write paths.
 */
import {
  SOMNIA_MAINNET_ADDRESSES,
  SOMNIA_TESTNET_ADDRESSES,
  SOMNIA_TESTNET_PRICE_FEED,
  SomniaMarkets,
} from "@somnia-chain/markets-sdk";
import type { SomniaMarketsConfig } from "@somnia-chain/markets-sdk";
import { type BridgeEnv, BridgeError, assertWriteAllowed, chainFor } from "./env.ts";

export function buildExchange(env: BridgeEnv, opts: { needSigner?: boolean } = {}): SomniaMarkets {
  // Evaluate the write gate BEFORE anything else so paper-mode / mainnet-disabled
  // refusals surface with the correct reason regardless of other config.
  if (opts.needSigner) {
    assertWriteAllowed(env); // throws unless mode/network/gate/signer all permit
  }
  if (!env.indexerUrl) {
    throw new BridgeError("CONFIG_ERROR", "INDEXER_URL is required for live DreamDEX reads");
  }
  const config: SomniaMarketsConfig = {
    indexerUrl: env.indexerUrl,
    chain: chainFor(env.network),
    // Per-chain contract addresses are required for on-chain reads/writes
    // (getMarketOnchain, place-order); the SDK does not derive them from chain.
    addresses: env.network === "mainnet" ? SOMNIA_MAINNET_ADDRESSES : SOMNIA_TESTNET_ADDRESSES,
    ...(env.wsRpcUrl ? { wsRpcUrl: env.wsRpcUrl } : {}),
    ...(env.network === "testnet" ? { priceFeed: SOMNIA_TESTNET_PRICE_FEED } : {}),
  };
  if (opts.needSigner) {
    config.privateKey = env.privateKey as `0x${string}`;
  }
  return new SomniaMarkets(config);
}
