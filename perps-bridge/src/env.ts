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

/**
 * Accept a key with or without the `0x` prefix (MetaMask exports it bare) and
 * with surrounding whitespace. Anything that is not 32 bytes of hex fails with a
 * message that never contains the value itself.
 */
export function normalizePrivateKey(raw: string | undefined): string | undefined {
  const s = (raw ?? "").trim();
  if (!s) return undefined;
  const hex = s.startsWith("0x") || s.startsWith("0X") ? s.slice(2) : s;
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) {
    throw new BridgeError(
      "CONFIG_ERROR",
      `PERPS_PRIVATE_KEY must be 64 hex characters (optionally prefixed with 0x); got ${hex.length} characters`,
    );
  }
  return `0x${hex.toLowerCase()}`;
}

export function readEnv(): PerpsEnv {
  return {
    network: (process.env.NETWORK ?? "").toLowerCase(),
    tradingMode: (process.env.TRADING_MODE ?? "paper").toLowerCase(),
    indexerUrl: process.env.PERPS_INDEXER_URL || DEFAULT_INDEXER_URL,
    rpcUrl: process.env.PERPS_RPC_URL || DEFAULT_RPC_URL,
    wsRpcUrl: process.env.PERPS_WS_RPC_URL || DEFAULT_WS_RPC_URL,
    account: process.env.PERPS_ACCOUNT || undefined,
    privateKey: normalizePrivateKey(process.env.PERPS_PRIVATE_KEY),
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
