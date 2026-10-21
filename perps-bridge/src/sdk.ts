/**
 * Build the official SomniaMarkets client for Hideki. The ONLY place the SDK is
 * constructed. A signer is attached only for write paths, after the gate.
 */
import { SOMNIA_HIDEKI_TESTNET_ADDRESSES, SomniaMarkets } from "@somnia-chain/markets-sdk";
import type { SomniaMarketsConfig } from "@somnia-chain/markets-sdk";
import { hidekiTestnet } from "@somnia-chain/markets-sdk/chains";
import { type PublicClient, createPublicClient, defineChain, http } from "viem";
import { type PerpsEnv, assertWriteAllowed } from "./env.ts";

function chainFor(env: PerpsEnv) {
  return defineChain({
    ...hidekiTestnet,
    rpcUrls: { default: { http: [env.rpcUrl], webSocket: [env.wsRpcUrl] } },
  });
}

export function buildMarkets(env: PerpsEnv, opts: { needSigner?: boolean } = {}): SomniaMarkets {
  if (opts.needSigner) assertWriteAllowed(env); // gate before anything else
  const config: SomniaMarketsConfig = {
    chain: chainFor(env),
    indexerUrl: env.indexerUrl,
    addresses: SOMNIA_HIDEKI_TESTNET_ADDRESSES,
    wsRpcUrl: env.wsRpcUrl,
  };
  if (opts.needSigner) config.privateKey = env.privateKey as `0x${string}`;
  return new SomniaMarkets(config);
}

/** Plain HTTP client for chain-id checks and receipts (no SDK state needed). */
export function buildPublicClient(env: PerpsEnv): PublicClient {
  return createPublicClient({ chain: chainFor(env), transport: http(env.rpcUrl, { timeout: 20_000 }) }) as PublicClient;
}
