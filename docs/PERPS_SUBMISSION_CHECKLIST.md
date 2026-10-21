# DreamDEX Perps Bounty — Submission Checklist

Status as of 2026-10-22 (branch `hackathon/dreamdex-perps-2026`). Only items with
evidence are marked VERIFIED.

## Official bounty conditions — what could and could not be verified

| Item | Source | Status |
|---|---|---|
| Event: "an online builder bounty focused on dreamDEX Perps" | Eventbrite listing | VERIFIED (public page) |
| Dates: Oct 19 – Nov 2, 2026. The listing shows "10 PM–8 AM PDT" in one place and "5 AM–4 PM UTC" in another; 8 AM PDT is 15:00 UTC, so the end time is inconsistent | Eventbrite listing | VERIFIED as published; **exact deadline time unresolved** |
| Only whitelisted emails can submit; Event Contracts builders were whitelisted and invited by email/Telegram; others ask in the dreamDEX Discord or SomniaHacks Telegram | Eventbrite listing | VERIFIED (public page) |
| Submissions go through the DoraHacks page | Eventbrite listing | VERIFIED (public page) |
| Judging criteria, prizes, required deliverables, eligibility details, exact deadline + timezone | DoraHacks `dreamdex-perps-bounty` | **NOT VERIFIED** — DoraHacks returns HTTP 405 / an AWS WAF "Human Verification" page to automated access |
| Perps network, SDK version, sizing/precision hazards | app.dreamdex.io docs (developers/perps-testnet, trading/perps-testnet) | VERIFIED and cross-checked against the installed SDK 0.32.1 types and live reads |

### Human verification needed (open the DoraHacks page in a browser)

- [ ] Exact submission deadline and timezone.
- [ ] Judging criteria (update PERPS_SUBMISSION.md wording if they emphasize specific SDK features).
- [ ] Required deliverables (video length? live deployment? specific fields?).
- [ ] Whether the submitting DoraHacks account email is whitelisted.
- [ ] Prize / track selection and any "new work only" rules.
- [ ] Whether a public repository branch or a merged `main` is expected.

## Engineering status

### VERIFIED (evidence in this repo / this session)

- [x] Existing functionality operational — offline suite 256 passed (183 pre-existing + 73 new); ruff, format, mypy clean; Event Contracts bridge `tsc` clean.
- [x] Perps adapter reads actual Hideki markets — 21 markets via `listPerpMarkets` (live `pytest -m live`: 3 passed).
- [x] Market details normalized and visible — `edge-lab perps markets` / `inspect`, per-market decimals 6–24.
- [x] Funding, basis, spread, depth computed from live data — `scan` / dashboard on live Hideki.
- [x] Missing data explicitly identified — `INSUFFICIENT_DATA` (e.g. XLM volatility live), stale-mark mapping tests.
- [x] Risk checks produce explainable results — every check printed with detail; blocked reasons tested.
- [x] Paper trading without a wallet — live paper open → MTM → close → report exercised.
- [x] Perps dashboard works locally — `/perps` live (screenshots taken in-session), fixture endpoints tested.
- [x] Testnet execution isolated behind permission gates — CLI/bridge/adapter gate tests; forged/expired approvals never reach the bridge.
- [x] Order preview validates size and margin — live official `getMaxPerpOrderSize` / margin / liquidation preview for a public address.
- [x] Bridge unit tests — `npm run typecheck`, `npm test` (4 pass).
- [x] Submission documentation exists — PERPS_ARCHITECTURE / DEVELOPMENT_HISTORY / TESTNET_RUNBOOK / DEMO / SUBMISSION / this file.
- [x] Development history separates previous and new work — PERPS_DEVELOPMENT_HISTORY.md.
- [x] Demo recording instructions ready — PERPS_DEMO.md.

### IMPLEMENTED BUT NOT LIVE-VERIFIED

- [ ] Signed testnet order submission (`edge-lab perps execute … --yes`, bridge `place-order` → `placePerpOrder`).
- [ ] Receipt retrieval for a real transaction (`edge-lab perps receipt`) — the command works against the RPC but has no Edge Lab transaction to read yet.
- [ ] Fill reconciliation and post-trade position read on a real order (unit-tested with synthetic results only).
- [ ] Live account equity/positions for a funded account (only an empty account was read).
- [ ] CI run on GitHub for the new `perps-bridge` job (not pushed yet).

### REQUIRES USER ACTION

- [ ] Create a dedicated throwaway Hideki testnet key; store it in 1Password and export `PERPS_PRIVATE_KEY` (never paste it into chat).
- [ ] Fund it: Perps Arena paper USDso → move to the Perps account; STT gas via the app's bot top-up (runbook §7).
- [ ] Run `NETWORK=hideki-testnet TRADING_MODE=testnet edge-lab perps execute BTC --side long --size 0.00013 --yes`, then `edge-lab perps receipt <hash>`; paste the evidence into PERPS_SUBMISSION.md.
- [ ] Record and upload the demo video (PERPS_DEMO.md); paste the URL.
- [ ] Verify the DoraHacks conditions above.
- [ ] Authorize `git push` of `hackathon/dreamdex-perps-2026` (and a PR, if wanted).
- [ ] Submit on DoraHacks.

### NOT COMPLETED (deliberately out of scope)

- Predictive strategy model / expected-value estimates (no defensible model; reported as `NOT_ESTIMATED`).
- Leverage above 1x, stop/TP-SL orders, voucher claiming, deposits/withdrawals from Edge Lab.
- Mainnet perps (none exist; no mainnet mode is implemented).
