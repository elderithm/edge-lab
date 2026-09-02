/**
 * DreamDEX transport/execution commands. This layer ONLY moves data in/out of
 * the official SDK and normalizes it to plain JSON. No probability, edge, risk,
 * or strategy logic lives here — that is all in the Python core.
 */
import type { SomniaMarkets } from "@somnia-chain/markets-sdk";
import { type BridgeEnv, BridgeError } from "./env.ts";

const SUPPORTED_ASSETS = new Set(["BTC", "ETH"]);

type AnyRec = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function windowLabel(tradingStart: number | null, expiry: number | null): string | null {
  if (tradingStart === null || expiry === null) return null;
  const secs = expiry - tradingStart;
  if (secs <= 0) return null;
  if (secs === 900) return "15m";
  if (secs === 3600) return "1h";
  const mins = Math.round(secs / 60);
  return `${mins}m`;
}

async function loadBinaryMarkets(exchange: SomniaMarkets): Promise<{ symbol: string; info: AnyRec }[]> {
  const markets = await exchange.loadMarkets();
  const out: { symbol: string; info: AnyRec }[] = [];
  for (const [symbol, m] of Object.entries(markets)) {
    const rec = m as unknown as AnyRec;
    if (rec.type === "binary") out.push({ symbol, info: rec.info as AnyRec });
  }
  return out;
}

function marketRow(symbol: string, info: AnyRec): AnyRec {
  const tradingStart = num(info.tradingStart);
  const expiry = num(info.expiry);
  return {
    venue: "dreamdex",
    marketId: String(info.marketId ?? "").toLowerCase(),
    asset: String(info.asset ?? ""),
    symbol,
    upSymbol: symbol, // YES is the default outcome the facade resolves
    downSymbol: `${symbol}#NO`,
    status: String(info.status ?? "Unknown"),
    tradingStart,
    expiry,
    poolAddress: info.poolAddress ? String(info.poolAddress) : null,
    nonce: info.nonce != null ? String(info.nonce) : null,
    window: windowLabel(tradingStart, expiry),
  };
}

async function findByMarketId(exchange: SomniaMarkets, marketId: string): Promise<{ symbol: string; info: AnyRec }> {
  const wanted = marketId.toLowerCase();
  const rows = await loadBinaryMarkets(exchange);
  const hit = rows.find((r) => String(r.info.marketId ?? "").toLowerCase() === wanted);
  if (!hit) throw new BridgeError("MARKET_NOT_FOUND", `no binary market with marketId ${marketId}`);
  return hit;
}

/** List live BTC/ETH Event Contracts, keyed by canonical marketId. */
export async function discover(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const assets: string[] = Array.isArray(params.assets)
    ? (params.assets as string[]).map((a) => a.toUpperCase())
    : [...SUPPORTED_ASSETS];
  const rows = await loadBinaryMarkets(exchange);
  const markets = rows
    .map((r) => marketRow(r.symbol, r.info))
    .filter((r) => assets.includes(String(r.asset).toUpperCase()));
  return { source: "LIVE_DREAMDEX", markets };
}

/** Fresh on-chain market detail — status + opening reference. Call before writes. */
export async function market(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  if (!marketId) throw new BridgeError("CONFIG_ERROR", "marketId is required");
  const found = await findByMarketId(exchange, marketId);
  const onchain = (await exchange.client.getMarketOnchain(marketId as `0x${string}`)) as unknown as AnyRec;
  let openingReference: number | null = null;
  try {
    const res = (await exchange.client.getMarketResolution(marketId)) as unknown as AnyRec;
    openingReference = num(res?.openingAnswer ?? res?.openingPrice ?? null);
  } catch {
    openingReference = null; // opening question may not be answered yet
  }
  const row = marketRow(found.symbol, found.info);
  return {
    source: "LIVE_DREAMDEX",
    ...row,
    // On-chain truth overrides the (possibly lagging) indexer status:
    status: String(onchain.status ?? row.status),
    voided: Boolean(onchain.voided ?? false),
    resolvedAtTimestamp: num(onchain.resolvedAtTimestamp),
    openingReference,
  };
}

