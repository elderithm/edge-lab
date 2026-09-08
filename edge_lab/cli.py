"""Typer CLI for Polymarket Edge Lab.

Human-readable output by default; ``--json`` emits stable machine-readable
output. Exit codes: 0 success, 1 user/data/runtime error, 2 invalid usage
(handled by Typer). Expected errors never print a traceback unless ``--verbose``.
"""

from __future__ import annotations

import json as jsonlib
import time
from decimal import Decimal
from typing import Any

import typer

from .analysis.arb import ArbResult, analyze_complete_set
from .analysis.cohort import build_cohort
from .analysis.price_series import summarize_price_series
from .analysis.reverse_engineer import build_reverse_engineering, write_artifacts
from .analysis.wallet import WalletAnalysis, analyze_wallet, parse_claim_window
from .api import ClobClient, DataClient, GammaClient, GeoblockClient
from .config import Settings
from .errors import EdgeLabError, NotFoundError
from .export.csv_export import write_activity_csv, write_arb_candidates_csv
from .http import HttpClient
from .models import Market
from .paper.db import PaperDB
from .paper.follower import FollowConfig, PaperFollower
from .paper.report import build_report

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Read-only Polymarket research and paper-trading toolkit.",
    pretty_exceptions_enable=False,  # we manage error output and exit codes ourselves
)

# DreamDEX Event Contracts (hackathon) mounted as an isolated command group.
# This does not alter any existing Polymarket command.
from .dreamdex_cli import dreamdex_app  # noqa: E402

app.add_typer(dreamdex_app, name="dreamdex")


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"edge-lab {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Read-only Polymarket research and paper-trading toolkit."""


def _echo_json(data: Any) -> None:
    typer.echo(jsonlib.dumps(data, indent=2, default=str))


def _fail(exc: Exception, verbose: bool) -> None:
    if verbose and not isinstance(exc, EdgeLabError):
        raise exc
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _settings(timeout: float | None) -> Settings:
    return Settings.from_env().with_overrides(http_timeout=timeout)


def _http(settings: Settings) -> HttpClient:
    return HttpClient(
        timeout=settings.http_timeout,
        user_agent=settings.user_agent,
        max_retries=settings.max_retries,
    )


