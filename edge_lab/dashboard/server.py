"""Local read-only dashboard HTTP server (Python stdlib only).

Serves a single self-contained page plus JSON endpoints that run the same
probability → edge → risk pipeline as the CLI. It is decision-support only:
there is NO execution from the dashboard (that stays in the CLI behind an
explicit ``--yes`` confirmation), per the "no unattended real-money UI" rule.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..core.risk import RiskEngine
from ..errors import EdgeLabError
from ..strategies.event_contracts import build_event_signal
from ..venues.dreamdex.adapter import DreamdexAdapter
from ..venues.dreamdex.config import DreamdexConfig
from ..venues.dreamdex.fixtures import FixtureVenue
from .page import PAGE_HTML
from .service import scan_signals

# Process-wide TTL cache so a slow live scan is fetched once and reused (e.g.
# during a screen recording, or across rapid dashboard refreshes).
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _venue(source: str, now: int) -> Any:
    if source == "fixture":
        return FixtureVenue(now)
    return DreamdexAdapter(DreamdexConfig.from_env())


class _Handler(BaseHTTPRequestHandler):
    # configured by make_server()
    source: str = "live"
    assets: tuple[str, ...] = ("BTC", "ETH")
    size: Decimal = Decimal("5")
    cache_ttl: float = 0.0  # 0 = always fetch fresh

    def log_message(self, *_a: Any) -> None:  # quiet
        pass

    def _cached(self, key: str, compute: Callable[[], Any]) -> Any:
        if self.cache_ttl > 0:
            now = time.time()
            with _CACHE_LOCK:
                hit = _CACHE.get(key)
                if hit is not None and now - hit[0] < self.cache_ttl:
                    return hit[1]
        value = compute()  # computed outside the lock (may be slow)
        if self.cache_ttl > 0:
            with _CACHE_LOCK:
                _CACHE[key] = (time.time(), value)
        return value

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/health":
                self._json(200, {"ok": True, "source": self.source})
            elif path == "/api/scan":
                self._json(200, self._scan(query))
            elif path == "/api/inspect":
                self._json(200, self._inspect(query))
            else:
                self._json(404, {"error": "not found"})
        except EdgeLabError as exc:
            self._json(200, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _scan(self, query: dict[str, list[str]]) -> dict[str, Any]:
        source = (query.get("source", [self.source])[0]) or self.source
        assets = [a.upper() for a in (query.get("assets", [",".join(self.assets)])[0]).split(",") if a]

        def compute() -> dict[str, Any]:
            now = int(time.time())
            venue = _venue(source, now)
            signals = scan_signals(venue, assets, size=self.size, now=now, risk_engine=RiskEngine())
            return {
                "generated_at": now,
                "source": "SIMULATED" if source == "fixture" else "LIVE_DREAMDEX",
                "signals": [s.to_dict() for s in signals],
            }

        return self._cached(f"scan:{source}:{','.join(assets)}", compute)

    def _inspect(self, query: dict[str, list[str]]) -> dict[str, Any]:
        market_id = query.get("market_id", [""])[0]
        source = (query.get("source", [self.source])[0]) or self.source
        if not market_id:
            return {"error": "market_id required"}

        def compute() -> dict[str, Any]:
            now = int(time.time())
            venue = _venue(source, now)
            market = venue.get_market(market_id)
            book = venue.get_order_book(market_id)
            und = venue.get_underlying(market.asset)
            sig = build_event_signal(market, book, und, size=self.size, now=now, risk_engine=RiskEngine())
            payload = sig.to_dict()
            payload["order_book"] = {
                "up_asks": [[str(lv.price), str(lv.size)] for lv in book.up.asks],
                "down_asks": [[str(lv.price), str(lv.size)] for lv in book.down.asks],
            }
            payload["generated_at"] = now
            return payload

        return self._cached(f"inspect:{source}:{market_id}", compute)


def make_server(
    host: str, port: int, *, source: str, assets: tuple[str, ...], size: Decimal, cache_ttl: float = 0.0
) -> ThreadingHTTPServer:
    _Handler.source = source
    _Handler.assets = assets
    _Handler.size = size
    _Handler.cache_ttl = cache_ttl
    return ThreadingHTTPServer((host, port), _Handler)
