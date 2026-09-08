# Paper Trading

## Purpose

Measure the gap between seeing a public signal and obtaining a simulated executable price.

Paper trading is not intended to produce cosmetically attractive P&L. It should be conservative enough to reject fragile strategies.

## Signal lifecycle

1. Poll public wallet activity.
2. Detect a previously unseen relevant activity item.
3. Record original signal timestamp and reported signal price if present.
4. Fetch current order book.
5. Calculate signal age.
6. Calculate executable simulated price for configured notional using order-book depth.
7. Calculate drift versus source trade price when comparable.
8. Either simulate fill or record a skip reason.
9. Persist everything needed for later audit.

## Required skip reasons

At minimum:

- `signal_too_old`
- `missing_token_id`
- `missing_source_price`
- `order_book_unavailable`
- `insufficient_liquidity`
- `price_drift_too_large`
- `duplicate_signal`
- `unsupported_activity`
- `invalid_market_state`

## BUY simulation

For a BUY signal, walk current asks until configured paper notional/size is filled.

Record:

- signal price;
- best ask at observation;
- simulated VWAP;
- quantity;
- notional;
- price drift bps;
- signal age seconds;
- configured fee/slippage buffer.

## SELL simulation

When modeling exits based on a followed wallet's SELL activity, walk bids and apply the same conservative rules.

Do not sell more than the paper position owns.

## P&L

Separate:

- realized P&L;
- unrealized/mark-to-market P&L;
- fees/buffer assumptions;
- total net estimated P&L.

Do not present net cash flow as P&L when open positions exist.

## Database

Suggested tables:

- `schema_meta`
- `paper_runs`
- `observed_signals`
- `paper_fills`
- `paper_positions`
- `paper_closures`

Persist raw source identifiers so a result can be traced back to the retrieved activity.

## Forward-test metrics

A paper-follow report should include:

- signals observed;
- signals filled;
- signals skipped by reason;
- median/p90 signal age;
- median/p90 price drift;
- fill-rate estimate;
- realized P&L;
- mark-to-market P&L;
- max drawdown where meaningful;
- average paper notional;
- concentration by market.

## Anti-overfitting rule

Do not tune `max-age`, `max-drift-bps`, or other execution filters repeatedly against the same realized sample and then call the resulting P&L out-of-sample.
