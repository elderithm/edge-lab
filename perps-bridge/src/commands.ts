/**
 * DreamDEX Perps transport/execution commands. This layer ONLY moves data in/out
 * of the official SDK. Every bigint leaves as a RAW decimal string; all scaling
 * (baseDecimals / quoteDecimals / tick / lot), analytics and risk logic live in
 * the Python core.
 *
 * The one exception is `place-order`, which re-validates the order against
 * fresh on-chain state immediately before signing (defence in depth — Python's
 * risk engine has already approved it).
 */
import { ORDER_TYPE, type SomniaMarkets } from "@somnia-chain/markets-sdk";
import type { PerpMarket } from "@somnia-chain/markets-sdk";
import { privateKeyToAccount } from "viem/accounts";
import { BridgeError, HIDEKI_CHAIN_ID, type PerpsEnv } from "./env.ts";
import { buildPublicClient } from "./sdk.ts";

type AnyRec = Record<string, unknown>;
type Hex = `0x${string}`;

const ORDER_GAS = 10_000_000n; // docs: estimates spike to 3.2M-7.7M; unused gas is not billed

function now(): number {
  return Math.floor(Date.now() / 1000);
}

/** Recursively stringify bigints so the payload is plain JSON. */
export function plain(v: unknown): unknown {
  if (typeof v === "bigint") return v.toString();
  if (Array.isArray(v)) return v.map(plain);
  if (v && typeof v === "object") {
    const out: AnyRec = {};
    for (const [k, x] of Object.entries(v as AnyRec)) out[k] = plain(x);
    return out;
  }
  return v;
}

function addr(v: unknown, name: string): Hex {
  const s = String(v ?? "");
  if (!/^0x[0-9a-fA-F]{40}$/.test(s)) throw new BridgeError("CONFIG_ERROR", `${name} must be a 0x address`);
  return s.toLowerCase() as Hex;
}

function big(v: unknown, name: string): bigint {
  const s = String(v ?? "");
  if (!/^[0-9]+$/.test(s)) throw new BridgeError("CONFIG_ERROR", `${name} must be a non-negative raw integer string`);
  return BigInt(s);
}

async function marketOrThrow(m: SomniaMarkets, pool: Hex): Promise<PerpMarket> {
  const row = await m.client.getPerpMarket(pool);
  if (!row) throw new BridgeError("MARKET_NOT_FOUND", `no perp market with pool ${pool}`);
  return row;
}

/** Tick/lot/min checks shared by preview and place (exact integer arithmetic). */
export function precisionProblems(row: PerpMarket, price: bigint, quantity: bigint): string[] {
  const tick = BigInt(row.tickSize);
  const lot = BigInt(row.lotSize);
  const min = BigInt(row.minQuantity);
  const out: string[] = [];
  if (price <= 0n) out.push("price must be > 0");
  if (tick > 0n && price % tick !== 0n) out.push(`price ${price} is not a multiple of tickSize ${tick}`);
  if (quantity <= 0n) out.push("quantity must be > 0");
  if (lot > 0n && quantity % lot !== 0n) out.push(`quantity ${quantity} is not a multiple of lotSize ${lot}`);
  if (quantity < min) out.push(`quantity ${quantity} is below minQuantity ${min}`);
  return out;
}

/** Notional in raw quote units: quantity(raw base) * price(18dp) / 10^baseDecimals, rescaled to quoteDecimals. */
export function notionalRaw(row: PerpMarket, price: bigint, quantity: bigint): bigint {
  const quoteAtoms = (quantity * price) / 10n ** BigInt(row.baseDecimals); // 18dp quote
  const qd = BigInt(row.quoteDecimals);
  return qd >= 18n ? quoteAtoms * 10n ** (qd - 18n) : quoteAtoms / 10n ** (18n - qd);
}

function decimalToRaw(human: string, decimals: number): bigint {
  const m = /^([0-9]+)(?:\.([0-9]+))?$/.exec(human.trim());
  if (!m) throw new BridgeError("CONFIG_ERROR", `invalid decimal '${human}'`);
  const frac = (m[2] ?? "").slice(0, decimals).padEnd(decimals, "0");
  return BigInt(m[1]) * 10n ** BigInt(decimals) + BigInt(frac || "0");
}

/** List perp markets + the system config of their MarginBank. */
export async function markets(m: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const limit = Number(params.limit ?? 50);
  const rows = await m.client.listPerpMarkets({ limit });
  let system: unknown = null;
  const bank = rows[0]?.marginBank;
  if (bank) {
    try {
      system = await m.client.getPerpSystemConfig(bank);
    } catch (err) {
      system = { error: String((err as Error)?.message ?? err).slice(0, 200) };
    }
  }
  return { source: "LIVE_DREAMDEX_PERPS", chainId: HIDEKI_CHAIN_ID, capturedAt: now(), system, markets: rows };
}

