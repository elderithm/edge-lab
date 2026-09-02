# Data Sources

Use official Polymarket APIs as the primary source.

## Official documentation

- API overview: https://docs.polymarket.com/api-reference/introduction
- Market data overview: https://docs.polymarket.com/market-data/overview
- Fetching markets: https://docs.polymarket.com/market-data/fetching-markets
- List markets: https://docs.polymarket.com/api-reference/markets/list-markets
- User activity: https://docs.polymarket.com/api-reference/core/get-user-activity
- User/market trades: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets
- Order book: https://docs.polymarket.com/api-reference/market-data/get-order-book
- Price history: https://docs.polymarket.com/api-reference/markets/get-prices-history
- Rate limits: https://docs.polymarket.com/api-reference/rate-limits
- Geographic restrictions: https://docs.polymarket.com/api-reference/geoblock

## Base endpoints

At the time this spec was written, official docs expose:

```text
Gamma API: https://gamma-api.polymarket.com
Data API:  https://data-api.polymarket.com
CLOB API:  https://clob.polymarket.com
Geoblock:  https://polymarket.com/api/geoblock
```

Before implementing an endpoint, verify its current official documentation rather than relying only on this file.

## Authentication boundary

Gamma API, Data API, and CLOB read endpoints used by this project are public/read-only in the official API documentation.

Do **not** implement authenticated CLOB trading endpoints in this repository.

## Rate limiting

Respect official rate limits and throttling behavior.

Client requirements:

- bounded concurrency;
- timeouts;
- retry only idempotent reads;
- exponential backoff with jitter for transient failures;
- no retry storms;
- pagination helpers;
- clear handling of partial retrieval.

## Normalization rules

External APIs may represent numeric values as strings or numbers. Normalize monetary values into `Decimal` immediately after parsing.

Timestamps:

- normalize to UTC;
- preserve source timestamp when useful;
- convert to requested display timezone only at the presentation layer.

## Data-quality rules

Never silently fabricate:

- category;
- P&L;
- holding period;
- execution price;
- market resolution time;
- historical order-book depth.

If the source does not provide enough data, return `unknown`, omit the metric, or label it as an estimate with the method used.
