/**
 * DreamDEX transport/execution commands. This layer ONLY moves data in/out of
 * the official SDK and normalizes it to plain JSON. No probability, edge, risk,
 * or strategy logic lives here — that is all in the Python core.
 *
 * All reads use the low-level client's one-shot / live-filtered methods
 * (`listLiveBinaryMarkets`, `getMarket`, `getMarketOnchain`, `getBinaryOrderBook`)
 * — never `loadMarkets()`, which fetches the entire (huge, rolling) registry.
 */
import type { SomniaMarkets } from "@somnia-chain/markets-sdk";
import { type BridgeEnv, BridgeError } from "./env.ts";

const SUPPORTED_ASSETS = new Set(["BTC", "ETH"]);
const RAW6 = 1_000_000; // binary pools use 6 decimals (DECIMALS)

// getMarketOnchain().status is the numeric contract enum, not a string.
const ONCHAIN_STATUS = ["Listed", "Trading", "Locked", "Settling", "Resolved", "Voided", "Finalized"];

function onchainStatusStr(v: unknown): string | null {
  const n = Number(v);
  if (Number.isInteger(n) && n >= 0 && n < ONCHAIN_STATUS.length) return ONCHAIN_STATUS[n];
  return typeof v === "string" && v ? v : null;
}

type AnyRec = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function human6(raw: unknown): number {
  return Number(raw as bigint | number | string) / RAW6;
}

function windowLabel(tradingStart: number | null, expiry: number | null): string | null {
  if (tradingStart === null || expiry === null) return null;
  const secs = expiry - tradingStart;
  if (secs <= 0) return null;
  if (secs === 900) return "15m";
  if (secs === 3600) return "1h";
  if (secs === 60) return "1m";
  const mins = Math.round(secs / 60);
  return mins >= 1 ? `${mins}m` : `${secs}s`;
}

function marketRow(m: AnyRec, poolOverride?: unknown): AnyRec {
  const tradingStart = num(m.tradingStart);
  const expiry = num(m.expiry);
  const asset = String(m.asset ?? "");
  const win = windowLabel(tradingStart, expiry);
  const pool = poolOverride ?? m.poolAddress ?? null;
  const expIso = expiry ? new Date(expiry * 1000).toISOString().slice(11, 19) : "?";
  return {
    venue: "dreamdex",
    marketId: String(m.marketId ?? "").toLowerCase(),
    asset,
    symbol: `${asset}-${win ?? "?"}@${expIso}`,
    status: String(m.status ?? "Unknown"),
    tradingStart,
    expiry,
    poolAddress: pool ? String(pool) : null,
    nonce: m.nonce != null ? String(m.nonce) : null,
    window: win,
  };
}

/** List currently-live BTC/ETH Event Contracts (server-side filtered). */
export async function discover(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const assets = new Set(
    (Array.isArray(params.assets) ? (params.assets as string[]) : [...SUPPORTED_ASSETS]).map((a) =>
      a.toUpperCase(),
    ),
  );
  const limit = num(params.limit) ?? 100;
  const live = (await exchange.client.listLiveBinaryMarkets({ limit })) as unknown as AnyRec[];
  const markets = live
    .filter((m) => assets.has(String(m.asset ?? "").toUpperCase()) && String(m.status) === "Trading")
    .map((m) => marketRow(m));
  return { source: "LIVE_DREAMDEX", markets };
}

async function getMarketRowOrThrow(exchange: SomniaMarkets, marketId: string): Promise<AnyRec> {
  const row = (await exchange.client.getMarket(marketId)) as unknown as AnyRec | null;
  if (!row || !row.marketId) throw new BridgeError("MARKET_NOT_FOUND", `no market with marketId ${marketId}`);
  return row;
}

/** Fresh on-chain market detail — status + opening reference. Call before writes. */
export async function market(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  if (!marketId) throw new BridgeError("CONFIG_ERROR", "marketId is required");
  const row = await getMarketRowOrThrow(exchange, marketId);
  const onchain = (await exchange.client.getMarketOnchain(marketId as `0x${string}`)) as unknown as AnyRec;
  let openingReference: number | null = null;
  try {
    const res = (await exchange.client.getMarketResolution(marketId)) as unknown as AnyRec;
    openingReference = num(res?.openingAnswer ?? res?.openingPrice ?? null);
  } catch {
    openingReference = null; // opening question may not be answered yet
  }
  return {
    source: "LIVE_DREAMDEX",
    ...marketRow(row),
    // on-chain (numeric enum) truth overrides possibly-lagging indexer status
    status: onchainStatusStr(onchain.status) ?? String(row.status),
    voided: Boolean(onchain.voided ?? false),
    resolvedAtTimestamp: num(onchain.resolvedAtTimestamp),
    openingReference,
  };
}

