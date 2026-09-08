/**
 * DreamDEX bridge CLI: `node src/index.ts <command> '<jsonParams>'`.
 *
 * Reads a command + JSON params (argv[3] or stdin), calls the official
 * @somnia-chain/markets-sdk through the command handlers, and writes a single
 * JSON object to stdout. Errors become `{ "error": { code, message } }` with a
 * non-zero exit. Secrets are never echoed.
 */
import { SomniaMarketsError } from "@somnia-chain/markets-sdk";
import { BridgeError, readEnv } from "./env.ts";
import { buildExchange } from "./sdk.ts";
import { discover, market, orderbook, placeOrder, previewOrder, price } from "./commands.ts";

type AnyRec = Record<string, unknown>;

async function readParams(): Promise<AnyRec> {
  const inline = process.argv[3];
  if (inline) return JSON.parse(inline) as AnyRec;
  if (process.stdin.isTTY) return {};
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? (JSON.parse(raw) as AnyRec) : {};
}

function mapErrorCode(err: unknown): string {
  if (err instanceof BridgeError) return err.code;
  if (err instanceof SomniaMarketsError) return err.name || "SDK_ERROR";
  const name = (err as { name?: string })?.name ?? "";
  if (/timeout|network|fetch|ECONN|ENOTFOUND/i.test(String((err as Error)?.message))) return "RPC_ERROR";
  return name || "BRIDGE_ERROR";
}

async function main(): Promise<void> {
  const cmd = process.argv[2];
  const env = readEnv();
  const params = await readParams();

  let result: AnyRec;
  switch (cmd) {
    case "discover":
      result = await discover(buildExchange(env), params);
      break;
    case "market":
      result = await market(buildExchange(env), params);
      break;
    case "orderbook":
      result = await orderbook(buildExchange(env), params);
      break;
    case "price":
      result = await price(buildExchange(env), params);
      break;
    case "preview-order":
      result = await previewOrder(buildExchange(env), params); // no signer
      break;
    case "place-order":
      result = await placeOrder(buildExchange(env, { needSigner: true }), env, params);
      break;
    case "health":
      result = { ok: true, network: env.network, tradingMode: env.tradingMode, sdk: "@somnia-chain/markets-sdk" };
      break;
    default:
      throw new BridgeError(
        "CONFIG_ERROR",
        `unknown command '${cmd}' (discover|market|orderbook|price|preview-order|place-order|health)`,
      );
  }
  emit(result, 0);
}

/**
 * Write the JSON result and force-exit once it is flushed. The SDK keeps
 * chain/price-feed sockets open, so a one-shot command would otherwise hang the
 * process until its caller times out; a one-shot request/response must exit.
 */
function emit(obj: unknown, code: number): void {
  process.stdout.write(JSON.stringify(obj), () => process.exit(code));
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  emit({ error: { code: mapErrorCode(err), message } }, 1);
});
