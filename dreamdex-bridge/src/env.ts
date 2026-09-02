/**
 * Bridge configuration from environment. No secrets are logged or echoed.
 * Mode/network gating lives here so a mainnet write can never be inferred.
 */
import { somniaMainnet, somniaShannon } from "@somnia-chain/markets-sdk/chains";
import type { Chain } from "viem";

export type Network = "testnet" | "mainnet";
export type TradingMode = "paper" | "testnet" | "mainnet";

export interface BridgeEnv {
  network: Network;
  tradingMode: TradingMode;
  indexerUrl: string;
  wsRpcUrl?: string;
  rpcUrl?: string;
  privateKey?: string;
  enableMainnetTrading: boolean;
}

export function readEnv(): BridgeEnv {
  const network = (process.env.NETWORK ?? "testnet").toLowerCase() as Network;
  const tradingMode = (process.env.TRADING_MODE ?? "paper").toLowerCase() as TradingMode;
  if (network !== "testnet" && network !== "mainnet") {
    throw new BridgeError("CONFIG_ERROR", `invalid NETWORK '${network}' (want testnet|mainnet)`);
  }
  if (!["paper", "testnet", "mainnet"].includes(tradingMode)) {
    throw new BridgeError("CONFIG_ERROR", `invalid TRADING_MODE '${tradingMode}'`);
  }
  return {
    network,
    tradingMode,
    indexerUrl: process.env.INDEXER_URL ?? "",
    wsRpcUrl: process.env.WS_RPC_URL || undefined,
    rpcUrl: process.env.RPC_URL || undefined,
    privateKey: process.env.PRIVATE_KEY || undefined,
    enableMainnetTrading: (process.env.ENABLE_MAINNET_TRADING ?? "false").toLowerCase() === "true",
  };
}

export function chainFor(network: Network): Chain {
  return network === "mainnet" ? (somniaMainnet as Chain) : (somniaShannon as Chain);
}

/**
 * Assert that writing is permitted for this env. Reads never call this.
 * Mainnet requires the explicit triple gate; testnet requires a signer.
 */
export function assertWriteAllowed(env: BridgeEnv): void {
  if (env.tradingMode === "paper") {
    throw new BridgeError("PAPER_MODE", "TRADING_MODE=paper never submits transactions");
  }
  if (env.network === "mainnet" || env.tradingMode === "mainnet") {
    const gated = env.network === "mainnet" && env.tradingMode === "mainnet" && env.enableMainnetTrading;
    if (!gated) {
      throw new BridgeError(
        "MAINNET_DISABLED",
        "mainnet trading requires NETWORK=mainnet AND TRADING_MODE=mainnet AND ENABLE_MAINNET_TRADING=true",
      );
    }
  }
  if (!env.privateKey) {
    throw new BridgeError("SIGNER_REQUIRED", "a signer (PRIVATE_KEY) is required to submit transactions");
  }
}

export class BridgeError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
  }
}