/** One market: indexed row + fresh on-chain state + risk params (+ funding premium, best effort). */
export async function market(m: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const row = await marketOrThrow(m, pool);
  const [state, risk] = await Promise.all([m.client.getPerpState(pool), m.client.getPerpRiskParams(pool)]);
  let premium: unknown = null;
  try {
    premium = await m.client.getPerpFundingPremium(pool);
  } catch {
    premium = null; // un-upgraded pool: optional read, reported as missing
  }
  return { source: "LIVE_DREAMDEX_PERPS", chainId: HIDEKI_CHAIN_ID, capturedAt: now(), market: row, state, risk, premium };
}

export async function orderbook(m: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const depth = Number(params.depth ?? 25);
  const book = await m.client.getSpotOrderBook(pool, { depth });
  return { source: "LIVE_DREAMDEX_PERPS", pool, capturedAt: now(), ...book };
}

export async function candles(m: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const interval = Number(params.intervalSeconds ?? 300);
  const limit = Number(params.limit ?? 48);
  const rows = await m.client.getCandles(pool, interval, { limit });
  return { source: "LIVE_DREAMDEX_PERPS", pool, intervalSeconds: interval, capturedAt: now(), candles: rows };
}

/** Read-only account view for a PUBLIC address: equity, voucher, non-flat positions. */
export async function account(m: SomniaMarkets, env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  const acct = addr(params.account ?? env.account, "account (or PERPS_ACCOUNT)");
  const rows = await m.client.listPerpMarkets({ limit: 50 });
  if (rows.length === 0) throw new BridgeError("MARKET_NOT_FOUND", "no perp markets listed");
  const bank = rows[0].marginBank;
  const [equity, voucher] = await Promise.all([
    m.client.tryGetPerpAccountEquity(bank, acct),
    m.client.getPerpVoucherEligibility(bank, acct).catch((e: unknown) => ({ error: String((e as Error)?.message) })),
  ]);
  const positions: AnyRec[] = [];
  for (const row of rows) {
    const pos = await m.client.getPerpPosition({ marginBank: row.marginBank, account: acct, pool: row.poolAddress });
    if (pos.size !== 0n) positions.push({ pool: row.poolAddress, baseSymbol: row.baseSymbol, ...pos });
  }
  return { source: "LIVE_DREAMDEX_PERPS", account: acct, marginBank: bank, capturedAt: now(), equity, voucher, positions };
}

/**
 * Unsigned order preview: precision checks always; with an account, also the
 * official sizing / margin / liquidation projections. Needs no signer.
 */
export async function previewOrder(m: SomniaMarkets, env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const isBid = Boolean(params.isBid);
  const price = big(params.price, "price");
  const quantity = big(params.quantity, "quantity");
  const row = await marketOrThrow(m, pool);
  const state = await m.client.getPerpState(pool);
  const problems = precisionProblems(row, price, quantity);
  const acctRaw = params.account ?? env.account;
  let sizing: unknown = null;
  let margin: unknown = null;
  let liquidation: unknown = null;
  if (acctRaw) {
    const acct = addr(acctRaw, "account");
    const base = { pool, marginBank: row.marginBank, account: acct, isBid, price };
    [sizing, margin, liquidation] = await Promise.all([
      m.client.getMaxPerpOrderSize(base),
      m.client.previewPerpOrderMargin({ ...base, quantity }),
      m.client.previewPerpLiquidationPrice({ ...base, quantity }),
    ]);
  }
  return {
    source: "LIVE_DREAMDEX_PERPS",
    dryRun: true,
    chainId: HIDEKI_CHAIN_ID,
    capturedAt: now(),
    pool,
    isBid,
    price: price.toString(),
    quantity: quantity.toString(),
    notionalRaw: notionalRaw(row, price, quantity).toString(),
    markPriceOk: state.markPriceOk,
    precisionProblems: problems,
    sizing,
    margin,
    liquidation,
    note: "unsigned preview; nothing signed or submitted",
  };
}

const ORDER_TYPES: Record<string, number> = { ioc: ORDER_TYPE.MARKET, limit: ORDER_TYPE.LIMIT, post_only: ORDER_TYPE.POST_ONLY };

/**
 * Submit a Hideki testnet perp order. Re-validates chain id, market state,
 * precision, official max size, voucher restrictions and the bridge notional cap
 * immediately before signing; any failure throws before the SDK write is called.
 */
