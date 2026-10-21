"""DreamDEX Perps Edge Lab CLI (mounted as ``edge-lab perps ...``).

Explainable perpetual-futures analytics and risk-aware execution on Somnia
Hideki Testnet. Paper is the default and needs no wallet. Testnet submission
requires NETWORK=hideki-testnet + TRADING_MODE=testnet + a dedicated
PERPS_PRIVATE_KEY + passing every risk check + an explicit ``--yes``.
"""

from __future__ import annotations

import json as jsonlib
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import typer

from .errors import EdgeLabError
from .paper.perps_paper import DEFAULT_PATH, PerpsPaperDB
from .perps.analytics import AssessmentThresholds, walk_book
from .perps.execution import DEFAULT_EVIDENCE_DIR, submit, write_evidence, write_voucher_evidence
from .perps.risk import PerpsRiskDecision
from .perps.service import build_preview, decide, live_account_context
from .perps.service import inspect as inspect_market
from .perps.service import scan as scan_markets
from .venues.dreamdex_perps.adapter import PerpsAdapter
from .venues.dreamdex_perps.config import PerpsConfig
from .venues.dreamdex_perps.fixtures import FixturePerpsVenue
from .venues.dreamdex_perps.models import DataSource, PerpSide, plain

perps_app = typer.Typer(
    no_args_is_help=True,
    help="DreamDEX Perps (Hideki testnet): analytics -> execution cost -> risk -> paper/testnet.",
)


def _fail(exc: Exception, verbose: bool) -> None:
    if verbose and not isinstance(exc, EdgeLabError):
        raise exc
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _venue(source: str, now: int, config: PerpsConfig) -> Any:
    if source == "fixture":
        typer.secho("[SIMULATED FIXTURE — not live DreamDEX data]", fg=typer.colors.YELLOW, err=True)
        return FixturePerpsVenue(now)
    if source != "live":
        raise EdgeLabError("--source must be live or fixture")
    return PerpsAdapter(config)