/** Executable Up/Down books via one on-chain read of the market's current pool. */
export async function orderbook(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  const depth = num(params.depth) ?? 25;
  if (!marketId) throw new BridgeError("CONFIG_ERROR", "marketId is required");
  const row = await getMarketRowOrThrow(exchange, marketId);
  const pool = String(row.poolAddress ?? "");
  if (!pool) throw new BridgeError("MARKET_NOT_FOUND", `market ${marketId} has no bound pool`);
  const book = (await exchange.client.getBinaryOrderBook(pool as `0x${string}`, { depth })) as unknown as AnyRec;
  const levels = (side: unknown): [number, number][] =>
    Array.isArray(side) ? side.map((l: AnyRec) => [human6(l.price), human6(l.size)] as [number, number]) : [];
  return {
    source: "LIVE_DREAMDEX",
    marketId: marketId.toLowerCase(),
    capturedAt: Math.floor(Date.now() / 1000),
    up: { asks: levels(book.yesAsks), bids: levels(book.yesBids) },
    down: { asks: levels(book.noAsks), bids: levels(book.noBids) },
  };
}

/** Underlying price + recent price ticks (raw; Python computes volatility). */
export async function price(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const asset = String(params.asset ?? "").toUpperCase();
  const limit = num(params.limit) ?? 40;
  if (!asset) throw new BridgeError("CONFIG_ERROR", "asset is required (e.g. BTC)");
  const now = Math.floor(Date.now() / 1000);
  const live = (await exchange.client.fetchPrice(asset)) as unknown as AnyRec | null;
  if (!live || num(live.price) === null) throw new BridgeError("STALE_PRICE_DATA", `no live price for ${asset}`);
  let closes: [number, number][] = [];
  try {
    const hist = (await exchange.client.fetchPriceHistory(asset, { limit })) as unknown as AnyRec[];
    closes = hist
      .map((p) => [num(p.blockTimestamp ?? p.timestamp ?? p.ts), num(p.price)] as [number | null, number | null])
      .filter((c): c is [number, number] => c[0] !== null && c[1] !== null && c[1] > 0);
    closes.sort((a, b) => a[0] - b[0]);
  } catch {
    closes = [];
  }
  return {
    source: "dreamdex-pricefeed",
    asset,
    price: num(live.price),
    timestamp: num(live.blockTimestamp) ?? now,
    receivedAt: now,
    intervalSeconds: 0, // irregular ticks; Python uses the per-point timestamps
    closes,
  };
}

/**
 * Submit a Shannon Testnet order via the low-level trader. Re-reads on-chain
 * status immediately before signing and refuses anything but a TRADING market.
 * Never called in paper mode.
 */
export async function placeOrder(exchange: SomniaMarkets, env: BridgeEnv, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  const side = String(params.side ?? "").toUpperCase(); // UP | DOWN
  const price = num(params.price);
  const size = num(params.size);
  if (!marketId || (side !== "UP" && side !== "DOWN") || size === null || size <= 0 || price === null) {
    throw new BridgeError("CONFIG_ERROR", "marketId, side (UP|DOWN), positive size and price are required");
  }
  // Transaction safety: validate current on-chain status right before signing,
  // and resolve the market's CURRENT pool (pools are recycled) from marketId.
  const row = await getMarketRowOrThrow(exchange, marketId);
  const pool = String(row.poolAddress ?? "");
  if (!pool) throw new BridgeError("MARKET_NOT_FOUND", `market ${marketId} has no bound pool`);
  const onchain = (await exchange.client.getMarketOnchain(marketId as `0x${string}`)) as unknown as AnyRec;
  const status = onchainStatusStr(onchain.status) ?? "Unknown";
  if (status !== "Trading") {
    throw new BridgeError("MARKET_NOT_TRADING", `market ${marketId} status is ${status}, not Trading`);
  }
  const trader = exchange.client.createTrader({ privateKey: env.privateKey as `0x${string}` });
  const result = (await trader.placeOrder({
    pool: pool as `0x${string}`,
    side: side === "UP" ? "BUY_YES" : "BUY_NO",
    price: BigInt(Math.round(price * RAW6)),
    quantity: BigInt(Math.round(size * RAW6)),
    autoApprove: true,
  })) as unknown as AnyRec;
  return {
    source: "LIVE_DREAMDEX",
    submitted: true,
    network: env.network,
    marketId: marketId.toLowerCase(),
    side,
    order: result,
  };
}