export async function placeOrder(m: SomniaMarkets, env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const isBid = Boolean(params.isBid);
  const price = big(params.price, "price");
  const quantity = big(params.quantity, "quantity");
  const orderTypeName = String(params.orderType ?? "ioc");
  const orderType = ORDER_TYPES[orderTypeName];
  if (orderType === undefined) throw new BridgeError("CONFIG_ERROR", `orderType must be one of ${Object.keys(ORDER_TYPES)}`);
  if (params.riskApproved !== true) {
    throw new BridgeError("RISK_NOT_APPROVED", "place-order requires an explicit riskApproved=true from the risk engine");
  }

  const pub = buildPublicClient(env);
  const chainId = await pub.getChainId();
  if (chainId !== HIDEKI_CHAIN_ID) {
    throw new BridgeError("WRONG_CHAIN", `RPC chain id ${chainId} != Hideki ${HIDEKI_CHAIN_ID}`);
  }
  const signer = privateKeyToAccount(env.privateKey as Hex).address.toLowerCase() as Hex;

  const row = await marketOrThrow(m, pool);
  const state = await m.client.getPerpState(pool);
  if (!state.markPriceOk) throw new BridgeError("STALE_MARK_PRICE", "mark feed reports stale; sizing unavailable");
  const problems = precisionProblems(row, price, quantity);
  if (problems.length) throw new BridgeError("PRECISION_ERROR", problems.join("; "));

  const cap = decimalToRaw(env.maxOrderNotional, row.quoteDecimals);
  const notional = notionalRaw(row, price, quantity);
  if (notional > cap) {
    throw new BridgeError("NOTIONAL_CAP", `order notional ${notional} raw > bridge cap ${cap} raw (PERPS_MAX_ORDER_NOTIONAL)`);
  }

  const sizing = await m.client.getMaxPerpOrderSize({ pool, marginBank: row.marginBank, account: signer, isBid, price });
  if (!sizing.priceable) throw new BridgeError("STALE_MARK_PRICE", "getMaxPerpOrderSize: market not priceable");
  if (sizing.limitedBy === "voucherBlocked") {
    throw new BridgeError("VOUCHER_BLOCKED", "paper USDso voucher cannot open positions in this market");
  }
  if (!sizing.placeable || sizing.maxQuantity < quantity) {
    throw new BridgeError(
      "MAX_ORDER_SIZE",
      `quantity ${quantity} exceeds official max ${sizing.maxQuantity} (limitedBy=${sizing.limitedBy}, placeable=${sizing.placeable})`,
    );
  }

  const trader = m.client.createTrader({ privateKey: env.privateKey as Hex });
  const result = await trader.placePerpOrder({ pool, isBid, price, quantity, orderType, gas: ORDER_GAS });
  const position = await m.client
    .getPerpPosition({ marginBank: row.marginBank, account: signer, pool })
    .catch((e: unknown) => ({ error: String((e as Error)?.message).slice(0, 200) }));
  const receipt = result.receipt;
  return {
    source: "LIVE_DREAMDEX_PERPS",
    submitted: true,
    chainId,
    account: signer,
    pool,
    isBid,
    price: price.toString(),
    quantity: quantity.toString(),
    orderType: orderTypeName,
    txHash: result.hash,
    receipt: {
      status: receipt.status,
      blockNumber: receipt.blockNumber,
      gasUsed: receipt.gasUsed,
      transactionHash: receipt.transactionHash,
    },
    orderId: result.orderId ?? null,
    fills: result.fills,
    positionAfter: position,
    capturedAt: now(),
  };
}

/**
 * Claim the signer's one-time paper-USDso credit (testnet voucher) into its own
 * Perps account. Gated like an order (`buildMarkets(..., { needSigner })`), plus an
 * explicit `confirmed=true`, a chain-id check and a fresh eligibility read right
 * before signing. Nothing but the protocol's own credit moves.
 */
