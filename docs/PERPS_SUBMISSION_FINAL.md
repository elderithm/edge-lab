# DreamDEX Perps Edge Lab — Final Submission (dreamDEX Perps Builder Bounty 2026, MVP Track)

Audit date: 2026-11-01. Branch `hackathon/dreamdex-perps-2026` (HEAD at the time of
writing: see `git log -1`). Status labels: **VERIFIED** (evidence in this repo or
re-read live), **IMPLEMENTED BUT UNVERIFIED**, **MISSING**, **BLOCKED**.

> **Official rules not verified.** The DoraHacks page
> (`dorahacks.io/hackathon/dreamdex-perps-bounty/detail`) returns HTTP 405 / an AWS
> WAF human-verification page to automated access. Third-party participant repos
> state the window as Oct 19 – Nov 1, 2026, one of them "Nov 1, 23:59 UTC"; the
> Eventbrite listing said Nov 2. **Treat Nov 1, 23:59 UTC as the deadline until a
> human confirms it on the official page.** Judging criteria and required fields
> must also be confirmed there.

## 1. Project

**DreamDEX Perps Edge Lab** — *Explainable Perpetual Futures Intelligence and
Risk-Aware Execution.*

An independent quantitative layer for DreamDEX Perps on Somnia Hideki Testnet
(chain 50383). It reads every live perp market through the official
`@somnia-chain/markets-sdk`, explains funding, basis, liquidity and volatility,
estimates what an order would really cost from the live book, blocks unsafe
orders with explicit, check-by-check reasons, and lets a trader paper-trade or
submit a manually confirmed testnet order whose result is reconciled from the
receipt, the decoded fills and the MarginBank position.

