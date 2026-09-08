# Claude Code Kickoff Prompt

You are implementing the `polymarket-edge-lab` repository.

First, read `CLAUDE.md` completely. Then read every file in `docs/`, especially:

- `docs/01-architecture.md`
- `docs/03-cli-spec.md`
- `docs/04-wallet-reverse-engineering.md`
- `docs/05-paper-trading.md`
- `docs/06-safety-and-compliance.md`
- `docs/07-testing-and-quality.md`
- `docs/09-implementation-tasks.md`

Treat those files as the source of truth for this implementation.

## Goal

Build the MVP of Polymarket Edge Lab: a robust, typed, read-only Polymarket research and paper-trading CLI that can analyze public wallet behavior, inspect markets/order books, scan apparent binary-market pricing edges, forward-paper-follow wallets, and reverse-engineer candidate wallet strategies.

## Critical boundary

Do NOT implement any real-money execution capability.

That means no private keys, signing, authenticated CLOB trading, order placement/cancellation, deposits/withdrawals/bridging, or geoblock/VPN/proxy bypass. Public/read-only API access, local analysis, exports, and paper trading are allowed.

## How to work

1. Inspect the current repository before changing anything.
2. Summarize the current state and identify what is missing relative to `docs/09-implementation-tasks.md`.
3. Create a concise implementation plan.
4. Implement tasks in dependency order, starting with Task 1.
5. Keep API clients, domain models, analysis logic, paper execution, persistence, and CLI concerns separated.
6. Use `Decimal` for prices, sizes, notionals, fees, and P&L.
7. Make normal tests independent of live Polymarket availability by using fixtures/mocks.
8. Add bounded retries/timeouts and respect documented rate limits.
9. Do not silently invent data that public APIs do not provide. Label estimates explicitly.
10. After each logical milestone, run the relevant tests and quality checks and fix failures before continuing.

## Completion target

Aim to complete Tasks 1–6 in `docs/09-implementation-tasks.md` if the repository state allows it. If a task cannot be completed because an external API field/behavior is uncertain, implement the safe subset, document the limitation, and continue with the remaining independent work rather than guessing.

At the end, provide:

- a summary of what was implemented;
- the final repository structure;
- commands to install and run it;
- commands for tests/lint/type checks;
- known limitations;
- the next highest-value research improvement.