def _dec(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise EdgeLabError(f"{name} must be a decimal number, got {value!r}") from exc


def _side(value: str) -> PerpSide:
    v = value.strip().upper()
    if v not in ("LONG", "SHORT"):
        raise EdgeLabError("--side must be long or short")
    return PerpSide(v)


def _echo_json(data: Any) -> None:
    typer.echo(jsonlib.dumps(data, indent=2, default=str))


def _label(source: DataSource) -> str:
    return "LIVE TESTNET (Hideki 50383)" if source is DataSource.LIVE else "SIMULATED FIXTURE"


def _print_decision(d: PerpsRiskDecision) -> None:
    for c in d.checks:
        typer.echo(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    verdict = "APPROVED" if d.approved else "BLOCKED"
    typer.secho(f"  => {verdict} ({d.mode})", fg=typer.colors.GREEN if d.approved else typer.colors.YELLOW)


@perps_app.command()
def markets(
    source: str = typer.Option("live", "--source", help="live | fixture"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Discover perp markets and their per-market precision parameters."""
    now = int(time.time())
    try:
        venue = _venue(source, now, PerpsConfig.from_env())
        rows = venue.list_markets()
        if json_out:
            _echo_json({"source": venue.source.value, "markets": [m.to_dict() for m in rows]})
            return
        typer.echo(f"[{_label(venue.source)}] {len(rows)} markets")
        typer.echo(f"{'symbol':<14} {'pool':<44} {'bd':>3} {'tick':>12} {'lot':>14} {'min':>14} {'maxLev':>6}")
        for m in rows:
            typer.echo(
                f"{m.symbol:<14} {m.market_id:<44} {m.base_decimals:>3} {plain(m.tick_size):>12} "
                f"{plain(m.lot_size):>14} {plain(m.min_quantity):>14} {plain(m.max_leverage) + 'x':>6}"
            )
        typer.echo("\nProtocol max leverage is informational; Edge Lab caps effective leverage at 1x.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def scan(
    source: str = typer.Option("live", "--source", help="live | fixture"),
    reference_notional: float = typer.Option(100.0, "--reference-notional", help="Probe size in quote units."),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Rank markets by the published category order, then by round-trip execution cost."""
    now = int(time.time())
    th = AssessmentThresholds(reference_notional=Decimal(str(reference_notional)))
    try:
        venue = _venue(source, now, PerpsConfig.from_env())
        res = scan_markets(venue, now, th)
        if json_out:
            _echo_json({**res, "assessments": [a.to_dict() for a in res["assessments"]]})
            return
        typer.echo(f"[{_label(venue.source)}] {res['count']} markets, probe {th.reference_notional} quote")
        typer.echo(
            f"{'symbol':<14} {'mark':>14} {'basisBps':>9} {'fund/yr':>9} {'sprdBps':>8} {'rtCostBps':>9} "
            f"{'vol24h':>8}  category"
        )
        for a in res["assessments"]:
            s24 = a.volatility.sigma_over(Decimal(24))
            typer.echo(
                f"{a.snapshot.market.symbol:<14} {_f(a.basis.mark, '0.0001'):>14} {_f(a.basis.bps, '0.01'):>9} "
                f"{_pct(a.funding.annualized):>9} {_f(a.liquidity.spread_bps, '0.01'):>8} "
                f"{_f(a.round_trip_cost_bps, '0.01'):>9} {_pct(s24):>8}  {a.category}"
            )
        for e in res["read_errors"]:
            typer.secho(f"  read error {e['market_id']}: {e['error']}", fg=typer.colors.YELLOW)
        typer.echo("\nObservations, not executable edge. No expected value is claimed (no predictive model).")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def inspect(
    market: str = typer.Argument(..., help="BTC, BTC-PERP, or a pool address"),
    source: str = typer.Option("live", "--source"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Full observed / cost / risk breakdown for one market."""
    now = int(time.time())
    try:
        venue = _venue(source, now, PerpsConfig.from_env())
        a = inspect_market(venue, market, now)
        d = a.to_dict()
        if json_out:
            _echo_json(d)
            return
        m = a.snapshot.market
        typer.echo(f"{m.symbol}  [{m.key}]  {_label(a.snapshot.source)}")
        typer.echo(f"category: {a.category}")
        for r in a.reasons:
            typer.echo(f"  - {r}")
        for section in ("funding", "basis", "liquidity", "volatility"):
            typer.echo(f"\n{section}:")
            for k, v in d["observed"][section].items():  # type: ignore[index]
                typer.echo(f"  {k}: {v}")
        typer.echo("\nexecution cost (probe):")
        typer.echo(jsonlib.dumps(d["execution_cost"], indent=2))
        typer.echo("\nrisk:")
        typer.echo(jsonlib.dumps(d["risk"], indent=2))
        typer.echo(f"\nexpected edge: {d['expected_edge']}")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def preview(
    market: str = typer.Argument(...),
    side: str = typer.Option(..., "--side", help="long | short"),
    size: str = typer.Option(..., "--size", help="Base-asset quantity, e.g. 0.001"),
    account: str | None = typer.Option(None, "--account", help="Public address (else PERPS_ACCOUNT)."),
    order_type: str = typer.Option("ioc", "--order-type", help="ioc | limit | post_only"),
    limit_price: str | None = typer.Option(None, "--limit-price"),
    source: str = typer.Option("live", "--source"),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Unsigned order preview: cost, margin, liquidation, paper + testnet eligibility. Signs nothing."""
    now = int(time.time())
    config = PerpsConfig.from_env()
    try:
        venue = _venue(source, now, config)
        s, q = _side(side), _dec(size, "--size")
        lp = _dec(limit_price, "--limit-price") if limit_price else None
        out = build_preview(
            venue, market, s, q, now, config=config, db_path=db_path, account=account,
            order_type=order_type, limit_price=lp,
        )  # fmt: skip
        paper: PerpsRiskDecision = out["paper"]
        testnet: PerpsRiskDecision | None = out["testnet"]
        if json_out:
            _echo_json({**out, "paper": paper.to_dict(), "testnet": testnet.to_dict() if testnet else None})
            return
        m = out["market"]
        typer.echo(f"{m['symbol']} {s.value} {q}  [{out['source']}]  — UNSIGNED PREVIEW")
        est = paper.execution
        if est:
            typer.echo(
                f"  est. avg price {_f(est.avg_price, '0.0001')}  notional {_f(est.notional, '0.0001')}  "
                f"slippage {_f(est.slippage_bps, '0.01')}bps  fee {est.fee_bps}bps  (book walk, not a fill)"
            )
        if paper.margin:
            mg = paper.margin
            typer.echo(
                f"  initial margin {_f(mg.initial_margin, '0.0001')}  est. liq {_f(mg.est_liquidation_price, '0.01')} "
                f"({mg.source}, vs paper equity)"
            )
        typer.echo("\nPaper eligibility (simulated equity):")
        _print_decision(paper)
        if testnet:
            typer.echo(f"\nTestnet eligibility (account={out['account'] or 'none'}):")
            _print_decision(testnet)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command(name="paper-trade")
def paper_trade(
    market: str = typer.Argument(...),
    side: str = typer.Option(..., "--side"),
    size: str = typer.Option(..., "--size"),
    source: str = typer.Option("live", "--source"),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Open a SIMULATED position filled from the observed book (no wallet)."""
    now = int(time.time())
    config = PerpsConfig.from_env()
    try:
        venue = _venue(source, now, config)
        s, q = _side(side), _dec(size, "--size")
        m = venue.resolve(market)
        snap = venue.get_snapshot(m.market_id)
        with PerpsPaperDB(db_path) as db:
            decision = decide(
                snap, s, q, now, mode="paper", equity=db.starting_equity, db=db,
                order_type="ioc", limit_price=None, config=config, preview=None,
            )  # fmt: skip
            if not decision.approved or decision.execution is None or decision.execution.avg_price is None:
                typer.secho("PAPER TRADE BLOCKED:", fg=typer.colors.YELLOW)
                _print_decision(decision)
                raise typer.Exit(1)
            est = decision.execution
            fee = est.notional * est.fee_bps / Decimal(10_000)
            pid = db.open_position(
                market_id=m.market_id,
                symbol=m.symbol,
                quote_decimals=m.quote_decimals,
                side=s,
                quantity=q,
                entry_price=est.avg_price,  # type: ignore[arg-type]
                entry_fee=fee,
                entry_cum_funding_raw=snap.state.projected_cumulative_funding_raw,
                price_source=f"SIMULATED_FILL_FROM_{snap.source.value}_BOOK",
            )
        typer.secho(
            f"PAPER #{pid} {s.value} {q} {m.symbol} @ {_f(est.avg_price, '0.0001')} "
            f"(simulated fill from {_label(snap.source)} book; slippage {_f(est.slippage_bps, '0.01')}bps)",
            fg=typer.colors.GREEN,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command(name="paper-close")
def paper_close(
    position_id: int = typer.Argument(...),
    source: str = typer.Option("live", "--source"),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Close a paper position against the current observed book."""
    now = int(time.time())
    try:
        venue = _venue(source, now, PerpsConfig.from_env())
        with PerpsPaperDB(db_path) as db:
            pos = db.get(position_id)
            snap = venue.get_snapshot(pos.market_id)
            exit_side = PerpSide.SHORT if pos.side is PerpSide.LONG else PerpSide.LONG
            est = walk_book(snap.book, exit_side, pos.quantity, snap.risk.taker_fee_bps)
            if not est.fully_filled or est.avg_price is None:
                raise EdgeLabError(f"book cannot absorb a {pos.quantity} close right now; position left open")
            fee = est.notional * est.fee_bps / Decimal(10_000)
            realized = db.close_position(
                position_id, exit_price=est.avg_price, exit_fee=fee,
                cum_funding_raw=snap.state.projected_cumulative_funding_raw,
            )  # fmt: skip
        typer.secho(
            f"Closed PAPER #{position_id} @ {_f(est.avg_price, '0.0001')}: realized {_f(realized, '0.000001')} "
            f"(simulated; includes estimated funding & fees)",
            fg=typer.colors.GREEN,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def _marks(venue: Any, market_ids: set[str]) -> dict[str, tuple[Decimal | None, int | None]]:
    if not market_ids:
        return {}
    snaps, _ = venue.snapshots(sorted(market_ids))
    return {s.market.market_id: (s.state.mark_price, s.state.projected_cumulative_funding_raw) for s in snaps}


@perps_app.command()
def positions(
    account: str | None = typer.Option(None, "--account", help="Public address for live testnet positions."),
    source: str = typer.Option("live", "--source"),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Paper positions (marked to market) and, with an account, live testnet positions."""
    now = int(time.time())
    config = PerpsConfig.from_env()
    try:
        venue = _venue(source, now, config)
        with PerpsPaperDB(db_path) as db:
            open_pos = db.list_positions("open")
            marks = _marks(venue, {p.market_id for p in open_pos})
        paper_rows = []
        for p in open_pos:
            mark, cum = marks.get(p.market_id, (None, None))
            paper_rows.append(
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "quantity": str(p.quantity),
                    "entry_price": str(p.entry_price),
                    "mark": None if mark is None else str(mark),
                    "unrealized_pnl": _f(p.unrealized(mark), "0.000001"),
                    "funding_paid_est": _f(p.funding_since_open(cum), "0.000001"),
                    "price_source": p.price_source,
                }
            )
        live = None
        acct = account or config.account
        if acct and isinstance(venue, PerpsAdapter):
            a = venue.get_account(acct)
            live = {
                "label": "LIVE TESTNET account state",
                "account": a.account,
                "equity": None if a.equity is None else str(a.equity),
                "voucher": a.voucher,
                "positions": [
                    {"symbol": p.symbol, "size": str(p.size), "avg_entry_price": str(p.avg_entry_price)}
                    for p in a.positions
                ],
            }
        if json_out:
            _echo_json({"paper": paper_rows, "testnet": live})
            return
        typer.echo("PAPER positions (simulated):")
        for r in paper_rows or [{"id": "-", "symbol": "(none)"}]:
            typer.echo(f"  {r}")
        if live:
            typer.echo(f"\nLIVE TESTNET {live['account']}: equity={live['equity']}")
            for row in live["positions"] or ["(flat)"]:  # type: ignore[list-item]
                typer.echo(f"  {row}")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def report(
    source: str = typer.Option("live", "--source", help="Source used to mark open paper positions."),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Paper P&L (realized / unrealized / funding) and recorded testnet order evidence."""
    now = int(time.time())
    try:
        venue = _venue(source, now, PerpsConfig.from_env())
        with PerpsPaperDB(db_path) as db:
            all_pos = db.list_positions()
            marks = _marks(venue, {p.market_id for p in all_pos if p.status == "open"})
            summary = db.summary(marks)
            orders = db.list_testnet_orders()
        history = [
            {
                "id": p.id,
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": str(p.quantity),
                "entry": str(p.entry_price),
                "exit": None if p.exit_price is None else str(p.exit_price),
                "status": p.status,
                "realized": None if p.realized_pnl is None else str(p.realized_pnl),
                "price_source": p.price_source,
            }
            for p in all_pos
        ]
        if json_out:
            _echo_json({"paper_summary": summary, "paper_history": history, "testnet_orders": orders})
            return
        typer.echo(f"PAPER summary: {summary}")
        for h in history:
            typer.echo(f"  {h}")
        typer.echo(f"\nTESTNET orders recorded: {len(orders)}")
        for o in orders:
            typer.echo(
                f"  #{o['id']} {o['side']} {o['quantity']} {o['symbol']} tx={o['tx_hash']} "
                f"receipt={o['receipt_status']} state={o['reconciled_status']}"
            )
        typer.echo("\nPaper results are simulated and are not evidence of strategy profitability.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def execute(
    market: str = typer.Argument(...),
    side: str = typer.Option(..., "--side"),
    size: str = typer.Option(..., "--size"),
    order_type: str = typer.Option("ioc", "--order-type", help="ioc | limit | post_only"),
    limit_price: str | None = typer.Option(None, "--limit-price"),
    yes: bool = typer.Option(False, "--yes", help="Confirm the real Hideki TESTNET transaction."),
    db_path: str = typer.Option(DEFAULT_PATH, "--db"),
    evidence_dir: str = typer.Option(DEFAULT_EVIDENCE_DIR, "--evidence-dir"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Submit a Hideki TESTNET perp order after every risk check passes and --yes is given."""
    now = int(time.time())
    config = PerpsConfig.from_env()
    try:
        blockers = config.write_blockers()
        if blockers:
            raise EdgeLabError("testnet execution not enabled: " + "; ".join(blockers))
        adapter = PerpsAdapter(config)
        s, q = _side(side), _dec(size, "--size")
        lp = _dec(limit_price, "--limit-price") if limit_price else None
        m = adapter.resolve(market)
        snap = adapter.get_snapshot(m.market_id)  # fresh book + state
        signer = adapter.signer_address()
        equity, exposure = live_account_context(adapter, signer, snap)
        draft = decide(
            snap, s, q, now, mode="testnet", equity=equity, db=None, order_type=order_type,
            limit_price=lp, config=config, preview=None, live_exposure=exposure,
        )  # fmt: skip
        official = None
        if draft.intent is not None:
            official = adapter.preview_order(
                m, is_bid=s.is_bid, price_raw=draft.intent.limit_price_raw,
                quantity_raw=draft.intent.quantity_raw, account=signer,
            )  # fmt: skip
        decision = decide(
            snap, s, q, int(time.time()), mode="testnet", equity=equity, db=None, order_type=order_type,
            limit_price=lp, config=config, preview=official, live_exposure=exposure,
        )  # fmt: skip
        typer.echo(f"Proposal: {s.value} {q} {m.symbol} [{m.key}] signer={signer} equity={equity}")
        if decision.intent:
            typer.echo(f"  limit {decision.intent.limit_price} ({order_type}), raw qty {decision.intent.quantity_raw}")
        _print_decision(decision)
        if not decision.approved:
            raise EdgeLabError("blocked by risk engine; nothing was submitted")
        if not yes:
            typer.secho("Refusing to submit without explicit --yes confirmation.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        result, rec = submit(adapter, decision.approval(), m)
        path = write_evidence(evidence_dir, decision=decision.to_dict(), result=result, reconciled=rec)
        with PerpsPaperDB(db_path) as db:
            db.record_testnet_order(
                {
                    "market_id": m.market_id,
                    "symbol": m.symbol,
                    "side": s.value,
                    "quantity": q,
                    "limit_price": decision.intent.limit_price if decision.intent else None,
                    "order_type": order_type,
                    "account": signer,
                    "tx_hash": rec.tx_hash,
                    "receipt_status": rec.receipt_status,
                    "block_number": rec.block_number,
                    "order_id": rec.order_id,
                    "filled_qty": rec.filled_qty,
                    "avg_fill_price": rec.avg_fill_price,
                    "reconciled_status": rec.status,
                    "position_after": rec.position_after,
                    "evidence_path": str(path),
                }
            )
        color = typer.colors.GREEN if rec.status in ("FILLED", "PARTIALLY_FILLED", "RESTING") else typer.colors.RED
        typer.secho(f"TESTNET tx {rec.tx_hash}: receipt={rec.receipt_status} state={rec.status}", fg=color)
        typer.echo(f"  {rec.detail}; position after = {rec.position_after}")
        typer.echo(f"  evidence: {path}")
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command("claim-voucher")
def claim_voucher(
    yes: bool = typer.Option(False, "--yes", help="Confirm the real Hideki TESTNET transaction."),
    evidence_dir: str = typer.Option(DEFAULT_EVIDENCE_DIR, "--evidence-dir"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Claim the signer's one-time 1,000 paper-USDso Perps credit on Hideki TESTNET (needs --yes)."""
    config = PerpsConfig.from_env()
    try:
        blockers = config.write_blockers()
        if blockers:
            raise EdgeLabError("testnet execution not enabled: " + "; ".join(blockers))
        adapter = PerpsAdapter(config)
        signer = adapter.signer_address()
        acct = adapter.get_account(signer)
        voucher = acct.voucher
        typer.echo(f"Signer {signer}: equity={acct.equity} USDso, voucher={voucher}")
        if voucher.get("eligible") is not True:
            raise EdgeLabError(f"voucher not claimable: {voucher.get('reason') or voucher.get('error') or voucher}")
        if not yes:
            typer.secho("Refusing to submit without explicit --yes confirmation.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        result = adapter.claim_voucher(confirmed=True)
        path = write_voucher_evidence(evidence_dir, result)
        status = (result.get("receipt") or {}).get("status")
        color = typer.colors.GREEN if status == "success" else typer.colors.RED
        typer.secho(f"TESTNET tx {result.get('txHash')}: receipt={status}", fg=color)
        after = adapter.get_account(signer)
        typer.echo(
            f"  Perps equity {acct.equity} -> {after.equity} USDso (re-read from MarginBank {result.get('marginBank')})"
        )
        typer.echo(f"  evidence: {path}")
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def receipt(
    tx_hash: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Re-read a testnet transaction receipt from the Hideki RPC (independent verification)."""
    try:
        r = PerpsAdapter(PerpsConfig.from_env()).get_receipt(tx_hash)
        if json_out:
            _echo_json(r)
            return
        typer.echo(f"tx {r.get('transactionHash')}: status={r.get('status')} block={r.get('blockNumber')}")
        typer.echo(f"  chainId={r.get('chainId')} from={r.get('from')} to={r.get('to')} logs={r.get('logCount')}")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@perps_app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    source: str = typer.Option("live", "--source", help="live | fixture"),
    cache_ttl: float = typer.Option(0.0, "--cache-ttl"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Serve the local dashboard; the Perps view is at /perps (preview only, no execution)."""
    from .dashboard.server import make_server

    try:
        server = make_server(
            host, port, source=source, assets=("BTC", "ETH"), size=Decimal(5), cache_ttl=cache_ttl, perps_source=source
        )
        label = "SIMULATED FIXTURE" if source == "fixture" else "LIVE Hideki testnet"
        typer.secho(f"DreamDEX Perps Edge Lab [{label}] → http://{host}:{port}/perps", fg=typer.colors.GREEN)
        typer.echo("Read-only decision support. Execution stays in the CLI. Ctrl+C to stop.")
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def _f(v: Decimal | None, places: str) -> str:
    return "-" if v is None else str(v.quantize(Decimal(places)))


def _pct(v: Decimal | None) -> str:
    return "-" if v is None else f"{(v * 100).quantize(Decimal('0.01'))}%"