It separates four things that are usually blurred together: **observed** market
conditions, **estimated execution cost**, **risk** (margin, effective leverage,
liquidation distance, the protocol's own max order size) and **strategy edge** —
always reported as `NOT_ESTIMATED`, because there is no validated predictive model
and no profit is claimed. Each market gets one category from published thresholds
(`REVIEW`, `WATCH`, `HIGH_EXECUTION_COST`, `INSUFFICIENT_LIQUIDITY`,
`HIGH_LIQUIDATION_RISK`, `STALE_DATA`, `INSUFFICIENT_DATA`). Effective leverage is
hard-capped at 1x.

## 2. MVP audit

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Perps features implemented | **VERIFIED** | Market discovery, normalized market model, funding/basis/liquidity/volatility analytics, book-walk execution cost, margin/liquidation estimates, assessment + ranking, risk engine (20+ checks, `RiskApproval`), unsigned preview with official sizing/margin/liquidation, paper trading (long/short, MTM, funding), testnet execution + reconciliation + evidence, `/perps` dashboard, CLI (`edge-lab perps …`). |
| 2 | Live Hideki market discovery | **VERIFIED** | `edge-lab perps markets` → 21 live markets with per-market decimals/tick/lot/min (re-run 2026-11-01); `pytest -m live` 3 passed. |
| 3 | Real testnet Perps order submitted | **VERIFIED** | One IOC order via `edge-lab perps execute BTC --side long --size 0.00013 --yes` after all risk checks passed (§5). |
| 4 | Tx hash + successful receipt | **VERIFIED** | `0x57fe64c4…aa47`, block 30162072, `status=success`, re-read with `edge-lab perps receipt`. |
| 5 | Fills / open position verified | **VERIFIED** | Decoded fill 0.00013 @ 81970.6; reconciled `FILLED`; MarginBank position re-read 2026-11-01: 0.00013 BTC long, entry 81970.6. |
| 6 | Close orders implemented and tested | **IMPLEMENTED BUT UNVERIFIED** | Closing = opposite-side `execute` for the same size (no dedicated reduce-only command). Live unsigned preview of the closing short passes every testnet check except `execution_mode` (no key in the audit shell). Not yet signed. |
| 7 | Dashboard with real testnet data | **VERIFIED** | `edge-lab perps dashboard` → `/perps` HTTP 200; `/api/perps/scan` returned `LIVE_TESTNET`, 21 markets (2026-11-01). |
| 8 | Automated tests | **VERIFIED** | §6. |
| 9 | Committed and pushed | **BLOCKED (needs approval)** | All work committed on `hackathon/dreamdex-perps-2026`; **not pushed** — GitHub currently has only `main` without any Perps code. |
| 10 | README sufficient for judging | **IMPLEMENTED BUT UNVERIFIED** | README has a Perps section, commands and doc links; judges cannot see it until the branch is pushed. |
| 11 | Demo instructions + submission materials | **IMPLEMENTED BUT UNVERIFIED** | This file, `PERPS_DEMO.md`, runbook; **demo video not recorded**. |
| 12 | Feedback Track issues | **VERIFIED (1 issue)** | `docs/feedback/FEEDBACK-001-voucher-claim-reverts.md`: eligibility says `true`, `claim()` reverts `0x3e31dcc2` for every address; reproducible with one `eth_call`, re-verified 2026-11-01. |

## 3. New functionality developed for this bounty

Edge Lab previously covered Polymarket research and DreamDEX Event Contracts
(Shannon testnet, [PR #1](https://github.com/elderithm/edge-lab/pull/1)). Everything
below is new on this branch; Event Contracts and Polymarket code is unchanged.

- `perps-bridge/` — isolated TypeScript bridge on SDK 0.32.1, Hideki only; JSON in/out, raw integers as strings; write gate; pre-sign re-validation (chain id, mark freshness, tick/lot/min, notional cap, `getMaxPerpOrderSize`, voucher limits).
- `edge_lab/venues/dreamdex_perps/` — typed models (identity = chain + pool), exact per-market decimal scaling, fixtures labelled SIMULATED.
- `edge_lab/perps/` — analytics, assessment, risk engine, execution + reconciliation, service.
- `edge_lab/paper/perps_paper.py` — paper ledger with funding from the cumulative index; testnet order ledger.
- `edge_lab/perps_cli.py` — `markets`, `scan`, `inspect`, `preview`, `paper-trade`, `paper-close`, `positions`, `report`, `execute`, `receipt`, `claim-voucher`, `dashboard`.
- `edge_lab/dashboard/perps_{api,page}.py` — `/perps` view (preview only, never submits).
- Tests (`tests/test_perps_*.py`, bridge `node:test`) and a CI job for the bridge.

Design and history: `docs/PERPS_ARCHITECTURE.md`, `docs/PERPS_DEVELOPMENT_HISTORY.md`.

## 4. Demonstration

```bash
git clone https://github.com/elderithm/edge-lab && cd edge-lab
git checkout hackathon/dreamdex-perps-2026
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
(cd perps-bridge && npm ci)                               # Node >= 22

edge-lab perps markets                                    # live Hideki markets
edge-lab perps scan                                       # ranked assessment
edge-lab perps inspect BTC                                # funding, basis, liquidity, vol, cost, risk
edge-lab perps preview BTC --side long --size 0.001       # unsigned; add --account 0x… for official sizing
edge-lab perps paper-trade BTC --side long --size 0.001 && edge-lab perps report
edge-lab perps dashboard                                  # http://127.0.0.1:8787/perps
edge-lab perps receipt 0x57fe64c4d310adcdcf8e577be284dff088a55f1b10eb78672a92634af082aa47
edge-lab perps scan --source fixture                      # offline, SIMULATED
```

Signed testnet execution (dedicated testnet key, funded per the runbook):

```bash
export NETWORK=hideki-testnet TRADING_MODE=testnet       # + PERPS_PRIVATE_KEY in the shell, never committed
edge-lab perps execute BTC --side long --size 0.00013          # prints every check, refuses without --yes
edge-lab perps execute BTC --side long --size 0.00013 --yes
```

## 5. GitHub

https://github.com/elderithm/edge-lab — branch `hackathon/dreamdex-perps-2026`
(**push pending approval**).

## 6. Testnet transaction evidence

| Field | Value |
|---|---|
| Network | Somnia Hideki Testnet, chain id 50383 |
| Command | `edge-lab perps execute BTC --side long --size 0.00013 --yes` (IOC, limit 82022.9) |
| Risk decision | `APPROVED (testnet)` — all 22 checks PASS (official max size 0.02305, margin sufficient, effective leverage 0.11x) |
| Tx hash | `0x57fe64c4d310adcdcf8e577be284dff088a55f1b10eb78672a92634af082aa47` |
| Block / receipt | 30162072, `success`, 8 logs |
| From → to | dedicated testnet signer `0x74dab13fd6561090fbedc477f7d5de01cf96e501` → BTC-PERP pool `0x4181dd08e73bbcdd1ba3e615a18f6abd941b94c0` |
| Order / fill | order id 6364126705429802276655; 1 fill, 0.00013 BTC @ 81970.6 USDso (maker order 7415591117631246718766) |
| Reconciled | `FILLED`; position after 0.00013 |
| Position re-read 2026-11-01 | 0.00013 BTC long, avg entry 81970.6; equity ≈ 99.06 USDso |

Hideki has no public block explorer; the evidence is the RPC receipt, the decoded
fill and the MarginBank position. Collateral: Perps Arena paper USDso (100) moved
into the MarginBank with the SDK's `depositMargin` (a one-off script, not part of
Edge Lab).

⟨Add the closing order here if it is executed: tx hash, block, reconciled state,
position after = 0.⟩

## 7. Testing results (2026-11-01)

| Suite | Result |
|---|---|
| `pytest` (offline: 183 pre-existing + 75 Perps) | 258 passed, 8 deselected |
| `ruff check`, `ruff format --check`, `mypy` (63 files) | clean |
| `perps-bridge`: `npm run typecheck`, `npm test` | OK, 6 passed |
| `dreamdex-bridge` (Event Contracts) `tsc` | OK |
| `pytest -m live tests/test_perps_live.py` (live Hideki) | 3 passed, 1 skipped (signed test is opt-in) |
| Gate tests | forged / expired / paper-mode approvals, wrong network, missing `--yes`, risk-blocked orders and unconfirmed voucher claims never reach the SDK write |

## 8. Known limitations

- One signed order verified; closing it has not been signed yet (§2 item 6).
- No predictive model: `REVIEW` is an observation, not a trade signal; expected edge is `NOT_ESTIMATED`.
- Effective leverage capped at 1x by design; no TP/SL, no reduce-only flag. The risk engine counts a closing order as additional gross exposure (conservative).
- Liquidation prices without an account are labelled estimates; the protocol preview is used when an account is supplied.
- Realized volatility uses DreamDEX perp-trade candles, not the oracle index; thin markets report `INSUFFICIENT_DATA`.
- `claim-voucher` is implemented but the distributor reverts for every address (FEEDBACK-001).
- Edge Lab does not move collateral (no deposit/withdraw commands).
- Run commands from the repository root; ledger and evidence go to `./.edge-lab/`.

## 9. Demo video checklist (2–3 min, script in `PERPS_DEMO.md`)

- [ ] `edge-lab perps markets` — live markets, per-market precision.
- [ ] Dashboard `/perps` — categories, funding, basis, cost; missing data shown as missing.
- [ ] Inspect BTC — book, funding normalization, volatility, `NOT_ESTIMATED` edge.
- [ ] `preview … --account 0x…` — official sizing/margin/liquidation, every check listed.
- [ ] Paper trade → `report` (labelled SIMULATED / PAPER).
- [ ] `execute … --yes` (or the closing order) + `receipt <hash>` + `report` showing `FILLED`.
- [ ] Never show the private key, the shell where it was entered, or `.env`.
- [ ] Upload (YouTube unlisted is fine) and paste the URL below.

Demo video: ⟨URL⟩

## 10. Remaining DoraHacks submission actions (in order)

1. **Confirm the deadline and required fields** on the official DoraHacks page in a browser (possibly Nov 1, 23:59 UTC).
2. **Approve the push**: `git push -u origin hackathon/dreamdex-perps-2026` (makes the Perps code public).
3. Optional, ~2 min: close the test position — `edge-lab perps execute BTC --side short --size 0.00013 --yes` from the repo root — and paste the evidence into §6.
4. Record and upload the demo video; paste the URL into §9.
5. On DoraHacks (whitelisted account): create the BUIDL, MVP Track; paste §1 (description), §3, §4, §6, §7, §8; GitHub URL and branch; video URL.
6. Feedback Track (if submitted separately): paste `docs/feedback/FEEDBACK-001-voucher-claim-reverts.md` in the template the official page requires.
7. Check any other required field (e.g. a social post link) that the official page lists.