export async function claimVoucher(m: SomniaMarkets, env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  if (params.confirmed !== true) {
    throw new BridgeError("NOT_CONFIRMED", "claim-voucher requires an explicit confirmed=true");
  }
  const pub = buildPublicClient(env);
  const chainId = await pub.getChainId();
  if (chainId !== HIDEKI_CHAIN_ID) {
    throw new BridgeError("WRONG_CHAIN", `RPC chain id ${chainId} != Hideki ${HIDEKI_CHAIN_ID}`);
  }
  const signer = privateKeyToAccount(env.privateKey as Hex).address.toLowerCase() as Hex;
  const rows = await m.client.listPerpMarkets({ limit: 50 });
  if (rows.length === 0) throw new BridgeError("MARKET_NOT_FOUND", "no perp markets listed");
  const bank = rows[0].marginBank;

  const before = await m.client.getPerpVoucherEligibility(bank, signer);
  if (!before.eligible) {
    throw new BridgeError("VOUCHER_NOT_ELIGIBLE", `voucher not claimable for ${signer}: ${before.reason}`);
  }
  const equityBefore = await m.client.tryGetPerpAccountEquity(bank, signer);

  const trader = m.client.createTrader({ privateKey: env.privateKey as Hex });
  const result = await trader.claimPerpVoucher({ marginBank: bank, gas: ORDER_GAS });
  const [equityAfter, after] = await Promise.all([
    m.client.tryGetPerpAccountEquity(bank, signer),
    m.client.getPerpVoucherEligibility(bank, signer).catch((e: unknown) => ({ error: String((e as Error)?.message) })),
  ]);
  const r = result.receipt;
  return {
    source: "LIVE_DREAMDEX_PERPS",
    submitted: true,
    chainId,
    account: signer,
    marginBank: bank,
    grantAmount: before.grantAmount,
    txHash: result.hash,
    receipt: { status: r.status, blockNumber: r.blockNumber, gasUsed: r.gasUsed, transactionHash: r.transactionHash },
    equityBefore,
    equityAfter,
    eligibilityAfter: after,
    capturedAt: now(),
  };
}

/** Receipt by hash, for after-the-fact reconciliation. */
export async function receipt(env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  const hash = String(params.hash ?? "");
  if (!/^0x[0-9a-fA-F]{64}$/.test(hash)) throw new BridgeError("CONFIG_ERROR", "hash must be a 0x tx hash");
  const pub = buildPublicClient(env);
  const r = await pub.getTransactionReceipt({ hash: hash as Hex });
  return {
    source: "LIVE_DREAMDEX_PERPS",
    chainId: await pub.getChainId(),
    transactionHash: r.transactionHash,
    status: r.status,
    blockNumber: r.blockNumber,
    gasUsed: r.gasUsed,
    from: r.from,
    to: r.to,
    logCount: r.logs.length,
  };
}

/** Account position in one pool (public address). */
export async function position(m: SomniaMarkets, env: PerpsEnv, params: AnyRec): Promise<AnyRec> {
  const pool = addr(params.pool, "pool");
  const acct = addr(params.account ?? env.account, "account (or PERPS_ACCOUNT)");
  const row = await marketOrThrow(m, pool);
  const pos = await m.client.getPerpPosition({ marginBank: row.marginBank, account: acct, pool });
  return { source: "LIVE_DREAMDEX_PERPS", pool, account: acct, capturedAt: now(), ...pos };
}

/**
 * Everything the analytics need for one or more markets, in ONE process (a
 * scan would otherwise spawn ~3 bridge processes per market). A failing market
 * is reported as `{ pool, error }` rather than aborting the whole snapshot.
 */
export async function snapshot(m: SomniaMarkets, params: AnyRec): Promise<AnyRec> {
  const depth = Number(params.depth ?? 25);
  const interval = Number(params.candleIntervalSeconds ?? 300);
  const candleLimit = Number(params.candleLimit ?? 48);
  const rows = await m.client.listPerpMarkets({ limit: 50 });
  const wanted = Array.isArray(params.pools) ? new Set((params.pools as string[]).map((p) => p.toLowerCase())) : null;
  const selected = wanted ? rows.filter((r) => wanted.has(r.poolAddress.toLowerCase())) : rows;
  const items = await Promise.all(
    selected.map(async (row) => {
      const pool = row.poolAddress;
      try {
        const [state, risk, book, bars] = await Promise.all([
          m.client.getPerpState(pool),
          m.client.getPerpRiskParams(pool),
          m.client.getSpotOrderBook(pool, { depth }),
          m.client.getCandles(pool, interval, { limit: candleLimit }).catch(() => null),
        ]);
        const premium = await m.client.getPerpFundingPremium(pool).catch(() => null);
        return { pool, capturedAt: now(), market: row, state, risk, premium, book, candles: bars, candleIntervalSeconds: interval };
      } catch (err) {
        return { pool, market: row, error: { code: "MARKET_READ_FAILED", message: String((err as Error)?.message).slice(0, 300) } };
      }
    }),
  );
  return { source: "LIVE_DREAMDEX_PERPS", chainId: HIDEKI_CHAIN_ID, capturedAt: now(), items };
}

/** The PUBLIC address of the configured signer (never the key). Gated like a write. */
export function signer(env: PerpsEnv): AnyRec {
  if (!env.privateKey) throw new BridgeError("SIGNER_REQUIRED", "PERPS_PRIVATE_KEY is not set");
  return { address: privateKeyToAccount(env.privateKey as Hex).address.toLowerCase() };
}