# --- geo --------------------------------------------------------------------
@app.command()
def geo(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON."),
    timeout: float | None = typer.Option(None, "--timeout", help="HTTP timeout seconds."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Check the official geoblock status (informational only)."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            status = GeoblockClient(http, settings.geoblock_url).get_status()
        if json_out:
            _echo_json({"blocked": status.blocked, "country": status.country, "region": status.region})
            return
        typer.echo(f"country: {status.country or 'unknown'}")
        typer.echo(f"region:  {status.region or 'unknown'}")
        if status.blocked is None:
            typer.echo("status:  unknown (could not determine from response)")
        elif status.blocked:
            typer.echo("status:  BLOCKED — real trading is unavailable from this location.")
            typer.echo("This tool remains read-only research/paper-trading and will not bypass restrictions.")
        else:
            typer.echo("status:  not blocked. This tool still performs read-only research/paper trading only.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


# --- market -----------------------------------------------------------------
@app.command()
def market(
    slug: str = typer.Argument(..., help="Market slug."),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Display market metadata and a current price/order-book summary."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            gamma = GammaClient(http, settings.gamma_url)
            clob = ClobClient(http, settings.clob_url)
            mkt = gamma.get_market_by_slug(slug)
            summary = _market_summary(mkt, clob)
        if json_out:
            _echo_json(summary)
            return
        typer.echo(mkt.question)
        typer.echo(f"slug:         {mkt.slug}")
        typer.echo(f"condition_id: {mkt.condition_id}")
        typer.echo(f"active:       {mkt.active}  closed: {mkt.closed}  accepting_orders: {mkt.accepting_orders}")
        for tok in summary["tokens"]:
            typer.echo(
                f"  [{tok['outcome']}] token={tok['token_id']} best_ask={tok['best_ask']} best_bid={tok['best_bid']}"
            )
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def _market_summary(mkt: Market, clob: ClobClient) -> dict[str, Any]:
    tokens = []
    for tok in mkt.tokens:
        best_ask = best_bid = None
        try:
            book = clob.get_order_book(tok.token_id)
            best_ask = str(book.best_ask.price) if book.best_ask else None
            best_bid = str(book.best_bid.price) if book.best_bid else None
        except EdgeLabError:
            pass  # price summary is best-effort; metadata still shown
        tokens.append({"outcome": tok.outcome, "token_id": tok.token_id, "best_ask": best_ask, "best_bid": best_bid})
    return {
        "slug": mkt.slug,
        "question": mkt.question,
        "condition_id": mkt.condition_id,
        "active": mkt.active,
        "closed": mkt.closed,
        "accepting_orders": mkt.accepting_orders,
        "category": mkt.category,
        "tags": list(mkt.tags),
        "tokens": tokens,
    }


# --- price-history ----------------------------------------------------------
@app.command(name="price-history")
def price_history_cmd(
    token_id: str = typer.Argument(..., help="CLOB outcome token id."),
    interval: str = typer.Option("1d", "--interval", help="1m, 1h, 6h, 1d, 1w, or max."),
    fidelity: int | None = typer.Option(None, "--fidelity", help="Sampling resolution in minutes."),
    stats: bool = typer.Option(False, "--stats", help="Include descriptive series statistics."),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Historical mid-price series for an outcome token (read-only)."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            history = ClobClient(http, settings.clob_url).get_price_history(
                token_id, interval=interval, fidelity=fidelity
            )
        series_stats = summarize_price_series(history) if stats else None
        if json_out:
            payload = history.to_dict()
            if series_stats is not None:
                payload["stats"] = series_stats.to_dict()
            _echo_json(payload)
            return
        if history.is_empty:
            typer.echo(f"No price history returned for token {token_id} (interval={interval}).")
            return
        prices = [p.price for p in history.points]
        first, last = history.points[0], history.points[-1]
        typer.echo(f"token: {token_id}  interval: {interval}")
        typer.echo(f"points: {len(history.points)}")
        typer.echo(f"first:  {first.price} @ {_iso(first.timestamp)}")
        typer.echo(f"last:   {last.price} @ {_iso(last.timestamp)}")
        typer.echo(f"min/max: {min(prices)} / {max(prices)}")
        if series_stats is not None:
            typer.echo(
                f"total return: {series_stats.total_return}  "
                f"max drawdown: {series_stats.max_drawdown}  "
                f"per-step vol: {series_stats.per_step_return_volatility}"
            )
            typer.echo("(descriptive mid-price stats; not an execution backtest)")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def _iso(ts: int) -> str:
    from .models import iso_utc

    return iso_utc(ts)


# --- analyze-wallet ---------------------------------------------------------
@app.command(name="analyze-wallet")
def analyze_wallet_cmd(
    address: str = typer.Argument(..., help="Wallet address (0x...)."),
    max_records: int = typer.Option(5000, "--max-records"),
    utc_offset: int = typer.Option(0, "--utc-offset", help="Display timezone offset in hours."),
    claim_window: str | None = typer.Option(
        None, "--claim-window", help="Test a 'trades mainly START-END' claim, e.g. 6-9 (local hours)."
    ),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Fetch public activity and summarize behavior."""
    settings = _settings(timeout)
    try:
        window = parse_claim_window(claim_window) if claim_window else None
        with _http(settings) as http:
            data = DataClient(http, settings.data_url)
            activities = list(data.iter_activity(address, max_records=max_records))
        result = analyze_wallet(activities, utc_offset_hours=utc_offset)
        claim = result.window_claim(*window) if window else None
        if json_out:
            payload = result.to_dict()
            if claim is not None:
                payload["claim_window_evaluation"] = claim
            _echo_json(payload)
            return
        typer.echo(f"Retrieved {result.record_count} activities ({result.dated_count} dated).")
        if result.time_range:
            start, end = result.time_range
            typer.echo(f"Time range (UTC): {_iso(start)} → {_iso(end)}")
        typer.echo(f"BUY: {result.buy_count}  SELL: {result.sell_count}  other: {result.other_side_count}")
        typer.echo(f"Observed notional: {result.observed_notional} USDC")
        typer.echo(f"\nActivity by local hour (UTC{utc_offset:+d}):")
        peak = max(result.hour_local.values(), default=0)
        for h in range(24):
            c = result.hour_local.get(h, 0)
            bar = "#" * int((c / peak) * 30) if peak else ""
            pct = (c / result.dated_count * 100) if result.dated_count else 0
            typer.echo(f"  {h:02d}:00  {c:5d}  {pct:5.1f}%  {bar}")
        typer.echo("\nActivity by weekday (local):")
        wk_peak = max(result.weekday_local.values(), default=0)
        for day, count in result.weekday_local.items():
            bar = "#" * int((count / wk_peak) * 20) if wk_peak else ""
            typer.echo(f"  {day}  {count:5d}  {bar}")
        typer.echo("\nTop markets:")
        for m, c in result.market_concentration[:5]:
            typer.echo(f"  {c:5d}  {m[:70]}")
        typer.echo("\nOutcome/side concentration:")
        for outcome, c in result.outcome_concentration[:5]:
            typer.echo(f"  {c:5d}  {outcome[:40]}")
        typer.echo(f"\nEntry-price buckets: {result.price_buckets}")
        if claim is not None:
            typer.echo(
                f"\nClaim '{claim['window_local']}' (UTC{utc_offset:+d}): "
                f"{claim['inside_pct']}% inside ({claim['inside_count']}/{claim['dated_count']}), "
                f"{claim['outside_pct']}% outside."
            )
        for w in result.warnings:
            typer.secho(f"warning: {w}", fg=typer.colors.YELLOW, err=True)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


# --- analyze-cohort ---------------------------------------------------------
@app.command(name="analyze-cohort")
def analyze_cohort_cmd(
    addresses: list[str] = typer.Argument(..., help="Two or more wallet addresses."),
    max_records: int = typer.Option(2000, "--max-records"),
    utc_offset: int = typer.Option(0, "--utc-offset"),
    claim_window: str | None = typer.Option(None, "--claim-window", help="Shared window to compare, e.g. 6-9."),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Compare several wallets' behavior side by side (read-only)."""
    settings = _settings(timeout)
    try:
        window = parse_claim_window(claim_window) if claim_window else None
        analyses: list[tuple[str, WalletAnalysis]] = []
        with _http(settings) as http:
            data = DataClient(http, settings.data_url)
            for addr in addresses:
                acts = list(data.iter_activity(addr, max_records=max_records))
                analyses.append((addr, analyze_wallet(acts, utc_offset_hours=utc_offset)))
        cohort = build_cohort(analyses, utc_offset_hours=utc_offset, claim_window=window)
        if json_out:
            _echo_json(cohort.to_dict())
            return
        header = f"{'address':<14} {'recs':>6} {'buy':>5} {'sell':>5} {'b/s':>6} {'notional':>12} {'topshare':>8}"
        if window:
            header += f" {'win%':>6}"
        typer.echo(header)
        for r in cohort.rows:
            line = (
                f"{r.address[:14]:<14} {r.record_count:>6} {r.buy_count:>5} {r.sell_count:>5} "
                f"{str(r.buy_sell_ratio or '-'):>6} {str(r.observed_notional):>12} "
                f"{str(r.top_market_share or '-'):>8}"
            )
            if window:
                line += f" {str(r.window_share or '-'):>6}"
            typer.echo(line)
        for w in cohort.warnings:
            typer.secho(f"warning: {w}", fg=typer.colors.YELLOW, err=True)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


# --- export-wallet ----------------------------------------------------------
@app.command(name="export-wallet")
def export_wallet_cmd(
    address: str = typer.Argument(...),
    max_records: int = typer.Option(5000, "--max-records"),
    output: str = typer.Option("activity.csv", "--output", "-o"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Export public wallet activity to CSV (stable headers, ISO-8601 UTC)."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            data = DataClient(http, settings.data_url)
            activities = list(data.iter_activity(address, max_records=max_records))
        count = write_activity_csv(activities, output)
        typer.echo(f"Wrote {count} rows to {output}")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


# --- arb --------------------------------------------------------------------
@app.command()
def arb(
    slug: str = typer.Argument(...),
    notional: float = typer.Option(10.0, "--notional", help="Target USDC to deploy per complete set."),
    fee_buffer_bps: float = typer.Option(50.0, "--fee-buffer-bps"),
    slippage_buffer_bps: float = typer.Option(50.0, "--slippage-buffer-bps"),
    min_edge_bps: float = typer.Option(25.0, "--min-edge-bps"),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Size-aware complete-set (YES+NO) mispricing check for a binary market."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            gamma = GammaClient(http, settings.gamma_url)
            clob = ClobClient(http, settings.clob_url)
            mkt = gamma.get_market_by_slug(slug)
            result = _quote_market(mkt, clob, notional, fee_buffer_bps, slippage_buffer_bps, min_edge_bps)
        if result is None:
            raise NotFoundError(f"market {slug!r} is not a binary YES/NO market with order books")
        if json_out:
            _echo_json(result.to_dict())
            return
        _print_arb(result)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def _quote_market(
    mkt: Market,
    clob: ClobClient,
    notional: float,
    fee_bps: float,
    slip_bps: float,
    min_edge_bps: float,
) -> ArbResult | None:
    yes, no = mkt.yes_token, mkt.no_token
    if not mkt.is_binary or yes is None or no is None:
        return None
    yes_book = clob.get_order_book(yes.token_id)
    no_book = clob.get_order_book(no.token_id)
    return analyze_complete_set(
        mkt,
        yes_book,
        no_book,
        notional=Decimal(str(notional)),
        fee_buffer_bps=Decimal(str(fee_bps)),
        slippage_buffer_bps=Decimal(str(slip_bps)),
        min_edge_bps=Decimal(str(min_edge_bps)),
    )


def _print_arb(r: ArbResult) -> None:
    typer.echo(r.question)
    typer.echo(f"slug: {r.slug}")
    typer.echo(f"raw top-of-book YES+NO sum: {r.top_of_book_sum}")
    typer.echo(
        f"notional budget: ${r.notional_budget}  executable size: {r.executable_quantity} sets "
        f"(fully_filled={r.fully_filled})"
    )
    typer.echo(f"size-aware YES cost: {r.yes_cost} (vwap {r.yes_vwap})")
    typer.echo(f"size-aware NO  cost: {r.no_cost} (vwap {r.no_vwap})")
    typer.echo(f"cost per complete set: {r.cost_per_set}")
    typer.echo(f"gross edge: {r.gross_edge_bps} bps  buffers: {r.buffer_bps} bps  net edge: {r.net_edge_bps} bps")
    typer.echo(f"max size at >= min-edge: {r.max_size_at_min_edge}")
    if r.is_candidate:
        typer.secho(f"CANDIDATE: {r.note}", fg=typer.colors.GREEN)
    else:
        typer.echo(f"no candidate: {r.note}")


# --- scan-arbs --------------------------------------------------------------
@app.command(name="scan-arbs")
def scan_arbs_cmd(
    limit: int = typer.Option(100, "--limit", help="Max markets to fetch."),
    top: int = typer.Option(20, "--top", help="Max candidates to display."),
    notional: float = typer.Option(10.0, "--notional"),
    fee_buffer_bps: float = typer.Option(50.0, "--fee-buffer-bps"),
    slippage_buffer_bps: float = typer.Option(50.0, "--slippage-buffer-bps"),
    min_edge_bps: float = typer.Option(25.0, "--min-edge-bps"),
    output: str | None = typer.Option(None, "--output", "-o", help="Write all scanned results to a CSV."),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Scan active binary markets for size-aware paper-edge candidates."""
    settings = _settings(timeout)
    scanned = skipped = 0
    results: list[ArbResult] = []
    try:
        with _http(settings) as http:
            gamma = GammaClient(http, settings.gamma_url)
            clob = ClobClient(http, settings.clob_url)
            for mkt in gamma.iter_markets(max_markets=limit):
                if not (mkt.is_binary and mkt.yes_token and mkt.no_token and mkt.accepting_orders):
                    continue
                scanned += 1
                try:
                    r = _quote_market(mkt, clob, notional, fee_buffer_bps, slippage_buffer_bps, min_edge_bps)
                except EdgeLabError:
                    skipped += 1  # a single market failure must not abort the scan
                    continue
                if r is not None:
                    results.append(r)
        results.sort(key=lambda r: r.net_edge_bps, reverse=True)
        candidates = [r for r in results if r.is_candidate][:top]
        if output:
            rows = write_arb_candidates_csv(results, output)
            typer.echo(f"Wrote {rows} scanned market rows to {output}")
        if json_out:
            _echo_json(
                {
                    "scanned": scanned,
                    "skipped": skipped,
                    "candidates": [r.to_dict() for r in candidates],
                }
            )
            return
        typer.echo(f"Scanned {scanned} binary markets ({skipped} skipped on errors).")
        if not candidates:
            typer.echo("No candidates above threshold in this sample.")
            return
        typer.echo(f"{'net_bps':>9}  {'gross_bps':>9}  {'cost/set':>9}  {'exec_size':>10}  slug")
        for r in candidates:
            typer.echo(
                f"{r.net_edge_bps:>9}  {r.gross_edge_bps:>9}  {r.cost_per_set:>9}  "
                f"{r.executable_quantity:>10}  {r.slug}"
            )
        typer.echo("\nNote: apparent paper edges only; observations, not real fills.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


# --- paper-follow -----------------------------------------------------------
@app.command(name="paper-follow")
def paper_follow_cmd(
    address: str = typer.Argument(...),
    paper_usdc: float = typer.Option(10.0, "--paper-usdc"),
    max_age: int = typer.Option(120, "--max-age", help="Max signal age seconds."),
    max_drift_bps: float = typer.Option(300.0, "--max-drift-bps"),
    fee_buffer_bps: float = typer.Option(50.0, "--fee-buffer-bps"),
    slippage_buffer_bps: float = typer.Option(50.0, "--slippage-buffer-bps"),
    poll: float = typer.Option(5.0, "--poll", help="Seconds between polls."),
    latest: int = typer.Option(100, "--latest", help="Activities to fetch per poll."),
    once: bool = typer.Option(False, "--once", help="Run a single poll and exit."),
    new_run: bool = typer.Option(False, "--new-run", help="Start a fresh run instead of resuming."),
    db_path: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Forward paper-follow a public wallet (never places real orders)."""
    settings = _settings(None)
    path = db_path or settings.db_path
    cfg = FollowConfig(
        paper_usdc=Decimal(str(paper_usdc)),
        max_age_seconds=max_age,
        max_drift_bps=Decimal(str(max_drift_bps)),
        fee_buffer_bps=Decimal(str(fee_buffer_bps)),
        slippage_buffer_bps=Decimal(str(slippage_buffer_bps)),
    )
    db = PaperDB(path)
    try:
        with _http(settings) as http:
            data = DataClient(http, settings.data_url)
            clob = ClobClient(http, settings.clob_url)
            run_id = None if new_run else db.latest_run_id(address)
            if run_id is None:
                run_id = db.create_run(address, jsonlib.dumps({"paper_usdc": paper_usdc, "max_age": max_age}))
                typer.echo(f"Started paper run #{run_id} for {address}")
            else:
                typer.echo(f"Resuming paper run #{run_id} for {address}")
            follower = PaperFollower(db, clob, run_id, cfg)
            while True:
                activities = data.get_activity(address, limit=latest)
                outcomes = follower.process_activities(activities, int(time.time()))
                for o in outcomes:
                    if o.disposition != "duplicate":
                        typer.echo(o.message, nl=True)
                if once:
                    break
                time.sleep(poll)
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
        raise typer.Exit(130) from None
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)
    finally:
        db.close()


# --- paper-runs -------------------------------------------------------------
@app.command(name="paper-runs")
def paper_runs_cmd(
    db_path: str | None = typer.Option(None, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """List paper runs in the database (for use with paper-report --run-id)."""
    settings = _settings(None)
    path = db_path or settings.db_path
    db = PaperDB(path)
    try:
        runs = db.list_runs()
        rows = []
        for r in runs:
            rid = int(r["id"])
            rows.append(
                {
                    "run_id": rid,
                    "created_at": _iso(int(r["created_at"])),
                    "source_wallet": r["source_wallet"],
                    "status": r["status"],
                    "signals": len(db.signals(rid)),
                    "fills": len(db.fills(rid)),
                }
            )
        if json_out:
            _echo_json({"runs": rows})
            return
        if not rows:
            typer.echo(f"No paper runs in {path}.")
            return
        typer.echo(f"{'id':>4}  {'created (UTC)':<20}  {'signals':>7}  {'fills':>5}  wallet")
        for row in rows:
            typer.echo(
                f"{row['run_id']:>4}  {row['created_at']:<20}  "
                f"{row['signals']:>7}  {row['fills']:>5}  {row['source_wallet']}"
            )
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)
    finally:
        db.close()


# --- paper-report -----------------------------------------------------------
@app.command(name="paper-report")
def paper_report_cmd(
    run_id: int | None = typer.Option(None, "--run-id"),
    mark: bool = typer.Option(False, "--mark", help="Fetch current prices to mark open positions."),
    db_path: str | None = typer.Option(None, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Report realized and mark-to-market P&L for a paper run, separately."""
    settings = _settings(timeout)
    path = db_path or settings.db_path
    db = PaperDB(path)
    http: HttpClient | None = None
    try:
        rid = run_id if run_id is not None else db.latest_run_id()
        if rid is None:
            raise EdgeLabError("no paper runs found in database")
        provider = None
        if mark:
            http = _http(settings)
            clob = ClobClient(http, settings.clob_url)

            def provider(token_id: str) -> Decimal | None:
                try:
                    return clob.get_price(token_id, "SELL")  # mark a long at exitable bid
                except EdgeLabError:
                    return None

        report = build_report(db, rid, provider)
        if json_out:
            _echo_json(report.to_dict())
            return
        typer.echo(f"Paper run #{report.run_id}")
        typer.echo(
            f"signals: observed={report.signals_observed} filled={report.signals_filled} "
            f"skipped={report.signals_skipped} fill_rate={report.fill_rate}"
        )
        if report.skip_reasons:
            typer.echo(f"skip reasons: {report.skip_reasons}")
        typer.echo(f"signal age (s): median={report.median_age_seconds} p90={report.p90_age_seconds}")
        typer.echo(f"buy drift (bps): median={report.median_drift_bps} p90={report.p90_drift_bps}")
        typer.echo(f"realized P&L:   {report.realized_pnl}")
        if report.max_realized_drawdown is not None:
            typer.echo(f"max realized drawdown: {report.max_realized_drawdown}")
        if report.unrealized_pnl is None:
            typer.echo("unrealized P&L: unknown (open positions could not be marked; pass --mark)")
        else:
            typer.echo(f"unrealized P&L: {report.unrealized_pnl} (mark-to-market)")
            typer.echo(f"total net P&L:  {report.total_net_pnl}")
        typer.echo(f"buy/sell notional: {report.buy_notional} / {report.sell_notional}")
        if report.open_positions:
            typer.echo(f"\nOpen positions ({len(report.open_positions)}):")
            for p in report.open_positions:
                mark_str = "unmarked" if p.mark_price is None else f"mark {p.mark_price}"
                unreal = "n/a" if p.unrealized is None else f"{p.unrealized:+}"
                label = (p.title or p.asset)[:48]
                typer.echo(f"  {p.quantity} @ avg {p.avg_entry}  ({mark_str}, unrealized {unreal})  {label}")
        typer.echo("Note: realized and unrealized are reported separately; net cash flow is not P&L.")
        for w in report.warnings:
            typer.secho(f"warning: {w}", fg=typer.colors.YELLOW, err=True)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)
    finally:
        if http is not None:
            http.close()
        db.close()


# --- reverse-engineer-wallet ------------------------------------------------
@app.command(name="reverse-engineer-wallet")
def reverse_engineer_cmd(
    address: str = typer.Argument(...),
    max_records: int = typer.Option(5000, "--max-records"),
    utc_offset: int = typer.Option(0, "--utc-offset"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for report artifacts."),
    timeout: float | None = typer.Option(None, "--timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Reverse-engineer candidate strategy patterns and write report artifacts."""
    settings = _settings(timeout)
    try:
        with _http(settings) as http:
            data = DataClient(http, settings.data_url)
            activities = list(data.iter_activity(address, max_records=max_records))
        result = build_reverse_engineering(activities, address=address, utc_offset_hours=utc_offset)
        paths = write_artifacts(result, activities, output_dir)
        typer.echo(f"Analyzed {result.facts['record_count']} activities for {address}.")
        for name, p in paths.items():
            typer.echo(f"  {name}: {p}")
        typer.echo(f"Generated {len(result.candidates)} candidate pattern(s). See report.md for caveats.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point.

    ``standalone_mode=False`` makes Click return the exit code (or raise its
    control-flow exceptions) instead of calling ``sys.exit`` itself. Both the
    stock ``click`` exceptions and Typer's vendored ``typer._click`` variants
    carry an ``exit_code`` (2 for usage errors), so we duck-type on it.
    """
    try:
        code = app(args=argv, standalone_mode=False)
        return code if isinstance(code, int) else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        typer.echo("Aborted.", err=True)
        return 130
    except BaseException as exc:  # noqa: BLE001
        exit_code = getattr(exc, "exit_code", None)
        if exit_code is None:
            if type(exc).__name__ == "Abort":  # click/typer Abort control flow
                typer.echo("Aborted.", err=True)
                return 1
            raise
        show = getattr(exc, "show", None)
        if callable(show):
            try:
                show()
            except Exception:  # noqa: BLE001
                pass
        return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
