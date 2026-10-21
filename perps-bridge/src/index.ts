/**
 * DreamDEX Perps bridge CLI: `node src/index.ts <command> '<jsonParams>'`.
 *
 * Calls the official @somnia-chain/markets-sdk (Hideki Testnet) and writes one
 * JSON object to stdout. Errors become `{ "error": { code, message } }` with a
 * non-zero exit. Secrets are never echoed.
 */
import { SomniaMarketsError } from "@somnia-chain/markets-sdk";
import { BridgeError, HIDEKI_CHAIN_ID, readEnv } from "./env.ts";
import { buildMarkets } from "./sdk.ts";
import {
  account,
  candles,
  market,
  markets,
  orderbook,
  placeOrder,
  plain,
  position,
  previewOrder,
  receipt,
  signer,
  snapshot,
} from "./commands.ts";

type AnyRec = Record<string, unknown>;

async function readParams(): Promise<AnyRec> {
  const inline = process.argv[3];
  if (inline) return JSON.parse(inline) as AnyRec;
  return {};
}

// Contract revert names (from the docs' pitfalls list) -> stable bridge codes.
const REVERTS: [RegExp, string][] = [
  [/ImmediateOrCancelNoFill/, "IOC_NO_FILL"],
  [/InsufficientCollateral/, "INSUFFICIENT_COLLATERAL"],
  [/IsolatedMarketBlocked/, "ISOLATED_MARKET_BLOCKED"],
  [/MaxPositionSizeExceeded/, "MAX_POSITION_SIZE_EXCEEDED"],
  [/genesis check failed/i, "WS_REQUIRED"],
];

export function mapErrorCode(err: unknown): string {
  if (err instanceof BridgeError) return err.code;
  const msg = String((err as Error)?.message ?? err);
  for (const [re, code] of REVERTS) if (re.test(msg)) return code;
  if (err instanceof SomniaMarketsError) return err.name || "SDK_ERROR";
  if (/timeout|network|fetch|ECONN|ENOTFOUND|socket/i.test(msg)) return "RPC_ERROR";
  return (err as { name?: string })?.name || "BRIDGE_ERROR";
}

async function main(): Promise<void> {
  const cmd = process.argv[2];
  const env = readEnv();
  const params = await readParams();
  let result: AnyRec;
  switch (cmd) {
    case "health":
      result = { ok: true, chainId: HIDEKI_CHAIN_ID, network: env.network, tradingMode: env.tradingMode };
      break;
    case "markets":
      result = await markets(buildMarkets(env), params);
      break;
    case "market":
      result = await market(buildMarkets(env), params);
      break;
    case "orderbook":
      result = await orderbook(buildMarkets(env), params);
      break;
    case "candles":
      result = await candles(buildMarkets(env), params);
      break;
    case "account":
      result = await account(buildMarkets(env), env, params);
      break;
    case "position":
      result = await position(buildMarkets(env), env, params);
      break;
    case "preview-order":
      result = await previewOrder(buildMarkets(env), env, params); // no signer
      break;
    case "place-order":
      result = await placeOrder(buildMarkets(env, { needSigner: true }), env, params);
      break;
    case "snapshot":
      result = await snapshot(buildMarkets(env), params);
      break;
    case "signer":
      result = signer(env);
      break;
    case "receipt":
      result = await receipt(env, params);
      break;
    default:
      throw new BridgeError(
        "CONFIG_ERROR",
        `unknown command '${cmd}' (health|markets|market|orderbook|candles|account|position|preview-order|place-order|receipt|snapshot|signer)`,
      );
  }
  emit(result, 0);
}

/** Write JSON and force-exit once flushed (the SDK keeps sockets open). */
function emit(obj: unknown, code: number): void {
  process.stdout.write(JSON.stringify(plain(obj)), () => process.exit(code));
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  emit({ error: { code: mapErrorCode(err), message: message.slice(0, 600) } }, 1);
});