/** Executable Up/Down books for a market, addressed by canonical marketId. */
export async function orderbook(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  const depth = num(params.depth) ?? 50;
  if (!marketId) throw new BridgeError("CONFIG_ERROR", "marketId is required");
  const found = await findByMarketId(exchange, marketId);
  const upBook = await exchange.fetchOrderBook(found.symbol, depth);
  const downBook = await exchange.fetchOrderBook(`${found.symbol}#NO`, depth);
  return {
    source: "LIVE_DREAMDEX",
    marketId: marketId.toLowerCase(),
    capturedAt: Math.floor(Date.now() / 1000),
    up: { asks: upBook.asks, bids: upBook.bids },
    down: { asks: downBook.asks, bids: downBook.bids },
  };
}

/**
 * Underlying price snapshot + recent 1m closes for an asset (BTC/ETH). Returns
 * RAW closes only — the Python core computes returns/volatility, not this layer.
 */
export async function price(exchange: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const asset = String(params.asset ?? "").toUpperCase();
  const limit = num(params.limit) ?? 30;
  if (!asset) throw new BridgeError("CONFIG_ERROR", "asset is required (e.g. BTC)");
  const now = Math.floor(Date.now() / 1000);
  const live = (await exchange.fetchPrice(asset)) as unknown as AnyRec | null;
  if (!live || num(live.price) === null) {
    throw new BridgeError("STALE_PRICE_DATA", `no live price for ${asset}`);
  }
  let closes: [number, number][] = [];
  let intervalSeconds = 60;
  try {
    const ohlcv = (await exchange.fetchPriceOHLCV(asset, "1m", undefined, limit)) as unknown as number[][];
    closes = ohlcv
      .filter((c) => Array.isArray(c) && c.length >= 5)
      .map((c) => [Math.floor(c[0] / 1000), c[4]] as [number, number]);
  } catch {
    closes = []; // candles optional; Python treats missing vol as low confidence
  }
  return {
    source: "dreamdex-pricefeed",
    asset,
    price: num(live.price),
    timestamp: Math.floor((num(live.timestamp) ?? now * 1000) / 1000),
    receivedAt: now,
    intervalSeconds,
    closes,
  };
}

/**
 * Submit a Shannon Testnet order. Re-reads on-chain status immediately before
 * signing and refuses anything but a TRADING market. Never called in paper mode.
 */
export async function placeOrder(exchange: SomniaMarkets, env: BridgeEnv, params: AnyRec): Promise<AnyRec> {
  const marketId = String(params.marketId ?? "");
  const side = String(params.side ?? "").toUpperCase(); // UP | DOWN
  const price = num(params.price);
  const size = num(params.size);
  const orderType = (String(params.orderType ?? "limit").toLowerCase() === "market" ? "market" : "limit") as
    | "limit"
    | "market";
  if (!marketId || (side !== "UP" && side !== "DOWN") || size === null || size <= 0) {
    throw new BridgeError("CONFIG_ERROR", "marketId, side (UP|DOWN) and positive size are required");
  }
  const found = await findByMarketId(exchange, marketId);

  // Transaction safety: validate current on-chain status right before signing.
  const onchain = (await exchange.client.getMarketOnchain(marketId as `0x${string}`)) as unknown as AnyRec;
  const status = String(onchain.status ?? "Unknown");
  if (status !== "Trading") {
    throw new BridgeError("MARKET_NOT_TRADING", `market ${marketId} status is ${status}, not Trading`);
  }

  const ref = side === "UP" ? found.symbol : `${found.symbol}#NO`;
  const result = (await exchange.createOrder(
    ref,
    orderType,
    "buy",
    size,
    price ?? undefined,
  )) as unknown as AnyRec;
  return {
    source: "LIVE_DREAMDEX",
    submitted: true,
    network: env.network,
    marketId: marketId.toLowerCase(),
    side,
    order: result,
  };
}
