"""Geoblock status client: informational availability check only.

This never returns, suggests, or performs any circumvention. It reports the
official status so downstream code can note that real trading is unavailable
while still permitting read-only research and paper trading.
"""

from __future__ import annotations

from typing import Any

from ..http import HttpClient
from ..models import GeoStatus


class GeoblockClient:
    def __init__(self, http: HttpClient, url: str) -> None:
        self._http = http
        self._url = url

    def get_status(self) -> GeoStatus:
        payload = self._http.get_json(self._url)
        if not isinstance(payload, dict):
            return GeoStatus(blocked=None, country=None, region=None, raw={})
        return GeoStatus(
            blocked=_parse_blocked(payload),
            country=_first_str(payload, ("country", "countryCode", "cc")),
            region=_first_str(payload, ("region", "regionName", "state")),
            raw=payload,
        )


def _parse_blocked(payload: dict[str, Any]) -> bool | None:
    for key in ("blocked", "isBlocked", "restricted", "geoBlocked"):
        if key in payload and payload[key] is not None:
            return bool(payload[key])
    # Some responses phrase it positively, e.g. {"allowed": true}.
    for key in ("allowed", "isAllowed"):
        if key in payload and payload[key] is not None:
            return not bool(payload[key])
    return None


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return None
