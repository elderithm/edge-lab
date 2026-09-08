"""Data API client: public user activity/trades/positions (read-only)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..http import HttpClient
from ..models import WalletActivity

_MAX_PAGE = 500


class DataClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")

    def get_activity(
        self,
        user: str,
        *,
        limit: int = _MAX_PAGE,
        offset: int = 0,
        activity_type: str | None = "TRADE",
        start: int | None = None,
        end: int | None = None,
    ) -> list[WalletActivity]:
        params: dict[str, Any] = {
            "user": user,
            "limit": max(1, min(limit, _MAX_PAGE)),
            "offset": max(0, offset),
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        }
        if activity_type:
            params["type"] = activity_type
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        rows = _as_list(self._http.get_json(f"{self._base}/activity", params))
        return [WalletActivity.from_api(row) for row in rows]

    def iter_activity(
        self,
        user: str,
        *,
        max_records: int = 5000,
        activity_type: str | None = "TRADE",
    ) -> Iterator[WalletActivity]:
        """Paginate activity newest-first up to ``max_records``.

        Stops on an empty or short page so partial retrieval is explicit rather
        than silently padded.
        """
        yielded = 0
        offset = 0
        while yielded < max_records:
            page = min(_MAX_PAGE, max_records - yielded)
            rows = self.get_activity(user, limit=page, offset=offset, activity_type=activity_type)
            if not rows:
                return
            for row in rows:
                yield row
                yielded += 1
                if yielded >= max_records:
                    return
            if len(rows) < page:
                return
            offset += len(rows)

    def get_positions(self, user: str, *, limit: int = _MAX_PAGE) -> list[dict[str, Any]]:
        """Return raw public position rows; shape is left to the caller.

        Kept as raw dicts because the positions payload is only used for
        best-effort performance reconstruction, which must not fabricate fields.
        """
        rows = self._http.get_json(
            f"{self._base}/positions",
            {"user": user, "limit": max(1, min(limit, _MAX_PAGE))},
        )
        return _as_list(rows)


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []
