"""JSON endpoints for the dashboard's Perps view (read-only + unsigned preview).

There is deliberately no execution endpoint: testnet submission stays in the CLI
behind the risk engine and an explicit ``--yes``.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import EdgeLabError
from ..paper.perps_paper import DEFAULT_PATH, PerpsPaperDB
from ..perps.service import build_preview, inspect, scan
from ..venues.dreamdex_perps.adapter import PerpsAdapter
from ..venues.dreamdex_perps.config import PerpsConfig
from ..venues.dreamdex_perps.fixtures import FixturePerpsVenue
from ..venues.dreamdex_perps.models import PerpSide


class PerpsApi:
    def __init__(self, source: str, db_path: str = DEFAULT_PATH) -> None:
        self.source = source
        self.db_path = db_path
        self.config = PerpsConfig.from_env()

    def _venue(self, now: int) -> Any:
        return FixturePerpsVenue(now) if self.source == "fixture" else PerpsAdapter(self.config)

    def handle(self, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
        q = {k: v[0] for k, v in query.items() if v}
        now = int(time.time())
        if path == "/api/perps/scan":
            res = scan(self._venue(now), now)
            return {**res, "assessments": [a.to_dict() for a in res["assessments"]]}
        if path == "/api/perps/inspect":
            if not q.get("market"):
                return {"error": "market required"}
            a = inspect(self._venue(now), q["market"], now)
            d = a.to_dict()
            book = a.snapshot.book
            d["order_book"] = {
                "bids": [[str(lv.price), str(lv.quantity)] for lv in book.bids[:10]],
                "asks": [[str(lv.price), str(lv.quantity)] for lv in book.asks[:10]],
                "block_number": book.block_number,
            }
            return d
        if path == "/api/perps/preview":
            return self._preview(q, now)
        if path == "/api/perps/paper":
            return self._paper()
        return {"error": "not found"}

    def _preview(self, q: dict[str, str], now: int) -> dict[str, Any]:
        side = (q.get("side") or "").upper()
        if side not in ("LONG", "SHORT"):
            return {"error": "side must be long or short"}
        try:
            size = Decimal(q.get("size") or "")
        except InvalidOperation:
            return {"error": "size must be a decimal number"}
        if not q.get("market"):
            return {"error": "market required"}
        out = build_preview(
            self._venue(now),
            q["market"],
            PerpSide(side),
            size,
            now,
            config=self.config,
            db_path=self.db_path,
            account=q.get("account") or None,
        )
        return {
            **out,
            "paper": out["paper"].to_dict(),
            "testnet": out["testnet"].to_dict() if out["testnet"] else None,
            "execution_note": "Dashboard never submits. Use `edge-lab perps execute ... --yes` on testnet.",
        }

    def _paper(self) -> dict[str, Any]:
        try:
            with PerpsPaperDB(self.db_path) as db:
                positions = db.list_positions()
                orders = db.list_testnet_orders()
                open_ids = sorted({p.market_id for p in positions if p.status == "open"})
                marks: dict[str, tuple[Decimal | None, int | None]] = {}
                if open_ids:
                    snaps, _ = self._venue(int(time.time())).snapshots(open_ids)
                    marks = {
                        s.market.market_id: (s.state.mark_price, s.state.projected_cumulative_funding_raw)
                        for s in snaps
                    }
                summary = db.summary(marks)
        except EdgeLabError as exc:
            return {"error": str(exc)}
        return {
            "summary": summary,
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "quantity": str(p.quantity),
                    "entry_price": str(p.entry_price),
                    "mark": None if marks.get(p.market_id, (None,))[0] is None else str(marks[p.market_id][0]),
                    "unrealized_pnl": None
                    if p.status != "open" or p.unrealized(marks.get(p.market_id, (None, None))[0]) is None
                    else str(p.unrealized(marks[p.market_id][0])),
                    "realized_pnl": None if p.realized_pnl is None else str(p.realized_pnl),
                    "status": p.status,
                    "price_source": p.price_source,
                }
                for p in positions
            ],
            "testnet_orders": orders,
        }
