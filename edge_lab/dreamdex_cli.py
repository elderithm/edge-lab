"""DreamDEX Edge Lab CLI (mounted as ``edge-lab dreamdex ...``).

Deterministic decision-support: discover live DreamDEX Event Contracts, estimate
an independent probability, compute executable edge, run risk checks, and paper-
or testnet-trade. Paper is the default and needs no wallet. Mainnet is disabled.
"""

from __future__ import annotations

import json as jsonlib
import time
from decimal import Decimal
from typing import Any

import typer

from .core.risk import RiskConfig, RiskEngine
from .core.signal import Signal
from .core.types import Side, TradingMode
from .dashboard.server import make_server
from .dashboard.service import scan_signals
from .errors import EdgeLabError
from .paper.dreamdex_paper import DreamdexPaperDB
from .strategies.event_contracts import build_event_signal
from .venues.base import OrderRequest
from .venues.dreamdex.adapter import DreamdexAdapter
from .venues.dreamdex.config import DreamdexConfig
from .venues.dreamdex.fixtures import FixtureVenue

dreamdex_app = typer.Typer(
    no_args_is_help=True,
    help="DreamDEX Event Contracts: probability -> edge -> risk -> paper/testnet.",
)


def _fail(exc: Exception, verbose: bool) -> None:
    if verbose and not isinstance(exc, EdgeLabError):
        raise exc
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _source(source: str, now: int, config: DreamdexConfig) -> Any:
    if source == "fixture":
        typer.secho("[SIMULATED FIXTURE — not live DreamDEX data]", fg=typer.colors.YELLOW, err=True)
        return FixtureVenue(now)
    return DreamdexAdapter(config)


def _risk_engine(min_edge_bps: float | None) -> RiskEngine:
    cfg = RiskConfig()
    if min_edge_bps is not None:
        cfg = RiskConfig(
            min_edge_bps=Decimal(str(min_edge_bps)),
            min_confidence=cfg.min_confidence,
            min_time_to_expiry_seconds=cfg.min_time_to_expiry_seconds,
            max_price_age_seconds=cfg.max_price_age_seconds,
            max_market_data_age_seconds=cfg.max_market_data_age_seconds,
            max_slippage_bps=cfg.max_slippage_bps,
            max_position_per_market=cfg.max_position_per_market,
            max_total_exposure=cfg.max_total_exposure,
        )
    return RiskEngine(cfg)


def _signal_for(venue: Any, market_id: str, size: Decimal, now: int, engine: RiskEngine) -> Signal:
    market = venue.get_market(market_id)
    book = venue.get_order_book(market_id)
    underlying = venue.get_underlying(market.asset)
    return build_event_signal(market, book, underlying, size=size, now=now, risk_engine=engine)


def _echo_json(data: Any) -> None:
    typer.echo(jsonlib.dumps(data, indent=2, default=str))


