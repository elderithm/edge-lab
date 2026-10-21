/**
 * Perps bridge configuration from environment. No secrets are logged or echoed.
 *
 * Perps lives on Somnia Hideki Testnet only (there are no mainnet perp markets),
 * so the write gate is: NETWORK=hideki-testnet AND TRADING_MODE=testnet AND a
 * dedicated PERPS_PRIVATE_KEY. Reads never call the gate.
 */
export const HIDEKI_CHAIN_ID = 50383;
export const DEFAULT_INDEXER_URL = "https://hideki-dev.smk.somnia.host/v1/graphql";
export const DEFAULT_RPC_URL = "https://api.hideki2.infra.testnet.somnia.network";
export const DEFAULT_WS_RPC_URL = "wss://api.hideki2.infra.testnet.somnia.network/ws";

export type TradingMode = "paper" | "testnet";

export interface PerpsEnv {
  network: string;
  tradingMode: string;
  indexerUrl: string;
  rpcUrl: string;
  wsRpcUrl: string;
  account?: string;
  privateKey?: string;
  maxOrderNotional: string; // human quote units, decimal string
}

export function readEnv(): PerpsEnv {
  return {
    network: (process.env.NETWORK ?? "").toLowerCase(),
    tradingMode: (process.env.TRADING_MODE ?? "paper").toLowerCase(),
    indexerUrl: process.env.PERPS_INDEXER_URL || DEFAULT_INDEXER_URL,
    rpcUrl: process.env.PERPS_RPC_URL || DEFAULT_RPC_URL,
    wsRpcUrl: process.env.PERPS_WS_RPC_URL || DEFAULT_WS_RPC_URL,
    account: process.env.PERPS_ACCOUNT || undefined,
    privateKey: process.env.PERPS_PRIVATE_KEY || undefined,
    maxOrderNotional: process.env.PERPS_MAX_ORDER_NOTIONAL || "100",
  };
}

/** Throw unless this env may submit a Hideki testnet transaction. */
export function assertWriteAllowed(env: PerpsEnv): void {
  if (env.tradingMode !== "testnet") {
    throw new BridgeError("PAPER_MODE", `TRADING_MODE=${env.tradingMode || "paper"} never submits transactions`);
  }
  if (env.network !== "hideki-testnet") {
    throw new BridgeError("WRONG_NETWORK", `perps writes require NETWORK=hideki-testnet (got '${env.network}')`);
  }
  if (!env.privateKey) {
    throw new BridgeError("SIGNER_REQUIRED", "a dedicated testnet signer (PERPS_PRIVATE_KEY) is required");
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
