"""Gamma API client: market/event discovery and metadata (read-only)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC
from typing import Any

from ..errors import DataError, NotFoundError
from ..http import HttpClient
from ..models import Market, Token, parse_jsonish_list

# Gamma caps page size; keep requests polite.
_MAX_PAGE = 100


class GammaClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")

    def get_market_by_slug(self, slug: str) -> Market:
        # The documented, stable way to look a market up is the ``slug`` filter
        # on the list endpoint rather than an undocumented path segment.
        rows = self._http.get_json(f"{self._base}/markets", {"slug": slug})
        rows = _as_list(rows)
        if not rows:
            raise NotFoundError(f"no market with slug {slug!r}")
        return self.parse_market(rows[0])

    def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        active: bool | None = True,
        closed: bool | None = False,
    ) -> list[Market]:
        params: dict[str, Any] = {
            "limit": max(1, min(limit, _MAX_PAGE)),
            "offset": max(0, offset),
        }
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        rows = _as_list(self._http.get_json(f"{self._base}/markets", params))
        out: list[Market] = []
        for row in rows:
            try:
                out.append(self.parse_market(row))
            except DataError:
                # A non-binary or malformed market should not abort the page.
                continue
        return out

    def iter_markets(
        self,
        *,
        max_markets: int = 500,
        active: bool | None = True,
        closed: bool | None = False,
        page_size: int = _MAX_PAGE,
    ) -> Iterator[Market]:
        """Paginate ``/markets`` up to ``max_markets`` normalized markets.

        Pagination stops on an empty page or a short page (fewer raw rows than
        requested) so a truncated result set is never silently extended.
        """
        yielded = 0
        offset = 0
        page = max(1, min(page_size, _MAX_PAGE))
        while yielded < max_markets:
            rows = _as_list(
                self._http.get_json(
                    f"{self._base}/markets",
                    {
                        "limit": page,
                        "offset": offset,
                        **({"active": str(active).lower()} if active is not None else {}),
                        **({"closed": str(closed).lower()} if closed is not None else {}),
                    },
                )
            )
            if not rows:
                return
            for row in rows:
                try:
                    market = self.parse_market(row)
                except DataError:
                    continue
                yield market
                yielded += 1
                if yielded >= max_markets:
                    return
            if len(rows) < page:
                return
            offset += len(rows)

    @staticmethod
    def parse_market(row: dict[str, Any]) -> Market:
        outcomes = parse_jsonish_list(row.get("outcomes"))
        token_ids = parse_jsonish_list(row.get("clobTokenIds"))
        if not outcomes or not token_ids or len(outcomes) != len(token_ids):
            raise DataError("market is missing aligned outcomes/token ids")
        tokens = tuple(Token(token_id=token_ids[i], outcome=outcomes[i]) for i in range(len(outcomes)))
        tags = row.get("tags")
        tag_tuple: tuple[str, ...] = ()
        if isinstance(tags, list):
            tag_tuple = tuple(str(t.get("label")) if isinstance(t, dict) else str(t) for t in tags)
        end_date = row.get("endDate") or row.get("endDateIso")
        return Market(
            slug=str(row.get("slug") or ""),
            question=str(row.get("question") or row.get("title") or ""),
            condition_id=str(row.get("conditionId") or ""),
            tokens=tokens,
            active=bool(row.get("active", True)),
            closed=bool(row.get("closed", False)),
            accepting_orders=bool(row.get("acceptingOrders", row.get("enableOrderBook", True))),
            category=str(row["category"]) if row.get("category") else None,
            tags=tag_tuple,
            end_date=_parse_end_date(end_date),
        )


def _parse_end_date(value: Any) -> int | None:
    if not value:
        return None
    from datetime import datetime

    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=UTC).timestamp())
        except ValueError:
            continue
    return None


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # Some responses wrap rows under a "data" key.
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return [payload]
    return []