@dreamdex_app.command()
def scan(
    assets: str = typer.Option("BTC,ETH", "--assets", help="Comma-separated assets."),
    size: float = typer.Option(10.0, "--size", help="Intended paper size (outcome tokens)."),
    min_edge_bps: float | None = typer.Option(None, "--min-edge-bps"),
    source: str = typer.Option("live", "--source", help="live | fixture"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Scan BTC/ETH Event Contracts and rank risk-adjusted opportunities."""
    now = int(time.time())
    config = DreamdexConfig.from_env()
    engine = _risk_engine(min_edge_bps)
    asset_list = [a.strip().upper() for a in assets.split(",") if a.strip()]
    try:
        venue = _source(source, now, config)
        signals = scan_signals(venue, asset_list, size=Decimal(str(size)), now=now, risk_engine=engine)
        if json_out:
            _echo_json({"scanned": len(signals), "signals": [s.to_dict() for s in signals]})
            return
        if not signals:
            typer.echo("No markets available.")
            return
        header = f"{'asset·win':<14} {'tte':>7} {'upAsk':>8} {'pUp':>9} {'edgeBps':>9} {'conf':>7}  signal"
        typer.echo(header)
        for s in signals:
            up = s.edge.up
            tte = s.market.time_to_expiry(now)
            typer.echo(
                f"{(s.market.asset + '·' + (s.market.window_label or '?')):<14} "
                f"{(str(tte) + 's' if tte is not None else '?'):>7} "
                f"{(str(up.top_ask) if up.top_ask is not None else '-'):>8} "
                f"{str(s.probability.p_up):>9} "
                f"{(str(s.risk.edge_bps) if s.risk.edge_bps is not None else '-'):>9} "
                f"{str(s.probability.confidence):>7}  {s.state.value}"
            )
        typer.echo("\nModel estimates, not profit guarantees. Ranked by edge × confidence × liquidity.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def inspect(
    market_id: str = typer.Argument(...),
    size: float = typer.Option(10.0, "--size"),
    min_edge_bps: float | None = typer.Option(None, "--min-edge-bps"),
    source: str = typer.Option("live", "--source"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Show the full auditable reasoning chain for one market."""
    now = int(time.time())
    config = DreamdexConfig.from_env()
    engine = _risk_engine(min_edge_bps)
    try:
        venue = _source(source, now, config)
        sig = _signal_for(venue, market_id, Decimal(str(size)), now, engine)
        if json_out:
            _echo_json(sig.to_dict())
            return
        m = sig.market
        typer.echo(f"{m.symbol}  [{m.key}]")
        typer.echo(f"status={m.status.value} window={m.window_label} expiry={m.expiry} opening={m.opening_reference}")
        typer.echo(f"\nModel: {sig.probability.model_version}")
        for k, v in sig.probability.inputs.items():
            typer.echo(f"  {k}: {v}")
        typer.echo(
            f"  P(Up)={sig.probability.p_up}  P(Down)={sig.probability.p_down}  confidence={sig.probability.confidence}"
        )
        typer.echo("\nEdge (executable, size-aware):")
        for label, se in (("UP  ", sig.edge.up), ("DOWN", sig.edge.down)):
            typer.echo(
                f"  {label} top_ask={se.top_ask} exec_ask={se.executable_ask} exec_edge={se.executable_edge_bps}bps"
            )
        typer.echo(f"  buffers={sig.edge.buffer_bps}bps")
        typer.echo("\nRisk checks:")
        for c in sig.risk.checks:
            mark = "PASS" if c.passed else "FAIL"
            typer.echo(f"  [{mark}] {c.name}: {c.detail}")
        typer.echo(f"\nSignal: {sig.state.value}  rank={sig.rank_score}")
        typer.echo(sig.explanation)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command(name="paper-trade")
def paper_trade(
    market_id: str = typer.Argument(...),
    size: float = typer.Option(10.0, "--size"),
    min_edge_bps: float | None = typer.Option(None, "--min-edge-bps"),
    source: str = typer.Option("live", "--source"),
    db_path: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Simulate a fill for an actionable signal (no wallet, real market data)."""
    now = int(time.time())
    config = DreamdexConfig.from_env()
    engine = _risk_engine(min_edge_bps)
    path = db_path or ".edge-lab/dreamdex-paper.db"
    try:
        venue = _source(source, now, config)
        sig = _signal_for(venue, market_id, Decimal(str(size)), now, engine)
        if not sig.risk.is_actionable or sig.risk.side is None or sig.risk.price is None:
            typer.echo(f"NO PAPER TRADE: {sig.state.value} — {sig.explanation}")
            raise typer.Exit(0)
        with DreamdexPaperDB(path) as db:
            trade_id = db.record_trade(
                venue=sig.market.venue,
                market_id=sig.market.market_id,
                asset=sig.market.asset,
                symbol=sig.market.symbol,
                side=sig.risk.side,
                model_p=sig.probability.p_up if sig.risk.side == Side.UP else sig.probability.p_down,
                exec_price=sig.risk.price,
                edge_bps=sig.risk.edge_bps or Decimal(0),
                size=sig.risk.allowed_size,
                confidence=sig.probability.confidence,
                mode="paper",
            )
        typer.secho(
            f"PAPER {sig.risk.side.value} #{trade_id}: {sig.risk.allowed_size} @ {sig.risk.price} "
            f"(edge {sig.risk.edge_bps}bps, conf {sig.probability.confidence}) | {sig.market.symbol}",
            fg=typer.colors.GREEN,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def settle(
    trade_id: int = typer.Argument(...),
    outcome: str = typer.Argument(..., help="UP | DOWN | VOID"),
    db_path: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Settle a paper trade against a resolved/voided outcome."""
    path = db_path or ".edge-lab/dreamdex-paper.db"
    try:
        with DreamdexPaperDB(path) as db:
            pnl = db.settle_trade(trade_id, outcome)
        typer.echo(f"Settled paper trade #{trade_id} as {outcome.upper()}: realized P&L {pnl}")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def report(
    db_path: str | None = typer.Option(None, "--db"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Show paper-trading summary and trades (realized vs. open expected value)."""
    path = db_path or ".edge-lab/dreamdex-paper.db"
    try:
        with DreamdexPaperDB(path) as db:
            summary = db.summary()
            trades = db.list_trades()
        if json_out:
            _echo_json({"summary": summary, "trades": [t.__dict__ for t in trades]})
            return
        typer.echo(f"summary: {summary}")
        for t in trades:
            typer.echo(
                f"  #{t.id} {t.side} {t.asset} size={t.size} @ {t.exec_price} "
                f"status={t.status} outcome={t.outcome} realized={t.realized_pnl}"
            )
        typer.echo("\nRealized P&L is settled-only; open trades show expected value. Not a guarantee.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def preview(
    market_id: str = typer.Argument(...),
    side: str | None = typer.Option(None, "--side", help="UP | DOWN (omit to derive from the live signal)."),
    price: float | None = typer.Option(
        None, "--price", help="Limit price [0,1] (omit to use the signal's executable price)."
    ),
    size: float = typer.Option(5.0, "--size"),
    min_edge_bps: float | None = typer.Option(None, "--min-edge-bps"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Rehearse a testnet order (resolve pool + on-chain status + raw params) WITHOUT signing.

    Needs no wallet. Pass --side/--price to rehearse a specific order on any live
    market, or omit them to preview the order the signal would produce.
    """
    now = int(time.time())
    config = DreamdexConfig.from_env()
    engine = _risk_engine(min_edge_bps)
    try:
        adapter = DreamdexAdapter(config)
        if side and price is not None:
            req = OrderRequest(market_id, Side(side.upper()), Decimal(str(size)), Decimal(str(price)))
        else:
            sig = _signal_for(adapter, market_id, Decimal(str(size)), now, engine)
            if not sig.risk.is_actionable or sig.risk.side is None or sig.risk.price is None:
                raise EdgeLabError(
                    f"no actionable signal ({sig.state.value}); pass explicit --side and --price to rehearse anyway"
                )
            req = OrderRequest(market_id, sig.risk.side, sig.risk.allowed_size, sig.risk.price)
        result = adapter.preview_order(req)
        _echo_json(result)
        if result.get("wouldSubmit"):
            typer.secho("Dry run OK — params valid, nothing signed or submitted.", fg=typer.colors.GREEN)
        else:
            typer.secho(f"Would NOT submit: {result.get('note')}", fg=typer.colors.YELLOW)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def execute(
    market_id: str = typer.Argument(...),
    size: float = typer.Option(10.0, "--size"),
    min_edge_bps: float | None = typer.Option(None, "--min-edge-bps"),
    yes: bool = typer.Option(False, "--yes", help="Confirm the real (testnet) transaction."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Submit a real DreamDEX order (testnet). Requires TRADING_MODE=testnet + signer + confirmation."""
    now = int(time.time())
    config = DreamdexConfig.from_env()
    engine = _risk_engine(min_edge_bps)
    try:
        if config.trading_mode == TradingMode.PAPER:
            raise EdgeLabError("TRADING_MODE=paper; execution disabled. Set TRADING_MODE=testnet to submit.")
        adapter = DreamdexAdapter(config)
        sig = _signal_for(adapter, market_id, Decimal(str(size)), now, engine)
        if not sig.risk.is_actionable or sig.risk.side is None:
            raise EdgeLabError(f"not executable: {sig.state.value} — {sig.explanation}")
        typer.echo(
            f"Proposal: {sig.risk.side.value} {sig.risk.allowed_size} @ ~{sig.risk.price} "
            f"(edge {sig.risk.edge_bps}bps) on {sig.market.symbol} [{config.network}]"
        )
        for c in sig.risk.checks:
            typer.echo(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}")
        if not yes:
            typer.secho("Refusing to execute without explicit --yes confirmation.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        result = adapter.place_order(
            OrderRequest(
                market_id=sig.market.market_id,
                side=sig.risk.side,
                size=sig.risk.allowed_size,
                limit_price=sig.risk.price,
                order_type="limit",
            )
        )
        typer.secho(f"Submitted ({config.network}): {result.detail}", fg=typer.colors.GREEN)
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)


@dreamdex_app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    source: str = typer.Option("live", "--source", help="live | fixture"),
    assets: str = typer.Option("BTC,ETH", "--assets"),
    size: float = typer.Option(5.0, "--size"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Serve the read-only DreamDEX Edge Lab dashboard (decision-support only)."""
    asset_tuple = tuple(a.strip().upper() for a in assets.split(",") if a.strip())
    try:
        server = make_server(host, port, source=source, assets=asset_tuple, size=Decimal(str(size)))
        label = "SIMULATED FIXTURE" if source == "fixture" else "LIVE Shannon testnet"
        typer.secho(f"DreamDEX Edge Lab dashboard [{label}] → http://{host}:{port}", fg=typer.colors.GREEN)
        typer.echo("Read-only decision-support. Execution stays in the CLI. Ctrl+C to stop.")
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    except Exception as exc:  # noqa: BLE001
        _fail(exc, verbose)
